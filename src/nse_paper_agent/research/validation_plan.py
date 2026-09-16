from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Mapping

from nse_paper_agent.research.validation_request import StrategyValidationRequest


@dataclass(frozen=True)
class ValidationPlan:
    proposal_id: str
    base_version: str
    challenger_version: str
    hypothesis: str
    allowed_change_scope: str
    forbidden_change_scope: tuple[str, ...]
    risk_config_hash: str
    data_window: str
    target: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)
    split_policy: str = "chronological"
    min_trading_days: int = 60
    validation_status: str = "PLANNED"


class ValidationPlanner:
    """Build a deterministic, safety-bounded validation plan.

    This layer does not execute candidate code. It freezes the safety envelope
    and evaluation contract that a later replay runner must honor.
    """

    REQUIRED_SAFETY_SCOPES = frozenset(
        {
            "risk_limits",
            "hard_stop",
            "position_limits",
            "kill_switch",
            "capital_rules",
            "execution_safety",
            "production_identity",
        }
    )

    def __init__(self, min_trading_days: int = 60):
        if min_trading_days <= 0:
            raise ValueError("min_trading_days must be positive")
        self.min_trading_days = min_trading_days

    @staticmethod
    def _hash_risk_config(risk_config: Mapping[str, object]) -> str:
        payload = json.dumps(dict(risk_config), sort_keys=True, separators=(",", ":"), default=str).encode()
        return sha256(payload).hexdigest()

    def plan(
        self,
        request: StrategyValidationRequest,
        risk_config: Mapping[str, object],
        data_window: str,
    ) -> ValidationPlan:
        if request.validation_status != "PENDING":
            raise ValueError(f"validation request is not pending: {request.validation_status}")
        if request.base_version == request.proposed_version:
            raise ValueError("challenger version must differ from base version")
        if not data_window.strip():
            raise ValueError("data window is required")

        forbidden = set(request.forbidden_change_scope)
        if not self.REQUIRED_SAFETY_SCOPES.issubset(forbidden):
            raise ValueError("validation request does not freeze the complete safety envelope")
        if request.allowed_change_scope in forbidden:
            raise ValueError("allowed change scope overlaps forbidden scope")

        return ValidationPlan(
            proposal_id=request.proposal_id,
            base_version=request.base_version,
            challenger_version=request.proposed_version,
            hypothesis=request.hypothesis,
            allowed_change_scope=request.allowed_change_scope,
            forbidden_change_scope=request.forbidden_change_scope,
            risk_config_hash=self._hash_risk_config(risk_config),
            data_window=data_window,
            target=request.target,
            parameters=dict(request.parameters),
            min_trading_days=self.min_trading_days,
        )
