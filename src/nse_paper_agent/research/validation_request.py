from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from nse_paper_agent.strategy.proposal import StrategyProposal


@dataclass(frozen=True)
class StrategyValidationRequest:
    """Immutable handoff from learning/proposal into controlled validation."""

    proposal_id: str
    base_version: str
    proposed_version: str
    allowed_change_scope: str
    forbidden_change_scope: tuple[str, ...]
    hypothesis: str
    evidence: Mapping[str, float]
    target: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)
    validation_status: str = "PENDING"


def build_validation_request(proposal: StrategyProposal) -> StrategyValidationRequest:
    """Create a non-executable validation request from a bounded proposal."""
    if proposal.status != "PROPOSED":
        raise ValueError(f"proposal is not in PROPOSED state: {proposal.status}")
    if proposal.allowed_change_scope in proposal.forbidden_change_scope:
        raise ValueError("allowed change scope overlaps forbidden scope")
    return StrategyValidationRequest(
        proposal_id=proposal.proposal_id,
        base_version=proposal.base_version,
        proposed_version=proposal.proposed_version,
        allowed_change_scope=proposal.allowed_change_scope,
        forbidden_change_scope=proposal.forbidden_change_scope,
        hypothesis=proposal.hypothesis,
        evidence=dict(proposal.evidence),
        target=proposal.target,
        parameters=dict(proposal.parameters),
    )
