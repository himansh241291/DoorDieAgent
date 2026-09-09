from datetime import datetime,timezone,timedelta
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.risk.engine import RiskEngine

def cfg(): return {"account":{"starting_capital":50000.0,"minimum_cash_reserve":2000.0,"max_open_positions":5,"max_gross_position":10000.0,"buy_fee":20.0,"sell_fee":20.0,"risk_per_trade":.003},"risk":{"hard_stop_pct":.015,"take_profit_pct":.05,"daily_loss_limit_pct":.02,"rolling_drawdown_pct":.04,"rolling_drawdown_days":5,"rolling_block_hours":48,"stop_cooldown_minutes":120,"slippage_bps":10,"max_spread_bps":50},"safety":{"global_kill_switch":False,"emergency_kill_file":"/tmp/no-kill"}}
def test_five_day_drawdown_sets_block(tmp_path):
 db=Database(str(tmp_path/'x')); db.initialize(); r=Repository(db); rx=RiskEngine(cfg(),r); now=datetime.now(timezone.utc)
 for i,e in enumerate([50000,48000,47500,47000,46500]): db.conn.execute("INSERT INTO account_snapshots(ts_utc,ts_ist,cash,equity,gross,daily_start_equity,drawdown5) VALUES(?,?,?,?,?,?,?)",((now-timedelta(days=i)).isoformat(),now.isoformat(),e,e,0,50000,0))
 assert rx.rolling_drawdown_blocked(now); db.close()
