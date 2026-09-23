import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from nse_paper_agent.research.signal_quality import (
    _buckets,
    _bucket_for,
    _quantile,
)


def test_quantiles_and_bucket_assignment():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    buckets = _buckets(values)
    assert buckets[0].upper == _quantile(values, 1 / 3)
    assert buckets[1].upper == _quantile(values, 2 / 3)
    assert _bucket_for(1.0, buckets) == "LOW"
    assert _bucket_for(3.0, buckets) == "MID"
    assert _bucket_for(6.0, buckets) == "HIGH"

def test_signal_quality_runner_is_syntactically_valid():
    runner = Path(__file__).parents[2] / "scripts" / "analyze_signal_quality.py"
    source = runner.read_text(encoding="utf-8")
    compile(source, str(runner), "exec")
