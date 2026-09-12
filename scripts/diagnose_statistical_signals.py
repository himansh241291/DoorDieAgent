#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, time
from decimal import Decimal

from nse_paper_agent.domain.models import Bar, Regime
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy

EVENT_TIME = time(13, 55)
SYMBOLS = {"ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    with open(args.bars, newline="") as handle:
        rows = list(csv.DictReader(handle))

    history = {symbol: [] for symbol in SYMBOLS}
    strategy = BaselineBreakoutStrategy()
    shown = 0

    for row in rows:
        symbol = row["symbol"]
        if symbol not in SYMBOLS:
            continue
        bar = Bar(
            symbol=symbol,
            start=datetime.fromisoformat(row["start"]),
            end=datetime.fromisoformat(row["end"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        history[symbol].append(bar)
        if bar.end.time() != EVENT_TIME or bar.end.date().isoformat() < "2025-04-30":
            continue

        signal = strategy.evaluate(
            history[symbol],
            bar.end,
            Regime.RISK_ON,
            0.5,
            False,
            False,
            True,
            True,
        )
        print({
            "symbol": symbol,
            "event": bar.end.isoformat(),
            "close": float(bar.close),
            "eligible": signal.eligible,
            "reason": signal.reason,
            "score": signal.score,
            "metadata": signal.metadata,
        })
        shown += 1
        if shown >= args.limit:
            break

    if shown == 0:
        raise SystemExit("No mature 13:55 events found")


if __name__ == "__main__":
    main()
