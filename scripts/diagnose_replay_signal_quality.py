#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import mean, median

from nse_paper_agent.domain.models import Bar
from nse_paper_agent.indicators.technical import rsi, sma

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
            s.metadata_json,
            r.reason AS risk_reason,
            r.details_json AS risk_details_json
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
        LEFT JOIN risk_events r
          ON r.symbol IS NULL
         AND r.event_type='ENTRY'
         AND r.ts_utc=f.ts_utc
        WHERE f.side='BUY'
        ORDER BY f.ts_utc, f.id
        """
    ).fetchall()


def bucket_for(dt: datetime) -> str:
    t = dt.time()
    for name, sh, sm, eh, em in TIME_BUCKETS:
        start = t.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = t.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start <= t < end:
            return name
    return "outside"


def analyze(row: sqlite3.Row, bars_by_symbol: dict[str, list[Bar]]) -> dict[str, object]:
    entry = datetime.fromisoformat(row["entry_ts_utc"])
    exit_ts = datetime.fromisoformat(row["exit_ts_utc"]) if row["exit_ts_utc"] else None
    entry_price = float(row["entry_price"])
    symbol_bars = bars_by_symbol[row["symbol"]]
    post = [b for b in symbol_bars if b.end > entry and (exit_ts is None or b.end <= exit_ts)]
    mfe = max(((float(b.high) - entry_price) / entry_price * 100.0 for b in post), default=None)
    mae = min(((float(b.low) - entry_price) / entry_price * 100.0 for b in post), default=None)

    # Reconstruct the entry-side signal context without using future bars.
    prior_and_entry = [b for b in symbol_bars if b.end <= entry]
    closes = [b.close for b in prior_and_entry]
    sma20 = sma(closes, 20)
    rsi14 = rsi(closes, 14)
    distance_sma = ((float(closes[-1]) - float(sma20)) / float(sma20) * 100.0) if sma20 else None
    last5_volume = float(closes[-1]) if closes else None
    del last5_volume  # explicit: volume is handled from the bar below
    entry_bar = next((b for b in symbol_bars if b.end == entry), None)
    volume = float(entry_bar.volume) if entry_bar else None
    prev_volume = None
    if entry_bar:
        prior_bar = next((b for b in reversed(symbol_bars) if b.end < entry), None)
        prev_volume = float(prior_bar.volume) if prior_bar else None
    volume_ratio = volume / prev_volume if prev_volume and prev_volume > 0 else None

    forward: dict[str, float | None] = {}
    for minutes in (30, 60, 120, 240):
        cutoff = entry + timedelta(minutes=minutes)
        future = next((b for b in symbol_bars if b.end >= cutoff), None)
        forward[str(minutes)] = ((float(future.close) - entry_price) / entry_price * 100.0) if future else None

    return {
        "symbol": row["symbol"],
        "entry_ts_utc": row["entry_ts_utc"],
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
        "forward_30m_pct": forward["30"],
        "forward_60m_pct": forward["60"],
        "forward_120m_pct": forward["120"],
        "forward_240m_pct": forward["240"],
    }


def summarize(rows: list[dict[str, object]], label: str) -> None:
    pnls = [float(r["net_pnl"]) for r in rows]
    mfes = [float(r["mfe_pct"]) for r in rows if r["mfe_pct"] is not None]
    maes = [float(r["mae_pct"]) for r in rows if r["mae_pct"] is not None]
    print(label, {
        "trades": len(rows),
        "net_pnl": sum(pnls),
        "avg_net": mean(pnls) if pnls else None,
        "win_rate_pct": sum(v > 0 for v in pnls) / len(pnls) * 100 if pnls else 0.0,
        "mfe_median_pct": median(mfes) if mfes else None,
        "mae_median_pct": median(maes) if maes else None,
        "forward_30m_median_pct": median([float(r["forward_30m_pct"]) for r in rows if r["forward_30m_pct"] is not None]) if any(r["forward_30m_pct"] is not None for r in rows) else None,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Decompose replay entries by signal context and post-entry behavior.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--csv", help="Optional path for the per-entry diagnostic dataset")
    args = parser.parse_args()

    bars_by_symbol = parse_bars(args.bars)
    conn = sqlite3.connect(args.db)
    entries = load_entries(conn)
    conn.close()
    rows = [analyze(entry, bars_by_symbol) for entry in entries if entry["exit_ts_utc"]]

    print(f"entries={len(rows)}")
    summarize(rows, "overall")

    for key in ("symbol", "time_bucket", "exit_reason"):
        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            groups[str(row[key])].append(row)
        print(f"=== BY {key.upper()} ===")
        for name, group in sorted(groups.items()):
            summarize(group, name)

    print("=== RSI BANDS ===")
    bands = (("<50", -float("inf"), 50), ("50-55", 50, 55), ("55-60", 55, 60), ("60-65", 60, 65), ("65-70", 65, 70), ("70+", 70, float("inf")))
    for name, low, high in bands:
        group = [r for r in rows if r["rsi14"] is not None and low <= float(r["rsi14"]) < high]
        if group:
            summarize(group, name)

    print("=== SMA DISTANCE BANDS ===")
    bands = (("<-0.50%", -float("inf"), -0.5), ("-0.50..0%", -0.5, 0), ("0..0.25%", 0, 0.25), ("0.25..0.50%", 0.25, 0.50), ("0.50..1%", 0.50, 1.0), (">=1%", 1.0, float("inf")))
    for name, low, high in bands:
        group = [r for r in rows if r["sma20_distance_pct"] is not None and low <= float(r["sma20_distance_pct"]) < high]
        if group:
            summarize(group, name)

    for minutes in (30, 60, 120, 240):
        values = [float(r[f"forward_{minutes}m_pct"]) for r in rows if r[f"forward_{minutes}m_pct"] is not None]
        positive = sum(v > 0 for v in values)
        print(f"forward_{minutes}m", {"n": len(values), "mean_pct": mean(values) if values else None, "median_pct": median(values) if values else None, "positive_pct": positive / len(values) * 100 if values else 0.0, "p25_pct": percentile(values, .25), "p75_pct": percentile(values, .75)})

    if args.csv:
        fieldnames = list(rows[0].keys()) if rows else []
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"csv={args.csv}")


if __name__ == "__main__":
    main()
