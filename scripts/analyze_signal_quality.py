#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.signal_quality import analyze_input_dir


def _pct(value):
    return f"{value:.3%}" if value is not None else "NA"


def _print_split(split: str, feature: str, family: dict[str, object]) -> None:
    buckets = family[split][feature]["buckets"]
    for name in ("LOW", "MID", "HIGH"):
        row = buckets[name]
        print(
            f"    {split:9} {feature:18} {name:4} "
            f"n={row['samples']:3d} "
            f"30m={_pct(row['forward_mean_returns']['30m']):>8} "
            f"60m={_pct(row['forward_mean_returns']['60m']):>8} "
            f"120m={_pct(row['forward_mean_returns']['120m']):>8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze entry-signal quality using development-derived feature buckets."
    )
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/signal-quality.json")
    args = parser.parse_args()

    payload = analyze_input_dir(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    for version, family in payload["families"].items():
        print(f"
=== {version} ===")
        for feature in sorted(family["development"]):
            _print_split("DEVELOP", feature, family)
            _print_split("HOLDOUT", feature, family)

    print(f"
Written: {output}")


if __name__ == "__main__":
    main()
