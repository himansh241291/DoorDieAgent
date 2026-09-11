from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nse_paper_agent.domain.models import Bar
from nse_paper_agent.regime.intelligence import MarketIntelligence


def make_bars(symbol, closes):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(
            symbol,
            start + timedelta(days=i),
            start + timedelta(days=i + 1),
            Decimal(str(close)),
            Decimal(str(close)),
            Decimal(str(close)),
            Decimal(str(close)),
            Decimal("100000"),
        )
        for i, close in enumerate(closes)
    ]


def test_benchmark_calculates_sma20_and_sma50():
    closes = list(range(1, 51))
    result = MarketIntelligence(volatility_history=1).benchmark(make_bars("NIFTY50", closes))
    assert result["close"] == 50
    assert result["sma20"] == pytest.approx(sum(range(31, 51)) / 20)
    assert result["sma50"] == pytest.approx(25.5)


def test_benchmark_requires_sufficient_history():
    result = MarketIntelligence().benchmark(make_bars("NIFTY50", list(range(1, 30))))
    assert result["sma20"] is None
    assert result["sma50"] is None
    assert result["vol_percentile"] is None
    assert result["vol_shock"] is None


def test_breadth_requires_minimum_eligible_universe():
    intelligence = MarketIntelligence(breadth_min_symbols=5)
    bars = {
        f"S{i}": make_bars(f"S{i}", list(range(1, 21 + (i % 2))))
        for i in range(4)
    }
    assert intelligence.breadth(bars) is None


def test_breadth_counts_symbols_above_their_sma20():
    intelligence = MarketIntelligence(breadth_min_symbols=5)
    bars = {}
    for i in range(5):
        if i < 3:
            closes = [100] * 19 + [110]
        else:
            closes = [100] * 19 + [90]
        bars[f"S{i}"] = make_bars(f"S{i}", closes)
    assert intelligence.breadth(bars) == pytest.approx(3 / 5)


def test_volatility_percentile_is_bounded():
    closes = [100.0]
    for i in range(1, 100):
        closes.append(closes[-1] * (1.001 if i % 2 else 0.999))
    result = MarketIntelligence(volatility_history=10).benchmark(make_bars("NIFTY50", closes))
    assert 0.0 <= result["vol_percentile"] <= 1.0
    assert result["vol_shock"] in (True, False)


def test_invalid_price_history_degrades_volatility_inputs():
    closes = [100.0] * 49 + [0.0]
    result = MarketIntelligence().benchmark(make_bars("NIFTY50", closes))
    assert result["sma50"] == pytest.approx(100.0)
    assert result["vol_percentile"] is None
    assert result["vol_shock"] is None
