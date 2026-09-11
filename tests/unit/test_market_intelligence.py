from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nse_paper_agent.domain.models import Bar, Regime
from nse_paper_agent.regime.engine import RegimeEngine
from nse_paper_agent.regime.intelligence import MarketIntelligence
from nse_paper_agent.sentiment.provider import CompositeSentiment, NeutralSentimentProvider


def test_regime_classification_matrix():
    engine = RegimeEngine()
    ts = datetime.now(timezone.utc)
    assert engine.classify(ts, 105, 100, 98, 0.60, 0.50, False, True).regime is Regime.RISK_ON
    assert engine.classify(ts, 100, 101, 99, 0.40, 0.70, False, True).regime is Regime.CAUTIOUS
    assert engine.classify(ts, 100, 101, 99, 0.50, 0.50, False, True).regime is Regime.RANGE_BOUND
    assert engine.classify(ts, 95, 100, 101, 0.30, 0.50, False, True).regime is Regime.RISK_OFF
    assert engine.classify(ts, 105, 100, 98, 0.60, 0.50, True, True).regime is Regime.RISK_OFF


def test_regime_fails_closed_when_intelligence_is_missing_or_invalid():
    engine = RegimeEngine()
    ts = datetime.now(timezone.utc)
    missing = engine.classify(ts, None, None, None, None, None, None, True)
    assert missing.regime is Regime.DATA_DEGRADED
    assert missing.reason == "market_intelligence_unavailable"
    invalid = engine.classify(ts, 100, 100, 99, 1.2, 0.5, False, True)
    assert invalid.regime is Regime.DATA_DEGRADED
    assert invalid.reason == "breadth_out_of_range"
    unhealthy = engine.classify(ts, 100, 100, 99, 0.6, 0.5, False, False)
    assert unhealthy.regime is Regime.DATA_DEGRADED
    assert unhealthy.reason == "data_health_failure"


def test_neutral_sentiment_does_not_fabricate_news():
    now = datetime.now(timezone.utc)
    obs = NeutralSentimentProvider().symbol("ABC", now)
    assert obs.score is None
    assert obs.source == "unavailable"
    assert obs.confidence == 0.0
    assert obs.fresh_until is None


def test_composite_sentiment_is_bounded_and_supports_missing_news():
    composite = CompositeSentiment({"trend": 0.35,"breadth": 0.25,"relative_strength": 0.20,"volume_confirmation": 0.10,"news": 0.10})
    assert composite.score(1, 1, 1, 1, None) == pytest.approx(0.9)
    assert composite.score(-1, -1, -1, -1, -1) == pytest.approx(-1.0)
    with pytest.raises(ValueError): composite.score(1.1, 0, 0, 0, 0)


def _bar(symbol, day, minute, close, high=None, low=None, volume=100):
    start = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc) + timedelta(days=day, minutes=minute)
    return Bar(symbol,start,start+timedelta(minutes=5),Decimal(str(close)),Decimal(str(high or close)),Decimal(str(low or close)),Decimal(str(close)),Decimal(str(volume)))


def test_daily_bars_aggregate_intraday_data():
    bars = [_bar("ABC",0,0,100,102,99,10),_bar("ABC",0,5,101,103,100,20),_bar("ABC",1,0,102,104,101,30)]
    daily = MarketIntelligence.daily_bars(bars)
    assert len(daily) == 2
    assert daily[0].open == Decimal("100")
    assert daily[0].high == Decimal("103")
    assert daily[0].low == Decimal("99")
    assert daily[0].close == Decimal("101")
    assert daily[0].volume == Decimal("30")


def test_breadth_requires_minimum_eligible_universe():
    engine = MarketIntelligence(breadth_min_symbols=2)
    bars = {"A": [_bar("A",d,0,100+d) for d in range(20)],"B": [_bar("B",d,0,100+d) for d in range(20)]}
    assert engine.breadth(bars) == pytest.approx(1.0)
    assert engine.breadth({"A": bars["A"]}) is None


def test_market_intelligence_fails_closed_without_benchmark_history():
    engine = MarketIntelligence(benchmark_min_bars=50)
    result = engine.calculate([], {})
    assert result["close"] is None
    assert result["sma20"] is None
    assert result["sma50"] is None
    assert result["breadth20"] is None
