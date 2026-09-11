import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "scripts" / "run_replay.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_replay(fixture, tmp_path):
    db_path = tmp_path / f"{fixture.stem}.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            str(REPLAY),
            "--bars",
            str(fixture),
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    return db_path, result


def test_target_trade_lifecycle(tmp_path):
    fixture = FIXTURES / "trade_lifecycle_target.csv"

    db_path, result = run_replay(fixture, tmp_path)

    assert "'symbols': 1" in result.stdout
    assert "'bars': 46" in result.stdout
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    fills = db.execute(
        """
        SELECT side, qty, price, fee, reason
        FROM simulated_fills
        ORDER BY id
        """
    ).fetchall()

    assert len(fills) == 2

    buy, sell = fills

    assert buy["side"] == "BUY"
    assert buy["qty"] == 87
    assert buy["fee"] == 20.0
    assert buy["reason"] == "ENTRY"

    assert sell["side"] == "SELL"
    assert sell["qty"] == 87
    assert sell["fee"] == 20.0
    assert sell["reason"] == "TARGET"

    trade = db.execute(
        """
        SELECT
            qty,
            entry_price,
            exit_price,
            entry_fee,
            exit_fee,
            gross_pnl,
            net_pnl,
            strategy_version,
            exit_reason
        FROM closed_trades
        """
    ).fetchone()

    assert trade is not None
    assert trade["qty"] == 87
    assert trade["entry_fee"] == 20.0
    assert trade["exit_fee"] == 20.0
    assert trade["strategy_version"] == "baseline-breakout-v1"
    assert trade["exit_reason"] == "TARGET"

    # The target lifecycle must produce a positive net result
    # after both mandatory fees.
    assert trade["gross_pnl"] > 0
    assert trade["net_pnl"] > 0

    # Exact cash result verifies that conservative execution
    # pricing and both mandatory fees were applied.
    cash_json = db.execute(
        "SELECT value FROM kv_state WHERE key='cash'"
    ).fetchone()[0]

    final_cash = float(cash_json)

    assert abs(final_cash - 50402.5694785) < 1e-6
    assert abs(trade["net_pnl"] - 402.5694785) < 1e-6

    db.close()


def test_stop_trade_lifecycle_and_cooldown(tmp_path):
    fixture = FIXTURES / "trade_lifecycle_stop.csv"

    db_path, result = run_replay(fixture, tmp_path)

    assert "'symbols': 1" in result.stdout
    assert "'bars': 37" in result.stdout
    assert "'open_positions': []" in result.stdout

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    fills = db.execute(
        """
        SELECT side, qty, price, fee, reason
        FROM simulated_fills
        ORDER BY id
        """
    ).fetchall()

    assert len(fills) == 2

    buy, sell = fills

    assert buy["side"] == "BUY"
    assert buy["qty"] == 87
    assert buy["fee"] == 20.0
    assert buy["reason"] == "ENTRY"

    assert sell["side"] == "SELL"
    assert sell["qty"] == 87
    assert sell["fee"] == 20.0
    assert sell["reason"] == "STOP"

    trade = db.execute(
        """
        SELECT
            qty,
            entry_price,
            exit_price,
            entry_fee,
            exit_fee,
            gross_pnl,
            net_pnl,
            exit_reason
        FROM closed_trades
        """
    ).fetchone()

    assert trade is not None
    assert trade["qty"] == 87
    assert trade["entry_fee"] == 20.0
    assert trade["exit_fee"] == 20.0
    assert trade["exit_reason"] == "STOP"
    assert trade["gross_pnl"] < 0
    assert trade["net_pnl"] < trade["gross_pnl"]

    cooldown = db.execute(
        """
        SELECT until_utc, reason
        FROM cooldowns
        WHERE symbol='ABC'
        """
    ).fetchone()

    assert cooldown is not None
    assert cooldown["reason"] == "stop_loss"

    cooldown_signal = db.execute(
        """
        SELECT eligible, reason
        FROM signals
        WHERE reason='stop_cooldown'
        """
    ).fetchone()

    assert cooldown_signal is not None
    assert cooldown_signal["eligible"] == 0

    db.close()



