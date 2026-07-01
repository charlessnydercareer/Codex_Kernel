#!/usr/bin/env python3
"""
Consensus Approval Reader

Role:
    Read-only boundary between AlgebraGate and the Postgres semantic ledger.
    AlgebraGate calls require_approval_by_proposal_hash() before accepting
    any protected mutation. This module never writes to the ledger.

Authority chain:
    consensus_transport_bridge.py  -> writes consensus_approvals
    consensus_approval_reader.py   -> reads and verifies approval artifact
    algebra_gate.py                -> enforces or rejects topology mutation

Everything is keyed by the canonical proposal_hash of a Git-derived
mutation. There is no change_id read path.
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
    Queries consensus_proposals and consensus_approvals by proposal_hash.

    Read paths:
    - require_approval_by_proposal_hash: returns the single approval bound
      to an exact canonical proposal hash (raises on any mismatch)
    - check_approval: non-raising boolean variant
    """

    def __init__(self, conn_str: Optional[str] = None) -> None:
        self.conn_str = conn_str or os.getenv(
            "CODEX_DATABASE_URL",
            "dbname=codex_nexus user=nexus_admin host=localhost",
        )

    def require_approval_by_proposal_hash(
        self,
        proposal_hash: str,
    ) -> Dict[str, Any]:
        """
        Return the approval artifact bound to an exact canonical proposal hash.

        The database column and JSON payload must agree, and a matching
        proposal row must exist. AlgebraGate performs the full mutation,
        approval-hash, and quorum verification.
        """
        if not proposal_hash or not isinstance(proposal_hash, str):
            raise ConsensusApprovalViolation(
                "proposal_hash must be a non-empty string"
            )

        try:
            with psycopg.connect(self.conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT a.approval_hash, a.payload
                        FROM consensus_approvals AS a
                        JOIN consensus_proposals AS p
                          ON p.proposal_hash = a.proposal_hash
                        WHERE a.proposal_hash = %s
                        ORDER BY a.id
                        LIMIT 2
                        """,
                        (proposal_hash,),
                    )
                    rows = cur.fetchall()
        except psycopg.Error as exc:
            raise ConsensusApprovalViolation(
                "Ledger query failed while reading proposal approval."
            ) from exc

        if not rows:
            raise ConsensusApprovalViolation(
                f"No consensus approval found for proposal_hash={proposal_hash}"
            )
        if len(rows) != 1:
            raise ConsensusApprovalViolation(
                "Multiple consensus approvals found for one proposal_hash."
            )

        approval_hash, payload = rows[0]
        if not isinstance(payload, dict):
            raise ConsensusApprovalViolation(
                "Consensus approval payload is not an object."
            )
        if payload.get("event_type") != APPROVAL_EVENT_TYPE:
            raise ConsensusApprovalViolation(
                "Consensus approval has invalid event_type."
            )
        if payload.get("proposal_hash") != proposal_hash:
            raise ConsensusApprovalViolation(
                "Consensus approval proposal_hash does not match its ledger row."
            )
        if payload.get("approval_hash") != approval_hash:
            raise ConsensusApprovalViolation(
                "Consensus approval hash does not match its ledger row."
            )
        if not approval_hash or not APPROVAL_HASH_PATTERN.fullmatch(approval_hash):
            raise ConsensusApprovalViolation(
                "Consensus approval hash is malformed."
            )

        return payload

    def check_approval(self, proposal_hash: str) -> bool:
        """Non-raising variant. Returns True if approved, False otherwise."""
        try:
            self.require_approval_by_proposal_hash(proposal_hash)
            return True
        except ConsensusApprovalViolation:
            return False
