from datetime import datetime, timezone

import pytest

from nse_paper_agent.domain.models import Regime
from nse_paper_agent.regime.engine import RegimeEngine
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
    composite = CompositeSentiment({
        "trend": 0.35,
        "breadth": 0.25,
        "relative_strength": 0.20,
        "volume_confirmation": 0.10,
        "news": 0.10,
    })
    assert composite.score(1, 1, 1, 1, None) == pytest.approx(0.9)
    assert composite.score(-1, -1, -1, -1, -1) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        composite.score(1.1, 0, 0, 0, 0)
