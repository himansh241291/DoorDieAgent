from datetime import datetime, timezone

from nse_paper_agent.strategy.diagnosis import DiagnosisFinding, StrategyDiagnosis
from nse_paper_agent.strategy.proposal import StrategyProposalEngine


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def finding(code: str, severity: str = "MEDIUM", target: str | None = None) -> DiagnosisFinding:
    return DiagnosisFinding(
        code=code,
        severity=severity,
        statement=f"Observed {code}.",
        hypothesis=f"Test a bounded change for {code}.",
        samples=20,
        metrics={"expectancy": -5.0},
        target=target,
    )


def test_proposal_engine_converts_diagnosis_to_data_only_proposals():
    diagnosis = StrategyDiagnosis("baseline-breakout-v1", True, (finding("REGIME_WEAKNESS", target="RISK_OFF"),))
    proposals = StrategyProposalEngine().propose(diagnosis)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.base_version == "baseline-breakout-v1"
    assert proposal.proposed_version == "baseline-breakout-v1-challenger-2-risk_off"
    assert proposal.finding_code == "REGIME_WEAKNESS"
    assert proposal.allowed_change_scope == "regime_eligibility"
    assert proposal.target == "RISK_OFF"
    assert proposal.parameters["target"] == "RISK_OFF"
    assert proposal.status == "PROPOSED"
    assert "risk_limits" in proposal.forbidden_change_scope
    assert "hard_stop" in proposal.forbidden_change_scope
    assert "production_identity" in proposal.forbidden_change_scope


def test_empty_or_ineligible_diagnosis_produces_no_proposals():
    engine = StrategyProposalEngine()
    assert engine.propose(StrategyDiagnosis("a", False, (finding("SYMBOL_WEAKNESS"),))) == ()
    assert engine.propose(StrategyDiagnosis("a", True, ())) == ()


def test_proposals_are_bounded():
    diagnosis = StrategyDiagnosis(
        "a",
        True,
        tuple(finding(code) for code in ("A", "B", "C", "D")),
    )
    proposals = StrategyProposalEngine(max_proposals=2).propose(diagnosis)
    assert len(proposals) == 2
    assert proposals[0].proposal_id == "a:A:global:1"
    assert proposals[1].proposal_id == "a:B:global:2"
    assert proposals[0].proposed_version == "a-challenger-2-global"
