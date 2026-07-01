#!/usr/bin/env python3
"""
Consensus Transport Bridge

Role:
    Converts verified gossip envelopes into ConsensusGate state transitions.

Authority chain:
    gossip_protocol.py             -> authenticated transport
    consensus_transport_bridge.py  -> envelope-to-consensus reducer
    consensus_gate.py              -> proposal/vote validation + quorum math
    algebra_gate.py                -> enforcement boundary

Proposals are canonical Git-derived mutations (see canonical_consensus.py),
produced offline by proposal_producer.py. Everything is keyed by the
canonical proposal_hash, which binds each ballot and approval to the exact
incoming Git object identity. There is no translation from any legacy
change_id/parameter/value proposal shape.

This module does NOT mutate kernel state.
It only emits approved consensus artifacts that AlgebraGate may consume.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


try:
    from consensus_gate import ConsensusGate, ConsensusViolation
    from canonical_consensus import (
        APPROVAL_EVENT_TYPE,
        CanonicalConsensusViolation,
        build_approval_hash,
        build_proposal_hash,
        proposal_material,
    )
except ImportError:
    # Allows running as `python src/consensus_transport_bridge.py`
    sys.path.append(str(Path(__file__).resolve().parent))
    from consensus_gate import ConsensusGate, ConsensusViolation
    from canonical_consensus import (
        APPROVAL_EVENT_TYPE,
        CanonicalConsensusViolation,
        build_approval_hash,
        build_proposal_hash,
        proposal_material,
    )


SUPPORTED_MESSAGE_TYPES = {
    "CONSENSUS_PROPOSAL",
    "CONSENSUS_VOTE",
}


class ConsensusBridgeViolation(RuntimeError):
    pass


def utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ApprovedProposalStore:
    """
    Writes durable approval artifacts for AlgebraGate.

    This is not the full Postgres semantic ledger.
    It is a file-backed bootstrap bridge, keyed by canonical proposal_hash.

    Output:
        var/consensus/approved/<proposal_hash>.json
        var/consensus/events.jsonl
    """

    def __init__(
        self,
        approved_dir: str | Path = "var/consensus/approved",
        events_path: str | Path = "var/consensus/events.jsonl",
    ) -> None:
        self.approved_dir = Path(approved_dir)
        self.events_path = Path(events_path)

        self.approved_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def approval_path(self, proposal_hash: str) -> Path:
        safe = proposal_hash.replace(":", "_").replace("/", "_").replace("..", "_")
        return self.approved_dir / f"{safe}.json"

    def has_approval(self, proposal_hash: str) -> bool:
        return self.approval_path(proposal_hash).exists()

    def read_approval(self, proposal_hash: str) -> Dict[str, Any]:
        path = self.approval_path(proposal_hash)

        if not path.exists():
            raise FileNotFoundError(path)

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ConsensusBridgeViolation(f"Invalid approval artifact: {path}")

        return data

    def write_approval(self, event: Dict[str, Any]) -> None:
        path = self.approval_path(event["proposal_hash"])

        if path.exists():
            return

        tmp = path.with_suffix(".json.tmp")

        with tmp.open("w", encoding="utf-8") as f:
            json.dump(event, f, indent=2, sort_keys=True)
            f.write("\n")

        tmp.replace(path)

        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True))
            f.write("\n")


class ConsensusTransportBridge:
    """
    Bridges verified gossip envelopes into ConsensusGate.

    Important:
        This bridge assumes gossip_protocol.py already verified:
        - HMAC signature
        - protocol version
        - TTL
        - payload shape

    This bridge verifies:
        - message type
        - canonical mutation payload and proposal hash binding
        - voter identity consistency
        - quorum result
    """

    def __init__(
        self,
        *,
        node_id: str,
        peer_list: Iterable[str],
        approved_dir: str | Path = "var/consensus/approved",
        events_path: str | Path = "var/consensus/events.jsonl",
    ) -> None:
        self.node_id = node_id
        self.peer_list = sorted(set(peer_list))
        self.gate = ConsensusGate(node_id=node_id, peer_list=self.peer_list)
        if os.getenv("CODEX_CONSENSUS_STORE", "file") == "postgres":
            from postgres_consensus_store import PostgresConsensusStore
            self.store = PostgresConsensusStore()
        else:
            self.store = ApprovedProposalStore(
                approved_dir=approved_dir,
                events_path=events_path,
            )
        self.pending_votes: Dict[str, list[Dict[str, Any]]] = {}

    # ------------------------------------------------------------
    # Envelope reducer
    # ------------------------------------------------------------

    def handle_envelope(self, envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        message_type = envelope.get("message_type")

        if message_type not in SUPPORTED_MESSAGE_TYPES:
            raise ConsensusBridgeViolation(f"Unsupported message_type: {message_type}")

        if message_type == "CONSENSUS_PROPOSAL":
            return self._handle_proposal(envelope)

        if message_type == "CONSENSUS_VOTE":
            return self._handle_vote(envelope)

        raise ConsensusBridgeViolation(f"Unhandled message_type: {message_type}")

    # ------------------------------------------------------------
    # Proposal handling
    # ------------------------------------------------------------

    def _handle_proposal(self, envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sender_id = self._sender(envelope)
        payload = self._payload(envelope)

        # Verify canonical shape and hash FIRST — before touching ballot_box.
        # A forged or non-canonical proposal must never register a ballot.
        try:
            expected_hash = build_proposal_hash(payload)
        except CanonicalConsensusViolation as exc:
            raise ConsensusBridgeViolation(
                f"Proposal payload is not a canonical mutation: {exc}"
            ) from exc

        proposal_hash = self._require_str(payload, "proposal_hash")
        if expected_hash != proposal_hash:
            raise ConsensusBridgeViolation(
                f"Proposal hash mismatch: expected={expected_hash} "
                f"got={proposal_hash}"
            )

        if proposal_hash in self.gate.ballot_box:
            # The key is the canonical hash of the payload itself, so a
            # duplicate key is by construction the same mutation.
            return None

        try:
            self.gate.propose_mutation(payload, proposer=sender_id)
        except ConsensusViolation as exc:
            raise ConsensusBridgeViolation(str(exc)) from exc

        if hasattr(self.store, "record_proposal"):
            self.store.record_proposal(
                {
                    **proposal_material(payload),
                    "proposal_hash": proposal_hash,
                    "proposer": sender_id,
                }
            )

        print(
            f"[CONSENSUS_BRIDGE] registered proposal "
            f"proposal_hash={proposal_hash} proposer={sender_id}"
        )

        # Replay any votes that arrived before this proposal
        for pending in self.pending_votes.pop(proposal_hash, []):
            self._handle_vote(pending)

        if self.gate.check_consensus(proposal_hash):
            return self._emit_approval(proposal_hash)

        return None

    # ------------------------------------------------------------
    # Vote handling
    # ------------------------------------------------------------

    def _handle_vote(self, envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sender_id = self._sender(envelope)
        payload = self._payload(envelope)

        proposal_hash = self._require_str(payload, "proposal_hash")
        voter_id = self._require_str(payload, "voter_id")

        if voter_id != sender_id:
            raise ConsensusBridgeViolation(
                f"Voter identity mismatch: sender={sender_id} voter={voter_id}"
            )

        if "vote" not in payload or not isinstance(payload["vote"], bool):
            raise ConsensusBridgeViolation("Vote payload must contain boolean vote")

        vote = payload["vote"]

        # Queue vote if proposal hasn't arrived yet
        if proposal_hash not in self.gate.ballot_box:
            self.pending_votes.setdefault(proposal_hash, []).append(envelope)
            print(
                f"[CONSENSUS_BRIDGE] queued pending vote "
                f"proposal_hash={proposal_hash} voter={voter_id}"
            )
            return None

        try:
            reached = self.gate.cast_vote(
                proposal_hash=proposal_hash,
                voter_id=voter_id,
                vote=vote,
            )
        except ConsensusViolation as exc:
            raise ConsensusBridgeViolation(str(exc)) from exc

        if hasattr(self.store, "record_vote"):
            self.store.record_vote(
                {
                    "proposal_hash": proposal_hash,
                    "voter_id": voter_id,
                    "vote": vote,
                }
            )

        print(
            f"[CONSENSUS_BRIDGE] recorded vote "
            f"proposal_hash={proposal_hash} voter={voter_id} vote={vote}"
        )

        if reached:
            return self._emit_approval(proposal_hash)

        return None

    # ------------------------------------------------------------
    # Approval artifact
    # ------------------------------------------------------------

    def _emit_approval(self, proposal_hash: str) -> Dict[str, Any]:
        # Read from the store if already approved — never regenerate
        # approved_at (it is covered by the approval hash).
        if self.store.has_approval(proposal_hash):
            print(
                f"[CONSENSUS_BRIDGE] approval already exists "
                f"proposal_hash={proposal_hash}"
            )
            return self.store.read_approval(proposal_hash)

        proposal = self.gate.require_consensus(proposal_hash)
        event = self._approval_event_from_proposal(proposal)

        self.store.write_approval(event)

        print(
            f"[CONSENSUS_BRIDGE] APPROVED proposal_hash={proposal_hash} "
            f"approval_hash={event['approval_hash']}"
        )

        return event

    def _approval_event_from_proposal(self, proposal: Any) -> Dict[str, Any]:
        yes_votes = sorted(
            node for node, vote in proposal.votes.items() if vote is True
        )
        no_votes = sorted(
            node for node, vote in proposal.votes.items() if vote is False
        )

        quorum = {
            "threshold": self.gate.quorum_threshold(),
            "authorized_nodes": self.gate.authorized_nodes,
            "yes_votes": yes_votes,
            "no_votes": no_votes,
            "yes_count": len(yes_votes),
            "no_count": len(no_votes),
        }

        # The canonical approval carries the full mutation material so
        # AlgebraGate can verify every field against the recomputed push
        # payload. approval_hash covers everything, approved_at included.
        event = {
            "event_type": APPROVAL_EVENT_TYPE,
            **proposal_material(proposal.mutation),
            "proposal_hash": proposal.proposal_hash,
            "proposer": proposal.proposer,
            "quorum": quorum,
            "approved_at": utc_ts(),
        }
        event["approval_hash"] = build_approval_hash(event)

        return event

    # ------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------

    def _sender(self, envelope: Dict[str, Any]) -> str:
        sender = envelope.get("sender_id")

        if not isinstance(sender, str) or not sender:
            raise ConsensusBridgeViolation("Envelope missing sender_id")

        if sender not in self.gate.authorized_nodes:
            raise ConsensusBridgeViolation(f"Unauthorized sender: {sender}")

        return sender

    def _payload(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        payload = envelope.get("payload")

        if not isinstance(payload, dict):
            raise ConsensusBridgeViolation("Envelope payload must be object")

        return payload

    def _require_str(self, payload: Dict[str, Any], key: str) -> str:
        value = payload.get(key)

        if not isinstance(value, str) or not value:
            raise ConsensusBridgeViolation(f"Missing or invalid string field: {key}")

        return value


# ------------------------------------------------------------
# Replay CLI
# ------------------------------------------------------------

def load_jsonl(path: str | Path) -> list[Dict[str, Any]]:
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(p)

    rows: list[Dict[str, Any]] = []

    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            raw = line.strip()

            if not raw:
                continue

            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ConsensusBridgeViolation(
                    f"Invalid JSONL at {p}:{line_no}: {exc}"
                ) from exc

            if not isinstance(row, dict):
                raise ConsensusBridgeViolation(
                    f"JSONL row must be object at {p}:{line_no}"
                )

            rows.append(row)

    return rows


def parse_peers(raw: str) -> list[str]:
    if not raw.strip():
        return []

    return sorted(
        node.strip()
        for node in raw.split(",")
        if node.strip()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-id", default=os.getenv("CODEX_NODE_ID", "nexus-alpha"))
    parser.add_argument(
        "--peers",
        default=os.getenv("CODEX_CONSENSUS_PEERS", "nexus-beta,nexus-gamma,nexus-delta"),
        help="Comma-separated peer node IDs, not host:port addresses.",
    )
    parser.add_argument(
        "--gossip-ledger",
        default=os.getenv("CODEX_GOSSIP_LEDGER", "var/gossip/messages.jsonl"),
    )
    parser.add_argument(
        "--approved-dir",
        default=os.getenv("CODEX_CONSENSUS_APPROVED_DIR", "var/consensus/approved"),
    )
    parser.add_argument(
        "--events-path",
        default=os.getenv("CODEX_CONSENSUS_EVENTS", "var/consensus/events.jsonl"),
    )

    args = parser.parse_args()

    bridge = ConsensusTransportBridge(
        node_id=args.node_id,
        peer_list=parse_peers(args.peers),
        approved_dir=args.approved_dir,
        events_path=args.events_path,
    )

    envelopes = load_jsonl(args.gossip_ledger)

    for envelope in envelopes:
        try:
            bridge.handle_envelope(envelope)
        except Exception as exc:
            print(f"[CONSENSUS_BRIDGE] rejected envelope: {exc}")

    print("[CONSENSUS_BRIDGE] replay complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
