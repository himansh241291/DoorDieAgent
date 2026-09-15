from datetime import datetime, timezone

import pytest

from nse_paper_agent.domain.models import Regime, Signal
from nse_paper_agent.strategy.portfolio import (
    StrategyAvailability,
    StrategyHealth,
    StrategyPool,
    StrategyRegistration,
)


class DummyStrategy:
    def __init__(self, version: str):
        self.version = version


def signal(version: str, eligible: bool = True) -> Signal:
    return Signal(
        symbol="ABC",
        bar_end=datetime.now(timezone.utc),
        strategy_version=version,
        eligible=eligible,
        reason="test",
    )


def health(version: str, expectancy: float, confidence: float = 1.0) -> StrategyHealth:
    return StrategyHealth(
        version=version,
        samples=50,
        expectancy=expectancy,
        max_drawdown=0.02,
        confidence=confidence,
        availability=StrategyAvailability.ACTIVE,
    )


def test_pool_selects_healthiest_strategy():
    a = DummyStrategy("strategy-a")
    b = DummyStrategy("strategy-b")
    pool = StrategyPool([StrategyRegistration(a, priority=100), StrategyRegistration(b, priority=100)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a"), "strategy-b": signal("strategy-b")},
        Regime.RISK_ON,
        {"strategy-a": health("strategy-a", 10), "strategy-b": health("strategy-b", 50)},
    )
    assert selected.strategy is b
    assert selected.reason == "selected_by_strategy_health"
    assert selected.ranked_versions == ("strategy-b", "strategy-a")


def test_unhealthy_strategy_cannot_be_selected():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a")},
        Regime.RISK_ON,
        {"strategy-a": health("strategy-a", -1)},
    )
    assert selected.strategy is None
    assert selected.reason == "no_healthy_eligible_strategy"


def test_missing_health_fails_closed():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a")}, Regime.RISK_ON, {}
    )
    assert selected.strategy is None
    assert selected.reason == "no_healthy_eligible_strategy"


def test_regime_restriction_is_enforced():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool(
        [StrategyRegistration(strategy, allowed_regimes=frozenset({Regime.RISK_ON}))]
    )
    selected = pool.select(
        {"strategy-a": signal("strategy-a")},
        Regime.CAUTIOUS,
        {"strategy-a": health("strategy-a", 50)},
    )
    assert selected.strategy is None


def test_duplicate_strategy_versions_rejected():
    with pytest.raises(ValueError, match="strategy versions must be unique"):
        StrategyPool(
            [
                StrategyRegistration(DummyStrategy("same")),
                StrategyRegistration(DummyStrategy("same")),
            ]
        )


def test_nonfinite_health_fails_closed():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    bad = StrategyHealth(
        version="strategy-a",
        samples=50,
        expectancy=float("nan"),
        max_drawdown=0.02,
        confidence=1.0,
        availability=StrategyAvailability.ACTIVE,
    )
    selected = pool.select(
        {"strategy-a": signal("strategy-a")}, Regime.RISK_ON, {"strategy-a": bad}
    )
    assert selected.strategy is None
