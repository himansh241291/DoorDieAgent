from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from nse_paper_agent.domain.models import Bar, Regime, Signal
from nse_paper_agent.indicators.technical import rsi, sma


class TrendPullbackStrategy:
    version = "trend-pullback-v1"

    def evaluate(
        self,
        bars: list[Bar],
        now: datetime,
        regime: Regime,
        sentiment_score: float | None,
        held: bool,
        cooldown: bool,
        liquid: bool,
        feed_healthy: bool,
    ) -> Signal:
        symbol = bars[-1].symbol if bars else ""
        if not bars:
            return Signal(symbol, now, self.version, False, "no_bars")
        if held:
            return Signal(symbol, bars[-1].end, self.version, False, "already_held")
        if cooldown:
            return Signal(symbol, bars[-1].end, self.version, False, "stop_cooldown")
        if not feed_healthy:
            return Signal(symbol, bars[-1].end, self.version, False, "data_unhealthy")
        if now.time() > time(14, 45):
            return Signal(symbol, bars[-1].end, self.version, False, "entry_cutoff")
        if regime in {Regime.RISK_OFF, Regime.DATA_DEGRADED, Regime.RANGE_BOUND}:
            return Signal(symbol, bars[-1].end, self.version, False, f"regime_{regime.value}")
        if not liquid:
            return Signal(symbol, bars[-1].end, self.version, False, "liquidity_filter")
        if len(bars) < 55:
            return Signal(symbol, bars[-1].end, self.version, False, "insufficient_bars")

        closes = [b.close for b in bars]
        sma20 = sma(closes, 20)
        sma50 = sma(closes, 50)
        if sma20 is None or sma50 is None:
            return Signal(symbol, bars[-1].end, self.version, False, "indicator_unavailable")

        current = closes[-1]
        previous = closes[-2]
        distance = float((current - sma20) / sma20)
        pullback = bars[-1].low <= sma20 and current > sma20 and previous <= sma20
        trend = sma20 > sma50 and current > sma50
        rsi14 = rsi(closes, 14)
        if rsi14 is None:
            return Signal(symbol, bars[-1].end, self.version, False, "indicator_unavailable")
        if trend and pullback and 50.0 < rsi14 < 68.0:
            return Signal(
                symbol,
                bars[-1].end,
                self.version,
                True,
                "trend_pullback_entry",
                rsi14,
                {"sma20": float(sma20), "sma50": float(sma50), "distance_sma20": distance},
            )
        return Signal(symbol, bars[-1].end, self.version, False, "no_trend_pullback")


class MomentumExpansionStrategy:
    version = "momentum-expansion-v1"

    def evaluate(
        self,
        bars: list[Bar],
        now: datetime,
        regime: Regime,
        sentiment_score: float | None,
        held: bool,
        cooldown: bool,
        liquid: bool,
        feed_healthy: bool,
    ) -> Signal:
        symbol = bars[-1].symbol if bars else ""
        if not bars:
            return Signal(symbol, now, self.version, False, "no_bars")
        if held:
            return Signal(symbol, bars[-1].end, self.version, False, "already_held")
        if cooldown:
            return Signal(symbol, bars[-1].end, self.version, False, "stop_cooldown")
        if not feed_healthy:
            return Signal(symbol, bars[-1].end, self.version, False, "data_unhealthy")
        if now.time() > time(14, 45):
            return Signal(symbol, bars[-1].end, self.version, False, "entry_cutoff")
        if regime not in {Regime.RISK_ON, Regime.CAUTIOUS}:
            return Signal(symbol, bars[-1].end, self.version, False, f"regime_{regime.value}")
        if not liquid:
            return Signal(symbol, bars[-1].end, self.version, False, "liquidity_filter")
        if len(bars) < 31:
            return Signal(symbol, bars[-1].end, self.version, False, "insufficient_bars")

        closes = [b.close for b in bars]
        current = bars[-1]
        prev = bars[-2]
        sma20 = sma(closes, 20)
        if sma20 is None:
            return Signal(symbol, bars[-1].end, self.version, False, "indicator_unavailable")
        ranges = [float(b.high - b.low) for b in bars[-21:-1]]
        avg_range = sum(ranges) / len(ranges) if ranges else 0.0
        current_range = float(current.high - current.low)
        return5 = float((closes[-1] - closes[-6]) / closes[-6])
        volume_avg = sum(float(b.volume) for b in bars[-21:-1]) / 20.0
        close_above = current.close > sma20
        expansion = current_range >= avg_range * 1.5 if avg_range > 0 else False
        volume_ok = float(current.volume) >= volume_avg * 1.2 if volume_avg > 0 else True
        continuation = current.close > prev.close and return5 >= 0.008
        if close_above and expansion and volume_ok and continuation:
            return Signal(
                symbol,
                current.end,
                self.version,
                True,
                "momentum_expansion_entry",
                return5,
                {"sma20": float(sma20), "return5": return5, "range_ratio": current_range / avg_range if avg_range else None, "volume_ratio": float(current.volume) / volume_avg if volume_avg else None},
            )
        return Signal(symbol, current.end, self.version, False, "no_momentum_expansion")


