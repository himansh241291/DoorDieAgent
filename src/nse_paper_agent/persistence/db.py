from __future__ import annotations
import sqlite3,json,shutil
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION=2
SCHEMA='''
CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS account_snapshots(id INTEGER PRIMARY KEY,ts_utc TEXT NOT NULL,ts_ist TEXT NOT NULL,trading_date TEXT NOT NULL DEFAULT '',is_eod INTEGER NOT NULL DEFAULT 0,cash REAL NOT NULL,equity REAL NOT NULL,gross REAL NOT NULL,daily_start_equity REAL NOT NULL,drawdown5 REAL NOT NULL);
CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,qty INTEGER NOT NULL,entry_price REAL NOT NULL,stop_price REAL NOT NULL,target_price REAL NOT NULL,entry_fee REAL NOT NULL,strategy_version TEXT NOT NULL,entry_ts_utc TEXT NOT NULL,last_mark REAL NOT NULL);
CREATE TABLE IF NOT EXISTS simulated_fills(id INTEGER PRIMARY KEY AUTOINCREMENT,idempotency_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,qty INTEGER NOT NULL,price REAL NOT NULL,fee REAL NOT NULL,ts_utc TEXT NOT NULL,strategy_version TEXT NOT NULL,slippage_estimate REAL NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS closed_trades(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,qty INTEGER NOT NULL,entry_price REAL NOT NULL,exit_price REAL NOT NULL,entry_fee REAL NOT NULL,exit_fee REAL NOT NULL,gross_pnl REAL NOT NULL,net_pnl REAL NOT NULL,entry_ts_utc TEXT NOT NULL,exit_ts_utc TEXT NOT NULL,strategy_version TEXT NOT NULL,exit_reason TEXT NOT NULL,holding_seconds INTEGER NOT NULL,mae REAL,mfe REAL);
CREATE TABLE IF NOT EXISTS strategy_versions(version TEXT PRIMARY KEY,tier TEXT NOT NULL,definition_json TEXT NOT NULL,validation_json TEXT,active INTEGER NOT NULL,effective_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS strategy_metrics(id INTEGER PRIMARY KEY AUTOINCREMENT,version TEXT NOT NULL,regime TEXT,computed_ts_utc TEXT NOT NULL,metrics_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,idempotency_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,bar_end_utc TEXT NOT NULL,strategy_version TEXT NOT NULL,eligible INTEGER NOT NULL,reason TEXT NOT NULL,score REAL,metadata_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS market_bars(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,start_utc TEXT NOT NULL,end_utc TEXT NOT NULL,open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,close REAL NOT NULL,volume REAL NOT NULL,UNIQUE(symbol,end_utc));
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,ts_utc TEXT NOT NULL,bid REAL,ask REAL,last REAL,volume REAL NOT NULL);
CREATE TABLE IF NOT EXISTS market_regimes(id INTEGER PRIMARY KEY AUTOINCREMENT,ts_utc TEXT NOT NULL,regime TEXT NOT NULL,metrics_json TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sentiment_observations(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,ts_utc TEXT NOT NULL,score REAL,confidence REAL NOT NULL,source TEXT NOT NULL,fresh_until_utc TEXT,components_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS risk_events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts_utc TEXT NOT NULL,event_type TEXT NOT NULL,allowed INTEGER,reason TEXT NOT NULL,details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS system_events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts_utc TEXT NOT NULL,event_type TEXT NOT NULL,details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS data_health_events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts_utc TEXT NOT NULL,healthy INTEGER NOT NULL,reason TEXT NOT NULL,details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cooldowns(symbol TEXT PRIMARY KEY,until_utc TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON account_snapshots(ts_utc);
CREATE INDEX IF NOT EXISTS idx_fills_ts ON simulated_fills(ts_utc);
CREATE INDEX IF NOT EXISTS idx_closed_exit ON closed_trades(exit_ts_utc);
'''
class Database:
    def __init__(self,path:str):
        self.path=path; Path(path).parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(path,isolation_level=None,check_same_thread=False); self.conn.row_factory=sqlite3.Row; self._in_transaction=False
        self.conn.execute("PRAGMA journal_mode=WAL"); self.conn.execute("PRAGMA foreign_keys=ON"); self.conn.execute("PRAGMA synchronous=FULL")
    def initialize(self):
        with self.conn:
            self.conn.executescript(SCHEMA)

            version_row = self.conn.execute(
                "SELECT version FROM schema_meta ORDER BY version DESC LIMIT 1"
            ).fetchone()

            if version_row is None:
                self.conn.execute(
                    "INSERT INTO schema_meta(version) VALUES(?)",
                    (SCHEMA_VERSION,),
                )
            else:
                current = int(version_row["version"])

                if current < 2:
                    columns = {
                        row["name"]
                        for row in self.conn.execute(
                            "PRAGMA table_info(account_snapshots)"
                        ).fetchall()
                    }

                    if "trading_date" not in columns:
                        self.conn.execute(
                            "ALTER TABLE account_snapshots "
                            "ADD COLUMN trading_date TEXT NOT NULL DEFAULT ''"
                        )

                    if "is_eod" not in columns:
                        self.conn.execute(
                            "ALTER TABLE account_snapshots "
                            "ADD COLUMN is_eod INTEGER NOT NULL DEFAULT 0"
                        )

                    # Backfill the NSE trading date and normalize the IST
                    # representation of legacy UTC timestamps. Existing
                    # historical rows remain is_eod=0 deliberately: we must
                    # never fabricate completed EOD marks from old data.
                    rows = self.conn.execute(
                        "SELECT id, ts_utc FROM account_snapshots"
                    ).fetchall()

                    for row in rows:
                        raw = row["ts_utc"]
                        dt = datetime.fromisoformat(raw)

                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)

                        ist = dt.astimezone(IST)

                        self.conn.execute(
                            """
                            UPDATE account_snapshots
                            SET trading_date=?, ts_ist=?
                            WHERE id=?
                            """,
                            (
                                ist.date().isoformat(),
                                ist.isoformat(),
                                row["id"],
                            ),
                        )

                    self.conn.execute(
                        "UPDATE schema_meta SET version=?",
                        (SCHEMA_VERSION,),
                    )

            # This constraint must exist for BOTH newly-created databases
            # and databases migrated from schema version 1.
            #
            # Without it, INSERT OR IGNORE cannot guarantee that only one
            # completed EOD mark exists for an NSE trading date.
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_account_snapshots_eod_date "
                "ON account_snapshots(trading_date) "
                "WHERE is_eod=1 AND trading_date <> ''"
            )
    @contextmanager
    def transaction(self):
        if self._in_transaction: raise RuntimeError("nested database transaction is not supported")
        self.conn.execute("BEGIN IMMEDIATE"); self._in_transaction=True
        try: yield self.conn; self.conn.execute("COMMIT")
        except Exception: self.conn.execute("ROLLBACK"); raise
        finally: self._in_transaction=False
    def tx(self): return self.transaction()
    def close(self): self.conn.close()
    def set_state(self,key,value):
        self.conn.execute("INSERT INTO kv_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,json.dumps(value,default=str)))
        if not self._in_transaction: self.conn.commit()
    def get_state(self,key,default=None):
        row=self.conn.execute("SELECT value FROM kv_state WHERE key=?",(key,)).fetchone(); return default if not row else json.loads(row[0])
    def backup(self,dest_dir):
        Path(dest_dir).mkdir(parents=True,exist_ok=True); ts=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); dest=Path(dest_dir)/f"state-{ts}.sqlite3"; self.conn.execute("PRAGMA wal_checkpoint(FULL)"); shutil.copy2(self.path,dest); return str(dest)
