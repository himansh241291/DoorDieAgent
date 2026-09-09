from __future__ import annotations
from collections import defaultdict
from nse_paper_agent.domain.models import Bar
class CompletedBarStore:
    def __init__(self): self._bars=defaultdict(list)
    def add(self,bar:Bar)->bool:
        if self._bars[bar.symbol] and bar.end<=self._bars[bar.symbol][-1].end: return False
        self._bars[bar.symbol].append(bar); return True
    def get(self,symbol:str,n:int|None=None):
        rows=self._bars.get(symbol,[]); return rows[-n:] if n else list(rows)
