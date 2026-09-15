from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping

from nse_paper_agent.strategy.evidence import StrategyEvidence


@dataclass(frozen=True)
class StrategyDiagnosisPolicy:
    min_overall_samples: int = 20
    min_bucket_samples: int = 10
    recent_degradation_factor: float = 0.50
    forced_exit_share: float = 0.60
    max_findings: int = 5


@dataclass(frozen=True)
class DiagnosisFinding:
    code: str
    severity: str
    statement: str
    hypothesis: str
    samples: int
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyDiagnosis:
    version: str
    eligible: bool
    findings: tuple[DiagnosisFinding, ...] = ()
    reason: str = "no_diagnosable_pattern"


class StrategyDiagnosisEngine:
    """Turn measured evidence into bounded, explainable improvement hypotheses.

    The engine never edits strategy code, risk configuration, or production
    identity. It emits observations that downstream validation may evaluate.
    """

    def __init__(self, policy: StrategyDiagnosisPolicy | None = None):
        self.policy = policy or StrategyDiagnosisPolicy()
        if self.policy.min_overall_samples <= 0:
            raise ValueError("min_overall_samples must be positive")
        if self.policy.min_bucket_samples <= 0:
            raise ValueError("min_bucket_samples must be positive")
        if not 0 < self.policy.recent_degradation_factor <= 1:
            raise ValueError("recent_degradation_factor must be in (0, 1]")
        if not 0 < self.policy.forced_exit_share <= 1:
            raise ValueError("forced_exit_share must be in (0, 1]")
        if self.policy.max_findings <= 0:
            raise ValueError("max_findings must be positive")

    @staticmethod
    def _finite(value: float | None) -> bool:
        return value is not None and isfinite(float(value))

    def diagnose(self, evidence: StrategyEvidence) -> StrategyDiagnosis:
        overall = evidence.overall
        if overall.samples < self.policy.min_overall_samples:
            return StrategyDiagnosis(
                version=evidence.version,
                eligible=False,
                reason="insufficient_overall_evidence",
            )

        findings: list[DiagnosisFinding] = []

        if (
            self._finite(overall.expectancy)
            and self._finite(evidence.recent.expectancy)
            and overall.expectancy is not None
            and evidence.recent.expectancy is not None
            and overall.expectancy > 0
            and evidence.recent.expectancy < overall.expectancy * self.policy.recent_degradation_factor
        ):
            findings.append(
                DiagnosisFinding(
                    code="RECENT_DEGRADATION",
                    severity="HIGH",
                    statement="Recent expectancy has materially degraded versus the strategy's overall expectancy.",
                    hypothesis="Test a bounded entry-condition or regime-filter improvement against the recent failure pattern.",
                    samples=evidence.recent.samples,
                    metrics={
                        "overall_expectancy": float(overall.expectancy),
                        "recent_expectancy": float(evidence.recent.expectancy),
                    },
                )
            )

        forced = evidence.by_exit_reason.get("FORCED")
        if forced is not None and overall.samples > 0:
            forced_share = forced.samples / overall.samples
            if forced.samples >= self.policy.min_bucket_samples and forced_share >= self.policy.forced_exit_share:
                forced_exp = forced.expectancy
                findings.append(
                    DiagnosisFinding(
                        code="FORCED_EXIT_DOMINANT",
                        severity="MEDIUM",
                        statement="Forced exits represent a dominant share of completed trades.",
                        hypothesis="Evaluate entry timing or signal-quality improvements before changing the mandatory exit/risk rules.",
                        samples=forced.samples,
                        metrics={
                            "forced_exit_share": float(forced_share),
                            "forced_expectancy": float(forced_exp) if self._finite(forced_exp) else 0.0,
                        },
                    )
                )

        for regime, bucket in sorted(evidence.by_regime.items()):
            if len(findings) >= self.policy.max_findings:
                break
            if bucket.samples < self.policy.min_bucket_samples or bucket.expectancy is None:
                continue
            if bucket.expectancy < 0:
                findings.append(
                    DiagnosisFinding(
                        code="REGIME_WEAKNESS",
                        severity="MEDIUM",
                        statement=f"Observed expectancy is negative in regime {regime}.",
                        hypothesis=f"Test a regime-specific eligibility rule that reduces exposure in {regime}.",
                        samples=bucket.samples,
                        metrics={
                            "regime_expectancy": float(bucket.expectancy),
                        },
                    )
                )

        for bucket_name, bucket in sorted(evidence.by_time_bucket.items()):
            if len(findings) >= self.policy.max_findings:
                break
            if bucket.samples < self.policy.min_bucket_samples or bucket.expectancy is None:
                continue
            if bucket.expectancy < 0:
                findings.append(
                    DiagnosisFinding(
                        code="TIME_BUCKET_WEAKNESS",
                        severity="LOW",
                        statement=f"Observed expectancy is negative in the {bucket_name.lower()} entry window.",
                        hypothesis=f"Test a time-of-day eligibility restriction for the {bucket_name.lower()} window.",
                        samples=bucket.samples,
                        metrics={
                            "time_bucket_expectancy": float(bucket.expectancy),
                        },
                    )
                )

        for symbol, bucket in sorted(evidence.by_symbol.items()):
            if len(findings) >= self.policy.max_findings:
                break
            if bucket.samples < self.policy.min_bucket_samples or bucket.expectancy is None:
                continue
            if bucket.expectancy < 0:
                findings.append(
                    DiagnosisFinding(
                        code="SYMBOL_WEAKNESS",
                        severity="LOW",
                        statement=f"Observed expectancy is negative for {symbol}.",
                        hypothesis=f"Test whether excluding {symbol} improves out-of-sample stability without broadening exposure elsewhere.",
                        samples=bucket.samples,
                        metrics={
                            "symbol_expectancy": float(bucket.expectancy),
                        },
                    )
                )

        if not findings:
            return StrategyDiagnosis(
                version=evidence.version,
                eligible=True,
                reason="no_diagnosable_pattern",
            )

        return StrategyDiagnosis(
            version=evidence.version,
            eligible=True,
            findings=tuple(findings[: self.policy.max_findings]),
            reason="patterns_detected",
        )
