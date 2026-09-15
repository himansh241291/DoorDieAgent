#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import mean, median
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar
from nse_paper_agent.indicators.technical import rsi, sma

IST = ZoneInfo("Asia/Kolkata")
TIME_BUCKETS = (
    ("09:15-10:00", 9, 15, 10, 0),
    ("10:00-11:00", 10, 0, 11, 0),
    ("11:00-12:00", 11, 0, 12, 0),
    ("12:00-13:00", 12, 0, 13, 0),
    ("13:00-14:00", 13, 0, 14, 0),
    ("14:00-14:45", 14, 0, 14, 45),
)


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
                datetime.fromisoformat(row["start"]),
                datetime.fromisoformat(row["end"]),
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


def load_entries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT
            f.id AS fill_id,
            f.symbol,
            f.qty,
            f.price AS entry_price,
            f.ts_utc AS entry_ts_utc,
            f.strategy_version,
            c.exit_reason,
            c.exit_ts_utc,
            c.net_pnl,
            c.gross_pnl,
            c.entry_fee,
            c.exit_fee,
            s.score,
            s.metadata_json
        FROM simulated_fills f
        LEFT JOIN closed_trades c
          ON c.symbol=f.symbol
         AND c.entry_ts_utc=f.ts_utc
         AND c.qty=f.qty
         AND c.entry_price=f.price
        LEFT JOIN signals s
          ON s.symbol=f.symbol
         AND s.bar_end_utc=f.ts_utc
         AND s.strategy_version=f.strategy_version
         AND s.eligible=1
        WHERE f.side='BUY'
        ORDER BY f.ts_utc, f.id
        """
    ).fetchall()


def bucket_for(dt: datetime) -> str:
    t = dt.astimezone(IST).time()
    for name, sh, sm, eh, em in TIME_BUCKETS:
        start = t.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = t.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start <= t < end:
            return name
    return "outside"


def analyze(row: sqlite3.Row, bars_by_symbol: dict[str, list[Bar]]) -> dict[str, object]:
    entry = datetime.fromisoformat(row["entry_ts_utc"])
    exit_ts = datetime.fromisoformat(row["exit_ts_utc"])
    entry_price = float(row["entry_price"])
    symbol_bars = bars_by_symbol[row["symbol"]]

    post_entry = [
        bar
        for bar in symbol_bars
        if bar.end > entry and bar.end <= exit_ts
    ]
    mfe = max(
        ((float(bar.high) - entry_price) / entry_price * 100.0 for bar in post_entry),
        default=None,
    )
    mae = min(
        ((float(bar.low) - entry_price) / entry_price * 100.0 for bar in post_entry),
        default=None,
    )

    available = [bar for bar in symbol_bars if bar.end <= entry]
    closes = [bar.close for bar in available]
    sma20 = sma(closes, 20)
    rsi14 = rsi(closes, 14)
    distance_sma = (
        (float(closes[-1]) - float(sma20)) / float(sma20) * 100.0
        if sma20 is not None and closes
        else None
    )
    entry_bar = next((bar for bar in symbol_bars if bar.end == entry), None)
    prior_bar = next((bar for bar in reversed(symbol_bars) if bar.end < entry), None)
    volume = float(entry_bar.volume) if entry_bar else None
    prev_volume = float(prior_bar.volume) if prior_bar else None
    volume_ratio = (
        volume / prev_volume
        if volume is not None and prev_volume is not None and prev_volume > 0
        else None
    )

    forward: dict[int, float | None] = {}
    for minutes in (30, 60, 120, 240):
        cutoff = entry + timedelta(minutes=minutes)
        future = next((bar for bar in symbol_bars if bar.end >= cutoff), None)
        forward[minutes] = (
            (float(future.close) - entry_price) / entry_price * 100.0
            if future is not None
            else None
        )

    return {
        "symbol": row["symbol"],
        "entry_ts_utc": row["entry_ts_utc"],
        "entry_ts_ist": entry.astimezone(IST).isoformat(),
        "entry_price": entry_price,
        "qty": int(row["qty"]),
        "net_pnl": float(row["net_pnl"]),
        "gross_pnl": float(row["gross_pnl"]),
        "exit_reason": row["exit_reason"],
        "strategy_version": row["strategy_version"],
        "time_bucket": bucket_for(entry),
        "rsi14": rsi14,
        "sma20_distance_pct": distance_sma,
        "entry_volume": volume,
        "volume_ratio_vs_prev_bar": volume_ratio,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "forward_30m_pct": forward[30],
        "forward_60m_pct": forward[60],
        "forward_120m_pct": forward[120],
        "forward_240m_pct": forward[240],
    }


def median_field(rows: list[dict[str, object]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row[field] is not None]
    return median(values) if values else None


def summarize(rows: list[dict[str, object]], label: str) -> None:
    pnls = [float(row["net_pnl"]) for row in rows]
    mfes = [float(row["mfe_pct"]) for row in rows if row["mfe_pct"] is not None]
    maes = [float(row["mae_pct"]) for row in rows if row["mae_pct"] is not None]
    print(
        label,
        {
            "trades": len(rows),
            "net_pnl": sum(pnls),
            "avg_net": mean(pnls) if pnls else None,
            "win_rate_pct": sum(value > 0 for value in pnls) / len(pnls) * 100.0 if pnls else 0.0,
            "mfe_median_pct": median(mfes) if mfes else None,
            "mae_median_pct": median(maes) if maes else None,
            "forward_30m_median_pct": median_field(rows, "forward_30m_pct"),
        },
    )


def print_bands(rows: list[dict[str, object]], label: str, field: str, bands: tuple[tuple[str, float, float], ...]) -> None:
    print(f"=== {label} ===")
    for name, low, high in bands:
        group = [
            row for row in rows
            if row[field] is not None and low <= float(row[field]) < high
        ]
        if group:
            summarize(group, name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decompose replay entries by signal context and post-entry behavior."
    )
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--csv", help="Optional path for the per-entry diagnostic dataset")
    args = parser.parse_args()

    bars_by_symbol = parse_bars(args.bars)
    conn = sqlite3.connect(args.db)
    entries = load_entries(conn)
    conn.close()
    missing_exit = sum(entry["exit_ts_utc"] is None for entry in entries)
    rows = [
        analyze(entry, bars_by_symbol)
        for entry in entries
        if entry["exit_ts_utc"] is not None
    ]

    print(f"buy_fills={len(entries)}")
    print(f"closed_entries_analyzed={len(rows)}")
    print(f"open_or_unmatched_entries={missing_exit}")
    if not rows:
        raise SystemExit("no closed BUY fills available for analysis")

    summarize(rows, "overall")

    for key in ("symbol", "time_bucket", "exit_reason"):
        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            groups[str(row[key])].append(row)
        print(f"=== BY {key.upper()} ===")
        for name, group in sorted(groups.items()):
            summarize(group, name)

    print_bands(
        rows,
        "RSI BANDS",
        "rsi14",
        (
            ("<50", -float("inf"), 50),
            ("50-55", 50, 55),
            ("55-60", 55, 60),
            ("60-65", 60, 65),
            ("65-70", 65, 70),
            ("70+", 70, float("inf")),
        ),
    )
    print_bands(
        rows,
        "SMA DISTANCE BANDS",
        "sma20_distance_pct",
        (
            ("<0.10%", -float("inf"), 0.10),
            ("0.10-0.25%", 0.10, 0.25),
            ("0.25-0.50%", 0.25, 0.50),
            ("0.50-1.00%", 0.50, 1.00),
            (">=1.00%", 1.00, float("inf")),
        ),
    )

    for minutes in (30, 60, 120, 240):
        field = f"forward_{minutes}m_pct"
        values = [float(row[field]) for row in rows if row[field] is not None]
        positive = sum(value > 0 for value in values)
        print(
            f"forward_{minutes}m",
            {
                "n": len(values),
                "mean_pct": mean(values) if values else None,
                "median_pct": median(values) if values else None,
                "positive_pct": positive / len(values) * 100.0 if values else 0.0,
                "p25_pct": percentile(values, 0.25),
                "p75_pct": percentile(values, 0.75),
            },
        )

    if args.csv:
        fieldnames = list(rows[0].keys())
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"csv={args.csv}")


if __name__ == "__main__":
    main()
