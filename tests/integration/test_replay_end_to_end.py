import sqlite3
import subprocess
import sys

from nse_paper_agent.data.provider import load_bars_csv


FIXTURE = "tests/fixtures/sample_bars.csv"


def test_fixture_is_deterministic():
    a = load_bars_csv(FIXTURE)
    b = load_bars_csv(FIXTURE)

    assert [
        (x.symbol, x.end, x.close)
        for x in a
    ] == [
        (x.symbol, x.end, x.close)
        for x in b
    ]


def test_replay_persists_market_state(tmp_path):
    db_path = tmp_path / "replay.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_replay.py",
            "--bars",
            FIXTURE,
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "'symbols': 1" in result.stdout
    assert "'bars': 35" in result.stdout
    assert "'cash': 50000.0" in result.stdout
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)

    assert db.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 35
    assert db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 35
    assert db.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 35
    assert db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1

    # The supplied fixture does not produce a completed trade.
    assert db.execute("SELECT COUNT(*) FROM simulated_fills").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0] == 0

    db.close()


def test_multiday_replay_forces_eod_exit_and_rolls_eod_equity(tmp_path):
    from datetime import datetime, timezone
    from decimal import Decimal

    from nse_paper_agent.domain.models import Position
    from nse_paper_agent.persistence.db import Database
    from nse_paper_agent.persistence.repository import Repository

    bars_path = tmp_path / "multiday.csv"
    db_path = tmp_path / "multiday.sqlite3"

    # 15:30 IST = 10:00 UTC.
    # Day 1 EOD must close the seeded position.
    # Day 2 proves the completed Day 1 EOD mark is the new baseline.
    bars_path.write_text(
        """symbol,start,end,open,high,low,close,volume
ABC,2026-01-02T09:55:00+00:00,2026-01-02T10:00:00+00:00,100,100,100,100,1000
ABC,2026-01-05T03:45:00+00:00,2026-01-05T04:00:00+00:00,100,100,100,100,1000
""",
        encoding="utf-8",
    )

    db = Database(str(db_path))
    db.initialize()
    repo = Repository(db)

    # Seed a durable open position before replay starts.
    # The replay must close it at the Day 1 EOD boundary.
    repo.set_cash(48980.0)
    repo.save_position(
        Position(
            symbol="ABC",
            qty=10,
            entry_price=Decimal("100"),
            stop_price=Decimal("98.5"),
            target_price=Decimal("105"),
            entry_fee=Decimal("20"),
            strategy_version="baseline-breakout-v1",
            entry_ts=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
            last_mark=Decimal("100"),
        )
    )
    db.close()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_replay.py",
            "--bars",
            str(bars_path),
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)

    fills = db.execute(
        """
        SELECT side, reason
        FROM simulated_fills
        ORDER BY rowid
        """
    ).fetchall()

    assert fills == [("SELL", "FORCED")]

    eod = db.execute(
        """
        SELECT COUNT(*)
        FROM account_snapshots
        WHERE is_eod=1
        """
    ).fetchone()[0]

    assert eod == 1

    eod_equity = db.execute(
        """
        SELECT equity
        FROM account_snapshots
        WHERE is_eod=1
        """
    ).fetchone()[0]

    last_eod_equity = db.execute(
        """
        SELECT value
        FROM kv_state
        WHERE key='last_eod_equity'
        """
    ).fetchone()[0]

    assert float(last_eod_equity) == eod_equity

    db.close()


def test_multiday_replay_is_idempotent_after_restart(tmp_path):
    bars_path = tmp_path / "multiday.csv"
    db_path = tmp_path / "multiday.sqlite3"

    bars_path.write_text(
        """symbol,start,end,open,high,low,close,volume
ABC,2026-01-02T09:55:00+00:00,2026-01-02T10:00:00+00:00,100,100,100,100,1000
ABC,2026-01-05T03:45:00+00:00,2026-01-05T04:00:00+00:00,100,100,100,100,1000
""",
        encoding="utf-8",
    )

    first = subprocess.run(
        [
            sys.executable,
            "scripts/run_replay.py",
            "--bars",
            str(bars_path),
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    db = sqlite3.connect(db_path)

    counts_before = {
        "bars": db.execute(
            "SELECT COUNT(*) FROM market_bars"
        ).fetchone()[0],
        "fills": db.execute(
            "SELECT COUNT(*) FROM simulated_fills"
        ).fetchone()[0],
        "eod": db.execute(
            "SELECT COUNT(*) FROM account_snapshots WHERE is_eod=1"
        ).fetchone()[0],
    }

    db.close()

    second = subprocess.run(
        [
            sys.executable,
            "scripts/run_replay.py",
            "--bars",
            str(bars_path),
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    db = sqlite3.connect(db_path)

    counts_after = {
        "bars": db.execute(
            "SELECT COUNT(*) FROM market_bars"
        ).fetchone()[0],
        "fills": db.execute(
            "SELECT COUNT(*) FROM simulated_fills"
        ).fetchone()[0],
        "eod": db.execute(
            "SELECT COUNT(*) FROM account_snapshots WHERE is_eod=1"
        ).fetchone()[0],
    }

    assert counts_after == counts_before
    assert counts_after["eod"] == 1

    db.close()
