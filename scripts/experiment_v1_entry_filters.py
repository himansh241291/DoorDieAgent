#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import mean, median
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar
from nse_paper_agent.indicators.technical import rsi, sma

IST = ZoneInfo("Asia/Kolkata")
DEV_FRACTION = 0.70
HORIZONS = (30, 60, 120, 240)
ROUND_TRIP_FEE = 40.0

@dataclass(frozen=True)
class Entry:
    id: int
    symbol: str
    qty: int
    price: Decimal
    ts: datetime
    regime: str | None
    breadth20: float | None
    vol_percentile: float | None
    vol_shock: float | None

@dataclass(frozen=True)
class Context:
    rsi14: float | None
    sma20_distance_pct: float | None
    volume_ratio: float | None
    return_5m_pct: float | None
    return_15m_pct: float | None

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
            result[row["symbol"]].append(
                Bar(
                    row["symbol"],
                    datetime.fromisoformat(row["start"]),
                    datetime.fromisoformat(row["end"]),
                    Decimal(row["open"]),
                    Decimal(row["high"]),
                    Decimal(row["low"]),
                    Decimal(row["close"]),
                    Decimal(row["volume"]),
                )
            )
    for rows in result.values():
        rows.sort(key=lambda item: item.end)
    return result

def load_entries(db_path: str) -> list[Entry]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        WITH regime_at_entry AS (
            SELECT c.id AS trade_id,
                   mr.regime,
                   json_extract(mr.metrics_json, '$.breadth20') AS breadth20,
                   json_extract(mr.metrics_json, '$.vol_percentile') AS vol_percentile,
                   json_extract(mr.metrics_json, '$.vol_shock') AS vol_shock,
                   ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY mr.id DESC) AS rn
            FROM closed_trades c
            LEFT JOIN market_regimes mr ON mr.ts_utc = c.entry_ts_utc
        )
        SELECT c.id, c.symbol, c.qty, c.entry_price, c.entry_ts_utc,
               r.regime, r.breadth20, r.vol_percentile, r.vol_shock
        FROM closed_trades c
        LEFT JOIN regime_at_entry r ON r.trade_id = c.id AND r.rn = 1
        ORDER BY c.entry_ts_utc, c.id
        """
    ).fetchall()
    conn.close()
    return [
        Entry(
            id=int(row["id"]),
            symbol=str(row["symbol"]),
            qty=int(row["qty"]),
            price=Decimal(str(row["entry_price"])),
            ts=datetime.fromisoformat(row["entry_ts_utc"]),
            regime=row["regime"],
            breadth20=float(row["breadth20"]) if row["breadth20"] is not None else None,
            vol_percentile=float(row["vol_percentile"]) if row["vol_percentile"] is not None else None,
            vol_shock=float(row["vol_shock"]) if row["vol_shock"] is not None else None,
        )
        for row in rows
    ]

def context_for(entry: Entry, bars: list[Bar]) -> Context:
    available = [bar for bar in bars if bar.end <= entry.ts]
    closes = [bar.close for bar in available]
    sma20 = sma(closes, 20)
    rsi14 = rsi(closes, 14)
    distance = ((float(closes[-1]) - float(sma20)) / float(sma20) * 100.0) if sma20 is not None and closes else None
    current = available[-1] if available else None
    previous = available[-2] if len(available) >= 2 else None
    volume_ratio = (float(current.volume) / float(previous.volume) if current is not None and previous is not None and float(previous.volume) > 0 else None)
    def ret(n: int) -> float | None:
        if len(closes) <= n:
            return None
        prior = float(closes[-1 - n])
        return (float(closes[-1]) - prior) / prior * 100.0 if prior else None
    return Context(rsi14, distance, volume_ratio, ret(1), ret(3))

def target_row(entry: Entry, bars: list[Bar]) -> dict[str, object]:
    context = context_for(entry, bars)
    entry_ist = entry.ts.astimezone(IST)
    result: dict[str, object] = {
        "id": entry.id,
        "symbol": entry.symbol,
        "entry_ts_utc": entry.ts.isoformat(),
        "entry_ts_ist": entry_ist.isoformat(),
        "trading_date_ist": entry_ist.date().isoformat(),
        "qty": entry.qty,
        "entry_price": float(entry.price),
        "regime": entry.regime,
        "breadth20": entry.breadth20,
        "vol_percentile": entry.vol_percentile,
        "vol_shock": entry.vol_shock,
        "rsi14": context.rsi14,
        "sma20_distance_pct": context.sma20_distance_pct,
        "volume_ratio_vs_prev_bar": context.volume_ratio,
        "return_5m_pct": context.return_5m_pct,
        "return_15m_pct": context.return_15m_pct,
        "time_ist": entry_ist.strftime("%H:%M"),
    }
    for minutes in HORIZONS:
        cutoff = entry.ts + timedelta(minutes=minutes)
        future = next((bar for bar in bars if bar.end >= cutoff and bar.end.astimezone(IST).date() == entry_ist.date()), None)
        result[f"forward_{minutes}m_pct"] = ((float(future.close) - float(entry.price)) / float(entry.price) * 100.0 if future is not None else None)
    forward60 = result["forward_60m_pct"]
    result["forward_60m_net_pnl"] = (float(entry.price) * (float(forward60) / 100.0) * entry.qty - ROUND_TRIP_FEE if isinstance(forward60, float) else None)
    return result

def summarize(rows: list[dict[str, object]]) -> dict[str, float | int | None]:
    pnls = [float(row["forward_60m_net_pnl"]) for row in rows if row["forward_60m_net_pnl"] is not None]
    f30 = [float(row["forward_30m_pct"]) for row in rows if row["forward_30m_pct"] is not None]
    f60 = [float(row["forward_60m_pct"]) for row in rows if row["forward_60m_pct"] is not None]
    f120 = [float(row["forward_120m_pct"]) for row in rows if row["forward_120m_pct"] is not None]
    return {
        "trades": len(rows),
        "forward_60m_net_pnl": sum(pnls) if pnls else 0.0,
        "forward_60m_expectancy": mean(pnls) if pnls else None,
        "forward_60m_positive_pct": sum(value > 0 for value in f60) / len(f60) * 100.0 if f60 else 0.0,
        "forward_30m_median_pct": median(f30) if f30 else None,
        "forward_60m_median_pct": median(f60) if f60 else None,
        "forward_120m_median_pct": median(f120) if f120 else None,
    }

def split_by_day(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    ordered = sorted(rows, key=lambda row: (str(row["trading_date_ist"]), str(row["entry_ts_utc"]), int(row["id"])))
    days = sorted({str(row["trading_date_ist"]) for row in ordered})
    cut = max(1, int(len(days) * DEV_FRACTION))
    dev_days = set(days[:cut])
    return ([row for row in ordered if row["trading_date_ist"] in dev_days], [row for row in ordered if row["trading_date_ist"] not in dev_days])

def main() -> None:
    parser = argparse.ArgumentParser(description="Map V1 entry context and test a small, predeclared set of entry filters.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--csv", help="Write the per-entry edge map")
    args = parser.parse_args()
    bars_by_symbol = parse_bars(args.bars)
    entries = load_entries(args.db)
    rows = [target_row(entry, bars_by_symbol[entry.symbol]) for entry in entries]
    if not rows:
        raise SystemExit("no closed trades found")
    print(f"entries={len(rows)}")
    dev, holdout = split_by_day(rows)
    print("split=chronological_70pct_trading_days_development_30pct_holdout")
    print("NOTE=filters are predeclared research candidates only; no strategy configuration is changed")
    print("SPLIT", {"development": len(dev), "holdout": len(holdout), "development_days": len({str(row['trading_date_ist']) for row in dev}), "holdout_days": len({str(row['trading_date_ist']) for row in holdout}), "development_last": dev[-1]["trading_date_ist"], "holdout_first": holdout[0]["trading_date_ist"]})
    candidates: list[tuple[str, object]] = [
        ("baseline_all", lambda r: True),
        ("rsi_ge_60", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 60.0),
        ("rsi_ge_65", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 65.0),
        ("sma_dist_ge_0.25", lambda r: r["sma20_distance_pct"] is not None and float(r["sma20_distance_pct"]) >= 0.25),
        ("sma_dist_ge_0.50", lambda r: r["sma20_distance_pct"] is not None and float(r["sma20_distance_pct"]) >= 0.50),
        ("rsi_ge_60_and_sma_ge_0.25", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 60.0 and r["sma20_distance_pct"] is not None and float(r["sma20_distance_pct"]) >= 0.25),
        ("rsi_ge_60_and_sma_ge_0.50", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 60.0 and r["sma20_distance_pct"] is not None and float(r["sma20_distance_pct"]) >= 0.50),
        ("volume_ratio_ge_1.0", lambda r: r["volume_ratio_vs_prev_bar"] is not None and float(r["volume_ratio_vs_prev_bar"]) >= 1.0),
        ("volume_ratio_ge_1.5", lambda r: r["volume_ratio_vs_prev_bar"] is not None and float(r["volume_ratio_vs_prev_bar"]) >= 1.5),
        ("rsi_ge_60_and_volume_ge_1.0", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 60.0 and r["volume_ratio_vs_prev_bar"] is not None and float(r["volume_ratio_vs_prev_bar"]) >= 1.0),
        ("risk_on_only", lambda r: r["regime"] == "RISK_ON"),
        ("risk_on_and_rsi_ge_60", lambda r: r["regime"] == "RISK_ON" and r["rsi14"] is not None and float(r["rsi14"]) >= 60.0),
        ("risk_on_and_sma_ge_0.25", lambda r: r["regime"] == "RISK_ON" and r["sma20_distance_pct"] is not None and float(r["sma20_distance_pct"]) >= 0.25),
        ("morning_and_rsi_ge_60", lambda r: str(r["time_ist"]) < "10:00" and r["rsi14"] is not None and float(r["rsi14"]) >= 60.0),
    ]
    print("=== FILTER RESULTS ===")
    print("rule,split,trades,forward60_net_pnl,forward60_expectancy,forward60_positive_pct,forward30_median_pct,forward60_median_pct,forward120_median_pct")
    for name, predicate in candidates:
        for split_name, group in (("development", dev), ("holdout", holdout)):
            selected = [row for row in group if predicate(row)]
            summary = summarize(selected)
            print(name, split_name, *[summary[key] for key in ("trades", "forward_60m_net_pnl", "forward_60m_expectancy", "forward_60m_positive_pct", "forward_30m_median_pct", "forward_60m_median_pct", "forward_120m_median_pct")], sep=",")
    print("=== CONTEXT QUANTILES ===")
    for field in ("rsi14", "sma20_distance_pct", "volume_ratio_vs_prev_bar", "return_5m_pct", "return_15m_pct"):
        values = [float(row[field]) for row in rows if row[field] is not None]
        print(field, {"p25": percentile(values, 0.25), "median": median(values) if values else None, "p75": percentile(values, 0.75), "p90": percentile(values, 0.90)})
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"csv={args.csv}")

if __name__ == "__main__":
    main()
