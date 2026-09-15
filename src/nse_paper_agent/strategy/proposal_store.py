from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from nse_paper_agent.strategy.proposal import StrategyProposal


class StrategyProposalStore:
    """Durable store for bounded strategy proposals.

    Proposal persistence is append-only by proposal id. The store does not
    execute, mutate, approve, or activate proposals.
    """

    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_proposals(
                proposal_id TEXT PRIMARY KEY,
                base_version TEXT NOT NULL,
                proposed_version TEXT NOT NULL,
                finding_code TEXT NOT NULL,
                severity TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                rationale TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                allowed_change_scope TEXT NOT NULL,
                forbidden_change_scope_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_strategy_proposals_version "
            "ON strategy_proposals(base_version, created_at_utc)"
        )

    def save(self, proposal: StrategyProposal, created_at: datetime | None = None) -> bool:
        created_at = created_at or datetime.now(timezone.utc)
        cursor = self.db.conn.execute(
            """
            INSERT OR IGNORE INTO strategy_proposals(
                proposal_id, base_version, proposed_version, finding_code,
                severity, hypothesis, rationale, evidence_json,
                allowed_change_scope, forbidden_change_scope_json, status,
                created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                proposal.proposal_id,
                proposal.base_version,
                proposal.proposed_version,
                proposal.finding_code,
                proposal.severity,
                proposal.hypothesis,
                proposal.rationale,
                json.dumps(dict(proposal.evidence), sort_keys=True),
                proposal.allowed_change_scope,
                json.dumps(list(proposal.forbidden_change_scope), sort_keys=True),
                proposal.status,
                created_at.astimezone(timezone.utc).isoformat(),
            ),
        )
        return cursor.rowcount == 1

    def save_many(self, proposals: tuple[StrategyProposal, ...], created_at: datetime | None = None) -> int:
        created_at = created_at or datetime.now(timezone.utc)
        created = 0
        with self.db.transaction():
            for proposal in proposals:
                if self.save(proposal, created_at=created_at):
                    created += 1
        return created

    def get(self, proposal_id: str) -> StrategyProposal | None:
        row = self.db.conn.execute(
            "SELECT * FROM strategy_proposals WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return StrategyProposal(
            proposal_id=row["proposal_id"],
            base_version=row["base_version"],
            proposed_version=row["proposed_version"],
            finding_code=row["finding_code"],
            severity=row["severity"],
            hypothesis=row["hypothesis"],
            rationale=row["rationale"],
            evidence=json.loads(row["evidence_json"]),
            allowed_change_scope=row["allowed_change_scope"],
            forbidden_change_scope=tuple(json.loads(row["forbidden_change_scope_json"])),
            status=row["status"],
        )

    def list_for_base_version(self, base_version: str) -> tuple[StrategyProposal, ...]:
        rows = self.db.conn.execute(
            "SELECT proposal_id FROM strategy_proposals "
            "WHERE base_version=? ORDER BY created_at_utc, proposal_id",
            (base_version,),
        ).fetchall()
        return tuple(self.get(row["proposal_id"]) for row in rows if self.get(row["proposal_id"]) is not None)
