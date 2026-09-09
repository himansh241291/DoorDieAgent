from __future__ import annotations
import argparse,json,os,sqlite3
from nse_paper_agent.config import load_yaml
def main():
    p=argparse.ArgumentParser(); p.add_argument("--config",required=True); a=p.parse_args(); c=load_yaml(a.config); path=c["persistence"]["database"]; ok=os.path.exists(path)
    if ok:
        con=sqlite3.connect(path); result=con.execute("PRAGMA quick_check").fetchone()[0]; con.close(); ok=result=="ok"
    print(json.dumps({"ok":ok,"database":path,"mode":c["app"]["mode"]})); raise SystemExit(0 if ok else 1)
