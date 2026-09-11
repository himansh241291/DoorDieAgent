import pytest

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.research.governance import PromotionGate, build_manifest
from nse_paper_agent.research.production import activate, verify_persisted
from nse_paper_agent.research.promotion import evaluate_promotion


def manifest(version="baseline-v1", sma=20):
    return build_manifest(version, {"sma": sma}, {"stop": 0.015}, "2026-01/2026-09")


def decision(source):
    metrics = {"trades": 60, "max_drawdown": 0.02, "net_expectancy": 10}
    return evaluate_promotion(source, metrics, metrics, metrics, PromotionGate(), True)


def test_production_identity_survives_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    db = Database(str(path)); db.initialize(); repo = Repository(db)
    source = manifest()
    identity = activate(repo, decision(source))
    assert verify_persisted(repo, source) == identity
    db.close()

    db = Database(str(path)); db.initialize(); repo = Repository(db)
    assert verify_persisted(repo, source) == identity
    audit = db.conn.execute("SELECT COUNT(*) AS n FROM strategy_promotion_audit").fetchone()
    assert audit["n"] == 1
    db.close()


def test_different_identity_cannot_replace_production(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3")); db.initialize(); repo = Repository(db)
    activate(repo, decision(manifest("baseline-v1", 20)))
    with pytest.raises(RuntimeError, match="immutable"):
        activate(repo, decision(manifest("baseline-v2", 20)))
    db.close()


def test_startup_verification_fails_closed_on_risk_hash_change(tmp_path):
    db = Database(str(tmp_path / "state.sqlite3")); db.initialize(); repo = Repository(db)
    activate(repo, decision(manifest("baseline-v1", 20)))
    with pytest.raises(RuntimeError, match="identity mismatch"):
        verify_persisted(repo, manifest("baseline-v1", 20). __class__(
            "baseline-v1", manifest("baseline-v1", 21).config_hash, manifest("baseline-v1", 20).risk_hash,
            "2026-01/2026-09", {}
        ))
    db.close()
