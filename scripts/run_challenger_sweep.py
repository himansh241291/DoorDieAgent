#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_paper_agent.research.replay_validation import _config, execute_validation
from nse_paper_agent.research.validation_plan import ValidationPlanner
from nse_paper_agent.research.validation_request import StrategyValidationRequest

FORBIDDEN = (
    "risk_limits",
    "hard_stop",
    "position_limits",
    "kill_switch",
    "capital_rules",
    "execution_safety",
    "production_identity",
)

EXPERIMENTS = (
    ("regime_eligibility", "RISK_OFF", "Exclude RISK_OFF entries and test whether avoiding risk-off market regimes improves the baseline strategy's out-of-sample expectancy."),
    ("regime_eligibility", "DATA_DEGRADED", "Exclude DATA_DEGRADED entries and test whether avoiding degraded-data regimes improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:RELIANCE-EQ", "Exclude NSE:RELIANCE-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:TCS-EQ", "Exclude NSE:TCS-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:HDFCBANK-EQ", "Exclude NSE:HDFCBANK-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:ICICIBANK-EQ", "Exclude NSE:ICICIBANK-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:INFY-EQ", "Exclude NSE:INFY-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:SBIN-EQ", "Exclude NSE:SBIN-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
)


def run_experiment(scope: str, target: str, hypothesis: str, bars: str, root: Path) -> dict[str, object]:
    safe_target = target.lower().replace(":", "_").replace("/", "_").replace(" ", "_")
    name = f"{scope}-{safe_target}"
    work_dir = root / "work" / name
    output = root / "results" / f"{name}.json"
    request = StrategyValidationRequest(
        proposal_id=f"sweep:{scope}:{target}",
        base_version="baseline-breakout-v1",
        proposed_version=f"baseline-breakout-v1-challenger-{scope}-{safe_target}",
        allowed_change_scope=scope,
        forbidden_change_scope=FORBIDDEN,
        hypothesis=hypothesis,
        evidence={},
        target=target,
        parameters={},
    )
    cfg = _config()
    risk_config = cfg["risk"] | cfg["account"] | cfg["execution"]
    plan = ValidationPlanner(min_trading_days=60).plan(request, risk_config, "dataset-derived")
    result = execute_validation(plan, bars, str(work_dir))
    payload = result.as_dict()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bounded challenger validation sweep as one sequential job.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--output-dir", default="validation-sweep")
    parser.add_argument("--only", nargs="*", default=None, help="Optional experiment names, e.g. regime_eligibility-RISK_OFF")
    args = parser.parse_args()

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    selected = set(args.only) if args.only else None
    summary: list[dict[str, object]] = []

    for scope, target, hypothesis in EXPERIMENTS:
        safe_target = target.lower().replace(":", "_").replace("/", "_").replace(" ", "_")
        name = f"{scope}-{safe_target}"
        if selected is not None and name not in selected:
            continue
        print(f"\n=== RUNNING {name} ===", flush=True)
        try:
            payload = run_experiment(scope, target, hypothesis, args.bars, root)
            dev = payload["development"]
            holdout = payload["holdout"]
            row = {
                "experiment": name,
                "status": "PASS",
                "dev_trades": dev["trades"],
                "dev_net_pnl": dev["net_pnl"],
                "dev_expectancy": dev["expectancy"],
                "dev_drawdown": dev["max_drawdown"],
                "holdout_trades": holdout["trades"],
                "holdout_net_pnl": holdout["net_pnl"],
                "holdout_expectancy": holdout["expectancy"],
                "holdout_drawdown": holdout["max_drawdown"],
            }
        except Exception as exc:
            row = {"experiment": name, "status": "ERROR", "error": str(exc)}
            summary.append(row)
            print(f"ERROR: {exc}", flush=True)
            continue
        summary.append(row)
        print(json.dumps(row, indent=2, sort_keys=True), flush=True)

    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nsummary={summary_path}")


if __name__ == "__main__":
    main()
