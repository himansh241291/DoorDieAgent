import pytest

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.research.validation import require_long_duration, validate_replay


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
