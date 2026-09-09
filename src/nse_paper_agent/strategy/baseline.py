from __future__ import annotations
from datetime import datetime,time
from nse_paper_agent.domain.models import Bar,Regime,Signal
from nse_paper_agent.indicators.technical import sma,rsi
class BaselineBreakoutStrategy:
    version="baseline-breakout-v1"
    def __init__(self,sma_period=20,rsi_period=14,entry_cutoff="14:45"): self.sma_period=sma_period; self.rsi_period=rsi_period; self.entry_cutoff=time.fromisoformat(entry_cutoff)
    def evaluate(self,bars:list[Bar],now:datetime,regime:Regime,sentiment_score:float|None,held:bool,cooldown:bool,liquid:bool,feed_healthy:bool)->Signal:
        if not bars: return Signal("",now,self.version,False,"no_bars")
        b=bars[-1]
        if held: return Signal(b.symbol,b.end,self.version,False,"already_held")
        if cooldown: return Signal(b.symbol,b.end,self.version,False,"stop_cooldown")
        if not feed_healthy: return Signal(b.symbol,b.end,self.version,False,"data_unhealthy")
        if now.time()>self.entry_cutoff: return Signal(b.symbol,b.end,self.version,False,"entry_cutoff")
        if regime in {Regime.RISK_OFF,Regime.DATA_DEGRADED,Regime.RANGE_BOUND}: return Signal(b.symbol,b.end,self.version,False,f"regime_{regime.value}")
        if not liquid: return Signal(b.symbol,b.end,self.version,False,"liquidity_filter")
        if len(bars)<self.sma_period+1: return Signal(b.symbol,b.end,self.version,False,"insufficient_bars")
        closes=[x.close for x in bars]; cur=sma(closes,self.sma_period); prev=sma(closes[:-1],self.sma_period); cur_rsi=rsi(closes,self.rsi_period)
        if cur is None or prev is None or cur_rsi is None: return Signal(b.symbol,b.end,self.version,False,"indicator_unavailable")
        if not (closes[-1]>cur and closes[-2]<=prev): return Signal(b.symbol,b.end,self.version,False,"no_sma_cross")
        if not (50<cur_rsi<70): return Signal(b.symbol,b.end,self.version,False,"rsi_filter",cur_rsi)
        if sentiment_score is not None and sentiment_score<0.10: return Signal(b.symbol,b.end,self.version,False,"sentiment_filter",sentiment_score)
        return Signal(b.symbol,b.end,self.version,True,"baseline_entry",cur_rsi,{"sma":float(cur),"rsi":cur_rsi})
