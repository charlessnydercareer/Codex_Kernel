CREATE TABLE IF NOT EXISTS consensus_proposals (
    id BIGSERIAL PRIMARY KEY,
    change_id TEXT NOT NULL UNIQUE,
    proposal_hash TEXT NOT NULL UNIQUE,
    proposer TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "additionalProperties": false,
                "required": [
                    "change_id",
                    "parameter",
                    "value",
                    "proposal_hash",
                    "proposer"
                ],
                "properties": {
                    "change_id": {"type": "string", "minLength": 1},
                    "parameter": {"type": "string", "minLength": 1},
                    "value": {},
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
    change_id TEXT NOT NULL REFERENCES consensus_proposals(change_id) ON DELETE CASCADE,
    voter_id TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "additionalProperties": false,
                "required": [
                    "change_id",
                    "voter_id",
                    "vote",
                    "proposal_hash"
                ],
                "properties": {
                    "change_id": {"type": "string", "minLength": 1},
                    "voter_id": {"type": "string", "minLength": 1},
                    "vote": {"type": "boolean"},
                    "proposal_hash": {
                        "type": "string",
                        "pattern": "^sha256:[a-f0-9]{64}$"
                    }
                }
            }'::json,
            payload
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (change_id, voter_id)
);

CREATE TABLE IF NOT EXISTS consensus_approvals (
    id BIGSERIAL PRIMARY KEY,
    change_id TEXT NOT NULL UNIQUE REFERENCES consensus_proposals(change_id) ON DELETE CASCADE,
    proposal_hash TEXT NOT NULL,
    approval_hash TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "additionalProperties": false,
                "required": [
                    "event_type",
                    "change_id",
                    "parameter",
                    "value",
                    "proposal_hash",
                    "proposer",
                    "approved_at",
                    "quorum",
                    "approval_hash"
                ],
                "properties": {
                    "event_type": {"const": "CONSENSUS_APPROVAL"},
                    "change_id": {"type": "string", "minLength": 1},
                    "parameter": {"type": "string", "minLength": 1},
                    "value": {},
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
