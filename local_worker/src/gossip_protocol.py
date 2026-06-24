#!/usr/bin/env python3
"""
Authenticated Gossip Transport for Codex Kernel Consensus

Role:
    Transport signed consensus proposals/votes between sovereign nodes.

Non-role:
    This file does NOT decide consensus.
    This file does NOT mutate kernel state.
    This file does NOT bypass AlgebraGate.

Authority chain:
    gossip_protocol.py  -> message transport
    consensus_gate.py   -> vote validation / quorum math
    algebra_gate.py     -> enforcement boundary
    git ledger          -> canonical persistence
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


PROTOCOL_VERSION = "codex-gossip-v1"
MAX_MESSAGE_BYTES = 256_000
DEFAULT_TIMEOUT = 3.0


class GossipViolation(RuntimeError):
    pass


def utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_hash(payload: Dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True)
class Peer:
    node_id: str
    host: str
    port: int


class AuthenticatedEnvelope:
    """
    Signed message envelope.

    Signature covers every field except `signature`.
    """

    @staticmethod
    def build(
        *,
        node_id: str,
        secret: bytes,
        message_type: str,
        payload: Dict[str, Any],
        ttl: int = 3,
    ) -> Dict[str, Any]:
        envelope = {
            "protocol": PROTOCOL_VERSION,
            "message_id": str(uuid.uuid4()),
            "message_type": message_type,
            "sender_id": node_id,
            "timestamp": utc_ts(),
            "ttl": ttl,
            "payload": payload,
        }

        envelope["signature"] = AuthenticatedEnvelope.sign(envelope, secret)
        return envelope

    @staticmethod
    def sign(envelope: Dict[str, Any], secret: bytes) -> str:
        unsigned = dict(envelope)
        unsigned.pop("signature", None)

        digest = hmac.new(
            secret,
            canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest()

        return f"hmac-sha256:{digest}"

    @staticmethod
    def verify(envelope: Dict[str, Any], secret: bytes) -> None:
        if envelope.get("protocol") != PROTOCOL_VERSION:
            raise GossipViolation(f"Unsupported protocol: {envelope.get('protocol')}")

        signature = envelope.get("signature")
        if not isinstance(signature, str):
            raise GossipViolation("Missing signature")

        expected = AuthenticatedEnvelope.sign(envelope, secret)

        if not hmac.compare_digest(signature, expected):
            raise GossipViolation("Envelope signature mismatch")

        ttl = envelope.get("ttl")
        if not isinstance(ttl, int) or ttl < 0:
            raise GossipViolation("Invalid TTL")

        if not isinstance(envelope.get("payload"), dict):
            raise GossipViolation("Payload must be object")


class GossipLedger:
    """
    Local append-only JSONL transport ledger.

    This is not the canonical kernel ledger.
    It is only a transport/audit exhaust for gossip receipts.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._load_seen()

    def _load_seen(self) -> None:
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    message_id = item.get("message_id")
                    if isinstance(message_id, str):
                        self._seen.add(message_id)
                except Exception:
                    continue

    def seen(self, message_id: str) -> bool:
        return message_id in self._seen

    def append(self, envelope: Dict[str, Any]) -> None:
        message_id = envelope["message_id"]

        if self.seen(message_id):
            return

        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope, sort_keys=True))
            f.write("\n")

        self._seen.add(message_id)


