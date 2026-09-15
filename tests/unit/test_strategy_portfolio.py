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


def health(version: str, expectancy: float, confidence: float = 1.0, selection_ready: bool = True) -> StrategyHealth:
    return StrategyHealth(
        version=version,
        samples=50,
        expectancy=expectancy,
        recent_expectancy=expectancy,
        max_drawdown=0.02,
        confidence=confidence,
        availability=StrategyAvailability.ACTIVE,
        selection_ready=selection_ready,
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


def test_missing_health_fails_closed_without_bootstrap():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a")}, Regime.RISK_ON, {}
    )
    assert selected.strategy is None
    assert selected.reason == "no_healthy_eligible_strategy"


def test_single_active_bootstrap_is_explicit():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a")},
        Regime.RISK_ON,
        {},
        allow_single_active_bootstrap=True,
    )
    assert selected.strategy is strategy
    assert selected.reason == "single_active_strategy_bootstrap"
    assert selected.ranked_versions == ("strategy-a",)


def test_single_active_bootstrap_allows_insufficient_evidence_but_not_pause():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a")},
        Regime.RISK_ON,
        {"strategy-a": health("strategy-a", 10, selection_ready=False)},
        allow_single_active_bootstrap=True,
    )
    assert selected.strategy is strategy
    assert selected.reason == "single_active_strategy_bootstrap"


def test_bootstrap_does_not_bypass_paused_health():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    paused = StrategyHealth(
        version="strategy-a",
        samples=20,
        expectancy=10,
        recent_expectancy=-20,
        max_drawdown=0.05,
        confidence=0.5,
        availability=StrategyAvailability.PAUSED,
        selection_ready=False,
        reason="drawdown_limit_exceeded",
    )
    selected = pool.select(
        {"strategy-a": signal("strategy-a")},
        Regime.RISK_ON,
        {"strategy-a": paused},
        allow_single_active_bootstrap=True,
    )
    assert selected.strategy is None


def test_two_active_strategies_require_evidence_before_selection():
    a = DummyStrategy("strategy-a")
    b = DummyStrategy("strategy-b")
    pool = StrategyPool([StrategyRegistration(a), StrategyRegistration(b)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a"), "strategy-b": signal("strategy-b")},
        Regime.RISK_ON,
        {
            "strategy-a": health("strategy-a", 10, selection_ready=False),
            "strategy-b": health("strategy-b", 20, selection_ready=False),
        },
        allow_single_active_bootstrap=True,
    )
    assert selected.strategy is None


def test_bootstrap_does_not_select_when_signal_is_ineligible():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([StrategyRegistration(strategy)])
    selected = pool.select(
        {"strategy-a": signal("strategy-a", eligible=False)},
        Regime.RISK_ON,
        {},
        allow_single_active_bootstrap=True,
    )
    assert selected.strategy is None


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


def test_inactive_strategy_is_not_selectable_even_with_health():
    strategy = DummyStrategy("strategy-a")
    pool = StrategyPool([
        StrategyRegistration(strategy, availability=StrategyAvailability.PAUSED)
    ])
    selected = pool.select(
        {"strategy-a": signal("strategy-a")},
        Regime.RISK_ON,
        {"strategy-a": health("strategy-a", 50)},
        allow_single_active_bootstrap=True,
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
        selection_ready=True,
    )
    selected = pool.select(
        {"strategy-a": signal("strategy-a")}, Regime.RISK_ON, {"strategy-a": bad}
    )
    assert selected.strategy is None
