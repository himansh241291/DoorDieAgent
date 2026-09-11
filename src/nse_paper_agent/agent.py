from __future__ import annotations
import logging
from datetime import timedelta
from nse_paper_agent.domain.models import ExitReason
from nse_paper_agent.monitoring.logging import event

class TradingAgent:
    def __init__(self,cfg,provider,repo,broker,risk,health,strategy,regime_engine,sentiment,session,notifier,clock):
        self.cfg=cfg; self.provider=provider; self.repo=repo; self.broker=broker; self.risk=risk; self.health=health; self.strategy=strategy; self.regime_engine=regime_engine; self.sentiment=sentiment; self.session=session; self.notifier=notifier; self.clock=clock; self.log=logging.getLogger("agent")
    def startup(self):
        self.provider.connect()
        now = self.clock()
        daily_start = self.session.ensure_daily_state(
            self.repo,
            now,
            self.cfg["account"]["starting_capital"],
        )
        event(
            self.log,
            logging.INFO,
            "startup",
            mode="paper",
            positions=list(self.repo.positions()),
            session_state=self.session.state(now).value,
            trading_date=self.session.current_trading_date(now).isoformat()
            if self.session.current_trading_date(now)
            else None,
            daily_start_equity=daily_start,
        )
    def shutdown(self):
        self.provider.disconnect(); event(self.log,logging.INFO,"shutdown")
    def _notify(self,kind,**data):
        try: self.notifier.send({"event_type":kind,**data})
        except Exception as exc: event(self.log,logging.ERROR,"notification_failed",error=str(exc))
    def cycle(self, symbols:list[str]):
        now = self.clock()

        if now.tzinfo is None:
            raise ValueError("agent clock must return timezone-aware datetime")

        ist = now.astimezone(self.session.timezone)
        session = self.session.snapshot(now)

        self.session.ensure_daily_state(
            self.repo,
            now,
            self.cfg["account"]["starting_capital"],
        )

        event(
            self.log,
            logging.INFO,
            "session_state",
            ts_ist=ist.isoformat(),
            trading_date=(
                session.trading_date.isoformat()
                if session.is_trading_day
                else None
            ),
            state=session.state.value,
            entries_allowed=session.entries_allowed,
            exits_allowed=session.exits_allowed,
        )

        # No trading activity on weekends/holidays or outside the
        # continuous equity market session.
        if not session.exits_allowed:
            event(
                self.log,
                logging.INFO,
                "market_session_closed",
                ts_ist=ist.isoformat(),
                state=session.state.value,
            )
            return

        healthy,reason=self.provider.healthy(now)
        self.repo.record_data_health(now,healthy,reason,{})
        quotes=self.provider.latest_quotes(symbols)
        for symbol,p in list(self.repo.positions().items()):
            q=quotes.get(symbol)
            if not q: continue
            ok,_=self.health.check_quote(q,now)
            if not ok: continue
            bid=q.bid or q.last
            if bid is None: continue
            if bid<=p.stop_price:
                f=self.broker.sell(symbol,q,now,p.strategy_version,ExitReason.STOP); self.repo.cooldown(symbol,now+timedelta(minutes=self.cfg["risk"]["stop_cooldown_minutes"]),"stop_loss"); self._notify("paper_exit",symbol=symbol,reason="STOP",price=str(f.price),qty=f.qty,net_pnl=None); continue
            if bid>=p.target_price:
                f=self.broker.sell(symbol,q,now,p.strategy_version,ExitReason.TARGET); self._notify("paper_exit",symbol=symbol,reason="TARGET",price=str(f.price),qty=f.qty,net_pnl=None)
        quotes=self.provider.latest_quotes(symbols); equity=self.risk.equity(quotes); self.repo.db.set_state("last_equity",equity)
        if not healthy or not session.entries_allowed:
            return
        regime=self.regime_engine.classify(now,100.0,99.0,98.0,0.60,0.50,False,healthy); self.repo.record_regime(regime)
        rd=self.risk.can_buy(now,quotes,equity,regime.regime); self.repo.record_risk(now,"ENTRY_GATE",rd.allowed,rd.reason,{"size_factor":rd.size_factor})
        if not rd.allowed: return
        for symbol in symbols:
            q=quotes.get(symbol)
            if not q: continue
            qok,_=self.health.check_quote(q,now)
            if not qok: continue
            bars=self.provider.completed_bars(symbol,self.cfg["market"]["bar_interval_minutes"],now)
            for b in bars[-1:]: self.repo.record_bar(b)
            s_obs=self.sentiment.symbol(symbol,now); self.repo.record_sentiment(s_obs)
            signal=self.strategy.evaluate(bars,ist,regime.regime,s_obs.score,symbol in self.repo.positions(),self.repo.in_cooldown(symbol,now),True,qok)
            self.repo.record_signal(signal,f"{signal.strategy_version}:{symbol}:{signal.bar_end.isoformat()}")
            if not signal.eligible: continue
            price=q.ask or q.last
            if price is None: continue
            qty=self.risk.quantity(price,equity,q,rd.size_factor)
            if qty<=0: continue
            try:
                f=self.broker.buy(symbol,qty,q,now,signal.strategy_version)
                self._notify("paper_entry",symbol=symbol,price=str(f.price),qty=qty,stop=str(self.repo.positions()[symbol].stop_price),target=str(self.repo.positions()[symbol].target_price))
            except Exception as exc: self.repo.record_risk(now,"ENTRY_ERROR",False,str(exc),{"symbol":symbol})
