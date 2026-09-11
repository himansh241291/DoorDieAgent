from __future__ import annotations

from datetime import datetime
import math

from nse_paper_agent.domain.models import SentimentObservation


class SentimentPolicy:
    """Translate timestamped sentiment into entry quality without changing risk controls."""

    def __init__(self, min_score: float = 0.10, normal_score: float = 0.40, stale_after_minutes: int = 30):
        if not -1.0 <= min_score <= 1.0 or not -1.0 <= normal_score <= 1.0:
            raise ValueError("sentiment thresholds must be within [-1, 1]")
        if normal_score < min_score:
            raise ValueError("normal_score must be >= min_score")
        if stale_after_minutes <= 0:
            raise ValueError("stale_after_minutes must be positive")
        self.min_score = min_score
        self.normal_score = normal_score
        self.stale_after_minutes = stale_after_minutes

    def usable_score(self, observation: SentimentObservation, now: datetime) -> float | None:
        if observation.score is None or not math.isfinite(observation.score):
            return None
        if not 0.0 <= observation.confidence <= 1.0:
            return None
        if observation.fresh_until is not None and now > observation.fresh_until:
            return None
        age_seconds = (now - observation.ts).total_seconds()
        if age_seconds < 0 or age_seconds > self.stale_after_minutes * 60:
            return None
        if not -1.0 <= observation.score <= 1.0:
            return None
        return float(observation.score)

    def entry(self, observation: SentimentObservation, now: datetime) -> tuple[bool, float, str, float | None]:
        score = self.usable_score(observation, now)
        if score is None:
            return True, 1.0, "sentiment_unavailable_fallback", None
        if score < self.min_score:
            return False, 0.0, "sentiment_below_minimum", score
        if score < self.normal_score:
            return True, 0.5, "sentiment_cautious", score
        return True, 1.0, "sentiment_supportive", score
