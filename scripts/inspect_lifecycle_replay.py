#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--symbol", default="GAMMA")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    print(f"DB={args.db}")
    print(f"SYMBOL={args.symbol}")

    print("FILLS")
    fills = con.execute(
        """
        SELECT side, qty, price, fee, ts_utc, reason, strategy_version
        FROM simulated_fills
        WHERE symbol=?
        ORDER BY ts_utc
        """,
        (args.symbol,),
    ).fetchall()
    for row in fills:
        print(dict(row))

    print("CLOSED_TRADES")
    trades = con.execute(
        """
        SELECT symbol, qty, entry_price, exit_price, gross_pnl, net_pnl,
               entry_ts_utc, exit_ts_utc, exit_reason, holding_seconds
        FROM closed_trades
        WHERE symbol=?
        ORDER BY entry_ts_utc
        """,
        (args.symbol,),
    ).fetchall()
    for row in trades:
        print(dict(row))

    print("COOLDOWNS")
    cooldowns = con.execute(
        """
        SELECT symbol, until_utc, reason
        FROM cooldowns
        WHERE symbol=?
        ORDER BY until_utc
        """,
        (args.symbol,),
    ).fetchall()
    for row in cooldowns:
        print(dict(row))

    print("SIGNALS_LAST")
    signals = con.execute(
        """
        SELECT bar_end_utc, eligible, reason, score
        FROM signals
        WHERE symbol=?
        ORDER BY bar_end_utc DESC
        LIMIT ?
        """,
        (args.symbol, args.limit),
    ).fetchall()
    for row in reversed(signals):
        print(dict(row))

    # Show the first few persisted market bars after the actual entry time.
    if fills:
        buy = next((r for r in fills if r["side"] == "BUY"), None)
        if buy:
            print("POST_ENTRY_BARS")
            bars = con.execute(
                """
                SELECT end_utc, close, low, high
                FROM market_bars
                WHERE symbol=? AND end_utc > ?
                ORDER BY end_utc
                LIMIT ?
                """,
                (args.symbol, buy["ts_utc"], args.limit),
            ).fetchall()
            for row in bars:
                print(dict(row))

    con.close()


if __name__ == "__main__":
    main()
