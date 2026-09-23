#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.entry_timing import analyze_input_dir


def pct(value):
    return f"{value:.3%}" if value is not None else "NA"


def main():
    parser = argparse.ArgumentParser(description="Bounded entry-timing diagnosis.")
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/entry-timing.json")
    args = parser.parse_args()
    payload = analyze_input_dir(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print("=== ENTRY TIMING DIAGNOSIS ===")
    for family, strategies in payload["families"].items():
        print(f"=== {family} ===")
        for strategy, features in strategies.items():
            for feature, data in features.items():
                candidates = []
                for horizon in ("30m", "60m", "120m"):
                    if data.get("candidate") and data.get(f"ci95_{horizon}") != (None, None):
                        candidates.append(f"{horizon} diff={pct(data[f'high_minus_low_{horizon}'])} ci={tuple(pct(x) for x in data[f'ci95_{horizon}'])}")
                if candidates:
                    print(f"{strategy} {feature}: CANDIDATE")
                    for item in candidates:
                        print(f"  {item}")
    print(f"Written: {output}")


if __name__ == "__main__":
    main()
