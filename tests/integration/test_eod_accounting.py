from datetime import datetime, timezone
from pathlib import Path

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.session import SessionGuard


ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "nse_holidays.yaml"


def session_cfg():
    return {
        "session": {
            "pre_open": "09:00",
            "open": "09:15",
            "entry_cutoff": "14:45",
            "close": "15:30",
            "calendar_path": str(CALENDAR),
        }
    }


def ist_time(hour, minute, day):
    from zoneinfo import ZoneInfo

    return datetime(
        2026,
        9,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_new_trading_day_starts_from_previous_eod_equity(tmp_path):
    db = Database(str(tmp_path / "eod.sqlite3"))
    db.initialize()
    repo = Repository(db)
    session = SessionGuard(session_cfg())

    first = ist_time(15, 30, 15)

    session.ensure_daily_state(repo, first, 50000.0)

    repo.set_cash(51200.0)
    repo.db.set_state("last_equity", 51200.0)

    repo.record_eod_snapshot(
        trading_date="2026-09-15",
        ts=first,
        cash=51200.0,
        equity=51200.0,
        gross=0.0,
        daily_start_equity=50000.0,
        drawdown5=0.0,
    )

    next_day = ist_time(9, 15, 16)

    daily_start = session.ensure_daily_state(
        repo,
        next_day,
        50000.0,
    )

    assert daily_start == 51200.0
    assert repo.db.get_state("session_trading_date") == "2026-09-16"

    db.close()


def test_same_day_restart_preserves_daily_start_after_eod_mark(tmp_path):
    db = Database(str(tmp_path / "restart.sqlite3"))
    db.initialize()
    repo = Repository(db)
    session = SessionGuard(session_cfg())

    morning = ist_time(9, 30, 15)
    session.ensure_daily_state(repo, morning, 50000.0)

    repo.db.set_state("daily_start_equity", 49750.0)
    repo.db.set_state("last_equity", 50100.0)

    afternoon_restart = ist_time(14, 0, 15)

    assert session.ensure_daily_state(
        repo,
        afternoon_restart,
        50000.0,
    ) == 49750.0

    db.close()


def test_eod_timestamp_persists_correct_ist_timezone(tmp_path):
    db = Database(str(tmp_path / "timestamp.sqlite3"))
    db.initialize()
    repo = Repository(db)

    ts = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    repo.record_eod_snapshot(
        trading_date="2026-09-15",
        ts=ts,
        cash=50000,
        equity=50000,
        gross=0,
        daily_start_equity=50000,
        drawdown5=0,
    )

    row = db.conn.execute(
        """
        SELECT ts_utc, ts_ist, trading_date, is_eod
        FROM account_snapshots
        WHERE is_eod=1
        """
    ).fetchone()

    assert row["ts_utc"] == "2026-09-15T10:00:00+00:00"
    assert row["ts_ist"] == "2026-09-15T15:30:00+05:30"
    assert row["trading_date"] == "2026-09-15"
    assert row["is_eod"] == 1

    db.close()


def test_eod_marks_are_distinct_trading_days(tmp_path):
    db = Database(str(tmp_path / "distinct.sqlite3"))
    db.initialize()
    repo = Repository(db)

    for d, equity in [
        ("2026-09-15", 50000),
        ("2026-09-16", 50100),
        ("2026-09-17", 50200),
    ]:
        ts = datetime.fromisoformat(
            f"{d}T15:30:00+05:30"
        )
        repo.record_eod_snapshot(
            trading_date=d,
            ts=ts,
            cash=equity,
            equity=equity,
            gross=0,
            daily_start_equity=50000,
            drawdown5=0,
        )

    assert [x["trading_date"] for x in repo.eod_marks(5)] == [
        "2026-09-17",
        "2026-09-16",
        "2026-09-15",
    ]

    db.close()


def test_daily_start_never_uses_intraday_last_equity(tmp_path):
    db = Database(str(tmp_path / "baseline.sqlite3"))
    db.initialize()
    repo = Repository(db)
    session = SessionGuard(session_cfg())

    day1 = ist_time(10, 0, 15)
    session.ensure_daily_state(repo, day1, 50000.0)

    # Simulate a large intraday move.
    repo.db.set_state("last_equity", 60000.0)

    # No completed EOD mark exists.
    day2 = ist_time(9, 15, 16)

    # Same database has not completed day 1, so this test intentionally
    # starts with the existing trading-date state removed.
    repo.db.set_state("session_trading_date", "2026-09-14")

    assert session.ensure_daily_state(
        repo,
        day2,
        50000.0,
    ) == 50000.0

    db.close()


def test_completed_eod_mark_becomes_next_day_baseline(tmp_path):
    db = Database(str(tmp_path / "multi_day.sqlite3"))
    db.initialize()
    repo = Repository(db)
    session = SessionGuard(session_cfg())

    day1 = ist_time(15, 30, 15)

    session.ensure_daily_state(repo, day1, 50000.0)

    assert repo.record_eod_snapshot(
        "2026-09-15",
        day1,
        50750.0,
        50750.0,
        0.0,
        50000.0,
        0.0,
    )

    day2 = ist_time(9, 15, 16)

    assert session.ensure_daily_state(
        repo,
        day2,
        50000.0,
    ) == 50750.0

    assert repo.db.get_state("daily_start_equity") == 50750.0

    db.close()


def test_eod_state_survives_database_reopen(tmp_path):
    path = str(tmp_path / "persist.sqlite3")

    db = Database(path)
    db.initialize()
    repo = Repository(db)

    ts = ist_time(15, 30, 15)

    repo.record_eod_snapshot(
        "2026-09-15",
        ts,
        50325.0,
        50325.0,
        0.0,
        50000.0,
        0.0,
    )

    db.close()

    db = Database(path)
    db.initialize()
    repo = Repository(db)

    assert repo.db.get_state("last_eod_equity") == 50325.0
    assert repo.db.get_state("last_eod_trading_date") == "2026-09-15"
    assert len(repo.eod_marks(5)) == 1

    db.close()
