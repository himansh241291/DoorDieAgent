from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .governance import StrategyManifest, evaluate_candidate
from .lifecycle import StrategyState, transition


@dataclass(frozen=True)
class PromotionDecision:
    strategy_version: str
    state: StrategyState
    approved: bool
    decided_at: datetime
    reasons: tuple[str, ...]
    manifest: StrategyManifest


def evaluate_promotion(manifest: StrategyManifest, in_sample: dict[str, Any], out_of_sample: dict[str, Any], shadow: dict[str, Any], gate, human_approved: bool = False) -> PromotionDecision:
    ok, reasons = evaluate_candidate(in_sample, out_of_sample, shadow, gate, human_approved)
    state = StrategyState.CANDIDATE
    if not ok:
        return PromotionDecision(manifest.version, state, False, datetime.now(timezone.utc), tuple(reasons), manifest)
    for target in (StrategyState.VALIDATED, StrategyState.SHADOW, StrategyState.APPROVED, StrategyState.PRODUCTION):
        state = transition(state, target)
    return PromotionDecision(manifest.version, state, True, datetime.now(timezone.utc), (), manifest)
