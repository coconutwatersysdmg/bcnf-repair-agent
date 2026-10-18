"""Independent FD reference implementation and explicit diagnostic witnesses."""
from itertools import combinations
from .domain import validate_ids

def _fds(task):
    pos={a:i for i,a in enumerate(task['schema']['attributes'])}
    return [(fd,tuple(pos[a] for a in fd['lhs']),tuple(pos[a] for a in fd['rhs']))
            for fd in task['schema']['fds'] if not set(fd['rhs'])<=set(fd['lhs'])]

def _project(row, positions): return tuple(row[i] for i in positions)

def decision(task, ids, backend='generic'):
    validate_ids(ids,task)
    if backend=='bcnf':
        from .legacy import legacy_decision
        return legacy_decision(task,ids)
    if backend!='generic': raise ValueError('unknown backend')
    selected=set(ids); fds=_fds(task); indexes=[]
    for _,lhs,rhs in fds:
        index={}
        for rec in task['records']:
            if rec['id'] not in selected: continue
            x=_project(rec['values'],lhs);y=_project(rec['values'],rhs)
            if x in index and index[x]!=y: return dict(consistent=False,is_repair=False)
            index[x]=y
        indexes.append(index)
    for rec in task['records']:
        if rec['id'] in selected: continue
        if not any(_project(rec['values'],lhs) in idx and idx[_project(rec['values'],lhs)]!=_project(rec['values'],rhs)
                   for (_,lhs,rhs),idx in zip(fds,indexes)):
            return dict(consistent=True,is_repair=False)
    return dict(consistent=True,is_repair=True)

def diagnose(task, ids):
    validate_ids(ids,task)
    selected=set(ids); kept=[r for r in task['records'] if r['id'] in selected]; conflicts=[]
    fds=_fds(task)
    for fd,lhs,rhs in fds:
        blocks={}
        for rec in kept: blocks.setdefault(_project(rec['values'],lhs),[]).append(rec)
        for key,block in sorted(blocks.items()):
            for a,b in combinations(block,2):
                if _project(a['values'],rhs)!=_project(b['values'],rhs):
                    conflicts.append(dict(kind='conflict',ids=sorted([a['id'],b['id']]),fd=fd,lhs_values=list(key)))
    addable=[]
    if not conflicts:
        for rec in task['records']:
            if rec['id'] not in selected and decision(task,ids+[rec['id']])['consistent']: addable.append(rec['id'])
    return dict(consistent=not conflicts,is_repair=not conflicts and not addable,
                conflicts=conflicts,addable_ids=sorted(addable) if not conflicts else None)

def greedy_repair(task, order=None):
    evidence=task['source_evidence']
    if order is None:
        order=sorted([r['id'] for r in task['records']],key=lambda i:(-evidence.get(i,{}).get('score',0),i))
    validate_ids(order,task)
    if set(order)!={r['id'] for r in task['records']}: raise ValueError('greedy requires every row')
    result=[]
    for i in order:
        if decision(task,result+[i])['consistent']: result.append(i)
    return sorted(result)

def exhaustive_optimum(task, max_rows=18):
    ids=[r['id'] for r in task['records']]
    if len(ids)>max_rows: raise ValueError('exhaustive reference exceeds size cap')
    for size in range(len(ids),-1,-1):
        for candidate in combinations(ids,size):
            if decision(task,list(candidate))['consistent']:
                return dict(maximum_size=size,keep_ids=list(candidate))
