from __future__ import annotations

import pytest

from nse_paper_agent.research.validation_plan import ValidationPlanner
from nse_paper_agent.research.validation_request import StrategyValidationRequest


def test_incomplete_safety_envelope_is_reported_before_overlap():
    request = StrategyValidationRequest(
        proposal_id="p-1",
        base_version="baseline-breakout-v1",
        proposed_version="baseline-breakout-v1-challenger-2",
        allowed_change_scope="time_of_day_eligibility",
        forbidden_change_scope=("time_of_day_eligibility",),
        hypothesis="test",
        evidence={},
    )
    with pytest.raises(ValueError, match="complete safety envelope"):
        ValidationPlanner().plan(request, {}, "2025-09-15/2026-09-14")
