from datetime import datetime,timezone
from decimal import Decimal
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.risk.engine import RiskEngine
from nse_paper_agent.domain.models import Quote,ExitReason

def cfg():
 return {"account":{"starting_capital":50000.0,"minimum_cash_reserve":2000.0,"max_open_positions":5,"max_gross_position":10000.0,"buy_fee":20.0,"sell_fee":20.0,"risk_per_trade":.003},"risk":{"hard_stop_pct":.015,"take_profit_pct":.05,"daily_loss_limit_pct":.02,"rolling_drawdown_pct":.04,"rolling_drawdown_days":5,"rolling_block_hours":48,"stop_cooldown_minutes":120,"slippage_bps":10,"max_spread_bps":50},"execution":{"last_price_slippage_bps":25},"safety":{"global_kill_switch":False,"emergency_kill_file":"/tmp/no-kill"}}
def setup(tmp_path):
 db=Database(str(tmp_path/'x.sqlite')); db.initialize(); r=Repository(db); r.set_cash(50000); db.set_state('daily_start_equity',50000); return db,r,PaperBroker(cfg(),r),RiskEngine(cfg(),r)
def q(sym='ABC',p='100'):
 t=datetime.now(timezone.utc); d=Decimal(p); return Quote(sym,t,d-Decimal('.10'),d+Decimal('.10'),d,Decimal('100000'))
def test_entry_fee_and_reserve(tmp_path):
 db,r,b,_=setup(tmp_path); f=b.buy('ABC',10,q(),datetime.now(timezone.utc),'v1'); assert r.cash()>=2000 and f.fee==Decimal('20'); db.close()
def test_exit_fee_and_position_removed(tmp_path):
 db,r,b,_=setup(tmp_path); now=datetime.now(timezone.utc); b.buy('ABC',10,q(),now,'v1'); p=r.positions()['ABC']; f=b.sell('ABC',q('ABC',str(p.stop_price)),now,'v1',ExitReason.STOP); assert f.fee==Decimal('20') and 'ABC' not in r.positions(); db.close()
def test_daily_loss_blocks(tmp_path):
 db,r,_,rx=setup(tmp_path); assert rx.daily_loss_blocked(datetime.now(timezone.utc),49000); db.close()
