from pathlib import Path

from nse_paper_agent.research.entry_timing import _bucket, _candidate, _quantile


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
