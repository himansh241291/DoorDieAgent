#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SLIPPAGE_BPS = Decimal("10")
BUY_FEE = Decimal("20")
SELL_FEE = Decimal("20")
TIME_EXITS_MINUTES = (30, 45, 60, 90, 120, 180, 240)
TARGETS_PCT = (0.25, 0.50, 0.75, 1.00, 1.50)
STOPS_PCT = (0.50, 0.75, 1.00, 1.25, 1.50)


@dataclass(frozen=True)
class Bar:
    end: datetime
    open: Decimal
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
class Result:
    exit_price: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    exit_ts: datetime
    reason: str


def parse_bars(path: str) -> dict[str, list[Bar]]:
    result: dict[str, list[Bar]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            result.setdefault(row["symbol"], []).append(
                Bar(
                    end=datetime.fromisoformat(row["end"]),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                )
            )
    for bars in result.values():
        bars.sort(key=lambda item: item.end)
    return result


def load_entries(db_path: str) -> list[Entry]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT id, symbol, qty, entry_price, entry_ts_utc
        FROM closed_trades
        ORDER BY entry_ts_utc, id
        """
    ).fetchall()
    conn.close()
    return [
        Entry(int(row[0]), row[1], int(row[2]), Decimal(str(row[3])), datetime.fromisoformat(row[4]))
        for row in rows
    ]


def sell_price(price: Decimal) -> Decimal:
    return price * (Decimal("1") - SLIPPAGE_BPS / Decimal("10000"))


def close_at_bar(entry: Entry, bar: Bar, reason: str) -> Result:
    exit_price = sell_price(bar.close)
    gross = (exit_price - entry.price) * entry.qty
    net = gross - BUY_FEE - SELL_FEE
    return Result(exit_price, gross, net, bar.end, reason)


def same_session_bars(entry: Entry, bars: list[Bar]) -> list[Bar]:
    entry_date = entry.ts.astimezone(IST).date()
    return [
        bar
        for bar in bars
        if bar.end > entry.ts and bar.end.astimezone(IST).date() == entry_date
    ]


def simulate_time_exit(entry: Entry, bars: list[Bar], minutes: int) -> Result | None:
    future = same_session_bars(entry, bars)
    cutoff = entry.ts + timedelta(minutes=minutes)
    bar = next((item for item in future if item.end >= cutoff), None)
    return close_at_bar(entry, bar, f"TIME_{minutes}M") if bar else None


def simulate_bracket(entry: Entry, bars: list[Bar], stop_pct: float, target_pct: float) -> Result | None:
    stop = entry.price * (Decimal("1") - Decimal(str(stop_pct)) / Decimal("100"))
    target = entry.price * (Decimal("1") + Decimal(str(target_pct)) / Decimal("100"))
    future = same_session_bars(entry, bars)
    for bar in future:
        # OHLC does not reveal intrabar path. Conservative assumption: stop first
        # whenever both thresholds are touched in the same 5-minute candle.
        if bar.low <= stop:
            exit_price = sell_price(stop)
            gross = (exit_price - entry.price) * entry.qty
            return Result(exit_price, gross, gross - BUY_FEE - SELL_FEE, bar.end, f"STOP_{stop_pct:.2f}PCT")
        if bar.high >= target:
            exit_price = sell_price(target)
            gross = (exit_price - entry.price) * entry.qty
            return Result(exit_price, gross, gross - BUY_FEE - SELL_FEE, bar.end, f"TARGET_{target_pct:.2f}PCT")

    eod = future[-1] if future else None
    return close_at_bar(entry, eod, "EOD_FALLBACK") if eod else None


def summarize(label: str, results: Iterable[Result], entries: int) -> None:
    rows = list(results)
    pnls = [float(result.net_pnl) for result in rows]
    gross = sum(float(result.gross_pnl) for result in rows)
    net = sum(pnls)
    wins = sum(value > 0 for value in pnls)
    losses = sum(value <= 0 for value in pnls)
    print(
        label,
        {
            "entries_available": entries,
            "results": len(rows),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": wins / len(rows) * 100.0 if rows else 0.0,
            "gross_pnl": gross,
            "fees": len(rows) * float(BUY_FEE + SELL_FEE),
            "net_pnl": net,
            "expectancy": net / len(rows) if rows else 0.0,
            "median_net": median(pnls) if pnls else None,
            "worst_net": min(pnls) if pnls else None,
            "best_net": max(pnls) if pnls else None,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Controlled fixed-entry exit experiments for V1 replay entries."
    )
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    bars_by_symbol = parse_bars(args.bars)
    entries = load_entries(args.db)
    if not entries:
        raise SystemExit("no closed-trade entries found")

    print("EXPERIMENT=V1_FIXED_ENTRY_EXIT_RESEARCH")
    print("WARNING=entry events are held fixed; portfolio capacity/risk interactions are intentionally not re-simulated")
    print("WARNING=bracket experiments use OHLC path ambiguity with conservative STOP-first ordering")
    print("WARNING=time exits and EOD fallback remain within the same IST trading session")
    print(f"entries={len(entries)}")

    for minutes in TIME_EXITS_MINUTES:
        results = []
        for entry in entries:
            result = simulate_time_exit(entry, bars_by_symbol.get(entry.symbol, []), minutes)
            if result:
                results.append(result)
        summarize(f"TIME_{minutes}M", results, len(entries))

    for stop_pct in STOPS_PCT:
        for target_pct in TARGETS_PCT:
            results = []
            for entry in entries:
                result = simulate_bracket(entry, bars_by_symbol.get(entry.symbol, []), stop_pct, target_pct)
                if result:
                    results.append(result)
            summarize(f"BRACKET_STOP_{stop_pct:.2f}_TARGET_{target_pct:.2f}", results, len(entries))


if __name__ == "__main__":
    main()
