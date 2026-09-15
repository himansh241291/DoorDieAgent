from __future__ import annotations

import json
from datetime import datetime, timezone

from nse_paper_agent.research.validation_plan import ValidationPlan


class ValidationPlanStore:
    """Append-only persistence for validation plans."""

    def __init__(self, db):
        self.db = db
        self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_validation_plans(
                proposal_id TEXT PRIMARY KEY,
                base_version TEXT NOT NULL,
                challenger_version TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                allowed_change_scope TEXT NOT NULL,
                forbidden_change_scope_json TEXT NOT NULL,
                risk_config_hash TEXT NOT NULL,
                data_window TEXT NOT NULL,
                split_policy TEXT NOT NULL,
                min_trading_days INTEGER NOT NULL,
                validation_status TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )

    def save(self, plan: ValidationPlan, created_at: datetime | None = None) -> bool:
        created_at = created_at or datetime.now(timezone.utc)
        cursor = self.db.conn.execute(
            """
            INSERT OR IGNORE INTO strategy_validation_plans(
                proposal_id, base_version, challenger_version, hypothesis,
                allowed_change_scope, forbidden_change_scope_json,
                risk_config_hash, data_window, split_policy, min_trading_days,
                validation_status, created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                plan.proposal_id,
                plan.base_version,
                plan.challenger_version,
                plan.hypothesis,
                plan.allowed_change_scope,
                json.dumps(list(plan.forbidden_change_scope), sort_keys=True),
                plan.risk_config_hash,
                plan.data_window,
                plan.split_policy,
                plan.min_trading_days,
                plan.validation_status,
                created_at.astimezone(timezone.utc).isoformat(),
            ),
        )
        return cursor.rowcount == 1

    def get(self, proposal_id: str) -> ValidationPlan | None:
        row = self.db.conn.execute(
            "SELECT * FROM strategy_validation_plans WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return ValidationPlan(
            proposal_id=row["proposal_id"],
            base_version=row["base_version"],
            challenger_version=row["challenger_version"],
            hypothesis=row["hypothesis"],
            allowed_change_scope=row["allowed_change_scope"],
            forbidden_change_scope=tuple(json.loads(row["forbidden_change_scope_json"])),
            risk_config_hash=row["risk_config_hash"],
            data_window=row["data_window"],
            split_policy=row["split_policy"],
            min_trading_days=row["min_trading_days"],
            validation_status=row["validation_status"],
        )
