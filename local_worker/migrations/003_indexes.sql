CREATE INDEX IF NOT EXISTS idx_consensus_proposals_payload_gin ON consensus_proposals USING GIN(payload);
CREATE INDEX IF NOT EXISTS idx_consensus_votes_payload_gin ON consensus_votes USING GIN(payload);
CREATE INDEX IF NOT EXISTS idx_consensus_approvals_payload_gin ON consensus_approvals USING GIN(payload);

CREATE INDEX IF NOT EXISTS idx_kernel_events_type ON kernel_events(event_type);
CREATE INDEX IF NOT EXISTS idx_kernel_events_payload ON kernel_events USING GIN(payload);

CREATE INDEX IF NOT EXISTS idx_observability_events_type ON observability_events(event_type);
CREATE INDEX IF NOT EXISTS idx_observability_events_payload ON observability_events USING GIN(payload);
