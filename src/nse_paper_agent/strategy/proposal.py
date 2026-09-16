from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from nse_paper_agent.strategy.diagnosis import DiagnosisFinding, StrategyDiagnosis


@dataclass(frozen=True)
class StrategyProposal:
    proposal_id: str
    base_version: str
    proposed_version: str
    finding_code: str
    severity: str
    hypothesis: str
    rationale: str
    evidence: Mapping[str, float]
    allowed_change_scope: str
    forbidden_change_scope: tuple[str, ...]
    target: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)
    status: str = "PROPOSED"


class StrategyProposalEngine:
    """Convert bounded diagnoses into immutable, non-executable proposals.

    A proposal describes what should be tested. It contains no executable code
    and cannot alter risk controls, production identity, or live configuration.
    """

    FORBIDDEN_SCOPES = (
        "risk_limits",
        "hard_stop",
        "position_limits",
        "kill_switch",
        "capital_rules",
        "execution_safety",
        "production_identity",
    )

    _SCOPES = {
        "RECENT_DEGRADATION": "entry_condition_or_regime_filter",
        "FORCED_EXIT_DOMINANT": "entry_timing_or_signal_quality",
        "REGIME_WEAKNESS": "regime_eligibility",
        "TIME_BUCKET_WEAKNESS": "time_of_day_eligibility",
        "SYMBOL_WEAKNESS": "symbol_eligibility",
    }

    def __init__(self, max_proposals: int = 3):
        if max_proposals <= 0:
            raise ValueError("max_proposals must be positive")
        self.max_proposals = max_proposals

    @staticmethod
    def _proposal_id(base_version: str, finding: DiagnosisFinding, index: int) -> str:
        target = finding.target or "global"
        return f"{base_version}:{finding.code}:{target}:{index + 1}"

    @staticmethod
    def _proposed_version(base_version: str, finding: DiagnosisFinding, index: int) -> str:
        target = (finding.target or "global").lower().replace(" ", "-")
        suffix = index + 2
        return f"{base_version}-challenger-{suffix}-{target}"

    @staticmethod
    def _parameters(finding: DiagnosisFinding) -> dict[str, object]:
        parameters: dict[str, object] = {}
        if finding.target is not None:
            parameters["target"] = finding.target
        return parameters

    def _from_finding(self, diagnosis: StrategyDiagnosis, finding: DiagnosisFinding, index: int) -> StrategyProposal:
        scope = self._SCOPES.get(finding.code, "bounded_strategy_logic")
        return StrategyProposal(
            proposal_id=self._proposal_id(diagnosis.version, finding, index),
            base_version=diagnosis.version,
            proposed_version=self._proposed_version(diagnosis.version, finding, index),
            finding_code=finding.code,
            severity=finding.severity,
            hypothesis=finding.hypothesis,
            rationale=finding.statement,
            evidence=dict(finding.metrics),
            allowed_change_scope=scope,
            forbidden_change_scope=self.FORBIDDEN_SCOPES,
            target=finding.target,
            parameters=self._parameters(finding),
        )

    def propose(self, diagnosis: StrategyDiagnosis) -> tuple[StrategyProposal, ...]:
        if not diagnosis.eligible or not diagnosis.findings:
            return ()
        return tuple(
            self._from_finding(diagnosis, finding, index)
            for index, finding in enumerate(diagnosis.findings[: self.max_proposals])
        )
