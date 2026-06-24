import sys
from src.consensus_approval_reader import ConsensusApprovalReader, ConsensusApprovalViolation

PROTECTED_PARAMETERS = {
    "cascade_depth",
    "max_depth",
    "max_cascade_depth",
    "schema_version",
    "algebra_policy_version",
}


def requires_consensus(old_state: dict, new_state: dict) -> bool:
    for key in PROTECTED_PARAMETERS:
        if old_state.get(key) != new_state.get(key):
            return True
    return False


def validate_topology(old_state, new_state, change_id, proposal_hash, conn_str=None):
    if new_state.get("cascade_depth", 0) > 1:
        print("[ALGEBRA_GATE] REJECTED: Cascade depth blast radius exceeded.")
        return False

    if requires_consensus(old_state, new_state):
        reader = ConsensusApprovalReader(conn_str=conn_str)
        try:
            approval = reader.require_approval(change_id, proposal_hash)
            print(
                f"[ALGEBRA_GATE] APPROVED: change_id={change_id} "
                f"approval_hash={approval['approval_hash']}"
            )
        except ConsensusApprovalViolation as exc:
            print(f"[ALGEBRA_GATE] REJECTED: {exc}")
            return False

    return True


if __name__ == "__main__":
    sys.exit(0)
