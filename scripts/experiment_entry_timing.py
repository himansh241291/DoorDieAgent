#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from nse_paper_agent.data.provider import load_bars_csv
from nse_paper_agent.research.entry_timing import analyze_split
from nse_paper_agent.research.replay_validation import _run_split, _split_dates
from nse_paper_agent.strategy.families import MomentumExpansionStrategy, TrendPullbackStrategy


EXPERIMENTS = (
    (MomentumExpansionStrategy, "sma20", "exclude_high"),
    (TrendPullbackStrategy, "distance_sma20", "require_high"),
)


class EntryTimingVariant:
    def __init__(self, base, feature: str, threshold: float, mode: str):
        self.base = base
        self.version = f"{base.version}-entry-timing"
        self.feature = feature
        self.threshold = threshold
        self.mode = mode

    def evaluate(self, *args, **kwargs):
        signal = self.base.evaluate(*args, **kwargs)
        value = signal.metadata.get(self.feature)
        if not signal.eligible or value is None:
            return signal
        allowed = value <= self.threshold if self.mode == "exclude_high" else value > self.threshold
        if allowed:
            return signal
        return replace(signal, eligible=False, reason="entry_timing_filter")


def _thresholds(root: Path) -> dict[str, dict[str, object]]:
    out = {}
    for strategy_cls, feature, mode in EXPERIMENTS:
        name = strategy_cls.version
        result = analyze_split(
            root / "work" / name / "development.sqlite3",
            root / "work" / name / "holdout.sqlite3",
        )
        data = result[name][feature]
        out[name] = {
            "feature": feature,
            "threshold": data["q2"],
            "mode": mode,
            "development_samples": data["buckets"]["development"]["LOW"]["samples"]
            + data["buckets"]["development"]["MID"]["samples"]
            + data["buckets"]["development"]["HIGH"]["samples"],
        }
    return out


def _run_variant(bars, dev_dates, holdout_dates, strategy_cls, feature, threshold, mode, work):
    dev = _run_split(
        bars, set(dev_dates), "development",
        str(work / f"{strategy_cls.version}-entry-timing-development.sqlite3"),
        EntryTimingVariant(strategy_cls(), feature, threshold, mode),
    )
    holdout = _run_split(
        bars, set(holdout_dates), "holdout",
        str(work / f"{strategy_cls.version}-entry-timing-holdout.sqlite3"),
        EntryTimingVariant(strategy_cls(), feature, threshold, mode),
    )
    return dev, holdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay bounded entry-timing hypotheses without changing production strategies.")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--input-dir", default="strategy-family-sweep")
    parser.add_argument("--output", default="strategy-family-sweep/entry-timing-experiments.json")
    args = parser.parse_args()

    root = Path(args.input_dir)
    bars = load_bars_csv(args.bars)
    dev_dates, holdout_dates = _split_dates(bars)
    thresholds = _thresholds(root)
    work = root / "entry-timing-work"
    work.mkdir(parents=True, exist_ok=True)

    results = {}
    for strategy_cls, feature, mode in EXPERIMENTS:
        name = strategy_cls.version
        threshold = float(thresholds[name]["threshold"])
        dev, holdout = _run_variant(
            bars, dev_dates, holdout_dates, strategy_cls, feature, threshold, mode, work
        )
        results[name] = {
            "feature": feature,
            "threshold": threshold,
            "mode": mode,
            "development": dev.as_dict(),
            "holdout": holdout.as_dict(),
        }

    payload = {"experiments": results}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("=== ENTRY TIMING REPLAY EXPERIMENT ===")
    for name, data in results.items():
        for split in ("development", "holdout"):
            row = data[split]
            print(
                f"{name} {split}: trades={row['trades']} "
                f"net={row['net_pnl']:.2f} expectancy={row['expectancy']:.2f} "
                f"dd={row['max_drawdown']:.3%}"
            )
        dev = data["development"]
        hold = data["holdout"]
        print(
            f"{name} threshold={data['threshold']:.6f} mode={data['mode']} "
            f"holdout_net={hold['net_pnl']:.2f} holdout_expectancy={hold['expectancy']:.2f}"
        )
    print(f"Written: {output}")


if __name__ == "__main__":
    main()
