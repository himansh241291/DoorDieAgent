from datetime import datetime, timedelta, timezone

import pytest

from nse_paper_agent.domain.models import SentimentObservation
from nse_paper_agent.sentiment.policy import SentimentPolicy


def observation(score, now, confidence=1.0, fresh_until=None):
    return SentimentObservation("ABC", now, score, confidence, "test", fresh_until, {})


def test_sentiment_entry_thresholds_and_sizing():
    now = datetime.now(timezone.utc)
    policy = SentimentPolicy()

    assert policy.entry(observation(0.80, now), now) == (True, 1.0, "sentiment_supportive", 0.80)
    assert policy.entry(observation(0.25, now), now) == (True, 0.5, "sentiment_cautious", 0.25)
    assert policy.entry(observation(0.05, now), now) == (False, 0.0, "sentiment_below_minimum", 0.05)
    assert policy.entry(observation(-0.50, now), now) == (False, 0.0, "sentiment_below_minimum", -0.50)


def test_missing_and_stale_sentiment_falls_back_without_fabricating_score():
    now = datetime.now(timezone.utc)
    policy = SentimentPolicy(stale_after_minutes=30)

    missing = observation(None, now)
    stale = observation(0.90, now - timedelta(minutes=31))
    expired = observation(0.90, now, fresh_until=now - timedelta(seconds=1))

    assert policy.entry(missing, now) == (True, 1.0, "sentiment_unavailable_fallback", None)
    assert policy.entry(stale, now) == (True, 1.0, "sentiment_unavailable_fallback", None)
    assert policy.entry(expired, now) == (True, 1.0, "sentiment_unavailable_fallback", None)


def test_invalid_sentiment_is_not_used():
    now = datetime.now(timezone.utc)
    policy = SentimentPolicy()

    assert policy.usable_score(observation(float("nan"), now), now) is None
    assert policy.usable_score(observation(0.5, now, confidence=1.1), now) is None
    assert policy.usable_score(observation(0.5, now + timedelta(seconds=1)), now) is None


def test_policy_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        SentimentPolicy(min_score=0.5, normal_score=0.4)
    with pytest.raises(ValueError):
        SentimentPolicy(stale_after_minutes=0)
