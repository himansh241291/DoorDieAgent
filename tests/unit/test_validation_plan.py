from __future__ import annotations

import pytest

from nse_paper_agent.research.validation_plan import ValidationPlanner
from nse_paper_agent.research.validation_request import StrategyValidationRequest


FORBIDDEN = (
    "risk_limits",
    "hard_stop",
    "position_limits",
    "kill_switch",
    "capital_rules",
    "execution_safety",
    "production_identity",
)


def request(**overrides):
    values = dict(
        proposal_id="p-1",
        base_version="baseline-breakout-v1",
        proposed_version="baseline-breakout-v1-challenger-2",
        allowed_change_scope="time_of_day_eligibility",
        forbidden_change_scope=FORBIDDEN,
        hypothesis="Exclude a weak entry window.",
        evidence={"time_bucket_expectancy": -12.0},
    )
    values.update(overrides)
    return StrategyValidationRequest(**values)


def test_plan_freezes_safety_envelope_and_hashes_risk_config():
    plan = ValidationPlanner().plan(
        request(),
        {"max_position": 10000, "hard_stop": 0.015, "daily_loss": 0.02},
        "2025-09-15/2026-09-14",
    )
    assert plan.validation_status == "PLANNED"
    assert plan.split_policy == "chronological"
    assert plan.min_trading_days == 60
    assert len(plan.risk_config_hash) == 64
    assert plan.challenger_version.endswith("challenger-2")
    assert set(FORBIDDEN).issubset(plan.forbidden_change_scope)


def test_plan_rejects_non_pending_request():
    with pytest.raises(ValueError, match="not pending"):
        ValidationPlanner().plan(request(validation_status="PLANNED"), {}, "2025-09-15/2026-09-14")


def test_plan_rejects_same_version():
    with pytest.raises(ValueError, match="must differ"):
        ValidationPlanner().plan(
            request(proposed_version="baseline-breakout-v1"),
            {},
            "2025-09-15/2026-09-14",
        )


def test_plan_rejects_incomplete_safety_envelope():
    with pytest.raises(ValueError, match="complete safety envelope"):
        ValidationPlanner().plan(
            request(forbidden_change_scope=("time_of_day_eligibility",)),
            {},
            "2025-09-15/2026-09-14",
        )


def test_plan_rejects_blank_data_window():
    with pytest.raises(ValueError, match="data window"):
        ValidationPlanner().plan(request(), {}, "")
