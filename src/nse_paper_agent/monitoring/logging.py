from __future__ import annotations
import json,logging,os,sys
from logging.handlers import RotatingFileHandler
from datetime import datetime,timezone
class JsonFormatter(logging.Formatter):
    def format(self,record):
        payload={"ts_utc":datetime.now(timezone.utc).isoformat(),"level":record.levelname,"logger":record.name,"message":record.getMessage()}; extra=getattr(record,"event",None)
        if isinstance(extra,dict): payload.update(extra)
        return json.dumps(payload,default=str,separators=(",",":"))
def configure_logging(directory,level,max_bytes,backup_count):
    os.makedirs(directory,exist_ok=True); root=logging.getLogger(); root.handlers.clear(); root.setLevel(getattr(logging,level.upper())); formatter=JsonFormatter(); fh=RotatingFileHandler(os.path.join(directory,"agent.jsonl"),maxBytes=max_bytes,backupCount=backup_count); sh=logging.StreamHandler(sys.stdout); fh.setFormatter(formatter); sh.setFormatter(formatter); root.addHandler(fh); root.addHandler(sh)
def event(logger,level,message,**fields): logger.log(level,message,extra={"event":fields})
