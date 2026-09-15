#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from math import isfinite


def load_state(conn: sqlite3.Connection) -> dict[str, object]:
    rows = conn.execute("SELECT key, value FROM kv_state").fetchall()
    result: dict[str, object] = {}
    for key, value in rows:
        try:
            result[key] = json.loads(value)
        except json.JSONDecodeError:
            result[key] = value
    return result


def check_finite_positive(name: str, value: float) -> None:
    if not isfinite(value):
        raise SystemExit(f"{name} is not finite: {value}")


def reconcile(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    state = load_state(conn)

    starting_capital = float(state.get("starting_capital", 50000.0))
    cash = float(state.get("cash", 0.0))
    closed = conn.execute(
        """
        SELECT id, symbol, qty, entry_price, exit_price,
               entry_fee, exit_fee, gross_pnl, net_pnl,
               entry_ts_utc, exit_ts_utc, exit_reason
        FROM closed_trades
        ORDER BY id
        """
    ).fetchall()
    open_positions = conn.execute(
        """
        SELECT symbol, qty, entry_price, entry_fee, last_mark
        FROM positions
        ORDER BY symbol
        """
    ).fetchall()
    eod = conn.execute(
        """
        SELECT trading_date, cash, equity, gross, daily_start_equity, drawdown5
        FROM account_snapshots
        WHERE is_eod=1
        ORDER BY trading_date
        """
    ).fetchall()

    gross_pnl = sum(float(row["gross_pnl"]) for row in closed)
    fees = sum(float(row["entry_fee"]) + float(row["exit_fee"]) for row in closed)
    net_pnl = sum(float(row["net_pnl"]) for row in closed)
    check_cash = starting_capital + net_pnl

    for name, value in (
        ("starting_capital", starting_capital),
        ("cash", cash),
        ("gross_pnl", gross_pnl),
        ("fees", fees),
        ("net_pnl", net_pnl),
        ("cash_from_realized_pnl", check_cash),
    ):
        check_finite_positive(name, value)

    print("=== REALIZED LEDGER ===")
    print({
        "starting_capital": starting_capital,
        "closed_trades": len(closed),
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "starting_plus_net_pnl": check_cash,
        "final_cash": cash,
        "realized_cash_difference": cash - check_cash,
        "open_positions": len(open_positions),
    })

    if abs(cash - check_cash) > 0.01 and not open_positions:
        print("STATUS realized_cash_reconciliation=FAIL")
    elif open_positions:
        print("STATUS realized_cash_reconciliation=OPEN_POSITIONS_PRESENT")
    else:
        print("STATUS realized_cash_reconciliation=PASS")

    print("=== EOD EQUITY ===")
    peak = None
    max_dd = 0.0
    min_row = None
    for row in eod:
        equity = float(row["equity"])
        check_finite_positive("eod_equity", equity)
        if peak is None or equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak else 0.0
        if dd > max_dd:
            max_dd = dd
            min_row = row

    print({
        "eod_marks": len(eod),
        "first_eod_equity": float(eod[0]["equity"]) if eod else None,
        "last_eod_equity": float(eod[-1]["equity"]) if eod else None,
        "minimum_eod_equity": min((float(row["equity"]) for row in eod), default=None),
        "max_eod_peak_to_trough": max_dd,
        "max_drawdown_trading_date": min_row["trading_date"] if min_row else None,
    })

    # EOD equity must agree with cash plus the marked value represented by gross.
    eod_mismatches = []
    for row in eod:
        cash_value = float(row["cash"])
        equity = float(row["equity"])
        gross = float(row["gross"])
        if abs((cash_value + gross) - equity) > 0.01:
            eod_mismatches.append({
                "trading_date": row["trading_date"],
                "cash_plus_gross": cash_value + gross,
                "equity": equity,
                "difference": cash_value + gross - equity,
            })
    print({"eod_internal_mismatches": len(eod_mismatches)})
    if eod_mismatches:
        print("first_eod_internal_mismatch", eod_mismatches[0])

    print("=== EQUITY VS REALIZED ===")
    if eod:
        last_eod = float(eod[-1]["equity"])
        print({
            "last_eod_equity": last_eod,
            "final_cash": cash,
            "difference": last_eod - cash,
        })
    else:
        print({"last_eod_equity": None, "final_cash": cash, "difference": None})

    print("=== RESULT ===")
    if eod_mismatches:
        print("STATUS eod_internal_equity=FAIL")
    elif eod and not open_positions and abs(float(eod[-1]["equity"]) - cash) > 0.01:
        print("STATUS final_eod_vs_cash=CHECK")
    else:
        print("STATUS accounting=PASS")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile replay realized P&L, cash and EOD equity accounting.")
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    reconcile(args.db)


if __name__ == "__main__":
    main()
