#!/usr/bin/env bash
# Launch codex_nexus compose stack with credentials sourced from KeePassXC vault.
# Never run docker compose directly against compose.yml — always use this wrapper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/../compose.yml"

eval "$(jarvis-secret batch-export CODEX_POSTGRES_PASSWORD CODEX_DATABASE_URL)"

export CODEX_POSTGRES_PASSWORD
export CODEX_DATABASE_URL

exec docker compose -f "${COMPOSE_FILE}" "$@"
