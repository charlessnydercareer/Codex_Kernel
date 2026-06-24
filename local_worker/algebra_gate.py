#!/usr/bin/env python3
"""
Algebra Gate: final protected-mutation enforcement boundary.

The gate consumes a canonical mutation derived from incoming Git objects and
accepts it only when Postgres contains an approval for that exact mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable

sys.path.append(str(Path(__file__).resolve().parent / "src"))

from consensus_approval_reader import (
    ConsensusApprovalReader,
    ConsensusApprovalViolation,
)


class AlgebraGateViolation(RuntimeError):
    pass


PROPOSAL_VERSION = 1
HASH_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
MUTATION_FIELDS = (
    "proposal_version",
    "refname",
    "oldrev",
    "newrev",
    "changed_paths",
    "protected_path",
    "mutation_type",
    "parameter",
    "old_value",
    "new_value",
    "diff_hash",
)


def canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def stable_hash(payload: Dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def proposal_material(mutation: Dict[str, Any]) -> Dict[str, Any]:
    missing = [field for field in MUTATION_FIELDS if field not in mutation]
    if missing:
        raise AlgebraGateViolation(
            f"Mutation payload missing fields: {', '.join(missing)}"
        )

    material = {field: mutation[field] for field in MUTATION_FIELDS}

    if (
        not isinstance(material["proposal_version"], int)
        or isinstance(material["proposal_version"], bool)
        or material["proposal_version"] != PROPOSAL_VERSION
    ):
        raise AlgebraGateViolation(
            f"Unsupported proposal_version: {material['proposal_version']}"
        )
    if material["mutation_type"] not in {"add", "update", "delete"}:
        raise AlgebraGateViolation("Mutation type is invalid.")
    if not isinstance(material["changed_paths"], list):
        raise AlgebraGateViolation("changed_paths must be a list.")
    if material["changed_paths"] != sorted(set(material["changed_paths"])):
        raise AlgebraGateViolation("changed_paths must be sorted and unique.")
    if not HASH_PATTERN.fullmatch(str(material["diff_hash"])):
        raise AlgebraGateViolation("diff_hash is missing or malformed.")

    for field in ("refname", "oldrev", "newrev", "protected_path", "parameter"):
        if not isinstance(material[field], str) or not material[field]:
            raise AlgebraGateViolation(f"Mutation field is invalid: {field}")

    return material


def build_proposal_hash(mutation: Dict[str, Any]) -> str:
    return stable_hash(proposal_material(mutation))


def finalize_mutation(mutation: Dict[str, Any]) -> Dict[str, Any]:
    finalized = dict(mutation)
    finalized["proposal_hash"] = build_proposal_hash(finalized)
    return finalized


def approval_material(approval: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in approval.items()
        if key != "approval_hash"
    }


def build_approval_hash(approval: Dict[str, Any]) -> str:
    return stable_hash(approval_material(approval))


def _validated_node_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(node, str) and node for node in value
    ):
        raise AlgebraGateViolation(f"Approval quorum {field} is invalid.")
    if value != sorted(value):
        raise AlgebraGateViolation(f"Approval quorum {field} must be sorted.")
    if len(value) != len(set(value)):
        raise AlgebraGateViolation(f"Approval quorum {field} contains duplicates.")
    return value


def verify_quorum(
    quorum: Any,
    authorized_nodes: Iterable[str],
) -> None:
    if not isinstance(quorum, dict):
        raise AlgebraGateViolation("Approval quorum block missing.")

    trusted_input = list(authorized_nodes)
    if len(trusted_input) != len(set(trusted_input)):
        raise AlgebraGateViolation("Trusted authorized-node set contains duplicates.")
    trusted_nodes = sorted(trusted_input)
    if not trusted_nodes:
        raise AlgebraGateViolation("Trusted authorized-node set is empty.")

    declared_nodes = _validated_node_list(
        quorum.get("authorized_nodes"),
        "authorized_nodes",
    )
    yes_votes = _validated_node_list(quorum.get("yes_votes"), "yes_votes")
    no_votes = _validated_node_list(quorum.get("no_votes"), "no_votes")

    if declared_nodes != trusted_nodes:
        raise AlgebraGateViolation(
            "Approval authorized_nodes do not match trusted membership."
        )
    if set(yes_votes) & set(no_votes):
        raise AlgebraGateViolation("Approval contains conflicting voter IDs.")

    all_votes = set(yes_votes) | set(no_votes)
    unauthorized = sorted(all_votes - set(trusted_nodes))
    if unauthorized:
        raise AlgebraGateViolation(
            f"Approval contains unauthorized voter IDs: {unauthorized}"
        )

    threshold = quorum.get("threshold")
    expected_threshold = (2 * len(trusted_nodes)) // 3 + 1
    if (
        not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or threshold != expected_threshold
    ):
        raise AlgebraGateViolation(
            "Approval quorum threshold does not match 2/3 + 1 membership."
        )

    yes_count = quorum.get("yes_count")
    no_count = quorum.get("no_count")
    if (
        not isinstance(yes_count, int)
        or isinstance(yes_count, bool)
        or not isinstance(no_count, int)
        or isinstance(no_count, bool)
    ):
        raise AlgebraGateViolation("Approval quorum vote counts must be integers.")
    if yes_count != len(yes_votes):
        raise AlgebraGateViolation("Approval yes_count does not match yes_votes.")
    if no_count != len(no_votes):
        raise AlgebraGateViolation("Approval no_count does not match no_votes.")
    if yes_count < threshold:
        raise AlgebraGateViolation(
            f"Approval quorum not satisfied: yes_count={yes_count}, "
            f"threshold={threshold}"
        )


def verify_approval_payload(
    approval: Dict[str, Any],
    mutation: Dict[str, Any],
    authorized_nodes: Iterable[str],
) -> None:
    if not isinstance(approval, dict):
        raise AlgebraGateViolation("Approval payload must be an object.")
    if approval.get("event_type") != "CONSENSUS_APPROVAL":
        raise AlgebraGateViolation("Approval payload has invalid event_type.")
    if not isinstance(approval.get("approved_at"), str) or not approval["approved_at"]:
        raise AlgebraGateViolation("Approval approved_at is missing or invalid.")

    expected_proposal_hash = build_proposal_hash(mutation)
    supplied_proposal_hash = mutation.get("proposal_hash")
    if supplied_proposal_hash != expected_proposal_hash:
        raise AlgebraGateViolation("Mutation proposal_hash is not canonical.")
    if approval.get("proposal_hash") != expected_proposal_hash:
        raise AlgebraGateViolation("Approval proposal_hash / mutation payload mismatch.")

    expected_material = proposal_material(mutation)
    for field, expected in expected_material.items():
        if approval.get(field) != expected:
            raise AlgebraGateViolation(
                f"Approval mutation payload mismatch: {field}"
            )

    verify_quorum(approval.get("quorum"), authorized_nodes)

    approval_hash = approval.get("approval_hash")
    if not isinstance(approval_hash, str) or not HASH_PATTERN.fullmatch(
        approval_hash
    ):
        raise AlgebraGateViolation("Approval hash missing or malformed.")
    if approval_hash != build_approval_hash(approval):
        raise AlgebraGateViolation("Approval hash does not match approval proof.")


def authorized_nodes_from_env() -> list[str]:
    raw = os.getenv("CODEX_AUTHORIZED_NODES", "")
    nodes = sorted(node.strip() for node in raw.split(",") if node.strip())
    if not nodes:
        raise AlgebraGateViolation(
            "CODEX_AUTHORIZED_NODES is required for protected mutations."
        )
    if len(nodes) != len(set(nodes)):
        raise AlgebraGateViolation("CODEX_AUTHORIZED_NODES contains duplicates.")
    return nodes


def require_consensus_approval(
    mutation: Dict[str, Any],
    *,
    reader: ConsensusApprovalReader | None = None,
    authorized_nodes: Iterable[str] | None = None,
) -> Dict[str, Any]:
    expected_proposal_hash = build_proposal_hash(mutation)
    if mutation.get("proposal_hash") != expected_proposal_hash:
        raise AlgebraGateViolation("Mutation proposal_hash is not canonical.")

    approval_reader = reader or ConsensusApprovalReader()
    approval = approval_reader.require_approval_by_proposal_hash(
        expected_proposal_hash
    )
    verify_approval_payload(
        approval=approval,
        mutation=mutation,
        authorized_nodes=(
            list(authorized_nodes)
            if authorized_nodes is not None
            else authorized_nodes_from_env()
        ),
    )
    return approval


def run_gate(mutation: Dict[str, Any]) -> None:
    approval = require_consensus_approval(mutation)
    print(
        "[ALGEBRA_GATE] Consensus proof: PASS "
        f"proposal_hash={mutation['proposal_hash']} "
        f"parameter={mutation['parameter']} "
        f"approval_hash={approval['approval_hash']}"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: algebra_gate.py <mutation-json-path|->",
            file=sys.stderr,
        )
        return 2

    path = argv[1]
    try:
        if path == "-":
            mutation = json.load(sys.stdin)
        else:
            with Path(path).open("r", encoding="utf-8") as handle:
                mutation = json.load(handle)
        if not isinstance(mutation, dict):
            raise AlgebraGateViolation("Mutation JSON must be an object.")
        run_gate(mutation)
        return 0
    except (AlgebraGateViolation, ConsensusApprovalViolation, OSError, ValueError) as exc:
        print(f"[ALGEBRA_GATE] REJECTED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
