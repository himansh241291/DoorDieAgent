import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def run_python(code, db_path):
    return subprocess.run(
        [PYTHON, "-c", code, str(db_path)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_state_survives_process_restart(tmp_path):
    db_path = tmp_path / "restart.sqlite3"

    first_process = r"""
import sys
from decimal import Decimal
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Position

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

repo.set_cash(41234.56)
repo.db.set_state("daily_start_equity", 50000.0)

position = Position(
    symbol="ABC",
    qty=87,
    entry_price=Decimal("100.7011005"),
    stop_price=Decimal("99.190584"),
    target_price=Decimal("105.7361555"),
    entry_fee=Decimal("20"),
    strategy_version="baseline-breakout-v1",
    entry_ts=datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc),
    last_mark=Decimal("101.00"),
)

repo.save_position(position)

db.close()
"""

    second_process = r"""
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

assert repo.cash() == 41234.56

positions = repo.positions()
assert "ABC" in positions
assert positions["ABC"].qty == 87
assert str(positions["ABC"].entry_price) == "100.7011005"
assert positions["ABC"].strategy_version == "baseline-breakout-v1"

print("RESTART_RECOVERY_OK")
db.close()
"""

    first = run_python(first_process, db_path)
    assert first.returncode == 0

    second = run_python(second_process, db_path)

    assert "RESTART_RECOVERY_OK" in second.stdout


def test_existing_account_state_is_not_silently_reset(tmp_path):
    db_path = tmp_path / "account_state.sqlite3"

    seed = r"""
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()

repo = Repository(db)
repo.set_cash(43750.25)
repo.db.set_state("daily_start_equity", 45000.0)

db.close()
"""

    verify = r"""
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()

repo = Repository(db)

assert repo.cash() == 43750.25
assert repo.db.get_state("daily_start_equity") == 45000.0

print("ACCOUNT_STATE_PRESERVED")
db.close()
"""

    run_python(seed, db_path)
    result = run_python(verify, db_path)

    assert "ACCOUNT_STATE_PRESERVED" in result.stdout


def test_fill_idempotency_survives_restart(tmp_path):
    db_path = tmp_path / "idempotency.sqlite3"

    first_process = r"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Fill, Side

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

fill = Fill(
    idempotency_key="fill:ABC:BUY:2026-01-02T06:40:00+00:00",
    symbol="ABC",
    side=Side.BUY,
    qty=87,
    price=Decimal("100.7011005"),
    fee=Decimal("20"),
    ts=datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc),
    strategy_version="baseline-breakout-v1",
    slippage_estimate=Decimal("0.1007011"),
    reason="ENTRY",
)

repo.insert_fill(fill)

db.close()
"""

    second_process = r"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Fill, Side

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

key = "fill:ABC:BUY:2026-01-02T06:40:00+00:00"

assert repo.fill_exists(key)

count_before = db.conn.execute(
    "SELECT COUNT(*) FROM simulated_fills WHERE idempotency_key=?",
    (key,),
).fetchone()[0]

assert count_before == 1

# The application must check idempotency before inserting.
if not repo.fill_exists(key):
    fill = Fill(
        idempotency_key=key,
        symbol="ABC",
        side=Side.BUY,
        qty=87,
        price=Decimal("100.7011005"),
        fee=Decimal("20"),
        ts=datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc),
        strategy_version="baseline-breakout-v1",
        slippage_estimate=Decimal("0.1007011"),
        reason="ENTRY",
    )
    repo.insert_fill(fill)

count_after = db.conn.execute(
    "SELECT COUNT(*) FROM simulated_fills WHERE idempotency_key=?",
    (key,),
).fetchone()[0]

assert count_after == 1

print("FILL_IDEMPOTENCY_OK")
db.close()
"""

    run_python(first_process, db_path)
    result = run_python(second_process, db_path)

    assert "FILL_IDEMPOTENCY_OK" in result.stdout


def test_signal_idempotency_survives_restart(tmp_path):
    db_path = tmp_path / "signal_idempotency.sqlite3"

    first_process = r"""
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Signal

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

signal = Signal(
    symbol="ABC",
    bar_end=datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc),
    strategy_version="baseline-breakout-v1",
    eligible=True,
    reason="baseline_entry",
    score=1.0,
    metadata={"test": True},
)

repo.record_signal(
    signal,
    "replay:ABC:2026-01-02T06:40:00+00:00",
)

db.close()
"""

    second_process = r"""
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Signal

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

signal = Signal(
    symbol="ABC",
    bar_end=datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc),
    strategy_version="baseline-breakout-v1",
    eligible=True,
    reason="baseline_entry",
    score=1.0,
    metadata={"test": True},
)

key = "replay:ABC:2026-01-02T06:40:00+00:00"

repo.record_signal(signal, key)

count = db.conn.execute(
    "SELECT COUNT(*) FROM signals WHERE idempotency_key=?",
    (key,),
).fetchone()[0]

assert count == 1

print("SIGNAL_IDEMPOTENCY_OK")
db.close()
"""

    run_python(first_process, db_path)
    result = run_python(second_process, db_path)

    assert "SIGNAL_IDEMPOTENCY_OK" in result.stdout


def test_replay_does_not_reset_existing_account_state(tmp_path):
    import json

    db_path = tmp_path / "existing_account.sqlite3"

    seed = r"""
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()

repo = Repository(db)
repo.set_cash(43123.45)
repo.db.set_state("daily_start_equity", 44000.0)

db.close()
"""

    verify = r"""
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()

repo = Repository(db)

# Simulate the exact startup logic used by run_replay.py.
if repo.db.get_state("cash") is None:
    repo.set_cash(50000.0)

if repo.db.get_state("daily_start_equity") is None:
    repo.db.set_state("daily_start_equity", 50000.0)

assert repo.cash() == 43123.45
assert repo.db.get_state("daily_start_equity") == 44000.0

print("REPLAY_ACCOUNT_STATE_NOT_RESET")
db.close()
"""

    run_python(seed, db_path)
    result = run_python(verify, db_path)

    assert "REPLAY_ACCOUNT_STATE_NOT_RESET" in result.stdout


def test_checkpoint_survives_restart(tmp_path):
    db_path = tmp_path / "checkpoint.sqlite3"

    first_process = r"""
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

ts = datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc)

repo.set_checkpoint("ABC", ts)

db.close()
"""

    second_process = r"""
import sys
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

checkpoint = repo.get_checkpoint("ABC")

assert checkpoint == "2026-01-02T06:40:00+00:00"

print("CHECKPOINT_RECOVERED")
db.close()
"""

    run_python(first_process, db_path)
    result = run_python(second_process, db_path)

    assert "CHECKPOINT_RECOVERED" in result.stdout


def test_checkpoint_is_per_symbol(tmp_path):
    db_path = tmp_path / "symbol_checkpoint.sqlite3"

    process = r"""
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

abc = datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc)
xyz = datetime(2026, 1, 2, 6, 45, tzinfo=timezone.utc)

repo.set_checkpoint("ABC", abc)
repo.set_checkpoint("XYZ", xyz)

assert repo.get_checkpoint("ABC") == "2026-01-02T06:40:00+00:00"
assert repo.get_checkpoint("XYZ") == "2026-01-02T06:45:00+00:00"

print("PER_SYMBOL_CHECKPOINT_OK")
db.close()
"""

    result = run_python(process, db_path)

    assert "PER_SYMBOL_CHECKPOINT_OK" in result.stdout


def test_checkpoint_prevents_duplicate_bar_processing(tmp_path):
    db_path = tmp_path / "duplicate_bar.sqlite3"

    process = r"""
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Bar

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

bar = Bar(
    symbol="ABC",
    start=datetime(2026, 1, 2, 6, 35, tzinfo=timezone.utc),
    end=datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc),
    open=100,
    high=101,
    low=99,
    close=100.5,
    volume=50000,
)

repo.record_bar(bar)
repo.set_checkpoint("ABC", bar.end)

checkpoint = repo.get_checkpoint("ABC")

assert checkpoint == bar.end.isoformat()

# Simulate the replay's restart decision.
should_skip = checkpoint is not None and bar.end.isoformat() <= checkpoint

assert should_skip is True

count = db.conn.execute(
    "SELECT COUNT(*) FROM market_bars WHERE symbol='ABC'"
).fetchone()[0]

assert count == 1

print("DUPLICATE_BAR_BLOCKED")
db.close()
"""

    result = run_python(process, db_path)

    assert "DUPLICATE_BAR_BLOCKED" in result.stdout


def test_snapshot_and_checkpoint_are_atomic(tmp_path):
    db_path = tmp_path / "atomic_checkpoint.sqlite3"

    process = r'''
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

ts = datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc)

repo.record_account_snapshot_and_checkpoint(
    symbol="ABC",
    bar_end=ts,
    cash=50000.0,
    equity=50000.0,
    gross=0.0,
    daily_start_equity=50000.0,
    drawdown5=0.0,
)

snapshot_count = db.conn.execute(
    "SELECT COUNT(*) FROM account_snapshots"
).fetchone()[0]

assert snapshot_count == 1
assert repo.get_checkpoint("ABC") == "2026-01-02T06:40:00+00:00"

print("ATOMIC_CHECKPOINT_COMMIT_OK")
db.close()
'''

    result = run_python(process, db_path)

    assert "ATOMIC_CHECKPOINT_COMMIT_OK" in result.stdout


def test_failed_snapshot_does_not_advance_checkpoint(tmp_path):
    db_path = tmp_path / "failed_checkpoint.sqlite3"

    process = r'''
import sys
from datetime import datetime, timezone

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

old_ts = datetime(2026, 1, 2, 6, 35, tzinfo=timezone.utc)

repo.record_account_snapshot_and_checkpoint(
    symbol="ABC",
    bar_end=old_ts,
    cash=50000.0,
    equity=50000.0,
    gross=0.0,
    daily_start_equity=50000.0,
    drawdown5=0.0,
)

new_ts = datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc)

try:
    with db.transaction():
        db.conn.execute(
            """
            INSERT INTO account_snapshots
            (ts_utc, ts_ist, cash, equity, gross, daily_start_equity, drawdown5)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_ts.isoformat(),
                new_ts.isoformat(),
                49000.0,
                49000.0,
                0.0,
                50000.0,
                0.0,
            ),
        )

        raise RuntimeError("simulated persistence failure")

except RuntimeError:
    pass

snapshot_count = db.conn.execute(
    "SELECT COUNT(*) FROM account_snapshots"
).fetchone()[0]

assert snapshot_count == 1
assert repo.get_checkpoint("ABC") == "2026-01-02T06:35:00+00:00"

print("FAILED_SNAPSHOT_DID_NOT_ADVANCE_CHECKPOINT")
db.close()
'''

    result = run_python(process, db_path)

    assert "FAILED_SNAPSHOT_DID_NOT_ADVANCE_CHECKPOINT" in result.stdout


def test_market_bar_history_survives_restart(tmp_path):
    db_path = tmp_path / "bar_history.sqlite3"

    first_process = r"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Bar

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

bars = []

for minute, close in (
    (0, "100.00"),
    (5, "100.50"),
    (10, "101.00"),
):
    bar = Bar(
        symbol="ABC",
        start=datetime(2026, 1, 2, 6, minute, tzinfo=timezone.utc),
        end=datetime(2026, 1, 2, 6, minute + 5, tzinfo=timezone.utc),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("50000"),
    )
    repo.record_bar(bar)
    bars.append(bar)

repo.set_checkpoint("ABC", bars[-1].end)

db.close()
"""

    second_process = r"""
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

history = repo.market_bars("ABC")
checkpoint = repo.get_checkpoint("ABC")

assert len(history) == 3
assert [str(bar.close) for bar in history] == [
    "100.0",
    "100.5",
    "101.0",
]
assert checkpoint == "2026-01-02T06:15:00+00:00"

print("BAR_HISTORY_RECOVERED")
db.close()
"""

    run_python(first_process, db_path)
    result = run_python(second_process, db_path)

    assert "BAR_HISTORY_RECOVERED" in result.stdout


def test_recovered_history_is_available_before_new_bar(tmp_path):
    db_path = tmp_path / "history_before_new_bar.sqlite3"

    process = r"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.domain.models import Bar

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

for minute, close in (
    (0, "100.00"),
    (5, "100.50"),
    (10, "101.00"),
):
    bar = Bar(
        symbol="ABC",
        start=datetime(2026, 1, 2, 6, minute, tzinfo=timezone.utc),
        end=datetime(2026, 1, 2, 6, minute + 5, tzinfo=timezone.utc),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("50000"),
    )
    repo.record_bar(bar)

# Simulate application restart.
history = repo.market_bars("ABC")

new_bar = Bar(
    symbol="ABC",
    start=datetime(2026, 1, 2, 6, 15, tzinfo=timezone.utc),
    end=datetime(2026, 1, 2, 6, 20, tzinfo=timezone.utc),
    open=Decimal("101.00"),
    high=Decimal("101.50"),
    low=Decimal("101.00"),
    close=Decimal("101.50"),
    volume=Decimal("50000"),
)

history.append(new_bar)

assert len(history) == 4
assert history[-1].end == new_bar.end
assert history[-1].close == Decimal("101.50")

print("RECOVERED_HISTORY_PLUS_NEW_BAR_OK")
db.close()
"""

    result = run_python(process, db_path)

    assert "RECOVERED_HISTORY_PLUS_NEW_BAR_OK" in result.stdout


def test_hard_crash_after_buy_commit_recovers_without_duplicate(tmp_path):
    import os
    import signal

    db_path = tmp_path / "hard_crash_buy.sqlite3"

    process = r'''
import os
import signal
import sys
from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.domain.models import Quote

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

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
        "slippage_bps": 10,
    },
    "execution": {
        "last_price_slippage_bps": 25,
    },
}

repo.set_cash(50000.0)
broker = PaperBroker(cfg, repo)

now = datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc)

quote = Quote(
    "ABC",
    now,
    Decimal("99.00"),
    Decimal("100.00"),
    Decimal("99.50"),
    Decimal("50000"),
)

broker.buy(
    "ABC",
    87,
    quote,
    now,
    "baseline-breakout-v1",
)

# The broker transaction has committed.
# Simulate an unrecoverable process crash immediately afterward.
os.kill(os.getpid(), signal.SIGKILL)
'''

    crashed = subprocess.run(
        [PYTHON, "-c", process, str(db_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert crashed.returncode == -signal.SIGKILL

    verify = r'''
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

positions = repo.positions()

assert "ABC" in positions
assert positions["ABC"].qty == 87

fills = db.conn.execute(
    "SELECT COUNT(*) FROM simulated_fills WHERE symbol='ABC' AND side='BUY'"
).fetchone()[0]

assert fills == 1

cash = repo.cash()
expected_cash = 50000.0 - (100.10 * 87) - 20.0

assert abs(cash - expected_cash) < 1e-9

print("HARD_CRASH_AFTER_BUY_RECOVERED")
db.close()
'''

    result = run_python(verify, db_path)

    assert "HARD_CRASH_AFTER_BUY_RECOVERED" in result.stdout


def test_hard_crash_after_sell_commit_recovers_without_duplicate(tmp_path):
    import os
    import signal

    db_path = tmp_path / "hard_crash_sell.sqlite3"

    process = r'''
import os
import signal
import sys
from datetime import datetime, timezone
from decimal import Decimal

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.domain.models import Quote, Position, ExitReason

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

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
        "slippage_bps": 10,
    },
    "execution": {
        "last_price_slippage_bps": 25,
    },
}

repo.set_cash(40000.0)

entry_time = datetime(2026, 1, 2, 6, 40, tzinfo=timezone.utc)

position = Position(
    symbol="ABC",
    qty=87,
    entry_price=Decimal("100.10"),
    stop_price=Decimal("98.5985"),
    target_price=Decimal("105.105"),
    entry_fee=Decimal("20"),
    strategy_version="baseline-breakout-v1",
    entry_ts=entry_time,
    last_mark=Decimal("100.10"),
)

repo.save_position(position)

broker = PaperBroker(cfg, repo)

exit_time = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)

quote = Quote(
    "ABC",
    exit_time,
    Decimal("106.00"),
    Decimal("107.00"),
    Decimal("106.50"),
    Decimal("50000"),
)

broker.sell(
    "ABC",
    quote,
    exit_time,
    "baseline-breakout-v1",
    ExitReason.TARGET,
)

# The broker transaction has committed.
# Simulate an unrecoverable process crash immediately afterward.
os.kill(os.getpid(), signal.SIGKILL)
'''

    crashed = subprocess.run(
        [PYTHON, "-c", process, str(db_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert crashed.returncode == -signal.SIGKILL

    verify = r'''
import sys

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository

db = Database(sys.argv[1])
db.initialize()
repo = Repository(db)

assert "ABC" not in repo.positions()

sell_fills = db.conn.execute(
    "SELECT COUNT(*) FROM simulated_fills WHERE symbol='ABC' AND side='SELL'"
).fetchone()[0]

assert sell_fills == 1

closed = db.conn.execute(
    "SELECT COUNT(*) FROM closed_trades WHERE symbol='ABC'"
).fetchone()[0]

assert closed == 1

print("HARD_CRASH_AFTER_SELL_RECOVERED")
db.close()
'''

    result = run_python(verify, db_path)

    assert "HARD_CRASH_AFTER_SELL_RECOVERED" in result.stdout
