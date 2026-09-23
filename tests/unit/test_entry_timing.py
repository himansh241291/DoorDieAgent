from pathlib import Path

from nse_paper_agent.research.entry_timing import _bootstrap_ci, _bucket, _candidate, _quantile


def test_entry_timing_uses_three_development_buckets():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    q1 = _quantile(values, 1 / 3)
    q2 = _quantile(values, 2 / 3)
    assert _bucket(1.0, q1, q2) == "LOW"
    assert _bucket(3.0, q1, q2) == "MID"
    assert _bucket(6.0, q1, q2) == "HIGH"


def test_candidate_requires_sample_and_ci_gate():
    base = {
        "buckets": {"holdout": {"LOW": {"samples": 8}, "HIGH": {"samples": 8}}},
        "high_minus_low_30m": 0.002,
        "ci95_30m": (0.0005, 0.003),
        "high_minus_low_60m": None,
        "ci95_60m": (None, None),
        "high_minus_low_120m": None,
        "ci95_120m": (None, None),
    }
    assert _candidate(base)


def test_runner_is_syntactically_valid():
    runner = Path(__file__).parents[2] / "scripts" / "analyze_entry_timing.py"
    compile(runner.read_text(encoding="utf-8"), str(runner), "exec")


def test_bootstrap_ci_contains_observed_high_minus_low():
    high = [0.01, 0.02, 0.03, 0.015, 0.025, 0.018, 0.022, 0.027]
    low = [-0.01, -0.02, -0.015, -0.005, -0.012, -0.018, -0.008, -0.014]
    observed = sum(high) / len(high) - sum(low) / len(low)
    lower, upper = _bootstrap_ci(high, low)
    assert lower <= observed <= upper


def test_entry_timing_variant_filters_only_eligible_signal():
    from datetime import datetime, timezone
    from nse_paper_agent.domain.models import Signal
    from scripts.experiment_entry_timing import EntryTimingVariant

    class FakeStrategy:
        version = "fake-v1"
        def evaluate(self, *args, **kwargs):
            return Signal("TEST", datetime.now(timezone.utc), self.version, True, "entry", metadata={"feature": 2.0})

    blocked = EntryTimingVariant(FakeStrategy(), "feature", 1.0, "exclude_high").evaluate()
    assert blocked.eligible is False
    assert blocked.reason == "entry_timing_filter"

    allowed = EntryTimingVariant(FakeStrategy(), "feature", 3.0, "exclude_high").evaluate()
    assert allowed.eligible is True

    required = EntryTimingVariant(FakeStrategy(), "feature", 1.0, "require_high").evaluate()
    assert required.eligible is True
