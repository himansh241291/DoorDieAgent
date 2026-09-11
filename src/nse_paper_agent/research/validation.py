from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class ReplayValidation:
    trades: int
    wins: int
    losses: int
    net_pnl: float
    expectancy: float
    win_rate: float
    max_drawdown: float
    trading_days: int
    forced_exits: int
    stop_exits: int
    target_exits: int
    blocked_entries: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "net_pnl": self.net_pnl,
            "net_expectancy": self.expectancy,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "trading_days": self.trading_days,
            "forced_exits": self.forced_exits,
            "stop_exits": self.stop_exits,
            "target_exits": self.target_exits,
            "blocked_entries": self.blocked_entries,
        }


def validate_replay(db) -> ReplayValidation:
    trades = db.conn.execute("SELECT net_pnl, exit_reason FROM closed_trades ORDER BY id").fetchall()
    marks = db.conn.execute(
        "SELECT trading_date, equity FROM account_snapshots WHERE is_eod=1 ORDER BY trading_date"
    ).fetchall()
    blocked = db.conn.execute(
        "SELECT COUNT(*) AS n FROM risk_events WHERE event_type='ENTRY' AND allowed=0"
    ).fetchone()["n"]

    pnls = [float(row["net_pnl"]) for row in trades]
    if not all(isfinite(value) for value in pnls):
        raise ValueError("replay contains non-finite trade PnL")

    wins = sum(value > 0 for value in pnls)
    losses = sum(value <= 0 for value in pnls)
    net_pnl = sum(pnls)
    expectancy = net_pnl / len(pnls) if pnls else 0.0
    win_rate = wins / len(pnls) if pnls else 0.0

    peak = None
    max_drawdown = 0.0
    for row in marks:
        equity = float(row["equity"])
        if not isfinite(equity) or equity <= 0:
            raise ValueError("replay contains invalid EOD equity")
        peak = equity if peak is None else max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)

    reasons = [row["exit_reason"] for row in trades]
    return ReplayValidation(
        trades=len(trades),
        wins=wins,
        losses=losses,
        net_pnl=net_pnl,
        expectancy=expectancy,
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        trading_days=len(marks),
        forced_exits=reasons.count("FORCED"),
        stop_exits=reasons.count("STOP"),
        target_exits=reasons.count("TARGET"),
        blocked_entries=int(blocked),
    )


def require_long_duration(validation: ReplayValidation, min_trading_days: int = 60) -> None:
    if validation.trading_days < min_trading_days:
        raise ValueError(f"insufficient replay duration: {validation.trading_days} < {min_trading_days} trading days")
    if validation.trades and validation.forced_exits > validation.trades:
        raise ValueError("invalid forced-exit count")
