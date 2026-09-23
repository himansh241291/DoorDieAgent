from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
DEFAULT_INITIAL_CAPITAL = Decimal("50000")
DEFAULT_HARD_STOP_PCT = Decimal("0.015")
DEFAULT_TARGET_PCT = Decimal("0.05")
DEFAULT_SLIPPAGE_BPS = Decimal("10")
DEFAULT_BUY_FEE = Decimal("20")
DEFAULT_SELL_FEE = Decimal("20")
DEFAULT_TIME_EXITS = (60, 120, 180, 240)
DEFAULT_PROTECTION = (
    ("MFE_PROTECT_0.50_LOCK_0.00", Decimal("0.005"), Decimal("0")),
    ("MFE_PROTECT_0.75_LOCK_0.25", Decimal("0.0075"), Decimal("0.0025")),
)
DEFAULT_TRAILS = (
    ("MFE_TRAIL_0.50_GB_0.25", Decimal("0.005"), Decimal("0.0025")),
    ("MFE_TRAIL_0.75_GB_0.25", Decimal("0.0075"), Decimal("0.0025")),
    ("MFE_TRAIL_1.00_GB_0.50", Decimal("0.01"), Decimal("0.005")),
)


@dataclass(frozen=True)
class Bar:
    end: datetime
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Entry:
    id: int
    symbol: str
    qty: int
    price: Decimal
    ts: datetime


@dataclass(frozen=True)
class TradeResult:
    entry_id: int
    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: Decimal
    exit_price: Decimal
    qty: int
    gross_pnl: Decimal
    net_pnl: Decimal
    reason: str
    mfe: Decimal
    mae: Decimal


def parse_bars(path: str | Path) -> dict[str, list[Bar]]:
    result: dict[str, list[Bar]] = {}
    with open(path, encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
        index = {name: pos for pos, name in enumerate(header)}
        required = {"symbol", "end", "high", "low", "close"}
        missing = required - set(index)
        if missing:
            raise ValueError(f"missing bar columns: {sorted(missing)}")
        for line in handle:
            if not line.strip():
                continue
            row = line.rstrip("\n").split(",")
            symbol = row[index["symbol"]]
            result.setdefault(symbol, []).append(
                Bar(
                    end=datetime.fromisoformat(row[index["end"]]),
                    high=Decimal(row[index["high"]]),
                    low=Decimal(row[index["low"]]),
                    close=Decimal(row[index["close"]]),
                )
            )
    for bars in result.values():
        bars.sort(key=lambda bar: bar.end)
    return result


def load_entries(db_path: str | Path) -> list[Entry]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, symbol, qty, entry_price, entry_ts_utc
            FROM closed_trades
            ORDER BY entry_ts_utc, id
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        Entry(
            id=int(row[0]),
            symbol=str(row[1]),
            qty=int(row[2]),
            price=Decimal(str(row[3])),
            ts=datetime.fromisoformat(row[4]),
        )
        for row in rows
    ]


def _sell_price(price: Decimal, slippage_bps: Decimal) -> Decimal:
    return price * (Decimal("1") - slippage_bps / Decimal("10000"))


def _same_session_bars(entry: Entry, bars: list[Bar]) -> list[Bar]:
    session_date = entry.ts.astimezone(IST).date()
    return [
        bar
        for bar in bars
        if bar.end > entry.ts and bar.end.astimezone(IST).date() == session_date
    ]


def _result(
    entry: Entry,
    bar: Bar,
    reason: str,
    exit_price: Decimal,
    path: list[Bar],
) -> TradeResult:
    gross = (exit_price - entry.price) * entry.qty
    net = gross - DEFAULT_BUY_FEE - DEFAULT_SELL_FEE
    mfe = max(
        ((bar.high - entry.price) / entry.price for bar in path),
        default=Decimal("0"),
    )
    mae = min(
        ((bar.low - entry.price) / entry.price for bar in path),
        default=Decimal("0"),
    )
    return TradeResult(
        entry.id,
        entry.symbol,
        entry.ts,
        bar.end,
        entry.price,
        exit_price,
        entry.qty,
        gross,
        net,
        reason,
        mfe,
        mae,
    )


