from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar, Regime
from nse_paper_agent.strategy.families import (
    MeanReversionStrategy,
    MomentumExpansionStrategy,
    TrendPullbackStrategy,
    VolatilityBreakoutStrategy,
)

IST = ZoneInfo("Asia/Kolkata")


def _bars(values, volumes=None):
    volumes = volumes or [1000] * len(values)
    bars = []
    for i, (value, volume) in enumerate(zip(values, volumes)):
        ts = datetime(2026, 1, 1, 10, 0, tzinfo=IST).replace(day=1)
        ts = ts.replace(minute=(i * 5) % 60)
        bars.append(
            Bar(
                "NSE:TEST-EQ",
                ts,
                ts,
                Decimal(str(value - 0.5)),
                Decimal(str(value + 0.5)),
                Decimal(str(value - 0.5)),
                Decimal(str(value)),
                Decimal(str(volume)),
            )
        )
    return bars


def test_strategy_family_versions_are_unique():
    versions = {
        TrendPullbackStrategy.version,
        MomentumExpansionStrategy.version,
        MeanReversionStrategy.version,
        VolatilityBreakoutStrategy.version,
    }
    assert len(versions) == 4


def test_strategy_families_share_signal_contract():
    bars = _bars([100 + i * 0.2 for i in range(60)])
    for strategy_cls in (TrendPullbackStrategy, MomentumExpansionStrategy, MeanReversionStrategy, VolatilityBreakoutStrategy):
        signal = strategy_cls().evaluate(bars, bars[-1].end, Regime.RISK_ON, 0.5, False, False, True, True)
        assert signal.strategy_version == strategy_cls.version
        assert signal.symbol == "NSE:TEST-EQ"


def test_mean_reversion_can_emit_long_entry_on_oversold_reversal():
    values = [110 - i * 0.7 for i in range(25)] + [92.5, 93.5]
    bars = _bars(values)
    signal = MeanReversionStrategy().evaluate(bars, bars[-1].end, Regime.RANGE_BOUND, 0.5, False, False, True, True)
    assert signal.eligible is True
    assert signal.reason == "mean_reversion_entry"


def test_volatility_breakout_emits_when_close_breaks_prior_high():
    values = [100 + (i % 3) * 0.1 for i in range(24)] + [101.5]
    bars = _bars(values, [1000] * 24 + [2000])
    bars[-1] = Bar(
        bars[-1].symbol,
        bars[-1].start,
        bars[-1].end,
        Decimal("101.0"),
        Decimal("102.0"),
        Decimal("100.8"),
        Decimal("101.5"),
        Decimal("2000"),
    )
    signal = VolatilityBreakoutStrategy().evaluate(bars, bars[-1].end, Regime.RISK_ON, 0.5, False, False, True, True)
    assert signal.eligible is True
    assert signal.reason == "volatility_breakout_entry"
