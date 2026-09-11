from __future__ import annotations

from enum import Enum


class StrategyState(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    APPROVED = "APPROVED"
    PRODUCTION = "PRODUCTION"


_ALLOWED = {
    StrategyState.CANDIDATE: {StrategyState.VALIDATED},
    StrategyState.VALIDATED: {StrategyState.SHADOW},
    StrategyState.SHADOW: {StrategyState.APPROVED},
    StrategyState.APPROVED: {StrategyState.PRODUCTION},
    StrategyState.PRODUCTION: set(),
}


def transition(current: StrategyState, target: StrategyState) -> StrategyState:
    if target not in _ALLOWED[current]:
        raise ValueError(f"invalid strategy transition: {current.value} -> {target.value}")
    return target
