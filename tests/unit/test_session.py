from datetime import datetime, timezone
from pathlib import Path

import pytest

from nse_paper_agent.data.calendar import TradingCalendar
from nse_paper_agent.session import SessionGuard, SessionState


ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "nse_holidays.yaml"


def cfg():
    return {
        "session": {
            "pre_open": "09:00",
            "open": "09:15",
            "entry_cutoff": "14:45",
            "close": "15:30",
            "calendar_path": str(CALENDAR),
        }
    }


def ist(hour, minute, day=15):
    from zoneinfo import ZoneInfo

    return datetime(
        2026,
        9,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )


def test_nse_calendar_weekend_and_holiday():
    cal = TradingCalendar(str(CALENDAR))

    assert cal.is_trading_day(__import__("datetime").date(2026, 9, 11))
    assert not cal.is_trading_day(__import__("datetime").date(2026, 9, 12))
    assert not cal.is_trading_day(__import__("datetime").date(2026, 9, 13))
    assert not cal.is_trading_day(__import__("datetime").date(2026, 10, 2))


def test_session_before_pre_open_is_closed():
    s = SessionGuard(cfg())
    assert s.state(ist(8, 59)) == SessionState.CLOSED


def test_session_pre_open():
    s = SessionGuard(cfg())
    assert s.state(ist(9, 0)) == SessionState.PRE_OPEN
    assert s.state(ist(9, 14)) == SessionState.PRE_OPEN


def test_session_open_and_entries():
    s = SessionGuard(cfg())

    assert s.state(ist(9, 15)) == SessionState.OPEN
    assert s.entries_allowed(ist(9, 15))
    assert s.entries_allowed(ist(14, 44))


def test_entry_cutoff_blocks_new_entries_but_allows_exits():
    s = SessionGuard(cfg())

    assert s.state(ist(14, 45)) == SessionState.ENTRY_CUTOFF
    assert not s.entries_allowed(ist(14, 45))
    assert s.snapshot(ist(14, 45)).exits_allowed


def test_close_enters_eod_state():
    s = SessionGuard(cfg())

    assert s.state(ist(15, 29)) == SessionState.ENTRY_CUTOFF
    assert s.state(ist(15, 30)) == SessionState.EOD
    assert not s.entries_allowed(ist(15, 30))
    assert s.snapshot(ist(15, 30)).exits_allowed


def test_after_market_close_remains_eod_for_trading_date():
    s = SessionGuard(cfg())

    assert s.state(ist(16, 0)) == SessionState.EOD
    assert s.state(ist(23, 59)) == SessionState.EOD


def test_next_midnight_is_non_trading_day_until_session_begins():
    s = SessionGuard(cfg())

    # September 16, 2026 is a weekday and therefore a trading day,
    # but before 09:00 it is outside the session.
    assert s.state(ist(0, 1, day=16)) == SessionState.CLOSED


def test_weekend_is_always_closed():
    s = SessionGuard(cfg())

    assert s.state(ist(10, 0, day=12)) == SessionState.CLOSED
    assert s.state(ist(14, 0, day=13)) == SessionState.CLOSED


def test_holiday_is_always_closed():
    s = SessionGuard(cfg())

    # 2026-10-02 is configured as an NSE holiday.
    dt = datetime(
        2026,
        10,
        2,
        10,
        0,
        tzinfo=timezone.utc,
    )

    assert s.state(dt) == SessionState.CLOSED
    assert not s.snapshot(dt).is_trading_day


def test_naive_datetime_is_rejected():
    s = SessionGuard(cfg())

    with pytest.raises(ValueError):
        s.state(datetime(2026, 9, 15, 10, 0))


class FakeDB:
    def __init__(self):
        self.state = {}

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value):
        self.state[key] = value

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeRepo:
    def __init__(self):
        self.db = FakeDB()


def test_daily_state_first_trading_day_uses_starting_capital():
    s = SessionGuard(cfg())
    repo = FakeRepo()

    value = s.ensure_daily_state(repo, ist(9, 15), 50000.0)

    assert value == 50000.0
    assert repo.db.get_state("daily_start_equity") == 50000.0
    assert repo.db.get_state("session_trading_date") == "2026-09-15"


def test_daily_state_same_day_restart_is_idempotent():
    s = SessionGuard(cfg())
    repo = FakeRepo()

    s.ensure_daily_state(repo, ist(9, 15), 50000.0)

    repo.db.set_state("daily_start_equity", 49750.0)
    repo.db.set_state("last_equity", 51000.0)

    value = s.ensure_daily_state(repo, ist(11, 0), 50000.0)

    assert value == 49750.0
    assert repo.db.get_state("session_trading_date") == "2026-09-15"


def test_new_trading_day_uses_last_marked_equity():
    s = SessionGuard(cfg())
    repo = FakeRepo()

    s.ensure_daily_state(repo, ist(9, 15), 50000.0)

    repo.db.set_state("last_equity", 51250.0)

    value = s.ensure_daily_state(
        repo,
        ist(9, 15, day=16),
        50000.0,
    )

    assert value == 51250.0
    assert repo.db.get_state("daily_start_equity") == 51250.0
    assert repo.db.get_state("session_trading_date") == "2026-09-16"


def test_weekend_does_not_roll_daily_state():
    s = SessionGuard(cfg())
    repo = FakeRepo()

    s.ensure_daily_state(repo, ist(9, 15), 50000.0)
    repo.db.set_state("daily_start_equity", 49800.0)
    repo.db.set_state("last_equity", 51000.0)

    value = s.ensure_daily_state(
        repo,
        ist(10, 0, day=12),
        50000.0,
    )

    assert value == 49800.0
    assert repo.db.get_state("session_trading_date") == "2026-09-15"


def test_timezone_conversion_is_authoritative():
    s = SessionGuard(cfg())

    # 03:45 UTC == 09:15 IST.
    dt = datetime(
        2026,
        9,
        15,
        3,
        45,
        tzinfo=timezone.utc,
    )

    assert s.state(dt) == SessionState.OPEN
    assert s.entries_allowed(dt)
