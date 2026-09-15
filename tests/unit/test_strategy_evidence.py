from datetime import datetime, timedelta, timezone

from nse_paper_agent.strategy.evidence import StrategyEvidenceEngine, StrategyOutcome


BASE = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)


def outcome(version, pnl, index, symbol, regime, hour, reason="TARGET"):
    entry = BASE + timedelta(days=index, hours=hour - 9)
    return StrategyOutcome(
        version=version,
        net_pnl=float(pnl),
        exit_ts=entry + timedelta(minutes=30),
        regime=regime,
        symbol=symbol,
        entry_ts=entry,
        exit_reason=reason,
        holding_seconds=1800,
    )


def test_evidence_builds_overall_recent_and_context_buckets():
    rows = [
        outcome("a", 10, 0, "AAA", "RISK_ON", 10),
        outcome("a", -5, 1, "AAA", "RISK_ON", 12),
        outcome("a", 20, 2, "BBB", "CAUTIOUS", 14, "FORCED"),
        outcome("a", -15, 3, "BBB", "CAUTIOUS", 10, "STOP"),
    ]
    evidence = StrategyEvidenceEngine(recent_window=2).compute(rows, ["a", "inactive"])["a"]

    assert evidence.overall.samples == 4
    assert evidence.overall.expectancy == 2.5
    assert evidence.overall.win_rate == 0.5
    assert evidence.overall.gross_profit == 30
    assert evidence.overall.gross_loss == -20
    assert evidence.overall.profit_factor == 1.5
    assert evidence.overall.max_losing_streak == 1
    assert evidence.recent.samples == 2
    assert evidence.recent.expectancy == 2.5
    assert evidence.by_regime["RISK_ON"].samples == 2
    assert evidence.by_regime["CAUTIOUS"].samples == 2
    assert evidence.by_symbol["AAA"].net_pnl == 5
    assert evidence.by_symbol["BBB"].net_pnl == 5
    assert evidence.by_exit_reason["TARGET"].samples == 2
    assert evidence.by_time_bucket["MORNING"].samples == 2
    assert evidence.by_time_bucket["MIDDAY"].samples == 1
    assert evidence.by_time_bucket["AFTERNOON"].samples == 1


def test_evidence_ignores_inactive_and_nonfinite_outcomes():
    rows = [
        outcome("a", 10, 0, "AAA", "RISK_ON", 10),
        StrategyOutcome("inactive", 100, BASE + timedelta(days=2)),
        StrategyOutcome("a", float("nan"), BASE + timedelta(days=3)),
    ]
    result = StrategyEvidenceEngine().compute(rows, ["a"])
    assert result["a"].overall.samples == 1
    assert result["a"].overall.net_pnl == 10
