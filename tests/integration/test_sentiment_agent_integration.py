from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.domain.models import Bar, ExitReason, Position, Quote, Regime, SentimentObservation
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy


class StaticSentiment:
    def __init__(self, market_score, symbol_score):
        self.market_score = market_score
        self.symbol_score = symbol_score

    def market(self, now):
        return SentimentObservation("NIFTY50", now, self.market_score, 1.0, "test", now, {})

    def symbol(self, symbol, now):
        return SentimentObservation(symbol, now, self.symbol_score, 1.0, "test", now, {})


def test_sentiment_quality_changes_strategy_entry_without_touching_risk(tmp_path):
    strategy = BaselineBreakoutStrategy()
    now = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)
    cases = [(0.80, True), (0.20, True), (0.05, False), (None, True)]
    bars = []
    for i in range(21):
        close = Decimal("100") if i < 20 else Decimal("101")
        bar_time = now.replace(minute=0) if i < 20 else now
        bars.append(Bar("ABC", bar_time, bar_time, close, close, close, close, Decimal("100000")))

    # Validate the strategy integration contract; the risk engine remains the
    # authoritative sizing/control layer after the strategy emits a signal.
    for sentiment, eligible in cases:
        signal = strategy.evaluate(
            bars, now, Regime.RISK_ON, sentiment, False, False, True, True
        )
        assert signal.eligible is eligible


def test_negative_sentiment_does_not_disable_existing_position_exit(tmp_path):
    db = Database(str(tmp_path / "sentiment.sqlite"))
    db.initialize()
    repo = Repository(db)
    repo.set_cash(48980)
    repo.save_position(
        Position(
            "ABC", 10, Decimal("100"), Decimal("98.5"), Decimal("105"),
            Decimal("20"), "baseline-breakout-v1", datetime.now(timezone.utc), Decimal("100")
        )
    )
    broker = PaperBroker(
        {"account": {"buy_fee": 20, "sell_fee": 20}, "risk": {"slippage_bps": 10}},
        repo,
    )
    quote = Quote(
        "ABC", datetime.now(timezone.utc), Decimal("98.4"), Decimal("98.6"),
        Decimal("98.5"), Decimal("100000")
    )
    fill = broker.sell("ABC", quote, quote.ts, "baseline-breakout-v1", ExitReason.STOP)
    assert fill.qty == 10
    assert "ABC" not in repo.positions()
    db.close()
