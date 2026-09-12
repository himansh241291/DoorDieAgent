#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate STOP -> cooldown lifecycle in a replay database.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--symbol", default="GAMMA")
    parser.add_argument("--cooldown-minutes", type=int, default=120)
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    fills = con.execute(
        """
        SELECT side, ts_utc, reason, qty, price, fee
        FROM simulated_fills
        WHERE symbol=?
        ORDER BY ts_utc
        """,
        (args.symbol,),
    ).fetchall()

    stops = [row for row in fills if row["side"] == "SELL" and row["reason"] == "STOP"]
    if len(stops) != 1:
        raise SystemExit(f"Expected exactly one STOP for {args.symbol}; found {len(stops)}")

    stop = stops[0]
    stop_ts = datetime.fromisoformat(stop["ts_utc"])
    expected_until = stop_ts + timedelta(minutes=args.cooldown_minutes)

    cooldown = con.execute(
        "SELECT symbol, until_utc, reason FROM cooldowns WHERE symbol=?",
        (args.symbol,),
    ).fetchone()
    if cooldown is None:
        raise SystemExit(f"No cooldown persisted for {args.symbol}")

    actual_until = datetime.fromisoformat(cooldown["until_utc"])
    seconds_error = abs((actual_until - expected_until).total_seconds())
    if seconds_error > 1:
        raise SystemExit(
            f"Cooldown mismatch: expected {expected_until.isoformat()}, "
            f"actual {actual_until.isoformat()}"
        )

    violating = con.execute(
        """
        SELECT bar_end_utc, reason, eligible
        FROM signals
        WHERE symbol=?
          AND bar_end_utc > ?
          AND bar_end_utc < ?
          AND reason='stop_cooldown'
        ORDER BY bar_end_utc
        """,
        (args.symbol, stop["ts_utc"], cooldown["until_utc"]),
    ).fetchall()

    all_in_window = con.execute(
        """
        SELECT COUNT(*)
        FROM signals
        WHERE symbol=?
          AND bar_end_utc > ?
          AND bar_end_utc < ?
        """,
        (args.symbol, stop["ts_utc"], cooldown["until_utc"]),
    ).fetchone()[0]

    reentry_fills = con.execute(
        """
        SELECT COUNT(*)
        FROM simulated_fills
        WHERE symbol=?
          AND side='BUY'
          AND ts_utc > ?
          AND ts_utc < ?
        """,
        (args.symbol, stop["ts_utc"], cooldown["until_utc"]),
    ).fetchone()[0]

    con.close()

    print({
        "symbol": args.symbol,
        "stop_ts_utc": stop["ts_utc"],
        "cooldown_until_utc": cooldown["until_utc"],
        "expected_until_utc": expected_until.isoformat(),
        "configured_minutes": args.cooldown_minutes,
        "signals_during_cooldown": all_in_window,
        "signals_blocked_by_stop_cooldown": len(violating),
        "reentries_during_cooldown": reentry_fills,
        "cooldown_persisted": True,
        "cooldown_verified": seconds_error <= 1 and reentry_fills == 0,
    })

    if reentry_fills != 0:
        raise SystemExit("Cooldown violation: BUY occurred before cooldown expiry")
    if all_in_window and len(violating) == 0:
        raise SystemExit("Cooldown was persisted but no stop_cooldown signals were recorded")


if __name__ == "__main__":
    main()
