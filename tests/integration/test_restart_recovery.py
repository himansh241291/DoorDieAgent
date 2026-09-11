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
