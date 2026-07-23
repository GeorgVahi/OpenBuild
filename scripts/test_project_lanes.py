"""Focused M1 tests for the private project coordinator state."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "openbuild" / "skills" / "build" / "scripts"))

from project_state import (  # type: ignore[import-not-found]
    ProjectStateError,
    ProjectStateStore,
    ENTRY_POINT_TRANSITIONS,
    NAMED_READS,
    PROMPT_READ_REFERENCE_MAP,
    TRANSITION_REGISTRY,
    TRANSITION_IDS,
    _digest,
    validate_transition_registry,
    validate_scope_state,
)
from project_lanes import ProjectLaneCoordinator, ProjectLaneError  # type: ignore[import-not-found]
from project_scopes import ProjectScopeError, ProjectScopeManager  # type: ignore[import-not-found]
from recovery_state import RecoveryRegistry, RecoveryStateError  # type: ignore[import-not-found]


class ProjectStateM1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.temp_path = self.root / f".project-state-{next(tempfile._get_candidate_names())}"
        self.project = self.temp_path / "project"
        self.project.mkdir(parents=True)
        self.coordinator = self.temp_path / "coordinator"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_path, ignore_errors=True)

    def store(self) -> ProjectStateStore:
        return ProjectStateStore(self.project, coordinator_root=self.coordinator)

    def capability(
        self,
        store: ProjectStateStore,
        plan_id: str = "plan-a",
        attempt_id: str = "attempt-1",
    ) -> str:
        store.ensure_setup()
        return store.issue_bootstrap_capability(plan_id, attempt_id)["bootstrap_capability"]

    def test_concurrent_setup_anchor_and_clean_bootstrap_converge(self) -> None:
        store = self.store()
        capability = self.capability(store)

        def bootstrap(_: int) -> tuple[str, str, int, str]:
            store = self.store()
            anchor = store.create_anchor(capability, "plan-a", "attempt-1")
            state = store.bootstrap(anchor["anchor_id"], "clean")
            return setup["key_id"], anchor["lock_id"], state["generation"], anchor["anchor_id"]

        setup = store.ensure_setup()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values = []
            failures = 0
            for future in [pool.submit(bootstrap, index) for index in range(8)]:
                try:
                    values.append(future.result())
                except ProjectStateError:
                    failures += 1
        self.assertEqual(failures, 7)
        self.assertEqual(len(set(values)), 1)
        public = self.store().read_state(values[0][3])
        self.assertEqual(public["status"], "present")
        self.assertEqual(public["state"]["state"], "clean")
        self.assertIsNone(public["state"]["incident_id"])

    def test_capability_is_single_use_and_project_plan_bound(self) -> None:
        cap = self.capability(self.store())
        first = self.store().create_anchor(cap, "plan-a", "attempt-1")
        with self.assertRaisesRegex(ProjectStateError, "consumed"):
            self.store().create_anchor(cap, "plan-a", "attempt-1")
        with self.assertRaises(ProjectStateError):
            self.store().create_anchor(cap, "plan-b", "attempt-1")
        other_path = self.temp_path / "other"
        other_path.mkdir()
        other = ProjectStateStore(other_path, coordinator_root=self.coordinator)
        with self.assertRaises(ProjectStateError):
            other.create_anchor(cap, "plan-a", "attempt-1")
        self.assertTrue((self.store().anchor_path(first["anchor_id"]) / "anchor.lock").is_file())

    def test_capability_mismatch_rejects_before_the_first_ba0_sink(self) -> None:
        cap = self.capability(self.store())
        anchors = self.coordinator / "anchors"
        with self.assertRaises(ProjectStateError):
            self.store().create_anchor(cap, "plan-b", "attempt-1")
        self.assertFalse(anchors.exists(), "a rejected capability must not construct a BA0 sink")

    def test_crash_resume_uses_the_durable_cursor_and_exact_outcome(self) -> None:
        cap = self.capability(self.store())
        interrupted = ProjectStateStore(
            self.project,
            coordinator_root=self.coordinator,
            fault="after-capability-consume",
        )
        with self.assertRaisesRegex(ProjectStateError, "injected"):
            interrupted.create_anchor(cap, "plan-a", "attempt-1")
        recovered = self.store().resume_anchor(cap, "plan-a", "attempt-1")
        self.assertEqual(recovered, self.store().read_anchor(recovered["anchor_id"])["anchor"])
        with self.assertRaisesRegex(ProjectStateError, "consumed"):
            self.store().create_anchor(cap, "plan-a", "attempt-1")

    def test_anchor_publish_is_private_durable_and_never_replaces_the_lock(self) -> None:
        cap = self.capability(self.store())
        delayed = ProjectStateStore(
            self.project,
            coordinator_root=self.coordinator,
            fault="after-anchor-temp-sync",
        )
        with self.assertRaisesRegex(ProjectStateError, "injected"):
            delayed.create_anchor(cap, "plan-a", "attempt-1")
        anchor = self.store().resume_anchor(cap, "plan-a", "attempt-1")
        directory = self.store().anchor_path(anchor["anchor_id"])
        self.assertEqual(sorted(path.name for path in directory.iterdir()), ["anchor.lock", "manifest.json"])
        lock_identity = (directory / "anchor.lock").stat().st_ino
        self.store().bootstrap(anchor["anchor_id"], "clean")
        self.assertEqual(lock_identity, (directory / "anchor.lock").stat().st_ino)
        state = self.coordinator / "states" / f"{anchor['anchor_id']}.json"
        self.assertTrue(state.is_file())

    @unittest.skipIf(os.name == "nt", "symlink creation is not a portable test permission")
    def test_private_root_rejects_a_symlink_ancestor(self) -> None:
        target = self.temp_path / "target"
        target.mkdir()
        link = self.temp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        unsafe = ProjectStateStore(self.project, coordinator_root=link / "coordinator")
        with self.assertRaisesRegex(ProjectStateError, "link or reparse"):
            unsafe.ensure_setup()

    def test_lock_key_schema_and_breach_split_fail_closed(self) -> None:
        anchor = self.store().create_anchor(self.capability(self.store()), "plan-a", "attempt-1")
        breach = self.store().bootstrap(anchor["anchor_id"], "indeterminate")
        self.assertEqual(breach["state"], "breach")
        self.assertIn("incident_id", breach)
        anchor_path = self.store().anchor_path(anchor["anchor_id"])
        (anchor_path / "manifest.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.store().read_state(anchor["anchor_id"]), {"status": "indeterminate"})

    def test_registry_is_complete_and_named_reads_are_sink_free(self) -> None:
        self.assertEqual(len(TRANSITION_IDS), len(set(TRANSITION_IDS)))
        for required in ("I0", "BA0", "B0", *("O" + str(number) for number in range(1, 9)), "S", "BS", "R", "TST"):
            self.assertIn(required, TRANSITION_IDS)
        self.assertEqual(validate_transition_registry(TRANSITION_REGISTRY), [])
        self.assertEqual(
            set(NAMED_READS),
            {"read_status", "read_setup", "read_anchor", "read_state", "read_lanes", "read_milestones", "read_scopes", "read_private_source"},
        )
        self.assertIn("agent_runner.read_owner_prompt_snapshot", PROMPT_READ_REFERENCE_MAP.values())
        self.assertIn("RecoveryRegistry.read_private_source", ENTRY_POINT_TRANSITIONS)
        before = list(self.coordinator.rglob("*")) if self.coordinator.exists() else []
        store = self.store()
        self.assertEqual(store.read_status(), {"status": "setup-required"})
        for name in NAMED_READS:
            result = getattr(store, name)()
            self.assertIn(result["status"], {"setup-required", "absent", "indeterminate"})
        after = list(self.coordinator.rglob("*")) if self.coordinator.exists() else []
        self.assertEqual(before, after)

    def test_named_reads_are_typed_and_do_not_call_a_sink(self) -> None:
        store = self.store()
        anchor = store.create_anchor(self.capability(store), "plan-a", "attempt-1")
        store.bootstrap(anchor["anchor_id"], "clean")
        before = sorted(path.relative_to(self.temp_path).as_posix() for path in self.temp_path.rglob("*"))
        real_open = os.open

        def read_only_open(path: object, flags: int, *args: object) -> int:
            self.assertEqual(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_EXCL), 0)
            return real_open(path, flags, *args)

        with mock.patch("project_state._ensure_private_directory", side_effect=AssertionError("mkdir")), \
             mock.patch("project_state._write_exclusive_json", side_effect=AssertionError("write")), \
             mock.patch("project_state._replace_json", side_effect=AssertionError("replace")), \
             mock.patch("project_state._locked", side_effect=AssertionError("lock")), \
             mock.patch("project_state.secrets.token_hex", side_effect=AssertionError("key")), \
             mock.patch("project_state.os.open", side_effect=read_only_open), \
             mock.patch("project_state.os.chmod", side_effect=AssertionError("chmod")), \
             mock.patch("project_state.os.fsync", side_effect=AssertionError("fsync")):
            for name in NAMED_READS:
                result = getattr(store, name)(anchor["anchor_id"])
                expected = (
                    "setup-ready"
                    if name in {"read_status", "read_setup"}
                    else "present"
                )
                self.assertEqual(result["status"], expected)
        after = sorted(path.relative_to(self.temp_path).as_posix() for path in self.temp_path.rglob("*"))
        self.assertEqual(before, after)

    def test_scope_schema_and_prompt_stage_mapping(self) -> None:
        self.assertEqual(TRANSITION_IDS["O" + "4"], "R-031.M1.O4.prompt-snapshot.stage")
        self.assertEqual(validate_scope_state({"kind": "file", "path": "src/a.py", "mode": "hard"})["mode"], "hard")
        with self.assertRaises(ProjectStateError):
            validate_scope_state({"kind": "file", "path": "../escape", "mode": "hard"})


class ProjectLaneM2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_context = tempfile.TemporaryDirectory(prefix="openbuild-project-lanes-")
        self.temp = Path(self.temp_context.name)
        self.checkout = self.temp / "checkout"
        self.checkout.mkdir(parents=True)
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.checkout / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "-m", "base")
        self.integration_ref = "refs/openbuild/integration"
        self.git("update-ref", self.integration_ref, "HEAD")
        self.coordinator = self.temp / "coordinator"
        self.recovery = self.temp / "recovery"
        self.lanes = self.temp / "lanes"
        self.lanes.mkdir()
        self.store = ProjectStateStore(self.checkout, coordinator_root=self.coordinator)
        cap = self.store.issue_bootstrap_capability("plan", "attempt")["bootstrap_capability"]
        self.anchor = self.store.create_anchor(cap, "plan", "attempt")["anchor_id"]
        self.store.bootstrap(self.anchor, "clean")

    def tearDown(self) -> None:
        self.temp_context.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> None:
        subprocess.run(["git", *args], cwd=cwd or self.checkout, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def coordinator_for(self, *, fault: str | None = None) -> ProjectLaneCoordinator:
        return ProjectLaneCoordinator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery,
            lane_root=self.lanes,
            integration_ref=self.integration_ref,
            fault=fault,
        )

    def test_exact_m1_schema_one_state_migrates_on_first_lane_session_bind(self) -> None:
        state_path = self.coordinator / "states" / f"{self.anchor}.json"
        legacy = {
            "schema": 1,
            "generation": 0,
            "epoch": 0,
            "state": "clean",
            "registry": "B0",
            "incident_id": None,
            "lanes": [],
            "milestones": [],
            "scopes": [],
        }
        legacy["digest"] = hashlib.sha256(
            json.dumps(
                legacy,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        state_path.write_text(
            json.dumps(
                legacy,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        before = state_path.read_bytes()

        observed = self.store.read_state(self.anchor)

        self.assertEqual(observed["status"], "present")
        self.assertIsNone(observed["state"]["lane_session"])
        self.assertEqual(state_path.read_bytes(), before)

        self.coordinator_for()
        migrated = self.store.read_state(self.anchor)["state"]
        self.assertEqual(migrated["generation"], 1)
        self.assertEqual(migrated["lane_session"]["reader_floor"], "2.3.6")
        self.assertNotEqual(state_path.read_bytes(), before)

    def test_two_lanes_get_independent_worktrees_and_local_registry_reservations(self) -> None:
        coordinator = self.coordinator_for()
        one = coordinator.create("lane-one", "M2", self.lanes / "one", ["one.py"])
        two = coordinator.create("lane-two", "M2", self.lanes / "two", ["two.py"])
        self.assertEqual((one["state"], two["state"]), ("ready", "ready"))
        self.assertNotEqual(one["worktree"], two["worktree"])
        self.assertNotEqual(one["branch"], two["branch"])
        registry = RecoveryRegistry(Path(one["worktree"]), state_root=self.recovery)
        registry.reserve_normal("one-writer", allowed_set_digest="a" * 64, recovery_capable=False)
        with self.assertRaises(RecoveryStateError):
            registry.reserve_normal("another", allowed_set_digest="a" * 64, recovery_capable=False)

    def test_runner_binding_confines_allowed_paths_to_the_registered_lane(self) -> None:
        coordinator = self.coordinator_for()
        lane = coordinator.create(
            "runner-bound",
            "M2",
            self.lanes / "runner-bound",
            ["src"],
        )
        binding = coordinator.runner_writer_binding(
            "runner-bound",
            Path(lane["worktree"]),
            ["src/owned.py"],
            require_ready=True,
        )
        self.assertEqual(binding["schema"], "project-lane-runner-v1")
        self.assertEqual(binding["allowed_paths"], ["src/owned.py"])
        self.assertEqual(
            coordinator.verify_runner_writer_binding(
                binding,
                Path(lane["worktree"]),
            ),
            binding,
        )
        with self.assertRaisesRegex(ProjectLaneError, "escapes"):
            coordinator.runner_writer_binding(
                "runner-bound",
                Path(lane["worktree"]),
                ["outside.py"],
                require_ready=True,
            )
        tampered = dict(binding)
        tampered["allowed_paths"] = ["src/other.py"]
        with self.assertRaisesRegex(ProjectLaneError, "changed"):
            coordinator.verify_runner_writer_binding(
                tampered,
                Path(lane["worktree"]),
            )

    def test_existing_registry_allows_one_reservation_per_independent_worktree(self) -> None:
        one, two = self.lanes / "manual-one", self.lanes / "manual-two"
        self.git("worktree", "add", "-b", "manual-one", str(one)); self.git("worktree", "add", "-b", "manual-two", str(two))
        def reserve(path: Path, lease: str) -> str:
            return RecoveryRegistry(path, state_root=self.recovery).reserve_normal(lease, allowed_set_digest="b" * 64, recovery_capable=False)["lease"]["lease_id"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(set(pool.map(lambda args: reserve(*args), ((one, "one"), (two, "two")))), {"one", "two"})
        with self.assertRaises(RecoveryStateError):
            reserve(one, "second-one")

    def test_dirty_work_is_external_and_conflicting_lane_waits_without_mutation(self) -> None:
        dirty = self.checkout / "user.txt"; dirty.write_bytes(b"uncommitted\x00bytes")
        before = dirty.read_bytes(); index_before = self.git_output("ls-files", "--stage", "-z")
        independent = self.coordinator_for().create("independent", "M2", self.lanes / "independent", ["other.py"])
        blocked = self.coordinator_for().create("blocked", "M2", self.lanes / "blocked", ["user.txt"])
        self.assertEqual(independent["state"], "ready"); self.assertEqual(blocked["state"], "waiting-for-scope")
        self.assertEqual(dirty.read_bytes(), before); self.assertEqual(self.git_output("ls-files", "--stage", "-z"), index_before)
        scopes = self.store.read_scopes(self.anchor)["scopes"]
        self.assertTrue(any(item["kind"] == "protected-user-work" and item["path"] == "user.txt" and item["owner"] is None for item in scopes))

    def test_timeout_quarantines_until_explicit_terminal_close(self) -> None:
        lane = self.coordinator_for().create("timeout", "M2", self.lanes / "timeout", ["time.py"])
        allowed_set_digest = "a" * 64
        lease = {
            "lease_id": "timeout-contained",
            "run_id": "timeout-run",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "normal-contained",
            "recovery_capable": True,
            "state": "running",
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {"lease": lease, "outbox": None, "quarantine": None, "history": []}
        coordinator = self.coordinator_for()
        with mock.patch.object(coordinator, "_assert_legacy_vacancy"), \
             mock.patch("project_lanes.RecoveryRegistry", return_value=active_registry):
            lane = coordinator.attach_contained_writer(
                "timeout",
                lease_id="timeout-contained",
                run_id="timeout-run",
                allowed_set_digest=allowed_set_digest,
            )
        self.assertEqual(lane["state"], "running")
        quarantined = self.coordinator_for().cancel_or_crash("timeout", "timeout")
        self.assertEqual(quarantined["state"], "quarantined")
        with mock.patch("project_lanes.RecoveryRegistry", return_value=active_registry), \
             self.assertRaisesRegex(ProjectLaneError, "not vacant"):
            self.coordinator_for().close_terminal("timeout")
        archive = {
            "event": "contained-terminal-released",
            "lease_id": "timeout-contained",
            "lease_kind": "normal-contained",
            "allowed_set_digest": allowed_set_digest,
            "archive_digest": "b" * 64,
        }
        closed_registry = mock.Mock()
        closed_registry.state.return_value = {
            "lease": None,
            "outbox": None,
            "quarantine": None,
            "history": [archive],
        }
        with mock.patch("project_lanes.RecoveryRegistry", return_value=closed_registry):
            closed = self.coordinator_for().close_terminal("timeout")
        self.assertEqual((closed["state"], closed["terminal_evidence"]), ("closed", "b" * 64))

    def test_successful_writer_waits_for_integration_after_lane_local_release(self) -> None:
        self.coordinator_for().create(
            "successful",
            "M2",
            self.lanes / "successful",
            ["success.py"],
        )
        allowed_set_digest = "a" * 64
        writer = {
            "lease_id": "successful-contained",
            "run_id": "successful-run",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "normal-contained",
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": {
                **writer,
                "recovery_capable": True,
                "state": "running",
            },
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        coordinator = self.coordinator_for()
        with mock.patch.object(
            coordinator,
            "_assert_legacy_vacancy",
        ), mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=active_registry,
        ):
            running = coordinator.attach_contained_writer(
                "successful",
                lease_id=writer["lease_id"],
                run_id=writer["run_id"],
                allowed_set_digest=allowed_set_digest,
            )
        self.assertEqual(running["state"], "running")
        release = {
            "event": "contained-terminal-released",
            "lease_id": writer["lease_id"],
            "lease_kind": "normal-contained",
            "allowed_set_digest": allowed_set_digest,
            "terminal_success": True,
            "semantic_disposition": None,
            "final_state": "handoff-committed",
            "handoff_digest": "b" * 64,
            "archive_digest": "c" * 64,
        }
        closed_registry = mock.Mock()
        closed_registry.state.return_value = {
            "lease": None,
            "outbox": None,
            "quarantine": None,
            "history": [release],
        }
        with mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=closed_registry,
        ):
            waiting = coordinator.record_successful_terminal("successful")
            replay = coordinator.record_successful_terminal("successful")
        self.assertEqual(waiting["state"], "waiting-for-integration")
        self.assertEqual(waiting["terminal_evidence"], "c" * 64)
        self.assertEqual(replay, waiting)
        with self.assertRaisesRegex(ProjectLaneError, "not terminally closable"):
            coordinator.close_terminal("successful")

    def test_failed_writer_reopens_only_for_its_reserved_recovery_target(self) -> None:
        lane = self.coordinator_for().create(
            "recoverable",
            "M2",
            self.lanes / "recoverable",
            ["recover.py"],
        )
        allowed_set_digest = "d" * 64
        source_writer = {
            "lease_id": "recoverable-contained",
            "run_id": "recoverable-run",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "normal-contained",
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": {
                **source_writer,
                "recovery_capable": True,
                "state": "running",
            },
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        coordinator = self.coordinator_for()
        with mock.patch.object(
            coordinator,
            "_assert_legacy_vacancy",
        ), mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=active_registry,
        ):
            running = coordinator.attach_contained_writer(
                "recoverable",
                lease_id=source_writer["lease_id"],
                run_id=source_writer["run_id"],
                allowed_set_digest=allowed_set_digest,
            )
        self.assertEqual(running["state"], "running")
        self.assertEqual(
            coordinator.cancel_or_crash("recoverable", "crashed")["state"],
            "quarantined",
        )

        release = {
            "event": "contained-terminal-released",
            "lease_id": source_writer["lease_id"],
            "lease_kind": "normal-contained",
            "allowed_set_digest": allowed_set_digest,
            "terminal_success": False,
            "semantic_disposition": None,
            "handoff_digest": None,
            "outbox_digest": None,
            "archive_digest": "e" * 64,
        }
        vacant_registry = mock.Mock()
        vacant_registry.state.return_value = {
            "lease": None,
            "outbox": None,
            "quarantine": None,
            "history": [release],
        }
        checkpoint_digest = "f" * 64
        with mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=vacant_registry,
        ):
            recovery_ready = coordinator.record_recovery_ready(
                "recoverable",
                checkpoint_digest,
            )
            replay = coordinator.record_recovery_ready(
                "recoverable",
                checkpoint_digest,
            )
        self.assertEqual(recovery_ready["state"], "recovery-ready")
        self.assertIsNone(recovery_ready["writer"])
        self.assertEqual(
            recovery_ready["recovery_checkpoint_digest"],
            checkpoint_digest,
        )
        self.assertEqual(recovery_ready["terminal_evidence"], "e" * 64)
        self.assertEqual(replay, recovery_ready)

        recovery_writer = {
            "lease_id": "recoverable-target",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "recovery-target",
            "recovery_capable": True,
            "state": "running",
            "plan": {"run_id": "recoverable-target-run"},
        }
        recovery_registry = mock.Mock()
        recovery_registry.state.return_value = {
            "lease": recovery_writer,
            "outbox": None,
            "quarantine": None,
            "history": [release],
        }
        with mock.patch.object(
            coordinator,
            "_assert_legacy_vacancy",
        ), mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=recovery_registry,
        ):
            recovered_running = coordinator.attach_contained_writer(
                "recoverable",
                lease_id=recovery_writer["lease_id"],
                run_id=recovery_writer["plan"]["run_id"],
                allowed_set_digest=allowed_set_digest,
                lease_kind="recovery-target",
                recovery_checkpoint_digest=checkpoint_digest,
            )
        self.assertEqual(recovered_running["state"], "running")
        self.assertEqual(
            recovered_running["writer"]["lease_kind"],
            "recovery-target",
        )
        self.assertNotIn("recovery_checkpoint_digest", recovered_running)
        self.assertNotIn("terminal_evidence", recovered_running)

    def test_cancel_binds_an_already_active_writer_before_terminal_state(self) -> None:
        self.coordinator_for().create("cancel-race", "M2", self.lanes / "cancel-race", ["race.py"])
        allowed_set_digest = "c" * 64
        lease = {
            "lease_id": "cancel-race-contained",
            "run_id": "cancel-race-run",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "normal-contained",
            "recovery_capable": True,
            "state": "running",
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": lease,
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        coordinator = self.coordinator_for()
        with mock.patch.object(coordinator, "_assert_legacy_vacancy"), \
             mock.patch("project_lanes.RecoveryRegistry", return_value=active_registry):
            quarantined = coordinator.cancel_or_crash("cancel-race", "timeout")
            replayed = coordinator.attach_contained_writer(
                "cancel-race",
                lease_id="cancel-race-contained",
                run_id="cancel-race-run",
                allowed_set_digest=allowed_set_digest,
            )
        self.assertEqual(quarantined["state"], "quarantined")
        self.assertEqual(quarantined["writer"]["lease_id"], "cancel-race-contained")
        self.assertEqual(replayed, quarantined)

    def test_running_replay_revalidates_registry_and_allows_writer_dirties(self) -> None:
        lane = self.coordinator_for().create("running-replay", "M2", self.lanes / "running-replay", ["running.py"])
        writer = {
            "lease_id": "running-contained",
            "run_id": "running-run",
            "allowed_set_digest": "d" * 64,
            "lease_kind": "normal-contained",
        }
        state = self.store.read_state(self.anchor)["state"]
        lane["state"] = "running"
        lane["writer"] = writer
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=[lane],
            scopes=state["scopes"],
        )
        (Path(lane["worktree"]) / "running.py").write_text("writer change\n", encoding="utf-8")
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": {
                **writer,
                "recovery_capable": True,
                "state": "running",
            },
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        coordinator = self.coordinator_for()
        with mock.patch.object(coordinator, "_assert_legacy_vacancy"), \
             mock.patch("project_lanes.RecoveryRegistry", return_value=active_registry):
            replayed = coordinator.create(
                "running-replay",
                "M2",
                self.lanes / "running-replay",
                ["running.py"],
            )
        self.assertEqual(replayed["state"], "running")
        active_registry.state.return_value["lease"] = None
        with mock.patch.object(coordinator, "_assert_legacy_vacancy"), \
             mock.patch("project_lanes.RecoveryRegistry", return_value=active_registry), \
             self.assertRaisesRegex(ProjectLaneError, "not active"):
            coordinator.attach_contained_writer(
                "running-replay",
                lease_id="running-contained",
                run_id="running-run",
                allowed_set_digest="d" * 64,
            )

    def test_project_state_rejects_malformed_nested_lane_and_scope_on_replace_and_reload(self) -> None:
        lane = self.coordinator_for().create("schema", "M2", self.lanes / "schema", ["schema.py"])
        state = self.store.read_state(self.anchor)["state"]
        malformed = dict(lane)
        malformed["worktree"] = str(self.checkout)
        malformed["unknown"] = True
        with self.assertRaisesRegex(ProjectStateError, "lane"):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=state["generation"],
                lanes=[malformed],
                scopes=state["scopes"],
            )
        malformed_scope = {
            "kind": "protected-user-work",
            "path": "schema.py",
            "owner": None,
            "adoption": "protected",
            "evidence": {"content": {"kind": "file"}},
            "provenance": "e" * 64,
        }
        with self.assertRaisesRegex(ProjectStateError, "scope"):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=state["generation"],
                lanes=[lane],
                scopes=[malformed_scope],
            )

        state_path = self.coordinator / "states" / f"{self.anchor}.json"
        tampered = json.loads(state_path.read_text(encoding="utf-8"))
        tampered["lanes"][0]["branch"] = "refs/heads/arbitrary"
        tampered.pop("digest")
        tampered["digest"] = hashlib.sha256(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        state_path.write_text(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.store.read_state(self.anchor), {"status": "indeterminate"})

    def test_terminal_transition_is_idempotent_and_unmaterialized_lanes_close(self) -> None:
        running = self.coordinator_for().create("terminal-replay", "M2", self.lanes / "terminal-replay", ["terminal.py"])
        state = self.store.read_state(self.anchor)["state"]
        running["state"] = "running"
        running["writer"] = {
            "lease_id": "terminal-contained",
            "run_id": "terminal-run",
            "allowed_set_digest": "f" * 64,
            "lease_kind": "normal-contained",
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=[running],
            scopes=state["scopes"],
        )
        first = self.coordinator_for().cancel_or_crash("terminal-replay", "timeout")
        second = self.coordinator_for().cancel_or_crash("terminal-replay", "timeout")
        self.assertEqual((first["state"], second["state"]), ("quarantined", "quarantined"))
        self.assertEqual(second["writer"], running["writer"])

        dirty = self.checkout / "waiting.txt"
        dirty.write_text("protected\n", encoding="utf-8")
        waiting = self.coordinator_for().create(
            "waiting-close",
            "M2",
            self.lanes / "waiting-close",
            ["waiting.txt"],
        )
        self.assertEqual(waiting["state"], "waiting-for-scope")
        waiting = self.coordinator_for().cancel_or_crash("waiting-close", "cancelled")
        with mock.patch("project_lanes.RecoveryRegistry", side_effect=AssertionError("registry must remain absent")):
            closed = self.coordinator_for().close_terminal("waiting-close")
        self.assertEqual((waiting["terminal_from"], closed["state"]), ("waiting-for-scope", "closed"))

        with self.assertRaisesRegex(ProjectLaneError, "after-lane-state"):
            self.coordinator_for(fault="after-lane-state").create(
                "creating-close",
                "M2",
                self.lanes / "creating-close",
                ["creating.py"],
            )
        creating = self.coordinator_for().cancel_or_crash("creating-close", "cancelled")
        with mock.patch("project_lanes.RecoveryRegistry", side_effect=AssertionError("registry must remain absent")):
            closed = self.coordinator_for().close_terminal("creating-close")
        self.assertEqual((creating["terminal_from"], closed["state"]), ("creating", "closed"))

    def test_lane_create_replays_after_state_and_worktree_boundaries(self) -> None:
        target = self.lanes / "replay"
        with self.assertRaisesRegex(ProjectLaneError, "after-lane-state"):
            self.coordinator_for(fault="after-lane-state").create(
                "replay",
                "M2",
                target,
                ["replay.py"],
            )
        resumed = self.coordinator_for().create("replay", "M2", target, ["replay.py"])
        self.assertEqual(resumed["state"], "ready")
        self.assertEqual(
            self.coordinator_for().create("replay", "M2", target, ["replay.py"]),
            resumed,
        )
        self.assertEqual(
            len(
                [
                    lane
                    for lane in self.store.read_lanes(self.anchor)["lanes"]
                    if lane["lane_id"] == "replay"
                ]
            ),
            1,
        )

    def test_claimless_protected_waiter_replays_its_reservation(self) -> None:
        protected = self.checkout / "protected-replay.py"
        protected.write_text("user work\n", encoding="utf-8", newline="\n")
        target = self.lanes / "protected-replay"
        with self.assertRaisesRegex(ProjectLaneError, "after-lane-state"):
            self.coordinator_for(fault="after-lane-state").create(
                "protected-replay",
                "M2",
                target,
                ["protected-replay.py"],
            )
        interrupted = next(
            lane
            for lane in self.store.read_lanes(self.anchor)["lanes"]
            if lane["lane_id"] == "protected-replay"
        )
        self.assertEqual(interrupted["state"], "waiting-for-scope")
        self.assertEqual(
            [
                record
                for record in self.store.read_scopes(self.anchor)["scopes"]
                if record.get("owner") == "protected-replay"
            ],
            [],
        )
        newer = self.coordinator_for().create(
            "protected-newer",
            "M2",
            self.lanes / "protected-newer",
            ["protected-replay.py"],
        )
        self.assertEqual(newer["state"], "waiting-for-scope")

        resumed = self.coordinator_for().create(
            "protected-replay",
            "M2",
            target,
            ["protected-replay.py"],
        )
        self.assertEqual(resumed["state"], "waiting-for-scope")
        self.assertEqual(
            [
                (record["path"], record["status"])
                for record in self.store.read_scopes(self.anchor)["scopes"]
                if record.get("owner") == "protected-replay"
            ],
            [("protected-replay.py", "waiting")],
        )
        claims = self.store.read_scopes(self.anchor)["scopes"]
        older_claim = next(
            record
            for record in claims
            if record.get("owner") == "protected-replay"
        )
        newer_claim = next(
            record
            for record in claims
            if record.get("owner") == "protected-newer"
        )
        self.assertLess(older_claim["sequence"], newer_claim["sequence"])

    def test_generic_sink_rejects_forged_protected_adoption(self) -> None:
        protected = self.checkout / "sink-adoption.txt"
        protected.write_text("adopt me\n", encoding="utf-8", newline="\n")
        coordinator = self.coordinator_for()
        coordinator.create(
            "sink-adoption-waiter",
            "M2",
            self.lanes / "sink-adoption-waiter",
            ["sink-adoption.txt"],
        )
        action = "1" * 64
        plan = "2" * 64
        protected_state = self.store.read_state(self.anchor)["state"]
        forged_intent_scopes = [
            dict(scope) for scope in protected_state["scopes"]
        ]
        forged_intent = next(
            scope
            for scope in forged_intent_scopes
            if scope.get("path") == "sink-adoption.txt"
            and scope.get("kind") == "protected-user-work"
        )
        forged_intent["adoption"] = "adoption-intent"
        forged_intent["adoption_intent"] = {
            "user_action_digest": action,
            "plan_digest": plan,
            "provenance": forged_intent["provenance"],
            "intent_generation": protected_state["generation"],
        }
        with self.assertRaisesRegex(
            ProjectStateError,
            "purpose-specific protected adoption",
        ):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=protected_state["generation"],
                lanes=protected_state["lanes"],
                scopes=forged_intent_scopes,
            )
        coordinator.begin_protected_user_work_adoption(
            ["sink-adoption.txt"],
            user_action_digest=action,
            plan_digest=plan,
        )
        integration = self.lanes / "sink-adoption-integration"
        self.git(
            "worktree",
            "add",
            "-b",
            "sink-adoption-integration",
            str(integration),
        )
        (integration / "sink-adoption.txt").write_bytes(protected.read_bytes())
        self.git("add", "sink-adoption.txt", cwd=integration)
        self.git("commit", "-m", "accept protected sink fixture", cwd=integration)
        integrated_commit = self.git_output(
            "rev-parse",
            "HEAD",
            cwd=integration,
        ).decode().strip()
        self.git("update-ref", self.integration_ref, integrated_commit)
        receipt = coordinator.build_protected_user_work_acceptance_receipt(
            ["sink-adoption.txt"],
            user_action_digest=action,
            plan_digest=plan,
            integrated_commit=integrated_commit,
        )

        state = self.store.read_state(self.anchor)["state"]
        forged_scopes = [dict(scope) for scope in state["scopes"]]
        forged = next(
            scope
            for scope in forged_scopes
            if scope.get("path") == "sink-adoption.txt"
            and scope.get("kind") == "protected-user-work"
        )
        forged["adoption"] = "adopted"
        forged["owner"] = "integration"
        forged["adoption_acceptance"] = {
            "user_action_digest": action,
            "plan_digest": plan,
            "integrated_commit": integrated_commit,
            "integration_receipt_digest": receipt["digest"],
            "receipt": receipt,
        }
        forged.pop("adoption_intent")
        with self.assertRaisesRegex(
            ProjectStateError,
            "purpose-specific protected adoption",
        ):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=state["generation"],
                lanes=state["lanes"],
                scopes=forged_scopes,
            )
        unchanged = self.store.read_state(self.anchor)["state"]
        self.assertEqual(unchanged["generation"], state["generation"])
        self.assertEqual(
            next(
                scope["adoption"]
                for scope in unchanged["scopes"]
                if scope.get("path") == "sink-adoption.txt"
            ),
            "adoption-intent",
        )
        adopted = coordinator.finalize_protected_user_work_adoption(
            ["sink-adoption.txt"],
            user_action_digest=action,
            plan_digest=plan,
            integration_receipt=receipt,
        )
        self.assertEqual(adopted[0]["adoption"], "adopted")

    def test_simultaneous_lane_resume_and_writer_attach_converge(self) -> None:
        target = self.lanes / "concurrent"
        with self.assertRaisesRegex(ProjectLaneError, "after-lane-state"):
            self.coordinator_for(fault="after-lane-state").create(
                "concurrent",
                "M2",
                target,
                ["concurrent.py"],
            )
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            resumed = list(
                pool.map(
                    lambda _: self.coordinator_for().create(
                        "concurrent",
                        "M2",
                        target,
                        ["concurrent.py"],
                    ),
                    range(2),
                )
            )
        self.assertEqual([lane["state"] for lane in resumed], ["ready", "ready"])

        allowed_set_digest = "6" * 64
        lease = {
            "lease_id": "concurrent-contained",
            "run_id": "concurrent-run",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "normal-contained",
            "recovery_capable": True,
            "state": "running",
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": lease,
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        with mock.patch.object(ProjectLaneCoordinator, "_assert_legacy_vacancy"), \
             mock.patch("project_lanes.RecoveryRegistry", return_value=active_registry), \
             concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            attached = list(
                pool.map(
                    lambda _: self.coordinator_for().attach_contained_writer(
                        "concurrent",
                        lease_id="concurrent-contained",
                        run_id="concurrent-run",
                        allowed_set_digest=allowed_set_digest,
                    ),
                    range(2),
                )
            )
        self.assertEqual([lane["state"] for lane in attached], ["running", "running"])
        stored = next(
            lane
            for lane in self.store.read_lanes(self.anchor)["lanes"]
            if lane["lane_id"] == "concurrent"
        )
        self.assertEqual(stored["writer"]["lease_id"], "concurrent-contained")

    def test_path_escape_and_common_identity_drift_fail_before_git_mutation(self) -> None:
        outside = self.temp / "outside"
        outside.mkdir()
        before = self.git_output("for-each-ref", "--format=%(refname)", "refs/heads/")
        with self.assertRaisesRegex(ProjectLaneError, "escapes"):
            self.coordinator_for().create("escape", "M2", outside / "lane", ["a.py"])
        coordinator = self.coordinator_for()
        coordinator.common = {"path": "wrong", "identity": [0, 0]}
        with self.assertRaisesRegex(ProjectLaneError, "identity drifted"):
            coordinator.create("drift", "M2", self.lanes / "drift", ["b.py"])
        self.assertEqual(
            self.git_output("for-each-ref", "--format=%(refname)", "refs/heads/"),
            before,
        )

    def test_integration_ref_is_an_authoritative_session_binding(self) -> None:
        coordinator = self.coordinator_for()
        coordinator.create("session", "M2", self.lanes / "session", ["session.py"])
        before = self.store.read_state(self.anchor)["state"]
        with self.assertRaisesRegex(ProjectLaneError, "integration"):
            ProjectLaneCoordinator(
                self.checkout,
                self.store,
                self.anchor,
                recovery_root=self.recovery,
                lane_root=self.lanes,
                integration_ref="refs/openbuild/alternate",
            )
        self.assertEqual(self.store.read_state(self.anchor)["state"], before)

    def test_scope_aliases_and_reparse_ancestors_fail_closed(self) -> None:
        for index, scope in enumerate(("src//a.py", "src/./a.py", "src/a.py/", "C:/escape.py")):
            with self.subTest(scope=scope), self.assertRaisesRegex(ProjectLaneError, "scope"):
                self.coordinator_for().create(
                    f"alias-{index}",
                    "M2",
                    self.lanes / f"alias-{index}",
                    [scope],
                )
        (self.checkout / "Case.txt").write_text("dirty\n", encoding="utf-8")
        case_lane = self.coordinator_for().create(
            "case-alias",
            "M2",
            self.lanes / "case-alias",
            ["case.txt"],
        )
        self.assertEqual(case_lane["state"], "waiting-for-scope")

        real = self.checkout / "real"
        real.mkdir()
        link = self.checkout / "linked"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlink creation is not permitted")
        with self.assertRaisesRegex(ProjectLaneError, "link"):
            self.coordinator_for().create(
                "linked-scope",
                "M2",
                self.lanes / "linked-scope",
                ["linked/file.py"],
            )

    def test_anchor_lock_remains_readable_and_immutable_across_lane_updates(self) -> None:
        lock = self.store.anchor_path(self.anchor) / "anchor.lock"
        before = lock.read_bytes()
        self.coordinator_for().create("immutable", "M2", self.lanes / "immutable", ["immutable.py"])
        self.assertEqual(lock.read_bytes(), before)
        self.assertTrue((self.store.anchor_path(self.anchor) / "state.lock").is_file())

    def test_protected_adoption_is_explicit_replay_safe_and_integration_bound(self) -> None:
        dirty = self.checkout / "adopt.txt"
        dirty.write_bytes(b"adopt me\n")
        coordinator = self.coordinator_for()
        blocked = coordinator.create("adopt-waiter", "M2", self.lanes / "adopt-waiter", ["adopt.txt"])
        self.assertEqual(blocked["state"], "waiting-for-scope")
        action = "a" * 64
        plan = "b" * 64
        intent = coordinator.begin_protected_user_work_adoption(
            ["adopt.txt"],
            user_action_digest=action,
            plan_digest=plan,
        )
        self.assertEqual(intent[0]["adoption"], "adoption-intent")
        self.assertEqual(
            coordinator.begin_protected_user_work_adoption(
                ["adopt.txt"],
                user_action_digest=action,
                plan_digest=plan,
            ),
            intent,
        )
        with self.assertRaises(ProjectLaneError):
            coordinator.begin_protected_user_work_adoption(
                ["adopt.txt"],
                user_action_digest="d" * 64,
                plan_digest=plan,
            )

        integration = self.lanes / "adoption-integration"
        self.git("worktree", "add", "-b", "adoption-integration", str(integration))
        (integration / "adopt.txt").write_bytes(dirty.read_bytes())
        self.git("add", "adopt.txt", cwd=integration)
        self.git("commit", "-m", "adopt protected work", cwd=integration)
        integrated_commit = self.git_output("rev-parse", "HEAD", cwd=integration).decode().strip()
        self.git("update-ref", self.integration_ref, integrated_commit)

        with self.assertRaises(ProjectLaneError):
            coordinator.build_protected_user_work_acceptance_receipt(
                ["adopt.txt"],
                user_action_digest=action,
                plan_digest=plan,
                integrated_commit=self.git_output("rev-parse", "HEAD").decode().strip(),
            )
        integration_receipt = coordinator.build_protected_user_work_acceptance_receipt(
            ["adopt.txt"],
            user_action_digest=action,
            plan_digest=plan,
            integrated_commit=integrated_commit,
        )
        tampered_receipt = dict(integration_receipt)
        tampered_receipt["digest"] = "d" * 64
        with self.assertRaisesRegex(ProjectLaneError, "receipt binding"):
            coordinator.finalize_protected_user_work_adoption(
                ["adopt.txt"],
                user_action_digest=action,
                plan_digest=plan,
                integration_receipt=tampered_receipt,
            )
        adopted = coordinator.finalize_protected_user_work_adoption(
            ["adopt.txt"],
            user_action_digest=action,
            plan_digest=plan,
            integration_receipt=integration_receipt,
        )
        self.assertEqual((adopted[0]["adoption"], adopted[0]["owner"]), ("adopted", "integration"))
        self.assertEqual(
            coordinator.finalize_protected_user_work_adoption(
                ["adopt.txt"],
                user_action_digest=action,
                plan_digest=plan,
                integration_receipt=integration_receipt,
            ),
            adopted,
        )
        (integration / "follow-up.txt").write_text(
            "accepted follow-up\n",
            encoding="utf-8",
            newline="\n",
        )
        self.git("add", "follow-up.txt", cwd=integration)
        self.git("commit", "-m", "accepted integration follow-up", cwd=integration)
        accepted_tip = self.git_output(
            "rev-parse",
            "HEAD",
            cwd=integration,
        ).decode().strip()
        self.git("update-ref", self.integration_ref, accepted_tip)
        resumed = coordinator.create(
            "adopt-waiter",
            "M2",
            self.lanes / "adopt-waiter",
            ["adopt.txt"],
        )
        self.assertEqual(resumed["state"], "ready")
        self.assertEqual(
            self.git_output(
                "rev-parse",
                "HEAD",
                cwd=Path(resumed["worktree"]),
            ).decode().strip(),
            accepted_tip,
        )

        state_path = self.coordinator / "states" / f"{self.anchor}.json"
        tampered = json.loads(state_path.read_text(encoding="utf-8"))
        scope = next(
            value
            for value in tampered["scopes"]
            if value["path"] == "adopt.txt"
        )
        receipt = scope["adoption_acceptance"]["receipt"]
        receipt["paths"][0]["path"] = "unrelated.txt"
        receipt.pop("digest")
        receipt["digest"] = hashlib.sha256(
            json.dumps(
                receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        scope["adoption_acceptance"]["integration_receipt_digest"] = receipt["digest"]
        tampered.pop("digest")
        tampered["digest"] = hashlib.sha256(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        state_path.write_text(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.store.read_state(self.anchor), {"status": "indeterminate"})

    def test_protected_adoption_fault_and_rollback_never_free_scope(self) -> None:
        (self.checkout / "rollback.txt").write_text("protected\n", encoding="utf-8")
        self.coordinator_for().create(
            "rollback-waiter",
            "M2",
            self.lanes / "rollback-waiter",
            ["rollback.txt"],
        )
        action = "e" * 64
        plan = "f" * 64
        with self.assertRaisesRegex(ProjectLaneError, "after-adoption-intent"):
            self.coordinator_for(fault="after-adoption-intent").begin_protected_user_work_adoption(
                ["rollback.txt"],
                user_action_digest=action,
                plan_digest=plan,
            )
        recovered = self.coordinator_for().recover_protected_user_work_adoption(
            ["rollback.txt"],
            user_action_digest=action,
            plan_digest=plan,
        )
        self.assertEqual(recovered[0]["adoption"], "protected")
        replay = self.coordinator_for().begin_protected_user_work_adoption(
            ["rollback.txt"],
            user_action_digest=action,
            plan_digest=plan,
        )
        self.assertEqual(replay[0]["adoption"], "adoption-intent")
        rolled_back = self.coordinator_for().rollback_protected_user_work_adoption(
            ["rollback.txt"],
            user_action_digest=action,
            plan_digest=plan,
        )
        self.assertEqual(rolled_back[0]["adoption"], "protected")
        scope = next(
            item
            for item in self.store.read_scopes(self.anchor)["scopes"]
            if item["path"] == "rollback.txt"
        )
        self.assertEqual((scope["adoption"], scope["owner"]), ("protected", None))

    def test_adoption_verification_and_publish_faults_recover_exactly_once(self) -> None:
        action = "1" * 64
        plan = "2" * 64
        for name, fault in (("verify", "after-adoption-verify"), ("publish", "after-adoption-accept")):
            with self.subTest(fault=fault):
                path = f"{name}.txt"
                (self.checkout / path).write_text(f"{name}\n", encoding="utf-8")
                coordinator = self.coordinator_for()
                coordinator.create(
                    f"{name}-waiter",
                    "M2",
                    self.lanes / f"{name}-waiter",
                    [path],
                )
                coordinator.begin_protected_user_work_adoption(
                    [path],
                    user_action_digest=action,
                    plan_digest=plan,
                )
                integration = self.lanes / f"{name}-integration"
                self.git("worktree", "add", "-b", f"{name}-integration", str(integration))
                (integration / path).write_bytes((self.checkout / path).read_bytes())
                self.git("add", path, cwd=integration)
                self.git("commit", "-m", f"adopt {name}", cwd=integration)
                commit = self.git_output("rev-parse", "HEAD", cwd=integration).decode().strip()
                self.git("update-ref", self.integration_ref, commit)
                receipt = coordinator.build_protected_user_work_acceptance_receipt(
                    [path],
                    user_action_digest=action,
                    plan_digest=plan,
                    integrated_commit=commit,
                )
                with self.assertRaisesRegex(ProjectLaneError, fault):
                    self.coordinator_for(fault=fault).finalize_protected_user_work_adoption(
                        [path],
                        user_action_digest=action,
                        plan_digest=plan,
                        integration_receipt=receipt,
                    )
                adopted = self.coordinator_for().recover_protected_user_work_adoption(
                    [path],
                    user_action_digest=action,
                    plan_digest=plan,
                    integration_receipt=receipt,
                )
                self.assertEqual(adopted[0]["adoption"], "adopted")

    def test_protected_deletion_rejects_git_failure_and_accepts_exact_tree_absence(self) -> None:
        tracked = self.checkout / "delete.txt"
        tracked.write_text("delete me\n", encoding="utf-8")
        self.git("add", "delete.txt")
        self.git("commit", "-m", "add deletion target")
        self.git("update-ref", self.integration_ref, "HEAD")
        tracked.unlink()
        self.git("add", "delete.txt")
        coordinator = self.coordinator_for()
        coordinator.create(
            "delete-waiter",
            "M2",
            self.lanes / "delete-waiter",
            ["delete.txt"],
        )
        action = "3" * 64
        plan = "4" * 64
        coordinator.begin_protected_user_work_adoption(
            ["delete.txt"],
            user_action_digest=action,
            plan_digest=plan,
        )
        with self.assertRaises(ProjectLaneError):
            coordinator.build_protected_user_work_acceptance_receipt(
                ["delete.txt"],
                user_action_digest=action,
                plan_digest=plan,
                integrated_commit="0" * 40,
            )
        integration = self.lanes / "deletion-integration"
        self.git("worktree", "add", "-b", "deletion-integration", str(integration))
        (integration / "delete.txt").unlink()
        self.git("add", "delete.txt", cwd=integration)
        self.git("commit", "-m", "accept protected deletion", cwd=integration)
        commit = self.git_output("rev-parse", "HEAD", cwd=integration).decode().strip()
        self.git("update-ref", self.integration_ref, commit)
        receipt = coordinator.build_protected_user_work_acceptance_receipt(
            ["delete.txt"],
            user_action_digest=action,
            plan_digest=plan,
            integrated_commit=commit,
        )
        adopted = coordinator.finalize_protected_user_work_adoption(
            ["delete.txt"],
            user_action_digest=action,
            plan_digest=plan,
            integration_receipt=receipt,
        )
        self.assertEqual(adopted[0]["adoption"], "adopted")

    def test_retained_legacy_checkout_registry_blocks_lane_admission(self) -> None:
        registry = RecoveryRegistry(self.checkout, state_root=self.recovery)
        registry.reserve_normal(
            "legacy-retained",
            allowed_set_digest="5" * 64,
            recovery_capable=False,
        )
        before = self.git_output("for-each-ref", "--format=%(refname)", "refs/heads/")
        with self.assertRaisesRegex(ProjectLaneError, "not vacant"):
            self.coordinator_for().create(
                "blocked-by-legacy",
                "M2",
                self.lanes / "blocked-by-legacy",
                ["legacy.py"],
            )
        self.assertEqual(self.store.read_lanes(self.anchor)["lanes"], [])
        self.assertEqual(
            self.git_output("for-each-ref", "--format=%(refname)", "refs/heads/"),
            before,
        )

    def test_retained_legacy_registry_blocks_replay_after_durable_lane_intent(self) -> None:
        target = self.lanes / "legacy-replay"
        with self.assertRaisesRegex(ProjectLaneError, "after-lane-state"):
            self.coordinator_for(fault="after-lane-state").create(
                "legacy-replay",
                "M2",
                target,
                ["legacy-replay.py"],
            )
        RecoveryRegistry(self.checkout, state_root=self.recovery).reserve_normal(
            "legacy-after-intent",
            allowed_set_digest="7" * 64,
            recovery_capable=False,
        )
        with self.assertRaisesRegex(ProjectLaneError, "not vacant"):
            self.coordinator_for().create(
                "legacy-replay",
                "M2",
                target,
                ["legacy-replay.py"],
            )
        lane = next(
            item
            for item in self.store.read_lanes(self.anchor)["lanes"]
            if item["lane_id"] == "legacy-replay"
        )
        self.assertEqual(lane["state"], "creating")
        self.assertFalse(target.exists())

    def test_staged_and_unstaged_renames_protect_both_paths(self) -> None:
        for name in ("staged-old.txt", "unstaged-old.txt"):
            (self.checkout / name).write_text(name, encoding="utf-8")
        self.git("add", "staged-old.txt", "unstaged-old.txt")
        self.git("commit", "-m", "add rename targets")
        self.git("update-ref", self.integration_ref, "HEAD")
        self.git("mv", "staged-old.txt", "staged-new.txt")
        os.replace(
            self.checkout / "unstaged-old.txt",
            self.checkout / "unstaged-new.txt",
        )
        for index, path in enumerate(
            (
                "staged-old.txt",
                "staged-new.txt",
                "unstaged-old.txt",
                "unstaged-new.txt",
            )
        ):
            with self.subTest(path=path):
                lane = self.coordinator_for().create(
                    f"rename-{index}",
                    "M2",
                    self.lanes / f"rename-{index}",
                    [path],
                )
                self.assertEqual(lane["state"], "waiting-for-scope")

    def test_adoption_rejects_symlink_or_executable_mode_substitution(self) -> None:
        target = "same-blob"
        link = self.checkout / "protected-link"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("file symlink creation is not permitted")
        coordinator = self.coordinator_for()
        coordinator.create(
            "link-waiter",
            "M2",
            self.lanes / "link-waiter",
            ["protected-link"],
        )
        action = "8" * 64
        plan = "9" * 64
        coordinator.begin_protected_user_work_adoption(
            ["protected-link"],
            user_action_digest=action,
            plan_digest=plan,
        )
        integration = self.lanes / "link-integration"
        self.git("worktree", "add", "-b", "link-integration", str(integration))
        (integration / "protected-link").write_bytes(os.fsencode(target))
        self.git("add", "protected-link", cwd=integration)
        self.git("commit", "-m", "substitute regular file", cwd=integration)
        commit = self.git_output("rev-parse", "HEAD", cwd=integration).decode().strip()
        self.git("update-ref", self.integration_ref, commit)
        receipt = coordinator.build_protected_user_work_acceptance_receipt(
            ["protected-link"],
            user_action_digest=action,
            plan_digest=plan,
            integrated_commit=commit,
        )
        with self.assertRaisesRegex(ProjectLaneError, "does not match"):
            coordinator.finalize_protected_user_work_adoption(
                ["protected-link"],
                user_action_digest=action,
                plan_digest=plan,
                integration_receipt=receipt,
            )

        executable = self.checkout / "protected-executable"
        executable.write_bytes(b"same executable blob\n")
        executable.chmod(0o755)
        coordinator.create(
            "executable-waiter",
            "M2",
            self.lanes / "executable-waiter",
            ["protected-executable"],
        )
        coordinator.begin_protected_user_work_adoption(
            ["protected-executable"],
            user_action_digest=action,
            plan_digest=plan,
        )
        executable_integration = self.lanes / "executable-integration"
        self.git(
            "worktree",
            "add",
            "-b",
            "executable-integration",
            str(executable_integration),
            self.integration_ref,
        )
        (executable_integration / "protected-executable").write_bytes(executable.read_bytes())
        (executable_integration / "protected-executable").chmod(0o644)
        self.git("add", "protected-executable", cwd=executable_integration)
        self.git("commit", "-m", "substitute executable mode", cwd=executable_integration)
        executable_commit = self.git_output("rev-parse", "HEAD", cwd=executable_integration).decode().strip()
        self.git("update-ref", self.integration_ref, executable_commit)
        executable_receipt = coordinator.build_protected_user_work_acceptance_receipt(
            ["protected-executable"],
            user_action_digest=action,
            plan_digest=plan,
            integrated_commit=executable_commit,
        )
        with self.assertRaisesRegex(ProjectLaneError, "does not match"):
            coordinator.finalize_protected_user_work_adoption(
                ["protected-executable"],
                user_action_digest=action,
                plan_digest=plan,
                integration_receipt=executable_receipt,
            )

    def git_output(self, *args: str, cwd: Path | None = None) -> bytes:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.checkout,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout


class ProjectScopeM3Tests(unittest.TestCase):
    """R-031 M3 scope-resource lease policy at the project owner layer."""

    def setUp(self) -> None:
        self.temp_root = Path(__file__).resolve().parents[1] / ".tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp = self.temp_root / f"openbuild-project-scopes-{next(tempfile._get_candidate_names())}"
        self.temp.mkdir()
        self.checkout = self.temp / "checkout"
        self.checkout.mkdir(parents=True)
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.checkout / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "-m", "base")
        self.integration_ref = "refs/openbuild/integration"
        self.git("update-ref", self.integration_ref, "HEAD")
        self.coordinator_root = self.temp / "coordinator"
        self.recovery = self.temp / "recovery"
        self.lanes = self.temp / "lanes"
        self.lanes.mkdir()
        self.store = ProjectStateStore(self.checkout, coordinator_root=self.coordinator_root)
        capability = self.store.issue_bootstrap_capability("plan", "attempt")["bootstrap_capability"]
        self.anchor = self.store.create_anchor(capability, "plan", "attempt")["anchor_id"]
        self.store.bootstrap(self.anchor, "clean")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def git(self, *args: str, cwd: Path | None = None) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd or self.checkout,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def lanes_coordinator(self) -> ProjectLaneCoordinator:
        return ProjectLaneCoordinator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery,
            lane_root=self.lanes,
            integration_ref=self.integration_ref,
        )

    def scopes(self) -> ProjectScopeManager:
        return ProjectScopeManager(self.store, self.anchor, checkout=self.checkout)

    def create(self, lane_id: str, scopes: list[object]) -> dict[str, object]:
        return self.lanes_coordinator().create(
            lane_id,
            "M3",
            self.lanes / lane_id,
            scopes,  # type: ignore[arg-type]
        )

    def scope_records(self, owner: str) -> list[dict[str, object]]:
        return [
            item
            for item in self.store.read_scopes(self.anchor)["scopes"]
            if item.get("owner") == owner
        ]

    def mark_waiting_for_integration(self, lane_id: str) -> dict[str, object]:
        state = self.store.read_state(self.anchor)["state"]
        lanes = list(state["lanes"])
        lane = next(item for item in lanes if item["lane_id"] == lane_id)
        lane["state"] = "waiting-for-integration"
        lane["writer"] = {
            "lease_id": f"{lane_id}-writer",
            "run_id": f"{lane_id}-run",
            "allowed_set_digest": "c" * 64,
            "lease_kind": "normal-contained",
        }
        lane["terminal_evidence"] = "d" * 64
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=state["scopes"],
        )
        return lane

    def integration_release_receipt(
        self,
        lane: dict[str, object],
    ) -> dict[str, object]:
        receipt: dict[str, object] = {
            "schema": "project-scope-release-v1",
            "kind": "coherent-integration",
            "lane_id": lane["lane_id"],
            "admitted_base": lane["base"],
            "accepted_commit": lane["base"],
            "terminal_evidence": lane["terminal_evidence"],
            "writer_binding_digest": _digest(lane["writer"]),
            "validation_evidence": "e" * 64,
        }
        receipt["digest"] = _digest(receipt)
        return receipt

    def test_double_claim_and_case_ancestor_aliases_wait_without_worktree_activation(self) -> None:
        first = self.create("first", ["Src"])
        alias = self.create("alias", ["src/File.py"])
        duplicate = self.create("duplicate", ["SRC"])
        self.assertEqual(first["state"], "ready")
        self.assertEqual((alias["state"], duplicate["state"]), ("waiting-for-scope", "waiting-for-scope"))
        self.assertFalse((self.lanes / "alias").exists())
        self.assertEqual(
            [record["status"] for record in self.scope_records("first")],
            ["active"],
        )
        self.assertEqual(
            [record["status"] for record in self.scope_records("alias")],
            ["waiting"],
        )

    def test_concurrent_double_claim_retries_generation_cas_to_owner_and_waiter(self) -> None:
        first = self.lanes_coordinator()
        second = self.lanes_coordinator()
        original = self.store.replace_lane_state
        barrier = threading.Barrier(2)
        counter_lock = threading.Lock()
        publish_count = 0

        def synchronized_publish(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal publish_count
            with counter_lock:
                publish_count += 1
                ordinal = publish_count
            if ordinal <= 2:
                barrier.wait(timeout=10)
            return original(*args, **kwargs)

        def create_lane(
            coordinator: ProjectLaneCoordinator,
            lane_id: str,
        ) -> dict[str, object]:
            return coordinator.create(
                lane_id,
                "M3",
                self.lanes / lane_id,
                ["shared.py"],
            )

        with mock.patch.object(
            self.store,
            "replace_lane_state",
            side_effect=synchronized_publish,
        ):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(create_lane, first, "concurrent-first"),
                    pool.submit(create_lane, second, "concurrent-second"),
                ]
                lanes = [future.result(timeout=30) for future in futures]

        self.assertEqual(
            sorted(lane["state"] for lane in lanes),
            ["ready", "waiting-for-scope"],
        )
        claims = [
            item
            for item in self.store.read_scopes(self.anchor)["scopes"]
            if item.get("path") == "shared.py"
        ]
        self.assertEqual(
            sorted(item["status"] for item in claims),
            ["active", "waiting"],
        )

    def test_claimless_alpha2_running_lane_migrates_before_new_overlap(self) -> None:
        coordinator = self.lanes_coordinator()
        legacy_worktree = self.lanes / "legacy-running"
        self.git(
            "worktree",
            "add",
            "-b",
            "openbuild/lanes/legacy-running",
            str(legacy_worktree),
        )
        state = self.store.read_state(self.anchor)["state"]
        writer = {
            "lease_id": "legacy-lease",
            "run_id": "legacy-run",
            "allowed_set_digest": "9" * 64,
            "lease_kind": "normal-contained",
        }
        legacy_lane = {
            "lane_id": "legacy-running",
            "milestone": "M2",
            "reader_floor": "2.3.6",
            "common": coordinator.common,
            "base": coordinator.base,
            "branch": "refs/heads/openbuild/lanes/legacy-running",
            "worktree": str(legacy_worktree),
            "scopes": ["shared.py"],
            "state": "running",
            "writer": writer,
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=[legacy_lane],
            scopes=state["scopes"],
        )
        admitted = self.store.read_state(self.anchor)["state"]
        forged = dict(legacy_lane)
        forged["scope_schema"] = "project-scopes-v1"
        forged["scope_requests"] = [
            {"kind": "directory", "path": "shared.py", "mode": "hard"}
        ]
        forged["scope_enqueue_sequence"] = admitted["generation"] + 1
        with self.assertRaisesRegex(
            ProjectStateError,
            "migration requires explicit project claims",
        ):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=admitted["generation"],
                lanes=[forged],
                scopes=admitted["scopes"],
            )
        waiting = self.create("new-overlap", ["shared.py"])
        self.assertEqual(waiting["state"], "waiting-for-scope")
        claims = self.store.read_scopes(self.anchor)["scopes"]
        self.assertEqual(
            [
                (item["owner"], item["status"])
                for item in claims
                if item.get("path") == "shared.py"
            ],
            [
                ("legacy-running", "active"),
                ("new-overlap", "waiting"),
            ],
        )
        binding = self.lanes_coordinator().runner_writer_binding(
            "legacy-running",
            legacy_worktree,
            ["shared.py"],
            require_ready=False,
        )
        self.assertEqual(binding["allowed_paths"], ["shared.py"])

    def test_overlapping_live_alpha2_lanes_fail_closed_before_migration(self) -> None:
        coordinator = self.lanes_coordinator()
        state = self.store.read_state(self.anchor)["state"]
        lanes = []
        for lane_id in ("legacy-live-a", "legacy-live-b"):
            lanes.append(
                {
                    "lane_id": lane_id,
                    "milestone": "M2",
                    "reader_floor": "2.3.6",
                    "common": coordinator.common,
                    "base": coordinator.base,
                    "branch": f"refs/heads/openbuild/lanes/{lane_id}",
                    "worktree": str(self.lanes / lane_id),
                    "scopes": ["shared.py"],
                    "state": "running",
                    "writer": {
                        "lease_id": f"{lane_id}-lease",
                        "run_id": f"{lane_id}-run",
                        "allowed_set_digest": "8" * 64,
                        "lease_kind": "normal-contained",
                    },
                }
            )
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=state["scopes"],
        )
        before = self.store.read_state(self.anchor)["state"]
        with self.assertRaisesRegex(
            ProjectScopeError,
            "overlapping live legacy lanes",
        ):
            self.scopes().migrate_legacy_claims()
        after = self.store.read_state(self.anchor)["state"]
        self.assertEqual(after["generation"], before["generation"])
        self.assertEqual(after["scopes"], before["scopes"])

    def test_real_admission_rejects_overlapping_live_alpha2_before_mutation(self) -> None:
        coordinator = self.lanes_coordinator()
        lanes = []
        for lane_id in ("legacy-admission-a", "legacy-admission-b"):
            worktree = self.lanes / lane_id
            self.git(
                "worktree",
                "add",
                "-b",
                f"openbuild/lanes/{lane_id}",
                str(worktree),
            )
            lanes.append(
                {
                    "lane_id": lane_id,
                    "milestone": "M2",
                    "reader_floor": "2.3.6",
                    "common": coordinator.common,
                    "base": coordinator.base,
                    "branch": f"refs/heads/openbuild/lanes/{lane_id}",
                    "worktree": str(worktree),
                    "scopes": ["shared.py"],
                    "state": "running",
                    "writer": {
                        "lease_id": f"{lane_id}-lease",
                        "run_id": f"{lane_id}-run",
                        "allowed_set_digest": "6" * 64,
                        "lease_kind": "normal-contained",
                    },
                }
            )
        state = self.store.read_state(self.anchor)["state"]
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=state["scopes"],
        )
        before = self.store.read_state(self.anchor)["state"]
        with self.assertRaisesRegex(
            ProjectLaneError,
            "overlapping live legacy lanes",
        ):
            coordinator.create(
                "fresh-after-legacy",
                "M3",
                self.lanes / "fresh-after-legacy",
                ["fresh.py"],
            )
        after = self.store.read_state(self.anchor)["state"]
        self.assertEqual(after["generation"], before["generation"])
        self.assertEqual(after["lanes"], before["lanes"])

    def test_existing_waiter_preflights_live_alpha2_before_base_refresh(self) -> None:
        protected = self.checkout / "waiter.py"
        protected.write_text("protected\n", encoding="utf-8", newline="\n")
        coordinator = self.lanes_coordinator()
        waiter = coordinator.create(
            "legacy-refresh-waiter",
            "M3",
            self.lanes / "legacy-refresh-waiter",
            ["waiter.py"],
        )
        self.assertEqual(waiter["state"], "waiting-for-scope")

        action = "4" * 64
        plan = "5" * 64
        coordinator.begin_protected_user_work_adoption(
            ["waiter.py"],
            user_action_digest=action,
            plan_digest=plan,
        )
        integration = self.lanes / "legacy-refresh-integration"
        self.git(
            "worktree",
            "add",
            "-b",
            "legacy-refresh-integration",
            str(integration),
        )
        (integration / "waiter.py").write_bytes(protected.read_bytes())
        self.git("add", "waiter.py", cwd=integration)
        self.git("commit", "-m", "accept waiter", cwd=integration)
        accepted = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=integration,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode().strip()
        self.git("update-ref", self.integration_ref, accepted)
        receipt = coordinator.build_protected_user_work_acceptance_receipt(
            ["waiter.py"],
            user_action_digest=action,
            plan_digest=plan,
            integrated_commit=accepted,
        )
        coordinator.finalize_protected_user_work_adoption(
            ["waiter.py"],
            user_action_digest=action,
            plan_digest=plan,
            integration_receipt=receipt,
        )

        state = self.store.read_state(self.anchor)["state"]
        legacy_lanes = []
        for lane_id in ("legacy-refresh-a", "legacy-refresh-b"):
            worktree = self.lanes / lane_id
            self.git(
                "worktree",
                "add",
                "-b",
                f"openbuild/lanes/{lane_id}",
                str(worktree),
            )
            legacy_lanes.append(
                {
                    "lane_id": lane_id,
                    "milestone": "M2",
                    "reader_floor": "2.3.6",
                    "common": coordinator.common,
                    "base": waiter["base"],
                    "branch": f"refs/heads/openbuild/lanes/{lane_id}",
                    "worktree": str(worktree),
                    "scopes": ["shared-legacy.py"],
                    "state": "running",
                    "writer": {
                        "lease_id": f"{lane_id}-lease",
                        "run_id": f"{lane_id}-run",
                        "allowed_set_digest": "7" * 64,
                        "lease_kind": "normal-contained",
                    },
                }
            )
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=[*state["lanes"], *legacy_lanes],
            scopes=state["scopes"],
        )
        before = self.store.read_state(self.anchor)["state"]
        with self.assertRaisesRegex(
            ProjectLaneError,
            "overlapping live legacy lanes",
        ):
            coordinator.create(
                "legacy-refresh-waiter",
                "M3",
                self.lanes / "legacy-refresh-waiter",
                ["waiter.py"],
            )
        after = self.store.read_state(self.anchor)["state"]
        self.assertEqual(after["generation"], before["generation"])
        current_waiter = next(
            lane
            for lane in after["lanes"]
            if lane["lane_id"] == "legacy-refresh-waiter"
        )
        self.assertEqual(current_waiter["base"], waiter["base"])
        self.assertFalse((self.lanes / "fresh-after-legacy").exists())

    def test_legacy_migration_revalidates_paths_before_active_claims(self) -> None:
        coordinator = self.lanes_coordinator()
        state = self.store.read_state(self.anchor)["state"]
        legacy = {
            "lane_id": "legacy-alias",
            "milestone": "M2",
            "reader_floor": "2.3.6",
            "common": coordinator.common,
            "base": coordinator.base,
            "branch": "refs/heads/openbuild/lanes/legacy-alias",
            "worktree": str(self.lanes / "legacy-alias"),
            "scopes": ["alias.py"],
            "state": "ready",
            "writer": None,
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=[legacy],
            scopes=state["scopes"],
        )
        manager = self.scopes()
        before = self.store.read_state(self.anchor)["state"]
        with mock.patch.object(
            manager,
            "_assert_real_path",
            side_effect=ProjectScopeError(
                "scope target is a link or reparse point"
            ),
        ), self.assertRaisesRegex(ProjectScopeError, "link or reparse"):
            manager.migrate_legacy_claims()
        after = self.store.read_state(self.anchor)["state"]
        self.assertEqual(after["generation"], before["generation"])
        self.assertEqual(after["scopes"], before["scopes"])

    def test_migrated_waiter_ticket_precedes_lexically_earlier_new_lane(self) -> None:
        coordinator = self.lanes_coordinator()
        state = self.store.read_state(self.anchor)["state"]
        legacy_lanes = [
            {
                "lane_id": lane_id,
                "milestone": "M2",
                "reader_floor": "2.3.6",
                "common": coordinator.common,
                "base": coordinator.base,
                "branch": f"refs/heads/openbuild/lanes/{lane_id}",
                "worktree": str(self.lanes / lane_id),
                "scopes": ["shared.py"],
                "state": "ready",
                "writer": None,
            }
            for lane_id in ("legacy-ticket-a", "legacy-ticket-b")
        ]
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=legacy_lanes,
            scopes=state["scopes"],
        )
        manager = self.scopes()
        manager.migrate_legacy_claims()
        migrated = self.store.read_state(self.anchor)["state"]
        new_lane = {
            "lane_id": "aaa-new",
            "milestone": "M3",
            "reader_floor": "2.3.6",
            "common": coordinator.common,
            "base": coordinator.base,
            "branch": "refs/heads/openbuild/lanes/aaa-new",
            "worktree": str(self.lanes / "aaa-new"),
            "scopes": ["shared.py"],
            "scope_schema": "project-scopes-v1",
            "scope_requests": [
                {"kind": "directory", "path": "shared.py", "mode": "hard"}
            ],
            "scope_enqueue_sequence": migrated["generation"] + 1,
            "state": "creating",
            "writer": None,
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=migrated["generation"],
            lanes=[*migrated["lanes"], new_lane],
            scopes=migrated["scopes"],
        )
        manager.reserve_planned("aaa-new", ["shared.py"])
        claims = self.store.read_scopes(self.anchor)["scopes"]
        migrated_waiter = next(
            item for item in claims if item.get("owner") == "legacy-ticket-b"
        )
        new_waiter = next(
            item for item in claims if item.get("owner") == "aaa-new"
        )
        self.assertLess(migrated_waiter["sequence"], new_waiter["sequence"])
        waiters = [migrated_waiter, new_waiter]
        self.assertTrue(
            manager._group_is_eligible([migrated_waiter], waiters)
        )
        self.assertFalse(manager._group_is_eligible([new_waiter], waiters))

    def test_contract_resource_collisions_and_soft_intents(self) -> None:
        contract = {"kind": "contract", "path": "api/v1", "mode": "hard"}
        resource = {"kind": "resource", "path": "postgres/main", "mode": "hard"}
        self.assertEqual(self.create("contract-one", [contract])["state"], "ready")
        self.assertEqual(self.create("contract-two", [contract])["state"], "waiting-for-scope")
        self.assertEqual(self.create("resource-one", [resource])["state"], "ready")
        self.assertEqual(self.create("resource-two", [resource])["state"], "waiting-for-scope")
        self.assertEqual(
            self.create(
                "soft-intent",
                [{"kind": "resource", "path": "redis/cache", "mode": "soft"}],
            )["state"],
            "ready",
        )
        self.assertEqual(
            self.create(
                "hard-after-soft",
                [{"kind": "resource", "path": "redis/cache", "mode": "hard"}],
            )["state"],
            "ready",
        )

    def test_logical_scope_keys_ignore_filesystem_ancestors_and_dirty_paths(self) -> None:
        (self.checkout / "api").write_text("not a directory\n", encoding="utf-8")
        lane = self.create(
            "logical-only",
            [
                {"kind": "contract", "path": "api/users", "mode": "hard"},
                {"kind": "resource", "path": "api/users", "mode": "hard"},
            ],
        )
        self.assertEqual(lane["state"], "ready")
        self.assertEqual(
            [
                (item["kind"], item["status"])
                for item in self.scope_records("logical-only")
            ],
            [("contract", "active"), ("resource", "active")],
        )
        protected = [
            item
            for item in self.store.read_scopes(self.anchor)["scopes"]
            if item.get("kind") == "protected-user-work"
        ]
        self.assertEqual([item["path"] for item in protected], ["api"])

    def test_protected_work_blocks_expansion_and_ready_legacy_migration(self) -> None:
        (self.checkout / "protected.py").write_text(
            "user work\n",
            encoding="utf-8",
        )
        holder = self.create("protected-expander", ["owned.py"])
        expansion = self.scopes().expand(
            "protected-expander",
            ["protected.py"],
            pre_write=True,
        )
        self.assertEqual(expansion["status"], "waiting-for-scope")
        self.assertEqual(
            [
                item["status"]
                for item in self.scope_records("protected-expander")
                if item["phase"] == "expansion"
            ],
            ["waiting"],
        )
        state = self.store.read_state(self.anchor)["state"]
        coordinator = self.lanes_coordinator()
        legacy = {
            "lane_id": "legacy-protected",
            "milestone": "M2",
            "reader_floor": "2.3.6",
            "common": coordinator.common,
            "base": coordinator.base,
            "branch": "refs/heads/openbuild/lanes/legacy-protected",
            "worktree": str(self.lanes / "legacy-protected"),
            "scopes": ["protected.py"],
            "state": "ready",
            "writer": None,
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=[*state["lanes"], legacy],
            scopes=state["scopes"],
        )
        self.scopes().migrate_legacy_claims()
        migrated = self.store.read_state(self.anchor)["state"]
        legacy_lane = next(
            lane
            for lane in migrated["lanes"]
            if lane["lane_id"] == "legacy-protected"
        )
        self.assertEqual(legacy_lane["state"], "waiting-for-scope")
        self.assertEqual(
            [
                item["status"]
                for item in migrated["scopes"]
                if item.get("owner") == "legacy-protected"
            ],
            ["waiting"],
        )
        self.assertTrue(Path(str(holder["worktree"])).is_dir())

    def test_same_text_file_and_contract_keep_typed_replay_binding(self) -> None:
        requests = [
            {"kind": "file", "path": "shared-key", "mode": "hard"},
            {"kind": "contract", "path": "shared-key", "mode": "hard"},
        ]
        lane = self.create("typed-same-text", requests)
        self.assertEqual(lane["scopes"], ["shared-key"])
        self.assertEqual(lane["scope_requests"], requests)
        self.assertEqual(
            [item["kind"] for item in self.scope_records("typed-same-text")],
            ["file", "contract"],
        )
        with self.assertRaisesRegex(ProjectLaneError, "replay binding changed"):
            self.create(
                "typed-same-text",
                [{"kind": "contract", "path": "shared-key", "mode": "hard"}],
            )

    def test_mixed_file_and_logical_scopes_attach_one_contained_writer(self) -> None:
        lane = self.create(
            "mixed-authority",
            [
                {"kind": "file", "path": "owned.py", "mode": "hard"},
                {"kind": "contract", "path": "api/users", "mode": "hard"},
                {"kind": "resource", "path": "postgres/main", "mode": "hard"},
            ],
        )
        coordinator = self.lanes_coordinator()
        binding = coordinator.runner_writer_binding(
            "mixed-authority",
            Path(str(lane["worktree"])),
            ["owned.py"],
            require_ready=True,
        )
        writer = {
            "lease_id": "mixed-authority-lease",
            "run_id": "mixed-authority-run",
            "allowed_set_digest": "7" * 64,
            "lease_kind": "normal-contained",
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": {
                **writer,
                "recovery_capable": True,
                "state": "running",
            },
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        with mock.patch.object(
            coordinator,
            "_assert_legacy_vacancy",
        ), mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=active_registry,
        ):
            attached = coordinator.attach_contained_writer(
                "mixed-authority",
                lease_id=writer["lease_id"],
                run_id=writer["run_id"],
                allowed_set_digest=writer["allowed_set_digest"],
            )
        self.assertEqual(binding["allowed_paths"], ["owned.py"])
        self.assertEqual(attached["state"], "running")

    def test_final_file_and_directory_links_are_rejected(self) -> None:
        target_file = self.checkout / "target.txt"
        target_file.write_text("target\n", encoding="utf-8")
        target_directory = self.checkout / "target-directory"
        target_directory.mkdir()
        file_link = self.checkout / "file-link"
        directory_link = self.checkout / "directory-link"
        try:
            os.symlink(target_file, file_link)
            os.symlink(
                target_directory,
                directory_link,
                target_is_directory=True,
            )
        except (NotImplementedError, OSError):
            self.skipTest("final-component symlink creation is not permitted")
        with self.assertRaisesRegex(ProjectScopeError, "link or reparse"):
            self.scopes().normalize(
                [{"kind": "file", "path": "file-link", "mode": "hard"}]
            )
        with self.assertRaisesRegex(ProjectScopeError, "link or reparse"):
            self.scopes().normalize(
                [
                    {
                        "kind": "directory",
                        "path": "directory-link",
                        "mode": "hard",
                    }
                ]
            )

    def test_oldest_eligible_waiter_policy_precedes_newer_waiter(self) -> None:
        manager = self.scopes()
        oldest = {
            "kind": "file",
            "path": "shared.py",
            "mode": "hard",
            "owner": "oldest",
            "status": "waiting",
            "sequence": 10,
            "reservation": "oldest:planned:10",
            "phase": "planned",
        }
        newest = {
            **oldest,
            "owner": "newest",
            "sequence": 11,
            "reservation": "newest:planned:11",
        }
        self.assertTrue(manager._group_is_eligible([oldest], [oldest, newest]))
        self.assertFalse(manager._group_is_eligible([newest], [oldest, newest]))

    def test_release_remains_fail_closed_without_integration_owner(self) -> None:
        self.create("holder", ["shared.py"])
        self.create("oldest", ["shared.py"])
        self.create("newest", ["shared.py"])
        holder = self.mark_waiting_for_integration("holder")
        receipt = self.integration_release_receipt(holder)
        with self.assertRaisesRegex(
            ProjectScopeError,
            "registry-resident integration-owner acceptance",
        ):
            self.scopes().release(
                "holder",
                acceptance=receipt,
            )
        self.assertEqual(
            [record["status"] for record in self.scope_records("holder")],
            ["active"],
        )
        self.assertEqual(
            [record["status"] for record in self.scope_records("oldest")],
            ["waiting"],
        )

    def test_durable_sink_rejects_caller_generated_release_without_mutation(self) -> None:
        self.create("release-bypass", ["shared.py"])
        self.mark_waiting_for_integration("release-bypass")
        state = self.store.read_state(self.anchor)["state"]
        for mutation in ("delete", "cancel", "reticket"):
            with self.subTest(mutation=mutation):
                scopes = [dict(item) for item in state["scopes"]]
                if mutation == "delete":
                    scopes = [
                        item
                        for item in scopes
                        if item.get("owner") != "release-bypass"
                    ]
                elif mutation == "cancel":
                    scope = next(
                        item
                        for item in scopes
                        if item.get("owner") == "release-bypass"
                    )
                    scope["status"] = "cancelled"
                else:
                    scope = next(
                        item
                        for item in scopes
                        if item.get("owner") == "release-bypass"
                    )
                    scope["reservation"] = "release-bypass:planned:forged"
                with self.assertRaisesRegex(
                    ProjectStateError,
                    "release requires its owning lifecycle",
                ):
                    self.store.replace_lane_state(
                        self.anchor,
                        expected_generation=state["generation"],
                        lanes=state["lanes"],
                        scopes=scopes,
                    )
                reloaded = self.store.read_state(self.anchor)["state"]
                self.assertEqual(reloaded["generation"], state["generation"])
                self.assertEqual(
                    [
                        item["status"]
                        for item in reloaded["scopes"]
                        if item.get("owner") == "release-bypass"
                    ],
                    ["active"],
                )

    def test_prewrite_expansion_is_atomic_and_postwrite_expansion_is_rejected(self) -> None:
        self.create("expand-one", ["one.py"])
        self.create("expand-two", ["two.py"])
        waiting = self.scopes().expand(
            "expand-one",
            ["two.py", "three.py"],
            pre_write=True,
        )
        self.assertEqual(waiting["status"], "waiting-for-scope")
        expansion = [
            record
            for record in self.scope_records("expand-one")
            if record["phase"] == "expansion"
        ]
        self.assertEqual([record["status"] for record in expansion], ["waiting", "waiting"])
        self.assertEqual(
            [record["path"] for record in expansion],
            ["three.py", "two.py"],
        )
        replayed = self.scopes().expand(
            "expand-one",
            ["two.py", "three.py"],
            pre_write=True,
        )
        self.assertEqual(replayed["reservation"], waiting["reservation"])
        replayed_lane = next(
            item
            for item in self.store.read_state(self.anchor)["state"]["lanes"]
            if item["lane_id"] == "expand-one"
        )
        self.assertEqual(replayed_lane["state"], "waiting-for-scope")
        self.assertEqual(replayed_lane["scope_wait_from"], "ready")
        self.assertEqual(
            len(
                [
                    record
                    for record in self.scope_records("expand-one")
                    if record["phase"] == "expansion"
                ]
            ),
            2,
        )
        state = self.store.read_state(self.anchor)["state"]
        lanes = list(state["lanes"])
        lane = next(item for item in lanes if item["lane_id"] == "expand-one")
        lane["state"] = "running"
        lane.pop("scope_wait_from")
        lane["writer"] = {
            "lease_id": "expand-one-writer",
            "run_id": "expand-one-run",
            "allowed_set_digest": "a" * 64,
            "lease_kind": "normal-contained",
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=state["scopes"],
        )
        with self.assertRaisesRegex(ProjectScopeError, "post-write"):
            self.scopes().expand("expand-one", ["four.py"], pre_write=False)

    def test_successful_prestart_expansion_enters_fresh_runner_binding(self) -> None:
        lane = self.create("expand-granted", ["original.py"])
        expanded = self.scopes().expand(
            "expand-granted",
            [{"kind": "file", "path": "added.py", "mode": "hard"}],
            pre_write=True,
        )
        self.assertEqual(expanded["status"], "active")
        binding = self.lanes_coordinator().runner_writer_binding(
            "expand-granted",
            Path(str(lane["worktree"])),
            ["added.py"],
            require_ready=True,
        )
        self.assertEqual(binding["allowed_paths"], ["added.py"])
        with self.assertRaisesRegex(ProjectLaneError, "escapes active"):
            self.lanes_coordinator().runner_writer_binding(
                "expand-granted",
                Path(str(lane["worktree"])),
                ["added.py/child"],
                require_ready=True,
            )

    def test_live_prewrite_expansion_fails_closed_until_runner_bridge(self) -> None:
        self.create("live-expand", ["one.py"])
        self.create("live-blocker", ["two.py"])
        state = self.store.read_state(self.anchor)["state"]
        lanes = list(state["lanes"])
        lane = next(item for item in lanes if item["lane_id"] == "live-expand")
        lane["state"] = "running"
        lane["writer"] = {
            "lease_id": "live-expand-writer",
            "run_id": "live-expand-run",
            "allowed_set_digest": "f" * 64,
            "lease_kind": "normal-contained",
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=state["scopes"],
        )
        with self.assertRaisesRegex(ProjectScopeError, "post-write"):
            self.scopes().expand(
                "live-expand",
                ["two.py", "three.py"],
                pre_write=True,
            )
        state = self.store.read_state(self.anchor)["state"]
        lane = next(item for item in state["lanes"] if item["lane_id"] == "live-expand")
        self.assertNotIn("safe_stop", lane)
        claims = self.scope_records("live-expand")
        self.assertEqual(
            [(claim["path"], claim["status"]) for claim in claims],
            [("one.py", "active")],
        )

    def test_cycle_cancels_newer_cycle_edge_not_unrelated_newer_wait(self) -> None:
        self.create("cycle-a", ["a.py"])
        self.create("cycle-b", ["b.py"])
        self.create("outside", ["c.py"])
        self.assertEqual(
            self.scopes().expand("cycle-a", ["b.py"], pre_write=True)["status"],
            "waiting-for-scope",
        )
        state = self.store.read_state(self.anchor)["state"]
        lanes = list(state["lanes"])
        injected = {
            "kind": "file",
            "path": "a.py",
            "mode": "hard",
            "owner": "cycle-b",
            "status": "waiting",
            "sequence": state["generation"] + 1,
            "reservation": "cycle-b:expansion:injected",
            "phase": "expansion",
        }
        unrelated = {
            "kind": "file",
            "path": "c.py",
            "mode": "hard",
            "owner": "cycle-b",
            "status": "waiting",
            "sequence": state["generation"] + 2,
            "reservation": "cycle-b:expansion:unrelated",
            "phase": "expansion",
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=[*state["scopes"], injected, unrelated],
        )
        result = self.scopes().resolve_wait_cycles()
        self.assertEqual(result["cancelled"], ["cycle-b:expansion:injected"])
        cancelled = [
            record
            for record in self.scope_records("cycle-b")
            if record["reservation"] in {
                "cycle-b:expansion:injected",
                "cycle-b:expansion:unrelated",
            }
        ]
        self.assertEqual(
            [(record["reservation"], record["status"]) for record in cancelled],
            [
                ("cycle-b:expansion:injected", "cancelled"),
                ("cycle-b:expansion:unrelated", "waiting"),
            ],
        )

    def test_two_inactive_expansions_cancel_victim_edge_and_leave_progress(self) -> None:
        self.create("cycle-progress-a", ["a.py"])
        second = self.create("cycle-progress-b", ["b.py"])
        self.assertEqual(
            self.scopes().expand(
                "cycle-progress-a",
                ["b.py"],
                pre_write=True,
            )["status"],
            "waiting-for-scope",
        )
        victim = self.scopes().expand(
            "cycle-progress-b",
            ["a.py"],
            pre_write=True,
        )
        self.assertEqual(victim["status"], "cancelled")
        state = self.store.read_state(self.anchor)["state"]
        lanes = {lane["lane_id"]: lane for lane in state["lanes"]}
        self.assertEqual(lanes["cycle-progress-a"]["state"], "waiting-for-scope")
        self.assertEqual(lanes["cycle-progress-b"]["state"], "ready")
        self.assertEqual(self.scopes()._cycle_nodes(self.scopes()._wait_edges(state["scopes"])), [])
        binding = self.lanes_coordinator().runner_writer_binding(
            "cycle-progress-b",
            Path(str(second["worktree"])),
            ["b.py"],
            require_ready=True,
        )
        self.assertEqual(binding["allowed_paths"], ["b.py"])

    def test_live_cycle_fails_closed_without_runner_safe_stop_bridge(self) -> None:
        self.create("cycle-live-a", ["a.py"])
        self.create("cycle-live-b", ["b.py"])
        self.scopes().expand("cycle-live-a", ["b.py"], pre_write=True)
        state = self.store.read_state(self.anchor)["state"]
        lanes = list(state["lanes"])
        victim = next(item for item in lanes if item["lane_id"] == "cycle-live-b")
        victim["state"] = "running"
        victim["writer"] = {
            "lease_id": "cycle-live-b-writer",
            "run_id": "cycle-live-b-run",
            "allowed_set_digest": "b" * 64,
            "lease_kind": "normal-contained",
        }
        injected = {
            "kind": "file",
            "path": "a.py",
            "mode": "hard",
            "owner": "cycle-live-b",
            "status": "waiting",
            "sequence": state["generation"] + 1,
            "reservation": "cycle-live-b:expansion:injected",
            "phase": "expansion",
        }
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=state["generation"],
            lanes=lanes,
            scopes=[*state["scopes"], injected],
        )
        with self.assertRaisesRegex(ProjectScopeError, "runner safe-stop bridge"):
            self.scopes().resolve_wait_cycles()
        claims = [
            record
            for record in self.scope_records("cycle-live-b")
            if record["reservation"] == "cycle-live-b:expansion:injected"
        ]
        self.assertEqual([record["status"] for record in claims], ["waiting"])


if __name__ == "__main__":
    unittest.main()
