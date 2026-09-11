import csv
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from nse_paper_agent.data.provider import load_bars_csv


FIXTURE = "tests/fixtures/sample_bars.csv"


def test_fixture_is_deterministic():
    a = load_bars_csv(FIXTURE)
    b = load_bars_csv(FIXTURE)

    assert [(x.symbol, x.end, x.close) for x in a] == [(x.symbol, x.end, x.close) for x in b]


def test_replay_persists_market_state(tmp_path):
    db_path = tmp_path / "replay.sqlite3"
    result = subprocess.run([sys.executable, "scripts/run_replay.py", "--bars", FIXTURE, "--db", str(db_path)], check=True, capture_output=True, text=True)

    assert "'symbols': 1" in result.stdout
    assert "'bars': 35" in result.stdout
    assert "'cash': 50000.0" in result.stdout
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)
    assert db.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 35
    assert db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 35
    assert db.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 35
    assert db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM simulated_fills").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0] == 0
    db.close()


def test_multiday_replay_forces_eod_exit_and_rolls_eod_equity(tmp_path):
    from decimal import Decimal
    from nse_paper_agent.domain.models import Position
    from nse_paper_agent.persistence.db import Database
    from nse_paper_agent.persistence.repository import Repository

    bars_path = tmp_path / "multiday.csv"
    db_path = tmp_path / "multiday.sqlite3"
    bars_path.write_text("""symbol,start,end,open,high,low,close,volume
ABC,2026-01-02T09:55:00+00:00,2026-01-02T10:00:00+00:00,100,100,100,100,1000
ABC,2026-01-05T03:45:00+00:00,2026-01-05T04:00:00+00:00,100,100,100,100,1000
""", encoding="utf-8")

    db = Database(str(db_path))
    db.initialize()
    repo = Repository(db)
    repo.set_cash(48980.0)
    repo.save_position(Position("ABC", 10, Decimal("100"), Decimal("98.5"), Decimal("105"), Decimal("20"), "baseline-breakout-v1", datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc), Decimal("100")))
    db.close()

    result = subprocess.run([sys.executable, "scripts/run_replay.py", "--bars", str(bars_path), "--db", str(db_path)], check=True, capture_output=True, text=True)
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)
    assert db.execute("SELECT side, reason FROM simulated_fills ORDER BY rowid").fetchall() == [("SELL", "FORCED")]
    assert db.execute("SELECT COUNT(*) FROM account_snapshots WHERE is_eod=1").fetchone()[0] == 1
    eod_equity = db.execute("SELECT equity FROM account_snapshots WHERE is_eod=1").fetchone()[0]
    last_eod_equity = db.execute("SELECT value FROM kv_state WHERE key='last_eod_equity'").fetchone()[0]
    assert float(last_eod_equity) == eod_equity
    db.close()


def test_multiday_replay_is_idempotent_after_restart(tmp_path):
    bars_path = tmp_path / "multiday.csv"
    db_path = tmp_path / "multiday.sqlite3"
    bars_path.write_text("""symbol,start,end,open,high,low,close,volume
ABC,2026-01-02T09:55:00+00:00,2026-01-02T10:00:00+00:00,100,100,100,100,1000
ABC,2026-01-05T03:45:00+00:00,2026-01-05T04:00:00+00:00,100,100,100,100,1000
""", encoding="utf-8")

    subprocess.run([sys.executable, "scripts/run_replay.py", "--bars", str(bars_path), "--db", str(db_path)], check=True, capture_output=True, text=True)
    db = sqlite3.connect(db_path)
    counts_before = {"bars": db.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0], "fills": db.execute("SELECT COUNT(*) FROM simulated_fills").fetchone()[0], "eod": db.execute("SELECT COUNT(*) FROM account_snapshots WHERE is_eod=1").fetchone()[0]}
    db.close()

    subprocess.run([sys.executable, "scripts/run_replay.py", "--bars", str(bars_path), "--db", str(db_path)], check=True, capture_output=True, text=True)
    db = sqlite3.connect(db_path)
    counts_after = {"bars": db.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0], "fills": db.execute("SELECT COUNT(*) FROM simulated_fills").fetchone()[0], "eod": db.execute("SELECT COUNT(*) FROM account_snapshots WHERE is_eod=1").fetchone()[0]}
    assert counts_after == counts_before
    assert counts_after["eod"] == 1
    db.close()


def test_replay_uses_real_market_intelligence_with_benchmark_and_universe(tmp_path):
    bars_path = tmp_path / "market_intelligence.csv"
    db_path = tmp_path / "market_intelligence.sqlite3"
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    start = date(2026, 1, 2)
    rows = []
    day = start
    index = 0
    while index < 80:
        if day.weekday() < 5:
            ts = datetime(day.year, day.month, day.day, 4, 0, tzinfo=timezone.utc)
            benchmark = 100.0 + index * 0.5
            rows.append(["NIFTY50", ts - timedelta(minutes=5), ts, benchmark, benchmark + 0.1, benchmark - 0.1, benchmark, 1000000])
            for offset, symbol in enumerate(symbols):
                close = 50.0 + offset + index * 0.5
                rows.append([symbol, ts - timedelta(minutes=5), ts, close, close + 0.1, close - 0.1, close, 1000000])
            index += 1
        day += timedelta(days=1)

    with bars_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "start", "end", "open", "high", "low", "close", "volume"])
        for symbol, start_ts, end_ts, open_, high, low, close, volume in rows:
            writer.writerow([symbol, start_ts.isoformat(), end_ts.isoformat(), open_, high, low, close, volume])

    result = subprocess.run([sys.executable, "scripts/run_replay.py", "--bars", str(bars_path), "--db", str(db_path)], check=True, capture_output=True, text=True)
    assert "'symbols': 6" in result.stdout
    assert "'trading_symbols': 5" in result.stdout

    db = sqlite3.connect(db_path)
    regimes = db.execute("SELECT regime, reason, metrics_json FROM market_regimes ORDER BY rowid").fetchall()
    assert regimes
    assert any(regime == "RISK_ON" and reason == "trend_and_breadth_confirmed" for regime, reason, _ in regimes)
    assert any('"breadth20": 1.0' in metrics for _, _, metrics in regimes)
    assert not any('legacy_fixture_without_benchmark' in metrics for _, _, metrics in regimes)
    db.close()
