from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


HORIZON_MINUTES = (5, 15, 30, 60, 120, 240)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _horizon_returns(
    bars,
    entry_ts: str,
    exit_ts: str,
    entry_price: float,
) -> dict[str, float | None]:
    entry = _parse_ts(entry_ts)
    exit_time = _parse_ts(exit_ts)
    result: dict[str, float | None] = {}
    for minutes in HORIZON_MINUTES:
        target = entry.timestamp() + minutes * 60
        value = None
        for bar in bars:
            end = _parse_ts(bar["end_utc"])
            if end > exit_time or end.timestamp() < target:
                continue
            value = (float(bar["close"]) - entry_price) / entry_price
            break
        result[f"{minutes}m"] = value
    return result


def analyze_trade_path(conn, trade: sqlite3.Row) -> dict[str, object]:
    symbol = trade["symbol"]
    entry_ts = trade["entry_ts_utc"]
    exit_ts = trade["exit_ts_utc"]
    entry_price = float(trade["entry_price"])

    bars = conn.execute(
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
    for bar in bars:
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

    return {
        "symbol": symbol,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_price": entry_price,
        "exit_price": float(trade["exit_price"]),
        "exit_reason": str(trade["exit_reason"]),
        "net_pnl": float(trade["net_pnl"]),
        "holding_minutes": float(trade["holding_seconds"]) / 60.0,
        "mfe": mfe,
        "mfe_minutes": mfe_minutes,
        "mae": mae,
        "mae_minutes": mae_minutes,
        "forward_close_returns": _horizon_returns(
            bars, entry_ts, exit_ts, entry_price
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
            ORDER BY id
            """
        ).fetchall()
        paths = [analyze_trade_path(conn, trade) for trade in trades]
    finally:
        conn.close()

    def mean(values):
        values = [float(v) for v in values if v is not None]
        return sum(values) / len(values) if values else None

    horizons = [f"{minutes}m" for minutes in HORIZON_MINUTES]
    return {
        "db": str(path),
        "trades": len(paths),
        "trade_paths": paths,
        "summary": {
            "mean_holding_minutes": mean(p["holding_minutes"] for p in paths),
            "mean_mfe": mean(p["mfe"] for p in paths),
            "mean_mae": mean(p["mae"] for p in paths),
            "horizon_mean_returns": {
                key: mean(p["forward_close_returns"][key] for p in paths)
                for key in horizons
            },
            "positive_return_rate": {
                key: (
                    sum(
                        p["forward_close_returns"][key] is not None
                        and p["forward_close_returns"][key] > 0
                        for p in paths
                    )
                    / sum(
                        p["forward_close_returns"][key] is not None
                        for p in paths
                    )
                    if any(
                        p["forward_close_returns"][key] is not None
                        for p in paths
                    )
                    else None
                )
                for key in horizons
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
