# The Codex Kernel Architecture

The Codex Kernel is a distributed, Postgres-backed enforcement engine for Git-based topology mutations. It enforces the principle that no protected state change may enter the ledger without a durable, cryptographically-bound, multi-node consensus approval already recorded in the semantic ledger. The kernel is not autonomous: it requires operator provisioning and an external consensus approval population flow before any protected mutation can be accepted.

---

## 1. What Codex Kernel Is

Codex Kernel v2 is a Git push enforcement system with a distributed semantic ledger backing the enforcement boundary.

The core guarantee: a push that mutates any protected field in `src/state.json` is rejected unless a matching consensus approval record already exists in the Postgres ledger. That approval record must carry a valid 2/3+1 quorum block signed by the authorized node set (`CODEX_AUTHORIZED_NODES`) and a cryptographic hash binding the approval to the exact mutation payload. Pushes that do not touch protected fields, and pushes that modify Python source files, are also inspected inline for dangerous AST patterns (`exec`, `eval`, `__import__`).

The system is fail-closed: any exception during push enforcement produces a non-zero exit and a rejected push. A missing or unreachable database causes all protected mutations to be permanently rejected.

---

## 2. Authority Chain

The authority chain has two phases: an offline consensus accumulation phase (before a push is attempted) and an online enforcement phase (during the push).

**Offline — consensus accumulation:**

```
GossipTransport
    -> ConsensusTransportBridge (REDUCER: converts verified envelopes into durable approval artifacts)
        -> ConsensusGate (vote tallying, 2/3+1 quorum math)
            -> PostgresConsensusStore / ApprovedProposalStore
                -> Postgres consensus_proposals / consensus_approvals tables
```

**Online — push enforcement:**

```
git push
    -> shell pre-receive hook
        -> pre_receive_gate.py (ref validation, AST scan, protected mutation detection)
            -> algebra_gate.require_consensus_approval() (proposal_hash binding + quorum verification)
                -> ConsensusApprovalReader (Postgres JOIN on proposal_hash + approval_hash verification)
                    -> Postgres consensus_approvals table
                        -> exit 0 (accepted) or exit 1 (rejected)
```

A protected mutation is only accepted if an approval record was written to Postgres during the offline phase before the push is attempted. The enforcement gate does not collect votes; it reads pre-computed approval artifacts.

---

## 3. v2 Components

### `bare_hub.git/hooks/pre-receive` + `local_worker/git_hooks/pre-receive`

Both hook files are identical shell scripts. Their only job is to resolve paths and exec `python3 src/pre_receive_gate.py --git-dir <bare_repo>`. All enforcement logic lives in the Python layer.

### `src/pre_receive_gate.py`

The Python enforcement gate. It runs entirely inline (no subprocess delegation to separate gate scripts). In sequence, for each ref update:

1. Validates the refname against `refs/heads/*` (configurable via `CODEX_ALLOW_REF_DELETES`, `CODEX_ALLOW_NON_FAST_FORWARD`).
2. Verifies fast-forward ancestry using `git merge-base --is-ancestor`.
3. Computes `diff_hash` as SHA256 of `git diff --raw` output on the incoming object database.
4. Calls `_scan_changed_python()`: reads each modified `.py` blob from the incoming Git object database (not the working tree) and AST-parses it for `exec`, `eval`, and `__import__` calls. Any detected pattern causes immediate rejection.
5. Calls `_protected_mutations()`: diffs `src/state.json` between `oldrev` and `newrev` and identifies changes to protected fields (`cascade_depth`, `max_depth`, `max_cascade_depth`, `schema_version`, `algebra_policy_version`).
6. For each protected mutation, calls `require_consensus_approval()` from `algebra_gate.py`.

Pushed content is read exclusively from the incoming Git object database. The working tree is never used as an authority.

### `src/algebra_gate.py`

The consensus-enforcement boundary. It does **not** read `src/state.json`, does not import pydantic, and does not validate numeric ranges directly. Its function is:

1. Receive a mutation dict (constructed by `pre_receive_gate.py` from the detected JSON field change).
2. Compute the mutation's `proposal_hash` via `canonical_json` + SHA256.
3. Call `ConsensusApprovalReader.require_approval_by_proposal_hash()` to retrieve the stored approval from Postgres.
4. Call `verify_quorum()`: confirms `yes_count >= (2 * len(trusted_nodes)) // 3 + 1`, that `yes_votes` and `no_votes` do not overlap, and that all voters are in `CODEX_AUTHORIZED_NODES`.
5. Verify the stored `approval_hash` matches a recalculated hash of the approval payload.

