from datetime import timezone

import pytest

from nse_paper_agent.research.governance import PromotionGate, build_manifest
from nse_paper_agent.research.lifecycle import StrategyState
from nse_paper_agent.research.promotion import evaluate_promotion


def _manifest():
    return build_manifest("candidate-v2", {"sma": 20}, {"stop": 0.015}, "2026-01/2026-09", {"source": "replay"})


def test_promotion_requires_all_gates_and_reaches_production():
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    decision = evaluate_promotion(_manifest(), metrics, metrics, metrics, PromotionGate(), True)
    assert decision.approved
    assert decision.state is StrategyState.PRODUCTION
    assert decision.reasons == ()
    assert decision.decided_at.tzinfo is timezone.utc


def test_failed_promotion_stays_candidate():
    good = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    bad = {"trades": 19, "max_drawdown": 0.05, "net_expectancy": 0}
    decision = evaluate_promotion(_manifest(), good, bad, good, PromotionGate(), True)
    assert not decision.approved
    assert decision.state is StrategyState.CANDIDATE
    assert "insufficient_oos_trades" in decision.reasons


def test_promotion_is_not_allowed_without_human_approval():
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    decision = evaluate_promotion(_manifest(), metrics, metrics, metrics, PromotionGate(), False)
    assert not decision.approved
    assert decision.state is StrategyState.CANDIDATE
    assert "human_approval_required" in decision.reasons


def test_promotion_preserves_manifest_identity():
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    manifest = _manifest()
    decision = evaluate_promotion(manifest, metrics, metrics, metrics, PromotionGate(), True)
    assert decision.manifest == manifest
    assert decision.strategy_version == manifest.version


def test_promotion_requires_a_valid_manifest():
    with pytest.raises(ValueError):
        build_manifest("", {}, {}, "window")
