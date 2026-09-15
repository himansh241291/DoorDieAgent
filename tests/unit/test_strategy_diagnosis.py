from datetime import datetime, timezone

from nse_paper_agent.strategy.diagnosis import StrategyDiagnosisEngine, StrategyDiagnosisPolicy
from nse_paper_agent.strategy.evidence import StrategyEvidence, StrategyEvidenceEngine, StrategyOutcome


BASE = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)


def outcome(version, pnl, index, symbol="AAA", regime="RISK_ON", reason="TARGET"):
    entry = BASE.replace(day=1 + index)
    return StrategyOutcome(
        version=version,
        net_pnl=float(pnl),
        exit_ts=entry,
        regime=regime,
        symbol=symbol,
        entry_ts=entry,
        exit_reason=reason,
        holding_seconds=1800,
    )


def make_evidence(rows, recent_window=20):
    return StrategyEvidenceEngine(recent_window=recent_window).compute(rows, ["a"])["a"]


def test_insufficient_evidence_does_not_diagnose():
    evidence = make_evidence([outcome("a", 10, i) for i in range(5)])
    diagnosis = StrategyDiagnosisEngine(StrategyDiagnosisPolicy(min_overall_samples=20)).diagnose(evidence)
    assert not diagnosis.eligible
    assert diagnosis.reason == "insufficient_overall_evidence"
    assert diagnosis.findings == ()


def test_recent_degradation_generates_bounded_hypothesis():
    rows = [outcome("a", 20, i) for i in range(15)] + [outcome("a", -20, i + 15) for i in range(5)]
    evidence = make_evidence(rows, recent_window=5)
    diagnosis = StrategyDiagnosisEngine().diagnose(evidence)
    assert diagnosis.eligible
    assert diagnosis.reason == "patterns_detected"
    finding = next(item for item in diagnosis.findings if item.code == "RECENT_DEGRADATION")
    assert finding.severity == "HIGH"
    assert finding.samples == 5
    assert "risk" not in finding.hypothesis.lower()


def test_forced_exit_dominance_is_detected_without_changing_exit_policy():
    rows = [outcome("a", -5, i, reason="FORCED") for i in range(12)] + [outcome("a", 2, i + 12) for i in range(8)]
    evidence = make_evidence(rows)
    diagnosis = StrategyDiagnosisEngine().diagnose(evidence)
    finding = next(item for item in diagnosis.findings if item.code == "FORCED_EXIT_DOMINANT")
    assert finding.samples == 12
    assert finding.metrics["forced_exit_share"] == 0.6
    assert "mandatory exit" in finding.hypothesis.lower()


def test_weak_regime_is_detected_only_with_enough_samples():
    rows = [outcome("a", -4, i, regime="CAUTIOUS") for i in range(10)] + [outcome("a", 5, i + 10, regime="RISK_ON") for i in range(10)]
    evidence = make_evidence(rows)
    diagnosis = StrategyDiagnosisEngine().diagnose(evidence)
    findings = [item for item in diagnosis.findings if item.code == "REGIME_WEAKNESS"]
    assert len(findings) == 1
    assert findings[0].statement.endswith("CAUTIOUS.")


def test_weak_time_bucket_is_detected_with_enough_samples():
    rows = []
    for i in range(10):
        rows.append(outcome("a", -3, i, symbol="AAA"))
    for i in range(10, 20):
        rows.append(outcome("a", 5, i, symbol="BBB"))
    evidence = make_evidence(rows)
    diagnosis = StrategyDiagnosisEngine().diagnose(evidence)
    assert diagnosis.eligible
    assert any(item.code == "TIME_BUCKET_WEAKNESS" for item in diagnosis.findings)


def test_finding_count_is_bounded():
    rows = [outcome("a", -10, i, symbol="AAA", regime="CAUTIOUS", reason="FORCED") for i in range(20)]
    evidence = make_evidence(rows)
    diagnosis = StrategyDiagnosisEngine(StrategyDiagnosisPolicy(max_findings=2)).diagnose(evidence)
    assert len(diagnosis.findings) == 2
