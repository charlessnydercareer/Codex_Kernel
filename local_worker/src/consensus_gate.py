import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

try:
    from canonical_consensus import (
        CanonicalConsensusViolation,
        build_proposal_hash,
    )
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from canonical_consensus import (
        CanonicalConsensusViolation,
        build_proposal_hash,
    )


class ConsensusViolation(RuntimeError):
    pass


@dataclass
class Proposal:
    mutation: Dict[str, Any]
    proposal_hash: str
    proposer: str
    votes: Dict[str, bool] = field(default_factory=dict)


class ConsensusGate:
    """
    Deterministic 2/3 + 1 governance gate over canonical Git-derived
    mutations. Proposals are keyed by their canonical proposal_hash, which
    binds every ballot to the exact incoming Git object identity
    (refname/oldrev/newrev/diff_hash and the protected-field change).
    """

    def __init__(self, node_id: str, peer_list: List[str]):
        self.node_id = node_id
        self.peers = sorted(set(peer_list))
        self.authorized_nodes = sorted(set([self.node_id] + self.peers))
        self.ballot_box: Dict[str, Proposal] = {}

    def quorum_threshold(self) -> int:
        total_nodes = len(self.authorized_nodes)
        # Integer-stable quorum math for 2/3 + 1
        return (2 * total_nodes) // 3 + 1

    def propose_mutation(
        self,
        mutation: Dict[str, Any],
        proposer: str | None = None,
    ) -> str:
        proposer = proposer or self.node_id
        if proposer not in self.authorized_nodes:
            raise ConsensusViolation(f"Unauthorized proposer: {proposer}")

        try:
            expected_hash = build_proposal_hash(mutation)
        except CanonicalConsensusViolation as exc:
            raise ConsensusViolation(
                f"Proposal is not a canonical mutation: {exc}"
            ) from exc

        if mutation.get("proposal_hash") != expected_hash:
            raise ConsensusViolation("Mutation proposal_hash is not canonical.")
        if expected_hash in self.ballot_box:
            raise ConsensusViolation(f"Proposal already exists: {expected_hash}")

        self.ballot_box[expected_hash] = Proposal(
            mutation=dict(mutation),
            proposal_hash=expected_hash,
            proposer=proposer,
            votes={proposer: True},
        )
        print(
            f"[CONSENSUS_GATE] Proposed {mutation['parameter']}="
            f"{mutation['new_value']} proposal_hash={expected_hash}"
        )
        return expected_hash

    def cast_vote(
        self,
        proposal_hash: str,
        voter_id: str,
        vote: bool,
    ) -> bool:
        if voter_id not in self.authorized_nodes:
            raise ConsensusViolation(f"Unauthorized voter: {voter_id}")
        if proposal_hash not in self.ballot_box:
            raise ConsensusViolation(f"Unknown proposal: {proposal_hash}")

        proposal = self.ballot_box[proposal_hash]
        proposal.votes[voter_id] = bool(vote)
        return self.check_consensus(proposal_hash)

    def check_consensus(self, proposal_hash: str) -> bool:
        proposal = self.ballot_box[proposal_hash]
        yes_votes = sum(1 for v in proposal.votes.values() if v is True)
        return yes_votes >= self.quorum_threshold()

    def require_consensus(self, proposal_hash: str) -> Proposal:
        """Returns the Proposal if quorum is reached, raises if not."""
        if proposal_hash not in self.ballot_box:
            raise ConsensusViolation(f"Unknown proposal: {proposal_hash}")
        if not self.check_consensus(proposal_hash):
            raise ConsensusViolation(f"Quorum not reached for: {proposal_hash}")
        return self.ballot_box[proposal_hash]
