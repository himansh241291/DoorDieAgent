#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar, Regime
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy

IST = ZoneInfo("Asia/Kolkata")
SYMBOLS = ["ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON"]
BENCHMARK = "NIFTY50"
EVENT_TIME = time(13, 55)


def weekdays(start: date, count: int) -> list[date]:
    out: list[date] = []
    current = start
    while len(out) < count:
        if current.weekday() < 5:
            out.append(current)
        current += timedelta(days=1)
    return out


def price_pattern(symbol_index: int, day_index: int, bar_index: int) -> Decimal:
    base = Decimal(str(50 + symbol_index * 7)) * Decimal("1.0025") ** day_index
    if bar_index < 36:
        return base
    return base * (Decimal("1.0003") if bar_index % 2 == 0 else Decimal("0.9997"))


def outcome(symbol_index: int, day_index: int, event_close: Decimal) -> Decimal:
    # One target, one stop, and three controlled EOD outcomes each mature day.
    role = symbol_index
    if role == 0:
        return event_close * Decimal("1.070")
    if role == 1:
        return event_close * Decimal("0.970")
    if role == 2:
        return event_close * (Decimal("1.005") if day_index % 2 == 0 else Decimal("1.001"))
    if role == 3:
        return event_close * (Decimal("0.995") if day_index % 2 == 0 else Decimal("0.999"))
    return event_close * Decimal("1.002")


def make_row(symbol: str, start: datetime, end: datetime, close: Decimal, volume: Decimal) -> dict[str, str]:
    return {
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "open": f"{close:.6f}",
        "high": f"{close * Decimal('1.0005'):.6f}",
        "low": f"{close * Decimal('0.9995'):.6f}",
        "close": f"{close:.6f}",
        "volume": f"{volume:.0f}",
    }


def build_rows(days: list[date]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for day_index, trading_date in enumerate(days):
        for symbol_index, symbol in enumerate([BENCHMARK, *SYMBOLS]):
            if symbol == BENCHMARK:
                base = Decimal("100") * Decimal("1.0025") ** day_index
            else:
                base = Decimal(str(50 + (symbol_index - 1) * 7)) * Decimal("1.0025") ** day_index

            for bar_index in range(76):
                start = datetime.combine(trading_date, time(9, 15), IST) + timedelta(minutes=5 * bar_index)
                end = start + timedelta(minutes=5)
                close = base

                if symbol != BENCHMARK and day_index >= 81 and bar_index >= 36:
                    close = price_pattern(symbol_index - 1, day_index, bar_index)
                    if end.time() == EVENT_TIME:
                        close = base * Decimal("1.004")
                    elif end.time() > EVENT_TIME:
                        close = outcome(symbol_index - 1, day_index, base * Decimal("1.004"))

                volume = Decimal("250000") if symbol == BENCHMARK else Decimal(str(150000 + symbol_index * 10000))
                rows.append(make_row(symbol, start, end, close, volume))
    return rows


def validate_preview(rows: list[dict[str, str]]) -> int:
    history: dict[str, list[Bar]] = {symbol: [] for symbol in [BENCHMARK, *SYMBOLS]}
    strategy = BaselineBreakoutStrategy()
    signals = 0
    for row in rows:
        symbol = row["symbol"]
        bar = Bar(
            symbol=symbol,
            start=datetime.fromisoformat(row["start"]),
            end=datetime.fromisoformat(row["end"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        history[symbol].append(bar)
        if symbol in SYMBOLS and bar.end.time() == EVENT_TIME and bar.end.date() >= days_global[81]:
            signal = strategy.evaluate(history[symbol], bar.end, Regime.RISK_ON, 0.5, False, False, True, True)
            if signal.eligible:
                signals += 1
    return signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic multi-trade statistical replay fixture")
    parser.add_argument("--output", required=True)
    parser.add_argument("--days", type=int, default=100)
    parser.add_argument("--start-date", default="2025-01-02")
    args = parser.parse_args()

    global days_global
    days_global = weekdays(date.fromisoformat(args.start_date), args.days)
    rows = build_rows(days_global)
    signals = validate_preview(rows)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "start", "end", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    print({
        "output": str(output),
        "trading_days": len(days_global),
        "rows": len(rows),
        "symbols": len(SYMBOLS) + 1,
        "mature_days": max(0, len(days_global) - 81),
        "expected_daily_setups": len(SYMBOLS),
        "preview_valid_signals": signals,
    })


if __name__ == "__main__":
    main()
