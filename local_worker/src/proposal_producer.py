#!/usr/bin/env python3
"""
Offline Canonical Proposal Producer

Role:
    Derive finalized canonical mutations from the exact Git objects of a
    candidate ref update, before the push is attempted. The output payloads
    are byte-identical to what pre_receive_gate.py recomputes during the
    push, so approvals collected against them satisfy the online gate.

Operator flow:
    1. Prepare the candidate commit locally.
    2. Run this producer against the local repository:
       proposal_producer.py --git-dir .git --refname refs/heads/main \
           --oldrev <current-hub-tip> --newrev <candidate-commit>
    3. Broadcast each emitted mutation as a CONSENSUS_PROPOSAL
       (gossip_protocol.py propose --mutation-json ...).
    4. Peers vote by proposal_hash. The bridge writes the quorum approval
       to the Postgres ledger.
    5. Push. The pre-receive gate recomputes the mutation and accepts only
       if the stored approval hash matches.

This module never writes to the ledger and never mutates repository state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.append(str(Path(__file__).resolve().parent))

from pre_receive_gate import (  # noqa: E402
    GitObjectRepository,
    PreReceiveGate,
    PreReceiveViolation,
    RefUpdate,
)


def derive_mutations(
    git_dir: str | Path,
    *,
    refname: str,
    oldrev: str,
    newrev: str,
) -> list[Dict[str, Any]]:
    """Derive finalized canonical mutations for a candidate ref update."""
    gate = PreReceiveGate(GitObjectRepository(git_dir))
    return gate.derive_protected_mutations(RefUpdate(oldrev, newrev, refname))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive canonical protected mutations from exact Git objects, "
            "one JSON object per line."
        )
    )
    parser.add_argument("--git-dir", required=True)
    parser.add_argument("--refname", required=True)
    parser.add_argument("--oldrev", required=True)
    parser.add_argument("--newrev", required=True)
    args = parser.parse_args(argv)

    try:
        mutations = derive_mutations(
            args.git_dir,
            refname=args.refname,
            oldrev=args.oldrev,
            newrev=args.newrev,
        )
    except PreReceiveViolation as exc:
        print(f"[PROPOSAL_PRODUCER] FAILED: {exc}", file=sys.stderr)
        return 1

    if not mutations:
        print(
            "[PROPOSAL_PRODUCER] No protected mutations in this update; "
            "no consensus proposal is required.",
            file=sys.stderr,
        )
        return 0

    for mutation in mutations:
        print(json.dumps(mutation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
