from __future__ import annotations

import json
import sqlite3
from pathlib import Path


HORIZON_MINUTES = (5, 15, 30, 60, 120, 240)


def _horizon_return(conn, symbol: str, entry_ts: str, entry_price: float, exit_ts: str, minutes: int):
    row = conn.execute(
        """
        SELECT close
        FROM market_bars
        WHERE symbol = ?
          AND end_utc > ?
          AND end_utc <= datetime(?, ?)
        ORDER BY end_utc
        LIMIT 1
        """,
        (symbol, entry_ts, entry_ts, f"+{minutes} minutes"),
    ).fetchone()
    if row is None:
        return None
    return (float(row["close"]) - entry_price) / entry_price


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

    mfe = None
    mae = None
    mfe_minutes = None
    mae_minutes = None
    for bar in bars:
        high_return = (float(bar["high"]) - entry_price) / entry_price
        low_return = (float(bar["low"]) - entry_price) / entry_price
        elapsed_minutes = (
            __import__("datetime").datetime.fromisoformat(bar["end_utc"])
            - __import__("datetime").datetime.fromisoformat(entry_ts)
        ).total_seconds() / 60.0
        if mfe is None or high_return > mfe:
            mfe = high_return
            mfe_minutes = elapsed_minutes
        if mae is None or low_return < mae:
            mae = low_return
            mae_minutes = elapsed_minutes

    horizon = {
        f"{minutes}m": _horizon_return(
            conn, symbol, entry_ts, entry_price, exit_ts, minutes
        )
        for minutes in HORIZON_MINUTES
    }

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
        "forward_close_returns": horizon,
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
                for key in [f"{m}m" for m in HORIZON_MINUTES]
            },
            "positive_return_rate": {
                key: (
                    sum(
                        p["forward_close_returns"][key] is not None
                        and p["forward_close_returns"][key] > 0
                        for p in paths
                    )
                    / sum(p["forward_close_returns"][key] is not None for p in paths)
                    if any(p["forward_close_returns"][key] is not None for p in paths)
                    else None
                )
                for key in [f"{m}m" for m in HORIZON_MINUTES]
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
        dev_db = root / "work" / version / "development.sqlite3"
        holdout_db = root / "work" / version / "holdout.sqlite3"
        rows.append(
            {
                "strategy_version": version,
                "development": analyze_db(dev_db),
                "holdout": analyze_db(holdout_db),
            }
        )
    if not rows:
        raise ValueError(f"no strategy-family results found under {root / 'results'}")
    return {"families": rows}
