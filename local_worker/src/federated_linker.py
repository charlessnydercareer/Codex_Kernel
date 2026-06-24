import hashlib
import json
import os
import numpy as np

class FederatedLinker:
    """
    Manages cross-repository state negotiation by verifying
    remote Merkle proofs against local topological constraints.
    """
    def __init__(self, local_repo_id, local_adjacency_matrix, state_file="topology.json"):
        self.local_repo_id = local_repo_id
        self.state_file = state_file
        # Expecting a numpy array representing the adjacency matrix
        self.local_matrix = np.array(local_adjacency_matrix)

    def calculate_merkle_root(self, adjacency_matrix):
        """Creates a unique hash of the repo's current dependency state."""
        matrix_str = json.dumps(adjacency_matrix.tolist(), sort_keys=True)
        return hashlib.sha256(matrix_str.encode()).hexdigest()

    def negotiate_federated_change(self, remote_repo_id, proposed_matrix, proof, max_depth=1):
        """
        Validates if a remote repo's proposed change violates local quiescence.
        """
        proposed_np = np.array(proposed_matrix)
        
        # 1. Error Handling: Dimension check
        if proposed_np.shape != self.local_matrix.shape:
            print(f"[FEDERATED_LINKER] ERROR: Dimension mismatch. Local: {self.local_matrix.shape}, Remote: {proposed_np.shape}")
            return False

        # 2. Verify the Proof of Boundary
        expected_root = self.calculate_merkle_root(proposed_np)
        if proof != expected_root:
            print(f"[FEDERATED_LINKER] SECURITY ALERT: Proof mismatch from {remote_repo_id}")
            return False
            
        # 3. Local Quiescence Check: Merge remote matrix and calculate cascade depth
        merged_matrix = np.logical_or(self.local_matrix, proposed_np).astype(int)
        
        # Calculate reachability for path analysis
        reachability = np.linalg.matrix_power(merged_matrix, max_depth + 1)
        
        if np.any(reachability > 0):
            print(f"[FEDERATED_LINKER] SECURITY ALERT: Federated cascade depth exceeded from {remote_repo_id}")
            return False

        self.local_matrix = merged_matrix
        print(f"[FEDERATED_LINKER] Topology merge validated for {remote_repo_id}")
        return True

    def commit_federated_state(self):
        """Finalizes the synchronization by persisting to disk."""
        with open(self.state_file, 'w') as f:
            json.dump(self.local_matrix.tolist(), f)
        print(f"[FEDERATED_LINKER] State synchronized and persisted to {self.state_file}.")

if __name__ == "__main__":
    initial_matrix = [[0, 1, 0], [0, 0, 0], [0, 0, 0]]
    linker = FederatedLinker(local_repo_id="nexus-alpha", local_adjacency_matrix=initial_matrix)
    print("Federated Linker initialized with persistence and error handling.")
