from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo


HORIZONS = (30, 60, 120, 240)
MIN_DEVELOPMENT_SAMPLES = 12
IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class EntryRecord:
    symbol: str
    strategy_version: str
    entry_ts: datetime
    net_pnl: float
    entry_price: float
    features: dict[str, float]


@dataclass(frozen=True)
class Bucket:
    name: str
    lower: float | None
    upper: float | None


def _finite(value) -> bool:
    return value is not None and isfinite(float(value))


def _time_bucket(ts: datetime) -> str:
    local = ts.astimezone(IST)
    minutes = local.hour * 60 + local.minute
    if minutes < 11 * 60 + 30:
        return "MORNING"
    if minutes < 13 * 60 + 30:
        return "MIDDAY"
    return "AFTERNOON"


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires values")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _buckets(values: list[float]) -> list[Bucket]:
    q1 = _quantile(values, 1 / 3)
    q2 = _quantile(values, 2 / 3)
    return [
        Bucket("LOW", None, q1),
        Bucket("MID", q1, q2),
        Bucket("HIGH", q2, None),
    ]


def _bucket_for(value: float, buckets: list[Bucket]) -> str:
    if value <= buckets[0].upper:
        return buckets[0].name
    if value <= buckets[1].upper:
        return buckets[1].name
    return buckets[2].name


def _forward_returns(
    conn: sqlite3.Connection,
    symbol: str,
    entry_ts: datetime,
    entry_price: float,
) -> dict[str, float | None]:
    rows = conn.execute(
        """
        SELECT end_utc, close
        FROM market_bars
        WHERE symbol = ?
          AND start_utc >= ?
        ORDER BY end_utc
        """,
        (symbol, entry_ts.isoformat()),
    ).fetchall()
    result: dict[str, float | None] = {}
    for minutes in HORIZONS:
        target = entry_ts.timestamp() + minutes * 60
        value = None
        for row in rows:
            end = datetime.fromisoformat(row[0])
            if end.timestamp() >= target:
                value = (float(row[1]) - entry_price) / entry_price
                break
        result[f"{minutes}m"] = value
    return result


def _load_entries(db_path: Path) -> list[EntryRecord]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        trades = conn.execute(
            """
            SELECT symbol, strategy_version, entry_ts_utc, entry_price, net_pnl
            FROM closed_trades
            ORDER BY entry_ts_utc, id
            """
        ).fetchall()

        signals = conn.execute(
            """
            SELECT symbol, strategy_version, bar_end_utc, score, metadata_json
            FROM signals
            WHERE eligible = 1
            ORDER BY bar_end_utc
            """
        ).fetchall()

        signal_rows = {}
        for row in signals:
            key = (
                row["symbol"],
                row["strategy_version"],
                row["bar_end_utc"],
            )
            metadata = json.loads(row["metadata_json"] or "{}")
            features = {}
            if _finite(row["score"]):
                features["score"] = float(row["score"])
            for key_name, raw in metadata.items():
                if isinstance(raw, (int, float)) and _finite(raw):
                    features[str(key_name)] = float(raw)
            signal_rows[key] = features

        result: list[EntryRecord] = []
        for trade in trades:
            key = (
                trade["symbol"],
                trade["strategy_version"],
                trade["entry_ts_utc"],
            )
            features = signal_rows.get(key)
            if features is None:
                continue
            result.append(
                EntryRecord(
                    symbol=str(trade["symbol"]),
                    strategy_version=str(trade["strategy_version"]),
                    entry_ts=datetime.fromisoformat(trade["entry_ts_utc"]),
                    net_pnl=float(trade["net_pnl"]),
                    entry_price=float(trade["entry_price"]),
                    features=features,
                )
            )
        return result
    finally:
        conn.close()


