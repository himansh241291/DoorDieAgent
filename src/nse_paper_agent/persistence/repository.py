from __future__ import annotations
import json
from datetime import timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from nse_paper_agent.domain.models import Position
from .db import Database
IST=ZoneInfo("Asia/Kolkata")

def iso(ts): return ts.astimezone(timezone.utc).isoformat()

def iso_ist(ts): return ts.astimezone(IST).isoformat()
class Repository:
    def __init__(self,db:Database): self.db=db
    def cash(self): return float(self.db.get_state("cash",50000.0))
    def set_cash(self,v): self.db.set_state("cash",v)
    def positions(self):
        rows=self.db.conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
        return {r["symbol"]:Position(r["symbol"],r["qty"],Decimal(str(r["entry_price"])),Decimal(str(r["stop_price"])),Decimal(str(r["target_price"])),Decimal(str(r["entry_fee"])),r["strategy_version"],__import__('datetime').datetime.fromisoformat(r["entry_ts_utc"]),Decimal(str(r["last_mark"]))) for r in rows}
    def save_position(self,p): self.db.conn.execute("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?,?,?,?)",(p.symbol,p.qty,float(p.entry_price),float(p.stop_price),float(p.target_price),float(p.entry_fee),p.strategy_version,iso(p.entry_ts),float(p.last_mark)))
    def delete_position(self,symbol): self.db.conn.execute("DELETE FROM positions WHERE symbol=?",(symbol,))
    def insert_fill(self,f): self.db.conn.execute("INSERT INTO simulated_fills(idempotency_key,symbol,side,qty,price,fee,ts_utc,strategy_version,slippage_estimate,reason) VALUES(?,?,?,?,?,?,?,?,?,?)",(f.idempotency_key,f.symbol,f.side.value,f.qty,float(f.price),float(f.fee),iso(f.ts),f.strategy_version,float(f.slippage_estimate),f.reason))
    def fill_exists(self,key): return self.db.conn.execute("SELECT 1 FROM simulated_fills WHERE idempotency_key=?",(key,)).fetchone() is not None
    def close_trade(self,**kw): self.db.conn.execute("INSERT INTO closed_trades(symbol,qty,entry_price,exit_price,entry_fee,exit_fee,gross_pnl,net_pnl,entry_ts_utc,exit_ts_utc,strategy_version,exit_reason,holding_seconds,mae,mfe) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",kw["values"])
    def record_signal(self,s,key): self.db.conn.execute("INSERT OR IGNORE INTO signals(idempotency_key,symbol,bar_end_utc,strategy_version,eligible,reason,score,metadata_json) VALUES(?,?,?,?,?,?,?,?)",(key,s.symbol,iso(s.bar_end),s.strategy_version,int(s.eligible),s.reason,s.score,json.dumps(s.metadata,default=str)))
    def record_bar(self,b): self.db.conn.execute("INSERT OR IGNORE INTO market_bars(symbol,start_utc,end_utc,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?,?)",(b.symbol,iso(b.start),iso(b.end),float(b.open),float(b.high),float(b.low),float(b.close),float(b.volume)))

    def market_bars(self, symbol):
        from datetime import datetime
        from nse_paper_agent.domain.models import Bar

        rows = self.db.conn.execute(
            """
            SELECT symbol,start_utc,end_utc,open,high,low,close,volume
            FROM market_bars
            WHERE symbol=?
            ORDER BY end_utc
            """,
            (symbol,),
        ).fetchall()

        return [
            Bar(
                symbol=row["symbol"],
                start=datetime.fromisoformat(row["start_utc"]),
                end=datetime.fromisoformat(row["end_utc"]),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
            )
            for row in rows
        ]
    def record_quote(self,q): self.db.conn.execute("INSERT INTO quotes(symbol,ts_utc,bid,ask,last,volume) VALUES(?,?,?,?,?,?)",(q.symbol,iso(q.ts),float(q.bid) if q.bid is not None else None,float(q.ask) if q.ask is not None else None,float(q.last) if q.last is not None else None,float(q.volume)))
    def record_regime(self,r): self.db.conn.execute("INSERT INTO market_regimes(ts_utc,regime,metrics_json,reason) VALUES(?,?,?,?)",(iso(r.ts),r.regime.value,json.dumps(r.metrics),r.reason))
    def record_sentiment(self,s): self.db.conn.execute("INSERT INTO sentiment_observations(symbol,ts_utc,score,confidence,source,fresh_until_utc,components_json) VALUES(?,?,?,?,?,?,?)",(s.symbol,iso(s.ts),s.score,s.confidence,s.source,iso(s.fresh_until) if s.fresh_until else None,json.dumps(s.components)))
    def record_risk(self,ts,event_type,allowed,reason,details): self.db.conn.execute("INSERT INTO risk_events(ts_utc,event_type,allowed,reason,details_json) VALUES(?,?,?,?,?)",(iso(ts),event_type,int(allowed) if allowed is not None else None,reason,json.dumps(details,default=str)))
    def record_system(self,ts,event_type,details): self.db.conn.execute("INSERT INTO system_events(ts_utc,event_type,details_json) VALUES(?,?,?)",(iso(ts),event_type,json.dumps(details,default=str)))
    def record_data_health(self,ts,healthy,reason,details): self.db.conn.execute("INSERT INTO data_health_events(ts_utc,healthy,reason,details_json) VALUES(?,?,?,?)",(iso(ts),int(healthy),reason,json.dumps(details,default=str)))
    def cooldown(self,symbol,until,reason): self.db.conn.execute("INSERT OR REPLACE INTO cooldowns(symbol,until_utc,reason) VALUES(?,?,?)",(symbol,iso(until),reason))
    def in_cooldown(self,symbol,now):
        r=self.db.conn.execute("SELECT until_utc FROM cooldowns WHERE symbol=?",(symbol,)).fetchone(); return bool(r and __import__('datetime').datetime.fromisoformat(r[0])>now)

    def get_checkpoint(self,symbol):
        return self.db.get_state(f"checkpoint:{symbol}")

    def set_checkpoint(self,symbol,bar_end):
        self.db.set_state(f"checkpoint:{symbol}",iso(bar_end))

    def record_account_snapshot_and_checkpoint(
        self,
        symbol,
        bar_end,
        cash,
        equity,
        gross,
        daily_start_equity,
        drawdown5,
        trading_date=None,
        is_eod=False,
    ):
        checkpoint_key = f"checkpoint:{symbol}"

        if trading_date is None:
            trading_date = bar_end.astimezone(IST).date().isoformat()

        with self.db.transaction():
            self.db.conn.execute(
                """
                INSERT INTO account_snapshots
                (
                    ts_utc,
                    ts_ist,
                    trading_date,
                    is_eod,
                    cash,
                    equity,
                    gross,
                    daily_start_equity,
                    drawdown5
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iso(bar_end),
                    iso_ist(bar_end),
                    str(trading_date),
                    int(is_eod),
                    float(cash),
                    float(equity),
                    float(gross),
                    float(daily_start_equity),
                    float(drawdown5),
                ),
            )

            self.db.set_state(checkpoint_key, iso(bar_end))

    def record_eod_snapshot(
        self,
        trading_date,
        ts,
        cash,
        equity,
        gross,
        daily_start_equity,
        drawdown5,
    ):
        """
        Persist exactly one completed EOD equity mark per trading date.

        The partial unique index on (trading_date) for is_eod=1 makes
        repeated EOD processing idempotent at the database layer.
        """
        with self.db.transaction():
            cursor = self.db.conn.execute(
                """
                INSERT OR IGNORE INTO account_snapshots
                (
                    ts_utc,
                    ts_ist,
                    trading_date,
                    is_eod,
                    cash,
                    equity,
                    gross,
                    daily_start_equity,
                    drawdown5
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    iso(ts),
                    iso_ist(ts),
                    str(trading_date),
                    float(cash),
                    float(equity),
                    float(gross),
                    float(daily_start_equity),
                    float(drawdown5),
                ),
            )

            # Only the first successful EOD insertion can advance the
            # completed-day state. Repeated processing is therefore
            # idempotent and cannot overwrite the authoritative mark.
            if cursor.rowcount == 1:
                self.db.set_state(
                    "last_eod_trading_date",
                    str(trading_date),
                )
                self.db.set_state(
                    "last_eod_equity",
                    float(equity),
                )
                self.db.set_state(
                    "last_eod_ts_utc",
                    iso(ts),
                )

                return True

            return False

    def eod_marks(self, limit=5):
        rows = self.db.conn.execute(
            """
            SELECT trading_date, ts_utc, ts_ist, equity, daily_start_equity, drawdown5
            FROM account_snapshots
            WHERE is_eod=1 AND trading_date <> ''
            ORDER BY trading_date DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        return [dict(row) for row in rows]