def _hard_levels(entry: Entry) -> tuple[Decimal, Decimal]:
    stop = entry.price * (Decimal("1") - DEFAULT_HARD_STOP_PCT)
    target = entry.price * (Decimal("1") + DEFAULT_TARGET_PCT)
    return stop, target


def simulate(
    entry: Entry,
    bars: list[Bar],
    policy: str,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
) -> TradeResult | None:
    future = _same_session_bars(entry, bars)
    if not future:
        return None

    stop, target = _hard_levels(entry)
    path: list[Bar] = []
    trailing_stop: Decimal | None = None
    protection_stop: Decimal | None = None
    armed = False

    time_minutes: int | None = None
    if policy.startswith("TIME_"):
        time_minutes = int(policy.split("_", 1)[1][:-1])

    protection_activation: Decimal | None = None
    protection_lock: Decimal | None = None
    if policy.startswith("MFE_PROTECT_"):
        parts = policy.split("_")
        protection_activation = Decimal(parts[2]) / Decimal("100")
        protection_lock = Decimal(parts[4]) / Decimal("100")

    trail_activation: Decimal | None = None
    trail_giveback: Decimal | None = None
    if policy.startswith("MFE_TRAIL_"):
        parts = policy.split("_")
        trail_activation = Decimal(parts[2]) / Decimal("100")
        trail_giveback = Decimal(parts[4]) / Decimal("100")

    cutoff = entry.ts + timedelta(minutes=time_minutes) if time_minutes else None

    for index, bar in enumerate(future):
        path.append(bar)

        # Hard safety exits remain immutable and are evaluated before research exits.
        if bar.low <= stop:
            return _result(
                entry,
                bar,
                "STOP",
                _sell_price(stop, slippage_bps),
                path,
            )
        if bar.high >= target:
            return _result(
                entry,
                bar,
                "TARGET",
                _sell_price(target, slippage_bps),
                path,
            )

        high_return = (bar.high - entry.price) / entry.price

        if protection_activation is not None:
            if high_return >= protection_activation and not armed:
                armed = True
                protection_stop = (
                    entry.price * (Decimal("1") + protection_lock)
                )
                # Do not use the trigger bar for the protection exit. OHLC
                # does not reveal whether the high occurred before the low.
            elif armed and protection_stop is not None and index > 0 and bar.low <= protection_stop:
                return _result(
                    entry,
                    bar,
                    "MFE_PROTECT",
                    _sell_price(protection_stop, slippage_bps),
                    path,
                )

        if trail_activation is not None and trail_giveback is not None:
            if high_return >= trail_activation and trailing_stop is None:
                trailing_stop = bar.high * (Decimal("1") - trail_giveback)
                armed = True
                # Arm on the trigger bar; trailing stop becomes executable
                # only on the next bar to avoid intrabar path assumptions.
            elif trailing_stop is not None and index > 0:
                candidate = bar.high * (Decimal("1") - trail_giveback)
                if candidate > trailing_stop:
                    trailing_stop = candidate
                if bar.low <= trailing_stop:
                    return _result(
                        entry,
                        bar,
                        "MFE_TRAIL",
                        _sell_price(trailing_stop, slippage_bps),
                        path,
                    )

        if cutoff is not None and bar.end >= cutoff:
            return _result(
                entry,
                bar,
                f"TIME_{time_minutes}M",
                _sell_price(bar.close, slippage_bps),
                path,
            )

    return _result(
        entry,
        future[-1],
        "EOD",
        _sell_price(future[-1].close, slippage_bps),
        path,
    )