class MeanReversionStrategy:
    version = "mean-reversion-v1"

    def evaluate(
        self,
        bars: list[Bar],
        now: datetime,
        regime: Regime,
        sentiment_score: float | None,
        held: bool,
        cooldown: bool,
        liquid: bool,
        feed_healthy: bool,
    ) -> Signal:
        symbol = bars[-1].symbol if bars else ""
        if not bars:
            return Signal(symbol, now, self.version, False, "no_bars")
        if held:
            return Signal(symbol, bars[-1].end, self.version, False, "already_held")
        if cooldown:
            return Signal(symbol, bars[-1].end, self.version, False, "stop_cooldown")
        if not feed_healthy:
            return Signal(symbol, bars[-1].end, self.version, False, "data_unhealthy")
        if now.time() > time(14, 45):
            return Signal(symbol, bars[-1].end, self.version, False, "entry_cutoff")
        if regime not in {Regime.RANGE_BOUND, Regime.CAUTIOUS}:
            return Signal(symbol, bars[-1].end, self.version, False, f"regime_{regime.value}")
        if not liquid:
            return Signal(symbol, bars[-1].end, self.version, False, "liquidity_filter")
        if len(bars) < 22:
            return Signal(symbol, bars[-1].end, self.version, False, "insufficient_bars")

        closes = [b.close for b in bars]
        sma20 = sma(closes, 20)
        rsi14 = rsi(closes, 14)
        if sma20 is None or rsi14 is None:
            return Signal(symbol, bars[-1].end, self.version, False, "indicator_unavailable")
        current = closes[-1]
        previous = closes[-2]
        deviation = float((current - sma20) / sma20)
        reversal = current > previous
        if deviation <= -0.01 and rsi14 < 35.0 and reversal:
            return Signal(symbol, bars[-1].end, self.version, True, "mean_reversion_entry", rsi14, {"sma20": float(sma20), "deviation": deviation})
        return Signal(symbol, bars[-1].end, self.version, False, "no_mean_reversion")


class VolatilityBreakoutStrategy:
    version = "volatility-breakout-v1"

    def evaluate(
        self,
        bars: list[Bar],
        now: datetime,
        regime: Regime,
        sentiment_score: float | None,
        held: bool,
        cooldown: bool,
        liquid: bool,
        feed_healthy: bool,
    ) -> Signal:
        symbol = bars[-1].symbol if bars else ""
        if not bars:
            return Signal(symbol, now, self.version, False, "no_bars")
        if held:
            return Signal(symbol, bars[-1].end, self.version, False, "already_held")
        if cooldown:
            return Signal(symbol, bars[-1].end, self.version, False, "stop_cooldown")
        if not feed_healthy:
            return Signal(symbol, bars[-1].end, self.version, False, "data_unhealthy")
        if now.time() > time(14, 45):
            return Signal(symbol, bars[-1].end, self.version, False, "entry_cutoff")
        if regime not in {Regime.RISK_ON, Regime.CAUTIOUS}:
            return Signal(symbol, bars[-1].end, self.version, False, f"regime_{regime.value}")
        if not liquid:
            return Signal(symbol, bars[-1].end, self.version, False, "liquidity_filter")
        if len(bars) < 25:
            return Signal(symbol, bars[-1].end, self.version, False, "insufficient_bars")

        current = bars[-1]
        prior_high = max(b.high for b in bars[-21:-1])
        closes = [b.close for b in bars]
        sma20 = sma(closes, 20)
        if sma20 is None:
            return Signal(symbol, current.end, self.version, False, "indicator_unavailable")
        breakout = current.close > prior_high and current.close > sma20
        if breakout:
            distance = float((current.close - sma20) / sma20)
            return Signal(symbol, current.end, self.version, True, "volatility_breakout_entry", distance, {"prior_high": float(prior_high), "sma20": float(sma20), "distance_sma20": distance})
        return Signal(symbol, current.end, self.version, False, "no_volatility_breakout")


STRATEGY_FAMILIES = (
    TrendPullbackStrategy,
    MomentumExpansionStrategy,
    MeanReversionStrategy,
    VolatilityBreakoutStrategy,
)
