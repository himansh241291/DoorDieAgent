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
