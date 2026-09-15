from __future__ import annotations

from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.research.validation_plan import ValidationPlanner
from nse_paper_agent.research.validation_plan_store import ValidationPlanStore
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


def test_validation_plan_round_trip_and_idempotency(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3"))
    db.initialize()
    request = StrategyValidationRequest(
        proposal_id="proposal-1",
        base_version="baseline-breakout-v1",
        proposed_version="baseline-breakout-v1-challenger-2",
        allowed_change_scope="regime_eligibility",
        forbidden_change_scope=FORBIDDEN,
        hypothesis="Avoid weak regimes.",
        evidence={"regime_expectancy": -20.0},
    )
    plan = ValidationPlanner().plan(
        request,
        {"max_position": 10000, "hard_stop": 0.015},
        "2025-09-15/2026-09-14",
    )
    store = ValidationPlanStore(db)
    ts = datetime(2026, 9, 15, tzinfo=timezone.utc)
    assert store.save(plan, created_at=ts) is True
    assert store.save(plan, created_at=ts) is False
    loaded = store.get("proposal-1")
    assert loaded == plan
    db.close()
