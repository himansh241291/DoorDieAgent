from datetime import datetime, timezone, timedelta

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.risk.engine import RiskEngine


def cfg():
    return {
        "account": {
            "starting_capital": 50000.0,
            "minimum_cash_reserve": 2000.0,
            "max_open_positions": 5,
            "max_gross_position": 10000.0,
            "buy_fee": 20.0,
            "sell_fee": 20.0,
            "risk_per_trade": .003,
        },
        "risk": {
            "hard_stop_pct": .015,
            "take_profit_pct": .05,
            "daily_loss_limit_pct": .02,
            "rolling_drawdown_pct": .04,
            "rolling_drawdown_days": 5,
            "rolling_block_hours": 48,
            "stop_cooldown_minutes": 120,
            "slippage_bps": 10,
            "max_spread_bps": 50,
        },
        "safety": {
            "global_kill_switch": False,
            "emergency_kill_file": "/tmp/no-kill",
        },
    }


def insert_eod(repo, trading_date, equity):
    ts = datetime.fromisoformat(
        f"{trading_date}T15:30:00+05:30"
    )

    repo.record_eod_snapshot(
        trading_date=trading_date,
        ts=ts,
        cash=equity,
        equity=equity,
        gross=0.0,
        daily_start_equity=50000.0,
        drawdown5=0.0,
    )


def test_five_completed_eod_marks_trigger_four_percent_drawdown(tmp_path):
    db = Database(str(tmp_path / "x.sqlite"))
    db.initialize()
    repo = Repository(db)
    rx = RiskEngine(cfg(), repo)

    for d, equity in zip(
        [
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
            "2026-09-07",
        ],
        [50000, 51000, 50500, 49000, 48000],
    ):
        insert_eod(repo, d, equity)

    now = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    assert rx.rolling_drawdown_blocked(now)

    block_until = repo.db.get_state("rolling_block_until")
    assert block_until is not None

    db.close()


def test_intraday_snapshots_do_not_count_as_completed_eod_marks(tmp_path):
    db = Database(str(tmp_path / "x.sqlite"))
    db.initialize()
    repo = Repository(db)
    rx = RiskEngine(cfg(), repo)

    # Four EOD marks are insufficient.
    for d, equity in zip(
        [
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
        ],
        [50000, 49000, 48000, 47000],
    ):
        insert_eod(repo, d, equity)

    # Add many ordinary intraday snapshots.
    for i in range(20):
        ts = datetime(
            2026,
            9,
            4,
            10,
            0,
            tzinfo=timezone.utc,
        ) + timedelta(minutes=i)

        repo.record_account_snapshot_and_checkpoint(
            symbol="ABC",
            bar_end=ts,
            cash=46000,
            equity=46000,
            gross=0,
            daily_start_equity=50000,
            drawdown5=0,
            trading_date="2026-09-04",
            is_eod=False,
        )

    assert len(repo.eod_marks(5)) == 4
    assert not rx.rolling_drawdown_blocked(
        datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    )

    db.close()


def test_eod_mark_is_idempotent(tmp_path):
    db = Database(str(tmp_path / "x.sqlite"))
    db.initialize()
    repo = Repository(db)

    insert_eod(repo, "2026-09-07", 50000)
    insert_eod(repo, "2026-09-07", 49000)

    rows = repo.eod_marks(5)

    assert len(rows) == 1
    assert rows[0]["equity"] == 50000.0

    db.close()


def test_rolling_block_is_48_hours(tmp_path):
    db = Database(str(tmp_path / "x.sqlite"))
    db.initialize()
    repo = Repository(db)
    rx = RiskEngine(cfg(), repo)

    for d, equity in zip(
        [
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
            "2026-09-07",
        ],
        [50000, 51000, 50500, 49000, 48000],
    ):
        insert_eod(repo, d, equity)

    now = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    assert rx.rolling_drawdown_blocked(now)

    block_until = datetime.fromisoformat(
        repo.db.get_state("rolling_block_until")
    )

    assert block_until == now + timedelta(hours=48)

    db.close()
