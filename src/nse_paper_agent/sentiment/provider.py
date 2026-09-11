from __future__ import annotations

from datetime import datetime
from typing import Protocol

from nse_paper_agent.domain.models import SentimentObservation


class SentimentProvider(Protocol):
    def market(self, now: datetime) -> SentimentObservation: ...

    def symbol(self, symbol: str, now: datetime) -> SentimentObservation: ...


class NeutralSentimentProvider:
    """Safe placeholder until a real, timestamped provider is configured.

    A missing source is represented by score=None rather than fabricated
    neutral news data. The strategy can then fall back to technical/regime
    inputs without pretending that news was observed.
    """

    def market(self, now: datetime) -> SentimentObservation:
        return SentimentObservation("NIFTY50", now, None, 0.0, "unavailable", None, {})

    def symbol(self, symbol: str, now: datetime) -> SentimentObservation:
        return SentimentObservation(symbol, now, None, 0.0, "unavailable", None, {})


class CompositeSentiment:
    """Weighted, bounded sentiment combiner."""

    COMPONENTS = ("trend", "breadth", "relative_strength", "volume_confirmation", "news")

    def __init__(self, weights: dict[str, float]):
        if set(weights) != set(self.COMPONENTS):
            raise ValueError("sentiment weights must define exactly all components")
        if any(weight < 0 for weight in weights.values()):
            raise ValueError("sentiment weights cannot be negative")
        if sum(weights.values()) <= 0:
            raise ValueError("sentiment weights must have positive total")
        self.weights = dict(weights)

    def score(self, trend: float, breadth: float, relative_strength: float, volume_confirmation: float, news: float | None) -> float:
        values = {
            "trend": trend,
            "breadth": breadth,
            "relative_strength": relative_strength,
            "volume_confirmation": volume_confirmation,
            "news": 0.0 if news is None else news,
        }
        if any(value < -1.0 or value > 1.0 for value in values.values()):
            raise ValueError("sentiment components must be within [-1, 1]")
        total = sum(self.weights.values())
        return max(-1.0, min(1.0, sum(self.weights[name] * values[name] for name in self.COMPONENTS) / total))
