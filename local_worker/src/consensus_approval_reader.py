#!/usr/bin/env python3
"""
Consensus Approval Reader

Role:
    Read-only boundary between AlgebraGate and the Postgres semantic ledger.
    AlgebraGate calls require_approval() before accepting any protected mutation.
    This module never writes to the ledger.

Authority chain:
    consensus_transport_bridge.py  -> writes consensus_approvals
    consensus_approval_reader.py   -> reads and verifies approval artifact
    algebra_gate.py                -> enforces or rejects topology mutation
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

import psycopg

APPROVAL_EVENT_TYPE = "CONSENSUS_APPROVAL"
APPROVAL_HASH_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class ConsensusApprovalViolation(RuntimeError):
    pass


class ConsensusApprovalReader:
    """
    Queries consensus_approvals and verifies the approval artifact.

    Checks:
    - Row exists for change_id
    - payload.event_type == "CONSENSUS_APPROVAL"
    - payload.proposal_hash matches the caller-supplied proposal_hash
    - approval_hash column is present and matches sha256: pattern
    """

    def __init__(self, conn_str: Optional[str] = None) -> None:
        self.conn_str = conn_str or os.getenv(
            "CODEX_DATABASE_URL",
            "dbname=codex_nexus user=nexus_admin host=localhost",
        )

    def require_approval(self, change_id: str, proposal_hash: str) -> Dict[str, Any]:
        """
        Return the approval artifact if change_id is approved for proposal_hash.
        Raise ConsensusApprovalViolation otherwise.
        """
        if not change_id or not isinstance(change_id, str):
            raise ConsensusApprovalViolation("change_id must be a non-empty string")
        if not proposal_hash or not isinstance(proposal_hash, str):
            raise ConsensusApprovalViolation("proposal_hash must be a non-empty string")

        try:
            with psycopg.connect(self.conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT approval_hash, payload
                        FROM consensus_approvals
                        WHERE change_id = %s
                        """,
                        (change_id,),
                    )
                    row = cur.fetchone()
        except psycopg.Error as exc:
            raise ConsensusApprovalViolation(
                f"Ledger query failed for change_id={change_id}: {exc}"
            ) from exc

        if row is None:
            raise ConsensusApprovalViolation(
                f"No consensus approval found for change_id={change_id}"
            )

        approval_hash, payload = row

        if not isinstance(payload, dict):
            raise ConsensusApprovalViolation(
                f"Approval payload is not an object for change_id={change_id}"
            )

        event_type = payload.get("event_type")
        if event_type != APPROVAL_EVENT_TYPE:
            raise ConsensusApprovalViolation(
                f"Approval event_type mismatch for change_id={change_id}: "
                f"expected={APPROVAL_EVENT_TYPE} got={event_type}"
            )

        stored_proposal_hash = payload.get("proposal_hash")
        if stored_proposal_hash != proposal_hash:
            raise ConsensusApprovalViolation(
                f"Proposal hash mismatch for change_id={change_id}: "
                f"expected={proposal_hash} stored={stored_proposal_hash}"
            )

        if not approval_hash or not APPROVAL_HASH_PATTERN.match(approval_hash):
            raise ConsensusApprovalViolation(
                f"Approval artifact has invalid approval_hash for change_id={change_id}"
            )

        return payload

    def check_approval(self, change_id: str, proposal_hash: str) -> bool:
        """Non-raising variant. Returns True if approved, False otherwise."""
        try:
            self.require_approval(change_id, proposal_hash)
            return True
        except ConsensusApprovalViolation:
            return False