Any of the above checks failing raises `AlgebraGateViolation`, which propagates to an exit code 1 at the hook boundary.

`algebra_gate.py` has a known bug: `json` is used in `main()` but is not imported. This does not affect the pre-receive integration path (which calls module functions directly), but it makes the CLI entry point non-functional.

### `src/consensus_approval_reader.py`

The read-only boundary between `algebra_gate` and Postgres. It queries a JOIN of `consensus_approvals` and `consensus_proposals` on `proposal_hash`. It enforces that exactly one approval row exists (rejecting if zero or more than one are found), validates `event_type == CONSENSUS_APPROVAL`, and verifies the `approval_hash` format via SHA256 hex-digest regex. All database exceptions are wrapped as `ConsensusApprovalViolation`. No writes occur in this module.

### `src/consensus_transport_bridge.py`

The reducer that converts verified gossip envelopes into durable Postgres approval records. It is not a transport layer. Its responsibilities:

1. Receive `CONSENSUS_PROPOSAL` and `CONSENSUS_VOTE` envelopes that have already been HMAC-verified by `gossip_protocol.py`.
2. Manage an in-memory `ballot_box` per `change_id`.
3. Compute quorum threshold: `(2 * total_nodes) // 3 + 1`.
4. When threshold is reached, build an approval artifact containing `change_id`, `parameter`, `value`, `proposer`, `proposal_hash`, a quorum block (`authorized_nodes`, `yes_votes`, `no_votes`, counts, threshold), `approved_at`, and `approval_hash`.
5. Write the approval to `PostgresConsensusStore` (when `CODEX_CONSENSUS_STORE=postgres`) or to the file-backed `ApprovedProposalStore` (`var/consensus/approved/{change_id}.json`).

In-memory ballot state is ephemeral. Restarting the bridge process loses unfinalized votes. Durable state lives only in what has been written to the store.

### `src/gossip_protocol.py`

The authenticated inter-node TCP transport. It is responsible for message distribution only; it does not decide consensus or mutate state.

- `AuthenticatedEnvelope` signs messages with HMAC-SHA256 over canonical JSON using a shared secret (`CODEX_GOSSIP_SECRET`). Verification uses constant-time comparison.
- `GossipTransport` binds a TCP listener, accepts connections in daemon threads, reads newline-delimited JSON, verifies signature and TTL, deduplicates by `message_id` via `GossipLedger` (append-only JSONL at `var/gossip/messages.jsonl`), and dispatches to an `on_message` callback.
- Flood-forward: verified messages with `TTL > 0` are re-signed with the local node's secret and forwarded to all peers except the original sender, with TTL decremented.
- CLI commands: `serve`, `propose`, `vote` (all require `CODEX_GOSSIP_SECRET`).
- Optional bridge integration: when `CODEX_CONSENSUS_BRIDGE=true`, verified envelopes are routed to `ConsensusTransportBridge.handle_envelope`.

### `src/consensus_gate.py`

Vote tallying and in-memory governance. `ConsensusGate` maintains a `ballot_box` dict keyed by `change_id`, accepts proposals with self-votes, records votes from authorized peers, and computes quorum as `(2 * total_nodes) // 3 + 1`. It validates proposal hashes with SHA256 over canonical JSON.

`consensus_gate.py` is **not** invoked during a git push. It operates as part of the offline gossip accumulation pipeline via `ConsensusTransportBridge`. The pre-receive enforcement path reads pre-computed approval records from Postgres; it does not collect live votes.

### `src/postgres_consensus_store.py`

The Postgres-backed persistence layer for consensus artifacts. Used by `ConsensusTransportBridge` when `CODEX_CONSENSUS_STORE=postgres`. It provides:

- `record_proposal`: insert into `consensus_proposals` with `ON CONFLICT DO NOTHING`.
- `record_vote`: insert into `consensus_votes` with `ON CONFLICT DO UPDATE`.
- `has_approval` / `read_approval`: query `consensus_approvals` by `change_id`, raise `FileNotFoundError` if absent.
- `write_approval`: insert approval event with `ON CONFLICT DO NOTHING`.

