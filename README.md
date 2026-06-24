# The Codex Kernel Architecture

The Codex Kernel is designed as a multi-layered gatekeeper. Each component you see in the sandbox performs a specific verification role to ensure the integrity of the ledger.

Here is how the system components work together to maintain Quiescence:

## 1. The Git Boundary (pre-receive hook)
The pre-receive script acts as the "doorman." When you run `git push`, this script fires before the repository accepts any data. It triggers the internal security gates in a specific sequence. If any script exits with a non-zero code, the push is physically rejected by Git, preventing the untrusted code from ever touching the bare hub.

## 2. The Structural Enforcement (algebra_gate.py)
This is a schema validator. It reads `src/state.json` to ensure the project's foundational metrics (like `cascade_depth`) are within safe mathematical limits. It uses `pydantic` to enforce a strict data contract, ensuring that no one can commit a state that might cause the system to spiral out of control.

## 3. The Semantic Enforcement (src/ast_gate.py)
This script performs a static code analysis. Instead of running your code, it parses it into an Abstract Syntax Tree (AST). It walks through that tree looking for prohibited "dangerous" patterns, such as `exec()` or `eval()`. If it finds them, it identifies the violation and blocks the push, ensuring that no malicious or highly unpredictable code enters the ledger.

## 4. The Topological Enforcement (src/federated_linker.py)
This handles cross-repository identity. It uses Merkle proofs (cryptographic hashes of the dependency matrix) to ensure that the "map" of your project is consistent. If another node tries to push a state update, the Linker verifies that the incoming hash matches the proposed data and checks if the proposed change exceeds the local `max_depth` (the "blast radius").

## 5. The Governance Layer (src/consensus_gate.py)
This introduces multi-node democracy. When a change is proposed to critical system parameters (like `max_depth`), it does not automatically apply. The ConsensusGate tracks incoming votes from peer nodes. It only authorizes the change once it receives a supermajority (2/3 + 1) of votes, effectively preventing any single node—or a compromised administrator—from unilaterally changing the security policy.

## 6. The Reconciliation Loop (src/reconciler.py)
If the system ever enters an invalid state due to a failure or a race condition, the reconciler acts as the "factory reset." It is designed to evaluate the current state and force it back to the last known-good configuration (status: `INITIALIZED`, cascade_depth: `0`), ensuring the kernel can always recover itself back to a state of Quiescence.

---
### Summary of the Gatekeeper Flow:
- **`pre-receive`** stops the push.
- **`algebra_gate`** checks the data.
- **`ast_gate`** checks the logic.
- **`federated_linker`** checks the network topology.
- **`consensus_gate`** validates the governance.
- **`reconciler`** resets the baseline.

Together, they transform a standard Git repository into an autonomous, self-healing, and mathematically protected enforcement engine.
