from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


HORIZON_MINUTES = (5, 15, 30, 60, 120, 240)
MFE_THRESHOLDS = (0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _horizon_returns(
    bars,
    anchor_ts: str,
    anchor_price: float,
) -> dict[str, float | None]:
    anchor = _parse_ts(anchor_ts)
    result: dict[str, float | None] = {}
    for minutes in HORIZON_MINUTES:
        target = anchor.timestamp() + minutes * 60
        value = None
        for bar in bars:
            end = _parse_ts(bar["end_utc"])
            if end.timestamp() < target:
                continue
            value = (float(bar["close"]) - anchor_price) / anchor_price
            break
        result[f"{minutes}m"] = value
    return result


def analyze_trade_path(conn, trade: sqlite3.Row) -> dict[str, object]:
    symbol = trade["symbol"]
    entry_ts = trade["entry_ts_utc"]
    exit_ts = trade["exit_ts_utc"]
    entry_price = float(trade["entry_price"])
    exit_price = float(trade["exit_price"])

    path_bars = conn.execute(
        """
        SELECT start_utc, end_utc, high, low, close
        FROM market_bars
        WHERE symbol = ?
          AND start_utc >= ?
          AND end_utc <= ?
        ORDER BY end_utc
        """,
        (symbol, entry_ts, exit_ts),
    ).fetchall()

    entry = _parse_ts(entry_ts)
    mfe = None
    mae = None
    mfe_minutes = None
    mae_minutes = None
    for bar in path_bars:
        high_return = (float(bar["high"]) - entry_price) / entry_price
        low_return = (float(bar["low"]) - entry_price) / entry_price
        elapsed_minutes = (
            _parse_ts(bar["end_utc"]) - entry
        ).total_seconds() / 60.0
        if mfe is None or high_return > mfe:
            mfe = high_return
            mfe_minutes = elapsed_minutes
        if mae is None or low_return < mae:
            mae = low_return
            mae_minutes = elapsed_minutes

    forward_bars = conn.execute(
        """
        SELECT end_utc, close
        FROM market_bars
        WHERE symbol = ?
          AND start_utc >= ?
        ORDER BY end_utc
        """,
        (symbol, entry_ts),
    ).fetchall()

    post_exit_bars = conn.execute(
        """
        SELECT end_utc, close
        FROM market_bars
        WHERE symbol = ?
          AND start_utc >= ?
        ORDER BY end_utc
        """,
        (symbol, exit_ts),
    ).fetchall()

    return {
        "symbol": symbol,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_reason": str(trade["exit_reason"]),
        "net_pnl": float(trade["net_pnl"]),
        "holding_minutes": float(trade["holding_seconds"]) / 60.0,
        "exit_gross_return": (exit_price - entry_price) / entry_price,
        "mfe": mfe,
        "mfe_minutes": mfe_minutes,
        "mae": mae,
        "mae_minutes": mae_minutes,
        "forward_close_returns": _horizon_returns(
            forward_bars,
            entry_ts,
            entry_price,
        ),
        "post_exit_close_returns": _horizon_returns(
            post_exit_bars,
            exit_ts,
            exit_price,
        ),
    }


def analyze_db(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        trades = conn.execute(
            """
            SELECT symbol, entry_price, exit_price, entry_ts_utc, exit_ts_utc,
                   exit_reason, holding_seconds, net_pnl
            FROM closed_trades
            """
        ).fetchall()
        paths = [analyze_trade_path(conn, trade) for trade in trades]
    finally:
        conn.close()

    def mean(values):
        values = [float(v) for v in values if v is not None]
        return sum(values) / len(values) if values else None

    def positive_rate(values):
        values = [float(v) for v in values if v is not None]
        return sum(v > 0 for v in values) / len(values) if values else None

    horizons = [f"{minutes}m" for minutes in HORIZON_MINUTES]
    return {
        "db": str(path),
        "trades": len(paths),
        "trade_paths": paths,
        "summary": {
            "mean_holding_minutes": mean(p["holding_minutes"] for p in paths),
            "mean_exit_gross_return": mean(p["exit_gross_return"] for p in paths),
            "mean_mfe": mean(p["mfe"] for p in paths),
            "mean_mae": mean(p["mae"] for p in paths),
            "horizon_mean_returns": {
                key: mean(p["forward_close_returns"][key] for p in paths)
                for key in horizons
            },
            "positive_return_rate": {
                key: positive_rate(
                    p["forward_close_returns"][key] for p in paths
                )
                for key in horizons
            },
            "post_exit_horizon_mean_returns": {
                key: mean(p["post_exit_close_returns"][key] for p in paths)
                for key in horizons
            },
            "post_exit_positive_return_rate": {
                key: positive_rate(
                    p["post_exit_close_returns"][key] for p in paths
                )
                for key in horizons
            },
            "mfe_threshold_hit_rate": {
                f"{threshold:.2%}": (
                    sum(
                        p["mfe"] is not None and p["mfe"] >= threshold
                        for p in paths
                    ) / len(paths)
                    if paths
                    else None
                )
                for threshold in MFE_THRESHOLDS
            },
            "exit_reason_counts": {
                reason: sum(p["exit_reason"] == reason for p in paths)
                for reason in sorted({p["exit_reason"] for p in paths})
            },
        },
    }


def analyze_input_dir(input_dir: str) -> dict[str, object]:
    root = Path(input_dir)
    rows = []
    for result_path in sorted((root / "results").glob("*.json")):
        version = result_path.stem
        if version == "summary":
            continue
        rows.append(
            {
                "strategy_version": version,
                "development": analyze_db(
                    root / "work" / version / "development.sqlite3"
                ),
                "holdout": analyze_db(
                    root / "work" / version / "holdout.sqlite3"
                ),
            }
        )
    if not rows:
        raise ValueError(f"no strategy-family results found under {root / 'results'}")
    return {"families": rows}
