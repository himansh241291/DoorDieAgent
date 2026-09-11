from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.domain.models import Bar, ExitReason, Position, Quote, Regime
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy


def test_sentiment_quality_changes_strategy_entry_without_touching_risk():
    strategy = BaselineBreakoutStrategy()
    now = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)

    # First 14 changes net to zero (10 x +0.20, 4 x -0.50), then six
    # unchanged bars, then +1.00. This gives the strategy the required
    # 21 completed bars while preserving a real SMA cross and RSI in 50-70.
    closes = [Decimal("100")]
    for change in [
        Decimal("0.20"), Decimal("0.20"), Decimal("0.20"), Decimal("0.20"),
        Decimal("0.20"), Decimal("0.20"), Decimal("0.20"), Decimal("0.20"),
        Decimal("0.20"), Decimal("0.20"), Decimal("-0.50"), Decimal("-0.50"),
        Decimal("-0.50"), Decimal("-0.50"),
    ]:
        closes.append(closes[-1] + change)
    closes.extend([Decimal("100")] * 6)
    assert closes[-1] == Decimal("100")
    closes.append(Decimal("101"))

    bars = [
        Bar("ABC", now, now, close, close, close, close, Decimal("100000"))
        for close in closes
    ]

    cases = [(0.80, True, 1.0), (0.20, True, 0.5), (0.05, False, None), (None, True, 1.0)]
    for sentiment, eligible, expected_size_factor in cases:
        signal = strategy.evaluate(
            bars, now, Regime.RISK_ON, sentiment, False, False, True, True
        )
        assert signal.eligible is eligible
        if eligible:
            assert signal.metadata["sentiment_size_factor"] == expected_size_factor
        else:
            assert signal.reason == "sentiment_filter"


def test_negative_sentiment_does_not_disable_existing_position_exit(tmp_path):
    db = Database(str(tmp_path / "sentiment.sqlite"))
    db.initialize()
    repo = Repository(db)
    now = datetime.now(timezone.utc)
    repo.set_cash(Decimal("48980"))
    repo.save_position(
        Position(
            "ABC", 10, Decimal("100"), Decimal("98.5"), Decimal("105"),
            Decimal("20"), "baseline-breakout-v1", now, Decimal("100")
        )
    )
    broker = PaperBroker(
        {"account": {"buy_fee": 20, "sell_fee": 20}, "risk": {"slippage_bps": 10}},
        repo,
    )
    quote = Quote(
        "ABC", now, Decimal("98.4"), Decimal("98.6"), Decimal("98.5"), Decimal("100000")
    )
    fill = broker.sell("ABC", quote, quote.ts, "baseline-breakout-v1", ExitReason.STOP)
    assert fill.qty == 10
    assert "ABC" not in repo.positions()
    db.close()