def _feature_summary(
    entries: list[EntryRecord],
    thresholds: list[Bucket],
    feature: str,
    conn: sqlite3.Connection,
) -> dict[str, object]:
    grouped: dict[str, list[EntryRecord]] = {bucket.name: [] for bucket in thresholds}
    for entry in entries:
        value = entry.features.get(feature)
        if value is not None:
            grouped[_bucket_for(value, thresholds)].append(entry)

    output: dict[str, object] = {
        "development_cutpoints": {
            "q1": thresholds[0].upper,
            "q2": thresholds[1].upper,
        },
        "buckets": {},
    }

    for name, rows in grouped.items():
        forward: dict[str, list[float]] = {f"{m}m": [] for m in HORIZONS}
        for row in rows:
            values = _forward_returns(conn, row.symbol, row.entry_ts, row.entry_price)
            for key, value in values.items():
                if value is not None:
                    forward[key].append(value)

        pnls = [row.net_pnl for row in rows]
        output["buckets"][name] = {
            "samples": len(rows),
            "actual_expectancy": sum(pnls) / len(pnls) if pnls else None,
            "actual_net_pnl": sum(pnls),
            "forward_mean_returns": {
                key: sum(values) / len(values) if values else None
                for key, values in forward.items()
            },
            "forward_positive_rate": {
                key: sum(value > 0 for value in values) / len(values)
                if values
                else None
                for key, values in forward.items()
            },
        }
    return output


def analyze_db(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        all_entries = _load_entries(path)
        strategy_versions = sorted({entry.strategy_version for entry in all_entries})
        payload: dict[str, object] = {"db": str(path), "strategies": {}}

        for version in strategy_versions:
            entries = [entry for entry in all_entries if entry.strategy_version == version]
            feature_names = sorted(
                {name for entry in entries for name in entry.features}
            )
            version_payload = {
                "trades": len(entries),
                "time_buckets": {},
                "features": {},
            }

            time_rows: dict[str, list[EntryRecord]] = {}
            for entry in entries:
                time_rows.setdefault(_time_bucket(entry.entry_ts), []).append(entry)
            for name, rows in sorted(time_rows.items()):
                pnls = [row.net_pnl for row in rows]
                version_payload["time_buckets"][name] = {
                    "samples": len(rows),
                    "actual_expectancy": sum(pnls) / len(pnls) if pnls else None,
                    "actual_net_pnl": sum(pnls),
                }

            for feature in feature_names:
                values = [
                    entry.features[feature]
                    for entry in entries
                    if _finite(entry.features.get(feature))
                ]
                if len(values) < MIN_DEVELOPMENT_SAMPLES:
                    continue
                thresholds = _buckets(values)
                version_payload["features"][feature] = _feature_summary(
                    entries,
                    thresholds,
                    feature,
                    conn,
                )

            payload["strategies"][version] = version_payload
        return payload
    finally:
        conn.close()


def analyze_family_split(
    development_db: Path,
    holdout_db: Path,
) -> dict[str, object]:
    dev_entries = _load_entries(development_db)
    hold_entries = _load_entries(holdout_db)

    dev_conn = sqlite3.connect(development_db)
    hold_conn = sqlite3.connect(holdout_db)
    dev_conn.row_factory = sqlite3.Row
    hold_conn.row_factory = sqlite3.Row
    try:
        versions = sorted(
            {entry.strategy_version for entry in dev_entries}
            | {entry.strategy_version for entry in hold_entries}
        )
        output: dict[str, object] = {}

        for version in versions:
            dev = [x for x in dev_entries if x.strategy_version == version]
            hold = [x for x in hold_entries if x.strategy_version == version]
            features = sorted({k for x in dev for k in x.features})

            version_out = {"development": {}, "holdout": {}}
            for feature in features:
                values = [
                    x.features[feature]
                    for x in dev
                    if _finite(x.features.get(feature))
                ]
                if len(values) < MIN_DEVELOPMENT_SAMPLES:
                    continue
                buckets = _buckets(values)
                version_out["development"][feature] = _feature_summary(
                    dev, buckets, feature, dev_conn
                )
                version_out["holdout"][feature] = _feature_summary(
                    hold, buckets, feature, hold_conn
                )
            output[version] = version_out
        return output
    finally:
        dev_conn.close()
        hold_conn.close()


def analyze_input_dir(input_dir: str) -> dict[str, object]:
    root = Path(input_dir)
    versions = sorted(
        path.stem
        for path in (root / "results").glob("*.json")
        if path.stem != "summary"
    )
    if not versions:
        raise ValueError("no strategy-family results found")
    return {
        "families": {
            version: analyze_family_split(
                root / "work" / version / "development.sqlite3",
                root / "work" / version / "holdout.sqlite3",
            )
            for version in versions
        }
    }
