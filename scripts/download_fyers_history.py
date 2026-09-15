#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import tempfile
from datetime import date
from pathlib import Path

from nse_paper_agent.data.fyers import FyersHistoryConfig, FyersHistoricalClient

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "doordieagent"


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def _credentials(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit(f"credential file is empty: {path}")
    return value


def _write_csv(output: Path, bars) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["symbol", "start", "end", "open", "high", "low", "close", "volume"])
            for bar in bars:
                writer.writerow(
                    [
                        bar.symbol,
                        bar.start.isoformat(),
                        bar.end.isoformat(),
                        str(bar.open),
                        str(bar.high),
                        str(bar.low),
                        str(bar.close),
                        str(bar.volume),
                    ]
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Download FYERS NSE 5-minute historical candles for DoorDieAgent replay")
    parser.add_argument("--symbols", required=True, help="comma-separated FYERS symbols, e.g. NSE:NIFTY50-INDEX,NSE:RELIANCE-EQ")
    parser.add_argument("--start", required=True, type=_date, help="inclusive start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_date, help="inclusive end date, YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path, help="normalized DoorDieAgent CSV output")
    parser.add_argument("--app-id-file", type=Path, default=DEFAULT_CONFIG_DIR / "fyers_app_id")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_CONFIG_DIR / "fyers_access_token")
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    symbols = sorted({item.strip() for item in args.symbols.split(",") if item.strip()})
    if not symbols:
        parser.error("--symbols must contain at least one symbol")

    client = FyersHistoricalClient(
        FyersHistoryConfig(
            app_id=_credentials(args.app_id_file),
            access_token=_credentials(args.token_file),
        )
    )

    all_bars = []
    for symbol in symbols:
        print(f"Downloading {symbol} {args.start}..{args.end}", flush=True)
        bars = client.fetch_range(symbol, args.start, args.end)
        zero_volume = sum(1 for bar in bars if bar.volume == 0)
        print(f"  bars={len(bars)} zero_volume={zero_volume}", flush=True)
        all_bars.extend(bars)

    all_bars.sort(key=lambda bar: (bar.end, bar.symbol))
    _write_csv(args.output, all_bars)
    print(f"Wrote {len(all_bars)} bars to {args.output}")


if __name__ == "__main__":
    main()
