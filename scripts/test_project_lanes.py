"""Focused M1 tests for the private project coordinator state."""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import sys
import tempfile
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
    validate_transition_registry,
    validate_scope_state,
)


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


if __name__ == "__main__":
    unittest.main()