No hashing or quorum verification logic lives here; those are delegated to `algebra_gate.py` and `canonical_consensus.py`. This module verifies the database contract via `memory.py` at initialization.

### `src/memory.py`

A startup contract verifier. `MemoryLedgerContractVerifier.verify()` confirms that:

- The required Postgres extensions exist: `pg_jsonschema`, `pgcrypto`.
- The required tables exist in the public schema: `consensus_proposals`, `consensus_votes`, `consensus_approvals`, `kernel_events`, `observability_events`.
- The `jsonb_matches_schema` function is callable.

It raises `KernelContractViolation` and exits non-zero if any check fails. The `codex-ledger-verify` compose service invokes this at startup. `memory.py` does not provision anything; it only verifies that provisioning has already occurred.

### `src/ast_gate.py`

A standalone filesystem scanner for Python AST patterns (`exec`, `eval`, `__import__`). It scans a local `src/` directory tree and is **not** part of the active enforcement pipeline. The pre-receive hook never imports or calls it. The actual AST enforcement is performed inline by `pre_receive_gate.py::_scan_changed_python()`, which reads incoming Python blobs from the Git object database, not the local filesystem. `ast_gate.py` may be useful as a development-time linting tool but should not be cited as an enforcement gate.

### `src/federated_linker.py`

A stub. `FederatedLinker` implements SHA256 hashing of an adjacency matrix and numpy-based reachability analysis, but it is never imported or called by any enforcement component. `max_depth` is a protected field in `src/state.json` that requires consensus approval to mutate, but no algorithmic depth checking against incoming changes occurs in the active enforcement pipeline. The cross-repository topological enforcement described in prior documentation does not exist in v2.

### `src/reconciler.py`

A standalone drift-correction utility. When invoked manually, it:

1. Loads `src/state.json` and validates it with a Pydantic `StateContract` model (fields: `epoch`, `status`, `cascade_depth`).
2. If `status != "INITIALIZED"`, resets `status` to `"INITIALIZED"` and `cascade_depth` to `0`.
3. Writes the corrected state back to disk.
4. Runs `git add` and `git commit` directly via subprocess.

`reconciler.py` is not invoked anywhere in the system (no hook, compose service, or module calls it). Its git commit path bypasses the pre-receive hook entirely, meaning a reconciler invocation could commit state changes that would otherwise require consensus approval. If this utility is ever wired into the system, it must push through the hook rather than committing directly, or its invocation must be strictly controlled.

---

## 4. Runtime Contracts

The following environment variables are required for the enforcement gate to function:

| Variable | Used by | Effect if absent |
|---|---|---|
| `CODEX_DATABASE_URL` | `algebra_gate`, `consensus_approval_reader`, `postgres_consensus_store`, `memory` | Falls back to `dbname=codex_nexus user=nexus_admin host=localhost`; enforcement fails if DB unreachable |
| `CODEX_AUTHORIZED_NODES` | `algebra_gate` | Empty string by default; all protected mutations fail with `AlgebraGateViolation` if not set to a comma-separated node list |
| `CODEX_GOSSIP_SECRET` | `gossip_protocol` | Gossip transport CLI unusable without it |
| `CODEX_CONSENSUS_STORE` | `consensus_transport_bridge` | Defaults to file-backed store; set to `postgres` for Postgres-backed approval persistence |
| `CODEX_CONSENSUS_BRIDGE` | `gossip_protocol` | Set to `true` to wire gossip into `ConsensusTransportBridge` |
| `CODEX_ALLOW_REF_DELETES` | `pre_receive_gate` | Ref deletions rejected unless set to `1` |
| `CODEX_ALLOW_NON_FAST_FORWARD` | `pre_receive_gate` | Non-fast-forward pushes rejected unless set to `1` |

`CODEX_AUTHORIZED_NODES` is not currently exported in `compose.yml` or `scripts/compose-up.sh`. Until it is configured, all pushes that touch protected fields will be rejected. This is a deployment configuration requirement, not a security default.

---

## 5. Provisioning Sequence

The runtime does not provision its own trust substrate. The following steps must occur in order before any push enforcement is operational:

1. **Docker image provides extension availability.** The `codex-postgres` image must include `pg_jsonschema` and `pgcrypto`. These are not installed by the application at runtime.

