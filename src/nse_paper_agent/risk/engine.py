from __future__ import annotations
from datetime import timedelta
from decimal import Decimal,ROUND_DOWN
from nse_paper_agent.domain.models import Regime,RiskDecision
class RiskEngine:
    def __init__(self,cfg,repo): self.cfg=cfg; self.repo=repo
    def emergency_killed(self):
        import os
        return bool(self.cfg["safety"]["global_kill_switch"] or os.path.exists(self.cfg["safety"]["emergency_kill_file"]))
    def equity(self,quotes):
        gross=0.0
        for s,p in self.repo.positions().items():
            q=quotes.get(s); mark=float(q.bid if q and q.bid is not None else p.last_mark); gross+=float(p.qty)*mark
        return self.repo.cash()+gross
    def daily_loss_blocked(self,now,equity):
        start=self.repo.db.get_state("daily_start_equity",50000.0); return equity<=start*(1-self.cfg["risk"]["daily_loss_limit_pct"])
    def rolling_drawdown_blocked(self,now):
        block_until=self.repo.db.get_state("rolling_block_until")
        if block_until:
            block_until_ts=__import__('datetime').datetime.fromisoformat(block_until)
            if block_until_ts.tzinfo is None:
                block_until_ts=block_until_ts.replace(tzinfo=now.tzinfo)
            if block_until_ts>now:
                return True

        marks=self.repo.eod_marks(self.cfg["risk"]["rolling_drawdown_days"])
        vals=[float(mark["equity"]) for mark in reversed(marks)]

        if len(vals)<self.cfg["risk"]["rolling_drawdown_days"]:
            return False

        peak=vals[0]
        dd=0.0

        for value in vals:
            peak=max(peak,value)
            dd=max(dd,(peak-value)/peak if peak else 0.0)

        if dd>=self.cfg["risk"]["rolling_drawdown_pct"]:
            self.repo.db.set_state(
                "rolling_block_until",
                (now+timedelta(hours=self.cfg["risk"]["rolling_block_hours"])).isoformat(),
            )
            self.repo.record_risk(
                now,
                "ROLLING_DRAWDOWN_BLOCK",
                False,
                "rolling_drawdown_circuit_breaker",
                {
                    "drawdown": dd,
                    "threshold": self.cfg["risk"]["rolling_drawdown_pct"],
                    "completed_eod_marks": len(vals),
                    "block_hours": self.cfg["risk"]["rolling_block_hours"],
                },
            )
            return True

        return False
    def can_buy(self,now,quotes,equity,regime):
        if self.emergency_killed(): return RiskDecision(False,"kill_switch")
        if len(self.repo.positions())>=self.cfg["account"]["max_open_positions"]: return RiskDecision(False,"max_open_positions")
        if self.daily_loss_blocked(now,equity): return RiskDecision(False,"daily_loss_circuit_breaker")
        if self.rolling_drawdown_blocked(now): return RiskDecision(False,"rolling_drawdown_circuit_breaker")
        if regime in {Regime.RISK_OFF,Regime.DATA_DEGRADED,Regime.RANGE_BOUND}: return RiskDecision(False,f"regime_{regime.value}")
        return RiskDecision(True,"risk_checks_passed",0.5 if regime==Regime.CAUTIOUS else 1.0)
    def quantity(self,price,equity,quote,size_factor=1.0):
        a=self.cfg["account"]; risk=self.cfg["risk"]; stop=price*Decimal(str(risk["hard_stop_pct"])); budget=Decimal(str(equity*a["risk_per_trade"]))*Decimal(str(size_factor)); per_share=stop+Decimal(str(a["buy_fee"]))/max(1,int(Decimal(str(a["max_gross_position"]))/price)); q_risk=int((budget/per_share).to_integral_value(rounding=ROUND_DOWN)) if per_share>0 else 0; cash=Decimal(str(self.repo.cash())); max_cash=cash-Decimal(str(a["minimum_cash_reserve"]))-Decimal(str(a["buy_fee"])); q_cash=int((max_cash/price).to_integral_value(rounding=ROUND_DOWN)) if max_cash>0 else 0; q_cap=int((Decimal(str(a["max_gross_position"]))*Decimal(str(size_factor))/price).to_integral_value(rounding=ROUND_DOWN)); return max(0,min(q_risk,q_cash,q_cap))
