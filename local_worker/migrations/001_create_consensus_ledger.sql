-- Canonical consensus ledger, keyed by the canonical proposal_hash of a
-- Git-derived mutation (see local_worker/src/canonical_consensus.py).
-- Payload shapes are enforced with pg_jsonschema CHECK constraints.
--
-- Databases provisioned before the canonical schema carried change_id-keyed
-- v1 tables. Those are archived (never dropped: the ledger is append-only)
-- before the canonical tables are created. The guard below is idempotent:
-- it fires only while a v1-shaped consensus_proposals table exists.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'consensus_proposals'
          AND column_name = 'change_id'
    ) THEN
        ALTER TABLE consensus_approvals RENAME TO consensus_approvals_v1_archive;
        ALTER TABLE consensus_votes RENAME TO consensus_votes_v1_archive;
        ALTER TABLE consensus_proposals RENAME TO consensus_proposals_v1_archive;

        ALTER INDEX IF EXISTS idx_consensus_proposals_change_id RENAME TO idx_v1_archive_proposals_change_id;
        ALTER INDEX IF EXISTS idx_consensus_proposals_payload RENAME TO idx_v1_archive_proposals_payload;
        ALTER INDEX IF EXISTS idx_consensus_votes_change_id RENAME TO idx_v1_archive_votes_change_id;
        ALTER INDEX IF EXISTS idx_consensus_votes_payload RENAME TO idx_v1_archive_votes_payload;
        ALTER INDEX IF EXISTS idx_consensus_approvals_change_id RENAME TO idx_v1_archive_approvals_change_id;
        ALTER INDEX IF EXISTS idx_consensus_approvals_payload RENAME TO idx_v1_archive_approvals_payload;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS consensus_proposals (
    id BIGSERIAL PRIMARY KEY,
    proposal_hash TEXT NOT NULL UNIQUE,
    proposer TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "additionalProperties": false,
                "required": [
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
                    "proposal_hash",
                    "proposer"
                ],
                "properties": {
                    "proposal_version": {"const": 1},
                    "refname": {"type": "string", "minLength": 1},
                    "oldrev": {"type": "string", "minLength": 1},
                    "newrev": {"type": "string", "minLength": 1},
                    "changed_paths": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1}
                    },
                    "protected_path": {"type": "string", "minLength": 1},
                    "mutation_type": {"enum": ["add", "update", "delete"]},
                    "parameter": {"type": "string", "minLength": 1},
                    "old_value": {},
                    "new_value": {},
                    "diff_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    },
                    "proposal_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    },
                    "proposer": {"type": "string", "minLength": 1}
                }
            }'::json,
            payload
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS consensus_votes (
    id BIGSERIAL PRIMARY KEY,
    proposal_hash TEXT NOT NULL REFERENCES consensus_proposals(proposal_hash) ON DELETE CASCADE,
    voter_id TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "additionalProperties": false,
                "required": [
                    "proposal_hash",
                    "voter_id",
                    "vote"
                ],
                "properties": {
                    "proposal_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    },
                    "voter_id": {"type": "string", "minLength": 1},
                    "vote": {"type": "boolean"}
                }
            }'::json,
            payload
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (proposal_hash, voter_id)
);

CREATE TABLE IF NOT EXISTS consensus_approvals (
    id BIGSERIAL PRIMARY KEY,
    proposal_hash TEXT NOT NULL UNIQUE REFERENCES consensus_proposals(proposal_hash) ON DELETE CASCADE,
    approval_hash TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "additionalProperties": false,
                "required": [
                    "event_type",
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
                    "proposal_hash",
                    "proposer",
                    "quorum",
                    "approved_at",
                    "approval_hash"
                ],
                "properties": {
                    "event_type": {"const": "CONSENSUS_APPROVAL"},
                    "proposal_version": {"const": 1},
                    "refname": {"type": "string", "minLength": 1},
                    "oldrev": {"type": "string", "minLength": 1},
                    "newrev": {"type": "string", "minLength": 1},
                    "changed_paths": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1}
                    },
                    "protected_path": {"type": "string", "minLength": 1},
                    "mutation_type": {"enum": ["add", "update", "delete"]},
                    "parameter": {"type": "string", "minLength": 1},
                    "old_value": {},
                    "new_value": {},
                    "diff_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    },
                    "proposal_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    },
                    "proposer": {"type": "string", "minLength": 1},
                    "approved_at": {"type": "string", "minLength": 1},
                    "approval_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    },
                    "quorum": {
                        "type": "object",
                        "additionalProperties": false,
                        "required": [
                            "threshold",
                            "authorized_nodes",
                            "yes_votes",
                            "no_votes",
                            "yes_count",
                            "no_count"
                        ],
                        "properties": {
                            "threshold": {"type": "integer", "minimum": 1},
                            "authorized_nodes": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "yes_votes": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "no_votes": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "yes_count": {"type": "integer", "minimum": 0},
                            "no_count": {"type": "integer", "minimum": 0}
                        }
                    }
                }
            }'::json,
            payload
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
