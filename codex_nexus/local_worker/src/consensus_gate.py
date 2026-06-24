import json
import os

class ConsensusGate:
    """
    Implements a 2/3 + 1 voting logic for federated architectural updates.
    Ensures that consensus is reached before altering global defensive parameters.
    """
    def __init__(self, node_id, peer_list):
        self.node_id = node_id
        self.peers = peer_list  # List of peer node IDs
        self.ballot_box = {}

    def propose_change(self, change_id, parameter, new_value):
        """Initiates a proposal for a change in architectural parameters."""
        print(f"[CONSENSUS_GATE] Node {self.node_id} proposing {parameter}={new_value}")
        self.ballot_box[change_id] = {
            "parameter": parameter,
            "value": new_value,
            "votes": {self.node_id: True}
        }

    def cast_vote(self, change_id, voter_id, vote):
        """Records a vote from a peer node."""
        if change_id in self.ballot_box:
            self.ballot_box[change_id]["votes"][voter_id] = vote
            return self.check_consensus(change_id)
        return False

    def check_consensus(self, change_id):
        """Verifies if 2/3 + 1 majority has been achieved."""
        proposal = self.ballot_box[change_id]
        total_nodes = len(self.peers) + 1 # +1 for self
        yes_votes = sum(1 for v in proposal["votes"].values() if v)
        
        required_threshold = (2/3 * total_nodes) + 1
        
        if yes_votes >= required_threshold:
            print(f"[CONSENSUS_GATE] Consensus reached for {change_id}!")
            return True
        return False

if __name__ == "__main__":
    # Example initialization with 3 peers (Total 4 nodes)
    gate = ConsensusGate(node_id="nexus-alpha", peer_list=["nexus-beta", "nexus-gamma", "nexus-delta"])
    gate.propose_change("prop-001", "max_depth", 2)
    print("ConsensusGate initialized. Awaiting peer signals.")
