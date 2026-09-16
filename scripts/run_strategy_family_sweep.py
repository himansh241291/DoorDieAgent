#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from nse_paper_agent.data.provider import load_bars_csv
from nse_paper_agent.research.replay_validation import _run_split, _split_dates
from nse_paper_agent.strategy.families import STRATEGY_FAMILIES


def run_family(strategy_cls, bars_path: str, root: Path) -> dict[str, object]:
    name = strategy_cls.version
    bars = load_bars_csv(bars_path)
    dev_dates, holdout_dates = _split_dates(bars)
    work = root / "work" / name
    work.mkdir(parents=True, exist_ok=True)
    development = _run_split(
        bars,
        set(dev_dates),
        "development",
        str(work / "development.sqlite3"),
        strategy_cls(),
    )
    holdout = _run_split(
        bars,
        set(holdout_dates),
        "holdout",
        str(work / "holdout.sqlite3"),
        strategy_cls(),
    )
    payload = {
        "strategy_version": name,
        "development": development.as_dict(),
        "holdout": holdout.as_dict(),
    }
    output = root / "results" / f"{name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "strategy_version": name,
        "dev_trades": development.trades,
        "dev_net_pnl": development.net_pnl,
        "dev_expectancy": development.expectancy,
        "dev_drawdown": development.max_drawdown,
        "holdout_trades": holdout.trades,
        "holdout_net_pnl": holdout.net_pnl,
        "holdout_expectancy": holdout.expectancy,
        "holdout_drawdown": holdout.max_drawdown,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent strategy-family research on the fixed FYERS replay.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--output-dir", default="strategy-family-sweep")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    print(f"Running {len(STRATEGY_FAMILIES)} independent strategy families with up to {args.workers} workers", flush=True)

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=min(args.workers, len(STRATEGY_FAMILIES))) as pool:
        futures = {}
        for strategy_cls in STRATEGY_FAMILIES:
            print(f"QUEUED {strategy_cls.version}", flush=True)
            futures[pool.submit(run_family, strategy_cls, args.bars, root)] = strategy_cls.version

        for future in as_completed(futures):
            name = futures[future]
            try:
                row = future.result()
                row["status"] = "COMPLETED"
                results.append(row)
                print(f"\n=== COMPLETED {name} ===", flush=True)
                print(json.dumps(row, indent=2, sort_keys=True), flush=True)
            except Exception as exc:
                row = {"strategy_version": name, "status": "ERROR", "error": str(exc)}
                results.append(row)
                print(f"\n=== ERROR {name} ===\n{exc}", flush=True)

    results.sort(key=lambda row: str(row["strategy_version"]))
    summary = root / "summary.json"
    summary.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nsummary={summary}", flush=True)


if __name__ == "__main__":
    main()
