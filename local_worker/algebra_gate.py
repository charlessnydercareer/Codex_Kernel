#!/usr/bin/env python3
"""
Algebra Gate: final enforcement boundary.

Reads durable consensus approvals from Postgres and rejects protected topology
mutations unless the approval is present, hash-bound, and quorum-valid.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.append(str(Path(__file__).resolve().parent / "src"))

from consensus_approval_reader import (
    ConsensusApprovalReader,
    ConsensusApprovalViolation,
)


class AlgebraGateViolation(RuntimeError):
    pass


PROTECTED_PARAMETERS = {
    "cascade_depth",
    "max_depth",
    "max_cascade_depth",
    "schema_version",
    "algebra_policy_version",
}


def is_protected_parameter(parameter: str) -> bool:
    return parameter in PROTECTED_PARAMETERS


def requires_consensus(old_state: dict, new_state: dict) -> bool:
    for key in PROTECTED_PARAMETERS:
        if old_state.get(key) != new_state.get(key):
            return True
    return False


def verify_approval_payload(
    approval: Dict[str, Any],
    change_id: str,
    proposal_hash: str,
) -> None:
    if approval.get("event_type") != "CONSENSUS_APPROVAL":
        raise AlgebraGateViolation("Approval payload has invalid event_type.")

    if approval.get("change_id") != change_id:
        raise AlgebraGateViolation("Approval change_id mismatch.")

    if approval.get("proposal_hash") != proposal_hash:
        raise AlgebraGateViolation("Approval proposal_hash mismatch.")

    approval_hash = approval.get("approval_hash")
    if not isinstance(approval_hash, str) or not approval_hash.startswith("sha256:"):
        raise AlgebraGateViolation("Approval hash missing or malformed.")

    quorum = approval.get("quorum")
    if not isinstance(quorum, dict):
        raise AlgebraGateViolation("Approval quorum block missing.")

    threshold = quorum.get("threshold")
    yes_count = quorum.get("yes_count")
    yes_votes = quorum.get("yes_votes")

    if not isinstance(threshold, int) or threshold < 1:
        raise AlgebraGateViolation("Approval quorum threshold invalid.")
    if not isinstance(yes_count, int):
        raise AlgebraGateViolation("Approval yes_count invalid.")
    if not isinstance(yes_votes, list):
        raise AlgebraGateViolation("Approval yes_votes invalid.")

    if yes_count < threshold:
        raise AlgebraGateViolation(
            f"Approval quorum not satisfied: yes_count={yes_count}, threshold={threshold}"
        )


def require_consensus_approval(
    change_id: str,
    proposal_hash: str,
) -> Dict[str, Any]:
    reader = ConsensusApprovalReader()

    if not reader.verify_proposal_hash(change_id, proposal_hash):
        raise AlgebraGateViolation(
            f"Rejecting {change_id}: proposal hash not found or mismatched."
        )

    approval = reader.get_approval(change_id)
    if not approval:
        raise AlgebraGateViolation(
            f"Rejecting {change_id}: no approved consensus in ledger."
        )

    verify_approval_payload(
        approval=approval,
        change_id=change_id,
        proposal_hash=proposal_hash,
    )

    return approval


def validate_topology(old_state, new_state, change_id, proposal_hash):
    """Pre-receive hook entry point. Compares old/new state for protected changes."""
    if new_state.get("cascade_depth", 0) > 1:
        print("[ALGEBRA_GATE] REJECTED: Cascade depth blast radius exceeded.")
        return False

    if requires_consensus(old_state, new_state):
        try:
            approval = require_consensus_approval(change_id, proposal_hash)
            print(
                f"[ALGEBRA_GATE] APPROVED: change_id={change_id} "
                f"approval_hash={approval['approval_hash']}"
            )
        except (AlgebraGateViolation, ConsensusApprovalViolation) as exc:
            print(f"[ALGEBRA_GATE] REJECTED: {exc}")
            return False

    return True


def run_gate(change_id: str, proposal_hash: str, parameter: str) -> None:
    """CLI entry point. Validates a single parameter change by name."""
    if not is_protected_parameter(parameter):
        print(
            f"[ALGEBRA_GATE] Non-protected parameter '{parameter}' "
            f"does not require consensus."
        )
        return

    approval = require_consensus_approval(
        change_id=change_id,
        proposal_hash=proposal_hash,
    )

    print(
        "[ALGEBRA_GATE] Consensus proof: PASS "
        f"change_id={change_id} "
        f"parameter={parameter} "
        f"approval_hash={approval.get('approval_hash')}"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "Usage: algebra_gate.py <change_id> <proposal_hash> <parameter>",
            file=sys.stderr,
        )
        return 2

    _, change_id, proposal_hash, parameter = argv

    try:
        run_gate(change_id, proposal_hash, parameter)
        return 0
    except Exception as exc:
        print(f"[ALGEBRA_GATE] Security Invariant Violation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
