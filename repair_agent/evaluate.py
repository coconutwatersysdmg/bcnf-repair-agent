"""Separate hidden-truth evaluation; this module never calls a model."""
import csv
import json
from pathlib import Path
from .checker import diagnose, decision
from .domain import task_hash, validate_ids
from .data_builder import load_tasks
from .run_io import read_jsonl, write_json

def evaluate_run(run,truth_path):
    run=Path(run);manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    tasks={t['task_id']:t for t in load_tasks(run/'public_tasks.jsonl')}
    truth_rows=read_jsonl(truth_path)
    truth={r['task_id']:r for r in truth_rows}
    if len(truth)!=len(truth_rows):raise ValueError('duplicate truth task id')
    for tid,t in tasks.items():
        if tid not in truth or truth[tid]['task_hash']!=task_hash(t):raise ValueError('truth does not match frozen public task')
        validate_ids(truth[tid]['true_ids'],t)
        if not decision(t,truth[tid]['true_ids'])['consistent']:raise ValueError('hidden truth is inconsistent')
    rows=read_jsonl(run/'results.jsonl');by_key={}
    for r in rows:
        key=(r['task_id'],r['arm'],r['repeat'])
        if key in by_key:raise ValueError('duplicate result')
        by_key[key]=r
    scored=[]
    expected={(tid,arm,repeat) for tid in tasks for arm in manifest['arms'] for repeat in range(manifest['repeats'])}
    if set(by_key)-expected:raise ValueError('result outside frozen experiment matrix')
    for tid,arm,repeat in sorted(expected):
        t=tasks[tid]
        r=dict(by_key.get((tid,arm,repeat),dict(task_id=tid,base_instance_id=t['base_instance_id'],
            task_hash=task_hash(t),arm=arm,repeat=repeat,mode='DETERMINISTIC' if arm.startswith('D') else manifest['result_mode'],
            status='MISSING_RESULT',keep_ids=None,category=t.get('category'),family=t.get('family'),track=t.get('track'),rounds=0,billed_cny=0)))
        if r['task_hash']!=task_hash(t):raise ValueError('result task hash differs')
        chosen=r.get('keep_ids');valid=True
        try:validate_ids(chosen,t)
        except ValueError:valid=False
        if valid:
            diag=diagnose(t,chosen);true=set(truth[tid]['true_ids']);kept=set(chosen);tp=len(kept&true)
            precision=tp/len(kept) if kept else 0.0
            recall=tp/len(true) if true else (1.0 if not kept else 0.0)
            if not true and not kept:precision=1.0
            r.update(consistent=diag['consistent'],is_repair=diag['is_repair'],conflict_pairs=len(diag['conflicts']),
                     addable_count=len(diag['addable_ids']) if diag['addable_ids'] is not None else None,
                     precision=precision,recall=recall,f1=2*precision*recall/(precision+recall) if precision+recall else 0)
        else:r.update(consistent=False,is_repair=False,conflict_pairs=None,addable_count=None,precision=0,recall=0,f1=0)
        r['pass_claim_mismatch']=r['status']=='PASS' and not r['is_repair']
        r.pop('trajectory',None);scored.append(r)
    write_json(run/'evaluated.json',scored)
    columns=['task_id','base_instance_id','mode','arm','repeat','category','family','track','status','is_repair','consistent',
             'precision','recall','f1','conflict_pairs','addable_count','rounds','billed_cny','network_attempts','elapsed_seconds','pass_claim_mismatch']
    with (run/'evaluated.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(scored)
    return scored
