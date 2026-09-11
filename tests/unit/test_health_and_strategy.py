from datetime import datetime,timezone,timedelta
from decimal import Decimal
from nse_paper_agent.domain.models import Quote,Regime,Bar
from nse_paper_agent.risk.health import DataHealth
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy
def test_stale_quote_blocks():
 now=datetime.now(timezone.utc); q=Quote('ABC',now-timedelta(minutes=2),Decimal('100'),Decimal('101'),Decimal('100'),Decimal('1')); assert not DataHealth(30,50).check_quote(q,now)[0]
def test_bad_quote_blocks():
 now=datetime.now(timezone.utc); q=Quote('ABC',now,Decimal('-1'),Decimal('1'),Decimal('1'),Decimal('1')); assert not DataHealth().check_quote(q,now)[0]
def test_risk_off_blocks_strategy():
 now=datetime.now(timezone.utc); bars=[]; p=100
 for i in range(35):
  p=100+i*.01; t=now-timedelta(minutes=5*(35-i)); bars.append(Bar('ABC',t,t+timedelta(minutes=5),Decimal(str(p)),Decimal(str(p+1)),Decimal(str(p-1)),Decimal(str(p)),Decimal('100000')))
 assert not BaselineBreakoutStrategy().evaluate(bars,now,Regime.RISK_OFF,.8,False,False,True,True).eligible


def test_exit_price_allows_stale_quote():
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from nse_paper_agent.domain.models import Quote
    from nse_paper_agent.risk.health import DataHealth

    now = datetime.now(timezone.utc)

    q = Quote(
        "ABC",
        now - timedelta(minutes=5),
        Decimal("99"),
        Decimal("101"),
        Decimal("100"),
        Decimal("1000"),
    )

    health = DataHealth(max_age_seconds=30, max_spread_bps=50)

    ok, reason = health.check_quote(q, now)
    assert not ok
    assert reason == "stale_quote"

    exit_ok, exit_reason = health.check_exit_price(q)
    assert exit_ok
    assert exit_reason == "bid_available"


def test_exit_price_rejects_unusable_quote():
    from datetime import datetime, timezone
    from decimal import Decimal

    from nse_paper_agent.domain.models import Quote
    from nse_paper_agent.risk.health import DataHealth

    now = datetime.now(timezone.utc)

    q = Quote(
        "ABC",
        now,
        None,
        None,
        None,
        Decimal("1000"),
    )

    health = DataHealth(max_age_seconds=30, max_spread_bps=50)

    ok, reason = health.check_exit_price(q)

    assert not ok
    assert reason == "no_exit_price"
