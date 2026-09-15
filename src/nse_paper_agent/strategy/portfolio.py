from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Mapping, Protocol, Sequence

from nse_paper_agent.domain.models import Bar, Regime, Signal


class StrategyAvailability(str, Enum):
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class Strategy(Protocol):
    version: str

    def evaluate(
        self,
        bars: list[Bar],
        now,
        regime: Regime,
        sentiment_score: float | None,
        held: bool,
        cooldown: bool,
        liquid: bool,
        feed_healthy: bool,
    ) -> Signal: ...


@dataclass(frozen=True)
class StrategyHealth:
    version: str
    samples: int = 0
    expectancy: float | None = None
    max_drawdown: float | None = None
    confidence: float = 0.0
    regime_expectancy: Mapping[str, float] = field(default_factory=dict)
    availability: StrategyAvailability = StrategyAvailability.RESEARCH

    def eligible_for_selection(self, regime: Regime) -> bool:
        if self.availability is not StrategyAvailability.ACTIVE:
            return False
        if self.samples <= 0 or self.expectancy is None or self.max_drawdown is None:
            return False
        if not all(isfinite(float(x)) for x in (self.expectancy, self.max_drawdown, self.confidence)):
            return False
        if self.max_drawdown < 0 or self.max_drawdown >= 1:
            return False
        if self.expectancy <= 0 or self.confidence <= 0:
            return False
        regime_exp = self.regime_expectancy.get(regime.value)
        if regime_exp is not None and (not isfinite(float(regime_exp)) or regime_exp <= 0):
            return False
        return True


@dataclass(frozen=True)
class StrategyRegistration:
    strategy: Strategy
    priority: int = 100
    allowed_regimes: frozenset[Regime] = frozenset()
    availability: StrategyAvailability = StrategyAvailability.ACTIVE


@dataclass(frozen=True)
class StrategySelection:
    strategy: Strategy | None
    reason: str
    ranked_versions: tuple[str, ...] = ()


class StrategyPool:
    """Registry/selector only; it never changes risk limits or strategy code."""

    def __init__(self, registrations: Sequence[StrategyRegistration]):
        versions = [r.strategy.version for r in registrations]
        if len(set(versions)) != len(versions):
            raise ValueError("strategy versions must be unique")
        self._registrations = tuple(registrations)

    def versions(self) -> tuple[str, ...]:
        return tuple(r.strategy.version for r in self._registrations)

    def active_registrations(self) -> tuple[StrategyRegistration, ...]:
        return tuple(r for r in self._registrations if r.availability is StrategyAvailability.ACTIVE)

    def active_versions(self) -> tuple[str, ...]:
        return tuple(r.strategy.version for r in self.active_registrations())

    def select(
        self,
        signals: Mapping[str, Signal],
        regime: Regime,
        health: Mapping[str, StrategyHealth],
        allow_single_active_bootstrap: bool = False,
    ) -> StrategySelection:
        ranked: list[tuple[float, float, float, int, int, str, Strategy]] = []
        eligible_versions: list[str] = []
        active_signals: list[StrategyRegistration] = []

        for registration in self.active_registrations():
            strategy = registration.strategy
            signal = signals.get(strategy.version)
            if signal is None or not signal.eligible:
                continue
            if registration.allowed_regimes and regime not in registration.allowed_regimes:
                continue
            active_signals.append(registration)
            record = health.get(strategy.version, StrategyHealth(strategy.version))
            if not record.eligible_for_selection(regime):
                continue
            eligible_versions.append(strategy.version)
            ranked.append(
                (
                    float(record.expectancy),
                    -float(record.max_drawdown),
                    float(record.confidence),
                    int(record.samples),
                    -int(registration.priority),
                    strategy.version,
                    strategy,
                )
            )

        if ranked:
            ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], item[4], item[5]))
            return StrategySelection(ranked[0][6], "selected_by_strategy_health", tuple(item[5] for item in ranked))

        if allow_single_active_bootstrap and len(active_signals) == 1:
            strategy = active_signals[0].strategy
            return StrategySelection(strategy, "single_active_strategy_bootstrap", (strategy.version,))

        return StrategySelection(None, "no_healthy_eligible_strategy", tuple(sorted(eligible_versions)))
