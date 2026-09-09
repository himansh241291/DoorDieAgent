from datetime import datetime
from nse_paper_agent.domain.models import Regime,RegimeSnapshot
class RegimeEngine:
    def classify(self,ts:datetime,benchmark_close:float,sma20:float,sma50:float,breadth20:float,vol_percentile:float,vol_shock:bool,data_healthy:bool)->RegimeSnapshot:
        m={"benchmark_close":benchmark_close,"sma20":sma20,"sma50":sma50,"breadth20":breadth20,"vol_percentile":vol_percentile,"vol_shock":float(vol_shock),"data_healthy":float(data_healthy)}
        if not data_healthy:return RegimeSnapshot(ts,Regime.DATA_DEGRADED,m,"data_health_failure")
        if vol_shock or vol_percentile>=.95:return RegimeSnapshot(ts,Regime.RISK_OFF,m,"volatility_shock")
        if benchmark_close<sma20 and benchmark_close<sma50 and breadth20<.35:return RegimeSnapshot(ts,Regime.RISK_OFF,m,"benchmark_and_breadth_weak")
        if benchmark_close>=sma20>=sma50 and breadth20>=.55 and vol_percentile<.80:return RegimeSnapshot(ts,Regime.RISK_ON,m,"trend_and_breadth_confirmed")
        if breadth20<.45 or vol_percentile>=.80:return RegimeSnapshot(ts,Regime.CAUTIOUS,m,"mixed_trend_or_elevated_volatility")
        return RegimeSnapshot(ts,Regime.RANGE_BOUND,m,"no_confirmed_trend")
