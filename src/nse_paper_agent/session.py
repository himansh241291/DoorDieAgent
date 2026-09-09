from datetime import time
from nse_paper_agent.data.calendar import TradingCalendar
class SessionGuard:
    def __init__(self,cfg):
        self.open=time.fromisoformat(cfg["session"]["open"]); self.close=time.fromisoformat(cfg["session"]["close"]); self.cutoff=time.fromisoformat(cfg["session"]["entry_cutoff"]); self.calendar=TradingCalendar(cfg["session"]["calendar_path"])
    def is_open(self,now):
        return self.calendar.is_trading_day(now.date()) and self.open<=now.time()<=self.close
    def entries_allowed(self,now): return self.is_open(now) and now.time()<=self.cutoff
