from __future__ import annotations

from dataclasses import dataclass

from .governance import StrategyManifest
from .lifecycle import StrategyState


@dataclass(frozen=True)
class ProductionIdentity:
    version: str
    config_hash: str
    risk_hash: str


def identity_from_manifest(manifest: StrategyManifest) -> ProductionIdentity:
    return ProductionIdentity(manifest.version, manifest.config_hash, manifest.risk_hash)


def verify_identity(expected: ProductionIdentity, manifest: StrategyManifest) -> None:
    actual = identity_from_manifest(manifest)
    if actual != expected:
        raise RuntimeError(
            "production strategy identity mismatch: "
            f"expected={expected} actual={actual}"
        )


def require_production_decision(decision) -> ProductionIdentity:
    if not decision.approved or decision.state is not StrategyState.PRODUCTION:
        raise ValueError("only an approved PRODUCTION decision can become production identity")
    return identity_from_manifest(decision.manifest)
