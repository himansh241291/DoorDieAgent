from datetime import datetime, timedelta, timezone

from nse_paper_agent.domain.models import Regime
from nse_paper_agent.strategy.health import StrategyHealthEngine, StrategyHealthPolicy, StrategyOutcome
from nse_paper_agent.strategy.portfolio import StrategyAvailability


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def outcomes(version, pnls, regime="RISK_ON"):
    return [
        StrategyOutcome(version, float(pnl), BASE + timedelta(days=index), regime)
        for index, pnl in enumerate(pnls)
    ]


def test_health_requires_active_version_and_uses_completed_outcomes():
    engine = StrategyHealthEngine(StrategyHealthPolicy(min_samples=5, recent_window=3))
    result = engine.compute(outcomes("a", [10, 20, -5, 15, 12]), ["a", "b"])

    assert set(result) == {"a", "b"}
    assert result["a"].samples == 5
    assert result["a"].expectancy == 10.4
    assert result["a"].max_drawdown >= 0
    assert result["b"].samples == 0
    assert result["b"].availability is StrategyAvailability.ACTIVE


def test_negative_expectancy_has_zero_selection_confidence():
    engine = StrategyHealthEngine(StrategyHealthPolicy(min_samples=3))
    result = engine.compute(outcomes("a", [-10, -20, -5]), ["a"])
    health = result["a"]
    assert health.expectancy < 0
    assert health.confidence == 0


def test_regime_expectancy_is_separated():
    engine = StrategyHealthEngine(StrategyHealthPolicy(min_samples=2))
    data = outcomes("a", [10, 20], "RISK_ON") + outcomes("a", [-5, -15], "CAUTIOUS")
    result = engine.compute(data, ["a"], Regime.RISK_ON)
    assert result["a"].regime_expectancy["RISK_ON"] == 15
    assert result["a"].regime_expectancy["CAUTIOUS"] == -10


def test_large_drawdown_pauses_strategy():
    engine = StrategyHealthEngine(StrategyHealthPolicy(min_samples=5, max_drawdown_limit=0.04))
    # A losing sequence large enough to breach the strategy health drawdown threshold.
    result = engine.compute(outcomes("a", [1000, -3000, -1000, 500, 500]), ["a"])
    assert result["a"].availability is StrategyAvailability.PAUSED


def test_recent_performance_degradation_pauses_positive_strategy():
    engine = StrategyHealthEngine(
        StrategyHealthPolicy(min_samples=6, recent_window=3, degradation_expectancy_factor=0.50)
    )
    result = engine.compute(outcomes("a", [100, 100, 100, -20, -20, -20]), ["a"])
    assert result["a"].expectancy > 0
    assert result["a"].availability is StrategyAvailability.PAUSED


def test_nonfinite_outcomes_are_ignored():
    engine = StrategyHealthEngine(StrategyHealthPolicy(min_samples=2))
    data = outcomes("a", [10, 20]) + [
        StrategyOutcome("a", float("nan"), BASE + timedelta(days=10), "RISK_ON")
    ]
    result = engine.compute(data, ["a"])
    assert result["a"].samples == 2
    assert result["a"].expectancy == 15
