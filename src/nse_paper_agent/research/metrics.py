from __future__ import annotations
import math,statistics
def _streak(xs):
    cur=best=0
    for x in xs:
        if x<0: cur+=1; best=max(best,cur)
        else: cur=0
    return best
def compute_metrics(rows):
    pnls=[float(r["net_pnl"]) for r in rows]; wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]; gross_profit=sum(wins); gross_loss=abs(sum(losses)); equity=50000.0; peak=equity; max_dd=0.0
    for p in pnls: equity+=p; peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak if peak else 0)
    return {"trades":len(pnls),"win_rate":len(wins)/len(pnls) if pnls else 0,"avg_win":statistics.mean(wins) if wins else 0,"avg_loss":statistics.mean(losses) if losses else 0,"net_expectancy":statistics.mean(pnls) if pnls else 0,"profit_factor":gross_profit/gross_loss if gross_loss else math.inf,"max_drawdown":max_dd,"max_losing_streak":_streak(pnls),"net_pnl":sum(pnls)}
