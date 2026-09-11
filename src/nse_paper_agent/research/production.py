from __future__ import annotations

import json
from datetime import timezone

from .audit import audit_from_decision
from .identity import ProductionIdentity, identity_from_manifest, require_production_decision, verify_identity

_STATE_KEY = "production_strategy_identity"


def activate(repo, decision) -> ProductionIdentity:
    """Persist an approved production identity without allowing replacement."""
    identity = require_production_decision(decision)
    audit = audit_from_decision(decision).record()
    existing = repo.db.get_state(_STATE_KEY)
    if existing is not None:
        current = ProductionIdentity(existing["version"], existing["config_hash"], existing["risk_hash"])
        if current != identity:
            raise RuntimeError("production strategy identity is immutable")
        return current

    with repo.db.transaction():
        repo.db.conn.execute(
            "INSERT INTO strategy_promotion_audit(strategy_version,state,approved,decided_at_utc,reasons_json,manifest_json) VALUES(?,?,?,?,?,?)",
            (
                audit["strategy_version"],
                audit["state"],
                int(audit["approved"]),
                decision.decided_at.astimezone(timezone.utc).isoformat(),
                json.dumps(audit["reasons"]),
                json.dumps(audit["manifest"], sort_keys=True),
            ),
        )
        repo.db.set_state(_STATE_KEY, {
            "version": identity.version,
            "config_hash": identity.config_hash,
            "risk_hash": identity.risk_hash,
        })
    return identity


def verify_persisted(repo, manifest) -> ProductionIdentity | None:
    stored = repo.db.get_state(_STATE_KEY)
    if stored is None:
        return None
    expected = ProductionIdentity(stored["version"], stored["config_hash"], stored["risk_hash"])
    verify_identity(expected, manifest)
    return expected
