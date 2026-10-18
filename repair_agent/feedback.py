"""Deterministic structured counterexamples with an exact UTF-8 byte budget."""
import random
from .checker import diagnose
from .domain import canonical, task_hash

ARMS=('D0','D1','B0','B1','B2','B3','B3_truncate','B3_random')

def make_feedback(task, ids, arm, budget=1600, repeat=0):
    diag=diagnose(task,ids)
    if diag['is_repair']: return canonical({'status':'PASS'})
    if arm=='B1': return canonical({'status':'FAIL'})
    witnesses=diag['conflicts'][:] if not diag['consistent'] else [dict(kind='addable',ids=[i]) for i in diag['addable_ids']]
    envelope=dict(status='FAIL',witnesses=witnesses)
    if arm=='B2': return canonical(envelope)
    if arm not in ('B3','B3_truncate','B3_random'): raise ValueError('arm has no feedback policy')
    selected=[];envelope['witnesses']=selected
    if len(canonical(envelope).encode('utf-8'))>budget: raise ValueError('feedback budget too small for envelope')
    if arm=='B3_random':
        random.Random(task_hash({'task':task['task_id'],'repeat':repeat,'ids':sorted(ids)})).shuffle(witnesses)
    covered=set()
    while witnesses:
        if arm=='B3':
            witnesses.sort(key=lambda w:(-len(set(w['ids'])-covered),len(canonical(w).encode('utf-8')),canonical(w)))
        w=witnesses.pop(0)
        proposal=canonical(dict(status='FAIL',witnesses=selected+[w]))
        if len(proposal.encode('utf-8'))<=budget:
            selected.append(w);covered.update(w['ids'])
        elif arm=='B3_truncate': break
    return canonical(envelope)