2. **Migrations create the schema.** The `codex-db-migrate` compose service runs the SQL migrations (under `local_worker/migrations/`) that create the `consensus_proposals`, `consensus_votes`, `consensus_approvals`, `kernel_events`, and `observability_events` tables.

3. **`memory.py` verifies the database contract.** The `codex-ledger-verify` compose service calls `MemoryLedgerContractVerifier.verify()`. If any required extension or table is missing, the service exits non-zero and the system is not operational.

4. **Operator configures `CODEX_AUTHORIZED_NODES`.** The comma-separated list of authorized node identifiers must be set in the environment before push enforcement can compute valid quorum thresholds.

5. **Approval records must be pre-populated via the gossip consensus flow.** The pre-receive gate can only accept protected mutations that already have a matching approval row in `consensus_approvals`. See the Consensus Flow section for how those records are created.

To bring up the database stack, use `scripts/compose-up.sh`, which sources credentials from the vault via `jarvis-secret` and invokes `docker compose` against `compose.yml`. No database credentials are hardcoded.

---

## 6. Consensus Flow

The consensus flow is entirely asynchronous and must complete before a push is attempted.

1. An operator or authorized node proposes a mutation via the `gossip_protocol` CLI (`propose` command with `change_id`, `parameter`, `value`, `proposal_hash`). The envelope is HMAC-SHA256 signed with `CODEX_GOSSIP_SECRET`.

2. `GossipTransport` distributes the envelope to peer nodes via TCP with TTL-based flood forwarding. Each hop re-signs with the local node's key.

3. Each receiving node's `GossipTransport` verifies the envelope signature, deduplicates via `GossipLedger`, and dispatches to `ConsensusTransportBridge.handle_envelope` (if `CODEX_CONSENSUS_BRIDGE=true`).

4. Peer nodes cast votes via the gossip CLI (`vote` command). `ConsensusTransportBridge` accumulates votes in an in-memory `ballot_box`, checking voter authorization and proposal hash binding.

5. When `yes_count >= (2 * len(authorized_nodes)) // 3 + 1`, `ConsensusTransportBridge` builds an approval artifact and writes it to `PostgresConsensusStore` (or the file-backed store).

6. Only after the approval record exists in Postgres can a push that mutates the corresponding protected field be accepted.

The 2/3+1 quorum threshold is an integer floor computation: `threshold = (2 * N) // 3 + 1`. For example, with 3 nodes the threshold is 3; with 5 nodes the threshold is 4.

---

## 7. Protected Mutation Enforcement

The following fields in `src/state.json` are designated as protected. Any push that modifies them triggers the consensus approval check:

- `cascade_depth`
- `max_depth`
- `max_cascade_depth`
- `schema_version`
- `algebra_policy_version`

Note: the current `src/state.json` contains only three fields (`epoch`, `status`, `cascade_depth`). The fields `max_depth`, `max_cascade_depth`, `schema_version`, and `algebra_policy_version` are defined as protected in `PROTECTED_JSON_FIELDS` but do not yet exist in the state file, so mutations to them cannot currently be triggered.

**Enforcement path for a protected mutation:**

1. `pre_receive_gate.py` detects the field change, constructs a mutation dict, and calls `algebra_gate.require_consensus_approval(mutation)`.
2. `algebra_gate` computes `proposal_hash = SHA256(canonical_json(mutation))` and calls `ConsensusApprovalReader.require_approval_by_proposal_hash(proposal_hash)`.
3. `ConsensusApprovalReader` queries Postgres for a JOIN of `consensus_approvals` and `consensus_proposals` on `proposal_hash`. It requires exactly one matching row.
4. `algebra_gate.verify_quorum()` inspects the stored quorum block: confirms `yes_count >= threshold`, verifies no overlap between `yes_votes` and `no_votes`, and confirms all voters are in `CODEX_AUTHORIZED_NODES`.
5. `algebra_gate` recalculates `approval_hash` from the approval payload and verifies it matches the stored value.
6. If all checks pass, the mutation is accepted. Any failure raises `AlgebraGateViolation` and the push is rejected.

**Python source enforcement:**

All `.py` files in an incoming push are AST-parsed inline by `pre_receive_gate.py::_scan_changed_python()`. The blobs are read from the incoming Git object database. Patterns `exec`, `eval`, and `__import__` cause immediate push rejection. This check runs on all pushes, not only those touching protected fields.

