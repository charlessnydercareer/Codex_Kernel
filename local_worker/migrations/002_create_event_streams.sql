CREATE TABLE IF NOT EXISTS kernel_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "required": ["event_id", "event_type", "timestamp", "payload"],
                "properties": {
                    "event_id": {"type": "string", "minLength": 1},
                    "event_type": {"type": "string", "minLength": 1},
                    "timestamp": {"type": "string", "minLength": 1},
                    "payload": {"type": "object"}
                }
            }'::json,
            payload
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observability_events (
    id BIGSERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL CHECK (
        jsonb_matches_schema(
            '{
                "type": "object",
                "required": ["trace_id", "event_type", "timestamp"],
                "properties": {
                    "trace_id": {"type": "string", "minLength": 1},
                    "event_type": {"type": "string", "minLength": 1},
                    "timestamp": {"type": "string", "minLength": 1}
                }
            }'::json,
            payload
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
