import pytest

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.research.replay_validation import (
    ReplayValidationResult,
    _split_dates,
    execute_validation,
)
from nse_paper_agent.research.validation import require_long_duration, validate_replay
from nse_paper_agent.research.validation_plan import ValidationPlan


def test_replay_validation_calculates_trade_and_drawdown_metrics(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3"))
    db.initialize()
    db.conn.executemany(
        "INSERT INTO closed_trades(symbol,qty,entry_price,exit_price,entry_fee,exit_fee,gross_pnl,net_pnl,entry_ts_utc,exit_ts_utc,strategy_version,exit_reason,holding_seconds,mae,mfe) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("A", 10, 100, 105, 20, 20, 50, 10, "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00", "v1", "TARGET", 3600, -1, 5),
            ("B", 10, 100, 98, 20, 20, -20, -60, "2026-01-02T00:00:00+00:00", "2026-01-02T01:00:00+00:00", "v1", "STOP", 3600, -2, 1),
            ("C", 10, 100, 99, 20, 20, -10, -50, "2026-01-03T00:00:00+00:00", "2026-01-03T01:00:00+00:00", "v1", "FORCED", 3600, -1, 1),
        ],
    )
    for date, equity in (("2026-01-01", 50000), ("2026-01-02", 49000), ("2026-01-03", 48000)):
        db.conn.execute(
            "INSERT INTO account_snapshots(ts_utc,ts_ist,trading_date,is_eod,cash,equity,gross,daily_start_equity,drawdown5) VALUES(?,?,?,?,?,?,?,?,?)",
            (date + "T15:30:00+00:00", date + "T21:00:00+05:30", date, 1, equity, equity, 0, 50000, 0),
        )
    db.conn.execute("INSERT INTO risk_events(ts_utc,event_type,allowed,reason,details_json) VALUES(?,?,?,?,?)", ("2026-01-01T00:00:00+00:00", "ENTRY", 0, "blocked", "{}"))

    result = validate_replay(db)
    assert result.trades == 3
    assert result.wins == 1
    assert result.losses == 2
    assert result.net_pnl == -100
    assert result.expectancy == pytest.approx(-100 / 3)
    assert result.win_rate == pytest.approx(1 / 3)
    assert result.max_drawdown == pytest.approx(0.04)
    assert result.trading_days == 3
    assert result.forced_exits == 1
    assert result.stop_exits == 1
    assert result.target_exits == 1
    assert result.blocked_entries == 1
    db.close()


def test_long_duration_gate_rejects_short_replay():
    db = Database(":memory:")
    db.initialize()
    result = validate_replay(db)
    with pytest.raises(ValueError, match="insufficient replay duration"):
        require_long_duration(result, 60)
    db.close()


def test_split_dates_is_chronological():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    class B:
        def __init__(self, value):
            self.end = value

    ist = ZoneInfo("Asia/Kolkata")
    bars = [
        B(datetime(2026, 1, day, 10, 0, tzinfo=ist).astimezone(timezone.utc))
        for day in range(1, 11)
    ]
    dev, holdout = _split_dates(bars)
    assert dev == [f"2026-01-{day:02d}" for day in range(1, 8)]
    assert holdout == [f"2026-01-{day:02d}" for day in range(8, 11)]


def test_result_as_dict_contains_validation_metrics():
    result = ReplayValidationResult(
        "holdout", "2026-08-01", "2026-08-31", 100, 20, 10, 4, 6,
        -120.0, -12.0, 0.4, 0.03, 8, 2, 0, 49880.0,
    )
    data = result.as_dict()
    assert data["split"] == "holdout"
    assert data["trades"] == 10
    assert data["net_expectancy"] == -12.0
    assert data["max_drawdown"] == 0.03


def test_execute_validation_requires_target(tmp_path):
    plan = ValidationPlan(
        proposal_id="p1",
        base_version="baseline-breakout-v1",
        challenger_version="baseline-breakout-v1-challenger-2",
        hypothesis="test",
        allowed_change_scope="time_of_day_eligibility",
        forbidden_change_scope=("risk_limits",),
        risk_config_hash="x",
        data_window="2025-09-15/2026-09-14",
        target=None,
    )
    with pytest.raises(ValueError, match="requires a challenger target"):
        execute_validation(plan, "missing.csv", str(tmp_path))


def test_execute_validation_rejects_unsupported_scope(tmp_path):
    plan = ValidationPlan(
        proposal_id="p1",
        base_version="baseline-breakout-v1",
        challenger_version="baseline-breakout-v1-challenger-2",
        hypothesis="test",
        allowed_change_scope="risk_limits",
        forbidden_change_scope=("hard_stop",),
        risk_config_hash="x",
        data_window="2025-09-15/2026-09-14",
        target="x",
    )
    with pytest.raises(ValueError, match="unsupported validation scope"):
        execute_validation(plan, "missing.csv", str(tmp_path))


def test_execute_validation_rejects_unsupported_base_version(tmp_path):
    plan = ValidationPlan(
        proposal_id="p1",
        base_version="not-the-baseline",
        challenger_version="baseline-breakout-v1-challenger-time_of_day_eligibility-afternoon",
        hypothesis="test",
        allowed_change_scope="time_of_day_eligibility",
        forbidden_change_scope=("risk_limits",),
        risk_config_hash="x",
        data_window="2025-09-15/2026-09-14",
        target="AFTERNOON",
    )
    with pytest.raises(ValueError, match="unsupported validation base version"):
        execute_validation(plan, "missing.csv", str(tmp_path))


def test_execute_validation_rejects_risk_config_drift(tmp_path):
    plan = ValidationPlan(
        proposal_id="p1",
        base_version="baseline-breakout-v1",
        challenger_version="baseline-breakout-v1-challenger-time_of_day_eligibility-afternoon",
        hypothesis="test",
        allowed_change_scope="time_of_day_eligibility",
        forbidden_change_scope=("risk_limits",),
        risk_config_hash="not-the-canonical-hash",
        data_window="2025-09-15/2026-09-14",
        target="AFTERNOON",
    )
    with pytest.raises(ValueError, match="risk configuration does not match canonical"):
        execute_validation(plan, "missing.csv", str(tmp_path))
