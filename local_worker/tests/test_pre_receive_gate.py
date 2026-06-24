from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))
sys.path.insert(0, str(WORKER_ROOT / "src"))

from algebra_gate import (  # noqa: E402
    AlgebraGateViolation,
    build_approval_hash,
    finalize_mutation,
    proposal_material,
    verify_approval_payload,
)
from pre_receive_gate import (  # noqa: E402
    GitObjectRepository,
    PreReceiveGate,
    PreReceiveViolation,
    RefUpdate,
)


AUTHORIZED_NODES = [
    "nexus-alpha",
    "nexus-beta",
    "nexus-delta",
    "nexus-gamma",
]


def approval_for(
    mutation: dict,
    *,
    yes_votes: list[str] | None = None,
) -> dict:
    yes = yes_votes or [
        "nexus-alpha",
        "nexus-beta",
        "nexus-delta",
    ]
    approval = {
        "event_type": "CONSENSUS_APPROVAL",
        **proposal_material(mutation),
        "proposal_hash": mutation["proposal_hash"],
        "approved_at": "2026-06-24T12:00:00Z",
        "quorum": {
            "threshold": 3,
            "authorized_nodes": AUTHORIZED_NODES,
            "yes_votes": yes,
            "no_votes": [],
            "yes_count": len(yes),
            "no_count": 0,
        },
    }
    approval["approval_hash"] = build_approval_hash(approval)
    return approval


