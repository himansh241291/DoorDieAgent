from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

HORIZONS = (15, 30, 60, 120)
MIN_BUCKET_SAMPLES = 8
BOOTSTRAP_SEED = 44
BOOTSTRAP_ROUNDS = 2000


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires values")
    pos = (len(ordered) - 1) * fraction
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _bucket(value: float, q1: float, q2: float) -> str:
    if value <= q1:
        return "LOW"
    if value <= q2:
        return "MID"
    return "HIGH"


def _load(path: Path) -> tuple[sqlite3.Connection, list[dict[str, object]]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT f.symbol, f.ts_utc, f.price AS entry_price,
               f.strategy_version, c.net_pnl, s.score, s.metadata_json
        FROM simulated_fills f
        JOIN closed_trades c
          ON c.symbol=f.symbol AND c.entry_ts_utc=f.ts_utc
         AND c.qty=f.qty AND c.entry_price=f.price
        JOIN signals s
          ON s.symbol=f.symbol AND s.bar_end_utc=f.ts_utc
         AND s.strategy_version=f.strategy_version AND s.eligible=1
        WHERE f.side='BUY'
        ORDER BY f.ts_utc, f.id
        """
    ).fetchall()
    entries = []
    for row in rows:
        features = {}
        if row["score"] is not None:
            features["score"] = float(row["score"])
        for key, value in json.loads(row["metadata_json"] or "{}").items():
            if isinstance(value, (int, float)):
                features[str(key)] = float(value)
        entries.append({
            "symbol": str(row["symbol"]),
            "ts": datetime.fromisoformat(row["ts_utc"]),
            "price": float(row["entry_price"]),
            "strategy": str(row["strategy_version"]),
            "net_pnl": float(row["net_pnl"]),
            "features": features,
        })
    return conn, entries


def _forward(conn: sqlite3.Connection, row: dict[str, object]) -> dict[str, float | None]:
    out = {}
    for minutes in HORIZONS:
        target = row["ts"] + timedelta(minutes=minutes)
        bar = conn.execute(
            """
            SELECT close FROM market_bars
            WHERE symbol=? AND end_utc>=?
            ORDER BY end_utc LIMIT 1
            """,
            (row["symbol"], target.isoformat()),
        ).fetchone()
        out[f"{minutes}m"] = (
            (float(bar[0]) - row["price"]) / row["price"] if bar else None
        )
    return out


def _bootstrap_ci(values_a: list[float], values_b: list[float]) -> tuple[float, float]:
    import random
    rng = random.Random(BOOTSTRAP_SEED)
    if not values_a or not values_b:
        return (None, None)
    diffs = []
    for _ in range(BOOTSTRAP_ROUNDS):
        a = [values_a[rng.randrange(len(values_a))] for _ in values_a]
        b = [values_b[rng.randrange(len(values_b))] for _ in values_b]
        diffs.append(sum(a) / len(a) - sum(b) / len(b))
    diffs.sort()
    return (
        diffs[int(0.025 * (len(diffs) - 1))],
        diffs[int(0.975 * (len(diffs) - 1))],
    )


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    result = {"samples": len(rows), "net_pnl": sum(r["net_pnl"] for r in rows)}
    for minutes in HORIZONS:
        values = [r["forward"][f"{minutes}m"] for r in rows if r["forward"][f"{minutes}m"] is not None]
        result[f"{minutes}m"] = {
            "mean": sum(values) / len(values) if values else None,
            "positive_rate": sum(v > 0 for v in values) / len(values) if values else None,
        }
    return result


def analyze_split(dev_db: Path, holdout_db: Path) -> dict[str, object]:
    dev_conn, dev = _load(dev_db)
    hold_conn, holdout = _load(holdout_db)
    try:
        for row in dev:
            row["forward"] = _forward(dev_conn, row)
        for row in holdout:
            row["forward"] = _forward(hold_conn, row)

        strategies = sorted({r["strategy"] for r in dev} | {r["strategy"] for r in holdout})
        output = {}
        for strategy in strategies:
            drows = [r for r in dev if r["strategy"] == strategy]
            hrows = [r for r in holdout if r["strategy"] == strategy]
            features = sorted({k for r in drows for k in r["features"]})
            feature_out = {}
            for feature in features:
                values = [r["features"][feature] for r in drows if feature in r["features"]]
                if len(values) < MIN_BUCKET_SAMPLES * 3:
                    continue
                q1, q2 = _quantile(values, 1 / 3), _quantile(values, 2 / 3)
                buckets = {}
                for label, rows in (("development", drows), ("holdout", hrows)):
                    groups = {name: [] for name in ("LOW", "MID", "HIGH")}
                    for row in rows:
                        value = row["features"].get(feature)
                        if value is not None:
                            groups[_bucket(value, q1, q2)].append(row)
                    buckets[label] = {name: _summarize(group) for name, group in groups.items()}
                high = [r["forward"]["30m"] for r in buckets["holdout"]["HIGH"] if False]
                feature_out[feature] = {"q1": q1, "q2": q2, "buckets": buckets}
                for horizon in HORIZONS:
                    low = [r["forward"][f"{horizon}m"] for r in hrows
                           if r["features"].get(feature) is not None
                           and _bucket(r["features"][feature], q1, q2) == "LOW"
                           and r["forward"][f"{horizon}m"] is not None]
                    high = [r["forward"][f"{horizon}m"] for r in hrows
                            if r["features"].get(feature) is not None
                            and _bucket(r["features"][feature], q1, q2) == "HIGH"
                            and r["forward"][f"{horizon}m"] is not None]
                    feature_out[feature][f"high_minus_low_{horizon}m"] = (
                        (sum(high) / len(high) - sum(low) / len(low)) if low and high else None
                    )
                    feature_out[feature][f"ci95_{horizon}m"] = _bootstrap_ci(low, high) if low and high else (None, None)
                feature_out[feature]["candidate"] = _candidate(feature_out[feature])
            output[strategy] = feature_out
        return output
    finally:
        dev_conn.close()
        hold_conn.close()


def _candidate(feature: dict[str, object]) -> bool:
    for horizon in ("30m", "60m", "120m"):
        low = feature["buckets"]["holdout"]["LOW"]["samples"]
        high = feature["buckets"]["holdout"]["HIGH"]["samples"]
        diff = feature.get(f"high_minus_low_{horizon}")
        ci = feature.get(f"ci95_{horizon}")
        if low >= MIN_BUCKET_SAMPLES and high >= MIN_BUCKET_SAMPLES and diff is not None and ci[0] > 0.0 and abs(diff) >= 0.001:
            return True
    return False


def analyze_input_dir(input_dir: str) -> dict[str, object]:
    root = Path(input_dir)
    results = {}
    for path in sorted((root / "results").glob("*.json")):
        version = path.stem
        if version == "summary":
            continue
        results[version] = analyze_split(
            root / "work" / version / "development.sqlite3",
            root / "work" / version / "holdout.sqlite3",
        )
    if not results:
        raise ValueError("no strategy-family results found")
    return {"families": results}
