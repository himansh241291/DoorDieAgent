#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


NUMERIC_GATE = {
    "min_dev_trades": 50,
    "min_holdout_trades": 20,
    "max_holdout_drawdown": 0.04,
    "min_holdout_expectancy": 0.0,
}


def analyze_db(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        trades = conn.execute(
            """
            SELECT qty, entry_price, exit_price, entry_fee, exit_fee,
                   gross_pnl, net_pnl, holding_seconds, exit_reason
            FROM closed_trades
            ORDER BY id
            """
        ).fetchall()
        fills = conn.execute(
            """
            SELECT qty, price, fee, slippage_estimate, side
            FROM simulated_fills
            """
        ).fetchall()
    finally:
        conn.close()

    trade_count = len(trades)
    gross_pnl = sum(float(row["gross_pnl"]) for row in trades)
    net_pnl = sum(float(row["net_pnl"]) for row in trades)
    fees = sum(float(row["entry_fee"]) + float(row["exit_fee"]) for row in trades)
    notional = sum(float(row["qty"]) * float(row["entry_price"]) for row in trades)
    holding_seconds = [int(row["holding_seconds"]) for row in trades]
    gross_returns = [
        (float(row["exit_price"]) - float(row["entry_price"])) / float(row["entry_price"])
        for row in trades
        if float(row["entry_price"]) > 0
    ]
    net_returns = [
        float(row["net_pnl"]) / (float(row["qty"]) * float(row["entry_price"]))
        for row in trades
        if float(row["qty"]) > 0 and float(row["entry_price"]) > 0
    ]
    slippage_cost = sum(
        abs(float(row["slippage_estimate"])) * int(row["qty"])
        for row in fills
    )
    traded_notional = sum(float(row["price"]) * int(row["qty"]) for row in fills)

    reasons = {}
    for row in trades:
        reason = str(row["exit_reason"])
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "db": str(path),
        "trades": trade_count,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "fees": fees,
        "fees_per_trade": fees / trade_count if trade_count else 0.0,
        "entry_notional": notional,
        "average_entry_notional": notional / trade_count if trade_count else 0.0,
        "average_holding_minutes": (
            sum(holding_seconds) / len(holding_seconds) / 60.0
            if holding_seconds
            else 0.0
        ),
        "average_gross_return": (
            sum(gross_returns) / len(gross_returns) if gross_returns else 0.0
        ),
        "average_net_return": (
            sum(net_returns) / len(net_returns) if net_returns else 0.0
        ),
        "estimated_slippage_cost": slippage_cost,
        "estimated_slippage_bps": (
            slippage_cost / traded_notional * 10000
            if traded_notional
            else 0.0
        ),
        "exit_reasons": reasons,
        "wins": sum(float(row["net_pnl"]) > 0 for row in trades),
        "losses": sum(float(row["net_pnl"]) <= 0 for row in trades),
    }


def load_replay_result(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def analyze_family(root: Path, version: str) -> dict[str, object]:
    result_path = root / "results" / f"{version}.json"
    dev_db = root / "work" / version / "development.sqlite3"
    holdout_db = root / "work" / version / "holdout.sqlite3"

    result = load_replay_result(result_path)
    dev = result["development"]
    holdout = result["holdout"]

    numeric_failures = []
    if int(dev["trades"]) < NUMERIC_GATE["min_dev_trades"]:
        numeric_failures.append("insufficient_development_trades")
    if int(holdout["trades"]) < NUMERIC_GATE["min_holdout_trades"]:
        numeric_failures.append("insufficient_holdout_trades")
    if float(holdout["max_drawdown"]) > NUMERIC_GATE["max_holdout_drawdown"]:
        numeric_failures.append("holdout_drawdown_exceeded")
    if float(holdout["expectancy"]) <= NUMERIC_GATE["min_holdout_expectancy"]:
        numeric_failures.append("holdout_expectancy_not_positive")

    return {
        "strategy_version": version,
        "numeric_gate": {
            "eligible": not numeric_failures,
            "failures": numeric_failures,
        },
        "development": {
            "metrics": {
                "trades": int(dev["trades"]),
                "net_pnl": float(dev["net_pnl"]),
                "expectancy": float(dev["expectancy"]),
                "max_drawdown": float(dev["max_drawdown"]),
            },
            "economics": analyze_db(dev_db),
        },
        "holdout": {
            "metrics": {
                "trades": int(holdout["trades"]),
                "net_pnl": float(holdout["net_pnl"]),
                "expectancy": float(holdout["expectancy"]),
                "max_drawdown": float(holdout["max_drawdown"]),
            },
            "economics": analyze_db(holdout_db),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze completed strategy-family replays without rerunning them."
    )
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/economics.json")
    args = parser.parse_args()

    root = Path(args.input_dir)
    versions = sorted(
        path.stem
        for path in (root / "results").glob("*.json")
        if path.stem != "summary"
    )
    if not versions:
        raise SystemExit(f"no strategy-family results found under {root / 'results'}")

    rows = [analyze_family(root, version) for version in versions]
    payload = {
        "numeric_gate": NUMERIC_GATE,
        "families": rows,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"result={output}")


if __name__ == "__main__":
    main()
