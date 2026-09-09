from __future__ import annotations
from abc import ABC,abstractmethod
from datetime import datetime,timezone
from decimal import Decimal
from nse_paper_agent.domain.models import Fill,Position,Quote,Side,ExitReason
class BrokerExecution(ABC):
    @abstractmethod
    def buy(self,*args,**kwargs)->Fill: ...
    @abstractmethod
    def sell(self,*args,**kwargs)->Fill: ...
class PaperBroker(BrokerExecution):
    def __init__(self,cfg,repo): self.cfg=cfg; self.repo=repo
    def _price(self,q:Quote,side:Side):
        bps=Decimal(str(self.cfg["risk"]["slippage_bps"]))/Decimal(10000)
        if side==Side.BUY:
            base=q.ask
            if base is None and q.last is not None: base=q.last; bps=Decimal(str(self.cfg["execution"]["last_price_slippage_bps"]))/Decimal(10000)
            if base is None: raise ValueError("no executable buy price")
            return base*(1+bps),base*bps
        base=q.bid
        if base is None and q.last is not None: base=q.last; bps=Decimal(str(self.cfg["execution"]["last_price_slippage_bps"]))/Decimal(10000)
        if base is None: raise ValueError("no executable sell price")
        return base*(1-bps),base*bps
    def buy(self,symbol,qty,q,now,strategy_version):
        if qty<=0: raise ValueError("qty must be positive")
        key=f"BUY:{symbol}:{now.isoformat()}:{qty}:{strategy_version}"
        if self.repo.fill_exists(key): raise ValueError("duplicate buy idempotency key")
        price,slip=self._price(q,Side.BUY); fee=Decimal(str(self.cfg["account"]["buy_fee"])); cash=Decimal(str(self.repo.cash())); total=price*qty+fee
        if total>cash-Decimal(str(self.cfg["account"]["minimum_cash_reserve"])): raise ValueError("cash reserve breach prevented")
        stop=price*(1-Decimal(str(self.cfg["risk"]["hard_stop_pct"]))); target=price*(1+Decimal(str(self.cfg["risk"]["take_profit_pct"])))
        p=Position(symbol,qty,price,stop,target,fee,strategy_version,now,price); f=Fill(key,symbol,Side.BUY,qty,price,fee,now,strategy_version,slip,"ENTRY")
        with self.repo.db.transaction(): self.repo.set_cash(float(cash-total)); self.repo.insert_fill(f); self.repo.save_position(p)
        return f
    def sell(self,symbol,q,now,strategy_version,reason):
        p=self.repo.positions().get(symbol)
        if not p: raise ValueError("position not found")
        key=f"SELL:{symbol}:{now.isoformat()}:{p.qty}:{reason.value}"
        if self.repo.fill_exists(key): raise ValueError("duplicate sell idempotency key")
        price,slip=self._price(q,Side.SELL); fee=Decimal(str(self.cfg["account"]["sell_fee"])); cash=Decimal(str(self.repo.cash()))+price*p.qty-fee; gross=(price-p.entry_price)*p.qty; net=gross-p.entry_fee-fee
        f=Fill(key,symbol,Side.SELL,p.qty,price,fee,now,strategy_version,slip,reason.value)
        with self.repo.db.transaction():
            self.repo.set_cash(float(cash)); self.repo.insert_fill(f); self.repo.delete_position(symbol)
            self.repo.close_trade(values=(symbol,p.qty,float(p.entry_price),float(price),float(p.entry_fee),float(fee),float(gross),float(net),p.entry_ts.astimezone(timezone.utc).isoformat(),now.astimezone(timezone.utc).isoformat(),strategy_version,reason.value,int((now-p.entry_ts).total_seconds()),None,None))
        return f