class GitFixture:
    def __init__(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.root = root
        self.bare = root / "hub.git"
        self.work = root / "work"
        self._run(root, "git", "init", "--bare", str(self.bare))
        self._run(root, "git", "init", "-b", "main", str(self.work))
        self._run(self.work, "git", "config", "user.name", "Codex Test")
        self._run(
            self.work,
            "git",
            "config",
            "user.email",
            "codex-test@example.invalid",
        )
        self._run(
            self.work,
            "git",
            "remote",
            "add",
            "origin",
            str(self.bare),
        )

        (self.work / "src").mkdir()
        self.write_state(0)
        (self.work / "README.md").write_text("initial\n", encoding="utf-8")
        self._run(self.work, "git", "add", ".")
        self._run(self.work, "git", "commit", "-m", "initial")
        self._run(self.work, "git", "push", "-u", "origin", "main")
        self.base = self.rev()

    def close(self) -> None:
        self.tempdir.cleanup()

    def _run(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def rev(self) -> str:
        return self._run(self.work, "git", "rev-parse", "HEAD").stdout.strip()

    def write_state(self, cascade_depth: int) -> None:
        (self.work / "src" / "state.json").write_text(
            json.dumps(
                {
                    "epoch": "test",
                    "status": "INITIALIZED",
                    "cascade_depth": cascade_depth,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def commit_and_push(self, message: str) -> tuple[str, str]:
        oldrev = self.rev()
        self._run(self.work, "git", "add", ".")
        self._run(self.work, "git", "commit", "-m", message)
        newrev = self.rev()
        self._run(self.work, "git", "push", "origin", "main")
        return oldrev, newrev


class PreReceiveAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = GitFixture()
        self.repository = GitObjectRepository(self.fixture.bare)

    def tearDown(self) -> None:
        self.fixture.close()

    def update(self, oldrev: str, newrev: str) -> RefUpdate:
        return RefUpdate(oldrev, newrev, "refs/heads/main")

    def test_rejects_approved_value_one_when_commit_changes_value_two(self) -> None:
        self.fixture.write_state(2)
        oldrev, newrev = self.fixture.commit_and_push("change depth to two")

        def checker(mutation: dict) -> None:
            approved_mutation = dict(mutation)
            approved_mutation["new_value"] = 1
            approved_mutation = finalize_mutation(approved_mutation)
            verify_approval_payload(
                approval_for(approved_mutation),
                mutation,
                AUTHORIZED_NODES,
            )

        gate = PreReceiveGate(self.repository, approval_checker=checker)
        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "proposal_hash / mutation payload mismatch",
        ):
            gate.check_update(self.update(oldrev, newrev))

    def test_allows_commit_with_no_protected_mutation(self) -> None:
        (self.fixture.work / "README.md").write_text(
            "documentation only\n",
            encoding="utf-8",
        )
        oldrev, newrev = self.fixture.commit_and_push("docs only")

        def unexpected_checker(mutation: dict) -> None:
            self.fail(f"Approval checker should not run: {mutation}")

        gate = PreReceiveGate(
            self.repository,
            approval_checker=unexpected_checker,
        )
        gate.check_update(self.update(oldrev, newrev))

    def test_installed_shell_hook_allows_no_protected_mutation(self) -> None:
        source_hook = WORKER_ROOT / "git_hooks" / "pre-receive"
        installed_hook = self.fixture.bare / "hooks" / "pre-receive"
        shutil.copy2(source_hook, installed_hook)
        installed_hook.chmod(0o775)
        os.symlink(WORKER_ROOT, self.fixture.root / "local_worker")

        (self.fixture.work / "README.md").write_text(
            "shell hook documentation test\n",
            encoding="utf-8",
        )
        self.fixture.commit_and_push("shell hook docs only")

    def test_rejects_duplicate_voter_ids(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")

        def checker(mutation: dict) -> None:
            verify_approval_payload(
                approval_for(
                    mutation,
                    yes_votes=[
                        "nexus-alpha",
                        "nexus-alpha",
                        "nexus-beta",
                    ],
                ),
                mutation,
                AUTHORIZED_NODES,
            )

        gate = PreReceiveGate(self.repository, approval_checker=checker)
        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "contains duplicates",
        ):
            gate.check_update(self.update(oldrev, newrev))

    def test_rejects_vote_from_unauthorized_node(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")

        def checker(mutation: dict) -> None:
            verify_approval_payload(
                approval_for(
                    mutation,
                    yes_votes=[
                        "nexus-alpha",
                        "nexus-beta",
                        "rogue-node",
                    ],
                ),
                mutation,
                AUTHORIZED_NODES,
            )

        gate = PreReceiveGate(self.repository, approval_checker=checker)
        with self.assertRaisesRegex(
            AlgebraGateViolation,
            "unauthorized voter IDs",
        ):
            gate.check_update(self.update(oldrev, newrev))

    def test_accepts_exact_approved_protected_mutation(self) -> None:
        self.fixture.write_state(1)
        oldrev, newrev = self.fixture.commit_and_push("change depth to one")

        def checker(mutation: dict) -> None:
            self.assertEqual(mutation["refname"], "refs/heads/main")
            self.assertEqual(mutation["oldrev"], oldrev)
            self.assertEqual(mutation["newrev"], newrev)
            self.assertEqual(mutation["changed_paths"], ["src/state.json"])
            self.assertEqual(mutation["protected_path"], "src/state.json")
            self.assertEqual(mutation["parameter"], "cascade_depth")
            self.assertEqual(mutation["old_value"], 0)
            self.assertEqual(mutation["new_value"], 1)
            self.assertRegex(mutation["diff_hash"], r"^sha256:[a-f0-9]{64}$")
            verify_approval_payload(
                approval_for(mutation),
                mutation,
                AUTHORIZED_NODES,
            )

        gate = PreReceiveGate(self.repository, approval_checker=checker)
        gate.check_update(self.update(oldrev, newrev))

    def test_rejects_ref_deletion_by_default(self) -> None:
        gate = PreReceiveGate(self.repository)
        zero_oid = "0" * len(self.fixture.base)

        with self.assertRaisesRegex(
            PreReceiveViolation,
            "Ref deletion is not allowed",
        ):
            gate.check_update(self.update(self.fixture.base, zero_oid))

    def test_rejects_non_fast_forward_by_default(self) -> None:
        self.fixture.write_state(1)
        _, current_tip = self.fixture.commit_and_push("first branch")

        self.fixture._run(
            self.fixture.work,
            "git",
            "reset",
            "--hard",
            self.fixture.base,
        )
        (self.fixture.work / "README.md").write_text(
            "alternate history\n",
            encoding="utf-8",
        )
        self.fixture._run(self.fixture.work, "git", "add", ".")
        self.fixture._run(
            self.fixture.work,
            "git",
            "commit",
            "-m",
            "alternate branch",
        )
        alternate_tip = self.fixture.rev()
        self.fixture._run(
            self.fixture.work,
            "git",
            "push",
            "origin",
            "HEAD:refs/heads/alternate",
        )

        gate = PreReceiveGate(self.repository)
        with self.assertRaisesRegex(
            PreReceiveViolation,
            "Non-fast-forward update is not allowed",
        ):
            gate.check_update(self.update(current_tip, alternate_tip))


if __name__ == "__main__":
    unittest.main()
