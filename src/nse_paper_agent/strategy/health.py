from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from nse_paper_agent.domain.models import Regime
from nse_paper_agent.strategy.evidence import StrategyEvidence, StrategyEvidenceEngine, StrategyOutcome
from nse_paper_agent.strategy.portfolio import StrategyAvailability, StrategyHealth


@dataclass(frozen=True)
class StrategyHealthPolicy:
    min_samples: int = 20
    min_regime_samples: int = 10
    recent_window: int = 20
    degradation_expectancy_factor: float = 0.50
    max_drawdown_limit: float = 0.04


class StrategyHealthEngine:
    """Translate descriptive evidence into conservative selection health.

    Evidence describes what happened. Health decides whether the evidence is
    strong enough for strategy selection. Neither layer changes risk controls,
    strategy code, or production identity.
    """

    def __init__(
        self,
        policy: StrategyHealthPolicy | None = None,
        evidence_engine: StrategyEvidenceEngine | None = None,
    ):
        self.policy = policy or StrategyHealthPolicy()
        if self.policy.min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if self.policy.min_regime_samples <= 0:
            raise ValueError("min_regime_samples must be positive")
        if self.policy.recent_window <= 0:
            raise ValueError("recent_window must be positive")
        if not 0 < self.policy.degradation_expectancy_factor <= 1:
            raise ValueError("degradation_expectancy_factor must be in (0, 1]")
        if not 0 < self.policy.max_drawdown_limit < 1:
            raise ValueError("max_drawdown_limit must be in (0, 1)")
        self.evidence_engine = evidence_engine or StrategyEvidenceEngine(self.policy.recent_window)

    def _health_from_evidence(self, evidence: StrategyEvidence) -> StrategyHealth:
        overall = evidence.overall
        recent = evidence.recent
        regime_expectancy = {
            name: aggregate.expectancy
            for name, aggregate in evidence.by_regime.items()
            if aggregate.expectancy is not None
            and aggregate.samples >= self.policy.min_regime_samples
        }

        availability = StrategyAvailability.ACTIVE
        selection_ready = overall.samples >= self.policy.min_samples
        reason = "insufficient_evidence"

        if overall.samples == 0:
            reason = "no_trade_evidence"
            selection_ready = False
        elif overall.max_drawdown is not None and overall.max_drawdown > self.policy.max_drawdown_limit:
            availability = StrategyAvailability.PAUSED
            reason = "drawdown_limit_exceeded"
            selection_ready = False
        elif (
            selection_ready
            and overall.expectancy is not None
            and recent.expectancy is not None
            and overall.expectancy > 0
            and recent.expectancy < overall.expectancy * self.policy.degradation_expectancy_factor
        ):
            availability = StrategyAvailability.PAUSED
            reason = "recent_expectancy_degradation"
            selection_ready = False
        elif selection_ready:
            reason = "evidence_ready"

        return StrategyHealth(
            version=evidence.version,
            samples=overall.samples,
            expectancy=overall.expectancy,
            recent_expectancy=recent.expectancy,
            max_drawdown=overall.max_drawdown,
            confidence=overall.confidence,
            regime_expectancy=regime_expectancy,
            availability=availability,
            selection_ready=selection_ready,
            reason=reason,
        )

    def compute(
        self,
        outcomes: Iterable[StrategyOutcome],
        active_versions: Iterable[str],
        regime: Regime | None = None,
    ) -> Mapping[str, StrategyHealth]:
        evidence = self.evidence_engine.compute(outcomes, active_versions)
        return {version: self._health_from_evidence(record) for version, record in evidence.items()}
