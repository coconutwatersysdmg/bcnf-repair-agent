"""Offline bounded exhaustive validation; no model calls and no truth labels."""
from pathlib import Path
import sys, itertools, random, json, csv, hashlib
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT if (ROOT/'repair_agent/checker.py').exists() else ROOT / 'repair_agent_experiment/.worktrees/experiment-pilot-20261021'
sys.path.insert(0, str(REPO))
from repair_agent.legacy import _api, verify_snapshot
from repair_agent.checker import decision
from repair_agent.domain import is_bcnf


def run():
    assert verify_snapshot()['ok']
    types, mod, inc = _api()
    from algorithms.fd_hash import is_subset_repair_fd_hash
    families = [
        ('single', ('A','B','C'), [(('A',),('B','C'))]),
        ('dual', ('A','B','C'), [(('A',),('B','C')), (('B',),('A','C'))]),
        ('composite', ('A','B','C','D'), [(('A','B'),('C','D'))]),
        ('redundant_lhs', ('A','B','C'), [(('A',),('B','C')), (('A','B'),('C',))]),
        ('cycle', ('A','B','C'), [(('A',),('B',)), (('B',),('C',)), (('C',),('A',))]),
        ('trivial_only', ('A','B','C'), [(('A',),('A',))]),
        ('empty_key', ('A','B','C'), [((),('A','B','C'))]),
    ]
    counts=Counter(); by_family={}; records=[]
    for name, attrs, fds in families:
        family_counts=Counter()
        schema=types.RelationSchema(attributes=attrs,fds=tuple(types.FD(lhs,rhs) for lhs,rhs in fds),name=name)
        positions={a:i for i,a in enumerate(attrs)}
        projected=[(tuple(positions[a] for a in lhs),tuple(positions[a] for a in rhs)) for lhs,rhs in fds]
        for seed in range(5):
            rows=random.Random(2026102900+seed).sample(list(itertools.product(range(3),repeat=len(attrs))),7)
            task={'schema':{'name':name,'attributes':list(attrs),'fds':[{'lhs':list(lhs),'rhs':list(rhs)} for lhs,rhs in fds]},
                  'records':[{'id':str(i),'values':list(row)} for i,row in enumerate(rows)]}
            assert is_bcnf(task['schema'])
            # Direct pairwise FD semantics; enumerate ALL supersets for maximality.
            consistent={}
            for mask in range(1<<len(rows)):
                chosen=[rows[i] for i in range(len(rows)) if mask>>i&1]
                consistent[mask]=all(
                    not all(a[j]==b[j] for j in lhs) or all(a[j]==b[j] for j in rhs)
                    for a,b in itertools.combinations(chosen,2) for lhs,rhs in projected)
            for mask, ok in consistent.items():
                repair=ok and not any(other!=mask and other&mask==mask and value for other,value in consistent.items())
                expected=(ok,repair)
                retained=[rows[i] for i in range(len(rows)) if mask>>i&1]
                ids=[str(i) for i in range(len(rows)) if mask>>i&1]
                indexed=mod.BCNFRepairChecker(schema).check(rows,retained)
                hashed=is_subset_repair_fd_hash(schema,rows,retained)
                generic=decision(task,ids)
                state=inc.BCNFRepairState(schema,rows,retained)
                verdicts=[(indexed.candidate_consistent,indexed.is_repair),
                          (hashed.candidate_consistent,hashed.is_repair),
                          (generic['consistent'],generic['is_repair']),
                          (state.candidate_consistent(),state.is_repair())]
                assert all(v==expected for v in verdicts), (name,seed,mask,expected,verdicts)
                label='repair' if repair else 'consistent_nonmaximal' if ok else 'inconsistent'
                family_counts[label]+=1; counts[label]+=1
                records.append(dict(family=name,seed=seed,candidate_mask=mask,category=label,all_backends_match=True))
        by_family[name]=dict(family_counts)
    out=REPO/'results/audits/jcrd_checker_exhaustive_20261029'
    out.mkdir(parents=True,exist_ok=True)
    raw=out/'candidate_validation.csv'
    with raw.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    summary=dict(date='2026-10-29',protocol='7 schema families x 5 deterministic seeds x all 128 subsets of 7 rows',
        reference='Direct tuple-pair FD checking and exhaustive strict-superset enumeration',
        independent_candidates=len(records),categories=dict(counts),by_family=by_family,
        backends=['BCNF index','FD hash','generic checker','incremental initialization'],
        all_match=True,scope='Bounded exhaustive check; not an unbounded proof or timing benchmark',
        csv_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
