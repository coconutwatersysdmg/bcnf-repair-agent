"""Strict public-task and candidate boundaries; hidden truth is never accepted here."""
import hashlib
import json
import re

TASK_FIELDS={'task_id','base_instance_id','split','schema','records','initial_keep_ids','source_evidence','category','family','track'}

def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def task_hash(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()

def validate_ids(ids, task):
    known={r['id'] for r in task['records']}
    if not isinstance(ids,list) or any(type(i) is not str for i in ids):
        raise ValueError('keep_ids must be a list of strings')
    if len(ids)!=len(set(ids)) or not set(ids)<=known:
        raise ValueError('duplicate or unknown row id')
    return ids

def validate_task(t):
    if not isinstance(t,dict) or set(t)-TASK_FIELDS:
        raise ValueError('unexpected public task field')
    if not {'task_id','base_instance_id','split','schema','records','initial_keep_ids','source_evidence'}<=set(t):
        raise ValueError('missing public task field')
    for field in ('task_id','base_instance_id','split'):
        if not isinstance(t[field],str) or not t[field]: raise ValueError('invalid '+field)
    schema=t['schema']
    if not isinstance(schema,dict) or set(schema)!={'name','attributes','fds'}: raise ValueError('invalid schema fields')
    attrs=schema['attributes']
    if not isinstance(attrs,list) or not attrs or any(type(a) is not str for a in attrs) or len(set(attrs))!=len(attrs):
        raise ValueError('invalid attributes')
    if not isinstance(schema['fds'],list): raise ValueError('invalid fds')
    for fd in schema['fds']:
        if not isinstance(fd,dict) or set(fd)!={'lhs','rhs'}: raise ValueError('invalid fd')
        for side in ('lhs','rhs'):
            seq=fd[side]
            if not isinstance(seq,list) or any(type(a) is not str for a in seq) or len(seq)!=len(set(seq)) or not set(seq)<=set(attrs):
                raise ValueError('invalid fd attributes')
    if not isinstance(t['records'],list): raise ValueError('invalid records')
    ids=[]; rows=[]
    for rec in t['records']:
        if not isinstance(rec,dict) or set(rec)!={'id','values'} or type(rec['id']) is not str: raise ValueError('invalid record')
        values=rec['values']
        if not isinstance(values,list) or len(values)!=len(attrs) or any(type(v) is not str for v in values):
            raise ValueError('values must be non-null strings with schema width')
        ids.append(rec['id']);rows.append(tuple(values))
    if len(ids)!=len(set(ids)) or len(rows)!=len(set(rows)): raise ValueError('duplicate ids or tuples')
    validate_ids(t['initial_keep_ids'],t)
    evidence=t['source_evidence']
    if not isinstance(evidence,dict) or not set(evidence)<=set(ids): raise ValueError('invalid evidence ids')
    for info in evidence.values():
        if not isinstance(info,dict) or set(info)!={'source','score'}: raise ValueError('invalid source evidence fields')
        if type(info['source']) is not str or type(info['score']) not in (int,float) or not 0<=info['score']<=1:
            raise ValueError('invalid evidence score')
    return t

def parse_candidate(text, task):
    if not isinstance(text,str): raise ValueError('candidate must be text')
    text=text.strip()
    fenced=re.fullmatch(r'```json[ \t]*\r?\n(.*)\r?\n```',text,flags=re.IGNORECASE|re.DOTALL)
    if fenced: text=fenced.group(1)
    obj=json.loads(text)
    if not isinstance(obj,dict) or set(obj)!={'keep_ids'}: raise ValueError('expected only keep_ids')
    return validate_ids(obj['keep_ids'],task)

def is_bcnf(schema):
    attrs=set(schema['attributes'])
    for fd in schema['fds']:
        if set(fd['rhs'])<=set(fd['lhs']): continue
        closure=set(fd['lhs']); changed=True
        while changed:
            before=set(closure)
            for dep in schema['fds']:
                if set(dep['lhs'])<=closure: closure.update(dep['rhs'])
            changed=closure!=before
        if closure!=attrs: return False
    return True