class GossipTransport:
    def __init__(
        self,
        *,
        node_id: str,
        bind_host: str,
        bind_port: int,
        peers: Iterable[Peer],
        shared_secret: str,
        ledger_path: str | Path = "var/gossip/messages.jsonl",
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        if not shared_secret:
            raise GossipViolation("CODEX_GOSSIP_SECRET is required")

        self.node_id = node_id
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.peers = list(peers)
        self.secret = shared_secret.encode("utf-8")
        self.ledger = GossipLedger(ledger_path)
        self.on_message = on_message or self.default_handler

    # ------------------------------------------------------------
    # Message construction
    # ------------------------------------------------------------

    def build_proposal(
        self,
        *,
        change_id: str,
        parameter: str,
        value: Any,
        proposal_hash: str,
    ) -> Dict[str, Any]:
        return AuthenticatedEnvelope.build(
            node_id=self.node_id,
            secret=self.secret,
            message_type="CONSENSUS_PROPOSAL",
            payload={
                "change_id": change_id,
                "parameter": parameter,
                "value": value,
                "proposal_hash": proposal_hash,
            },
        )

    def build_vote(
        self,
        *,
        change_id: str,
        voter_id: str,
        vote: bool,
        proposal_hash: str,
    ) -> Dict[str, Any]:
        return AuthenticatedEnvelope.build(
            node_id=self.node_id,
            secret=self.secret,
            message_type="CONSENSUS_VOTE",
            payload={
                "change_id": change_id,
                "voter_id": voter_id,
                "vote": bool(vote),
                "proposal_hash": proposal_hash,
            },
        )

    # ------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------

    def broadcast(self, envelope: Dict[str, Any]) -> None:
        for peer in self.peers:
            self.send(peer, envelope)

    def send(self, peer: Peer, envelope: Dict[str, Any]) -> None:
        data = json.dumps(envelope, sort_keys=True).encode("utf-8") + b"\n"

        if len(data) > MAX_MESSAGE_BYTES:
            raise GossipViolation("Message exceeds MAX_MESSAGE_BYTES")

        try:
            with socket.create_connection(
                (peer.host, peer.port),
                timeout=DEFAULT_TIMEOUT,
            ) as sock:
                sock.sendall(data)
        except OSError as exc:
            print(
                f"[GOSSIP] send failed peer={peer.node_id} "
                f"{peer.host}:{peer.port} error={exc}"
            )

    # ------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------

    def serve_forever(self) -> None:
        print(
            f"[GOSSIP] node={self.node_id} listening "
            f"{self.bind_host}:{self.bind_port}"
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.bind_host, self.bind_port))
            server.listen()

            while True:
                conn, addr = server.accept()
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True,
                )
                thread.start()

    def _handle_connection(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        with conn:
            conn.settimeout(DEFAULT_TIMEOUT)
            data = b""

            while b"\n" not in data:
                chunk = conn.recv(4096)

                if not chunk:
                    break

                data += chunk

                if len(data) > MAX_MESSAGE_BYTES:
                    print(f"[GOSSIP] rejected oversized message from {addr}")
                    return

            line = data.split(b"\n", 1)[0]

            try:
                envelope = json.loads(line.decode("utf-8"))
                self.receive(envelope)
            except Exception as exc:
                print(f"[GOSSIP] rejected message from {addr}: {exc}")

    def receive(self, envelope: Dict[str, Any]) -> None:
        AuthenticatedEnvelope.verify(envelope, self.secret)

        message_id = envelope["message_id"]

        if self.ledger.seen(message_id):
            print(f"[GOSSIP] duplicate ignored message_id={message_id}")
            return

        self.ledger.append(envelope)
        print(
            f"[GOSSIP] accepted type={envelope['message_type']} "
            f"sender={envelope['sender_id']} id={message_id}"
        )

        self.on_message(envelope)

        # Optional flood forwarding with TTL decay.
        ttl = envelope.get("ttl", 0)

        if ttl > 0:
            forwarded = dict(envelope)
            forwarded["ttl"] = ttl - 1
            forwarded["signature"] = AuthenticatedEnvelope.sign(forwarded, self.secret)

            for peer in self.peers:
                if peer.node_id != envelope.get("sender_id"):
                    self.send(peer, forwarded)

    # ------------------------------------------------------------
    # Default handler
    # ------------------------------------------------------------

    def default_handler(self, envelope: Dict[str, Any]) -> None:
        """
        Default behavior only logs verified transport messages.

        Wire this to ConsensusGate in a higher-level integration module.
        """
        payload_hash = stable_hash(envelope["payload"])
        print(
            f"[GOSSIP] verified message_type={envelope['message_type']} "
            f"payload_hash={payload_hash}"
        )


def parse_peers(raw: str) -> List[Peer]:
    """
    Format:
        node_id@host:port,node_id@host:port

    Example:
        nexus-beta@127.0.0.1:9102,nexus-gamma@127.0.0.1:9103
    """
    peers: List[Peer] = []

    if not raw.strip():
        return peers

    for item in raw.split(","):
        item = item.strip()

        if not item:
            continue

        node_id, address = item.split("@", 1)
        host, port_s = address.rsplit(":", 1)

        peers.append(
            Peer(
                node_id=node_id,
                host=host,
                port=int(port_s),
            )
        )

    return peers


def build_bridge_handler():
    if os.getenv("CODEX_CONSENSUS_BRIDGE", "false").lower() not in {"1", "true", "yes", "on"}:
        return None

    from consensus_transport_bridge import ConsensusTransportBridge

    def _parse_peer_ids(raw: str) -> list[str]:
        if not raw.strip():
            return []
        return sorted(node.strip() for node in raw.split(",") if node.strip())

    bridge = ConsensusTransportBridge(
        node_id=os.getenv("CODEX_NODE_ID", "nexus-alpha"),
        peer_list=_parse_peer_ids(os.getenv("CODEX_CONSENSUS_PEERS", "nexus-beta,nexus-gamma,nexus-delta")),
        approved_dir=os.getenv("CODEX_CONSENSUS_APPROVED_DIR", "var/consensus/approved"),
        events_path=os.getenv("CODEX_CONSENSUS_EVENTS", "var/consensus/events.jsonl"),
    )

    return bridge.handle_envelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-id", default=os.getenv("CODEX_NODE_ID", "nexus-alpha"))
    parser.add_argument("--host", default=os.getenv("CODEX_GOSSIP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CODEX_GOSSIP_PORT", "9101")))
    parser.add_argument("--peers", default=os.getenv("CODEX_GOSSIP_PEERS", ""))
    parser.add_argument("--ledger", default=os.getenv("CODEX_GOSSIP_LEDGER", "var/gossip/messages.jsonl"))

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve")

    prop = sub.add_parser("propose")
    prop.add_argument("--change-id", required=True)
    prop.add_argument("--parameter", required=True)
    prop.add_argument("--value", required=True)
    prop.add_argument("--proposal-hash", required=True)

    vote = sub.add_parser("vote")
    vote.add_argument("--change-id", required=True)
    vote.add_argument("--voter-id", required=True)
    vote.add_argument("--proposal-hash", required=True)
    vote.add_argument("--yes", action="store_true")
    vote.add_argument("--no", action="store_true")

    args = parser.parse_args()

    secret = os.getenv("CODEX_GOSSIP_SECRET")
    if not secret:
        raise SystemExit("CODEX_GOSSIP_SECRET is required")

    transport = GossipTransport(
        node_id=args.node_id,
        bind_host=args.host,
        bind_port=args.port,
        peers=parse_peers(args.peers),
        shared_secret=secret,
        ledger_path=args.ledger,
        on_message=build_bridge_handler(),
    )

    if args.cmd == "serve":
        transport.serve_forever()
        return 0

    if args.cmd == "propose":
        envelope = transport.build_proposal(
            change_id=args.change_id,
            parameter=args.parameter,
            value=args.value,
            proposal_hash=args.proposal_hash,
        )
        transport.ledger.append(envelope)
        transport.broadcast(envelope)
        print(f"[GOSSIP] proposal broadcast id={envelope['message_id']}")
        return 0

    if args.cmd == "vote":
        if args.yes == args.no:
            raise SystemExit("Specify exactly one of --yes or --no")

        envelope = transport.build_vote(
            change_id=args.change_id,
            voter_id=args.voter_id,
            vote=args.yes,
            proposal_hash=args.proposal_hash,
        )
        transport.ledger.append(envelope)
        transport.broadcast(envelope)
        print(f"[GOSSIP] vote broadcast id={envelope['message_id']}")
        return 0

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
