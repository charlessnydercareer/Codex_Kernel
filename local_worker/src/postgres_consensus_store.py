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

All rows are keyed by the canonical proposal_hash of a Git-derived
mutation (see canonical_consensus.py). Payload shapes are enforced by
pg_jsonschema CHECK constraints in the migrations.
"""

from __future__ import annotations

import os
from typing import Any, Dict

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
        required = {"proposal_hash", "proposer"}
        missing = required - set(proposal)
        if missing:
            raise KernelContractViolation(f"Proposal missing fields: {sorted(missing)}")

        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO consensus_proposals (proposal_hash, proposer, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (proposal_hash) DO NOTHING
                    """,
                    (
                        proposal["proposal_hash"],
                        proposal["proposer"],
                        Jsonb(proposal),
                    ),
                )
            conn.commit()

    def record_vote(self, vote: Dict[str, Any]) -> None:
        required = {"proposal_hash", "voter_id", "vote"}
        missing = required - set(vote)
        if missing:
            raise KernelContractViolation(f"Vote missing fields: {sorted(missing)}")

        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO consensus_votes (proposal_hash, voter_id, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (proposal_hash, voter_id) DO UPDATE
                    SET payload = EXCLUDED.payload
                    """,
                    (
                        vote["proposal_hash"],
                        vote["voter_id"],
                        Jsonb(vote),
                    ),
                )
            conn.commit()

    def has_approval(self, proposal_hash: str) -> bool:
        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM consensus_approvals WHERE proposal_hash = %s
                    )
                    """,
                    (proposal_hash,),
                )
                return bool(cur.fetchone()[0])

    def read_approval(self, proposal_hash: str) -> Dict[str, Any]:
        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM consensus_approvals WHERE proposal_hash = %s
                    """,
                    (proposal_hash,),
                )
                row = cur.fetchone()

        if row is None:
            raise FileNotFoundError(
                f"No consensus approval for proposal_hash={proposal_hash}"
            )

        payload = row[0]
        if not isinstance(payload, dict):
            raise KernelContractViolation(
                f"Consensus approval payload is not object: {proposal_hash}"
            )

        return payload

    def write_approval(self, event: Dict[str, Any]) -> None:
        required = {
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
                    INSERT INTO consensus_approvals (proposal_hash, approval_hash, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (proposal_hash) DO NOTHING
                    """,
                    (
                        event["proposal_hash"],
                        event["approval_hash"],
                        Jsonb(event),
                    ),
                )
            conn.commit()
