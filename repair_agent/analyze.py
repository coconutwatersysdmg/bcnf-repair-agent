"""Task-level summaries, paired cluster bootstrap, and dependency-free SVG output."""
from collections import defaultdict,Counter
import csv
import html
import json
import random
from pathlib import Path
from statistics import mean
from .run_io import write_json

def _pass(r):return float(r.get('is_repair',r['status']=='PASS'))

def _groups(rows,dimension=None):
    grouped=defaultdict(list)
    for row in rows:grouped[(row['mode'],row['arm'],row.get(dimension,'unknown') if dimension else 'all')].append(row)
    out=[]
    for (mode,arm,value),members in sorted(grouped.items(),key=lambda item:str(item[0])):
        per_task=defaultdict(list)
        for r in members:per_task[r['task_id']].append(r)
        out.append(dict(mode=mode,arm=arm,subset=value,n_tasks=len(per_task),n_results=len(members),
            pass_rate=mean(mean(_pass(r) for r in rs) for rs in per_task.values()),
            mean_f1=mean(mean(r.get('f1',0) for r in rs) for rs in per_task.values()),
            mean_calls=mean(r.get('rounds',0) for r in members),
            total_cost_cny=sum(r.get('billed_cny',0) for r in members),statuses=dict(Counter(r['status'] for r in members))))
    return out

def paired_bootstrap(rows,left,right,draws=2000):
    lookup={(r['task_id'],r['repeat'],r['arm']):r for r in rows}
    differences=defaultdict(list)
    for (tid,repeat,arm),row in lookup.items():
        other=lookup.get((tid,repeat,right))
        if arm==left and other and row['mode']==other['mode']:
            differences[row['base_instance_id']].append(_pass(row)-_pass(other))
    values=[mean(v) for _,v in sorted(differences.items())]
    if not values:return None
    rng=random.Random(20261018)
    means=sorted(mean(rng.choices(values,k=len(values))) for _ in range(draws))
    return dict(left=left,right=right,n_base_instances=len(values),difference=mean(values),
                ci95=[means[int(draws*.025)],means[min(draws-1,int(draws*.975))]],
                method='paired base-instance cluster bootstrap; repeats averaged within instance',draws=draws)

def analyze_rows(rows):
    modes=sorted({r['mode'] for r in rows})
    comparisons=[]
    for mode in modes:
        subset=[r for r in rows if r['mode']==mode]
        for left,right in [('B2','B1'),('B3','B3_truncate'),('B3','B3_random')]:
            comparison=paired_bootstrap(subset,left,right)
            if comparison:comparison['mode']=mode;comparisons.append(comparison)
    return dict(total_results=len(rows),modes=modes,groups=_groups(rows),
                by_family=_groups(rows,'family'),by_category=_groups(rows,'category'),by_track=_groups(rows,'track'),
                paired_comparisons=comparisons,
                warning='SIMULATED and SCRIPTED are plumbing checks, not evidence of LLM performance.' if any(m in modes for m in ('SIMULATED','SCRIPTED')) else '')

def analyze_run(path):
    path=Path(path)
    rows=json.loads((path/'evaluated.json').read_text(encoding='utf-8'))
    summary=analyze_rows(rows);write_json(path/'analysis.json',summary)
    cols=['mode','arm','n_tasks','n_results','pass_rate','mean_f1','mean_calls','total_cost_cny']
    with (path/'summary.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(summary['groups'])
    groups=summary['groups'];height=100+len(groups)*45
    title=' / '.join(summary['modes'])+' - formal repair rate (not truth accuracy)'
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="950" height="{height}" viewBox="0 0 950 {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="20" y="28" font-size="17" font-family="sans-serif">{html.escape(title)}</text>']
    for i,r in enumerate(groups):
        y=65+i*45;width=550*r['pass_rate'];label=f"{r['mode']} {r['arm']}"
        parts.extend([f'<text x="20" y="{y+17}" font-size="12" font-family="sans-serif">{html.escape(label)}</text>',
                      f'<rect x="240" y="{y}" width="{width:.2f}" height="25" fill="#315a80"/>',
                      f'<text x="800" y="{y+17}" font-size="13">{r["pass_rate"]:.1%}</text>'])
    parts.append('</svg>');(path/'comparison.svg').write_text('\n'.join(parts),encoding='utf-8')
    return summary
