#!/usr/bin/env python3
import argparse
from nse_paper_agent.config import load_yaml,validate_runtime_config,immutable_risk_hash
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
p=argparse.ArgumentParser(); p.add_argument("--config",required=True); a=p.parse_args(); cfg=load_yaml(a.config); validate_runtime_config(cfg); db=Database(cfg["persistence"]["database"]); db.initialize(); repo=Repository(db)
if db.get_state("initialized") is None: repo.set_cash(cfg["account"]["starting_capital"]); db.set_state("daily_start_equity",cfg["account"]["starting_capital"]); db.set_state("immutable_risk_hash",immutable_risk_hash(cfg)); db.set_state("initialized",True)
print(f"initialized {cfg['persistence']['database']}"); db.close()
