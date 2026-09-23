from decimal import Decimal
import sqlite3

from nse_paper_agent.research.exit_lifecycle import (
    Entry,
    Bar,
    simulate,
    summarize,
)


def _bars():
    return [
        Bar(__import__("datetime").datetime.fromisoformat("2026-01-01T10:05:00+00:00"), Decimal("100.2"), Decimal("99.8"), Decimal("100.1")),
        Bar(__import__("datetime").datetime.fromisoformat("2026-01-01T10:10:00+00:00"), Decimal("101.0"), Decimal("100.0"), Decimal("100.8")),
        Bar(__import__("datetime").datetime.fromisoformat("2026-01-01T10:15:00+00:00"), Decimal("101.5"), Decimal("100.4"), Decimal("101.2")),
        Bar(__import__("datetime").datetime.fromisoformat("2026-01-01T10:20:00+00:00"), Decimal("102.0"), Decimal("100.8"), Decimal("101.8")),
        Bar(__import__("datetime").datetime.fromisoformat("2026-01-01T10:25:00+00:00"), Decimal("102.0"), Decimal("100.9"), Decimal("101.7")),
    ]


def _entry():
    return Entry(
        id=1,
        symbol="TEST",
        qty=10,
        price=Decimal("100"),
        ts=__import__("datetime").datetime.fromisoformat("2026-01-01T10:00:00+00:00"),
    )


def test_time_exit_happens_at_requested_horizon():
    result = simulate(_entry(), _bars(), "TIME_15M")
    assert result is not None
    assert result.reason == "TIME_15M"
    assert result.exit_ts.isoformat() == "2026-01-01T10:15:00+00:00"


def test_hard_stop_wins_over_research_exit():
    bars = _bars() + [
        Bar(
            __import__("datetime").datetime.fromisoformat("2026-01-01T10:30:00+00:00"),
            Decimal("101"),
            Decimal("98.4"),
            Decimal("98.7"),
        )
    ]
    result = simulate(_entry(), bars, "TIME_60M")
    assert result is not None
    assert result.reason == "STOP"


def test_mfe_protection_does_not_exit_on_trigger_bar():
    result = simulate(_entry(), _bars(), "MFE_PROTECT_0.50")
    assert result is not None
    assert result.reason == "EOD"


def test_summary_reports_drawdown_and_capture():
    result = simulate(_entry(), _bars(), "TIME_15M")
    summary = summarize([result])
    assert summary["trades"] == 1
    assert summary["net_pnl"] < 0
    assert summary["max_drawdown_pct"] > 0
    assert summary["mean_capture_ratio"] is not None
