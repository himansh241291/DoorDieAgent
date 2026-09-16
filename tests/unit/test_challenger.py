from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nse_paper_agent.domain.models import Regime, Signal
from nse_paper_agent.research.challenger import BoundedChallenger, ChallengerFactory
from nse_paper_agent.research.validation_plan import ValidationPlan

IST = ZoneInfo("Asia/Kolkata")


class StubStrategy:
    version = "baseline-v1"

    def evaluate(self, bars, now, regime, sentiment_score, held, cooldown, liquid, feed_healthy):
        return Signal("ABC", now, self.version, True, "baseline_entry", 1.0, {"x": 1})


def plan(scope, target):
    return ValidationPlan(
        proposal_id="p1",
        base_version="baseline-v1",
        challenger_version="baseline-v1-challenger-2",
        hypothesis="bounded challenger",
        allowed_change_scope=scope,
        forbidden_change_scope=("risk_limits", "hard_stop", "position_limits", "kill_switch", "capital_rules", "execution_safety", "production_identity"),
        risk_config_hash="a" * 64,
        data_window="2025-09-15/2026-09-14",
        target=target,
    )


def evaluate(challenger, when, regime=Regime.RISK_ON):
    return challenger.evaluate([], when, regime, None, False, False, True, True)


def test_regime_challenger_excludes_only_target_regime():
    challenger = BoundedChallenger(StubStrategy(), plan("regime_eligibility", "RISK_OFF"))
    assert evaluate(challenger, datetime(2026, 1, 1, 9, 15, tzinfo=IST), Regime.RISK_ON).eligible is True
    blocked = evaluate(challenger, datetime(2026, 1, 1, 9, 15, tzinfo=IST), Regime.RISK_OFF)
    assert blocked.eligible is False
    assert blocked.reason == "challenger_eligibility_filter"
    assert blocked.strategy_version == challenger.version


def test_symbol_challenger_excludes_only_target_symbol():
    challenger = BoundedChallenger(StubStrategy(), plan("symbol_eligibility", "ABC"))
    blocked = evaluate(challenger, datetime(2026, 1, 1, 9, 15, tzinfo=IST))
    assert blocked.eligible is False
    assert blocked.reason == "challenger_eligibility_filter"


def test_time_bucket_challenger_excludes_target_window():
    challenger = BoundedChallenger(StubStrategy(), plan("time_of_day_eligibility", "AFTERNOON"))
    assert evaluate(challenger, datetime(2026, 1, 1, 12, 30, tzinfo=IST)).eligible is True
    blocked = evaluate(challenger, datetime(2026, 1, 1, 14, 0, tzinfo=IST))
    assert blocked.eligible is False


def test_unsupported_scope_is_rejected():
    with pytest.raises(ValueError, match="unsupported challenger change scope"):
        BoundedChallenger(StubStrategy(), plan("hard_stop", "x"))


def test_eligibility_challenger_requires_target():
    with pytest.raises(ValueError, match="requires a target"):
        BoundedChallenger(StubStrategy(), plan("symbol_eligibility", None))


def test_factory_returns_materialized_challenger():
    result = ChallengerFactory().build(StubStrategy(), plan("regime_eligibility", "RISK_OFF"))
    assert result.version == "baseline-v1-challenger-2"
    assert result.change_scope == "regime_eligibility"
    assert result.target == "RISK_OFF"
    assert result.strategy.version == result.version
