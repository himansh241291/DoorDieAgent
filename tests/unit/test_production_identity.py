import pytest

from nse_paper_agent.research.governance import PromotionGate, build_manifest
from nse_paper_agent.research.identity import identity_from_manifest, require_production_decision, verify_identity
from nse_paper_agent.research.promotion import evaluate_promotion


def manifest(version="candidate-v2", sma=20):
    return build_manifest(version, {"sma": sma}, {"stop": 0.015}, "2026-01/2026-09")


def test_production_identity_is_derived_from_manifest():
    source = manifest("baseline-v1")
    identity = identity_from_manifest(source)
    assert identity.version == "baseline-v1"
    assert identity.config_hash == source.config_hash
    assert identity.risk_hash == source.risk_hash


def test_identity_verification_fails_on_config_change():
    expected = identity_from_manifest(manifest("baseline-v1", 20))
    with pytest.raises(RuntimeError, match="production strategy identity mismatch"):
        verify_identity(expected, manifest("baseline-v1", 21))


def test_identity_verification_fails_on_version_change():
    expected = identity_from_manifest(manifest("baseline-v1"))
    with pytest.raises(RuntimeError, match="production strategy identity mismatch"):
        verify_identity(expected, manifest("baseline-v2"))


def test_only_approved_production_decision_can_activate_identity():
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    decision = evaluate_promotion(manifest("baseline-v1"), metrics, metrics, metrics, PromotionGate(), True)
    identity = require_production_decision(decision)
    assert identity.version == "baseline-v1"


def test_rejected_decision_cannot_activate_identity():
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    bad = {"trades": 19, "max_drawdown": 0.05, "net_expectancy": 0}
    decision = evaluate_promotion(manifest("candidate-v3"), metrics, bad, metrics, PromotionGate(), True)
    with pytest.raises(ValueError, match="approved PRODUCTION"):
        require_production_decision(decision)
