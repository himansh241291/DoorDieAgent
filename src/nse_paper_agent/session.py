from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum

from nse_paper_agent.data.calendar import TradingCalendar
from nse_paper_agent.utils.time import IST


class SessionState(str, Enum):
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    ENTRY_CUTOFF = "ENTRY_CUTOFF"
    EOD = "EOD"


@dataclass(frozen=True)
class SessionSnapshot:
    trading_date: date
    state: SessionState
    is_trading_day: bool
    entries_allowed: bool
    exits_allowed: bool


class SessionGuard:
    """
    Authoritative NSE equity session/calendar logic.

    All session decisions are made in Asia/Kolkata time.
    """

    def __init__(self, cfg):
        session = cfg["session"]

        self.timezone = IST
        self.pre_open = time.fromisoformat(session.get("pre_open", "09:00"))
        self.open = time.fromisoformat(session["open"])
        self.entry_cutoff = time.fromisoformat(session["entry_cutoff"])
        self.close = time.fromisoformat(session["close"])

        if not (
            self.pre_open <= self.open <= self.entry_cutoff <= self.close
        ):
            raise ValueError(
                "invalid session configuration: "
                "pre_open <= open <= entry_cutoff <= close is required"
            )

        self.calendar = TradingCalendar(session["calendar_path"])

    def trading_day(self, d: date) -> bool:
        return self.calendar.is_trading_day(d)

    def state(self, now: datetime) -> SessionState:
        """
        Return the authoritative session state for an aware timestamp.

        The timestamp is converted to IST before evaluating the session.
        """
        if now.tzinfo is None:
            raise ValueError("session timestamp must be timezone-aware")

        ist = now.astimezone(self.timezone)
        d = ist.date()

        if not self.trading_day(d):
            return SessionState.CLOSED

        t = ist.time()

        if t < self.pre_open:
            return SessionState.CLOSED

        if t < self.open:
            return SessionState.PRE_OPEN

        if t < self.entry_cutoff:
            return SessionState.OPEN

        if t < self.close:
            return SessionState.ENTRY_CUTOFF

        # From the official continuous-session close until midnight,
        # the trading day is considered EOD.
        return SessionState.EOD

    def snapshot(self, now: datetime) -> SessionSnapshot:
        state = self.state(now)
        ist = now.astimezone(self.timezone)

        trading = self.trading_day(ist.date())

        return SessionSnapshot(
            trading_date=ist.date(),
            state=state,
            is_trading_day=trading,
            entries_allowed=state == SessionState.OPEN,
            exits_allowed=trading and state in {
                SessionState.OPEN,
                SessionState.ENTRY_CUTOFF,
                SessionState.EOD,
            },
        )

    def is_open(self, now: datetime) -> bool:
        return self.state(now) in {
            SessionState.OPEN,
            SessionState.ENTRY_CUTOFF,
        }

    def entries_allowed(self, now: datetime) -> bool:
        return self.state(now) == SessionState.OPEN

    def is_eod(self, now: datetime) -> bool:
        return self.state(now) == SessionState.EOD

    def is_pre_open(self, now: datetime) -> bool:
        return self.state(now) == SessionState.PRE_OPEN

    def current_trading_date(self, now: datetime) -> date | None:
        ist = now.astimezone(self.timezone)
        return ist.date() if self.trading_day(ist.date()) else None

    def ensure_daily_state(self, repo, now: datetime, starting_capital: float) -> float:
        """
        Ensure daily_start_equity belongs to the current NSE trading date.

        Same-day restart:
            preserve existing daily_start_equity.

        New trading day:
            initialize from the last marked equity.

        First-ever trading day:
            initialize from starting capital.

        Weekend/holiday:
            do not roll the trading-day state.
        """
        if now.tzinfo is None:
            raise ValueError("session timestamp must be timezone-aware")

        ist = now.astimezone(self.timezone)
        current_date = ist.date()

        if not self.trading_day(current_date):
            return float(
                repo.db.get_state("daily_start_equity", starting_capital)
            )

        stored_date = repo.db.get_state("session_trading_date")

        if stored_date == current_date.isoformat():
            return float(
                repo.db.get_state("daily_start_equity", starting_capital)
            )

        last_eod_equity = repo.db.get_state("last_eod_equity")

        if last_eod_equity is None:
            daily_start = float(starting_capital)
        else:
            daily_start = float(last_eod_equity)

        with repo.db.transaction():
            repo.db.set_state(
                "session_trading_date",
                current_date.isoformat(),
            )
            repo.db.set_state(
                "daily_start_equity",
                daily_start,
            )

        return daily_start
