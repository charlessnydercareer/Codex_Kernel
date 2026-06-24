#!/usr/bin/env python3
"""
Postgres-backed Consensus Store

Replaces:
    var/consensus/approved/*.json
    var/consensus/events.jsonl

With:
    consensus_proposals
    consensus_votes
    consensus_approvals
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import psycopg
from psycopg.types.json import Jsonb

from memory import KernelContractViolation, MemoryLedgerContractVerifier


class PostgresConsensusStore:
    def __init__(self, conn_str: str | None = None, verify_contract: bool = True) -> None:
        self.conn_str = conn_str or os.getenv(
            "CODEX_DATABASE_URL",
            "dbname=codex_nexus user=nexus_admin host=localhost",
        )

        if verify_contract:
            MemoryLedgerContractVerifier(self.conn_str).verify()

    def record_proposal(self, proposal: Dict[str, Any]) -> None:
        required = {"change_id", "proposal_hash", "proposer"}
        missing = required - set(proposal)
        if missing:
            raise KernelContractViolation(f"Proposal missing fields: {sorted(missing)}")

        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO consensus_proposals (change_id, proposal_hash, proposer, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (change_id) DO NOTHING
                    """,
                    (
                        proposal["change_id"],
                        proposal["proposal_hash"],
                        proposal["proposer"],
                        Jsonb(proposal),
                    ),
                )
            conn.commit()

    def record_vote(self, vote: Dict[str, Any]) -> None:
        required = {"change_id", "voter_id", "proposal_hash", "vote"}
        missing = required - set(vote)
        if missing:
            raise KernelContractViolation(f"Vote missing fields: {sorted(missing)}")

        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO consensus_votes (change_id, voter_id, proposal_hash, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (change_id, voter_id) DO UPDATE
                    SET proposal_hash = EXCLUDED.proposal_hash, payload = EXCLUDED.payload
                    """,
                    (
                        vote["change_id"],
                        vote["voter_id"],
                        vote["proposal_hash"],
                        Jsonb(vote),
                    ),
                )
            conn.commit()

    def has_approval(self, change_id: str) -> bool:
        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM consensus_approvals WHERE change_id = %s
                    )
                    """,
                    (change_id,),
                )
                return bool(cur.fetchone()[0])

    def read_approval(self, change_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM consensus_approvals WHERE change_id = %s
                    """,
                    (change_id,),
                )
                row = cur.fetchone()

        if row is None:
            raise FileNotFoundError(f"No consensus approval for change_id={change_id}")

        payload = row[0]
        if not isinstance(payload, dict):
            raise KernelContractViolation(
                f"Consensus approval payload is not object: {change_id}"
            )

        return payload

    def write_approval(self, event: Dict[str, Any]) -> None:
        required = {
            "change_id",
            "proposal_hash",
            "approval_hash",
        }
        missing = required - set(event)
        if missing:
            raise KernelContractViolation(f"Approval missing fields: {sorted(missing)}")

        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO consensus_approvals (change_id, proposal_hash, approval_hash, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (change_id) DO NOTHING
                    """,
                    (
                        event["change_id"],
                        event["proposal_hash"],
                        event["approval_hash"],
                        Jsonb(event),
                    ),
                )
            conn.commit()
