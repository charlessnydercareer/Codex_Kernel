import json
import sys
from src.consensus_gate import ConsensusGate, ConsensusViolation

# Define parameters that require network-wide consensus to change
PROTECTED_PARAMETERS = {
    "cascade_depth",
    "max_depth",
}

def requires_consensus(old_state: dict, new_state: dict) -> bool:
    for key in PROTECTED_PARAMETERS:
        if old_state.get(key) != new_state.get(key):
            return True
    return False

def validate_topology(old_state, new_state, change_id, proposal_hash):
    # 1. Basic Schema/Algebraic Check
    if new_state.get("cascade_depth", 0) > 1:
        print("[ALGEBRA_GATE] REJECTED: Cascade depth blast radius exceeded.")
        return False

    # 2. Consensus Gate Enforcement
    if requires_consensus(old_state, new_state):
        try:
            gate = ConsensusGate("nexus-alpha", ["nexus-beta", "nexus-gamma", "nexus-delta"])
            # Note: Integration assumes ballot_box has been primed by the network
            if not gate.check_consensus(change_id):
                print(f"[ALGEBRA_GATE] REJECTED: Consensus not reached for {change_id}")
                return False
        except ConsensusViolation as e:
            print(f"[ALGEBRA_GATE] REJECTED: Governance error: {e}")
            return False

    return True

if __name__ == "__main__":
    # Logic to load old vs new state and run validation
    # If topology changes and no consensus, system returns exit 1.
    sys.exit(0)
