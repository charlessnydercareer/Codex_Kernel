#!/usr/bin/env python3
"""
Git-object-bound pre-receive enforcement for Codex Kernel.

All inspected content is read from the incoming object database. The working
tree is never used as authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

WORKER_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(WORKER_ROOT))

from algebra_gate import (  # noqa: E402
    PROPOSAL_VERSION,
    finalize_mutation,
    require_consensus_approval,
)


ZERO_OID_CHARS = {"0"}
PROTECTED_JSON_FIELDS = {
    "src/state.json": {
        "cascade_depth",
        "max_depth",
        "max_cascade_depth",
        "schema_version",
        "algebra_policy_version",
    },
}


class PreReceiveViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class RefUpdate:
    oldrev: str
    newrev: str
    refname: str


def is_zero_oid(oid: str) -> bool:
    return bool(oid) and set(oid) == ZERO_OID_CHARS


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class GitObjectRepository:
    def __init__(self, git_dir: str | Path) -> None:
        self.git_dir = str(Path(git_dir).resolve())

    def run(
        self,
        *args: str,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            ["git", "--git-dir", self.git_dir, *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise PreReceiveViolation(
                f"Git object inspection failed: {' '.join(args)}: {message}"
            )
        return result

    def empty_tree(self) -> str:
        return self.run(
            "hash-object",
            "-t",
            "tree",
            "--stdin",
            input_bytes=b"",
        ).stdout.decode("ascii").strip()

    def commit_oid(self, oid: str) -> str:
        result = self.run("rev-parse", "--verify", f"{oid}^{{commit}}")
        return result.stdout.decode("ascii").strip()

    def is_ancestor(self, oldrev: str, newrev: str) -> bool:
        result = self.run(
            "merge-base",
            "--is-ancestor",
            oldrev,
            newrev,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise PreReceiveViolation("Unable to determine fast-forward status.")
        return result.returncode == 0

    def changed_paths(self, oldrev: str, newrev: str) -> list[str]:
        result = self.run(
            "diff",
            "--name-only",
            "-z",
            "--no-ext-diff",
            "--no-renames",
            oldrev,
            newrev,
            "--",
        )
        paths = [
            item.decode("utf-8")
            for item in result.stdout.split(b"\0")
            if item
        ]
        return sorted(set(paths))

    def diff_bytes(self, oldrev: str, newrev: str) -> bytes:
        return self.run(
            "diff",
            "--raw",
            "--full-index",
            "-z",
            "--no-ext-diff",
            "--no-renames",
            oldrev,
            newrev,
            "--",
        ).stdout

    def blob(self, revision: str, path: str) -> bytes | None:
        result = self.run("show", f"{revision}:{path}", check=False)
        if result.returncode != 0:
            return None
        return result.stdout


class PreReceiveGate:
    def __init__(
        self,
        repository: GitObjectRepository,
        *,
        approval_checker: Callable[[dict[str, Any]], Any] | None = None,
        allow_deletes: bool = False,
        allow_non_fast_forward: bool = False,
        allowed_ref_prefixes: Iterable[str] = ("refs/heads/",),
    ) -> None:
        self.repository = repository
        self.approval_checker = approval_checker or require_consensus_approval
        self.allow_deletes = allow_deletes
        self.allow_non_fast_forward = allow_non_fast_forward
        self.allowed_ref_prefixes = tuple(allowed_ref_prefixes)

    def check_updates(self, updates: Iterable[RefUpdate]) -> None:
        found = False
        for update in updates:
            found = True
            self.check_update(update)
        if not found:
            raise PreReceiveViolation("No ref updates were supplied on stdin.")

    def check_update(self, update: RefUpdate) -> None:
        if not update.refname.startswith(self.allowed_ref_prefixes):
            raise PreReceiveViolation(
                f"Ref is outside the allowed namespaces: {update.refname}"
            )
        if is_zero_oid(update.newrev):
            if self.allow_deletes:
                return
            raise PreReceiveViolation(
                f"Ref deletion is not allowed: {update.refname}"
            )

        newrev = self.repository.commit_oid(update.newrev)
        if is_zero_oid(update.oldrev):
            oldrev = self.repository.empty_tree()
        else:
            oldrev = self.repository.commit_oid(update.oldrev)
            if (
                not self.allow_non_fast_forward
                and not self.repository.is_ancestor(oldrev, newrev)
            ):
                raise PreReceiveViolation(
                    f"Non-fast-forward update is not allowed: {update.refname}"
                )

        changed_paths = self.repository.changed_paths(oldrev, newrev)
        diff_hash = sha256_bytes(self.repository.diff_bytes(oldrev, newrev))

        self._scan_changed_python(newrev, changed_paths)
        for mutation in self._protected_mutations(
            update=update,
            oldrev=oldrev,
            newrev=newrev,
            changed_paths=changed_paths,
            diff_hash=diff_hash,
        ):
            self.approval_checker(mutation)

    def _scan_changed_python(
        self,
        newrev: str,
        changed_paths: Iterable[str],
    ) -> None:
        for path in changed_paths:
            if not path.endswith(".py"):
                continue
            source = self.repository.blob(newrev, path)
            if source is None:
                continue
            try:
                tree = ast.parse(source.decode("utf-8"), filename=path)
            except (SyntaxError, UnicodeDecodeError) as exc:
                raise PreReceiveViolation(
                    f"Incoming Python source is invalid: {path}: {exc}"
                ) from exc

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(
                    node.func,
                    ast.Name,
                ):
                    continue
                if node.func.id in {"exec", "eval", "__import__"}:
                    raise PreReceiveViolation(
                        f"Incoming Python source uses prohibited "
                        f"{node.func.id}(): {path}"
                    )

    def _protected_mutations(
        self,
        *,
        update: RefUpdate,
        oldrev: str,
        newrev: str,
        changed_paths: list[str],
        diff_hash: str,
    ) -> list[dict[str, Any]]:
        mutations: list[dict[str, Any]] = []

        for protected_path, protected_fields in PROTECTED_JSON_FIELDS.items():
            if protected_path not in changed_paths:
                continue

            old_data = self._json_object(oldrev, protected_path)
            new_data = self._json_object(newrev, protected_path)
            old_exists = old_data is not None
            new_exists = new_data is not None

            for parameter in sorted(protected_fields):
                old_present = old_exists and parameter in old_data
                new_present = new_exists and parameter in new_data
                old_value = old_data.get(parameter) if old_present else None
                new_value = new_data.get(parameter) if new_present else None

                if old_present == new_present and old_value == new_value:
                    continue
                if not old_present:
                    mutation_type = "add"
                elif not new_present:
                    mutation_type = "delete"
                else:
                    mutation_type = "update"

                mutations.append(
                    finalize_mutation(
                        {
                            "proposal_version": PROPOSAL_VERSION,
                            "refname": update.refname,
                            "oldrev": update.oldrev,
                            "newrev": update.newrev,
                            "changed_paths": changed_paths,
                            "protected_path": protected_path,
                            "mutation_type": mutation_type,
                            "parameter": parameter,
                            "old_value": old_value,
                            "new_value": new_value,
                            "diff_hash": diff_hash,
                        }
                    )
                )

        return mutations

    def _json_object(
        self,
        revision: str,
        path: str,
    ) -> dict[str, Any] | None:
        blob = self.repository.blob(revision, path)
        if blob is None:
            return None
        try:
            value = json.loads(blob)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PreReceiveViolation(
                f"Protected JSON is invalid: {path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise PreReceiveViolation(
                f"Protected JSON must contain an object: {path}"
            )
        return value


def parse_updates(stream: Iterable[str]) -> list[RefUpdate]:
    updates: list[RefUpdate] = []
    for line_number, line in enumerate(stream, start=1):
        parts = line.strip().split()
        if not parts:
            continue
        if len(parts) != 3:
            raise PreReceiveViolation(
                f"Invalid pre-receive input on line {line_number}."
            )
        updates.append(RefUpdate(*parts))
    return updates


def env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-dir", required=True)
    args = parser.parse_args(argv)

    gate = PreReceiveGate(
        GitObjectRepository(args.git_dir),
        allow_deletes=env_flag("CODEX_ALLOW_REF_DELETES"),
        allow_non_fast_forward=env_flag("CODEX_ALLOW_NON_FAST_FORWARD"),
    )

    try:
        gate.check_updates(parse_updates(sys.stdin))
    except Exception as exc:
        print(f"[ENFORCEMENT_ENGINE] REJECTED: {exc}", file=sys.stderr)
        return 1

    print("[ENFORCEMENT_ENGINE] Incoming Git objects accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
