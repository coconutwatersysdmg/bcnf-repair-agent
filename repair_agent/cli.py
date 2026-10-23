"""All network use is behind run --mode live --live; defaults are offline."""
import argparse
import hashlib
import json
import os
import platform
import random
import sys
from pathlib import Path
from . import __version__
from .domain import canonical,task_hash
from .config import load_config,defaults
from .data_builder import generate_dataset,generate_paired_dataset,load_tasks
from .runner import run_case
from .policies import SimulatedClient
from .model_client import ModelClient
from .budget_cache import Store,units_for_tokens
from .feedback import ARMS
from .legacy import verify_snapshot
from .run_io import write_json,read_jsonl,append_jsonl,RunLock

def trailing_rate_limits(rows):
    streak=0
    for row in rows:
        status=row.get('status')
        if status=='HTTP_429':streak+=1
        elif status!='REQUEST_UNCERTAIN':streak=0
    return streak

def code_hash():
    root=Path(__file__).parent
    content={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))}
    content['vendor_snapshot']=verify_snapshot()
    content['vendor_manifest_sha256']=hashlib.sha256((root.parent/'vendor'/'snapshot.json').read_bytes()).hexdigest()
    return task_hash(content)

def run_experiment(data,out,config,mode='simulate',arms=None,repeats=1,live=False):
    if mode not in ('simulate','live'):raise ValueError('invalid run mode')
    if mode=='live' and not live:raise ValueError('live requests require explicit --live')
    arms=arms or ['D0','B0','B1','B2','B3']
    if not arms or len(set(arms))!=len(arms) or not set(arms)<=set(ARMS):raise ValueError('invalid arms')
    if type(repeats) is not int or not 1<=repeats<=100:raise ValueError('repeats must be 1..100')
    tasks=load_tasks(data)
    if not tasks:raise ValueError('empty experiment')
    if not verify_snapshot()['ok']:raise ValueError('legacy snapshot changed')
    out=Path(out)
    identity=dict(version=__version__,config=config,code_hash=code_hash(),task_hashes={t['task_id']:task_hash(t) for t in tasks},
                  arms=arms,repeats=repeats,result_mode='SIMULATED' if mode=='simulate' else 'LIVE',network_enabled=mode=='live')
    out.mkdir(parents=True,exist_ok=True)
    with RunLock(out/'run.lock'):
        manifest_path=out/'manifest.json'
        if manifest_path.exists():
            old=json.loads(manifest_path.read_text(encoding='utf-8'))
            if any(old.get(k)!=v for k,v in identity.items()):raise ValueError('run settings, code or data changed; use a new run directory')
        else:
            if (out/'results.jsonl').exists() or (out/'budget.sqlite3').exists():raise ValueError('orphan run data without manifest')
            write_json(manifest_path,dict(identity,python=platform.python_version()))
            (out/'public_tasks.jsonl').write_text(''.join(canonical(t)+'\n' for t in tasks),encoding='utf-8')
        stored=load_tasks(out/'public_tasks.jsonl')
        if {t['task_id']:task_hash(t) for t in stored}!=identity['task_hashes']:raise ValueError('frozen run tasks changed')
        previous=read_jsonl(out/'results.jsonl',repair_tail=True)
        keys=[(r['task_id'],r['arm'],r['repeat']) for r in previous]
        if len(keys)!=len(set(keys)):raise ValueError('duplicate completed run result')
        done=set(keys)
        rate_limit_streak=trailing_rate_limits(previous)
        halt_reason='CONSECUTIVE_HTTP_429' if rate_limit_streak>=3 else None
        with Store(out/'budget.sqlite3',config['budget_cny'],config['max_requests']) as book:
            client=SimulatedClient() if mode=='simulate' else ModelClient(config,book)
            for repeat in range(repeats):
                if halt_reason:break
                for task in tasks:
                    if halt_reason:break
                    ordered=arms[:];random.Random(task['task_id']+':'+str(repeat)).shuffle(ordered)
                    for arm in ordered:
                        if halt_reason:break
                        key=(task['task_id'],arm,repeat)
                        if key in done:continue
                        result=run_case(task,arm,client,config,repeat)
                        append_jsonl(out/'results.jsonl',result);done.add(key)
                        if result['status']=='HTTP_429':rate_limit_streak+=1
                        elif result['status']!='REQUEST_UNCERTAIN':rate_limit_streak=0
                        if rate_limit_streak>=3:halt_reason='CONSECUTIVE_HTTP_429'
            summary=dict(completed=len(done),expected=len(tasks)*len(arms)*repeats,mode=identity['result_mode'],ledger=book.summary())
            if halt_reason:summary['halt_reason']=halt_reason
            write_json(out/'run_summary.json',summary)
    return summary

