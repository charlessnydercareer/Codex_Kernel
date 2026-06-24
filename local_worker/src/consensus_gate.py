import json
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Any

class ConsensusViolation(RuntimeError):
    pass

@dataclass
class Proposal:
    change_id: str
    parameter: str
    value: Any
    proposer: str
    proposal_hash: str
    votes: Dict[str, bool] = field(default_factory=dict)

class ConsensusGate:
    """
    Deterministic 2/3 + 1 governance gate.
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

    def _hash_proposal(self, change_id: str, parameter: str, value: Any, proposer: str) -> str:
        payload = {
            "change_id": change_id,
            "parameter": parameter,
            "value": value,
            "proposer": proposer,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def propose_change(self, change_id: str, parameter: str, new_value: Any) -> str:
        if change_id in self.ballot_box:
            raise ConsensusViolation(f"Proposal already exists: {change_id}")

        proposal_hash = self._hash_proposal(change_id, parameter, new_value, self.node_id)
        proposal = Proposal(
            change_id=change_id,
            parameter=parameter,
            value=new_value,
            proposer=self.node_id,
            proposal_hash=proposal_hash,
            votes={self.node_id: True},
        )
        self.ballot_box[change_id] = proposal
        print(f"[CONSENSUS_GATE] Proposed {parameter}={new_value} change_id={change_id}")
        return proposal_hash

    def cast_vote(self, change_id: str, voter_id: str, vote: bool, proposal_hash: str) -> bool:
        if voter_id not in self.authorized_nodes:
            raise ConsensusViolation(f"Unauthorized voter: {voter_id}")
        if change_id not in self.ballot_box:
            raise ConsensusViolation(f"Unknown proposal: {change_id}")
        
        proposal = self.ballot_box[change_id]
        if proposal.proposal_hash != proposal_hash:
            raise ConsensusViolation("Proposal hash mismatch.")

        proposal.votes[voter_id] = bool(vote)
        return self.check_consensus(change_id)

    def check_consensus(self, change_id: str) -> bool:
        proposal = self.ballot_box[change_id]
        yes_votes = sum(1 for v in proposal.votes.values() if v is True)
        return yes_votes >= self.quorum_threshold()

    def require_consensus(self, change_id: str) -> Proposal:
        """Returns the Proposal if quorum is reached, raises if not."""
        if change_id not in self.ballot_box:
            raise ConsensusViolation(f"Unknown proposal: {change_id}")
        if not self.check_consensus(change_id):
            raise ConsensusViolation(f"Quorum not reached for: {change_id}")
        return self.ballot_box[change_id]
