#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

from nse_paper_agent.domain.models import Bar

HORIZONS_MINUTES = (30, 60, 120, 240)
TARGETS_PCT = (0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00, 5.00)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return ordered[low] + (ordered[high] - ordered[low]) * weight


def parse_bars(path: str) -> dict[str, list[Bar]]:
    result: dict[str, list[Bar]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            bar = Bar(
                row["symbol"],
                __import__("datetime").datetime.fromisoformat(row["start"]),
                __import__("datetime").datetime.fromisoformat(row["end"]),
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
                Decimal(row["volume"]),
            )
            result[bar.symbol].append(bar)
    for bars in result.values():
        bars.sort(key=lambda item: item.end)
    return result


def load_trades(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, symbol, qty, entry_price, exit_price,
               entry_fee, exit_fee, gross_pnl, net_pnl,
               entry_ts_utc, exit_ts_utc, exit_reason
        FROM closed_trades
        ORDER BY entry_ts_utc, id
        """
    ).fetchall()
    conn.close()
    return rows


def analyze_trade(trade: sqlite3.Row, bars_by_symbol: dict[str, list[Bar]]) -> dict[str, float | int | str | None]:
    from datetime import datetime

    entry = datetime.fromisoformat(trade["entry_ts_utc"])
    exit_ts = datetime.fromisoformat(trade["exit_ts_utc"])
    entry_price = float(trade["entry_price"])
    symbol_bars = bars_by_symbol.get(trade["symbol"], [])

    post_entry = [
        bar
        for bar in symbol_bars
        if bar.end > entry and bar.end <= exit_ts
    ]

    max_high = max((float(bar.high) for bar in post_entry), default=None)
    min_low = min((float(bar.low) for bar in post_entry), default=None)
    mfe_pct = ((max_high - entry_price) / entry_price * 100.0) if max_high is not None else None
    mae_pct = ((min_low - entry_price) / entry_price * 100.0) if min_low is not None else None

    result: dict[str, float | int | str | None] = {
        "id": int(trade["id"]),
        "symbol": trade["symbol"],
        "exit_reason": trade["exit_reason"],
        "net_pnl": float(trade["net_pnl"]),
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
    }

    for minutes in HORIZONS_MINUTES:
        cutoff = entry + timedelta(minutes=minutes)
        future = next((bar for bar in symbol_bars if bar.end >= cutoff), None)
        result[f"close_{minutes}m_pct"] = ((float(future.close) - entry_price) / entry_price * 100.0) if future else None

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze post-entry MFE/MAE and forward returns for replay trades.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    bars_by_symbol = parse_bars(args.bars)
    trades = load_trades(args.db)
    analyses = [analyze_trade(trade, bars_by_symbol) for trade in trades]

    print(f"trades={len(analyses)}")
    if not analyses:
        return

    mfe = [float(row["mfe_pct"]) for row in analyses if row["mfe_pct"] is not None]
    mae = [float(row["mae_pct"]) for row in analyses if row["mae_pct"] is not None]
    print(
        "mfe_pct",
        {"median": median(mfe), "mean": mean(mfe), "p25": percentile(mfe, 0.25), "p75": percentile(mfe, 0.75)},
    )
    print(
        "mae_pct",
        {"median": median(mae), "mean": mean(mae), "p25": percentile(mae, 0.25), "p75": percentile(mae, 0.75)},
    )

    for target in TARGETS_PCT:
        hit = sum(1 for value in mfe if value >= target)
        print(f"mfe_reach_{target:.2f}pct={hit}/{len(mfe)} ({hit / len(mfe) * 100:.1f}%)")

    for minutes in HORIZONS_MINUTES:
        values = [
            float(row[f"close_{minutes}m_pct"])
            for row in analyses
            if row[f"close_{minutes}m_pct"] is not None
        ]
        if values:
            positive = sum(1 for value in values if value > 0)
            print(
                f"forward_{minutes}m_close_pct",
                {
                    "median": median(values),
                    "mean": mean(values),
                    "positive_pct": positive / len(values) * 100.0,
                    "p25": percentile(values, 0.25),
                    "p75": percentile(values, 0.75),
                },
            )

    by_reason: dict[str, list[dict[str, float | int | str | None]]] = defaultdict(list)
    for row in analyses:
        by_reason[str(row["exit_reason"])].append(row)
    for reason, rows in sorted(by_reason.items()):
        mfes = [float(row["mfe_pct"]) for row in rows if row["mfe_pct"] is not None]
        maes = [float(row["mae_pct"]) for row in rows if row["mae_pct"] is not None]
        print(
            "exit_reason",
            reason,
            {
                "trades": len(rows),
                "avg_net": mean(float(row["net_pnl"]) for row in rows),
                "mfe_median_pct": median(mfes) if mfes else None,
                "mae_median_pct": median(maes) if maes else None,
            },
        )

    fees = sum(float(row["entry_fee"]) + float(row["exit_fee"]) for row in load_trades(args.db))
    gross = sum(float(row["gross_pnl"]) for row in load_trades(args.db))
    net = sum(float(row["net_pnl"]) for row in load_trades(args.db))
    print("economics", {"gross_pnl": gross, "fees": fees, "net_pnl": net})


if __name__ == "__main__":
    main()
