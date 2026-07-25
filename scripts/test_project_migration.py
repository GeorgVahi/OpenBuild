from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "openbuild"
    / "skills"
    / "build"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from project_migration import (  # type: ignore[import-not-found]
    BUILD_MODES,
    CURRENT_CLIENT_VERSION,
    ProjectMigrationCoordinator,
    ProjectMigrationError,
    TRANSITION_ALIASES,
    TRANSITION_REGISTRY,
    validate_transition_registry,
)


class ProjectMigrationCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_path = (
            Path.cwd()
            / f".project-migration-{next(tempfile._get_candidate_names())}"
        )
        self.root = self.temp_path / "coordinator"
        self.common = self.temp_path / "project.git"
        self.common.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_path, ignore_errors=True)

    def coordinator(
        self, *, fault: str | None = None
    ) -> ProjectMigrationCoordinator:
        return ProjectMigrationCoordinator(
            coordinator_root=self.root,
            fault=fault,
        )

    def setup_and_identity(
        self,
    ) -> tuple[ProjectMigrationCoordinator, dict[str, object]]:
        coordinator = self.coordinator()
        self.assertEqual(
            coordinator.pre_repository_setup("run")["status"],
            "setup-initialized",
        )
        return coordinator, coordinator.project_identity(self.common)

    def publish_anchor(
        self,
        coordinator: ProjectMigrationCoordinator,
        identity: dict[str, object],
        *,
        plan: str = "plan",
        attempt: str = "attempt",
    ) -> dict[str, object]:
        issued = coordinator.issue_bootstrap_capability(
            identity,
            plan,
            attempt,
        )
        return coordinator.consume_bootstrap_capability(
            issued["bootstrap_capability"],
            identity,
            plan,
            attempt,
        )

    def test_all_build_modes_setup_before_discovery_and_continue(self) -> None:
        for mode in BUILD_MODES:
            with self.subTest(mode=mode):
                root = self.temp_path / f"coordinator-{mode}"
                coordinator = ProjectMigrationCoordinator(
                    coordinator_root=root
                )
                events: list[tuple[str, str]] = []

                result = coordinator.coordinate_build_entry(
                    mode,
                    lambda requested_mode: events.append(
                        ("discover", requested_mode)
                    )
                    or {"continued": requested_mode},
                )

                self.assertEqual(result["status"], "setup-initialized")
                self.assertEqual(result["requested_mode"], mode)
                self.assertEqual(result["continuation"], {"continued": mode})
                self.assertEqual(events, [("discover", mode)])
                self.assertNotIn("setup_receipt_path", result)
                receipt_path = (
                    root
                    / "setup-receipts"
                    / f"{result['setup_receipt']}.json"
                )
                self.assertTrue(receipt_path.is_file())

    def test_default_root_is_a_fixed_child_of_codex_home(self) -> None:
        codex_home = self.temp_path / "codex-home"
        expected = codex_home / "openbuild" / "coordinator-v1"
        coordinator = ProjectMigrationCoordinator(codex_home=codex_home)

        self.assertEqual(coordinator.root, expected)
        self.assertIn("setup-models", BUILD_MODES)

    def test_valid_setup_fast_path_is_sink_free_and_key_never_rotates(self) -> None:
        coordinator, _ = self.setup_and_identity()
        key_before = (self.root / "coordinator.key").read_bytes()
        lock_before = (self.root / "coordinator.lock").stat()

        with mock.patch(
            "project_migration._write_exclusive_json",
            side_effect=AssertionError("write"),
        ), mock.patch(
            "project_migration._replace_json",
            side_effect=AssertionError("replace"),
        ), mock.patch(
            "project_migration._locked",
            side_effect=AssertionError("lock"),
        ), mock.patch(
            "project_migration.os.chmod",
            side_effect=AssertionError("chmod"),
        ), mock.patch(
            "project_migration.os.fsync",
            side_effect=AssertionError("fsync"),
        ):
            verified = coordinator.pre_repository_setup("full")

        self.assertEqual(verified["status"], "setup-verified")
        self.assertEqual((self.root / "coordinator.key").read_bytes(), key_before)
        lock_after = (self.root / "coordinator.lock").stat()
        self.assertEqual(
            (lock_before.st_dev, lock_before.st_ino),
            (lock_after.st_dev, lock_after.st_ino),
        )

    def test_tampered_setup_requires_setup_without_project_callback(self) -> None:
        coordinator, _ = self.setup_and_identity()
        key = self.root / "coordinator.key"
        key.write_text("tampered", encoding="utf-8")
        called = False

        def discover(_: str) -> object:
            nonlocal called
            called = True
            return object()

        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        result = coordinator.coordinate_build_entry("run", discover)
        after = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))

        self.assertEqual(result["status"], "setup-required")
        self.assertFalse(called)
        self.assertEqual(before, after)
        self.assertNotIn("continuation", result)

    def test_concurrent_setup_and_capabilities_share_key_anchor_and_lock(self) -> None:
        def initialize(_: int) -> tuple[str, bytes]:
            coordinator = self.coordinator()
            result = coordinator.pre_repository_setup("auto")
            return str(result["key_id"]), (self.root / "coordinator.key").read_bytes()

        with ThreadPoolExecutor(max_workers=8) as pool:
            setup_results = list(pool.map(initialize, range(16)))
        self.assertEqual(len({item[0] for item in setup_results}), 1)
        self.assertEqual(len({item[1] for item in setup_results}), 1)

        coordinator = self.coordinator()
        identity = coordinator.project_identity(self.common)

        def anchor(index: int) -> tuple[str, str]:
            current = self.coordinator()
            published = self.publish_anchor(
                current,
                identity,
                plan=f"plan-{index}",
                attempt=f"attempt-{index}",
            )
            return (
                str(published["anchor_id"]),
                str(published["lock_id"]),
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            anchors = list(pool.map(anchor, range(12)))
        self.assertEqual(len(set(anchors)), 1)

    def test_capability_is_bound_one_use_resumable_and_gc_needs_proof(self) -> None:
        coordinator, identity = self.setup_and_identity()
        issued = coordinator.issue_bootstrap_capability(
            identity,
            "plan",
            "attempt",
        )
        capability = str(issued["bootstrap_capability"])

        interrupted = self.coordinator(fault="after-capability-consume")
        with self.assertRaisesRegex(ProjectMigrationError, "injected fault"):
            interrupted.consume_bootstrap_capability(
                capability,
                identity,
                "plan",
                "attempt",
            )
        with self.assertRaisesRegex(ProjectMigrationError, "already consumed"):
            coordinator.consume_bootstrap_capability(
                capability,
                identity,
                "plan",
                "attempt",
            )
        resumed = coordinator.resume_bootstrap_capability(
            capability,
            identity,
            "plan",
            "attempt",
        )
        self.assertEqual(resumed["status"], "anchor-ready")

        abandoned = coordinator.issue_bootstrap_capability(
            identity,
            "abandoned-plan",
            "abandoned-attempt",
        )
        temp = coordinator.create_bootstrap_temp_for_test(
            str(abandoned["bootstrap_capability"]),
            identity,
            "abandoned-plan",
            "abandoned-attempt",
        )
        coordinator.abandon_bootstrap_capability(
            str(abandoned["bootstrap_capability"]),
            identity,
            "abandoned-plan",
            "abandoned-attempt",
        )
        with self.assertRaisesRegex(ProjectMigrationError, "retention proof"):
            coordinator.gc_bootstrap_temps(
                {"before_ns": 2**63 - 1, "mac": "0" * 64}
            )
        proof = coordinator.issue_retention_proof(2**63 - 1)
        removed = coordinator.gc_bootstrap_temps(proof)
        self.assertIn(str(temp), removed["removed"])
        self.assertFalse(temp.exists())

    def test_immutable_anchor_lock_survives_mutable_records_and_compaction(self) -> None:
        coordinator, identity = self.setup_and_identity()
        anchor = self.publish_anchor(coordinator, identity)
        anchor_id = str(anchor["anchor_id"])
        lock_path = coordinator.anchor_path(anchor_id) / "anchor.lock"
        manifest_path = coordinator.anchor_path(anchor_id) / "manifest.json"
        lock_before = lock_path.stat()
        manifest_before = manifest_path.read_bytes()

        state = coordinator.bootstrap_project(
            anchor_id,
            "clean",
            attempt_id="attempt",
            evidence={"C1": "clean", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"},
        )
        self.assertEqual(state["state"], "active")
        receipt = coordinator.issue_transition_receipt(
            "O8.receipt.gc",
            anchor_id=anchor_id,
            generation=int(state["generation"]),
            attempt_id="gc-attempt",
            sink_plan=("records/receipts/old.json",),
        )
        context = coordinator.open_transition_context(
            str(receipt["transition_receipt"])
        )
        context.run_sink(
            "records/receipts/old.json",
            lambda: coordinator.write_mutable_record(
                context,
                anchor_id,
                "receipts/old.json",
                {"completed": True, "completed_ns": 0},
            ),
        )
        context.complete()
        coordinator.compact_bootstrap_records(
            anchor_id,
            retain_after_ns=1,
        )

        lock_after = lock_path.stat()
        self.assertEqual(
            (lock_before.st_dev, lock_before.st_ino),
            (lock_after.st_dev, lock_after.st_ino),
        )
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertTrue((coordinator.anchor_path(anchor_id) / "records" / "project-registry.json").is_file())

    def test_reader_writer_floors_legacy_loading_and_vacancy_retirement(self) -> None:
        coordinator, identity = self.setup_and_identity()
        anchor = self.publish_anchor(coordinator, identity)
        anchor_id = str(anchor["anchor_id"])
        state = coordinator.bootstrap_project(
            anchor_id,
            "clean",
            attempt_id="attempt",
            evidence={"C1": "clean", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"},
        )
        self.assertEqual(state["reader_floor"], CURRENT_CLIENT_VERSION)
        self.assertEqual(state["writer_floor"], CURRENT_CLIENT_VERSION)

        legacy_path = self.temp_path / "legacy.json"
        legacy = {
            "schema_version": 5,
            "reader_floor": "2.3.6",
            "generation": 9,
            "epoch": 4,
            "lease": None,
            "outbox": None,
            "protected_work": [],
        }
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        before = legacy_path.read_bytes()
        loaded = coordinator.load_legacy_registry(legacy_path)
        self.assertEqual(loaded["reader_floor"], "2.3.6")
        self.assertEqual(legacy_path.read_bytes(), before)

        lower_writer = dict(state)
        lower_writer["writer_floor"] = "99.0.0"
        registry_path = coordinator.registry_path(anchor_id)
        coordinator.replace_registry_for_test(anchor_id, lower_writer)
        before = registry_path.read_bytes()
        with self.assertRaisesRegex(ProjectMigrationError, "writer floor"):
            coordinator.update_registry(
                anchor_id,
                expected_generation=int(lower_writer["generation"]),
                changes={"protected_work": []},
            )
        self.assertEqual(registry_path.read_bytes(), before)

        coordinator.replace_registry_for_test(anchor_id, state)
        retired = coordinator.retire_registry(
            anchor_id,
            expected_generation=int(state["generation"]),
        )
        self.assertEqual(retired["state"], "retired")
        self.assertEqual(
            coordinator.retire_registry(
                anchor_id,
                expected_generation=int(retired["generation"]),
            ),
            retired,
        )

    def test_legacy_protected_actor_keeps_conflicting_scope_waiting(self) -> None:
        coordinator, identity = self.setup_and_identity()
        anchor = self.publish_anchor(coordinator, identity)
        anchor_id = str(anchor["anchor_id"])
        coordinator.bootstrap_project(
            anchor_id,
            "clean",
            attempt_id="attempt",
            evidence={"C1": "clean", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"},
            protected_work=[
                {
                    "actor_id": "legacy-window",
                    "state": "active",
                    "source": "legacy",
                    "scopes": ["file:src/legacy.py"],
                }
            ],
        )
        waiting = coordinator.admit_scope(
            anchor_id,
            "file:src/legacy.py",
        )
        ready = coordinator.admit_scope(
            anchor_id,
            "file:src/new.py",
        )
        self.assertEqual(waiting["status"], "waiting-for-scope")
        self.assertEqual(ready["status"], "ready")

    def test_transition_registry_is_complete_unique_and_alias_exact(self) -> None:
        self.assertEqual(validate_transition_registry(TRANSITION_REGISTRY), [])
        identifiers = [entry["id"] for entry in TRANSITION_REGISTRY]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertIn("BS3.E3.finalize", TRANSITION_ALIASES["release_contained_terminal"])
        self.assertNotIn("BS3.E3.finalize", TRANSITION_ALIASES["commit_handoff"])

    def test_guarded_context_rejects_wrong_reused_skipped_and_direct_sinks(self) -> None:
        coordinator, identity = self.setup_and_identity()
        anchor = self.publish_anchor(coordinator, identity)
        anchor_id = str(anchor["anchor_id"])
        state = coordinator.bootstrap_project(
            anchor_id,
            "clean",
            attempt_id="attempt",
            evidence={"C1": "clean", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"},
        )
        receipt = coordinator.issue_transition_receipt(
            "O3.scope.reserve",
            anchor_id=anchor_id,
            generation=int(state["generation"]),
            attempt_id="scope-attempt",
            sink_plan=("intent", "registry"),
        )
        context = coordinator.open_transition_context(
            str(receipt["transition_receipt"])
        )
        effects: list[str] = []
        with self.assertRaisesRegex(ProjectMigrationError, "ordered sink"):
            context.run_sink("registry", lambda: effects.append("wrong"))
        self.assertEqual(effects, [])
        context.run_sink("intent", lambda: effects.append("intent"))
        context.run_sink("registry", lambda: effects.append("registry"))
        context.complete()
        self.assertEqual(effects, ["intent", "registry"])
        with self.assertRaisesRegex(ProjectMigrationError, "used"):
            coordinator.open_transition_context(
                str(receipt["transition_receipt"])
            )
        with self.assertRaisesRegex(ProjectMigrationError, "guarded"):
            coordinator.write_mutable_record(
                None,
                anchor_id,
                "forbidden.json",
                {"value": 1},
            )
        self.assertFalse(
            (coordinator.anchor_path(anchor_id) / "records" / "forbidden.json").exists()
        )

    def test_observation_context_has_closed_argv_and_no_durable_sink(self) -> None:
        coordinator, _ = self.setup_and_identity()
        with self.assertRaisesRegex(ProjectMigrationError, "allowlist"):
            coordinator.open_observation_context(
                "R.C1.git-topology.scan",
                ["git", "reset", "--hard"],
            )
        context = coordinator.open_observation_context(
            "R.C1.git-topology.scan",
            ["git", "rev-parse", "--git-common-dir"],
        )
        with self.assertRaisesRegex(ProjectMigrationError, "observation"):
            coordinator.write_mutable_record(
                context,
                "0" * 64,
                "forbidden.json",
                {"value": 1},
            )

    def test_bootstrap_clean_replays_each_ba0_sink_without_duplicate_artifacts(self) -> None:
        evidence = {channel: "clean" for channel in ("C1", "C2", "C3", "C4", "C5")}
        for fault in ("after-record-write", "after-clean-intent", "after-registry-visibility", "after-handoff"):
            with self.subTest(fault=fault):
                root = self.temp_path / f"clean-replay-{fault}"
                coordinator = ProjectMigrationCoordinator(coordinator_root=root)
                coordinator.pre_repository_setup("run")
                identity = coordinator.project_identity(self.common)
                anchor_id = str(self.publish_anchor(coordinator, identity, plan=fault, attempt=fault)["anchor_id"])
                with self.assertRaisesRegex(ProjectMigrationError, "injected fault"):
                    ProjectMigrationCoordinator(coordinator_root=root, fault=fault).bootstrap_project(
                        anchor_id, "clean", attempt_id=fault, evidence=evidence
                    )
                replayed = coordinator.bootstrap_project(
                    anchor_id, "clean", attempt_id=fault, evidence=evidence
                )
                self.assertEqual(replayed["state"], "active")
                records = coordinator.anchor_path(anchor_id) / "records"
                self.assertEqual(
                    sorted(path.name for path in records.iterdir()),
                    ["bootstrap-receipt.json", "clean-intent.json", "handoff.json", "project-registry.json"],
                )

    def test_bootstrap_incident_replay_rejects_mismatch_and_tamper(self) -> None:
        evidence = {"C1": "breach", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"}
        coordinator, identity = self.setup_and_identity()
        anchor_id = str(self.publish_anchor(coordinator, identity)["anchor_id"])
        with self.assertRaisesRegex(ProjectMigrationError, "injected fault"):
            self.coordinator(fault="after-incident-intent").bootstrap_project(
                anchor_id, "breach", attempt_id="attempt", evidence=evidence
            )
        with self.assertRaisesRegex(ProjectMigrationError, "does not match bootstrap replay"):
            coordinator.bootstrap_project(
                anchor_id, "breach", attempt_id="other", evidence=evidence
            )
        incident = coordinator.bootstrap_project(
            anchor_id, "breach", attempt_id="attempt", evidence=evidence
        )
        self.assertEqual(incident["state"], "incident-active")
        handoff = coordinator.anchor_path(anchor_id) / "records" / "handoff.json"
        payload = json.loads(handoff.read_text(encoding="utf-8"))
        payload["outcome"] = "clean"
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ProjectMigrationError, "digest is invalid"):
            coordinator.bootstrap_project(
                anchor_id, "breach", attempt_id="attempt", evidence=evidence
            )

    def test_bootstrap_incident_replays_each_ba0_sink(self) -> None:
        evidence = {"C1": "breach", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"}
        for fault in ("after-record-write", "after-incident-intent", "after-incident-visibility", "after-handoff"):
            with self.subTest(fault=fault):
                root = self.temp_path / f"incident-replay-{fault}"
                coordinator = ProjectMigrationCoordinator(coordinator_root=root)
                coordinator.pre_repository_setup("run")
                identity = coordinator.project_identity(self.common)
                anchor_id = str(self.publish_anchor(coordinator, identity, plan=fault, attempt=fault)["anchor_id"])
                with self.assertRaisesRegex(ProjectMigrationError, "injected fault"):
                    ProjectMigrationCoordinator(coordinator_root=root, fault=fault).bootstrap_project(
                        anchor_id, "breach", attempt_id=fault, evidence=evidence
                    )
                replayed = coordinator.bootstrap_project(
                    anchor_id, "breach", attempt_id=fault, evidence=evidence
                )
                self.assertEqual(replayed["state"], "incident-active")
                records = coordinator.anchor_path(anchor_id) / "records"
                self.assertEqual(
                    sorted(path.name for path in records.iterdir()),
                    ["bootstrap-incident.json", "bootstrap-receipt.json", "handoff.json", "incident-intent.json"],
                )

    def test_clean_breach_and_clear_faults_converge(self) -> None:
        coordinator, identity = self.setup_and_identity()
        clean_anchor = self.publish_anchor(coordinator, identity)
        clean_id = str(clean_anchor["anchor_id"])
        clean = coordinator.bootstrap_project(
            clean_id,
            "clean",
            attempt_id="clean",
            evidence={"C1": "clean", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"},
        )
        self.assertEqual(clean["state"], "active")
        self.assertFalse(coordinator.bs_path(clean_id).exists())

        other_common = self.temp_path / "other.git"
        other_common.mkdir()
        other_identity = coordinator.project_identity(other_common)
        breach_anchor = self.publish_anchor(
            coordinator,
            other_identity,
            plan="breach-plan",
            attempt="breach-attempt",
        )
        breach_id = str(breach_anchor["anchor_id"])
        incident = coordinator.bootstrap_project(
            breach_id,
            "breach",
            attempt_id="breach",
            evidence={"C1": "breach", "C2": "clean", "C3": "clean", "C4": "clean", "C5": "clean"},
            protected_work=[
                {
                    "actor_id": "legacy",
                    "state": "vacant",
                    "source": "legacy",
                    "scopes": ["file:kept.txt"],
                }
            ],
        )
        self.assertEqual(incident["state"], "incident-active")
        drained = coordinator.drain_bootstrap_incident(
            breach_id,
            expected_generation=int(incident["generation"]),
        )
        interrupted = self.coordinator(fault="after-registry-visibility")
        with self.assertRaisesRegex(ProjectMigrationError, "injected fault"):
            interrupted.clear_bootstrap_incident(
                breach_id,
                expected_generation=int(drained["generation"]),
            )
        cleared = coordinator.clear_bootstrap_incident(
            breach_id,
            expected_generation=int(drained["generation"]),
        )
        self.assertEqual(cleared["state"], "active")
        self.assertEqual(cleared["generation"], 0)
        self.assertEqual(cleared["protected_work"][0]["scopes"], ["file:kept.txt"])
        self.assertEqual(coordinator.read_bootstrap_incident(breach_id)["state"], "complete")

    def test_path_link_and_identity_changes_fail_closed(self) -> None:
        coordinator, _ = self.setup_and_identity()
        link = self.temp_path / "common-link"
        try:
            link.symlink_to(self.common, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks are unavailable")
        with self.assertRaisesRegex(ProjectMigrationError, "link or reparse"):
            coordinator.project_identity(link)


if __name__ == "__main__":
    unittest.main()
