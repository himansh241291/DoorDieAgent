from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .governance import StrategyManifest
from .lifecycle import StrategyState


@dataclass(frozen=True)
class PromotionAudit:
    strategy_version: str
    state: StrategyState
    approved: bool
    decided_at: datetime
    reasons: tuple[str, ...]
    manifest: StrategyManifest

    def record(self) -> dict[str, Any]:
        return {
            "strategy_version": self.strategy_version,
            "state": self.state.value,
            "approved": self.approved,
            "decided_at": self.decided_at.astimezone(timezone.utc).isoformat(),
            "reasons": list(self.reasons),
            "manifest": {
                "version": self.manifest.version,
                "config_hash": self.manifest.config_hash,
                "risk_hash": self.manifest.risk_hash,
                "data_window": self.manifest.data_window,
            },
        }


def audit_from_decision(decision) -> PromotionAudit:
    return PromotionAudit(
        decision.strategy_version,
        decision.state,
        decision.approved,
        decision.decided_at,
        decision.reasons,
        decision.manifest,
    )
