#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.strategy_forensics import (
    HORIZON_MINUTES,
    analyze_input_dir,
)


def _print_summary(payload: dict[str, object], output: Path) -> None:
    for family in payload["families"]:
        print(f"\n=== {family['strategy_version']} ===")
        for split in ("development", "holdout"):
            section = family[split]
            summary = section["summary"]
            print(
                f"{split:10} trades={section['trades']:3d} "
                f"hold={summary['mean_holding_minutes']:.1f}m "
                f"exit={summary['mean_exit_gross_return']:.3%} "
                f"MFE={summary['mean_mfe']:.3%} "
                f"MAE={summary['mean_mae']:.3%}"
            )
            print("  entry-forward:", end="")
            for minutes in HORIZON_MINUTES:
                key = f"{minutes}m"
                value = summary["horizon_mean_returns"][key]
                positive = summary["positive_return_rate"][key]
                if value is not None:
                    print(
                        f" {key}={value:.3%}/{positive:.1%}",
                        end=""
                    )
            print()
            print("  post-exit:    ", end="")
            for minutes in HORIZON_MINUTES:
                key = f"{minutes}m"
                value = summary["post_exit_horizon_mean_returns"][key]
                positive = summary["post_exit_positive_return_rate"][key]
                if value is not None:
                    print(
                        f" {key}={value:.3%}/{positive:.1%}",
                        end=""
                    )
            print()
            print(
                "  exits:",
                summary["exit_reason_counts"],
            )
            print(
                "  MFE hit rates:",
                summary["mfe_threshold_hit_rate"],
            )
    print(f"\nWritten: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze completed strategy-family trade paths without rerunning replays."
    )
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/forensics.json")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only compact forensic summaries instead of the full JSON payload.",
    )
    args = parser.parse_args()

    payload = analyze_input_dir(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.summary:
        _print_summary(payload, output)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(f"result={output}")


if __name__ == "__main__":
    main()
