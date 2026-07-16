"""Focused contracts for OpenBuild's private recovery control plane."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import multiprocessing
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "plugins" / "openbuild" / "skills" / "build" / "scripts" / "recovery_state.py"
SPEC = importlib.util.spec_from_file_location("openbuild_recovery_state", STATE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load recovery state owner from {STATE_PATH}")
recovery_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery_state)


def reserve_in_process(
    workspace: str,
    state_root: str,
    start: object,
    output: object,
    lease_id: str,
) -> None:
    owner = recovery_state.RecoveryRegistry(Path(workspace), state_root=Path(state_root))
    start.wait()
    try:
        owner.reserve_normal(lease_id, allowed_set_digest="b" * 64, recovery_capable=False)
        output.put((lease_id, "reserved"))
    except recovery_state.RecoveryStateError as exc:
        output.put((lease_id, str(exc)))


def run_git(workspace: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


class RegistryContractTests(unittest.TestCase):
    def make_git_workspace(self, root: Path) -> Path:
        workspace = root / "workspace"
        workspace.mkdir()
        run_git(workspace, "init", "--quiet")
        run_git(workspace, "config", "user.email", "tests@example.invalid")
        run_git(workspace, "config", "user.name", "OpenBuild Tests")
        (workspace / ".gitignore").write_text("ignored/\n", encoding="utf-8", newline="\n")
        (workspace / "allowed").mkdir()
        (workspace / "allowed" / "seed.txt").write_text("seed\n", encoding="utf-8", newline="\n")
        (workspace / "outside.txt").write_text("outside\n", encoding="utf-8", newline="\n")
        (workspace / "ignored").mkdir()
        (workspace / "ignored" / "cache.txt").write_text("ignored\n", encoding="utf-8", newline="\n")
        run_git(workspace, "add", ".gitignore", "allowed/seed.txt", "outside.txt")
        run_git(workspace, "commit", "--quiet", "-m", "baseline")
        return workspace

    def owner(self, workspace: Path, state_root: Path, **kwargs: object):
        return recovery_state.RecoveryRegistry(workspace, state_root=state_root, **kwargs)

    def checkpoint(self, owner, **kwargs: object) -> dict[str, object]:
        values: dict[str, object] = {
            "source_id": "opaque-source",
            "source_lease_id": "source-lease",
            "source_receipt_digest": "a" * 64,
            "source_milestone": "M2b-source",
            "target_milestone": "M2b-recovery",
            "allowed_paths": ["allowed"],
            "specification_revision": "R-029",
        }
        values.update(kwargs)
        return owner.capture_checkpoint(**values)

    def reserve_source(
        self,
        owner,
        *,
        lease_id: str = "normal-1",
        run_id: str = "contained-run",
    ) -> dict[str, object]:
        preflight = owner.prepare_source_checkpoint(
            source_id=f"{lease_id}-source",
            source_lease_id=lease_id,
            source_milestone="M2c-source",
            target_milestone="M2c-recovery",
            allowed_paths=["allowed"],
            specification_revision="R-029",
        )
        owner.reserve_normal(
            lease_id,
            allowed_set_digest=preflight["allowed_set_digest"],
            recovery_capable=True,
            source_state_id=preflight["source_state_id"],
            run_id=run_id,
            containment_plan=self.containment_plan(),
        )
        owner.bind_reserved_source_snapshot(lease_id, preflight)
        return preflight

    @staticmethod
    def containment_plan() -> dict[str, object]:
        return {
            "guardian_id": "private-guardian",
            "provider_plan_id": "provider-plan-1",
            "ipc_plan_id": "ipc-plan-1",
            "contained_launch_token": "contained-token",
            "fallback_token": "fallback-token",
            "recovery_target": False,
        }

    @staticmethod
    def process_receipt(
        *, pid: int = 101, identity: str = "private-process"
    ) -> dict[str, object]:
        return {
            "pid": pid,
            "identity": identity,
            "process_group_id": pid,
            "started_at": "2026-07-15T00:00:00Z",
        }

    @staticmethod
    def provider_receipt(
        *,
        guardian_id: str = "private-guardian",
        provider_plan_id: str = "provider-plan-1",
        ipc_plan_id: str = "ipc-plan-1",
        worker_pid: int = 101,
        worker_identity: str = "private-process",
    ) -> dict[str, object]:
        return {
            "guardian_id": guardian_id,
            "guardian_pid": 201,
            "guardian_identity": "private-guardian-process",
            "provider": "windows-job",
            "provider_plan_id": provider_plan_id,
            "ipc_plan_id": ipc_plan_id,
            "policy": "kill-on-close-no-breakaway",
            "active_processes": 1,
            "anti_migration": None,
            "precommit": {
                "guardian_id": guardian_id,
                "guardian_pid": 201,
                "guardian_identity": "private-guardian-process",
                "worker_pid": worker_pid,
                "worker_identity": worker_identity,
                "provider": "windows-job",
                "provider_plan_id": provider_plan_id,
                "ipc_plan_id": ipc_plan_id,
                "provider_populated": True,
                "membership_verified": True,
                "precommit_nonce": "private-precommit",
                "attested_at": "2026-07-15T00:00:01Z",
            },
        }

    @staticmethod
    def terminal_receipt(success: bool) -> dict[str, object]:
        return {
            "success": success,
            "binding_digest": "e" * 64,
            "terminal_event": "turn.completed" if success else "turn.failed",
        }

    @staticmethod
    def zero_proof() -> dict[str, object]:
        return {
            "populated": False,
            "identity_verified": True,
            "guardian_id": "private-guardian",
            "provider": "windows-job",
            "worker_pid": 101,
            "worker_identity": "private-process",
            "proved_at": "2026-07-15T00:00:02Z",
        }

    @staticmethod
    def guardian_close() -> dict[str, object]:
        return {
            "closed": True,
            "guardian_id": "private-guardian",
            "closed_at": "2026-07-15T00:00:03Z",
        }

    @staticmethod
    def handoff_event(
        allowed_set_digest: object, lease_id: str = "normal-1"
    ) -> dict[str, object]:
        return {
            "event_id": "f" * 64,
            "payload": {
                "lease_id": lease_id,
                "run_id": "contained-run",
                "receipt_digest": "a" * 64,
                "checkpoint_digest": "b" * 64,
                "allowed_set_digest": allowed_set_digest,
                "root_verification_digest": "d" * 64,
            },
        }

    def test_registry_uses_owner_private_state_and_root_stable_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            state_root = root / "private-state"
            first = self.owner(workspace, state_root)
            second = self.owner(workspace / ".", state_root)
            state = first.initialize()

            self.assertEqual(first.workspace_key, second.workspace_key)
            self.assertTrue(first.directory.is_relative_to(state_root))
            self.assertFalse(first.directory.is_relative_to(workspace))
            self.assertEqual(state["reader_floor"], "2.2.0")
            self.assertEqual(state["identity_version"], 2)
            self.assertEqual(state["workspace_key"], first.workspace_key)
            self.assertIn("git_common_dir_identity", state)
            if os.name == "nt":
                self.assertTrue(
                    recovery_state._windows_directory_is_private(
                        first.directory,
                        recovery_state._windows_current_user_sid(),
                    )
                )

    def test_digest_consistent_malformed_registry_generations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            owner.initialize()
            pristine = json.loads(owner.path.read_text(encoding="utf-8"))

            mutations = {
                "unknown top-level field": lambda value: value.__setitem__("raw_path", ".env"),
                "previous generation digest": lambda value: value.__setitem__(
                    "previous_generation_digest", "not-a-digest"
                ),
                "unknown lease state": lambda value: value.__setitem__(
                    "lease",
                    {
                        "lease_id": "lease-1",
                        "lease_kind": "normal-legacy",
                        "recovery_capable": False,
                        "state": "unknown",
                        "allowed_set_digest": "",
                        "source_state_id": None,
                        "run_id": None,
                        "prompt_sha256": None,
                        "containment_plan": {},
                    },
                ),
                "non-object outbox": lambda value: value.__setitem__("outbox", []),
                "non-string quarantine": lambda value: value.__setitem__("quarantine", {}),
                "unknown history event": lambda value: value.__setitem__(
                    "history", [{"event": "unknown", "path": ".env"}]
                ),
                "malformed tombstone": lambda value: value.__setitem__(
                    "tombstones", [{"event": "registry-retired"}]
                ),
                "malformed consumed grant": lambda value: value.__setitem__(
                    "consumed_grants", [{"grant_id": 7}]
                ),
                "non-boolean retirement": lambda value: value.__setitem__("retired", "yes"),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    malformed = json.loads(json.dumps(pristine))
                    mutate(malformed)
                    malformed["digest"] = recovery_state._digest(malformed)
                    owner.path.write_text(
                        json.dumps(malformed, sort_keys=True) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(recovery_state.RecoveryStateError):
                        owner.state()

    def test_digest_consistent_malformed_private_source_and_projection_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            source_state_id = checkpoint["source_state_id"]
            source_path = owner.source_path(source_state_id)
            pristine = json.loads(source_path.read_text(encoding="utf-8"))

            mutations = {
                "unknown source field": lambda value: value.__setitem__("raw_path", ".env"),
                "non-integer generation": lambda value: value.__setitem__("generation", "1"),
                "invalid checkpoint key": lambda value: value.__setitem__("checkpoint_key", "secret"),
                "malformed authorization": lambda value: value.__setitem__(
                    "authorization", {"grant_id": "opaque"}
                ),
                "private path in public checkpoint": lambda value: value[
                    "public_checkpoint"
                ].__setitem__("path", ".env"),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    malformed = json.loads(json.dumps(pristine))
                    mutate(malformed)
                    malformed["digest"] = recovery_state._digest(malformed)
                    source_path.write_text(
                        json.dumps(malformed, sort_keys=True) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(recovery_state.RecoveryStateError):
                        owner.public_checkpoint_for_source(source_state_id)

    def test_digest_consistent_contained_receipt_binding_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            pristine = json.loads(owner.path.read_text(encoding="utf-8"))

            mutations = {
                "missing provider plan": lambda lease: lease["provider_receipt"].pop(
                    "provider_plan_id"
                ),
                "mismatched provider plan": lambda lease: lease["provider_receipt"].__setitem__(
                    "provider_plan_id", "other-provider-plan"
                ),
                "missing IPC plan": lambda lease: lease["provider_receipt"].pop("ipc_plan_id"),
                "missing precommit": lambda lease: lease["provider_receipt"].pop("precommit"),
                "precommit guardian drift": lambda lease: lease["provider_receipt"][
                    "precommit"
                ].__setitem__("guardian_id", "other-guardian"),
                "precommit worker PID drift": lambda lease: lease["provider_receipt"][
                    "precommit"
                ].__setitem__("worker_pid", 999),
                "precommit worker identity drift": lambda lease: lease["provider_receipt"][
                    "precommit"
                ].__setitem__("worker_identity", "other-worker"),
                "membership not proven": lambda lease: lease["provider_receipt"][
                    "precommit"
                ].__setitem__("membership_verified", False),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    malformed = json.loads(json.dumps(pristine))
                    mutate(malformed["lease"])
                    malformed["digest"] = recovery_state._digest(malformed)
                    owner.path.write_text(
                        json.dumps(malformed, sort_keys=True) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(recovery_state.RecoveryStateError):
                        owner.state_for_activation()

    def test_digest_consistent_terminal_identity_binding_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(False), preflight["allowed_set_digest"]
            )
            owner.prove_contained_tree_empty(
                "normal-1", self.zero_proof(), preflight["allowed_set_digest"]
            )
            owner.acknowledge_guardian_close("normal-1", self.guardian_close())
            pristine = json.loads(owner.path.read_text(encoding="utf-8"))

            mutations = {
                "missing zero guardian": lambda lease: lease["zero_proof"].pop("guardian_id"),
                "zero guardian drift": lambda lease: lease["zero_proof"].__setitem__(
                    "guardian_id", "other-guardian"
                ),
                "zero provider drift": lambda lease: lease["zero_proof"].__setitem__(
                    "provider", "linux-cgroup-v2"
                ),
                "zero worker PID drift": lambda lease: lease["zero_proof"].__setitem__(
                    "worker_pid", 999
                ),
                "zero worker identity drift": lambda lease: lease["zero_proof"].__setitem__(
                    "worker_identity", "other-worker"
                ),
                "missing close guardian": lambda lease: lease["guardian_close"].pop(
                    "guardian_id"
                ),
                "close guardian drift": lambda lease: lease["guardian_close"].__setitem__(
                    "guardian_id", "other-guardian"
                ),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    malformed = json.loads(json.dumps(pristine))
                    mutate(malformed["lease"])
                    malformed["digest"] = recovery_state._digest(malformed)
                    owner.path.write_text(
                        json.dumps(malformed, sort_keys=True) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(recovery_state.RecoveryStateError):
                        owner.state()

    def test_digest_consistent_semantic_matrix_and_source_binding_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="escalation-run",
                source_lease_id="normal-1",
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed"],
                specification_revision="R-029",
            )
            owner.finalize_prepared_checkpoint(
                preflight,
                source_receipt_digest="a" * 64,
            )
            owner.reserve_normal(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id="escalation-run",
                containment_plan=self.containment_plan(),
            )
            owner.bind_reserved_source_snapshot("normal-1", preflight)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(True), preflight["allowed_set_digest"]
            )
            owner.prove_contained_tree_empty(
                "normal-1", self.zero_proof(), preflight["allowed_set_digest"]
            )
            owner.reject_semantic_handoff(
                "normal-1",
                run_id="escalation-run",
                disposition="needs-escalation",
                evidence_digest="d" * 64,
                checkpoint_allowed=False,
            )
            pristine = json.loads(owner.path.read_text(encoding="utf-8"))

            def rejection(value: dict[str, object]) -> dict[str, object]:
                return next(
                    event
                    for event in value["history"]
                    if event["event"] == "semantic-handoff-rejected"
                )

            def blocked_pending(value: dict[str, object]) -> None:
                value["lease"]["semantic_disposition"]["disposition"] = "blocked"
                rejection(value)["disposition"] = "blocked"

            def escalation_retains_checkpoint(value: dict[str, object]) -> None:
                value["lease"]["semantic_disposition"]["checkpoint_allowed"] = True
                value["lease"]["semantic_disposition"]["checkpoint_invalidation"] = "not-required"
                rejection(value)["checkpoint_allowed"] = True
                rejection(value)["checkpoint_invalidation"] = "not-required"

            def missing_source(value: dict[str, object]) -> None:
                value["lease"]["semantic_disposition"]["source_state_id"] = None
                rejection(value)["source_state_id"] = None

            def mismatched_run(value: dict[str, object]) -> None:
                value["lease"]["semantic_disposition"]["run_id"] = "other-run"
                rejection(value)["run_id"] = "other-run"

            def fabricated_completion(value: dict[str, object]) -> None:
                checkpoint_digest = "9" * 64
                semantic = value["lease"]["semantic_disposition"]
                semantic["checkpoint_invalidation"] = "completed"
                semantic["checkpoint_digest"] = checkpoint_digest
                value["history"].append(
                    {
                        "event": "source-checkpoint-invalidated",
                        "lease_id": "normal-1",
                        "run_id": "escalation-run",
                        "source_state_id": preflight["source_state_id"],
                        "checkpoint_digest": checkpoint_digest,
                        "evidence_digest": "d" * 64,
                    }
                )

            mutations = {
                "blocked with pending invalidation": blocked_pending,
                "escalation retains checkpoint": escalation_retains_checkpoint,
                "missing private source binding": missing_source,
                "mismatched run binding": mismatched_run,
                "fabricated invalidation completion": fabricated_completion,
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    malformed = json.loads(json.dumps(pristine))
                    mutate(malformed)
                    malformed["digest"] = recovery_state._digest(malformed)
                    owner.path.write_text(
                        json.dumps(malformed, sort_keys=True) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(recovery_state.RecoveryStateError):
                        owner.state()

    def test_needs_escalation_requires_authoritative_zero_write_snapshot(self) -> None:
        for changed_path in ("allowed/seed.txt", "outside.txt"):
            with self.subTest(changed_path=changed_path), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = self.make_git_workspace(root)
                owner = self.owner(workspace, root / "state")
                preflight = self.reserve_source(owner, run_id="escalation-run")
                owner.claim_contained_launch("normal-1", "contained-token")
                owner.bind_process_unactivated(
                    "normal-1",
                    allowed_set_digest=preflight["allowed_set_digest"],
                    provider_receipt=self.provider_receipt(),
                    process_receipt=self.process_receipt(),
                )
                owner.commit_activation("normal-1", preflight["allowed_set_digest"])
                (workspace / changed_path).write_text(
                    "writer edit\n", encoding="utf-8", newline="\n"
                )
                checkpoint = owner.finalize_prepared_checkpoint(
                    preflight,
                    source_receipt_digest="a" * 64,
                )
                owner.revalidate_checkpoint(checkpoint)
                owner.record_terminal_evidence(
                    "normal-1", self.terminal_receipt(True), preflight["allowed_set_digest"]
                )
                owner.prove_contained_tree_empty(
                    "normal-1", self.zero_proof(), preflight["allowed_set_digest"]
                )

                with self.assertRaisesRegex(
                    recovery_state.RecoveryStateError, "zero-write"
                ):
                    owner.reject_semantic_handoff(
                        "normal-1",
                        run_id="escalation-run",
                        disposition="needs-escalation",
                        evidence_digest="d" * 64,
                        checkpoint_allowed=False,
                    )
                retained = owner.state()
                self.assertEqual(retained["lease"]["state"], "stopped-terminal")
                self.assertNotIn("semantic_disposition", retained["lease"])
                self.assertTrue(retained["lease"]["terminal_receipt"]["success"])

    @unittest.skipUnless(os.name == "nt", "Windows owner-private registry DACL")
    def test_existing_inherited_windows_registry_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            owner.directory.mkdir(parents=True)

            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "protected"):
                owner.initialize()

    def test_exact_vacancy_and_reader_floor_retirement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            owner.initialize()
            owner.reserve_normal("normal-1", allowed_set_digest="b" * 64, recovery_capable=False)
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "vacant"):
                owner.reserve_normal("normal-2", allowed_set_digest="c" * 64, recovery_capable=False)
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "reader floor"):
                owner.assert_reader_compatible("2.1.5")
            owner.release_unactivated_reservation("normal-1")
            owner.retire_for_downgrade("2.1.5")
            self.assertTrue(owner.assert_reader_compatible("2.1.5")["retired"])

    def test_checkpoint_captures_git_and_exposes_only_keyed_opaque_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            encoded = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True)

            self.assertEqual(checkpoint["disposition"], "recovery-eligible")
            self.assertIn("head_id", checkpoint["pre_snapshot"])
            self.assertIn("full_index_digest", checkpoint["pre_snapshot"])
            self.assertIn("allowed_inventory_digest", checkpoint["pre_snapshot"])
            self.assertIn("ignored_inventory_digest", checkpoint["pre_snapshot"])
            self.assertTrue(any("content_id" in record for record in checkpoint["pre_snapshot"]["records"]))
            self.assertNotIn("allowed/seed.txt", encoded)
            self.assertNotIn("outside.txt", encoded)
            self.assertNotIn("ignored/cache.txt", encoded)
            self.assertNotIn('"checkpoint_key":', encoded)
            self.assertNotIn("seed\n", encoded)
            raw_seed_hash = hashlib.sha256(b"seed\n").hexdigest()
            self.assertNotIn(raw_seed_hash, encoded)
            private = owner.read_private_source(checkpoint["source_state_id"])
            self.assertEqual(len(bytes.fromhex(private["checkpoint_key"])), 32)
            self.assertIn("allowed/seed.txt", private["pre_snapshot"]["records"])
            self.assertIn("ignored/cache.txt", private["pre_snapshot"]["records"])

    def test_ignored_nested_repository_marker_is_normalized_and_fully_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            nested = workspace / "ignored" / "nested-repository"
            nested.mkdir()
            run_git(nested, "init", "--quiet")
            (nested / "private.txt").write_text("private\n", encoding="utf-8", newline="\n")
            owner = self.owner(workspace, root / "state")
            owner.initialize()

            checkpoint = self.checkpoint(owner)
            private = owner.read_private_source(checkpoint["source_state_id"])
            self.assertIn("ignored/nested-repository/private.txt", private["pre_snapshot"]["records"])

            (nested / "private.txt").write_text("changed\n", encoding="utf-8", newline="\n")
            changed = owner.revalidate_checkpoint(checkpoint)
            self.assertEqual(changed["disposition"], "recovery-ineligible")
            self.assertIn("outside-set-drift", changed["reasons"])

    def test_independent_normal_starts_serialize_to_one_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            state_root = root / "state"
            owner = self.owner(workspace, state_root)
            owner.initialize()
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            output = context.Queue()
            processes = [
                context.Process(
                    target=reserve_in_process,
                    args=(str(workspace), str(state_root), start, output, f"normal-{index}"),
                )
                for index in range(2)
            ]
            for process in processes:
                process.start()
            start.set()
            results = [output.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(sum(result == "reserved" for _, result in results), 1)
            self.assertEqual(owner.state()["lease"]["state"], "reserved")

    def test_reserved_source_rejects_a_completed_writer_change_after_pre_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="planned-source",
                source_lease_id="source-lease",
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed"],
                specification_revision="R-029",
            )

            owner.reserve_normal(
                "intervening-writer",
                allowed_set_digest="",
                recovery_capable=False,
            )
            owner.bind_legacy_process_unactivated(
                "intervening-writer",
                process_receipt={"pid": 101, "identity": "intervening-writer-1"},
            )
            (workspace / "allowed" / "seed.txt").write_text(
                "intervening writer\n",
                encoding="utf-8",
                newline="\n",
            )
            owner.release_legacy_terminal(
                "intervening-writer",
                {"success": True, "process_tree_stopped": True},
            )

            owner.reserve_normal(
                "source-lease",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
            )
            with self.assertRaisesRegex(
                recovery_state.RecoveryStateError,
                "changed before the reserved source boundary",
            ):
                owner.bind_reserved_source_snapshot("source-lease", preflight)

            self.assertEqual(owner.state()["lease"]["state"], "normal-preflight-reserved")
            owner.release_unactivated_reservation("source-lease")

    def test_activation_revalidates_normal_and_recovery_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            (workspace / "allowed" / "seed.txt").write_text(
                "activation drift\n", encoding="utf-8", newline="\n"
            )

            with self.assertRaisesRegex(
                recovery_state.RecoveryStateError,
                "activation provenance drift",
            ):
                owner.commit_activation("normal-1", preflight["allowed_set_digest"])

            retained = owner.state()["lease"]
            self.assertEqual(retained["state"], "process-bound-unactivated")
            self.assertEqual(retained["activation_abort"]["cause"], "provenance-drift")
            with self.assertRaisesRegex(
                recovery_state.RecoveryStateError,
                "already retained",
            ):
                owner.commit_activation("normal-1", preflight["allowed_set_digest"])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            (workspace / "allowed" / "seed.txt").write_text(
                "source edit\n", encoding="utf-8", newline="\n"
            )
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="c" * 64,
                specification_revision="R-029",
            )
            owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "target-lease",
                    "run_id": "target-run",
                    "prompt_sha256": "d" * 64,
                    "launch_token": "e" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            owner.claim_launch("target-lease", "e" * 64)
            owner.bind_process_unactivated(
                "target-lease",
                allowed_set_digest=checkpoint["allowed_set_digest"],
                provider_receipt=self.provider_receipt(
                    provider_plan_id="provider-plan", ipc_plan_id="ipc-plan"
                ),
                process_receipt=self.process_receipt(),
            )
            (workspace / "allowed" / "seed.txt").write_text(
                "activation drift\n", encoding="utf-8", newline="\n"
            )

            with self.assertRaisesRegex(
                recovery_state.RecoveryStateError,
                "activation provenance drift",
            ):
                owner.commit_activation("target-lease", checkpoint["allowed_set_digest"])

            retained = owner.state()["lease"]
            self.assertEqual(retained["state"], "process-bound-unactivated")
            self.assertEqual(retained["activation_abort"]["cause"], "provenance-drift")

    def test_git_common_directory_replacement_quarantines_same_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            original_git = workspace / ".git"
            moved_git = workspace / ".git-original"
            original_git.rename(moved_git)
            run_git(workspace, "init", "--quiet")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "quarantined"):
                owner.state_for_activation()
            raw = json.loads(owner.path.read_text(encoding="utf-8"))
            self.assertEqual(raw["quarantine"], "git-common-dir-drift")

    def test_pre_snapshot_precedes_terminal_receipt_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="planned-source",
                source_lease_id="source-lease",
                source_milestone="M2b-source",
                target_milestone="M2b-recovery",
                allowed_paths=["allowed"],
                specification_revision="R-029",
            )
            private = owner.read_private_source(preflight["source_state_id"])
            self.assertIsNone(private["source_binding"]["source_receipt_digest"])
            (workspace / "allowed" / "seed.txt").write_text("worker\n", encoding="utf-8", newline="\n")
            checkpoint = owner.finalize_prepared_checkpoint(
                preflight,
                source_receipt_digest="a" * 64,
            )
            candidate = owner.revalidate_checkpoint(checkpoint)
            self.assertEqual(candidate["disposition"], "recovery-eligible")
            self.assertEqual(candidate["candidate_snapshot"]["outside_set_delta"], [])

    def test_candidate_allows_attributable_changes_and_rejects_outside_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            (workspace / "allowed" / "seed.txt").write_text("worker\n", encoding="utf-8", newline="\n")
            eligible = owner.revalidate_checkpoint(checkpoint)
            self.assertEqual(eligible["disposition"], "recovery-eligible")
            self.assertEqual(eligible["candidate_snapshot"]["outside_set_delta"], [])

            (workspace / "outside.txt").write_text("user drift\n", encoding="utf-8", newline="\n")
            ineligible = owner.revalidate_checkpoint(eligible)
            self.assertEqual(ineligible["disposition"], "recovery-ineligible")
            self.assertIn("outside-set-drift", ineligible["reasons"])

    def test_checkpoint_rejects_preexisting_dirty_overlap_and_git_control_plane_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            (workspace / "allowed" / "seed.txt").write_text("user dirty\n", encoding="utf-8", newline="\n")
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            dirty_checkpoint = self.checkpoint(owner)
            (workspace / "allowed" / "seed.txt").write_text("worker dirty\n", encoding="utf-8", newline="\n")
            dirty = owner.revalidate_checkpoint(dirty_checkpoint)
            self.assertEqual(dirty["disposition"], "recovery-ineligible")
            self.assertIn("preexisting-dirty-overlap", dirty["reasons"])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            (workspace / "outside.txt").write_text("index only\n", encoding="utf-8", newline="\n")
            run_git(workspace, "add", "outside.txt")
            changed = owner.revalidate_checkpoint(checkpoint)
            self.assertEqual(changed["disposition"], "recovery-ineligible")
            self.assertIn("git-control-plane-drift", changed["reasons"])

    def test_checkpoint_rejects_status_suppressing_index_flags(self) -> None:
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = self.make_git_workspace(root)
                run_git(workspace, "update-index", flag, "outside.txt")
                (workspace / "outside.txt").write_text(
                    "hidden outside drift\n", encoding="utf-8", newline="\n"
                )
                owner = self.owner(workspace, root / "state")
                owner.initialize()
                with self.assertRaisesRegex(
                    recovery_state.RecoveryStateError,
                    "status-suppressing index flag",
                ):
                    self.checkpoint(owner)

    def test_snapshot_rejects_windows_reparse_metadata_before_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            metadata = (workspace / "allowed").lstat()

            class ReparseMetadata:
                st_mode = metadata.st_mode
                st_dev = metadata.st_dev
                st_ino = metadata.st_ino
                st_size = metadata.st_size
                st_mtime_ns = metadata.st_mtime_ns
                st_file_attributes = getattr(
                    recovery_state.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                )

            with mock.patch.object(
                Path, "lstat", return_value=ReparseMetadata()
            ), self.assertRaisesRegex(
                recovery_state.RecoveryStateError, "reparse point"
            ):
                owner._record_path(
                    "allowed",
                    key=os.urandom(32),
                    records={},
                    aliases={},
                    budget={"records": 0, "bytes": 0},
                    recurse=False,
                )

    def test_snapshot_rejects_reparse_point_in_an_intermediate_component(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            junction = workspace / "junction"
            junction.mkdir()
            (junction / "child.txt").write_text(
                "external\n", encoding="utf-8", newline="\n"
            )
            owner = self.owner(workspace, root / "state")
            original_lstat = Path.lstat

            class ReparseMetadata:
                def __init__(self, metadata: os.stat_result) -> None:
                    self.st_mode = metadata.st_mode
                    self.st_dev = metadata.st_dev
                    self.st_ino = metadata.st_ino
                    self.st_size = metadata.st_size
                    self.st_mtime_ns = metadata.st_mtime_ns
                    self.st_file_attributes = getattr(
                        recovery_state.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                    )

            def lstat_with_junction(path: Path) -> object:
                metadata = original_lstat(path)
                return ReparseMetadata(metadata) if path == junction else metadata

            with mock.patch.object(
                Path, "lstat", autospec=True, side_effect=lstat_with_junction
            ), self.assertRaisesRegex(
                recovery_state.RecoveryStateError, "reparse point"
            ):
                owner._record_path(
                    "junction/child.txt",
                    key=os.urandom(32),
                    records={},
                    aliases={},
                    budget={"records": 0, "bytes": 0},
                    recurse=False,
                )

    def test_snapshot_rejects_a_file_swap_between_lstat_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            allowed = workspace / "allowed.txt"
            outside = root / "outside.txt"
            allowed.write_text("inside\n", encoding="utf-8", newline="\n")
            outside.write_text("outside\n", encoding="utf-8", newline="\n")
            original_hash_file = owner._hash_file

            def swap_then_hash(*args: object, **kwargs: object) -> tuple[str, str]:
                allowed.unlink()
                os.link(outside, allowed)
                return original_hash_file(*args, **kwargs)

            with mock.patch.object(
                owner, "_hash_file", side_effect=swap_then_hash
            ), self.assertRaisesRegex(
                recovery_state.RecoveryStateError, "changed during snapshot"
            ):
                owner._record_path(
                    "allowed.txt",
                    key=os.urandom(32),
                    records={},
                    aliases={},
                    budget={"records": 0, "bytes": 0},
                    recurse=False,
                )

    def test_snapshot_rejects_a_directory_swap_before_scandir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            allowed = workspace / "race-dir"
            outside = root / "outside-race-dir"
            saved = workspace / "saved-race-dir"
            allowed.mkdir()
            outside.mkdir()
            (allowed / "inside.txt").write_text("inside\n", encoding="utf-8", newline="\n")
            (outside / "outside.txt").write_text("outside\n", encoding="utf-8", newline="\n")
            original_scandir = recovery_state.os.scandir

            def swap_then_scandir(path: object) -> object:
                allowed.rename(saved)
                outside.rename(allowed)
                return original_scandir(path)

            with mock.patch.object(
                recovery_state.os, "scandir", side_effect=swap_then_scandir
            ), self.assertRaisesRegex(
                recovery_state.RecoveryStateError,
                "changed during snapshot|directory enumeration failed",
            ):
                owner._record_path(
                    "race-dir",
                    key=os.urandom(32),
                    records={},
                    aliases={},
                    budget={"records": 0, "bytes": 0},
                    recurse=True,
                )

    def test_checkpoint_rejects_ignored_drift_aliases_limits_and_key_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            (workspace / "ignored" / "cache.txt").write_text("changed ignored\n", encoding="utf-8", newline="\n")
            changed = owner.revalidate_checkpoint(checkpoint)
            self.assertEqual(changed["disposition"], "recovery-ineligible")
            self.assertIn("outside-set-drift", changed["reasons"])

            source_path = owner.source_path(checkpoint["source_state_id"])
            private = json.loads(source_path.read_text(encoding="utf-8"))
            private["checkpoint_key"] = os.urandom(32).hex()
            source_path.write_text(json.dumps(private), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "key|digest"):
                owner.revalidate_checkpoint(checkpoint)

        if hasattr(os, "link"):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = self.make_git_workspace(root)
                os.link(workspace / "allowed" / "seed.txt", workspace / "allowed" / "alias.txt")
                owner = self.owner(workspace, root / "state")
                owner.initialize()
                with self.assertRaisesRegex(recovery_state.RecoveryStateError, "alias"):
                    self.checkpoint(owner)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state", max_records=1)
            owner.initialize()
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "limit"):
                self.checkpoint(owner)

    def test_authorization_is_durable_epoch_bound_and_consumed_with_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            (workspace / "allowed" / "seed.txt").write_text("worker\n", encoding="utf-8", newline="\n")
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="c" * 64,
                specification_revision="R-029",
            )
            private = owner.read_private_source(checkpoint["source_state_id"])
            self.assertEqual(private["authorization"]["grant_id"], grant["grant_id"])
            self.assertEqual(len(bytes.fromhex(private["authorization"]["authorization_nonce"])), 32)
            self.assertNotIn("authorization_nonce", json.dumps(grant, sort_keys=True))
            self.assertEqual(
                owner.grant_authorization(
                    checkpoint,
                    user_action_digest="c" * 64,
                    specification_revision="R-029",
                ),
                grant,
            )
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "immutable"):
                owner.grant_authorization(
                    checkpoint,
                    user_action_digest="f" * 64,
                    specification_revision="R-029",
                )

            state = owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "recovery-target-1",
                    "run_id": "target-run-1",
                    "prompt_sha256": "d" * 64,
                    "launch_token": "e" * 64,
                    "provider_plan_id": "provider-plan-1",
                    "ipc_plan_id": "ipc-plan-1",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            self.assertEqual(state["lease"]["state"], "reserved")
            self.assertEqual(state["lease"]["lease_kind"], "recovery-target")
            self.assertEqual(state["consumed_grants"][-1]["grant_id"], grant["grant_id"])
            self.assertNotIn("process_receipt", state["lease"])
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "vacant|consumed"):
                owner.consume_grant_and_reserve(
                    grant_id=grant["grant_id"],
                    checkpoint=checkpoint,
                    target_plan=state["lease"]["plan"],
                )

    def test_grant_epoch_and_allowed_binding_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="c" * 64,
                specification_revision="R-029",
            )
            owner.rotate_epoch_for_test()
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "epoch"):
                owner.consume_grant_and_reserve(
                    grant_id=grant["grant_id"],
                    checkpoint=checkpoint,
                    target_plan={
                        "lease_id": "recovery-target-1",
                        "run_id": "target-run-1",
                        "prompt_sha256": "d" * 64,
                        "launch_token": "e" * 64,
                        "provider_plan_id": "provider-plan-1",
                        "ipc_plan_id": "ipc-plan-1",
                        "allowed_set_digest": checkpoint["allowed_set_digest"],
                    },
                )

    def test_target_actual_receipts_appear_only_at_process_bound_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = self.checkpoint(owner)
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="c" * 64,
                specification_revision="R-029",
            )
            reserved = owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "target-lease",
                    "run_id": "target-run",
                    "prompt_sha256": "d" * 64,
                    "launch_token": "e" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            self.assertNotIn("process_receipt", reserved["lease"])
            claimed = owner.claim_launch("target-lease", "e" * 64)
            self.assertEqual(claimed["lease"]["state"], "launch-claimed")
            bound = owner.bind_process_unactivated(
                "target-lease",
                allowed_set_digest=checkpoint["allowed_set_digest"],
                provider_receipt=self.provider_receipt(
                    provider_plan_id="provider-plan", ipc_plan_id="ipc-plan"
                ),
                process_receipt=self.process_receipt(),
            )
            self.assertEqual(bound["lease"]["state"], "process-bound-unactivated")

    def test_recovery_target_preboundary_failure_is_terminal_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            checkpoint = owner.revalidate_checkpoint(self.checkpoint(owner))
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="c" * 64,
                specification_revision="R-029",
            )
            owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "target-lease",
                    "run_id": "target-run",
                    "prompt_sha256": "d" * 64,
                    "launch_token": "e" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            owner.claim_launch("target-lease", "e" * 64)
            failed = owner.fail_recovery_target_before_boundary(
                "target-lease",
                "provider-attach-failed",
                {"tree_empty": True, "no_user_code": True},
            )

            self.assertIsNone(failed["lease"])
            self.assertEqual(failed["history"][-1]["event"], "recovery-target-start-failed")
            self.assertEqual(
                owner.public_checkpoint_for_source(checkpoint["source_state_id"])[
                    "checkpoint_digest"
                ],
                checkpoint["checkpoint_digest"],
            )

    def test_guardian_owned_boundary_commit_is_decidable_for_every_durable_fault(self) -> None:
        fault_outcomes = {
            "before-write": "prior",
            "after-file-fsync": "prior",
            "after-replace": "committed",
            "before-metadata-barrier": "committed",
            "after-metadata-barrier": "committed",
        }
        for lease_kind in ("source", "target"):
            for fault, expected_outcome in fault_outcomes.items():
                with self.subTest(
                    lease_kind=lease_kind,
                    fault=fault,
                ), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    workspace = self.make_git_workspace(root)
                    state_root = root / "state"
                    owner = self.owner(workspace, state_root)
                    owner.initialize()
                    if lease_kind == "source":
                        preflight = self.reserve_source(owner, lease_id="source-lease")
                        owner.claim_contained_launch("source-lease", "contained-token")
                        lease_id = "source-lease"
                        allowed_set_digest = preflight["allowed_set_digest"]
                        expected_state = "normal-preflight-launch-claimed"
                    else:
                        checkpoint = owner.revalidate_checkpoint(self.checkpoint(owner))
                        grant = owner.grant_authorization(
                            checkpoint,
                            user_action_digest="c" * 64,
                            specification_revision="R-029",
                        )
                        owner.consume_grant_and_reserve(
                            grant_id=grant["grant_id"],
                            checkpoint=checkpoint,
                            target_plan={
                                "lease_id": "target-lease",
                                "run_id": "target-run",
                                "prompt_sha256": "d" * 64,
                                "launch_token": "e" * 64,
                                "provider_plan_id": "provider-plan",
                                "ipc_plan_id": "ipc-plan",
                                "allowed_set_digest": checkpoint["allowed_set_digest"],
                            },
                        )
                        owner.claim_launch("target-lease", "e" * 64)
                        lease_id = "target-lease"
                        allowed_set_digest = checkpoint["allowed_set_digest"]
                        expected_state = "launch-claimed"

                    faulting_guardian_owner = self.owner(workspace, state_root, fault=fault)

                    def bind_boundary() -> dict[str, object]:
                        provider_plan_id = (
                            "provider-plan-1" if lease_kind == "source" else "provider-plan"
                        )
                        ipc_plan_id = "ipc-plan-1" if lease_kind == "source" else "ipc-plan"
                        return faulting_guardian_owner.bind_process_unactivated(
                            lease_id,
                            allowed_set_digest=allowed_set_digest,
                            provider_receipt=self.provider_receipt(
                                provider_plan_id=provider_plan_id,
                                ipc_plan_id=ipc_plan_id,
                            ),
                            process_receipt=self.process_receipt(),
                        )

                    if expected_outcome == "prior":
                        with self.assertRaises(recovery_state.RecoveryStateError):
                            bind_boundary()
                        recovered = self.owner(workspace, state_root).state()
                        self.assertEqual(recovered["lease"]["state"], expected_state)
                        self.assertNotIn("process_receipt", recovered["lease"])
                    else:
                        committed = bind_boundary()
                        self.assertEqual(
                            committed["lease"]["state"],
                            "process-bound-unactivated",
                        )
                        recovered = self.owner(workspace, state_root).state_for_activation()
                        self.assertEqual(recovered["digest"], committed["digest"])
                        self.assertEqual(
                            recovered["lease"]["process_receipt"]["identity"],
                            "private-process",
                        )

    def test_contained_terminalization_requires_zero_proof_handoff_archive_and_guardian_close(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(True), preflight["allowed_set_digest"]
            )
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "zero proof"):
                owner.prove_contained_tree_empty(
                    "normal-1", {"populated": False}, preflight["allowed_set_digest"]
                )
            owner.prove_contained_tree_empty(
                "normal-1",
                self.zero_proof(),
                preflight["allowed_set_digest"],
            )
            owner.commit_handoff(
                "normal-1",
                self.handoff_event(preflight["allowed_set_digest"]),
                preflight["allowed_set_digest"],
            )
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "guardian close"):
                owner.release_contained_terminal("normal-1")
            owner.materialize_handoff("normal-1", owner.directory / "handoff-events.jsonl")
            owner.acknowledge_guardian_close("normal-1", self.guardian_close())
            released = owner.release_contained_terminal("normal-1")
            self.assertIsNone(released["lease"])
            self.assertIsNone(released["outbox"])
            archive = released["history"][-1]
            self.assertEqual(archive["event"], "contained-terminal-released")
            self.assertTrue(archive["terminal_success"])
            self.assertIsNone(archive["semantic_disposition"])
            for field in (
                "terminal_receipt_digest",
                "zero_proof_digest",
                "guardian_close_digest",
                "handoff_digest",
                "outbox_digest",
                "archive_digest",
            ):
                self.assertRegex(archive[field], r"^[0-9a-f]{64}$")

            corrupted = json.loads(owner.path.read_text(encoding="utf-8"))
            corrupted["history"][-1]["zero_proof_digest"] = "0" * 64
            corrupted["digest"] = recovery_state._digest(corrupted)
            owner.path.write_text(
                json.dumps(corrupted, sort_keys=True), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(
                recovery_state.RecoveryStateError, "terminal archive"
            ):
                owner.state()

    def test_failed_contained_terminal_retains_privacy_safe_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(False), preflight["allowed_set_digest"]
            )
            owner.prove_contained_tree_empty(
                "normal-1",
                self.zero_proof(),
                preflight["allowed_set_digest"],
            )
            owner.acknowledge_guardian_close("normal-1", self.guardian_close())
            released = owner.release_contained_terminal("normal-1")

            archive = released["history"][-1]
            self.assertFalse(archive["terminal_success"])
            self.assertIsNone(archive["semantic_disposition"])
            self.assertIsNone(archive["handoff_digest"])
            self.assertIsNone(archive["outbox_digest"])

    def test_semantic_rejection_blocks_handoff_replay_and_allows_safe_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="blocked-run",
                source_lease_id="normal-1",
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed"],
                specification_revision="R-029",
            )
            owner.reserve_normal(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id="blocked-run",
                containment_plan=self.containment_plan(),
            )
            owner.bind_reserved_source_snapshot("normal-1", preflight)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            (workspace / "allowed" / "seed.txt").write_text(
                "blocked edit\n", encoding="utf-8", newline="\n"
            )
            checkpoint = owner.finalize_prepared_checkpoint(
                preflight,
                source_receipt_digest="a" * 64,
            )
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(True), preflight["allowed_set_digest"]
            )
            owner.prove_contained_tree_empty(
                "normal-1",
                self.zero_proof(),
                preflight["allowed_set_digest"],
            )
            rejected = owner.reject_semantic_handoff(
                "normal-1",
                run_id="blocked-run",
                disposition="blocked",
                evidence_digest="c" * 64,
                checkpoint_allowed=True,
            )

            self.assertFalse(rejected["lease"]["terminal_receipt"]["success"])
            self.assertIsNone(rejected["outbox"])
            self.assertEqual(owner.revalidate_checkpoint(checkpoint)["disposition"], "recovery-eligible")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "accepted successful"):
                owner.commit_handoff(
                    "normal-1",
                    {"event_id": "forbidden", "payload": {"ok": True}},
                    preflight["allowed_set_digest"],
                )
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "already consumed"):
                owner.reject_semantic_handoff(
                    "normal-1",
                    run_id="blocked-run",
                    disposition="blocked",
                    evidence_digest="c" * 64,
                    checkpoint_allowed=True,
                )
            owner.acknowledge_guardian_close("normal-1", self.guardian_close())
            released = owner.release_contained_terminal("normal-1")
            self.assertIsNone(released["lease"])
            archive = released["history"][-1]
            self.assertEqual(archive["semantic_disposition"], "blocked")
            self.assertRegex(archive["semantic_disposition_digest"], r"^[0-9a-f]{64}$")
            self.assertTrue(
                any(event["event"] == "semantic-handoff-rejected" for event in released["history"])
            )

    def test_needs_escalation_invalidates_zero_write_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_git_workspace(root)
            owner = self.owner(workspace, root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="escalation-run",
                source_lease_id="normal-1",
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed"],
                specification_revision="R-029",
            )
            checkpoint = owner.finalize_prepared_checkpoint(
                preflight,
                source_receipt_digest="a" * 64,
            )
            owner.reserve_normal(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id="escalation-run",
                containment_plan=self.containment_plan(),
            )
            owner.bind_reserved_source_snapshot("normal-1", preflight)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(True), preflight["allowed_set_digest"]
            )
            owner.prove_contained_tree_empty(
                "normal-1",
                self.zero_proof(),
                preflight["allowed_set_digest"],
            )
            owner.reject_semantic_handoff(
                "normal-1",
                run_id="escalation-run",
                disposition="needs-escalation",
                evidence_digest="d" * 64,
                checkpoint_allowed=False,
            )
            invalidated = owner.invalidate_source_checkpoint(
                preflight["source_state_id"],
                reason="semantic-needs-escalation",
                evidence_digest="d" * 64,
            )

            self.assertEqual(invalidated["disposition"], "recovery-ineligible")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "semantic escalation"):
                owner.revalidate_checkpoint(checkpoint)
            with self.assertRaisesRegex(
                recovery_state.RecoveryStateError, "completed checkpoint invalidation"
            ):
                owner.acknowledge_guardian_close("normal-1", self.guardian_close())
            completed = owner.complete_source_checkpoint_invalidation(
                "normal-1",
                source_state_id=preflight["source_state_id"],
                checkpoint_digest=invalidated["checkpoint_digest"],
                evidence_digest="d" * 64,
            )
            self.assertEqual(
                completed["lease"]["semantic_disposition"]["checkpoint_invalidation"],
                "completed",
            )
            repeated = owner.invalidate_source_checkpoint(
                preflight["source_state_id"],
                reason="semantic-needs-escalation",
                evidence_digest="d" * 64,
            )
            self.assertEqual(repeated["checkpoint_digest"], invalidated["checkpoint_digest"])
            owner.complete_source_checkpoint_invalidation(
                "normal-1",
                source_state_id=preflight["source_state_id"],
                checkpoint_digest=invalidated["checkpoint_digest"],
                evidence_digest="d" * 64,
            )
            owner.acknowledge_guardian_close("normal-1", self.guardian_close())
            released = owner.release_contained_terminal("normal-1")
            self.assertIsNone(released["lease"])
            archive = released["history"][-1]
            self.assertEqual(archive["semantic_disposition"], "needs-escalation")
            self.assertRegex(archive["semantic_disposition_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                sum(
                    event.get("event") == "source-checkpoint-invalidated"
                    for event in released["history"]
                ),
                1,
            )

    def test_normal_fallback_is_one_shot_and_becomes_recovery_incapable_before_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.containment_failed_before_boundary("normal-1", "provider-create-failed")
            owner.prove_fallback_teardown("normal-1", {"tree_empty": True, "no_user_code": True})
            fallback = owner.claim_normal_fallback("normal-1", "fallback-token")
            self.assertEqual(fallback["lease"]["lease_kind"], "normal-fallback")
            self.assertFalse(fallback["lease"]["recovery_capable"])
            self.assertEqual(fallback["lease"]["state"], "ordinary-fallback-claimed")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "teardown-proved"):
                owner.claim_normal_fallback("normal-1", "second-token")

            bound = owner.bind_fallback_process_unactivated(
                "normal-1",
                process_receipt={"run_id": "fallback-run", "identity": "fallback-process"},
            )
            self.assertEqual(bound["lease"]["state"], "ordinary-process-bound-unactivated")
            active = owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            self.assertEqual(active["lease"]["state"], "legacy-running")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "stopped"):
                owner.release_legacy_terminal("normal-1", {"success": False, "process_tree_stopped": False})
            released = owner.release_legacy_terminal(
                "normal-1",
                {"success": False, "process_tree_stopped": True},
            )
            self.assertIsNone(released["lease"])
            self.assertEqual(released["history"][-1]["event"], "legacy-terminal-released")

    def test_fallback_process_bind_is_decidable_for_every_durable_fault(self) -> None:
        fault_outcomes = {
            "before-write": "prior",
            "after-file-fsync": "prior",
            "after-replace": "committed",
            "before-metadata-barrier": "committed",
            "after-metadata-barrier": "committed",
        }
        process_receipt = {"run_id": "fallback-run", "identity": "fallback-process"}
        for fault, expected_outcome in fault_outcomes.items():
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = self.make_git_workspace(root)
                state_root = root / "state"
                owner = self.owner(workspace, state_root)
                self.reserve_source(owner)
                owner.claim_contained_launch("normal-1", "contained-token")
                owner.containment_failed_before_boundary("normal-1", "provider-create-failed")
                owner.prove_fallback_teardown(
                    "normal-1", {"tree_empty": True, "no_user_code": True}
                )
                owner.claim_normal_fallback("normal-1", "fallback-token")
                faulting_owner = self.owner(workspace, state_root, fault=fault)

                def bind_fallback() -> dict[str, object]:
                    return faulting_owner.bind_fallback_process_unactivated(
                        "normal-1", process_receipt=process_receipt
                    )

                if expected_outcome == "prior":
                    with self.assertRaises(recovery_state.RecoveryStateError):
                        bind_fallback()
                    recovered = self.owner(workspace, state_root).state()
                    self.assertEqual(recovered["lease"]["state"], "ordinary-fallback-claimed")
                    self.assertNotIn("process_receipt", recovered["lease"])
                else:
                    committed = bind_fallback()
                    self.assertEqual(
                        committed["lease"]["state"], "ordinary-process-bound-unactivated"
                    )
                    self.assertEqual(committed["lease"]["process_receipt"], process_receipt)
                    recovered = self.owner(workspace, state_root).state_for_activation()
                    self.assertEqual(recovered["digest"], committed["digest"])
                    self.assertEqual(recovered["lease"]["process_receipt"], process_receipt)

    def test_ambiguous_fallback_launch_is_quarantined_without_ordinary_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.containment_failed_before_boundary("normal-1", "provider-create-failed")
            owner.prove_fallback_teardown(
                "normal-1", {"tree_empty": True, "no_user_code": True}
            )
            owner.claim_normal_fallback("normal-1", "fallback-token")
            quarantined = owner.quarantine_fallback_launch(
                "normal-1", "fallback-spawn-or-identity-ambiguous"
            )

            self.assertEqual(quarantined["quarantine"], "fallback-launch-ambiguous")
            self.assertEqual(quarantined["lease"]["state"], "ordinary-fallback-claimed")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "quarantined"):
                owner.release_legacy_terminal(
                    "normal-1", {"success": False, "process_tree_stopped": True}
                )

    def test_handoff_outbox_materializes_once_and_rejects_trace_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            owner.record_terminal_evidence(
                "normal-1", self.terminal_receipt(True), preflight["allowed_set_digest"]
            )
            owner.prove_contained_tree_empty(
                "normal-1",
                self.zero_proof(),
                preflight["allowed_set_digest"],
            )
            owner.commit_handoff(
                "normal-1",
                self.handoff_event(preflight["allowed_set_digest"]),
                preflight["allowed_set_digest"],
            )
            trace = owner.directory / "private-trace.jsonl"
            materialized = owner.materialize_handoff("normal-1", trace)
            self.assertEqual(materialized["outbox"]["state"], "materialized")
            self.assertEqual(len(trace.read_text(encoding="utf-8").splitlines()), 1)
            deduplicated = owner.materialize_handoff("normal-1", trace)
            self.assertEqual(deduplicated["outbox"]["state"], "materialized")
            self.assertEqual(len(trace.read_text(encoding="utf-8").splitlines()), 1)

            trace.write_text(
                json.dumps({"event_id": "f" * 64, "payload": {"ok": False}, "digest": "x" * 64})
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "quarantined"):
                owner.materialize_handoff("normal-1", trace)
            self.assertEqual(owner.state()["quarantine"], "handoff-trace-mismatch")

    def test_post_boundary_containment_loss_quarantines_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "quarantined"):
                owner.containment_failed_before_boundary("normal-1", "guardian-lost")
            self.assertEqual(owner.state()["quarantine"], "containment-loss-after-boundary")

    def test_running_guardian_loss_retains_and_quarantines_the_same_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            preflight = self.reserve_source(owner)
            owner.claim_contained_launch("normal-1", "contained-token")
            owner.bind_process_unactivated(
                "normal-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=self.provider_receipt(),
                process_receipt=self.process_receipt(),
            )
            owner.commit_activation("normal-1", preflight["allowed_set_digest"])
            quarantined = owner.quarantine_containment_loss("normal-1", "provider-query-failed")

            self.assertEqual(quarantined["quarantine"], "containment-loss-after-boundary")
            self.assertEqual(quarantined["lease"]["lease_id"], "normal-1")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "quarantined"):
                owner.reserve_normal("normal-2", allowed_set_digest="c" * 64, recovery_capable=False)

    def test_after_replace_failure_is_rebarriered_on_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self.make_git_workspace(root)
            state_root = root / "state"
            owner = self.owner(workspace, state_root, fault="after-replace")
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "after registry replace"):
                owner.initialize()
            recovered = self.owner(workspace, state_root).state_for_activation()
            self.assertEqual(recovered["generation"], 1)
            self.assertIsNone(recovered["quarantine"])

    def test_durable_replace_faults_reload_as_old_or_complete_generation(self) -> None:
        for fault, replacement_visible in [
            ("before-write", False),
            ("after-file-fsync", False),
            ("before-metadata-barrier", True),
            ("after-metadata-barrier", True),
        ]:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = self.make_git_workspace(root)
                state_root = root / "state"
                owner = self.owner(workspace, state_root, fault=fault)
                with self.assertRaises(recovery_state.RecoveryStateError):
                    owner.initialize()
                recovered_owner = self.owner(workspace, state_root)
                recovered = (
                    recovered_owner.state_for_activation()
                    if replacement_visible
                    else recovered_owner.initialize()
                )
                self.assertEqual(recovered["generation"], 1)
                self.assertEqual(recovered["digest"], recovery_state._digest(recovered))

    @unittest.skipUnless(
        os.path.normcase("Missing.txt") == os.path.normcase("missing.txt"),
        "case-insensitive filesystem collation",
    )
    def test_nonexisting_case_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = self.owner(self.make_git_workspace(root), root / "state")
            owner.initialize()
            with self.assertRaisesRegex(recovery_state.RecoveryStateError, "alias"):
                self.checkpoint(owner, allowed_paths=["Missing.txt", "missing.txt"])


if __name__ == "__main__":
    unittest.main()