---

## 8. Security Invariants

The following invariants hold in a correctly provisioned deployment:

- **The runtime does not provision its own trust substrate.** The Docker image provides extension availability. Migrations create the schema. `memory.py` verifies the database contract. `ConsensusBridge` writes approvals. `AlgebraGate` only reads approvals and enforces protected-mutation policy.

- **Fail-closed on missing approvals.** If no approval record exists for a proposed mutation, the push is rejected. There is no fallback-accept path.

- **Fail-closed on database unavailability.** If Postgres is unreachable, `ConsensusApprovalReader` raises `ConsensusApprovalViolation` and the push is rejected.

- **Pushed content, not working tree, is authoritative.** `pre_receive_gate.py` reads all inspected content from the incoming Git object database. The working tree is never consulted.

- **Approval hash binding prevents tampering.** The `approval_hash` is SHA256 of the approval payload (excluding the `approval_hash` field itself) serialized as canonical JSON. `algebra_gate` recalculates this at enforcement time and rejects any mismatch.

- **Quorum is verified against stored structure, not re-collected.** The enforcement gate does not wait for live votes. It validates that a pre-stored quorum block satisfies the threshold against the current `CODEX_AUTHORIZED_NODES`. This means changing `CODEX_AUTHORIZED_NODES` after an approval is written can invalidate existing approvals.

- **AST enforcement is not gated on consensus.** All incoming Python files are scanned for dangerous patterns regardless of whether the push touches protected fields.

---

## 9. Local Development Commands

Bring up the Postgres stack and verify the schema contract:

```bash
# Requires CODEX_POSTGRES_PASSWORD available via jarvis-secret
scripts/compose-up.sh
```

This runs three compose services in order: `codex-postgres` (PostgreSQL 18), `codex-db-migrate` (applies SQL migrations), `codex-ledger-verify` (runs `memory.py` contract verification).

Configure the authorized node list before testing protected mutation enforcement:

```bash
export CODEX_AUTHORIZED_NODES="node-a,node-b,node-c"
```

Start the gossip transport on a node:

```bash
python3 src/gossip_protocol.py serve --host 127.0.0.1 --port 9101
```

Propose and vote on a mutation via the gossip CLI:

```bash
# On the proposing node
python3 src/gossip_protocol.py propose --change-id <id> --parameter cascade_depth --value 1

# On each peer node
python3 src/gossip_protocol.py vote --change-id <id> --vote yes
```

Invoke the reconciler manually (standalone; not wired into the push pipeline):

```bash
python3 src/reconciler.py
```

---

## 10. Known Non-Goals

The following capabilities are **not** implemented in v2 and should not be assumed:

- **Cross-repository topological enforcement (`federated_linker.py`).** `FederatedLinker` is not invoked by any enforcement component. SHA256 hashing of adjacency matrices and numpy reachability analysis exist in the file but are unreachable dead code. There is no `max_depth` blast-radius check in the active push pipeline.

- **Automatic approval record creation.** No component automatically creates a `consensus_approvals` record in response to a mutation attempt. The approval must be pre-populated via the gossip consensus flow before the push is attempted. Pushes without a pre-existing approval are permanently rejected.

- **Automatic reconciliation.** `reconciler.py` is not wired into any hook, service, or scheduler. Drift correction requires manual invocation. Additionally, the reconciler's `git commit` path bypasses the pre-receive hook; do not wire it into the automated push pipeline without routing through the hook.

- **Merkle proofs.** No Merkle tree structure is implemented. The system uses flat SHA256 hashes of canonical JSON objects (`proposal_hash`, `approval_hash`, `diff_hash`). The term "Merkle proof" used in prior documentation was inaccurate.

- **Live vote collection during push.** The pre-receive enforcement gate is synchronous and read-only with respect to the consensus ledger. It does not initiate voting, wait for votes, or communicate with peer nodes.

- **`ast_gate.py` as a push gate.** This module scans the local filesystem, not incoming Git objects, and is never called by the enforcement pipeline. Do not cite it as an active enforcement gate.

- **`consensus_manager.py` as an active dispatcher.** No code in the enforcement path imports or instantiates `ConsensusManager`. Its routing role is superseded by `ConsensusTransportBridge`.
