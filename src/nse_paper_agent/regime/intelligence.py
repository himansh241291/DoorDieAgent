from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class MarketIntelligence:
    """Calculate deterministic daily features consumed by RegimeEngine."""

    benchmark_min_bars: int = 50
    volatility_window: int = 20
    volatility_history: int = 60
    breadth_window: int = 20
    breadth_min_symbols: int = 5

    @staticmethod
    def _closes(bars: list[Bar]) -> list[float]:
        return [float(bar.close) for bar in bars]

    @staticmethod
    def _sma(values: list[float], window: int) -> float | None:
        if len(values) < window:
            return None
        return mean(values[-window:])

    @staticmethod
    def _returns(closes: list[float]) -> list[float]:
        out: list[float] = []
        for previous, current in zip(closes, closes[1:]):
            if previous <= 0 or current <= 0 or not math.isfinite(previous) or not math.isfinite(current):
                return []
            out.append(current / previous - 1.0)
        return out

    @staticmethod
    def daily_bars(bars: list[Bar]) -> list[Bar]:
        ordered = sorted(bars, key=lambda bar: bar.end)
        groups: dict[date, list[Bar]] = {}
        for bar in ordered:
            groups.setdefault(bar.end.astimezone(IST).date(), []).append(bar)
        daily: list[Bar] = []
        for day_bars in groups.values():
            first, last = day_bars[0], day_bars[-1]
            daily.append(Bar(last.symbol,first.start,last.end,first.open,max(b.high for b in day_bars),min(b.low for b in day_bars),last.close,sum((b.volume for b in day_bars),Decimal("0"))))
        return daily

    def benchmark(self, bars: list[Bar]) -> dict[str, float | bool | None]:
        closes = self._closes(self.daily_bars(bars))
        valid = [value for value in closes if value > 0 and math.isfinite(value)]
        if len(closes) < self.benchmark_min_bars:
            return {"close": closes[-1] if closes else None,"sma20": self._sma(valid,20),"sma50": self._sma(valid,50),"vol_percentile": None,"vol_shock": None}

        sma20 = self._sma(valid,20); sma50 = self._sma(valid,50); returns = self._returns(closes)
        if not returns:
            return {"close": closes[-1],"sma20": sma20,"sma50": sma50,"vol_percentile": None,"vol_shock": None}

        realized: list[float] = []
        for end in range(self.volatility_window,len(returns)+1):
            window=returns[end-self.volatility_window:end]; avg=mean(window)
            realized.append(math.sqrt(mean((value-avg)**2 for value in window))*math.sqrt(252.0))
        percentile=None
        if len(realized)>=self.volatility_history:
            current=realized[-1]; history=realized[-self.volatility_history:]; percentile=sum(value<=current for value in history)/len(history)
        vol_shock=None
        if len(realized)>=2:
            previous=realized[-2]; vol_shock=previous>0 and realized[-1]>=previous*1.50
        return {"close": closes[-1],"sma20": sma20,"sma50": sma50,"vol_percentile": percentile,"vol_shock": vol_shock}

    def breadth(self,bars_by_symbol:dict[str,list[Bar]])->float|None:
        eligible=above=0
        for bars in bars_by_symbol.values():
            closes=self._closes(self.daily_bars(bars)); sma20=self._sma([v for v in closes if v>0 and math.isfinite(v)],self.breadth_window)
            if sma20 is None or not closes: continue
            eligible+=1; above+=closes[-1]>sma20
        if eligible<self.breadth_min_symbols: return None
        return above/eligible

    def calculate(self,benchmark_bars:list[Bar],bars_by_symbol:dict[str,list[Bar]])->dict[str,float|bool|None]:
        result=self.benchmark(benchmark_bars); result["breadth20"]=self.breadth(bars_by_symbol); return result