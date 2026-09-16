#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.replay_validation import _config, execute_validation
from nse_paper_agent.research.validation_request import StrategyValidationRequest
from nse_paper_agent.research.validation_plan import ValidationPlanner

FORBIDDEN = (
    "risk_limits",
    "hard_stop",
    "position_limits",
    "kill_switch",
    "capital_rules",
    "execution_safety",
    "production_identity",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a bounded challenger validation replay.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--scope", required=True, choices=("regime_eligibility", "time_of_day_eligibility", "symbol_eligibility"))
    parser.add_argument("--target", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--work-dir", default="validation-work")
    parser.add_argument("--output", default="validation-result.json")
    args = parser.parse_args()

    request = StrategyValidationRequest(
        proposal_id=f"manual-validation:{args.scope}:{args.target}",
        base_version="baseline-breakout-v1",
        proposed_version=f"baseline-breakout-v1-challenger-{args.scope}-{args.target.lower()}",
        allowed_change_scope=args.scope,
        forbidden_change_scope=FORBIDDEN,
        hypothesis=args.hypothesis,
        evidence={},
        target=args.target,
        parameters={},
    )
    cfg = _config()
    risk_config = cfg["risk"] | cfg["account"] | cfg["execution"]
    plan = ValidationPlanner(min_trading_days=60).plan(
        request,
        risk_config,
        "dataset-derived",
    )
    result = execute_validation(plan, args.bars, args.work_dir)
    payload = result.as_dict()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"result={output}")


if __name__ == "__main__":
    main()