def test_stale_quote_blocks_entry_but_allows_existing_stop(tmp_path):
    from datetime import datetime, timedelta
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from nse_paper_agent.agent import TradingAgent
    from nse_paper_agent.domain.models import Position, Quote
    from nse_paper_agent.persistence.db import Database
    from nse_paper_agent.persistence.repository import Repository
    from nse_paper_agent.paper_broker.broker import PaperBroker
    from nse_paper_agent.risk.engine import RiskEngine
    from nse_paper_agent.risk.health import DataHealth
    from nse_paper_agent.session import SessionGuard
    from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy
    from nse_paper_agent.regime.engine import RegimeEngine
    from nse_paper_agent.sentiment.provider import NeutralSentimentProvider

    class Provider:
        def __init__(self, quote):
            self.quote = quote

        def connect(self):
            pass

        def disconnect(self):
            pass

        def healthy(self, now):
            return False, "feed_degraded"

        def latest_quotes(self, symbols):
            return {symbol: self.quote for symbol in symbols}

        def completed_bars(self, symbol, interval_minutes, end):
            return []

    class Notifier:
        def send(self, payload):
            pass

    root = Path(__file__).resolve().parents[2]
    now = datetime(
        2026, 9, 11, 15, 30,
        tzinfo=ZoneInfo("Asia/Kolkata"),
    )

    cfg = {
        "account": {
            "starting_capital": 50000.0,
            "minimum_cash_reserve": 2000.0,
            "max_open_positions": 5,
            "max_gross_position": 10000.0,
            "buy_fee": 20.0,
            "sell_fee": 20.0,
            "risk_per_trade": 0.003,
        },
        "risk": {
            "hard_stop_pct": 0.015,
            "take_profit_pct": 0.05,
            "daily_loss_limit_pct": 0.02,
            "rolling_drawdown_pct": 0.04,
            "rolling_drawdown_days": 5,
            "rolling_block_hours": 48,
            "stop_cooldown_minutes": 120,
            "slippage_bps": 10,
            "max_spread_bps": 50,
        },
        "execution": {"last_price_slippage_bps": 25},
        "session": {
            "pre_open": "09:00",
            "open": "09:15",
            "entry_cutoff": "14:45",
            "close": "15:30",
            "calendar_path": str(root / "config" / "nse_holidays.yaml"),
        },
        "safety": {
            "global_kill_switch": False,
            "emergency_kill_file": str(tmp_path / "no-kill"),
        },
        "market": {"bar_interval_minutes": 5},
    }

    db = Database(str(tmp_path / "agent_health.sqlite3"))
    db.initialize()
    repo = Repository(db)

    repo.set_cash(48980.0)
    repo.save_position(
        Position(
            symbol="ABC",
            qty=10,
            entry_price=Decimal("100"),
            stop_price=Decimal("98.5"),
            target_price=Decimal("105"),
            entry_fee=Decimal("20"),
            strategy_version="baseline-breakout-v1",
            entry_ts=now - timedelta(minutes=30),
            last_mark=Decimal("100"),
        )
    )

    # Stale, but still has a usable bid below the stop.
    quote = Quote(
        "ABC",
        now - timedelta(minutes=5),
        Decimal("98"),
        Decimal("98.2"),
        Decimal("98.1"),
        Decimal("1000"),
    )

    agent = TradingAgent(
        cfg,
        Provider(quote),
        repo,
        PaperBroker(cfg, repo),
        RiskEngine(cfg, repo),
        DataHealth(30, 50),
        BaselineBreakoutStrategy(),
        RegimeEngine(),
        NeutralSentimentProvider(),
        SessionGuard(cfg),
        Notifier(),
        lambda: now,
    )

    agent.startup()
    agent.cycle(["ABC"])
    agent.shutdown()

    assert repo.positions() == {}

    fills = db.conn.execute(
        "SELECT side, reason FROM simulated_fills ORDER BY rowid"
    ).fetchall()

    assert [(row["side"], row["reason"]) for row in fills] == [
        ("SELL", "STOP")
    ]

    health = db.conn.execute(
        """
        SELECT healthy, reason
        FROM data_health_events
        ORDER BY rowid DESC
        LIMIT 1
        """
    ).fetchone()

    assert (health["healthy"], health["reason"]) == (
        0,
        "feed_degraded",
    )

    assert db.conn.execute(
        "SELECT COUNT(*) FROM simulated_fills WHERE side='BUY'"
    ).fetchone()[0] == 0

    db.close()
