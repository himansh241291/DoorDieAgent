from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt
from statistics import mean
from typing import Iterable, Mapping

from nse_paper_agent.domain.models import Regime
from nse_paper_agent.strategy.portfolio import StrategyAvailability, StrategyHealth


@dataclass(frozen=True)
class StrategyHealthPolicy:
    min_samples: int = 20
    recent_window: int = 20
    degradation_expectancy_factor: float = 0.50
    max_drawdown_limit: float = 0.04


@dataclass(frozen=True)
class StrategyOutcome:
    version: str
    net_pnl: float
    exit_ts: datetime
    regime: str | None = None


class StrategyHealthEngine:
    """Build deterministic strategy health from completed trade outcomes only.

    This layer observes performance. It cannot modify risk, strategy code, or
    production identity. Health is evidence for selection, not a promotion gate.
    """

    def __init__(self, policy: StrategyHealthPolicy | None = None):
        self.policy = policy or StrategyHealthPolicy()

    @staticmethod
    def _confidence(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        avg = mean(values)
        if avg <= 0 or not isfinite(avg):
            return 0.0
        variance = mean([(value - avg) ** 2 for value in values])
        se = sqrt(variance / len(values))
        if not isfinite(se):
            return 0.0
        # Conservative normal-approximation signal: lower 95% bound above zero.
        return max(0.0, min(1.0, (avg - 1.96 * se) / avg))

    @staticmethod
    def _drawdown(values: list[float], starting_equity: float = 50000.0) -> float:
        equity = float(starting_equity)
        peak = equity
        max_dd = 0.0
        for pnl in values:
            equity += pnl
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd

    def compute(
        self,
        outcomes: Iterable[StrategyOutcome],
        active_versions: Iterable[str],
        regime: Regime | None = None,
    ) -> Mapping[str, StrategyHealth]:
        grouped: dict[str, list[StrategyOutcome]] = {}
        for outcome in outcomes:
            if not isfinite(float(outcome.net_pnl)):
                continue
            grouped.setdefault(outcome.version, []).append(outcome)

        active = set(active_versions)
        result: dict[str, StrategyHealth] = {}
        for version in sorted(active):
            rows = sorted(grouped.get(version, []), key=lambda row: row.exit_ts)
            pnls = [float(row.net_pnl) for row in rows]
            recent = pnls[-self.policy.recent_window :]
            expectancy = mean(pnls) if pnls else None
            recent_expectancy = mean(recent) if recent else None
            max_dd = self._drawdown(pnls) if pnls else None
            confidence = self._confidence(pnls)

            by_regime: dict[str, list[float]] = {}
            for row in rows:
                if row.regime:
                    by_regime.setdefault(row.regime, []).append(float(row.net_pnl))
            regime_expectancy = {
                name: mean(values) for name, values in by_regime.items() if values
            }

            availability = StrategyAvailability.ACTIVE
            if not pnls or len(pnls) < self.policy.min_samples:
                availability = StrategyAvailability.ACTIVE
            elif max_dd is not None and max_dd > self.policy.max_drawdown_limit:
                availability = StrategyAvailability.PAUSED
            elif (
                expectancy is not None
                and recent_expectancy is not None
                and expectancy > 0
                and recent_expectancy < expectancy * self.policy.degradation_expectancy_factor
            ):
                availability = StrategyAvailability.PAUSED

            result[version] = StrategyHealth(
                version=version,
                samples=len(pnls),
                expectancy=expectancy,
                max_drawdown=max_dd,
                confidence=confidence,
                regime_expectancy=regime_expectancy,
                availability=availability,
            )
        return result
