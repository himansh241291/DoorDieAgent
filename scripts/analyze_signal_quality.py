#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.signal_quality import analyze_input_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze entry-signal quality using development-derived feature buckets."
    )
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument(
        "--output",
        default="strategy-family-sweep/signal-quality.json",
    )
    args = parser.parse_args()

    payload = analyze_input_dir(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    for version, family in payload["families"].items():
        print(f"\n=== {version} ===")
        for strategy, splits in family.items():
            print(f"\n{strategy}")
            for split, features in splits.items():
                for feature, summary in features.items():
                    print(f"  {split} {feature}")
                    print(
                        f"    cutpoints={summary['development_cutpoints']} "
                        f"buckets={summary['buckets']}"
                    )

    print(f"\nWritten: {output}")


if __name__ == "__main__":
    main()
