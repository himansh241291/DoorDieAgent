from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any


@dataclass(frozen=True)
class PromotionGate:
    min_closed_trades: int = 50
    min_oos_trades: int = 20
    require_shadow: bool = True
    require_human_approval: bool = True
    max_drawdown: float = 0.04
    min_expectancy: float = 0.0


@dataclass(frozen=True)
class StrategyManifest:
    version: str
    config_hash: str
    risk_hash: str
    data_window: str
    assumptions: dict[str, Any]


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(payload).hexdigest()


def build_manifest(version: str, strategy_config: dict[str, Any], risk_config: dict[str, Any], data_window: str, assumptions: dict[str, Any] | None = None) -> StrategyManifest:
    if not version.strip():
        raise ValueError("strategy version is required")
    if not data_window.strip():
        raise ValueError("data window is required")
    return StrategyManifest(version, _canonical_hash(strategy_config), _canonical_hash(risk_config), data_window, dict(assumptions or {}))


def evaluate_candidate(in_sample, out_of_sample, shadow, gate, human_approved=False):
    reasons = []
    if in_sample.get("trades", 0) < gate.min_closed_trades:
        reasons.append("insufficient_total_trades")
    if out_of_sample.get("trades", 0) < gate.min_oos_trades:
        reasons.append("insufficient_oos_trades")
    drawdown = out_of_sample.get("max_drawdown", 1)
    expectancy = out_of_sample.get("net_expectancy", -1)
    if not math.isfinite(float(drawdown)) or drawdown > gate.max_drawdown:
        reasons.append("oos_drawdown_exceeded")
    if not math.isfinite(float(expectancy)) or expectancy <= gate.min_expectancy:
        reasons.append("oos_expectancy_not_positive")
    if gate.require_shadow and shadow.get("trades", 0) < gate.min_oos_trades:
        reasons.append("insufficient_shadow_trades")
    if gate.require_human_approval and not human_approved:
        reasons.append("human_approval_required")
    return not reasons, reasons


def promotion_report(version, data_window, assumptions, in_sample, out_of_sample, shadow, regimes, failures, approved, reasons, manifest: StrategyManifest | None = None):
    report = {
        "strategy_version": version,
        "data_window": data_window,
        "assumptions": assumptions,
        "in_sample": in_sample,
        "out_of_sample": out_of_sample,
        "live_shadow": shadow,
        "regimes": regimes,
        "failure_cases": failures,
        "approved": bool(approved),
        "reasons": list(reasons),
    }
    if manifest is not None:
        report["manifest"] = {
            "version": manifest.version,
            "config_hash": manifest.config_hash,
            "risk_hash": manifest.risk_hash,
            "data_window": manifest.data_window,
            "assumptions": manifest.assumptions,
        }
    return json.dumps(report, indent=2, sort_keys=True)
