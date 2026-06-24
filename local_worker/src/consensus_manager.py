from src.consensus_gate import ConsensusGate, ConsensusViolation
from src.gossip_protocol import GossipTransport

class ConsensusManager:
    """
    Bridge between Authenticated Gossip Transport and Consensus Gate.
    Validates cryptographic envelopes before dispatching to governance.
    """
    def __init__(self, node_id, peers, secret):
        self.gate = ConsensusGate(node_id, peers)
        self.transport = GossipTransport(
            node_id=node_id,
            bind_host="127.0.0.1",
            bind_port=9101,
            peers=[],  # Populate from config
            shared_secret=secret,
            on_message=self._handle_consensus_packet
        )

    def _handle_consensus_packet(self, envelope):
        payload = envelope["payload"]
        msg_type = envelope["message_type"]

        if msg_type == "CONSENSUS_PROPOSAL":
            self.gate.propose_change(
                payload["change_id"],
                payload["parameter"],
                payload["value"]
            )
        elif msg_type == "CONSENSUS_VOTE":
            self.gate.cast_vote(
                payload["change_id"],
                payload["voter_id"],
                payload["vote"],
                payload["proposal_hash"]
            )

    def run(self):
        self.transport.serve_forever()
