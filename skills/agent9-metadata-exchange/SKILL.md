---
name: agent9-metadata-exchange
description: Instructions for interacting with the canonical Datacore (hindsight-nexus-db) for durable cross-agent metadata entity records. Trigger when needing to read or write task completion state, lookup entities, or query the datacore.
---

# Datacore Metadata Exchange

## Purpose
Provide access to the internal PostgreSQL metadata exchange database (`hindsight-nexus-db` integrated with Hindsight Memory Bank `JARVIS`) for durable cross-agent metadata entity records. 

## Task
Interact with the metadata exchange via MCP or CLI to persist entity records, search, and look up agent state. Never print database credentials or full connection strings.

## Environment
- `NEXUS_METADATA_EXCHANGE_DATABASE_URL`: required PostgreSQL URL, never printed
- `NEXUS_METADATA_EXCHANGE_ENABLED`: defaults to `true`
- `NEXUS_METADATA_EXCHANGE_BACKEND`: defaults to `postgres`

## Boundary Rules
- Does not submit job applications
- Does not send outbound email
- Does not mutate provider mailboxes
- Must never print database credentials or connection strings
- Uses only `NEXUS_METADATA_EXCHANGE_DATABASE_URL` — never `NEXUS_DATABASE_URL`
- Target database: `hindsight-nexus-db` (via Hindsight Memory Bank `JARVIS`)

## Interacting with the Datacore
You can use the exposed MCP tools when available to interact with the Datacore (`metadata_exchange_lookup`, `metadata_exchange_get_entity`, `metadata_exchange_record_task_completion`).

If MCP tools are unavailable, you may use the CLI commands provided by the `datacore.datacore.metadata_exchange.main` module.
Example commands (output is JSON only):
```bash
python -m datacore.datacore.metadata_exchange.main describe-config
python -m datacore.datacore.metadata_exchange.main health
python -m datacore.datacore.metadata_exchange.main add-entity --input path/to/entity.json
python -m datacore.datacore.metadata_exchange.main get-entity --entity-id some_id
python -m datacore.datacore.metadata_exchange.main list-entities [--limit N]
python -m datacore.datacore.metadata_exchange.main lookup --query snowflake
```
All command output is JSON only. No database URL or secret values are ever printed.

## Main Files
- `datacore/datacore/metadata_exchange/config.py`
- `datacore/datacore/metadata_exchange/schema.py`
- `datacore/datacore/metadata_exchange/store.py`
- `datacore/datacore/metadata_exchange/exchange_models.py`
- `datacore/datacore/metadata_exchange/postgres_store.py`
- `datacore/datacore/metadata_exchange/main.py`
