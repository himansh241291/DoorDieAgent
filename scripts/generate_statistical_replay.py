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
from nse_paper_agent.indicators.technical import sma, rsi

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


def base_price(symbol_index: int, day_index: int) -> Decimal:
    return Decimal(str(50 + symbol_index * 7)) * Decimal("1.0025") ** day_index


def event_outcome(symbol_index: int, day_index: int, event_close: Decimal) -> Decimal:
    if symbol_index == 0:
        return event_close * Decimal("1.070")
    if symbol_index == 1:
        return event_close * Decimal("0.970")
    if symbol_index == 2:
        return event_close * (Decimal("1.005") if day_index % 2 == 0 else Decimal("1.001"))
    if symbol_index == 3:
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
            base = Decimal("100") * Decimal("1.0025") ** day_index if symbol == BENCHMARK else base_price(symbol_index - 1, day_index)
            closes: list[Decimal] = [base] * 76

            if symbol != BENCHMARK and day_index >= 81:
                # Build a modest oscillating pre-event series that leaves RSI
                # near neutral, then explicitly create the SMA20 crossover:
                # previous close below previous SMA20; event close above current SMA20.
                for i in range(36, 55):
                    closes[i] = base * (Decimal("1.0003") if i % 2 == 0 else Decimal("0.9997"))
                closes[54] = base * Decimal("0.9985")
                event_close = base * Decimal("1.0015")
                closes[55] = event_close
                post_close = event_outcome(symbol_index - 1, day_index, event_close)
                for i in range(56, 76):
                    closes[i] = post_close

                sample = closes[:56]
                prev_sma = sma(sample[:-1], 20)
                prev_close = sample[-2]
                cur_sma = sma(sample, 20)
                cur_rsi = rsi(sample, 14)
                if prev_sma is None or cur_sma is None or cur_rsi is None or not (prev_close <= prev_sma and sample[-1] > cur_sma and 50 < cur_rsi < 70):
                    raise RuntimeError(
                        f"fixture construction failed for {symbol} {trading_date}: "
                        f"prev_close={prev_close} prev_sma={prev_sma} "
                        f"close={sample[-1]} sma={cur_sma} rsi={cur_rsi}"
                    )

            for bar_index, close in enumerate(closes):
                start = datetime.combine(trading_date, time(9, 15), IST) + timedelta(minutes=5 * bar_index)
                end = start + timedelta(minutes=5)
                volume = Decimal("250000") if symbol == BENCHMARK else Decimal(str(150000 + symbol_index * 10000))
                rows.append(make_row(symbol, start, end, close, volume))
    return rows


def validate_preview(rows: list[dict[str, str]], days: list[date]) -> tuple[int, list[str]]:
    history: dict[str, list[Bar]] = {symbol: [] for symbol in [BENCHMARK, *SYMBOLS]}
    strategy = BaselineBreakoutStrategy()
    signals = 0
    first_events: list[str] = []
    mature_start = days[81] if len(days) > 81 else None

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
        if symbol in SYMBOLS and mature_start is not None and bar.end.time().replace(tzinfo=None) == EVENT_TIME and bar.end.date() >= mature_start:
            signal = strategy.evaluate(history[symbol], bar.end, Regime.RISK_ON, 0.5, False, False, True, True)
            if signal.eligible:
                signals += 1
                if len(first_events) < 5:
                    first_events.append(f"{symbol}@{bar.end.isoformat()}")
    return signals, first_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic multi-trade statistical replay fixture")
    parser.add_argument("--output", required=True)
    parser.add_argument("--days", type=int, default=100)
    parser.add_argument("--start-date", default="2025-01-02")
    args = parser.parse_args()

    days = weekdays(date.fromisoformat(args.start_date), args.days)
    rows = build_rows(days)
    signals, first_events = validate_preview(rows, days)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "start", "end", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    print({
        "output": str(output),
        "trading_days": len(days),
        "rows": len(rows),
        "symbols": len(SYMBOLS) + 1,
        "mature_days": max(0, len(days) - 81),
        "expected_daily_setups": len(SYMBOLS),
        "preview_valid_signals": signals,
        "first_preview_events": first_events,
    })


if __name__ == "__main__":
    main()