def main(argv=None):
    parser=argparse.ArgumentParser(description='BCNF subset-repair experiments. Default execution is offline.')
    subs=parser.add_subparsers(dest='command',required=True)
    gen=subs.add_parser('generate');gen.add_argument('--out',required=True);gen.add_argument('--count',type=int,default=60)
    gen.add_argument('--entities',type=int,default=20);gen.add_argument('--seed',type=int,default=42);gen.add_argument('--split',default='dev')
    paired=subs.add_parser('generate-paired');paired.add_argument('--out',required=True);paired.add_argument('--pairs',type=int,default=90)
    paired.add_argument('--entities',type=int,default=8);paired.add_argument('--seed',type=int,default=2026102301);paired.add_argument('--split',default='test')
    run=subs.add_parser('run');run.add_argument('--data',required=True);run.add_argument('--out',required=True)
    run.add_argument('--config');run.add_argument('--mode',choices=['simulate','live'],default='simulate');run.add_argument('--live',action='store_true')
    run.add_argument('--arms',default='D0,B0,B1,B2,B3');run.add_argument('--repeats',type=int,default=1)
    ev=subs.add_parser('evaluate');ev.add_argument('--run',required=True);ev.add_argument('--truth',required=True)
    for command in ('analyze','replay','status'):
        sub=subs.add_parser(command);sub.add_argument('--run',required=True)
    est=subs.add_parser('estimate');est.add_argument('--config');est.add_argument('--tasks',type=int,default=100)
    est.add_argument('--repeats',type=int,default=3);est.add_argument('--input-tokens',type=int,default=5000);est.add_argument('--output-tokens',type=int,default=800)
    subs.add_parser('verify')
    smoke=subs.add_parser('smoke');smoke.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    if args.command=='generate':result=generate_dataset(args.out,args.count,args.seed,args.split,args.entities)
    elif args.command=='generate-paired':result=generate_paired_dataset(args.out,args.pairs,args.seed,args.split,args.entities)
    elif args.command=='run':result=run_experiment(args.data,args.out,load_config(args.config),args.mode,args.arms.split(','),args.repeats,args.live)
    elif args.command=='evaluate':
        from .evaluate import evaluate_run
        result={'evaluated':len(evaluate_run(args.run,args.truth))}
    elif args.command=='analyze':
        from .analyze import analyze_run
        result=analyze_run(args.run)
    elif args.command=='replay':
        from .replay import replay_run
        result=replay_run(args.run)
    elif args.command=='verify':
        result=verify_snapshot()
        if not result['ok']:raise ValueError('snapshot verification failed')
    elif args.command=='status':
        run_path=Path(args.run);c=json.loads((run_path/'manifest.json').read_text(encoding='utf-8'))['config']
        with Store(run_path/'budget.sqlite3',c['budget_cny'],c['max_requests']) as book:result=book.summary()
    elif args.command=='estimate':
        c=load_config(args.config)
        if min(args.tasks,args.repeats,args.input_tokens,args.output_tokens)<1:raise ValueError('estimate counts must be positive')
        calls=args.tasks*args.repeats*16
        cost=units_for_tokens(args.input_tokens*calls,args.output_tokens*calls,c['input_price_cny'],c['output_price_cny'])/1000000
        result=dict(model=c['model'],max_calls=calls,assumed_input_tokens=args.input_tokens,assumed_output_tokens=args.output_tokens,
                    estimated_cny=cost,with_20_percent_contingency=round(cost*1.2,6),price_checked_on=c['price_checked_on'],
                    note='Workload estimate, not a hard cap; applies to B0/B1/B2/B3. Extra arms add cost.')
    elif args.command=='smoke':
        from .evaluate import evaluate_run
        from .analyze import analyze_run
        from .replay import replay_run
        root=Path(args.out);data=root/'data';run=root/'run'
        if not data.exists():generate_dataset(data,30,42,'smoke',8)
        result=run_experiment(data/'public.jsonl',run,defaults(),'simulate',repeats=2)
        evaluate_run(run,data/'private_truth.jsonl');analyze_run(run);replay_run(run)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
