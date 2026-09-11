from __future__ import annotations

import logging
from datetime import timedelta

from nse_paper_agent.domain.models import ExitReason
from nse_paper_agent.monitoring.logging import event
from nse_paper_agent.regime.intelligence import MarketIntelligence


class TradingAgent:
    def __init__(self,cfg,provider,repo,broker,risk,health,strategy,regime_engine,sentiment,session,notifier,clock):
        self.cfg=cfg; self.provider=provider; self.repo=repo; self.broker=broker; self.risk=risk; self.health=health; self.strategy=strategy; self.regime_engine=regime_engine; self.sentiment=sentiment; self.session=session; self.notifier=notifier; self.clock=clock; self.log=logging.getLogger("agent")
        market_cfg=cfg.get("market",{})
        self.intelligence=MarketIntelligence(
            benchmark_min_bars=int(market_cfg.get("regime",{}).get("benchmark_min_bars",50)),
            volatility_window=int(market_cfg.get("regime",{}).get("volatility_window",20)),
            volatility_history=int(market_cfg.get("regime",{}).get("volatility_history",60)),
            breadth_window=int(market_cfg.get("regime",{}).get("breadth_window",20)),
            breadth_min_symbols=int(market_cfg.get("minimum_breadth_symbols",5)),
        )
    def startup(self):
        self.provider.connect(); now=self.clock(); daily_start=self.session.ensure_daily_state(self.repo,now,self.cfg["account"]["starting_capital"])
        event(self.log,logging.INFO,"startup",mode="paper",positions=list(self.repo.positions()),session_state=self.session.state(now).value,trading_date=self.session.current_trading_date(now).isoformat() if self.session.current_trading_date(now) else None,daily_start_equity=daily_start)
    def shutdown(self): self.provider.disconnect(); event(self.log,logging.INFO,"shutdown")
    def _notify(self,kind,**data):
        try: self.notifier.send({"event_type":kind,**data})
        except Exception as exc: event(self.log,logging.ERROR,"notification_failed",error=str(exc))

    def _market_intelligence(self,symbols,now):
        interval=int(self.cfg["market"]["bar_interval_minutes"]); benchmark_symbol=self.cfg["market"]["benchmark"]
        benchmark_bars=self.provider.completed_bars(benchmark_symbol,interval,now); bars_by_symbol={symbol:self.provider.completed_bars(symbol,interval,now) for symbol in symbols}
        metrics=self.intelligence.calculate(benchmark_bars,bars_by_symbol)
        required=(metrics.get("close"),metrics.get("sma20"),metrics.get("sma50"),metrics.get("breadth20"),metrics.get("vol_percentile"),metrics.get("vol_shock"))
        regime=self.regime_engine.classify(now,*required,self.provider.healthy(now)[0])
        return regime,metrics,benchmark_bars,bars_by_symbol

    def cycle(self, symbols:list[str]):
        now=self.clock()
        if now.tzinfo is None: raise ValueError("agent clock must return timezone-aware datetime")
        ist=now.astimezone(self.session.timezone); session=self.session.snapshot(now); self.session.ensure_daily_state(self.repo,now,self.cfg["account"]["starting_capital"])
        event(self.log,logging.INFO,"session_state",ts_ist=ist.isoformat(),trading_date=session.trading_date.isoformat() if session.is_trading_day else None,state=session.state.value,entries_allowed=session.entries_allowed,exits_allowed=session.exits_allowed)
        if not session.exits_allowed: event(self.log,logging.INFO,"market_session_closed",ts_ist=ist.isoformat(),state=session.state.value); return
        healthy,reason=self.provider.healthy(now); self.repo.record_data_health(now,healthy,reason,{})
        quotes=self.provider.latest_quotes(symbols)

        for symbol,p in list(self.repo.positions().items()):
            q=quotes.get(symbol)
            if not q: continue
            exit_ok,exit_reason=self.health.check_exit_price(q)
            if not exit_ok: self.repo.record_risk(now,"EXIT_PRICE_UNAVAILABLE",False,exit_reason,{"symbol":symbol}); continue
            bid=q.bid if q.bid is not None else q.last
            if bid<=p.stop_price:
                f=self.broker.sell(symbol,q,now,p.strategy_version,ExitReason.STOP); self.repo.cooldown(symbol,now+timedelta(minutes=self.cfg["risk"]["stop_cooldown_minutes"]),"stop_loss"); self._notify("paper_exit",symbol=symbol,reason="STOP",price=str(f.price),qty=f.qty,net_pnl=None); continue
            if bid>=p.target_price:
                f=self.broker.sell(symbol,q,now,p.strategy_version,ExitReason.TARGET); self._notify("paper_exit",symbol=symbol,reason="TARGET",price=str(f.price),qty=f.qty,net_pnl=None); continue
            if session.state.value=="EOD":
                f=self.broker.sell(symbol,q,now,p.strategy_version,ExitReason.FORCED); self._notify("paper_exit",symbol=symbol,reason="EOD_FORCED",price=str(f.price),qty=f.qty,net_pnl=None)

        quotes=self.provider.latest_quotes(symbols); equity=self.risk.equity(quotes); self.repo.db.set_state("last_equity",equity)
        if session.state.value=="EOD" and session.is_trading_day:
            eod_date=session.trading_date.isoformat(); last_eod=self.repo.db.get_state("last_eod_trading_date")
            if last_eod!=eod_date:
                daily_start=self.repo.db.get_state("daily_start_equity",self.cfg["account"]["starting_capital"]); gross=equity-self.repo.cash(); previous_marks=self.repo.eod_marks(self.cfg["risk"]["rolling_drawdown_days"]-1); values=[float(mark["equity"]) for mark in reversed(previous_marks)]; peak=max(values+[equity]) if values else equity; drawdown=(peak-equity)/peak if peak>0 else 0.0
                self.repo.record_eod_snapshot(eod_date,now,self.repo.cash(),equity,gross,daily_start,drawdown); event(self.log,logging.INFO,"eod_equity_mark",trading_date=eod_date,equity=equity,cash=self.repo.cash(),gross=gross,daily_start_equity=daily_start,drawdown5=drawdown)

        market_sentiment=self.sentiment.market(now); self.repo.record_sentiment(market_sentiment); symbol_sentiments={}
        for symbol in symbols:
            observation=self.sentiment.symbol(symbol,now); symbol_sentiments[symbol]=observation; self.repo.record_sentiment(observation)

        if not healthy:
            regime=self.regime_engine.classify(now,None,None,None,None,None,None,False); metrics={}; market_bars={}
        else:
            try:
                regime,metrics,_,market_bars=self._market_intelligence(symbols,now)
            except Exception as exc:
                event(self.log,logging.ERROR,"market_intelligence_failure",error=str(exc)); regime=self.regime_engine.classify(now,None,None,None,None,None,None,False); metrics={}; market_bars={}
        self.repo.record_regime(regime); event(self.log,logging.INFO,"market_regime",regime=regime.regime.value,reason=regime.reason,metrics=metrics)
        if not healthy or not session.entries_allowed: return
        rd=self.risk.can_buy(now,quotes,equity,regime.regime); self.repo.record_risk(now,"ENTRY_GATE",rd.allowed,rd.reason,{"size_factor":rd.size_factor,"regime":regime.regime.value})
        if not rd.allowed: return
        for symbol in symbols:
            q=quotes.get(symbol)
            if not q: continue
            qok,_=self.health.check_quote(q,now)
            if not qok: continue
            bars=market_bars.get(symbol) or self.provider.completed_bars(symbol,self.cfg["market"]["bar_interval_minutes"],now)
            for b in bars[-1:]: self.repo.record_bar(b)
            signal=self.strategy.evaluate(bars,ist,regime.regime,symbol_sentiments[symbol].score,symbol in self.repo.positions(),self.repo.in_cooldown(symbol,now),True,qok); self.repo.record_signal(signal,f"{signal.strategy_version}:{symbol}:{signal.bar_end.isoformat()}")
            if not signal.eligible: continue
            price=q.ask or q.last
            if price is None: continue
            qty=self.risk.quantity(price,equity,q,rd.size_factor)
            if qty<=0: continue
            try:
                f=self.broker.buy(symbol,qty,q,now,signal.strategy_version); p=self.repo.positions()[symbol]; self._notify("paper_entry",symbol=symbol,price=str(f.price),qty=qty,stop=str(p.stop_price),target=str(p.target_price))
            except Exception as exc: self.repo.record_risk(now,"ENTRY_ERROR",False,str(exc),{"symbol":symbol})