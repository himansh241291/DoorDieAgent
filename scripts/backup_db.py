#!/usr/bin/env python3
import argparse
from nse_paper_agent.config import load_yaml
from nse_paper_agent.persistence.db import Database
p=argparse.ArgumentParser(); p.add_argument("--config",required=True); a=p.parse_args(); c=load_yaml(a.config); db=Database(c["persistence"]["database"]); db.initialize(); print(db.backup(c["persistence"]["backup_dir"])); db.close()
