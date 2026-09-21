#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.strategy_family_economics import (
    NUMERIC_GATE,
    analyze_input_dir,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze completed strategy-family replays without rerunning them."
    )
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/economics.json")
    args = parser.parse_args()

    payload = analyze_input_dir(args.input_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"result={output}")


if __name__ == "__main__":
    main()
