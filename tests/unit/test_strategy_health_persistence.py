from datetime import datetime, timedelta, timezone

from nse_paper_agent.domain.models import Regime, RegimeSnapshot
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository


def test_strategy_outcomes_include_complete_learning_context(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3"))
    db.initialize()
    repo = Repository(db)
    entry = datetime(2026, 1, 1, 9, 5, tzinfo=timezone.utc)
    exit_ts = entry + timedelta(hours=1)

    repo.record_regime(RegimeSnapshot(entry - timedelta(minutes=5), Regime.RISK_ON, {"close": 100.0}, "entry"))
    repo.record_regime(RegimeSnapshot(entry + timedelta(minutes=25), Regime.CAUTIOUS, {"close": 101.0}, "later"))
    db.conn.execute(
        """
        INSERT INTO closed_trades
        (symbol, qty, entry_price, exit_price, entry_fee, exit_fee, gross_pnl,
         net_pnl, entry_ts_utc, exit_ts_utc, strategy_version, exit_reason,
         holding_seconds, mae, mfe)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "ABC", 1, 100.0, 110.0, 20.0, 20.0, 10.0, 5.0,
            entry.isoformat(), exit_ts.isoformat(),
            "strategy-a", "TARGET", 3600, None, None,
        ),
    )

    outcomes = repo.strategy_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].version == "strategy-a"
    assert outcomes[0].net_pnl == 5.0
    assert outcomes[0].regime == Regime.RISK_ON.value
    assert outcomes[0].symbol == "ABC"
    assert outcomes[0].entry_ts == entry
    assert outcomes[0].exit_reason == "TARGET"
    assert outcomes[0].holding_seconds == 3600
    db.close()


def test_strategy_metric_is_persisted(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3"))
    db.initialize()
    repo = Repository(db)
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    repo.record_strategy_metric(
        "strategy-a",
        ts,
        {"samples": 20, "expectancy": 12.5, "selection_ready": True},
        Regime.RISK_ON,
    )
    row = db.conn.execute(
        "SELECT version, regime, computed_ts_utc, metrics_json FROM strategy_metrics"
    ).fetchone()
    assert row["version"] == "strategy-a"
    assert row["regime"] == "RISK_ON"
    assert '"selection_ready": true' in row["metrics_json"]
    db.close()
