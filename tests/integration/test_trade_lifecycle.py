import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "scripts" / "run_replay.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_replay(fixture, tmp_path):
    db_path = tmp_path / f"{fixture.stem}.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            str(REPLAY),
            "--bars",
            str(fixture),
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    return db_path, result


def test_target_trade_lifecycle(tmp_path):
    fixture = FIXTURES / "trade_lifecycle_target.csv"

    db_path, result = run_replay(fixture, tmp_path)

    assert "'symbols': 1" in result.stdout
    assert "'bars': 46" in result.stdout
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    fills = db.execute(
        """
        SELECT side, qty, price, fee, reason
        FROM simulated_fills
        ORDER BY id
        """
    ).fetchall()

    assert len(fills) == 2

    buy, sell = fills

    assert buy["side"] == "BUY"
    assert buy["qty"] == 87
    assert buy["fee"] == 20.0
    assert buy["reason"] == "ENTRY"

    assert sell["side"] == "SELL"
    assert sell["qty"] == 87
    assert sell["fee"] == 20.0
    assert sell["reason"] == "TARGET"

    trade = db.execute(
        """
        SELECT
            qty,
            entry_price,
            exit_price,
            entry_fee,
            exit_fee,
            gross_pnl,
            net_pnl,
            strategy_version,
            exit_reason
        FROM closed_trades
        """
    ).fetchone()

    assert trade is not None
    assert trade["qty"] == 87
    assert trade["entry_fee"] == 20.0
    assert trade["exit_fee"] == 20.0
    assert trade["strategy_version"] == "baseline-breakout-v1"
    assert trade["exit_reason"] == "TARGET"

    # The target lifecycle must produce a positive net result
    # after both mandatory fees.
    assert trade["gross_pnl"] > 0
    assert trade["net_pnl"] > 0

    # Exact cash result verifies that conservative execution
    # pricing and both mandatory fees were applied.
    cash_json = db.execute(
        "SELECT value FROM kv_state WHERE key='cash'"
    ).fetchone()[0]

    final_cash = float(cash_json)

    assert abs(final_cash - 50402.5694785) < 1e-6
    assert abs(trade["net_pnl"] - 402.5694785) < 1e-6

    db.close()


def test_stop_trade_lifecycle_and_cooldown(tmp_path):
    fixture = FIXTURES / "trade_lifecycle_stop.csv"

    db_path, result = run_replay(fixture, tmp_path)

    assert "'symbols': 1" in result.stdout
    assert "'bars': 37" in result.stdout
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    fills = db.execute(
        """
        SELECT side, qty, price, fee, reason
        FROM simulated_fills
        ORDER BY id
        """
    ).fetchall()

    assert len(fills) == 2

    buy, sell = fills

    assert buy["side"] == "BUY"
    assert buy["qty"] == 87
    assert buy["fee"] == 20.0
    assert buy["reason"] == "ENTRY"

    assert sell["side"] == "SELL"
    assert sell["qty"] == 87
    assert sell["fee"] == 20.0
    assert sell["reason"] == "STOP"

    trade = db.execute(
        """
        SELECT
            qty,
            entry_price,
            exit_price,
            entry_fee,
            exit_fee,
            gross_pnl,
            net_pnl,
            exit_reason
        FROM closed_trades
        """
    ).fetchone()

    assert trade is not None
    assert trade["qty"] == 87
    assert trade["entry_fee"] == 20.0
    assert trade["exit_fee"] == 20.0
    assert trade["exit_reason"] == "STOP"
    assert trade["gross_pnl"] < 0
    assert trade["net_pnl"] < trade["gross_pnl"]

    cooldown = db.execute(
        """
        SELECT until_utc, reason
        FROM cooldowns
        WHERE symbol='ABC'
        """
    ).fetchone()

    assert cooldown is not None
    assert cooldown["reason"] == "stop_loss"

    cooldown_signal = db.execute(
        """
        SELECT eligible, reason
        FROM signals
        WHERE reason='stop_cooldown'
        """
    ).fetchone()

    assert cooldown_signal is not None
    assert cooldown_signal["eligible"] == 0

    db.close()
