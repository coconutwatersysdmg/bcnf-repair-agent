"""Read-only adapter to a hash-verified snapshot of the author's prior algorithms."""
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path
from .domain import is_bcnf, validate_ids

ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/'vendor'/'legacy_bcnf'

def verify_snapshot():
    manifest=json.loads((ROOT/'vendor'/'snapshot.json').read_text(encoding='utf-8'))
    changed=[name for name,digest in manifest['files'].items()
             if not (VENDOR/name).is_file() or hashlib.sha256((VENDOR/name).read_bytes()).hexdigest()!=digest]
    return dict(ok=not changed,changed=changed)

def _api():
    if not verify_snapshot()['ok']: raise RuntimeError('legacy snapshot changed')
    for name in ('common','algorithms'):
        module=sys.modules.get(name)
        if module and (not getattr(module,'__file__',None) or VENDOR not in Path(module.__file__).resolve().parents):
            raise RuntimeError('legacy top-level module collision: '+name)
    path=str(VENDOR)
    if path not in sys.path: sys.path.insert(0,path)
    return (importlib.import_module('common.types'),importlib.import_module('algorithms.bcnf_index'),
            importlib.import_module('algorithms.incremental'))

def _convert(task):
    if not is_bcnf(task['schema']): raise ValueError('BCNF backend requires BCNF schema')
    types,checker,incremental=_api();schema=task['schema']
    rs=types.RelationSchema(attributes=tuple(schema['attributes']),
        fds=tuple(types.FD(tuple(fd['lhs']),tuple(fd['rhs'])) for fd in schema['fds']),name=schema['name'])
    rows={r['id']:tuple(r['values']) for r in task['records']}
    return rs,rows,checker,incremental

def legacy_decision(task, ids):
    rs,rows,checker,_=_convert(task)
    result=checker.BCNFRepairChecker(rs).check(list(rows.values()),[rows[i] for i in ids])
    return dict(consistent=result.candidate_consistent,is_repair=result.is_repair)

class IncrementalSession:
    def __init__(self,task):
        self.task=task;rs,self.rows,_,module=_convert(task)
        self.ids=set(task['initial_keep_ids'])
        self.state=module.BCNFRepairState(rs,list(self.rows.values()),[self.rows[i] for i in self.ids])

    def update(self, ids):
        validate_ids(ids,self.task);new=set(ids);self.state.reset_work_counters()
        start=time.perf_counter()
        for i in sorted(self.ids-new): self.state.move_retained_to_deleted(self.rows[i])
        for i in sorted(new-self.ids): self.state.move_deleted_to_retained(self.rows[i])
        self.ids=new
        return dict(consistent=self.state.candidate_consistent(),is_repair=self.state.is_repair(),
                    seconds=time.perf_counter()-start,touched_block_entries=self.state.touched_block_entries)
