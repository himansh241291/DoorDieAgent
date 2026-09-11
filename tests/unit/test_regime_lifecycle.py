from datetime import datetime, timezone

from nse_paper_agent.domain.models import Quote, Regime
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.regime.engine import RegimeEngine
from nse_paper_agent.risk.engine import RiskEngine


def cfg():
    return {
        "account": {
            "starting_capital": 50000.0,
            "minimum_cash_reserve": 2000.0,
            "max_open_positions": 5,
            "max_gross_position": 10000.0,
            "buy_fee": 20.0,
            "sell_fee": 20.0,
            "risk_per_trade": 0.003,
        },
        "risk": {
            "hard_stop_pct": 0.015,
            "take_profit_pct": 0.05,
            "daily_loss_limit_pct": 0.02,
            "rolling_drawdown_pct": 0.04,
            "rolling_drawdown_days": 5,
            "rolling_block_hours": 48,
            "stop_cooldown_minutes": 120,
            "slippage_bps": 10,
            "max_spread_bps": 50,
        },
        "safety": {"global_kill_switch": False, "emergency_kill_file": "/tmp/no-kill"},
    }


def test_regime_lifecycle_has_expected_classification_and_entry_effect(tmp_path):
    engine = RegimeEngine()
    now = datetime.now(timezone.utc)
    cases = [
        (Regime.RISK_ON, "trend_and_breadth_confirmed", (110, 105, 100, 0.80, 0.50, False)),
        (Regime.CAUTIOUS, "mixed_trend_or_elevated_volatility", (110, 105, 100, 0.40, 0.50, False)),
        (Regime.RANGE_BOUND, "no_confirmed_trend", (102, 105, 100, 0.50, 0.50, False)),
        (Regime.RISK_OFF, "benchmark_and_breadth_weak", (90, 100, 105, 0.30, 0.50, False)),
        (Regime.RISK_OFF, "volatility_shock", (110, 105, 100, 0.70, 0.50, True)),
        (Regime.DATA_DEGRADED, "data_health_failure", (110, 105, 100, 0.70, 0.50, False)),
    ]

    db = Database(str(tmp_path / "regime.sqlite"))
    db.initialize()
    repo = Repository(db)
    repo.set_cash(50000)
    db.set_state("daily_start_equity", 50000)
    risk = RiskEngine(cfg(), repo)
    quote = Quote("ABC", now, 99.9, 100.1, 100, 100000)

    observed = []
    for expected, reason, values in cases:
        healthy = expected != Regime.DATA_DEGRADED
        snapshot = engine.classify(now, *values, healthy)
        assert snapshot.regime is expected
        assert snapshot.reason == reason
        observed.append(snapshot.regime)

        decision = risk.can_buy(now, {"ABC": quote}, 50000, snapshot.regime)
        if expected is Regime.RISK_ON:
            assert decision.allowed and decision.size_factor == 1.0
        elif expected is Regime.CAUTIOUS:
            assert decision.allowed and decision.size_factor == 0.5
        else:
            assert not decision.allowed
            assert decision.reason == f"regime_{expected.value}"

    assert observed == [
        Regime.RISK_ON,
        Regime.CAUTIOUS,
        Regime.RANGE_BOUND,
        Regime.RISK_OFF,
        Regime.RISK_OFF,
        Regime.DATA_DEGRADED,
    ]
    db.close()
