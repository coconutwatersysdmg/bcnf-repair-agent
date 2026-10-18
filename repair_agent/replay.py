"""Replay exactly saved candidate trajectories; exclude model, generation and IO time."""
import csv
import json
import time
from pathlib import Path
from .checker import decision
from .data_builder import load_tasks
from .legacy import IncrementalSession
from .domain import is_bcnf
from .run_io import read_jsonl,write_json

def replay_run(path):
    path=Path(path);tasks={t['task_id']:t for t in load_tasks(path/'public_tasks.jsonl')};rows=[];skipped=0
    for result in read_jsonl(path/'results.jsonl'):
        task=tasks[result['task_id']]
        if not is_bcnf(task['schema']):skipped+=1;continue
        tick=time.perf_counter();state=IncrementalSession(task);init=time.perf_counter()-tick
        trajectory=[entry['keep_ids'] for entry in result.get('trajectory',[]) if entry.get('keep_ids') is not None]
        if not trajectory and result.get('keep_ids') is not None:trajectory=[result['keep_ids']]
        for index,ids in enumerate(trajectory):
            tick=time.perf_counter();generic=decision(task,ids,'generic');generic_s=time.perf_counter()-tick
            tick=time.perf_counter();static=decision(task,ids,'bcnf');static_s=time.perf_counter()-tick
            inc=state.update(ids)
            if generic['is_repair']!=static['is_repair'] or static['is_repair']!=inc['is_repair'] or generic['consistent']!=inc['consistent']:
                raise RuntimeError('replay backends disagree')
            rows.append(dict(task_id=result['task_id'],arm=result['arm'],repeat=result['repeat'],step=index,
                generic_seconds=generic_s,bcnf_seconds=static_s,incremental_seconds=inc['seconds'],
                incremental_init_seconds=init if index==0 else 0,touched_block_entries=inc['touched_block_entries'],
                is_repair=inc['is_repair']))
    cols=['task_id','arm','repeat','step','generic_seconds','bcnf_seconds','incremental_seconds','incremental_init_seconds','touched_block_entries','is_repair']
    with (path/'replay.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=cols);writer.writeheader();writer.writerows(rows)
    summary=dict(checked_states=len(rows),all_backends_agree=True if rows else None,skipped_non_bcnf_results=skipped,
                 warning='Small simulated traces do not establish large-scale speedups. Static timing includes snapshot verification/adapter overhead.')
    write_json(path/'replay_summary.json',summary);return summary
