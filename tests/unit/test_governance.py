import json

import pytest

from nse_paper_agent.research.governance import (
    PromotionGate,
    build_manifest,
    evaluate_candidate,
    promotion_report,
)


def test_promotion_requires_human_approval():
    good = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    ok, reasons = evaluate_candidate(good, good, good, PromotionGate(), False)
    assert not ok and "human_approval_required" in reasons


def test_promotion_passes_only_when_all_required_gates_pass():
    good = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    ok, reasons = evaluate_candidate(good, good, good, PromotionGate(), True)
    assert ok and reasons == []


def test_promotion_rejects_bad_oos_metrics():
    good = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    bad = {"trades": 20, "max_drawdown": 0.05, "net_expectancy": 0}
    ok, reasons = evaluate_candidate(good, bad, good, PromotionGate(), True)
    assert not ok
    assert {"insufficient_oos_trades", "oos_drawdown_exceeded", "oos_expectancy_not_positive"} <= set(reasons)


def test_non_finite_oos_metrics_fail_closed():
    good = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    bad = {"trades": 20, "max_drawdown": float("nan"), "net_expectancy": float("inf")}
    ok, reasons = evaluate_candidate(good, bad, good, PromotionGate(), True)
    assert not ok
    assert "oos_drawdown_exceeded" in reasons
    assert "oos_expectancy_not_positive" in reasons


def test_manifest_hash_is_deterministic_and_order_independent():
    a = build_manifest("baseline-breakout-v1", {"rsi": 14, "sma": 20}, {"stop": 0.015}, "2025-01-01/2026-01-01", {"market": "NSE"})
    b = build_manifest("baseline-breakout-v1", {"sma": 20, "rsi": 14}, {"stop": 0.015}, "2025-01-01/2026-01-01", {"market": "NSE"})
    assert a.config_hash == b.config_hash
    assert a.risk_hash == b.risk_hash


def test_manifest_changes_when_strategy_or_risk_changes():
    base = build_manifest("baseline-breakout-v1", {"rsi": 14}, {"stop": 0.015}, "window")
    strategy = build_manifest("baseline-breakout-v1", {"rsi": 15}, {"stop": 0.015}, "window")
    risk = build_manifest("baseline-breakout-v1", {"rsi": 14}, {"stop": 0.02}, "window")
    assert base.config_hash != strategy.config_hash
    assert base.risk_hash != risk.risk_hash


def test_manifest_requires_identity_and_data_window():
    with pytest.raises(ValueError):
        build_manifest("", {}, {}, "window")
    with pytest.raises(ValueError):
        build_manifest("candidate", {}, {}, "")


def test_report_records_manifest_provenance():
    manifest = build_manifest("candidate-v2", {"sma": 20}, {"stop": 0.015}, "2026-01/2026-09", {"source": "replay"})
    report = json.loads(promotion_report("candidate-v2", manifest.data_window, {}, {}, {}, {}, [], [], False, ["human_approval_required"], manifest))
    assert report["approved"] is False
    assert report["manifest"]["version"] == "candidate-v2"
    assert report["manifest"]["config_hash"] == manifest.config_hash
    assert report["manifest"]["risk_hash"] == manifest.risk_hash
