"""Gate a live confirmation run before a larger paid matrix is launched."""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from repair_agent.data_builder import load_tasks
from repair_agent.feedback import make_feedback


CONFIRM_ARMS=(
    'B0','B1','B2',
    'B3_192','B3_truncate_192','B3_random_192',
    'B3_384','B3_truncate_384','B3_random_384',
)


def audit(run_path,min_policy_differences=3):
    run=Path(run_path)
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    tasks={row['task_id']:row for row in load_tasks(run/'public_tasks.jsonl')}
    rows=[json.loads(line) for line in (run/'results.jsonl').read_text(encoding='utf-8').splitlines() if line]
    keys=[(row['task_id'],row['arm'],row['repeat']) for row in rows]
    expected=len(tasks)*len(manifest['arms'])*manifest['repeats']
    first=defaultdict(dict)
    failure_states={}
    for row in rows:
        trajectory=row.get('trajectory') or []
        if row['arm'] in CONFIRM_ARMS and trajectory and isinstance(trajectory[0].get('response'),str):
            first[(row['task_id'],row['repeat'])][row['arm']]=hashlib.sha256(
                trajectory[0]['response'].encode('utf-8')).hexdigest()
        for entry in trajectory:
            ids=entry.get('keep_ids')
            if entry.get('status')=='FAIL' and isinstance(ids,list):
                failure_states[(row['task_id'],row['repeat'],tuple(sorted(ids)))]=(tasks[row['task_id']],ids,row['repeat'])
    complete_first=0;first_mismatches=[];missing_first=[]
    expected_b=set(CONFIRM_ARMS)&set(manifest['arms'])
    expected_first=((task_id,repeat) for task_id in tasks for repeat in range(manifest['repeats']))
    for key in expected_first:
        arms=first.get(key,{})
        if set(arms)!=expected_b:missing_first.append(dict(task_id=key[0],repeat=key[1],present=sorted(arms)))
        elif len(set(arms.values()))!=1:first_mismatches.append(dict(task_id=key[0],repeat=key[1]))
        else:complete_first+=1
    over={192:0,384:0};policy_differences={192:0,384:0}
    for task,ids,repeat in failure_states.values():
        full=len(make_feedback(task,ids,'B2',1600,repeat).encode('utf-8'))
        for budget in (192,384):
            over[budget]+=int(full>budget)
            outputs={make_feedback(task,ids,f'{policy}_{budget}',1600,repeat)
                     for policy in ('B3','B3_truncate','B3_random')}
            policy_differences[budget]+=int(len(outputs)>1)
    n_states=len(failure_states)
    rates={str(budget):(over[budget]/n_states if n_states else 0.0) for budget in (192,384)}
    checks={
        'matrix_complete':len(rows)==expected,
        'no_duplicate_keys':len(keys)==len(set(keys)),
        'paired_first_responses':not first_mismatches and not missing_first and complete_first==len(tasks)*manifest['repeats'],
        'budget_192_binds':rates['192']>=.20,
        'budget_384_binds':rates['384']>=.05,
        'policy_outputs_diverge':sum(policy_differences.values())>=min_policy_differences,
        'no_truth_key_in_results':'true_ids' not in (run/'results.jsonl').read_text(encoding='utf-8'),
    }
    return dict(ok=all(checks.values()),completed=len(rows),expected=expected,checks=checks,
        complete_first_response_groups=complete_first,first_response_mismatches=first_mismatches,
        missing_first_response_groups=missing_first,unique_failure_states=n_states,
        over_budget_counts={str(k):v for k,v in over.items()},over_budget_rates=rates,
        policy_difference_counts={str(k):v for k,v in policy_differences.items()})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--min-policy-differences',type=int,default=3)
    args=parser.parse_args()
    result=audit(args.run,args.min_policy_differences)
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['ok'] else 3)


if __name__=='__main__':main()
