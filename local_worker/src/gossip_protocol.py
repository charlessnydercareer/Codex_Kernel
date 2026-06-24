import json
import os
import socket
import time
from federated_linker import FederatedLinker
from consensus_gate import ConsensusGate

class GossipProtocol:
    """
    Broadcasts and listens for Merkle proof updates and Governance Proposals.
    Integrates with FederatedLinker and ConsensusGate.
    """
    def __init__(self, port=9066, local_repo_id="nexus-alpha"):
        self.port = port
        self.peer_data = "peer_matrix_state.json"
        
        # Linker initialized with dummy matrix for negotiation
        self.linker = FederatedLinker(local_repo_id=local_repo_id, local_adjacency_matrix=[[0, 1, 0], [0, 0, 0], [0, 0, 0]])
        
        # ConsensusGate initialized with mock peers
        self.peers = ["nexus-beta", "nexus-gamma", "nexus-delta"]
        self.governance = ConsensusGate(node_id=local_repo_id, peer_list=self.peers)

    def broadcast_packet(self, target_ip, packet):
        """Sends a packet to a peer node."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((target_ip, self.port))
            s.sendall(json.dumps(packet).encode())

    def start_listener(self):
        """Listens for incoming network packets."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('0.0.0.0', self.port))
        server.listen(5)
        print(f"[GOSSIP_LISTENER] Active on port {self.port}...")

        while True:
            conn, addr = server.accept()
            with conn:
                data = conn.recv(1024)
                if data:
                    packet = json.loads(data.decode())
                    self.handle_packet(packet, addr)

    def handle_packet(self, packet, addr):
        packet_type = packet.get("type", "TOPOLOGY_SYNC")
        
        if packet_type == "TOPOLOGY_SYNC":
            if self.linker.negotiate_federated_change(
                remote_repo_id=str(addr), 
                proposed_matrix=packet.get('matrix', []), 
                proof=packet.get('proof', '')
            ):
                self.update_peer_state(packet.get('proof', ''))
                print(f"[GOSSIP_LISTENER] Peer sync successful for topology.")
            else:
                print(f"[GOSSIP_LISTENER] Security rejection for peer {addr}")
                
        elif packet_type == "CONSENSUS_PROPOSAL":
            change_id = packet.get("change_id")
            voter_id = packet.get("voter_id")
            vote = packet.get("vote")
            
            # If the change_id is unknown, automatically propose it locally to initialize the ballot
            if change_id not in self.governance.ballot_box:
                parameter = packet.get("parameter", "unknown")
                new_value = packet.get("new_value", "unknown")
                self.governance.propose_change(change_id, parameter, new_value)
                
            print(f"[GOSSIP_LISTENER] Received CONSENSUS_PROPOSAL from {voter_id} for {change_id}")
            consensus_reached = self.governance.cast_vote(change_id, voter_id, vote)
            if consensus_reached:
                print(f"[GOSSIP_LISTENER] GOVERNANCE: Parameter update authorized by network!")

    def update_peer_state(self, proof):
        """Persists the received proof to the peer ledger."""
        state = {}
        if os.path.exists(self.peer_data):
            with open(self.peer_data, 'r') as f:
                state = json.load(f)
        
        state['last_received_proof'] = proof
        with open(self.peer_data, 'w') as f:
            json.dump(state, f)

if __name__ == "__main__":
    import sys
    gossip = GossipProtocol()
    if len(sys.argv) > 1 and sys.argv[1] == "broadcast":
        import numpy as np
        test_matrix = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
        test_proof = gossip.linker.calculate_merkle_root(np.array(test_matrix))
        packet = {
            "type": "TOPOLOGY_SYNC",
            "proof": test_proof,
            "matrix": test_matrix
        }
        gossip.broadcast_packet("127.0.0.1", packet)
        
    elif len(sys.argv) > 1 and sys.argv[1] == "vote":
        # Testing consensus logic
        # We need 2/3 + 1. Total nodes = 4. 2/3 * 4 + 1 = 3.66 -> needs 3 votes.
        # Self counts as 1. So we need 2 more yes votes.
        
        packet1 = {
            "type": "CONSENSUS_PROPOSAL",
            "change_id": "prop-001",
            "parameter": "max_depth",
            "new_value": 2,
            "voter_id": "nexus-beta",
            "vote": True
        }
        packet2 = {
            "type": "CONSENSUS_PROPOSAL",
            "change_id": "prop-001",
            "parameter": "max_depth",
            "new_value": 2,
            "voter_id": "nexus-gamma",
            "vote": True
        }
        packet3 = {
            "type": "CONSENSUS_PROPOSAL",
            "change_id": "prop-001",
            "parameter": "max_depth",
            "new_value": 2,
            "voter_id": "nexus-delta",
            "vote": True
        }
        gossip.broadcast_packet("127.0.0.1", packet1)
        time.sleep(0.5)
        gossip.broadcast_packet("127.0.0.1", packet2)
        time.sleep(0.5)
        gossip.broadcast_packet("127.0.0.1", packet3)
        
    else:
        gossip.start_listener()
