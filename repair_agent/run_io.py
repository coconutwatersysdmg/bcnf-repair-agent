"""Atomic manifests and OS-released single-writer run locks."""
import json
import os
import tempfile
from pathlib import Path

def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle:
            json.dump(obj,handle,ensure_ascii=False,indent=2,allow_nan=False);handle.flush();os.fsync(handle.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def read_jsonl(path,repair_tail=False):
    path=Path(path)
    if not path.exists():return []
    data=path.read_bytes();lines=data.splitlines(keepends=True);rows=[];offset=0
    for index,line in enumerate(lines):
        try:row=json.loads(line)
        except (ValueError,UnicodeError):
            if repair_tail and index==len(lines)-1 and not line.endswith(b'\n'):
                backup=path.with_suffix(path.suffix+'.incomplete-tail')
                if not backup.exists():backup.write_bytes(line)
                with path.open('r+b') as handle:handle.truncate(offset)
                break
            raise ValueError('invalid JSONL record at line '+str(index+1)) from None
        rows.append(row);offset+=len(line)
    return rows

def append_jsonl(path,obj):
    with Path(path).open('a+b') as handle:
        handle.seek(0,os.SEEK_END)
        if handle.tell():
            handle.seek(-1,os.SEEK_END)
            if handle.read(1)!=b'\n':handle.write(b'\n')
        handle.write((json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode('utf-8'))
        handle.flush();os.fsync(handle.fileno())

class RunLock:
    def __init__(self,path):self.path=Path(path)
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=self.path.open('a+b')
        if self.path.stat().st_size==0:self.handle.write(b'0');self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close();raise RuntimeError('run directory is already in use') from None
        return self
    def __exit__(self,*args):
        if os.name=='nt':
            import msvcrt
            self.handle.seek(0);msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.handle,fcntl.LOCK_UN)
        self.handle.close()
