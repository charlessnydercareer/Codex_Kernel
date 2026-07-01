from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict


PROPOSAL_VERSION = 1
APPROVAL_EVENT_TYPE = "CONSENSUS_APPROVAL"
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


class CanonicalConsensusViolation(RuntimeError):
    pass


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
        raise CanonicalConsensusViolation(
            f"Mutation payload missing fields: {', '.join(missing)}"
        )

    material = {field: mutation[field] for field in MUTATION_FIELDS}

    if (
        not isinstance(material["proposal_version"], int)
        or isinstance(material["proposal_version"], bool)
        or material["proposal_version"] != PROPOSAL_VERSION
    ):
        raise CanonicalConsensusViolation(
            f"Unsupported proposal_version: {material['proposal_version']}"
        )
    if material["mutation_type"] not in {"add", "update", "delete"}:
        raise CanonicalConsensusViolation("Mutation type is invalid.")
    if not isinstance(material["changed_paths"], list):
        raise CanonicalConsensusViolation("changed_paths must be a list.")
    if material["changed_paths"] != sorted(set(material["changed_paths"])):
        raise CanonicalConsensusViolation("changed_paths must be sorted and unique.")
    if not isinstance(material["diff_hash"], str) or not HASH_PATTERN.fullmatch(
        material["diff_hash"]
    ):
        raise CanonicalConsensusViolation("diff_hash is missing or malformed.")

    for field in ("refname", "oldrev", "newrev", "protected_path", "parameter"):
        if not isinstance(material[field], str) or not material[field]:
            raise CanonicalConsensusViolation(f"Mutation field is invalid: {field}")

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
