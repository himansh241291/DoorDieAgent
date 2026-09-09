#!/usr/bin/env python3
import argparse,json
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from nse_paper_agent.config import load_yaml
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
p=argparse.ArgumentParser(); p.add_argument("--config",required=True); a=p.parse_args(); c=load_yaml(a.config); db=Database(c["persistence"]["database"]); db.initialize(); repo=Repository(db); now=datetime.now(timezone.utc); equity=float(db.get_state("last_equity",c["account"]["starting_capital"])); cash=repo.cash(); gross=equity-cash
with db.conn: db.conn.execute("INSERT INTO account_snapshots(ts_utc,ts_ist,cash,equity,gross,daily_start_equity,drawdown5) VALUES(?,?,?,?,?,?,?)",(now.isoformat(),now.astimezone(ZoneInfo("Asia/Kolkata")).isoformat(),cash,equity,gross,float(db.get_state("daily_start_equity",equity)),0.0)); db.set_state("daily_start_equity",equity)
print(json.dumps({"eod_equity":equity,"cash":cash,"gross":gross,"ts":now.isoformat()})); print(db.backup(c["persistence"]["backup_dir"])); db.close()
