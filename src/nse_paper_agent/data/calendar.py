from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SessionWindow:
    open: time
    close: time


class TradingCalendar:
    def __init__(self, path: str):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        self.holidays = {
            date.fromisoformat(str(x)) for x in raw.get("holidays", [])
        }
        self.special_sessions = {
            date.fromisoformat(str(day)): SessionWindow(
                open=time.fromisoformat(str(values["open"])),
                close=time.fromisoformat(str(values["close"])),
            )
            for day, values in (raw.get("special_sessions", {}) or {}).items()
        }

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def session_window(
        self,
        d: date,
        default_open: time,
        default_close: time,
    ) -> SessionWindow | None:
        if not self.is_trading_day(d):
            return None
        return self.special_sessions.get(
            d,
            SessionWindow(open=default_open, close=default_close),
        )
