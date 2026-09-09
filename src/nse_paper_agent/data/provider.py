from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol
import csv
from nse_paper_agent.domain.models import Bar, Quote
class MarketDataProvider(Protocol):
    def connect(self)->None: ...
    def disconnect(self)->None: ...
    def healthy(self,now:datetime)->tuple[bool,str]: ...
    def latest_quotes(self,symbols:Iterable[str])->dict[str,Quote]: ...
    def completed_bars(self,symbol:str,interval_minutes:int,end:datetime)->list[Bar]: ...
class ReplayProvider:
    def __init__(self,bars:list[Bar],quotes:dict[str,list[Quote]]): self.bars=bars; self.quotes=quotes; self._connected=False
    def connect(self): self._connected=True
    def disconnect(self): self._connected=False
    def healthy(self,now): return self._connected,"replay_connected" if self._connected else "disconnected"
    def latest_quotes(self,symbols): return {s:self.quotes[s][-1] for s in symbols if self.quotes.get(s)}
    def completed_bars(self,symbol,interval_minutes,end): return [b for b in self.bars if b.symbol==symbol and b.end<=end]
def load_bars_csv(path:str)->list[Bar]:
    out=[]
    with open(path,newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(Bar(r["symbol"],datetime.fromisoformat(r["start"]),datetime.fromisoformat(r["end"]),Decimal(r["open"]),Decimal(r["high"]),Decimal(r["low"]),Decimal(r["close"]),Decimal(r["volume"])))
    return sorted(out,key=lambda x:(x.symbol,x.end))
class LiveMarketDataAdapterPlaceholder:
    def __init__(self,provider_name:str): self.provider_name=provider_name
    def connect(self): raise RuntimeError("live data adapter is a deployment-specific placeholder; implement only market-data ingestion")
    def disconnect(self): return
    def healthy(self,now): return False,"live_adapter_not_configured"
    def latest_quotes(self,symbols): raise RuntimeError("live data adapter not configured")
    def completed_bars(self,symbol,interval_minutes,end): raise RuntimeError("live data adapter not configured")
