import os
from pathlib import Path
import fcntl
class SingleProcessLock:
    def __init__(self,path): self.path=Path(path); self.handle=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True); self.handle=self.path.open("w")
        try: fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError("another agent process already holds the lock") from exc
        self.handle.write(str(os.getpid())); self.handle.flush(); return self
    def __exit__(self,exc_type,exc,tb):
        if self.handle: fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN); self.handle.close()
