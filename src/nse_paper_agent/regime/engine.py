from __future__ import annotations

import math
from datetime import datetime

from nse_paper_agent.domain.models import Regime, RegimeSnapshot


class RegimeEngine:
    """Deterministic market-regime classifier.

    Missing or invalid market-intelligence inputs are fail-closed as
    DATA_DEGRADED. The engine never invents a market regime from absent data.
    """

    def classify(
        self,
        ts: datetime,
        benchmark_close: float | None,
        sma20: float | None,
        sma50: float | None,
        breadth20: float | None,
        vol_percentile: float | None,
        vol_shock: bool | None,
        data_healthy: bool,
    ) -> RegimeSnapshot:
        metrics = {
            name: float(value)
            for name, value in (
                ("benchmark_close", benchmark_close),
                ("sma20", sma20),
                ("sma50", sma50),
                ("breadth20", breadth20),
                ("vol_percentile", vol_percentile),
            )
            if value is not None
        }
        metrics["vol_shock"] = float(bool(vol_shock)) if vol_shock is not None else 0.0
        metrics["data_healthy"] = float(data_healthy)

        if not data_healthy:
            return RegimeSnapshot(ts, Regime.DATA_DEGRADED, metrics, "data_health_failure")

        required = (benchmark_close, sma20, sma50, breadth20, vol_percentile, vol_shock)
        if any(value is None for value in required):
            return RegimeSnapshot(ts, Regime.DATA_DEGRADED, metrics, "market_intelligence_unavailable")

        numeric = (benchmark_close, sma20, sma50, breadth20, vol_percentile)
        if not all(math.isfinite(float(value)) for value in numeric):
            return RegimeSnapshot(ts, Regime.DATA_DEGRADED, metrics, "market_intelligence_invalid")

        if benchmark_close <= 0 or sma20 <= 0 or sma50 <= 0:
            return RegimeSnapshot(ts, Regime.DATA_DEGRADED, metrics, "non_positive_market_price")

        if not 0.0 <= breadth20 <= 1.0:
            return RegimeSnapshot(ts, Regime.DATA_DEGRADED, metrics, "breadth_out_of_range")

        if not 0.0 <= vol_percentile <= 1.0:
            return RegimeSnapshot(ts, Regime.DATA_DEGRADED, metrics, "volatility_percentile_out_of_range")

        if bool(vol_shock) or vol_percentile >= 0.95:
            return RegimeSnapshot(ts, Regime.RISK_OFF, metrics, "volatility_shock")

        if benchmark_close < sma20 and benchmark_close < sma50 and breadth20 < 0.35:
            return RegimeSnapshot(ts, Regime.RISK_OFF, metrics, "benchmark_and_breadth_weak")

        if benchmark_close >= sma20 >= sma50 and breadth20 >= 0.55 and vol_percentile < 0.80:
            return RegimeSnapshot(ts, Regime.RISK_ON, metrics, "trend_and_breadth_confirmed")

        if breadth20 < 0.45 or vol_percentile >= 0.80:
            return RegimeSnapshot(ts, Regime.CAUTIOUS, metrics, "mixed_trend_or_elevated_volatility")

        return RegimeSnapshot(ts, Regime.RANGE_BOUND, metrics, "no_confirmed_trend")
