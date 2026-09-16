#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
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

# RANGE_BOUND was already validated separately. RISK_OFF and DATA_DEGRADED are
# already hard-blocked by baseline-breakout-v1, so eligibility challengers for
# those states are behavioral no-ops and do not justify another full replay.
EXPERIMENTS = (
    ("symbol_eligibility", "NSE:RELIANCE-EQ", "Exclude NSE:RELIANCE-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:TCS-EQ", "Exclude NSE:TCS-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:HDFCBANK-EQ", "Exclude NSE:HDFCBANK-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:ICICIBANK-EQ", "Exclude NSE:ICICIBANK-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:INFY-EQ", "Exclude NSE:INFY-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
    ("symbol_eligibility", "NSE:SBIN-EQ", "Exclude NSE:SBIN-EQ entries and test whether avoiding this symbol improves the baseline strategy's out-of-sample expectancy."),
)


def _safe_name(scope: str, target: str) -> str:
    safe_target = target.lower().replace(":", "_").replace("/", "_").replace(" ", "_")
    return f"{scope}-{safe_target}"


def run_experiment(scope: str, target: str, hypothesis: str, bars: str, root: Path) -> dict[str, object]:
    name = _safe_name(scope, target)
    work_dir = root / "work" / name
    output = root / "results" / f"{name}.json"
    request = StrategyValidationRequest(
        proposal_id=f"sweep:{scope}:{target}",
        base_version="baseline-breakout-v1",
        proposed_version=f"baseline-breakout-v1-challenger-{scope}-{target.lower().replace(':', '_').replace('/', '_').replace(' ', '_')}",
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


def summarize(name: str, payload: dict[str, object]) -> dict[str, object]:
    dev = payload["development"]
    holdout = payload["holdout"]
    return {
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bounded challenger validation sweep as one parallelized job.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--output-dir", default="validation-sweep")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--only", nargs="*", default=None, help="Optional experiment names, e.g. symbol_eligibility-nse_reliance-eq")
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    selected = set(args.only) if args.only else None
    experiments = [item for item in EXPERIMENTS if selected is None or _safe_name(item[0], item[1]) in selected]
    summary: list[dict[str, object]] = []

    if not experiments:
        raise SystemExit("no experiments selected")

    print(f"Running {len(experiments)} experiments with up to {min(args.workers, len(experiments))} workers", flush=True)
    futures = {}
    with ProcessPoolExecutor(max_workers=min(args.workers, len(experiments))) as pool:
        for scope, target, hypothesis in experiments:
            name = _safe_name(scope, target)
            print(f"QUEUED {name}", flush=True)
            futures[pool.submit(run_experiment, scope, target, hypothesis, args.bars, root)] = name

        for future in as_completed(futures):
            name = futures[future]
            try:
                payload = future.result()
                row = summarize(name, payload)
                summary.append(row)
                print(f"\n=== COMPLETED {name} ===", flush=True)
                print(json.dumps(row, indent=2, sort_keys=True), flush=True)
            except Exception as exc:
                row = {"experiment": name, "status": "ERROR", "error": str(exc)}
                summary.append(row)
                print(f"\n=== ERROR {name} ===\n{exc}", flush=True)

    summary.sort(key=lambda item: str(item["experiment"]))
    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nsummary={summary_path}")


if __name__ == "__main__":
    main()
