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
BUY_FEE_AND_SELL_FEE = 40.0
HORIZON = 60
MIN_TRADES = 10


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
    for bars in result.values():
        bars.sort(key=lambda item: item.end)
    return result


def load_entries(db_path: str) -> list[dict[str, object]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT c.id, c.symbol, c.qty, c.entry_price, c.entry_ts_utc,
               mr.regime,
               json_extract(mr.metrics_json, '$.breadth20') AS breadth20,
               json_extract(mr.metrics_json, '$.vol_percentile') AS vol_percentile,
               json_extract(mr.metrics_json, '$.vol_shock') AS vol_shock
        FROM closed_trades c
        LEFT JOIN (
            SELECT ts_utc, MAX(id) AS id
            FROM market_regimes
            GROUP BY ts_utc
        ) latest ON latest.ts_utc = c.entry_ts_utc
        LEFT JOIN market_regimes mr ON mr.id = latest.id
        ORDER BY c.entry_ts_utc, c.id
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def context(entry: dict[str, object], bars: list[Bar]) -> dict[str, object]:
    ts = datetime.fromisoformat(str(entry["entry_ts_utc"]))
    available = [bar for bar in bars if bar.end <= ts]
    closes = [bar.close for bar in available]
    current = available[-1] if available else None
    previous = available[-2] if len(available) >= 2 else None
    sma20 = sma(closes, 20)
    rsi14 = rsi(closes, 14)
    sma_distance = ((float(closes[-1]) - float(sma20)) / float(sma20) * 100.0) if sma20 and closes else None
    volume_ratio = (float(current.volume) / float(previous.volume)) if current and previous and previous.volume > 0 else None

    def ret(n: int) -> float | None:
        if len(closes) <= n:
            return None
        base = float(closes[-1 - n])
        return (float(closes[-1]) - base) / base * 100.0 if base else None

    entry_ist = ts.astimezone(IST)
    return {
        "trading_date": entry_ist.date().isoformat(),
        "time_ist": entry_ist.strftime("%H:%M"),
        "rsi14": rsi14,
        "sma_distance_pct": sma_distance,
        "volume_ratio": volume_ratio,
        "return_5m_pct": ret(1),
        "return_15m_pct": ret(3),
        "regime": entry.get("regime"),
    }


def enrich(entry: dict[str, object], bars_by_symbol: dict[str, list[Bar]]) -> dict[str, object]:
    row = dict(entry)
    row.update(context(entry, bars_by_symbol[str(entry["symbol"]) ]))
    price = float(entry["entry_price"])
    qty = int(entry["qty"])
    bars = bars_by_symbol[str(entry["symbol"])]
    ts = datetime.fromisoformat(str(entry["entry_ts_utc"]))
    day = ts.astimezone(IST).date()
    future = [bar for bar in bars if bar.end >= ts + timedelta(minutes=HORIZON) and bar.end.astimezone(IST).date() == day]
    if future:
        forward = (float(future[0].close) - price) / price * 100.0
        row["forward_60m_pct"] = forward
        row["forward_60m_net_pnl"] = price * forward / 100.0 * qty - BUY_FEE_AND_SELL_FEE
    else:
        row["forward_60m_pct"] = None
        row["forward_60m_net_pnl"] = None
    return row


def summarize(rows: list[dict[str, object]]) -> dict[str, float | int | None]:
    values = [float(r["forward_60m_net_pnl"]) for r in rows if r["forward_60m_net_pnl"] is not None]
    returns = [float(r["forward_60m_pct"]) for r in rows if r["forward_60m_pct"] is not None]
    return {
        "trades": len(rows),
        "net_pnl": sum(values) if values else 0.0,
        "expectancy": mean(values) if values else None,
        "positive_pct": sum(v > 0 for v in values) / len(values) * 100.0 if values else 0.0,
        "median_return_pct": median(returns) if returns else None,
        "p25_return_pct": percentile(returns, 0.25),
        "p75_return_pct": percentile(returns, 0.75),
    }


def candidate_rules() -> list[tuple[str, object]]:
    return [
        ("baseline", lambda r: True),
        ("rsi_ge_60", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 60),
        ("rsi_ge_65", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 65),
        ("sma_ge_0.25", lambda r: r["sma_distance_pct"] is not None and float(r["sma_distance_pct"]) >= 0.25),
        ("sma_ge_0.50", lambda r: r["sma_distance_pct"] is not None and float(r["sma_distance_pct"]) >= 0.50),
        ("ret5_ge_0.25", lambda r: r["return_5m_pct"] is not None and float(r["return_5m_pct"]) >= 0.25),
        ("ret5_ge_0.50", lambda r: r["return_5m_pct"] is not None and float(r["return_5m_pct"]) >= 0.50),
        ("ret15_ge_0.25", lambda r: r["return_15m_pct"] is not None and float(r["return_15m_pct"]) >= 0.25),
        ("ret15_ge_0.50", lambda r: r["return_15m_pct"] is not None and float(r["return_15m_pct"]) >= 0.50),
        ("rsi65_sma25", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 65 and r["sma_distance_pct"] is not None and float(r["sma_distance_pct"]) >= 0.25),
        ("rsi65_ret5_25", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 65 and r["return_5m_pct"] is not None and float(r["return_5m_pct"]) >= 0.25),
        ("rsi65_ret15_25", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 65 and r["return_15m_pct"] is not None and float(r["return_15m_pct"]) >= 0.25),
        ("rsi60_sma25_ret5_25", lambda r: r["rsi14"] is not None and float(r["rsi14"]) >= 60 and r["sma_distance_pct"] is not None and float(r["sma_distance_pct"]) >= 0.25 and r["return_5m_pct"] is not None and float(r["return_5m_pct"]) >= 0.25),
        ("morning_rsi60", lambda r: str(r["time_ist"]) < "10:00" and r["rsi14"] is not None and float(r["rsi14"]) >= 60),
        ("risk_on_rsi60", lambda r: r["regime"] == "RISK_ON" and r["rsi14"] is not None and float(r["rsi14"]) >= 60),
    ]


def walkforward_splits(days: list[str]) -> list[tuple[str, list[str], str]]:
    # Four sequential validation blocks. Each block is preceded by a development history.
    n = len(days)
    block = max(5, n // 5)
    splits: list[tuple[str, list[str], str]] = []
    for i in range(1, 5):
        start = i * block
        end = min(start + block, n)
        if start >= n:
            break
        dev_days = days[:start]
        test_days = days[start:end]
        if len(test_days) >= 5 and dev_days:
            splits.append((f"WF{i}", dev_days, test_days[0] + ".." + test_days[-1]))
    return splits


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward V1 entry-filter stability experiment.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    bars_by_symbol = parse_bars(args.bars)
    entries = load_entries(args.db)
    rows = [enrich(entry, bars_by_symbol) for entry in entries]
    days = sorted({str(row["trading_date"]) for row in rows})
    splits = walkforward_splits(days)

    print(f"entries={len(rows)}")
    print(f"trading_days={len(days)}")
    print("split=walk_forward_expanding_development_then_unseen_validation")
    print("minimum_candidate_trades=10")
    print("NOTE=no strategy configuration is changed")

    rules = candidate_rules()
    for name, dev_days, test_range in splits:
        test_days = [d for d in days if d >= test_range.split("..")[0] and d <= test_range.split("..")[1]]
        dev = [r for r in rows if str(r["trading_date"]) in set(dev_days)]
        test = [r for r in rows if str(r["trading_date"]) in set(test_days)]
        print(f"=== {name} DEV={len(dev)} TEST={len(test)} TEST_DATES={test_range} ===")
        for rule_name, predicate in rules:
            selected_dev = [r for r in dev if predicate(r)]
            selected_test = [r for r in test if predicate(r)]
            if len(selected_dev) < MIN_TRADES or len(selected_test) < MIN_TRADES:
                print(rule_name, {"dev_trades": len(selected_dev), "test_trades": len(selected_test), "status": "INSUFFICIENT_SAMPLE"})
                continue
            ds = summarize(selected_dev)
            ts = summarize(selected_test)
            print(rule_name, {"dev": ds, "test": ts, "status": "OK"})

    print("=== FULL SAMPLE CONTEXT ===")
    for field in ("rsi14", "sma_distance_pct", "return_5m_pct", "return_15m_pct"):
        values = [float(r[field]) for r in rows if r[field] is not None]
        print(field, {"p25": percentile(values, .25), "median": median(values) if values else None, "p75": percentile(values, .75), "p90": percentile(values, .90)})


if __name__ == "__main__":
    main()
