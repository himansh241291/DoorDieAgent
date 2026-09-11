from datetime import datetime, timezone

from nse_paper_agent.research.audit import audit_from_decision
from nse_paper_agent.research.governance import PromotionGate, build_manifest
from nse_paper_agent.research.promotion import evaluate_promotion


def test_promotion_audit_preserves_approved_identity():
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    manifest = build_manifest("candidate-v2", {"sma": 20}, {"stop": 0.015}, "2026-01/2026-09")
    decision = evaluate_promotion(manifest, metrics, metrics, metrics, PromotionGate(), True)
    audit = audit_from_decision(decision)
    record = audit.record()
    assert record["strategy_version"] == manifest.version
    assert record["state"] == "PRODUCTION"
    assert record["approved"] is True
    assert record["manifest"]["config_hash"] == manifest.config_hash
    assert record["manifest"]["risk_hash"] == manifest.risk_hash
    assert record["decided_at"].endswith("+00:00")


def test_rejected_promotion_audit_is_explicit():
    good = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    bad = {"trades": 19, "max_drawdown": 0.05, "net_expectancy": 0}
    manifest = build_manifest("candidate-v3", {"rsi": 15}, {"stop": 0.015}, "window")
    decision = evaluate_promotion(manifest, good, bad, good, PromotionGate(), True)
    record = audit_from_decision(decision).record()
    assert record["state"] == "CANDIDATE"
    assert record["approved"] is False
    assert "insufficient_oos_trades" in record["reasons"]
