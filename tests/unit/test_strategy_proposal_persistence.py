from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.research.validation_request import build_validation_request
from nse_paper_agent.strategy.proposal import StrategyProposal
from nse_paper_agent.strategy.proposal_store import StrategyProposalStore


def _proposal() -> StrategyProposal:
    return StrategyProposal(
        proposal_id="baseline-breakout-v1:TIME_BUCKET_WEAKNESS:1",
        base_version="baseline-breakout-v1",
        proposed_version="baseline-breakout-v1-challenger-2",
        finding_code="TIME_BUCKET_WEAKNESS",
        severity="LOW",
        hypothesis="Test a time-of-day eligibility restriction for the afternoon window.",
        rationale="Observed expectancy is negative in the afternoon entry window.",
        evidence={"time_bucket_expectancy": -12.5},
        allowed_change_scope="time_of_day_eligibility",
        forbidden_change_scope=("risk_limits", "hard_stop", "kill_switch"),
    )


def test_proposal_store_is_idempotent_and_round_trips(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3"))
    db.initialize()
    store = StrategyProposalStore(db)
    proposal = _proposal()
    ts = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)

    assert store.save(proposal, created_at=ts) is True
    assert store.save(proposal, created_at=ts) is False

    restored = store.get(proposal.proposal_id)
    assert restored == proposal
    assert store.list_for_base_version(proposal.base_version) == (proposal,)
    db.close()


def test_validation_request_preserves_bounds(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3"))
    db.initialize()
    proposal = _proposal()

    request = build_validation_request(proposal)

    assert request.proposal_id == proposal.proposal_id
    assert request.base_version == proposal.base_version
    assert request.proposed_version == proposal.proposed_version
    assert request.allowed_change_scope == "time_of_day_eligibility"
    assert request.forbidden_change_scope == proposal.forbidden_change_scope
    assert request.evidence == {"time_bucket_expectancy": -12.5}
    db.close()


def test_validation_request_rejects_non_proposed_status():
    proposal = StrategyProposal(
        proposal_id="p1",
        base_version="baseline",
        proposed_version="baseline-challenger-2",
        finding_code="REGIME_WEAKNESS",
        severity="MEDIUM",
        hypothesis="bounded test",
        rationale="negative regime evidence",
        evidence={"regime_expectancy": -1.0},
        allowed_change_scope="regime_eligibility",
        forbidden_change_scope=("risk_limits",),
        status="APPROVED",
    )

    try:
        build_validation_request(proposal)
    except ValueError as exc:
        assert "PROPOSED" in str(exc)
    else:
        raise AssertionError("non-PROPOSED proposal must be rejected")
