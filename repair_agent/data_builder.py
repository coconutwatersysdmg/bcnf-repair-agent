"""Frozen synthetic data; public files and private evaluation truth are separate."""
import hashlib
import itertools
import json
import random
from pathlib import Path
from .domain import canonical, validate_task, task_hash
from .checker import greedy_repair

CATEGORIES=('clean','residual','over_deletion','mixed','ambiguous')
FAMILIES=('single','dual','composite')

def load_tasks(path):
    tasks=[validate_task(json.loads(line)) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    ids=[t['task_id'] for t in tasks]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate task IDs')
    return tasks

def generate_dataset(path,count=60,seed=42,split='dev',entities=20):
    path=Path(path)
    if type(count) is not int or count<1 or type(entities) is not int or entities<4: raise ValueError('invalid count/entities')
    if not isinstance(split,str) or not split or split not in ('dev','pilot','test','smoke'): raise ValueError('invalid split')
    if path.exists(): raise FileExistsError('dataset directory already exists; choose a new path')
    path.mkdir(parents=True)
    public=[];private=[]
    cells=list(itertools.product(FAMILIES,CATEGORIES,('C0','C1')))
    for index in range(count):
        family,category,track=cells[index%len(cells)]
        base=hashlib.sha256(f'{split}:{seed}:{index}'.encode()).hexdigest()[:20]
        rng=random.Random(base)
        attrs=['person_id','email','name','department']
        if family=='composite': attrs.append('course_id')
        keys=[['person_id']]
        if family in ('dual','composite'): keys.append(['email'])
        if family=='composite': keys=[k+['course_id'] for k in keys]
        schema=dict(name='R_'+base[:6],attributes=attrs,fds=[dict(lhs=k,rhs=attrs[:]) for k in keys])
        clean=[]
        # No source, row identifier, or record ordering encodes the truth label.
        domain=rng.choice(['campus','library','lab','sports'])
        for n in range(entities):
            row=[f'p{n}',f'{n}@{domain}.example',f'name_{rng.randrange(100000)}',f'd{rng.randrange(4)}']
            if family=='composite': row.append(f'c{n%3}')
            clean.append(row)
        dirty=[]
        if category!='clean':
            fraction=(.05,.15,.30)[index//len(cells)%3]
            for n in range(max(1,int(entities*fraction))):
                row=clean[n][:]
                if family!='single' and n%2:
                    row[0]=f'external{n}'
                else: row[1]=f'alternative{n}@{domain}.example'
                row[2]=f'other_name_{rng.randrange(100000)}'
                dirty.append(row)
            if family!='single' and category=='ambiguous':
                row=clean[0][:];row[1]=clean[3][1];row[2]='alternate_observation'
                dirty.append(row)
        # Independent random bijections per attribute preserve equality/FD structure
        # while removing spelling, ordinal and dirty-only prefix clues to truth.
        for col in range(len(attrs)):
            values=sorted({row[col] for row in clean+dirty})
            tokens=set()
            while len(tokens)<len(values):tokens.add(f'v{rng.getrandbits(64):016x}')
            tokens=sorted(tokens);rng.shuffle(tokens)
            mapping=dict(zip(values,tokens))
            for row in clean+dirty:row[col]=mapping[row[col]]
        labeled=[(row,True) for row in clean]+[(row,False) for row in dirty]
        rng.shuffle(labeled);records=[];true_ids=[];evidence={}
        for row,truth in labeled:
            rid=f'r{rng.getrandbits(64):016x}'
            records.append(dict(id=rid,values=row))
            if truth: true_ids.append(rid)
            if track=='C1':
                # Overlapping distributions deliberately allow misleading evidence.
                score=round(rng.uniform(.35,.95) if truth else rng.uniform(.20,.90),3)
                if category=='ambiguous': score=round(rng.uniform(.30,.90),3)
                evidence[rid]=dict(source=f'source_{rng.randrange(4)}',score=score)
        t=dict(task_id='t_'+base,base_instance_id=base,split=split,schema=schema,records=records,
               initial_keep_ids=[],source_evidence=evidence,category=category,family=family,track=track)
        if category=='clean': initial=true_ids[:]
        elif category=='over_deletion': initial=greedy_repair(t)[1:]
        elif category=='mixed':
            omitted=next(r['id'] for r in records if r['values']==clean[-1])
            initial=[r['id'] for r in records if r['id']!=omitted]
        else: initial=[r['id'] for r in records]
        t['initial_keep_ids']=sorted(initial);validate_task(t)
        public.append(t)
        private.append(dict(task_id=t['task_id'],base_instance_id=base,true_ids=sorted(true_ids),
                            task_hash=task_hash(t),injection_count=len(dirty)))
    for filename,records in [('public.jsonl',public),('private_truth.jsonl',private)]:
        (path/filename).write_text(''.join(canonical(r)+'\n' for r in records),encoding='utf-8')
    manifest=dict(version=2,seed=seed,split=split,count=count,entities=entities,
        cells=[dict(family=f,category=c,track=t,count=sum(x['family']==f and x['category']==c and x['track']==t for x in public)) for f,c,t in cells],
        hashes={name:hashlib.sha256((path/name).read_bytes()).hexdigest() for name in ('public.jsonl','private_truth.jsonl')})
    (path/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest
