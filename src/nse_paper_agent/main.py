from __future__ import annotations
import argparse, signal
from nse_paper_agent.config import load_yaml, validate_runtime_config, immutable_risk_hash
from nse_paper_agent.data.provider import LiveMarketDataAdapterPlaceholder
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.risk.engine import RiskEngine
from nse_paper_agent.risk.health import DataHealth
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy
from nse_paper_agent.regime.engine import RegimeEngine
from nse_paper_agent.sentiment.provider import NeutralSentimentProvider
from nse_paper_agent.session import SessionGuard
from nse_paper_agent.monitoring.alerts import NullNotifier, WebhookNotifier
from nse_paper_agent.monitoring.logging import configure_logging
from nse_paper_agent.utils.locking import SingleProcessLock
from nse_paper_agent.utils.time import utcnow

def build(cfg_path):
    cfg=load_yaml(cfg_path); validate_runtime_config(cfg)
    expected=cfg["safety"].get("production_config_immutable_risk_hash",""); actual=immutable_risk_hash(cfg)
    if expected and expected!=actual: raise ValueError("immutable risk configuration hash mismatch")
    configure_logging(cfg["logging"]["directory"],cfg["logging"]["level"],cfg["logging"]["max_bytes"],cfg["logging"]["backup_count"])
    db=Database(cfg["persistence"]["database"]); db.initialize(); repo=Repository(db)
    provider=LiveMarketDataAdapterPlaceholder("configured-live-market-data-placeholder")
    broker=PaperBroker(cfg,repo); risk=RiskEngine(cfg,repo); health=DataHealth(30,cfg["risk"]["max_spread_bps"])
    strategy=BaselineBreakoutStrategy(); regime=RegimeEngine(); sentiment=NeutralSentimentProvider(); session=SessionGuard(cfg)
    notifier=WebhookNotifier(cfg["notifications"]["webhook_url_env"]) if cfg["notifications"]["enabled"] else NullNotifier()
    from nse_paper_agent.agent import TradingAgent
    return TradingAgent(cfg,provider,repo,broker,risk,health,strategy,regime,sentiment,session,notifier,utcnow),db

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config",default="config/production.paper.yaml"); ap.add_argument("--symbols",nargs="*",default=[]); args=ap.parse_args()
    agent,db=build(args.config); stop=False
    def handler(signum,frame):
        nonlocal stop; stop=True
    signal.signal(signal.SIGTERM,handler); signal.signal(signal.SIGINT,handler)
    lock_path="/run/nse-paper-agent/agent.lock" if __import__('os').path.isdir("/run/nse-paper-agent") else "/tmp/nse-paper-agent.lock"
    with SingleProcessLock(lock_path):
        agent.startup()
        try:
            import time
            while not stop:
                if args.symbols: agent.cycle(args.symbols)
                time.sleep(30)
        finally: agent.shutdown(); db.close()
if __name__=="__main__": main()
