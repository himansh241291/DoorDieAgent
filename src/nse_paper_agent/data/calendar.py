from __future__ import annotations
from datetime import date
from pathlib import Path
import yaml
class TradingCalendar:
    def __init__(self,path:str):
        raw=yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        self.holidays={date.fromisoformat(str(x)) for x in raw.get("holidays",[])}
    def is_trading_day(self,d:date)->bool: return d.weekday()<5 and d not in self.holidays
