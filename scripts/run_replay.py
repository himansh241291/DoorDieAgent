#!/usr/bin/env python3
from __future__ import annotations
import argparse
from decimal import Decimal
from nse_paper_agent.data.provider import load_bars_csv
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.risk.engine import RiskEngine
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy
from nse_paper_agent.domain.models import Quote,Regime,ExitReason
p=argparse.ArgumentParser(); p.add_argument("--bars",required=True); p.add_argument("--db",required=True); a=p.parse_args(); bars=load_bars_csv(a.bars); symbols=sorted({b.symbol for b in bars}); cfg={"account":{"starting_capital":50000.0,"minimum_cash_reserve":2000.0,"max_open_positions":5,"max_gross_position":10000.0,"buy_fee":20.0,"sell_fee":20.0,"risk_per_trade":0.003},"risk":{"hard_stop_pct":.015,"take_profit_pct":.05,"daily_loss_limit_pct":.02,"rolling_drawdown_pct":.04,"rolling_drawdown_days":5,"rolling_block_hours":48,"stop_cooldown_minutes":120,"slippage_bps":10,"max_spread_bps":50},"execution":{"last_price_slippage_bps":25},"safety":{"global_kill_switch":False,"emergency_kill_file":"/never"}}
db=Database(a.db); db.initialize(); repo=Repository(db); repo.set_cash(50000.0); broker=PaperBroker(cfg,repo); risk=RiskEngine(cfg,repo); strategy=BaselineBreakoutStrategy(); history={s:[] for s in symbols}
for b in sorted(bars,key=lambda x:x.end):
    history[b.symbol].append(b); now=b.end; q=Quote(b.symbol,now,b.close*Decimal(".999"),b.close*Decimal("1.001"),b.close,b.volume); p0=repo.positions().get(b.symbol)
    if p0:
        if q.bid<=p0.stop_price: broker.sell(b.symbol,q,now,p0.strategy_version,ExitReason.STOP); continue
        if q.bid>=p0.target_price: broker.sell(b.symbol,q,now,p0.strategy_version,ExitReason.TARGET); continue
    if len(history[b.symbol])<35: continue
    sig=strategy.evaluate(history[b.symbol],now,Regime.RISK_ON,.5,b.symbol in repo.positions(),False,True,True); repo.record_signal(sig,f"replay:{sig.symbol}:{sig.bar_end.isoformat()}")
    if sig.eligible and b.symbol not in repo.positions():
        qty=risk.quantity(q.ask,risk.equity({b.symbol:q}),q,1.0)
        if qty>0: broker.buy(b.symbol,qty,q,now,sig.strategy_version)
print({"symbols":len(symbols),"bars":len(bars),"cash":repo.cash(),"open_positions":list(repo.positions())}); db.close()
