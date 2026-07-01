import sys
from pathlib import Path

try:
    from consensus_transport_bridge import ConsensusTransportBridge
    from gossip_protocol import GossipTransport
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from consensus_transport_bridge import ConsensusTransportBridge
    from gossip_protocol import GossipTransport


class ConsensusManager:
    """
    Bridge between Authenticated Gossip Transport and consensus governance.
    Verified envelopes carrying canonical Git-derived mutations are routed
    to the ConsensusTransportBridge reducer.
    """

    def __init__(self, node_id, peers, secret):
        self.bridge = ConsensusTransportBridge(
            node_id=node_id,
            peer_list=peers,
        )
        self.transport = GossipTransport(
            node_id=node_id,
            bind_host="127.0.0.1",
            bind_port=9101,
            peers=[],  # Populate from config
            shared_secret=secret,
            on_message=self.bridge.handle_envelope,
        )

    def run(self):
        self.transport.serve_forever()
