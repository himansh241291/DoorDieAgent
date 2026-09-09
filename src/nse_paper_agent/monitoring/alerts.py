from __future__ import annotations
import json,os,urllib.request
from typing import Protocol
class Notifier(Protocol):
    def send(self,payload:dict)->None: ...
class NullNotifier:
    def send(self,payload): return
class WebhookNotifier:
    def __init__(self,env_name): self.env_name=env_name
    def send(self,payload):
        url=os.environ.get(self.env_name,"").strip()
        if not url:return
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST"); urllib.request.urlopen(req,timeout=5).read()
