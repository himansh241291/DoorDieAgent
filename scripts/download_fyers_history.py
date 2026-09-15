#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from nse_paper_agent.data.fyers import FyersHistoryConfig, FyersHistoricalClient

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "doordieagent"
HEADER = ["symbol", "start", "end", "open", "high", "low", "close", "volume"]


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


def _chunks(start: date, end: date, max_days: int = 100):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _cache_name(symbol: str, start: date, end: date) -> str:
    safe_symbol = symbol.replace(":", "_").replace("/", "_")
    return f"{safe_symbol}__{start.isoformat()}__{end.isoformat()}.csv"


def _write_csv(output: Path, bars) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADER)
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


def _read_cache(path: Path):
    from nse_paper_agent.data.provider import load_bars_csv

    return load_bars_csv(str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Download FYERS NSE 5-minute historical candles for DoorDieAgent replay")
    parser.add_argument("--symbols", required=True, help="comma-separated FYERS symbols, e.g. NSE:NIFTY50-INDEX,NSE:RELIANCE-EQ")
    parser.add_argument("--start", required=True, type=_date, help="inclusive start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_date, help="inclusive end date, YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path, help="normalized DoorDieAgent CSV output")
    parser.add_argument("--cache-dir", type=Path, help="per-symbol/per-chunk cache directory; defaults to <output>.cache")
    parser.add_argument("--request-interval", type=float, default=2.0, help="minimum seconds between FYERS requests (default: 2)")
    parser.add_argument("--app-id-file", type=Path, default=DEFAULT_CONFIG_DIR / "fyers_app_id")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_CONFIG_DIR / "fyers_access_token")
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")
    if args.request_interval < 0:
        parser.error("--request-interval must be non-negative")

    symbols = sorted({item.strip() for item in args.symbols.split(",") if item.strip()})
    if not symbols:
        parser.error("--symbols must contain at least one symbol")

    cache_dir = args.cache_dir or Path(f"{args.output}.cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    client = FyersHistoricalClient(
        FyersHistoryConfig(
            app_id=_credentials(args.app_id_file),
            access_token=_credentials(args.token_file),
            min_request_interval_seconds=args.request_interval,
        )
    )

    all_bars = []
    total_chunks = sum(1 for _ in _chunks(args.start, args.end)) * len(symbols)
    completed = 0

    for symbol in symbols:
        print(f"Symbol {symbol}", flush=True)
        for chunk_start, chunk_end in _chunks(args.start, args.end):
            cache_path = cache_dir / _cache_name(symbol, chunk_start, chunk_end)
            completed += 1
            if cache_path.exists():
                bars = _read_cache(cache_path)
                print(f"  [{completed}/{total_chunks}] cached {chunk_start}..{chunk_end} bars={len(bars)}", flush=True)
            else:
                print(f"  [{completed}/{total_chunks}] downloading {chunk_start}..{chunk_end}", flush=True)
                bars = client.fetch(symbol, chunk_start, chunk_end)
                _write_csv(cache_path, bars)
                print(f"    bars={len(bars)} zero_volume={sum(1 for bar in bars if bar.volume == 0)}", flush=True)
            all_bars.extend(bars)

    deduped = {(bar.symbol, bar.start): bar for bar in all_bars}
    merged = [deduped[key] for key in sorted(deduped)]
    _write_csv(args.output, merged)
    print(f"Wrote {len(merged)} bars to {args.output}")
    print(f"Cache: {cache_dir}")


if __name__ == "__main__":
    main()
