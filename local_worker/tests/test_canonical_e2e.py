"""
End-to-end proof for schema unification option (a).

An approval produced OFFLINE — by deriving the canonical mutation from the
exact Git objects of a candidate commit and running it through the
consensus transport bridge — must be accepted by the ONLINE pre-receive
gate, which independently recomputes the same mutation from the incoming
object database.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))
sys.path.insert(0, str(WORKER_ROOT / "src"))

from algebra_gate import require_consensus_approval  # noqa: E402
from consensus_approval_reader import ConsensusApprovalViolation  # noqa: E402
from consensus_transport_bridge import (  # noqa: E402
    ApprovedProposalStore,
    ConsensusBridgeViolation,
    ConsensusTransportBridge,
)
from pre_receive_gate import (  # noqa: E402
    GitObjectRepository,
    PreReceiveGate,
    RefUpdate,
)
from proposal_producer import derive_mutations  # noqa: E402
from test_pre_receive_gate import GitFixture  # noqa: E402


AUTHORIZED_NODES = [
    "nexus-alpha",
    "nexus-beta",
    "nexus-delta",
    "nexus-gamma",
]


class FileStoreApprovalReader:
    """
    Test adapter exposing the ConsensusApprovalReader interface over the
    file-backed ApprovedProposalStore, so the full canonical path runs
    without a live Postgres instance.
    """

    def __init__(self, store: ApprovedProposalStore) -> None:
        self.store = store

    def require_approval_by_proposal_hash(self, proposal_hash: str) -> dict:
        if not self.store.has_approval(proposal_hash):
            raise ConsensusApprovalViolation(
                f"No consensus approval found for proposal_hash={proposal_hash}"
            )
        return self.store.read_approval(proposal_hash)


def proposal_envelope(sender_id: str, mutation: dict) -> dict:
    return {
        "message_type": "CONSENSUS_PROPOSAL",
        "sender_id": sender_id,
        "payload": dict(mutation),
    }


def vote_envelope(sender_id: str, proposal_hash: str, vote: bool = True) -> dict:
    return {
        "message_type": "CONSENSUS_VOTE",
        "sender_id": sender_id,
        "payload": {
            "proposal_hash": proposal_hash,
            "voter_id": sender_id,
            "vote": vote,
        },
    }


class CanonicalEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = GitFixture()
        self.storedir = tempfile.TemporaryDirectory()
        store_root = Path(self.storedir.name)
        self.store = ApprovedProposalStore(
            approved_dir=store_root / "approved",
            events_path=store_root / "events.jsonl",
        )
        self.bridge = ConsensusTransportBridge(
            node_id="nexus-alpha",
            peer_list=["nexus-beta", "nexus-delta", "nexus-gamma"],
            approved_dir=store_root / "approved",
            events_path=store_root / "events.jsonl",
        )
        self.reader = FileStoreApprovalReader(self.store)

    def tearDown(self) -> None:
        self.fixture.close()
        self.storedir.cleanup()

    def online_gate(self) -> PreReceiveGate:
        def checker(mutation: dict) -> None:
            require_consensus_approval(
                mutation,
                reader=self.reader,
                authorized_nodes=AUTHORIZED_NODES,
            )

        return PreReceiveGate(
            GitObjectRepository(self.fixture.bare),
            approval_checker=checker,
        )

    def approve_offline(self, oldrev: str, newrev: str) -> dict:
        """Derive from the LOCAL work repository and collect quorum."""
        mutations = derive_mutations(
            self.fixture.work / ".git",
            refname="refs/heads/main",
            oldrev=oldrev,
            newrev=newrev,
        )
        self.assertEqual(len(mutations), 1)
        mutation = mutations[0]

        approval = self.bridge.handle_envelope(
            proposal_envelope("nexus-alpha", mutation)
        )
        self.assertIsNone(approval)  # 1 of 3 votes: no quorum yet
        approval = self.bridge.handle_envelope(
            vote_envelope("nexus-beta", mutation["proposal_hash"])
        )
        self.assertIsNone(approval)  # 2 of 3 votes: no quorum yet
        approval = self.bridge.handle_envelope(
            vote_envelope("nexus-gamma", mutation["proposal_hash"])
        )
        self.assertIsNotNone(approval)  # 3 of 3: quorum reached
        self.assertEqual(approval["proposal_hash"], mutation["proposal_hash"])
        return mutation

    def test_offline_approval_is_accepted_by_pre_receive_gate(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")

        mutation = self.approve_offline(oldrev, newrev)

        # The offline derivation (work repo) and the online derivation
        # (hub object database) must agree on the exact payload.
        online = self.online_gate()
        online_mutations = online.derive_protected_mutations(
            RefUpdate(oldrev, newrev, "refs/heads/main")
        )
        self.assertEqual(online_mutations, [mutation])

        # The push is accepted only because the offline approval exists.
        online.check_update(RefUpdate(oldrev, newrev, "refs/heads/main"))

    def test_gate_rejects_push_without_offline_approval(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")

        with self.assertRaisesRegex(
            ConsensusApprovalViolation,
            "No consensus approval found",
        ):
            self.online_gate().check_update(
                RefUpdate(oldrev, newrev, "refs/heads/main")
            )

    def test_gate_rejects_different_commit_than_approved(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")
        self.approve_offline(oldrev, newrev)

        # A second candidate commit reaching the same value is NOT covered
        # by the first approval: the hash binds to the exact Git objects.
        self.fixture.write_state(0)
        mid_old, mid_new = self.fixture.commit_and_push("back to zero")
        self.fixture.write_state(1)
        second_old, second_new = self.fixture.commit_and_push("depth one again")
        self.assertEqual(mid_old, newrev)
        self.assertEqual(second_old, mid_new)

        with self.assertRaisesRegex(
            ConsensusApprovalViolation,
            "No consensus approval found",
        ):
            self.online_gate().check_update(
                RefUpdate(second_old, second_new, "refs/heads/main")
            )

    def test_bridge_rejects_non_canonical_proposal(self) -> None:
        with self.assertRaisesRegex(
            ConsensusBridgeViolation,
            "not a canonical mutation",
        ):
            self.bridge.handle_envelope(
                proposal_envelope(
                    "nexus-alpha",
                    {"change_id": "prop-001", "parameter": "max_depth", "value": 2},
                )
            )

    def test_bridge_rejects_tampered_proposal_hash(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")
        [mutation] = derive_mutations(
            self.fixture.work / ".git",
            refname="refs/heads/main",
            oldrev=oldrev,
            newrev=newrev,
        )
        tampered = dict(mutation)
        tampered["new_value"] = 7

        with self.assertRaisesRegex(
            ConsensusBridgeViolation,
            "hash mismatch",
        ):
            self.bridge.handle_envelope(
                proposal_envelope("nexus-alpha", tampered)
            )

    def test_no_quorum_means_no_approval_and_rejected_push(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")
        [mutation] = derive_mutations(
            self.fixture.work / ".git",
            refname="refs/heads/main",
            oldrev=oldrev,
            newrev=newrev,
        )

        self.bridge.handle_envelope(proposal_envelope("nexus-alpha", mutation))
        result = self.bridge.handle_envelope(
            vote_envelope("nexus-beta", mutation["proposal_hash"])
        )
        self.assertIsNone(result)  # 2 of 4 nodes: below 2/3+1 threshold of 3

        with self.assertRaisesRegex(
            ConsensusApprovalViolation,
            "No consensus approval found",
        ):
            self.online_gate().check_update(
                RefUpdate(oldrev, newrev, "refs/heads/main")
            )


if __name__ == "__main__":
    unittest.main()
