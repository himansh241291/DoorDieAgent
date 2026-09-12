#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a deterministic lifecycle replay fixture that forces the GAMMA stop path."
    )
    parser.add_argument("--input", required=True, help="Input long-duration replay CSV")
    parser.add_argument("--output", required=True, help="Output lifecycle replay CSV")
    parser.add_argument(
        "--entry-date",
        default="2025-05-01",
        help="Trading date containing the constructed GAMMA breakout (default: 2025-05-01)",
    )
    parser.add_argument(
        "--entry-time",
        default="13:55",
        help="IST bar end time of the constructed GAMMA breakout (default: 13:55)",
    )
    args = parser.parse_args()

    source = Path(args.input)
    destination = Path(args.output)

    if not source.exists():
        raise SystemExit(f"Input fixture does not exist: {source}")

    with source.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = rows[0].keys() if rows else []

    required = {"symbol", "end", "close"}
    missing = required - set(fieldnames)
    if missing:
        raise SystemExit(f"Fixture is missing required columns: {sorted(missing)}")

    gamma = [row for row in rows if row["symbol"] == "GAMMA"]
    if not gamma:
        raise SystemExit("GAMMA rows not found")

    candidates = [
        row
        for row in gamma
        if row["end"].startswith(f"{args.entry_date}T{args.entry_time}:")
    ]

    if len(candidates) != 1:
        raise SystemExit(
            f"Expected exactly one GAMMA breakout at {args.entry_date} {args.entry_time}, "
            f"found {len(candidates)}"
        )

    entry_row = candidates[0]
    entry_close = Decimal(entry_row["close"])

    # PaperBroker buys from the ask and adds slippage. The configured hard
    # stop is 1.5% below simulated entry. A 3% drop in the post-entry bar
    # therefore deterministically crosses the stop while leaving production
    # strategy/risk code untouched.
    stop_test_close = entry_close * Decimal("0.970")
    entry_end = entry_row["end"]

    changed = 0
    armed = False
    entry_index = None

    for index, row in enumerate(rows):
        if row["symbol"] != "GAMMA":
            continue
        if row["end"] == entry_end:
            armed = True
            entry_index = index
            continue
        if not armed:
            continue
        if row["end"].startswith(f"{args.entry_date}T"):
            row["open"] = f"{stop_test_close:.6f}"
            row["high"] = f"{stop_test_close:.6f}"
            row["low"] = f"{stop_test_close:.6f}"
            row["close"] = f"{stop_test_close:.6f}"
            changed += 1
        elif row["end"][:10] != args.entry_date:
            break

    if changed == 0:
        raise SystemExit("No post-entry GAMMA bars were modified")
    if entry_index is None:
        raise SystemExit("GAMMA breakout index was not found")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print({
        "input": str(source),
        "output": str(destination),
        "gamma_entry": entry_end,
        "breakout_close": float(entry_close),
        "stop_test_close": float(stop_test_close),
        "modified_post_entry_bars": changed,
    })


if __name__ == "__main__":
    main()
