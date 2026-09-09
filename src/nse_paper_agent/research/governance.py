from __future__ import annotations
from dataclasses import dataclass
import json
@dataclass(frozen=True)
class PromotionGate:
    min_closed_trades:int=50; min_oos_trades:int=20; require_shadow:bool=True; require_human_approval:bool=True; max_drawdown:float=.04; min_expectancy:float=0.0
def evaluate_candidate(in_sample,out_of_sample,shadow,gate,human_approved=False):
    reasons=[]
    if in_sample.get("trades",0)<gate.min_closed_trades: reasons.append("insufficient_total_trades")
    if out_of_sample.get("trades",0)<gate.min_oos_trades: reasons.append("insufficient_oos_trades")
    if out_of_sample.get("max_drawdown",1)>gate.max_drawdown: reasons.append("oos_drawdown_exceeded")
    if out_of_sample.get("net_expectancy",-1)<=gate.min_expectancy: reasons.append("oos_expectancy_not_positive")
    if gate.require_shadow and shadow.get("trades",0)<gate.min_oos_trades: reasons.append("insufficient_shadow_trades")
    if gate.require_human_approval and not human_approved: reasons.append("human_approval_required")
    return not reasons,reasons
def promotion_report(version,data_window,assumptions,in_sample,out_of_sample,shadow,regimes,failures,approved,reasons):
    return json.dumps({"strategy_version":version,"data_window":data_window,"assumptions":assumptions,"in_sample":in_sample,"out_of_sample":out_of_sample,"live_shadow":shadow,"regimes":regimes,"failure_cases":failures,"approved":approved,"reasons":reasons},indent=2,sort_keys=True)
