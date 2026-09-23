#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.exit_lifecycle import (
    DEFAULT_INITIAL_CAPITAL,
    policies,
    run_family,
)


def _compact(payload: dict[str, object]) -> None:
    for split in ("development", "holdout"):
        print(f"\n{split.upper()}")
        for policy, metrics in payload[split].items():
            print(
                f"{policy:28} "
                f"n={metrics['trades']:3d} "
                f"net={metrics['net_pnl']:9.2f} "
                f"exp={metrics['expectancy']:8.2f} "
                f"dd={metrics['max_drawdown_pct']:.2%} "
                f"win={metrics['win_rate']:.1%} "
                f"capture={metrics['mean_capture_ratio']:.2f}"
                if metrics["mean_capture_ratio"] is not None
                else
                f"{policy:28} "
                f"n={metrics['trades']:3d} "
                f"net={metrics['net_pnl']:9.2f} "
                f"exp={metrics['expectancy']:8.2f} "
                f"dd={metrics['max_drawdown_pct']:.2%} "
                f"win={metrics['win_rate']:.1%} "
                f"capture=None"
            )
            print(f"  exits={metrics['exit_reasons']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research-only fixed-entry exit lifecycle simulation."
    )
    parser.add_argument("--bars", required=True)
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/exit-lifecycle.json")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    root = Path(args.input_dir)
    versions = sorted(
        p.stem for p in (root / "results").glob("*.json")
        if p.stem != "summary"
    )

    payload: dict[str, object] = {
        "initial_capital_reference": str(DEFAULT_INITIAL_CAPITAL),
        "hard_stop_pct": "0.015",
        "target_pct": "0.05",
        "note": "Research-only. Entry events are fixed from existing family replay DBs. Portfolio capacity/interactions are not re-simulated.",
        "policies": policies(),
        "families": {},
    }

    for version in versions:
        print(f"RUNNING {version}", flush=True)
        payload["families"][version] = run_family(
            root / "work" / version / "development.sqlite3",
            root / "work" / version / "holdout.sqlite3",
            args.bars,
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.summary:
        for version, family in payload["families"].items():
            print(f"\n=== {version} ===")
            _compact(family)
        print(f"\nWritten: {output}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(f"result={output}")


if __name__ == "__main__":
    main()