def actual_trade(entry: Entry, db_path: str | Path) -> TradeResult | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT exit_ts_utc, exit_price, gross_pnl, net_pnl, exit_reason,
                   mae, mfe
            FROM closed_trades
            WHERE id = ?
            """,
            (entry.id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return TradeResult(
        entry.id,
        entry.symbol,
        entry.ts,
        datetime.fromisoformat(row[0]),
        entry.price,
        Decimal(str(row[1])),
        entry.qty,
        Decimal(str(row[2])),
        Decimal(str(row[3])),
        str(row[4]),
        Decimal(str(row[6])) if row[6] is not None else Decimal("0"),
        Decimal(str(row[5])) if row[5] is not None else Decimal("0"),
    )


def summarize(results: list[TradeResult], initial_capital: Decimal = DEFAULT_INITIAL_CAPITAL) -> dict[str, object]:
    if not results:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
            "expectancy": 0.0,
            "max_drawdown_pct": 0.0,
            "median_net": None,
            "mean_mfe": None,
            "mean_mae": None,
            "mean_capture_ratio": None,
            "exit_reasons": {},
        }

    ordered = sorted(results, key=lambda result: (result.exit_ts, result.entry_id))
    pnl = [float(result.net_pnl) for result in ordered]
    equity = float(initial_capital)
    peak = equity
    max_dd = 0.0
    captures = []

    for result in ordered:
        equity += float(result.net_pnl)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / float(initial_capital))
        mfe = float(result.mfe)
        if mfe > 0:
            captures.append(float((result.exit_price - result.entry_price) / result.entry_price) / mfe)

    reasons: dict[str, int] = {}
    for result in ordered:
        reasons[result.reason] = reasons.get(result.reason, 0) + 1

    return {
        "trades": len(ordered),
        "wins": sum(value > 0 for value in pnl),
        "losses": sum(value <= 0 for value in pnl),
        "win_rate": sum(value > 0 for value in pnl) / len(pnl),
        "gross_pnl": float(sum(result.gross_pnl for result in ordered)),
        "fees": float(len(ordered) * (DEFAULT_BUY_FEE + DEFAULT_SELL_FEE)),
        "net_pnl": float(sum(pnl)),
        "expectancy": float(sum(pnl) / len(pnl)),
        "max_drawdown_pct": max_dd,
        "median_net": median(pnl),
        "mean_mfe": float(sum(result.mfe for result in ordered) / len(ordered)),
        "mean_mae": float(sum(result.mae for result in ordered) / len(ordered)),
        "mean_capture_ratio": (
            sum(captures) / len(captures) if captures else None
        ),
        "exit_reasons": reasons,
    }


def policies() -> list[str]:
    result = ["EOD", *[f"TIME_{minutes}M" for minutes in DEFAULT_TIME_EXITS]]
    result.extend(name for name, _, _ in DEFAULT_PROTECTION)
    result.extend(name for name, _, _ in DEFAULT_TRAILS)
    return result


def run_db(db_path: str | Path, bars_by_symbol: dict[str, list[Bar]], policy: str) -> list[TradeResult]:
    entries = load_entries(db_path)
    results: list[TradeResult] = []
    for entry in entries:
        if policy == "ACTUAL":
            result = actual_trade(entry, db_path)
        else:
            result = simulate(entry, bars_by_symbol.get(entry.symbol, []), policy)
        if result is not None:
            results.append(result)
    return results


def run_family(
    development_db: str | Path,
    holdout_db: str | Path,
    bars_path: str | Path,
) -> dict[str, object]:
    bars = parse_bars(bars_path)
    payload: dict[str, object] = {}
    for split, db in (("development", development_db), ("holdout", holdout_db)):
        payload[split] = {}
        for policy in ["ACTUAL", *policies()]:
            if policy == "ACTUAL":
                results = run_db(db, bars, "ACTUAL")
            else:
                results = run_db(db, bars, policy)
            payload[split][policy] = summarize(results)
    return payload
