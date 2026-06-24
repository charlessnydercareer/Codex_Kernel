from __future__ import annotations

import sys
import unittest
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))
sys.path.insert(0, str(WORKER_ROOT / "src"))

from algebra_gate import (  # noqa: E402
    AlgebraGateViolation,
    build_approval_hash,
    finalize_mutation,
    proposal_material,
    verify_approval_payload,
)


AUTHORIZED_NODES = [
    "nexus-alpha",
    "nexus-beta",
    "nexus-delta",
    "nexus-gamma",
]


def mutation_for(new_value: object = 1) -> dict:
    return finalize_mutation(
        {
            "proposal_version": 1,
            "refname": "refs/heads/main",
            "oldrev": "1" * 40,
            "newrev": "2" * 40,
            "changed_paths": ["src/state.json"],
            "protected_path": "src/state.json",
            "mutation_type": "update",
            "parameter": "cascade_depth",
            "old_value": 0,
            "new_value": new_value,
            "diff_hash": "sha256:" + "3" * 64,
        }
    )


def approval_for(
    mutation: dict,
    *,
    authorized_nodes: list[str] | None = None,
    yes_votes: list[str] | None = None,
    no_votes: list[str] | None = None,
) -> dict:
    declared_nodes = authorized_nodes or list(AUTHORIZED_NODES)
    yes = yes_votes or [
        "nexus-alpha",
        "nexus-beta",
        "nexus-delta",
    ]
    no = no_votes or []
    approval = {
        "event_type": "CONSENSUS_APPROVAL",
        **proposal_material(mutation),
        "proposal_hash": mutation["proposal_hash"],
        "approved_at": "2026-06-24T12:00:00Z",
        "quorum": {
            "threshold": (2 * len(AUTHORIZED_NODES)) // 3 + 1,
            "authorized_nodes": declared_nodes,
            "yes_votes": yes,
            "no_votes": no,
            "yes_count": len(yes),
            "no_count": len(no),
        },
    }
    approval["approval_hash"] = build_approval_hash(approval)
    return approval


class AlgebraGateTests(unittest.TestCase):
    def test_accepts_exact_mutation_and_quorum_proof(self) -> None:
        mutation = mutation_for(1)
        verify_approval_payload(
            approval_for(mutation),
            mutation,
            AUTHORIZED_NODES,
        )

    def test_rejects_approval_for_different_mutation_value(self) -> None:
        expected_mutation = mutation_for(2)
        wrong_approval = approval_for(mutation_for(1))

        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "proposal_hash / mutation payload mismatch",
        ):
            verify_approval_payload(
                wrong_approval,
                expected_mutation,
                AUTHORIZED_NODES,
            )

    def test_rejects_duplicate_voter_ids(self) -> None:
        mutation = mutation_for(1)
        approval = approval_for(
            mutation,
            yes_votes=[
                "nexus-alpha",
                "nexus-alpha",
                "nexus-beta",
            ],
        )

        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "contains duplicates",
        ):
            verify_approval_payload(approval, mutation, AUTHORIZED_NODES)

    def test_rejects_unauthorized_voter(self) -> None:
        mutation = mutation_for(1)
        approval = approval_for(
            mutation,
            yes_votes=[
                "nexus-alpha",
                "nexus-beta",
                "rogue-node",
            ],
        )

        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "unauthorized voter IDs",
        ):
            verify_approval_payload(approval, mutation, AUTHORIZED_NODES)

    def test_rejects_tampered_approval_hash(self) -> None:
        mutation = mutation_for(1)
        approval = approval_for(mutation)
        approval["approved_at"] = "2026-06-24T12:01:00Z"

        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "does not match approval proof",
        ):
            verify_approval_payload(approval, mutation, AUTHORIZED_NODES)


if __name__ == "__main__":
    unittest.main()
