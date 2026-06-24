#!/usr/bin/env python3
"""
Postgres Semantic Ledger Contract Verifier

Runtime rule:
The kernel verifies infrastructure.
The kernel does not provision infrastructure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable
import psycopg


class KernelContractViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseContract:
    required_extensions: tuple[str, ...] = (
        "pg_jsonschema",
        "pgcrypto",
    )
    required_tables: tuple[str, ...] = (
        "consensus_proposals",
        "consensus_votes",
        "consensus_approvals",
        "kernel_events",
        "observability_events",
    )


class MemoryLedgerContractVerifier:
    def __init__(
        self,
        conn_str: str | None = None,
        contract: DatabaseContract | None = None,
    ) -> None:
        self.conn_str = conn_str or os.getenv(
            "CODEX_DATABASE_URL",
            "dbname=codex_nexus user=nexus_admin host=localhost",
        )
        self.contract = contract or DatabaseContract()

    def verify(self) -> None:
        with psycopg.connect(self.conn_str) as conn:
            self._verify_extensions(conn)
            self._verify_tables(conn)
            self._verify_pg_jsonschema_function(conn)

    def _verify_extensions(self, conn: psycopg.Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT extname FROM pg_extension WHERE extname = ANY(%s)
                """,
                (list(self.contract.required_extensions),),
            )
            found = {row[0] for row in cur.fetchall()}

        missing = set(self.contract.required_extensions) - found
        if missing:
            raise KernelContractViolation(
                f"Missing required PostgreSQL extensions: {sorted(missing)}"
            )

    def _verify_tables(self, conn: psycopg.Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(%s)
                """,
                (list(self.contract.required_tables),),
            )
            found = {row[0] for row in cur.fetchall()}

        missing = set(self.contract.required_tables) - found
        if missing:
            raise KernelContractViolation(
                f"Missing required PostgreSQL tables: {sorted(missing)}"
            )

    def _verify_pg_jsonschema_function(self, conn: psycopg.Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT jsonb_matches_schema(
                    '{"type":"object"}'::json,
                    '{}'::jsonb
                )
                """
            )
            ok = cur.fetchone()[0]

        if ok is not True:
            raise KernelContractViolation(
                "pg_jsonschema jsonb_matches_schema function failed contract check"
            )


def verify_database_contract() -> None:
    MemoryLedgerContractVerifier().verify()


if __name__ == "__main__":
    verify_database_contract()
    print("[MEMORY] Postgres semantic ledger contract verified.")
