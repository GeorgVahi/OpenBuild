"""Focused R-032 M6 tests for durable runtime capacity and isolation."""

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
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest import mock


sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "openbuild"
        / "skills"
        / "build"
        / "scripts"
    ),
)

from project_integrator import ProjectIntegrator  # type: ignore[import-not-found]
from project_lanes import ProjectLaneCoordinator  # type: ignore[import-not-found]
from project_runtime import ProjectRuntimeCoordinator  # type: ignore[import-not-found]
from project_scopes import ProjectScopeManager  # type: ignore[import-not-found]
import agent_runner  # type: ignore[import-not-found]
import project_state  # type: ignore[import-not-found]
import recovery_state  # type: ignore[import-not-found]
from project_state import (  # type: ignore[import-not-found]
    ProjectStateError,
    ProjectStateStore,
    _canonical,
    _digest,
)


def hard(path: str, *, kind: str = "file") -> dict[str, str]:
    return {"kind": kind, "path": path, "mode": "hard"}


class ProjectRuntimeM6Tests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path.cwd() / ".git" / "t"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="m6-runtime-", dir=test_root))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self._windows_dacl_patches: list[mock._patch] = []
        if os.name == "nt":
            # The managed test sandbox's access group is intentionally absent
            # from a real current-user-only DACL.  Keep the production code
            # strict and use ordinary private fixture directories here so the
            # state-machine contracts remain runnable.
            self._windows_dacl_patches = [
                mock.patch.object(project_state, "_windows_object_is_private", return_value=True),
                mock.patch.object(project_state, "_protect_windows_private_object", return_value=None),
                mock.patch.object(
                    project_state,
                    "_create_windows_private_directory",
                    side_effect=lambda path, user_sid: path.mkdir(exist_ok=True),
                ),
                mock.patch.object(
                    project_state,
                    "_windows_move_write_through",
                    side_effect=self._windows_move,
                ),
                mock.patch.object(recovery_state, "_windows_directory_is_private", return_value=True),
                mock.patch.object(recovery_state, "_protect_windows_directory", return_value=None),
            ]
            for patcher in self._windows_dacl_patches:
                patcher.start()
                self.addCleanup(patcher.stop)
        self.checkout = self.temp / "checkout"
        self.checkout.mkdir()
        for args in (
            ("init",),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "OpenBuild test"),
        ):
            subprocess.run(
                ["git", *args],
                cwd=self.checkout,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        (self.checkout / "base.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."],
            cwd=self.checkout,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "commit", "-m", "base"],
            cwd=self.checkout,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.integration_ref = "refs/openbuild/integration"
        subprocess.run(
            ["git", "update-ref", self.integration_ref, "HEAD"],
            cwd=self.checkout,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.store = ProjectStateStore(
            self.checkout,
            coordinator_root=self.temp / "state",
        )
        capability = self.store.issue_bootstrap_capability("plan", "attempt")[
            "bootstrap_capability"
        ]
        self.anchor = self.store.create_anchor(capability, "plan", "attempt")[
            "anchor_id"
        ]
        self.store.bootstrap(self.anchor, "clean")
        self.runtime = ProjectRuntimeCoordinator(self.store, self.anchor)
        (self.temp / "lanes").mkdir()
        self.lanes = ProjectLaneCoordinator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.temp / "recovery",
            lane_root=self.temp / "lanes",
            integration_ref=self.integration_ref,
        )
        self.integrator = ProjectIntegrator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.temp / "recovery",
            integration_checkout=self.temp / "integration",
            integration_ref=self.integration_ref,
        )

    def _runner_request_fixture(
        self,
        lane_id: str,
    ) -> dict[str, Any]:
        allowed_path = f"{lane_id}.txt"
        lane = self.lanes.create(
            lane_id,
            "m6",
            self.temp / "lanes" / lane_id,
            [hard(allowed_path)],
        )
        lease_id = f"{lane_id}-lease"
        runtime_claim = f"{lane_id}-run"
        project_lane = agent_runner.resolve_project_lane_start(
            Namespace(
                project_lane_id=lane_id,
                project_checkout=str(self.checkout),
                project_coordinator_root=str(self.temp / "state"),
                project_anchor_id=self.anchor,
                project_recovery_root=str(self.temp / "recovery"),
                project_lane_root=str(self.temp / "lanes"),
                project_integration_ref=self.integration_ref,
                lease_id=lease_id,
                _project_runtime_claim=runtime_claim,
            ),
            agent_name="openbuild_implementation_balanced",
            repo=Path(str(lane["worktree"])),
            allowed_files=[allowed_path],
        )
        assert project_lane is not None
        return {
            "repo": str(lane["worktree"]),
            "lease_id": lease_id,
            "project_runtime_claim": runtime_claim,
            "project_lane": project_lane,
        }

    def _terminal_runner_fixture(
        self,
        lane_id: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        request = self._runner_request_fixture(lane_id)
        lease_id = str(request["lease_id"])
        runtime_claim = str(request["project_runtime_claim"])
        writer = {
            "lease_id": lease_id,
            "run_id": runtime_claim,
            "allowed_set_digest": "a" * 64,
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
            self.lanes,
            "_assert_legacy_vacancy",
        ), mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=active_registry,
        ), mock.patch(
            "project_state.RecoveryRegistry",
            return_value=active_registry,
        ):
            self.lanes.attach_contained_writer(
                lane_id,
                lease_id=writer["lease_id"],
                run_id=writer["run_id"],
                allowed_set_digest=writer["allowed_set_digest"],
            )
        return request, writer

    @staticmethod
    def _runner_terminal_registry(
        writer: dict[str, str],
        *,
        success: bool,
    ) -> mock.Mock:
        release: dict[str, Any] = {
            "event": "contained-terminal-released",
            **writer,
            "terminal_success": success,
            "archive_digest": "b" * 64,
        }
        if success:
            release.update(
                {
                    "semantic_disposition": None,
                    "final_state": "handoff-committed",
                    "handoff_digest": "c" * 64,
                },
            )
        else:
            release.update(
                {
                    "semantic_disposition": None,
                    "handoff_digest": None,
                    "outbox_digest": None,
                },
            )
        registry = mock.Mock()
        registry.state.return_value = {
            "lease": None,
            "outbox": None,
            "quarantine": None,
            "history": [release],
        }
        return registry

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    @staticmethod
    def _windows_move(source: Path, target: Path, *, replace: bool) -> None:
        if not replace and target.exists():
            raise FileExistsError(str(target))
        os.replace(source, target)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.checkout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            self.fail(result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("ascii", "strict").strip()

    @unittest.skipUnless(os.name == "nt", "Windows mutable replace retry")
    def test_mutable_state_replace_retries_transient_windows_file_locks(self) -> None:
        path = self.temp / "replace-retry" / "state.json"
        attempts = 0

        def transient_move(source: Path, target: Path, *, replace: bool) -> None:
            nonlocal attempts
            if replace:
                attempts += 1
                if attempts < 3:
                    failure = PermissionError(13, "transient test lock", str(target))
                    failure.winerror = 5
                    raise failure
            self._windows_move(source, target, replace=replace)

        with mock.patch.object(
            project_state,
            "_windows_move_write_through",
            side_effect=transient_move,
        ):
            project_state._replace_json(path, {"schema": 1, "value": "published"})

        self.assertEqual(attempts, 3)
        self.assertEqual(project_state._read_json(path)["value"], "published")

    def _terminal_lane(
        self,
        lane_id: str,
        path: str,
        *,
        write_path: str | None = None,
    ) -> dict[str, object]:
        self.lanes.create(
            lane_id,
            "m6",
            self.temp / "lanes" / lane_id,
            [hard(path)],
        )
        return self._terminalize_existing_lane(
            lane_id,
            path,
            write_path=write_path,
        )

    def _terminalize_existing_lane(
        self,
        lane_id: str,
        path: str,
        *,
        write_path: str | None = None,
    ) -> dict[str, object]:
        lane = next(
            item
            for item in self.store.read_state(self.anchor)["state"]["lanes"]
            if item["lane_id"] == lane_id
        )
        worktree = Path(str(lane["worktree"]))
        changed_path = write_path or path
        (worktree / changed_path).write_text(f"{lane_id}\n", encoding="utf-8")
        self.git("add", changed_path, cwd=worktree)
        self.git("commit", "-m", lane_id, cwd=worktree)
        state = self.store.read_state(self.anchor)["state"]
        lanes = [dict(item) for item in state["lanes"]]
        terminal = next(item for item in lanes if item["lane_id"] == lane_id)
        terminal["state"] = "running"
        bound_allowed_set = terminal["dependency_binding"].get(
            "allowed_set_digest",
        )
        allowed_set_digest = (
            bound_allowed_set
            if isinstance(bound_allowed_set, str)
            else "a" * 64
        )
        terminal["writer"] = {
            "lease_id": f"{lane_id}-lease",
            "run_id": f"{lane_id}-run",
            "allowed_set_digest": allowed_set_digest,
            "lease_kind": "normal-contained",
        }
        terminal["dependency_binding"] = {
            **terminal["dependency_binding"],
            "allowed_set_digest": terminal["writer"]["allowed_set_digest"],
        }
        active = mock.Mock()
        active.state.return_value = {
            "lease": {**terminal["writer"], "state": "running"},
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        with mock.patch("project_state.RecoveryRegistry", return_value=active):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=int(state["generation"]),
                lanes=lanes,
                scopes=state["scopes"],
            )
        state = self.store.read_state(self.anchor)["state"]
        lanes = [dict(item) for item in state["lanes"]]
        terminal = next(item for item in lanes if item["lane_id"] == lane_id)
        terminal["state"] = "waiting-for-integration"
        terminal["terminal_evidence"] = "b" * 64
        self.store.replace_lane_state(
            self.anchor,
            expected_generation=int(state["generation"]),
            lanes=lanes,
            scopes=state["scopes"],
        )
        return next(
            item
            for item in self.store.read_state(self.anchor)["state"]["lanes"]
            if item["lane_id"] == lane_id
        )

    @staticmethod
    def _terminal_registry(lane: dict[str, object]) -> dict[str, object]:
        writer = lane["writer"]
        assert isinstance(writer, dict)
        return {
            "lease": None,
            "outbox": None,
            "quarantine": None,
            "history": [
                {
                    "event": "contained-terminal-released",
                    "lease_id": writer["lease_id"],
                    "run_id": writer["run_id"],
                    "lease_kind": writer["lease_kind"],
                    "allowed_set_digest": writer["allowed_set_digest"],
                    "terminal_success": True,
                    "semantic_disposition": None,
                    "final_state": "handoff-committed",
                    "archive_digest": lane["terminal_evidence"],
                    "handoff_digest": "c" * 64,
                    "outbox_digest": "d" * 64,
                },
            ],
        }

    def test_capacity_is_fifo_monotonic_and_releases_namespace(self) -> None:
        self.runtime.configure_capacity(2)
        first = self.runtime.acquire("lane-a", port=8080)
        second = self.runtime.acquire("lane-b", port=8080)
        third = self.runtime.acquire("lane-c")
        fourth = self.runtime.acquire("lane-d", port=8081)
        self.assertEqual([first["ticket"], second["ticket"], third["ticket"]], [1, 2, 3])
        self.assertEqual(first["status"], "running")
        self.assertEqual(second["status"], "waiting-for-capacity")
        self.assertEqual(third["status"], "running")
        self.assertEqual(
            set(first["namespaces"]),
            {"port", "test-db", "compose", "temp", "build"},
        )
        self.assertEqual(len(set(first["namespaces"].values())), 5)
        self.assertNotEqual(first["namespaces"], third["namespaces"])
        self.runtime.release("lane-a")
        promoted = self.runtime.status("lane-b")
        self.assertEqual(promoted["status"], "running")
        self.assertEqual(promoted["ticket"], 2)
        self.assertEqual(self.runtime.status("lane-d")["status"], "waiting-for-capacity")
        self.assertNotIn("8080", json.dumps(promoted, sort_keys=True))
        self.runtime.release("lane-c")
        self.assertEqual(self.runtime.status("lane-d")["status"], "running")
        completed = self.runtime.release("lane-b")
        replay = self.runtime.release("lane-b")
        self.assertEqual((completed["status"], replay["status"]), ("complete", "complete"))

    def test_priority_integration_is_fifo_per_class_and_preserves_scope_waiter(self) -> None:
        holder = self.lanes.create(
            "scope-holder", "m6", self.temp / "lanes" / "scope-holder", [hard("shared.txt")]
        )
        waiter = self.lanes.create(
            "scope-waiter", "m6", self.temp / "lanes" / "scope-waiter", [hard("shared.txt")]
        )
        newer_waiter = self.lanes.create(
            "scope-newer", "m6", self.temp / "lanes" / "scope-newer", [hard("shared.txt")]
        )
        self.assertEqual((holder["state"], waiter["state"]), ("ready", "waiting-for-scope"))
        self.assertEqual(newer_waiter["state"], "waiting-for-scope")
        before = [
            dict(item)
            for item in self.store.read_state(self.anchor)["state"]["scopes"]
            if item.get("owner") in {"scope-waiter", "scope-newer"}
        ]
        self.runtime.configure_capacity(1)
        self.runtime.acquire("capacity-owner")
        capacity_waiter = self.runtime.acquire("capacity-waiter")
        ordinary_a = self._terminal_lane("ordinary-a", "ordinary-a.txt")
        ordinary_b = self._terminal_lane("ordinary-b", "ordinary-b.txt")
        priority_a = self._terminal_lane("priority-a", "priority-a.txt")
        priority_b = self._terminal_lane("priority-b", "priority-b.txt")
        terminal_lanes = (ordinary_a, ordinary_b, priority_a, priority_b)
        registries = {
            str(lane["worktree"]): self._terminal_registry(lane)
            for lane in terminal_lanes
        }

        def registry_factory(worktree: Path, *, state_root: Path):
            del state_root
            value = mock.Mock()
            value.state.return_value = registries[str(worktree)]
            return value

        with mock.patch("project_state.RecoveryRegistry", side_effect=registry_factory), mock.patch(
            "project_integrator.RecoveryRegistry", side_effect=registry_factory
        ):
            for lane_id in ("ordinary-a", "ordinary-b"):
                self.integrator.enqueue(
                    lane_id,
                    validation_argv=[sys.executable, "-c", "raise SystemExit(19)"],
                )
            for lane_id in ("priority-a", "priority-b"):
                self.integrator.enqueue(
                    lane_id,
                    validation_argv=[sys.executable, "-c", "raise SystemExit(19)"],
                    dependency_unblocking=True,
                )
            positions = {
                lane_id: self.runtime.public_status(lane_id)["position"]
                for lane_id in (
                    "ordinary-a",
                    "ordinary-b",
                    "priority-a",
                    "priority-b",
                )
            }
            self.assertEqual(
                positions,
                {
                    "ordinary-a": 3,
                    "ordinary-b": 4,
                    "priority-a": 1,
                    "priority-b": 2,
                },
            )
            integration_order = [
                self.integrator.integrate_next()["result"]["lane_id"]
                for _ in range(4)
            ]
        self.assertEqual(
            integration_order,
            ["priority-a", "priority-b", "ordinary-a", "ordinary-b"],
        )
        after = [
            dict(item)
            for item in self.store.read_state(self.anchor)["state"]["scopes"]
            if item.get("owner") in {"scope-waiter", "scope-newer"}
        ]
        self.assertEqual(after, before)
        self.assertEqual(
            self.runtime.status("capacity-waiter")["ticket"],
            capacity_waiter["ticket"],
        )
        self.assertEqual(
            self.runtime.public_status("scope-waiter")["position"],
            1,
        )
        self.assertEqual(
            self.runtime.public_status("scope-newer")["position"],
            2,
        )
        terminal_holder = self._terminalize_existing_lane(
            "scope-holder",
            "shared.txt",
        )
        holder_registry = self._terminal_registry(terminal_holder)

        def holder_registry_factory(worktree: Path, *, state_root: Path):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = holder_registry
            return value

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=holder_registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=holder_registry_factory,
        ):
            self.integrator.enqueue(
                "scope-holder",
                validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
            )
            self.assertEqual(self.integrator.integrate_next()["status"], "released")
        for ordinal, lane_id in enumerate(
            ("scope-waiter", "scope-newer"),
            start=1,
        ):
            self.lanes.refresh_integration_stale(
                lane_id,
                allowed_set_digest=f"{ordinal:064x}",
                specification_revision="R-032",
            )
        scope_manager = ProjectScopeManager(
            self.store,
            self.anchor,
            checkout=self.checkout,
        )
        scope_manager.reserve_planned(
            "scope-newer",
            [hard("shared.txt")],
        )
        scope_status = {
            item["owner"]: item["status"]
            for item in self.store.read_state(self.anchor)["state"]["scopes"]
            if item.get("owner") in {"scope-waiter", "scope-newer"}
            and item.get("kind") == "file"
        }
        self.assertEqual(scope_status["scope-waiter"], "active")
        self.assertEqual(scope_status["scope-newer"], "waiting")

    def test_runner_bridge_applies_capacity_namespaces_and_resource_scope(
        self,
    ) -> None:
        self.runtime.configure_capacity(2)
        lanes = {
            "bridge-one": self.lanes.create(
                "bridge-one",
                "m6",
                self.temp / "lanes" / "bridge-one",
                [
                    hard("bridge-one.txt"),
                    hard("port/9301", kind="resource"),
                ],
            ),
            "bridge-two": self.lanes.create(
                "bridge-two",
                "m6",
                self.temp / "lanes" / "bridge-two",
                [
                    hard("bridge-two.txt"),
                    hard("port/9302", kind="resource"),
                ],
            ),
            "bridge-collision": self.lanes.create(
                "bridge-collision",
                "m6",
                self.temp / "lanes" / "bridge-collision",
                [
                    hard("bridge-collision.txt"),
                    hard("port/9301", kind="resource"),
                ],
            ),
            "bridge-capacity": self.lanes.create(
                "bridge-capacity",
                "m6",
                self.temp / "lanes" / "bridge-capacity",
                [
                    hard("bridge-capacity.txt"),
                    hard("port/9303", kind="resource"),
                ],
            ),
        }
        self.assertEqual(lanes["bridge-collision"]["state"], "waiting-for-scope")

        def args(lane_id: str) -> Namespace:
            return Namespace(
                project_lane_id=lane_id,
                project_checkout=str(self.checkout),
                project_coordinator_root=str(self.temp / "state"),
                project_anchor_id=self.anchor,
                project_recovery_root=str(self.temp / "recovery"),
                project_lane_root=str(self.temp / "lanes"),
                project_integration_ref=self.integration_ref,
                lease_id=f"{lane_id}-lease",
            )

        bindings = {
            lane_id: agent_runner.resolve_project_lane_start(
                args(lane_id),
                agent_name="openbuild_implementation_balanced",
                repo=Path(str(lanes[lane_id]["worktree"])),
                allowed_files=[f"{lane_id}.txt"],
            )
            for lane_id in ("bridge-one", "bridge-two")
        }
        for binding in bindings.values():
            assert binding is not None
            self.assertEqual(
                set(binding["lane_binding"]["runtime"]["namespaces"]),
                {"port", "test-db", "compose", "temp", "build"},
            )
        self.assertEqual(
            self.runtime.public_status("bridge-one")["state"],
            "running",
        )
        environments = {
            lane_id: agent_runner.project_runtime_environment(
                {"project_lane": binding},
            )
            for lane_id, binding in bindings.items()
        }
        self.assertEqual(environments["bridge-one"]["OPENBUILD_RUNTIME_PORT"], "9301")
        self.assertEqual(environments["bridge-two"]["OPENBUILD_RUNTIME_PORT"], "9302")
        for key in (
            "OPENBUILD_TEST_DB_NAMESPACE",
            "COMPOSE_PROJECT_NAME",
            "OPENBUILD_TEMP_NAMESPACE",
            "OPENBUILD_BUILD_NAMESPACE",
        ):
            self.assertNotEqual(
                environments["bridge-one"][key],
                environments["bridge-two"][key],
            )
        with self.assertRaisesRegex(
            agent_runner.RunnerError,
            "rejected runner start",
        ):
            agent_runner.resolve_project_lane_start(
                args("bridge-collision"),
                agent_name="openbuild_implementation_balanced",
                repo=Path(str(lanes["bridge-collision"]["worktree"])),
                allowed_files=["bridge-collision.txt"],
            )
        self.assertFalse(
            any(
                item.get("lane_id") == "bridge-collision"
                for item in self.store.read_state(self.anchor)["state"]["runtime"]["jobs"]
            ),
        )
        with self.assertRaisesRegex(
            agent_runner.RunnerError,
            "runtime capacity is not available",
        ):
            agent_runner.resolve_project_lane_start(
                args("bridge-capacity"),
                agent_name="openbuild_implementation_balanced",
                repo=Path(str(lanes["bridge-capacity"]["worktree"])),
                allowed_files=["bridge-capacity.txt"],
            )
        capacity_projection = self.runtime.public_status("bridge-capacity")
        self.assertEqual(
            (
                capacity_projection["state"],
                capacity_projection["reason_code"],
                capacity_projection["position"],
            ),
            ("blocked", "capacity-wait", 1),
        )
        agent_runner.release_project_lane_runtime(
            {"project_lane": bindings["bridge-one"]},
        )
        resumed = agent_runner.resolve_project_lane_start(
            args("bridge-capacity"),
            agent_name="openbuild_implementation_balanced",
            repo=Path(str(lanes["bridge-capacity"]["worktree"])),
            allowed_files=["bridge-capacity.txt"],
        )
        assert resumed is not None
        bindings["bridge-capacity"] = resumed
        bindings.pop("bridge-one")
        released = [
            agent_runner.release_project_lane_runtime(
                {"project_lane": binding},
            )
            for binding in bindings.values()
        ]
        self.assertTrue(
            all(
                item is not None and item["status"] == "complete"
                for item in released
            )
        )

    def test_runner_child_environment_replaces_ambient_managed_runtime_values(
        self,
    ) -> None:
        def request(port: int | None) -> dict[str, object]:
            return {
                "project_lane": {
                    "lane_binding": {
                        "runtime": {
                            "schema": "project-lane-runtime-v1",
                            "job_id": "environment-job",
                            "lane_id": "environment-lane",
                            "ticket": 1,
                            "namespace": "ob-environment",
                            "namespaces": {
                                "port": "ob-environment-port",
                                "test-db": "ob-environment-db",
                                "compose": "ob-environment-compose",
                                "temp": "ob-environment-temp",
                                "build": "ob-environment-build",
                            },
                            "port": port,
                            "owner_digest": "a" * 64,
                        },
                    },
                },
            }

        ambient = {
            "PATH": os.environ.get("PATH", ""),
            "OPENBUILD_RUNTIME_NAMESPACE": "ambient-runtime",
            "OPENBUILD_RUNTIME_PORT_NAMESPACE": "ambient-port-namespace",
            "OPENBUILD_RUNTIME_PORT": "9999",
            "OPENBUILD_TEST_DB_NAMESPACE": "ambient-db",
            "COMPOSE_PROJECT_NAME": "ambient-compose",
            "OPENBUILD_TEMP_NAMESPACE": "ambient-temp",
            "OPENBUILD_BUILD_NAMESPACE": "ambient-build",
        }
        unscoped = agent_runner.scrub_api_credentials(ambient)
        unscoped.update(agent_runner.project_runtime_environment(request(None)))
        scoped = agent_runner.scrub_api_credentials(ambient)
        scoped.update(agent_runner.project_runtime_environment(request(9301)))

        self.assertNotIn("OPENBUILD_RUNTIME_PORT", unscoped)
        self.assertEqual(scoped["OPENBUILD_RUNTIME_PORT"], "9301")
        for key, value in unscoped.items():
            if key != "PATH":
                self.assertNotIn("ambient", value)

    def test_successful_terminal_replays_after_runtime_release(
        self,
    ) -> None:
        request, writer = self._terminal_runner_fixture("terminal-success")
        registry = self._runner_terminal_registry(writer, success=True)
        with mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=registry,
        ):
            expected = self.lanes.record_successful_terminal("terminal-success")
        agent_runner.release_project_lane_runtime(request)

        self.assertEqual(
            self.runtime.status(
                request["project_lane"]["lane_binding"]["runtime"]["job_id"],
            )["status"],
            "complete",
        )
        self.assertEqual(
            agent_runner.complete_project_lane_writer(request),
            expected,
        )

    def test_recovery_ready_replays_after_runtime_release(
        self,
    ) -> None:
        request, writer = self._terminal_runner_fixture("terminal-recovery")
        self.lanes.cancel_or_crash("terminal-recovery", "crashed")
        registry = self._runner_terminal_registry(writer, success=False)
        checkpoint_digest = "d" * 64
        with mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=registry,
        ), mock.patch(
            "project_state.RecoveryRegistry",
            return_value=registry,
        ):
            expected = self.lanes.record_recovery_ready(
                "terminal-recovery",
                checkpoint_digest,
            )
        agent_runner.release_project_lane_runtime(request)

        self.assertEqual(
            agent_runner.prepare_project_lane_recovery(
                request,
                checkpoint_digest,
            ),
            expected,
        )

    def test_closed_terminal_replays_after_runtime_release(
        self,
    ) -> None:
        request, writer = self._terminal_runner_fixture("terminal-closed")
        self.lanes.cancel_or_crash("terminal-closed", "crashed")
        registry = self._runner_terminal_registry(writer, success=False)
        with mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=registry,
        ):
            expected = self.lanes.close_terminal("terminal-closed")
        agent_runner.release_project_lane_runtime(request)

        self.assertEqual(
            agent_runner.finalize_project_lane_terminal(
                request,
                "crashed",
            ),
            expected,
        )

    def test_completed_runtime_is_rejected_before_terminal_lane_state(
        self,
    ) -> None:
        request, _ = self._terminal_runner_fixture("terminal-live")
        agent_runner.release_project_lane_runtime(request)

        with self.assertRaisesRegex(
            agent_runner.RunnerError,
            "runtime capacity is not available",
        ):
            agent_runner.complete_project_lane_writer(request)

    def test_completed_safe_stop_replay_releases_runtime_before_receipt(
        self,
    ) -> None:
        request = self._runner_request_fixture("safe-stop-replay")
        runtime_job_id = request["project_lane"]["lane_binding"]["runtime"]["job_id"]
        completion = {
            "status": "completed",
            "intent_id": "e" * 64,
            "lane_id": "safe-stop-replay",
            "completed_state": "ready",
            "terminal_archive": "f" * 64,
            "completed_generation": 9,
        }
        registry = mock.Mock()
        registry.state.return_value = {
            "lease": None,
            "outbox": None,
            "quarantine": None,
        }
        run_dir = self.temp / "safe-stop-run"
        run_dir.mkdir()
        receipt = {
            "status": "completed",
            "process_tree_stopped": True,
        }
        request_with_profile = {
            **request,
            "profile": {"name": "openbuild_implementation_balanced"},
        }
        with mock.patch.object(
            agent_runner,
            "read_json",
            return_value=request_with_profile,
        ), mock.patch.object(
            agent_runner,
            "recovery_registry_for_request",
            return_value=registry,
        ), mock.patch.object(
            agent_runner,
            "project_lane_safe_stop_binding",
            return_value=(self.lanes, completion),
        ), mock.patch.object(
            agent_runner,
            "garbage_collect_owner_prompt_snapshots",
            return_value=set(),
        ):
            with mock.patch.object(
                agent_runner,
                "materialize_project_lane_safe_stop_receipt",
                side_effect=SystemExit("simulated post-completion receipt crash"),
            ), self.assertRaises(SystemExit):
                agent_runner.reconcile_implementation_registry(
                    run_dir,
                    receipt,
                )
            self.assertEqual(
                self.runtime.status(runtime_job_id)["status"],
                "complete",
            )
            with mock.patch.object(
                agent_runner,
                "materialize_project_lane_safe_stop_receipt",
            ):
                agent_runner.reconcile_implementation_registry(
                    run_dir,
                    receipt,
                )
        self.assertEqual(
            self.runtime.status(runtime_job_id)["status"],
            "complete",
        )

    def test_public_status_is_complete_after_successful_integration(
        self,
    ) -> None:
        lane = self._terminal_lane(
            "status-integrated",
            "status-integrated.txt",
        )
        registry_state = self._terminal_registry(lane)

        def registry_factory(worktree: Path, *, state_root: Path):
            del worktree, state_root
            registry = mock.Mock()
            registry.state.return_value = registry_state
            return registry

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=registry_factory,
        ):
            self.integrator.enqueue(
                "status-integrated",
                validation_argv=[
                    "git",
                    "diff",
                    "--check",
                    "HEAD^",
                    "HEAD",
                ],
            )
            self.assertEqual(
                self.integrator.integrate_next()["status"],
                "released",
            )

        projection = self.runtime.public_status("status-integrated")
        self.assertEqual(
            (
                projection["state"],
                projection["reason_code"],
                projection["next_action"],
            ),
            (
                "complete",
                "integration-complete",
                "none",
            ),
        )

    def test_failed_runner_start_releases_acquired_runtime_capacity(
        self,
    ) -> None:
        self.runtime.configure_capacity(1)
        lane = self.lanes.create(
            "bridge-failed-start",
            "m6",
            self.temp / "lanes" / "bridge-failed-start",
            [hard("bridge-failed-start.txt")],
        )
        args = Namespace(
            repo=str(lane["worktree"]),
            prompt_file=None,
            prompt_snapshot_id=None,
            prompt_sha256=None,
            search_fallback_source=None,
            expected_map_sha256=None,
            agent="openbuild_implementation_balanced",
            lease_id="bridge-failed-start-lease",
            allowed_file=["bridge-failed-start.txt"],
            specification_revision="R-032",
            recovery_target_milestone="m6",
            project_lane_id="bridge-failed-start",
            project_checkout=str(self.checkout),
            project_coordinator_root=str(self.temp / "state"),
            project_anchor_id=self.anchor,
            project_recovery_root=str(self.temp / "recovery"),
            project_lane_root=str(self.temp / "lanes"),
            project_integration_ref=self.integration_ref,
            run_dir=str(self.temp / "failed-start-run"),
            task_name="m6-failed-start",
            activation_timeout=300.0,
            codex_bin="codex",
        )
        occupied_registry = mock.Mock()
        occupied_registry.state.return_value = {
            "lease": {
                "lease_id": "different-lease",
                "lease_kind": "normal-contained",
                "state": "running",
            },
        }
        with mock.patch.object(
            agent_runner,
            "recovery_registry_for_agent",
            return_value=occupied_registry,
        ), self.assertRaisesRegex(
            agent_runner.RunnerError,
            "workspace is not vacant",
        ):
            agent_runner.start_run(args)

        runtime = self.store.read_state(self.anchor)["state"]["runtime"]
        self.assertEqual(runtime["jobs"], [])
        completed = next(
            item
            for item in runtime["completed"]
            if item.get("lane_id") == "bridge-failed-start"
        )
        self.assertEqual(completed["status"], "complete")
        replacement = self.runtime.acquire("bridge-after-failed-start")
        self.assertEqual(replacement["status"], "running")
        self.runtime.release("bridge-after-failed-start")

    def test_duplicate_same_lease_dispatch_cannot_release_live_runtime_slot(
        self,
    ) -> None:
        self.runtime.configure_capacity(2)
        lane = self.lanes.create(
            "bridge-duplicate-start",
            "m6",
            self.temp / "lanes" / "bridge-duplicate-start",
            [hard("bridge-duplicate-start.txt")],
        )

        def resolve(claim: str) -> dict[str, object] | None:
            args = Namespace(
                project_lane_id="bridge-duplicate-start",
                project_checkout=str(self.checkout),
                project_coordinator_root=str(self.temp / "state"),
                project_anchor_id=self.anchor,
                project_recovery_root=str(self.temp / "recovery"),
                project_lane_root=str(self.temp / "lanes"),
                project_integration_ref=self.integration_ref,
                lease_id="bridge-duplicate-start-lease",
                _project_runtime_claim=claim,
            )
            return agent_runner.resolve_project_lane_start(
                args,
                agent_name="openbuild_implementation_balanced",
                repo=Path(str(lane["worktree"])),
                allowed_files=["bridge-duplicate-start.txt"],
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(resolve, claim)
                for claim in ("dispatch-one", "dispatch-two")
            ]
            successes: list[dict[str, object]] = []
            failures: list[BaseException] = []
            for future in futures:
                try:
                    binding = future.result()
                    assert binding is not None
                    successes.append(binding)
                except BaseException as exc:
                    failures.append(exc)

        try:
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            self.assertRegex(str(failures[0]), "another dispatch")
            active = self.store.read_state(self.anchor)["state"]["runtime"]["jobs"]
            self.assertEqual(
                [
                    (item["lane_id"], item["status"])
                    for item in active
                ],
                [("bridge-duplicate-start", "running")],
            )
        finally:
            for binding in successes[:1]:
                agent_runner.release_project_lane_runtime(
                    {"project_lane": binding},
                )

    def test_exact_owner_duplicate_start_cannot_release_live_runtime_slot(
        self,
    ) -> None:
        self.runtime.configure_capacity(1)
        lane = self.lanes.create(
            "bridge-exact-duplicate",
            "m6",
            self.temp / "lanes" / "bridge-exact-duplicate",
            [hard("bridge-exact-duplicate.txt")],
        )
        run_dir = self.temp / "exact-duplicate-run"
        runtime_job_id = "run-" + hashlib.sha256(
            _canonical(
                {
                    "anchor_id": self.anchor,
                    "lane_id": "bridge-exact-duplicate",
                    "owner": "bridge-exact-duplicate-lease",
                }
            )
        ).hexdigest()[:20]
        prompt_sha256 = "a" * 64
        prompt_snapshot_id = "b" * 64

        def start_args() -> Namespace:
            return Namespace(
                repo=str(lane["worktree"]),
                prompt_file=None,
                prompt_snapshot_id=prompt_snapshot_id,
                prompt_sha256=prompt_sha256,
                search_fallback_source=None,
                expected_map_sha256=None,
                agent="openbuild_implementation_balanced",
                lease_id="bridge-exact-duplicate-lease",
                allowed_file=["bridge-exact-duplicate.txt"],
                specification_revision="R-032",
                recovery_target_milestone="m6",
                project_lane_id="bridge-exact-duplicate",
                project_checkout=str(self.checkout),
                project_coordinator_root=str(self.temp / "state"),
                project_anchor_id=self.anchor,
                project_recovery_root=str(self.temp / "recovery"),
                project_lane_root=str(self.temp / "lanes"),
                project_integration_ref=self.integration_ref,
                run_dir=str(run_dir),
                task_name="m6-exact-duplicate",
                activation_timeout=300.0,
                codex_bin="codex",
            )

        registry = mock.Mock()
        registry.state.return_value = {"lease": None}
        published = threading.Event()
        continue_original = threading.Event()
        original_thread_id: list[int] = []
        original_errors: list[BaseException] = []

        def publish_run_dir(path: Path) -> None:
            path.mkdir(parents=True, exist_ok=True)
            if original_thread_id and threading.get_ident() == original_thread_id[0]:
                published.set()
                if not continue_original.wait(10.0):
                    raise AssertionError("original start publication pause timed out")

        def run_original() -> None:
            original_thread_id.append(threading.get_ident())
            try:
                agent_runner.start_run(start_args())
            except BaseException as exc:
                original_errors.append(exc)

        contender: dict[str, Any] | None = None
        try:
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=registry,
            ), mock.patch.object(
                agent_runner,
                "read_owner_prompt_snapshot",
                return_value="exact duplicate prompt",
            ), mock.patch.object(
                agent_runner,
                "ensure_private_run_dir",
                side_effect=publish_run_dir,
            ), mock.patch.object(
                agent_runner,
                "validate_subscription_configuration",
                side_effect=agent_runner.RunnerError(
                    "injected failure after run-directory publication"
                ),
            ):
                original_thread = threading.Thread(
                    target=run_original,
                    name="m6-original-start",
                )
                original_thread.start()
                try:
                    self.assertTrue(
                        published.wait(10.0),
                        "original start did not publish its run directory",
                    )

                    with self.assertRaisesRegex(
                        agent_runner.RunnerError,
                        "runtime job is owned by another dispatch",
                    ):
                        agent_runner.start_run(start_args())

                    self.assertEqual(
                        self.runtime.status(runtime_job_id)["status"],
                        "running",
                    )
                    contender = self.runtime.acquire("bridge-exact-contender")
                    self.assertEqual(
                        contender["status"],
                        "waiting-for-capacity",
                    )
                    registry.reserve_normal.assert_not_called()
                finally:
                    continue_original.set()
                    original_thread.join(10.0)
                self.assertFalse(original_thread.is_alive())
                self.assertEqual(len(original_errors), 1)
                self.assertRegex(
                    str(original_errors[0]),
                    "injected failure after run-directory publication",
                )
        finally:
            continue_original.set()
            if contender is not None:
                self.runtime.release(contender["job_id"])

    def test_cancelled_unclaimed_capacity_waiter_cannot_consume_a_slot(
        self,
    ) -> None:
        self.runtime.configure_capacity(1)
        holder = self.lanes.create(
            "bridge-cancel-holder",
            "m6",
            self.temp / "lanes" / "bridge-cancel-holder",
            [hard("bridge-cancel-holder.txt")],
        )
        waiter = self.lanes.create(
            "bridge-cancel-waiter",
            "m6",
            self.temp / "lanes" / "bridge-cancel-waiter",
            [hard("bridge-cancel-waiter.txt")],
        )

        def args(lane_id: str) -> Namespace:
            return Namespace(
                project_lane_id=lane_id,
                project_checkout=str(self.checkout),
                project_coordinator_root=str(self.temp / "state"),
                project_anchor_id=self.anchor,
                project_recovery_root=str(self.temp / "recovery"),
                project_lane_root=str(self.temp / "lanes"),
                project_integration_ref=self.integration_ref,
                lease_id=f"{lane_id}-lease",
                _project_runtime_claim=f"{lane_id}-dispatch",
            )

        holder_binding = agent_runner.resolve_project_lane_start(
            args("bridge-cancel-holder"),
            agent_name="openbuild_implementation_balanced",
            repo=Path(str(holder["worktree"])),
            allowed_files=["bridge-cancel-holder.txt"],
        )
        assert holder_binding is not None
        with self.assertRaisesRegex(
            agent_runner.RunnerError,
            "runtime capacity is not available",
        ):
            agent_runner.resolve_project_lane_start(
                args("bridge-cancel-waiter"),
                agent_name="openbuild_implementation_balanced",
                repo=Path(str(waiter["worktree"])),
                allowed_files=["bridge-cancel-waiter.txt"],
            )

        waiting = self.store.read_state(self.anchor)["state"]["runtime"]["jobs"]
        self.assertEqual(
            [
                (item["lane_id"], item["status"], item["owner_digest"])
                for item in waiting
            ],
            [
                (
                    "bridge-cancel-holder",
                    "running",
                    holder_binding["lane_binding"]["runtime"]["owner_digest"],
                ),
                ("bridge-cancel-waiter", "waiting-for-capacity", None),
            ],
        )
        cancelled = self.lanes.cancel_or_crash(
            "bridge-cancel-waiter",
            "cancelled",
        )
        self.assertEqual(cancelled["state"], "cancelled")
        after_cancel = self.store.read_state(self.anchor)["state"]["runtime"]
        self.assertEqual(
            [
                (item["lane_id"], item["status"])
                for item in after_cancel["jobs"]
            ],
            [("bridge-cancel-holder", "running")],
        )
        cancelled_job = next(
            item
            for item in after_cancel["completed"]
            if item["lane_id"] == "bridge-cancel-waiter"
        )
        self.assertEqual(cancelled_job["status"], "complete")

        agent_runner.release_project_lane_runtime(
            {"project_lane": holder_binding},
        )
        replacement = self.runtime.acquire("bridge-after-waiter-cancel")
        self.assertEqual(replacement["status"], "running")
        self.runtime.release("bridge-after-waiter-cancel")

    def test_recovery_authorization_defers_runtime_claim_until_start(
        self,
    ) -> None:
        (self.temp / "recovery").mkdir(exist_ok=True)
        checkpoint_digest = "a" * 64
        checkpoint = {
            "disposition": "recovery-eligible",
            "checkpoint_digest": checkpoint_digest,
        }
        coordinator = mock.Mock()
        coordinator.lane_projection.return_value = {
            "state": "recovery-ready",
            "writer": None,
            "recovery_checkpoint_digest": checkpoint_digest,
        }
        coordinator.runner_writer_binding.return_value = {
            "schema": "project-lane-runner-v1",
            "allowed_paths": ["recovery-owned.txt"],
        }
        registry = mock.Mock()
        registry.checkpoint_allowed_paths.return_value = [
            "recovery-owned.txt",
        ]
        args = Namespace(
            project_lane_id="recovery-runtime-lane",
            project_checkout=str(self.checkout),
            project_coordinator_root=str(self.temp / "state"),
            project_anchor_id=self.anchor,
            project_recovery_root=str(self.temp / "recovery"),
            project_lane_root=str(self.temp / "lanes"),
            project_integration_ref=self.integration_ref,
            lease_id="recovery-runtime-lease",
            _project_runtime_claim="recovery-authorization",
        )
        with mock.patch.object(
            agent_runner,
            "_project_lane_coordinator",
            return_value=coordinator,
        ), mock.patch.object(
            agent_runner,
            "RecoveryRegistry",
            return_value=registry,
        ):
            authorization = (
                agent_runner.resolve_project_lane_recovery_authorization(
                    args,
                    repo=self.checkout,
                    checkpoint=checkpoint,
                )
            )

        assert authorization is not None
        self.assertNotIn("runtime", authorization["lane_binding"])
        coordinator.runner_writer_binding.assert_called_once_with(
            "recovery-runtime-lane",
            self.checkout,
            ["recovery-owned.txt"],
            require_ready=False,
            lease_kind="recovery-target",
        )

    def test_claimed_unactivated_runtime_blocks_ordinary_lane_cancellation(
        self,
    ) -> None:
        self.runtime.configure_capacity(1)
        lane = self.lanes.create(
            "bridge-claimed-cancel",
            "m6",
            self.temp / "lanes" / "bridge-claimed-cancel",
            [hard("bridge-claimed-cancel.txt")],
        )
        args = Namespace(
            project_lane_id="bridge-claimed-cancel",
            project_checkout=str(self.checkout),
            project_coordinator_root=str(self.temp / "state"),
            project_anchor_id=self.anchor,
            project_recovery_root=str(self.temp / "recovery"),
            project_lane_root=str(self.temp / "lanes"),
            project_integration_ref=self.integration_ref,
            lease_id="bridge-claimed-cancel-lease",
            _project_runtime_claim="bridge-claimed-cancel-dispatch",
        )
        binding = agent_runner.resolve_project_lane_start(
            args,
            agent_name="openbuild_implementation_balanced",
            repo=Path(str(lane["worktree"])),
            allowed_files=["bridge-claimed-cancel.txt"],
        )
        assert binding is not None
        try:
            with self.assertRaisesRegex(
                agent_runner.ProjectLaneError,
                "active claimed runtime job",
            ):
                self.lanes.cancel_or_crash(
                    "bridge-claimed-cancel",
                    "cancelled",
                )
            state = self.store.read_state(self.anchor)["state"]
            current_lane = next(
                item
                for item in state["lanes"]
                if item["lane_id"] == "bridge-claimed-cancel"
            )
            self.assertEqual(current_lane["state"], "ready")
            self.assertEqual(
                [
                    (item["lane_id"], item["status"])
                    for item in state["runtime"]["jobs"]
                ],
                [("bridge-claimed-cancel", "running")],
            )
        finally:
            agent_runner.release_project_lane_runtime(
                {"project_lane": binding},
            )

    def test_status_trace_covers_overlap_integration_stale_quarantine_and_complete(
        self,
    ) -> None:
        self.runtime.configure_capacity(2)
        self.runtime.acquire("runtime-running", port=9201)
        self.runtime.acquire("runtime-complete", port=9202)
        self.runtime.release("runtime-complete")

        self.lanes.create(
            "status-holder",
            "m6",
            self.temp / "lanes" / "status-holder",
            [hard("status-shared.txt")],
        )
        self.lanes.create(
            "status-waiter",
            "m6",
            self.temp / "lanes" / "status-waiter",
            [hard("status-shared.txt")],
        )

        integration_wait = self._terminal_lane(
            "status-integration",
            "status-integration.txt",
        )
        integration_registry = self._terminal_registry(integration_wait)

        def one_registry(worktree: Path, *, state_root: Path):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = integration_registry
            return value

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=one_registry,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=one_registry,
        ):
            self.integrator.enqueue(
                "status-integration",
                validation_argv=[sys.executable, "-c", "raise SystemExit(23)"],
            )
            waiting_projection = self.runtime.public_status(
                "status-integration",
            )
            self.assertEqual(
                (
                    waiting_projection["state"],
                    waiting_projection["position"],
                ),
                ("waiting-for-integration", 1),
            )
            blocked_result = self.integrator.integrate_next()
        self.assertEqual(blocked_result["diagnostic"]["code"], "validation-failed")

        self.lanes.create(
            "status-stale",
            "m6",
            self.temp / "lanes" / "status-stale",
            [
                hard("status-stale.txt"),
                {
                    "kind": "file",
                    "path": "status-producer.txt",
                    "mode": "soft",
                },
            ],
        )
        producer = self._terminal_lane(
            "status-producer",
            "status-producer.txt",
        )
        producer_registry = self._terminal_registry(producer)

        def producer_registry_factory(worktree: Path, *, state_root: Path):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = producer_registry
            return value

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=producer_registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=producer_registry_factory,
        ):
            self.integrator.enqueue(
                "status-producer",
                validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
                dependency_unblocking=True,
            )
            self.assertEqual(self.integrator.integrate_next()["status"], "released")

        quarantine = self.lanes.create(
            "status-quarantine",
            "m6",
            self.temp / "lanes" / "status-quarantine",
            [hard("status-quarantine.txt")],
        )
        state = self.store.read_state(self.anchor)["state"]
        lanes = [dict(item) for item in state["lanes"]]
        running_lane = next(
            item for item in lanes if item["lane_id"] == "status-quarantine"
        )
        running_lane["state"] = "running"
        running_lane["writer"] = {
            "lease_id": "status-quarantine-lease",
            "run_id": "status-quarantine-run",
            "allowed_set_digest": "e" * 64,
            "lease_kind": "normal-contained",
        }
        running_lane["dependency_binding"] = {
            **running_lane["dependency_binding"],
            "allowed_set_digest": "e" * 64,
        }
        live_registry = mock.Mock()
        live_registry.state.return_value = {
            "lease": {
                **running_lane["writer"],
                "state": "running",
                "recovery_capable": True,
            },
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        with mock.patch(
            "project_state.RecoveryRegistry",
            return_value=live_registry,
        ):
            self.store.replace_lane_state(
                self.anchor,
                expected_generation=int(state["generation"]),
                lanes=lanes,
                scopes=state["scopes"],
            )
        with mock.patch(
            "project_lanes.RecoveryRegistry",
            return_value=live_registry,
        ):
            quarantined = self.lanes.cancel_or_crash(
                "status-quarantine",
                "crashed",
            )
        self.assertEqual(quarantined["state"], "quarantined")

        projections = {
            lane_id: self.runtime.public_status(lane_id)
            for lane_id in (
                "runtime-running",
                "runtime-complete",
                "status-waiter",
                "status-integration",
                "status-stale",
                "status-quarantine",
            )
        }
        self.assertEqual(
            {key: value["state"] for key, value in projections.items()},
            {
                "runtime-running": "running",
                "runtime-complete": "complete",
                "status-waiter": "stale",
                "status-integration": "blocked",
                "status-stale": "stale",
                "status-quarantine": "blocked",
            },
        )
        rendered = json.dumps(
            [waiting_projection, *projections.values()],
            sort_keys=True,
        )
        for private_value in (
            str(self.temp),
            "9201",
            "9202",
            "status-quarantine-lease",
            "status-quarantine-run",
        ):
            self.assertNotIn(private_value, rendered)

    def test_merge_conflict_projects_blocked_without_private_diagnostic(self) -> None:
        first = self._terminal_lane(
            "conflict-first",
            "conflict-first.txt",
            write_path="base.txt",
        )
        second = self._terminal_lane(
            "conflict-second",
            "conflict-second.txt",
            write_path="base.txt",
        )
        registries = {
            str(first["worktree"]): self._terminal_registry(first),
            str(second["worktree"]): self._terminal_registry(second),
        }

        def registry_factory(worktree: Path, *, state_root: Path):
            del state_root
            value = mock.Mock()
            value.state.return_value = registries[str(worktree)]
            return value

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=registry_factory,
        ):
            self.integrator.enqueue(
                "conflict-first",
                validation_argv=["git", "diff", "--check"],
            )
            self.assertEqual(self.integrator.integrate_next()["status"], "released")
            self.integrator.enqueue(
                "conflict-second",
                validation_argv=["git", "diff", "--check"],
            )
            conflict = self.integrator.integrate_next()
        self.assertEqual(conflict["diagnostic"]["code"], "merge-conflict")
        projection = self.runtime.public_status("conflict-second")
        self.assertEqual(
            (
                projection["state"],
                projection["reason_code"],
                projection["next_action"],
            ),
            (
                "blocked",
                "integration-blocked",
                "inspect-safe-diagnostic",
            ),
        )
        self.assertNotIn(
            str(self.temp),
            json.dumps(projection, sort_keys=True),
        )

    def test_legacy_ordinary_intent_migrates_without_identity_rewrite(self) -> None:
        lane = self._terminal_lane("legacy-intent", "legacy-intent.txt")
        registry = self._terminal_registry(lane)

        def registry_factory(worktree: Path, *, state_root: Path):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = registry
            return value

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=registry_factory,
        ):
            self.integrator.enqueue(
                "legacy-intent",
                validation_argv=["git", "diff", "--check"],
            )
        state_path = self.temp / "state" / "states" / f"{self.anchor}.json"
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        intent = legacy["integration_queue"][0]
        intent.pop("queue_class")
        stable = {
            key: intent[key]
            for key in (
                "schema",
                "enqueue_generation",
                "result",
                "admitted_tip",
            )
        }
        intent["intent_id"] = hashlib.sha256(_canonical(stable)).hexdigest()
        legacy.pop("digest")
        legacy["digest"] = _digest(legacy)
        state_path.write_text(
            json.dumps(legacy, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        migrated = self.store._read_state_strict(self.anchor)
        self.assertEqual(
            migrated["integration_queue"][0]["queue_class"],
            "ordinary",
        )
        legacy_id = migrated["integration_queue"][0]["intent_id"]
        self.runtime.configure_capacity(2)
        reloaded = self.store._read_state_strict(self.anchor)
        self.assertEqual(
            (
                reloaded["integration_queue"][0]["queue_class"],
                reloaded["integration_queue"][0]["intent_id"],
            ),
            ("ordinary", legacy_id),
        )

    def test_public_projection_is_authoritative_and_private(self) -> None:
        self.runtime.configure_capacity(1)
        self.runtime.acquire("primary-run", port=9012)
        self.runtime.acquire("capacity-wait", port=9012)
        running = self.runtime.public_status("primary-run")
        waiting = self.runtime.public_status("capacity-wait")
        for projection in (running, waiting):
            self.assertEqual(
                set(projection),
                {
                    "state", "task_id", "lane_id", "milestone_id", "reason_code",
                    "queue_dependency", "position", "last_transition", "next_action",
                },
            )
            self.assertIn(
                projection["state"],
                {"running", "waiting-for-scope", "waiting-for-integration", "stale", "blocked", "complete"},
            )
            self.assertNotIn("9012", json.dumps(projection, sort_keys=True))
            self.assertNotIn(str(self.temp), json.dumps(projection, sort_keys=True))
        self.assertEqual(waiting["queue_dependency"], "runtime-capacity")
        self.assertEqual(waiting["position"], 1)
        self.runtime.release("primary-run")
        self.runtime.release("capacity-wait")
        self.assertEqual(self.runtime.public_status("capacity-wait")["state"], "complete")
        trace = self.runtime.public_trace()
        self.assertEqual(
            {item["state"] for item in trace},
            {"complete"},
        )
        rendered = json.dumps(trace, sort_keys=True)
        self.assertNotIn("9012", rendered)
        self.assertNotIn(str(self.temp), rendered)

    def test_deterministic_ten_lane_stress_has_no_lost_slots_or_updates(self) -> None:
        self.runtime.configure_capacity(2)
        scopes = ProjectScopeManager(self.store, self.anchor, checkout=self.checkout)
        scope_sets = [
            [hard(f"file-{number}.txt"), hard(f"resource-{number % 3}", kind="resource")]
            for number in range(10)
        ]
        for number, requests in enumerate(scope_sets):
            self.assertEqual(scopes.normalize(requests), requests)
            self.lanes.create(
                f"lane-{number}",
                "m6",
                self.temp / "lanes" / f"lane-{number}",
                requests,
            )
        pending = set(range(10))
        integration_order: list[str] = []
        runtime_tickets: list[int] = []
        snapshots: list[dict[str, object]] = []
        while pending:
            state = self.store.read_state(self.anchor)["state"]
            for lane in state["lanes"]:
                number = int(lane["lane_id"].removeprefix("lane-"))
                if number not in pending:
                    continue
                if lane.get("integration_stale") is not None:
                    self.lanes.refresh_integration_stale(
                        lane["lane_id"],
                        allowed_set_digest=f"{number + 1:064x}",
                        specification_revision="R-032",
                    )
                reservation = scopes.reserve_planned(
                    lane["lane_id"],
                    scope_sets[number],
                )
                refreshed_lane = next(
                    item
                    for item in self.store.read_state(
                        self.anchor,
                    )["state"]["lanes"]
                    if item["lane_id"] == lane["lane_id"]
                )
                if (
                    reservation["status"] == "active"
                    and refreshed_lane["state"] == "creating"
                ):
                    self.lanes.create(
                        lane["lane_id"],
                        "m6",
                        self.temp / "lanes" / lane["lane_id"],
                        scope_sets[number],
                    )
            ready = sorted(
                (
                    item
                    for item in self.store.read_state(self.anchor)["state"]["lanes"]
                    if int(item["lane_id"].removeprefix("lane-")) in pending
                    and item["state"] == "ready"
                ),
                key=lambda item: int(item["lane_id"].removeprefix("lane-")),
            )[:2]
            if not ready:
                current = self.store.read_state(self.anchor)["state"]
                self.fail(
                    "scope/runtime lifecycle made no progress: "
                    + json.dumps(
                        {
                            "lanes": {
                                item["lane_id"]: item["state"]
                                for item in current["lanes"]
                                if int(
                                    item["lane_id"].removeprefix("lane-"),
                                )
                                in pending
                            },
                            "scopes": [
                                {
                                    "owner": item.get("owner"),
                                    "path": item.get("path"),
                                    "status": item.get("status"),
                                }
                                for item in current["scopes"]
                                if item.get("owner")
                                in {f"lane-{number}" for number in pending}
                                and item.get("mode") == "hard"
                            ],
                        },
                        sort_keys=True,
                    )
                )

            bindings: dict[str, dict[str, object]] = {}
            terminal_lanes: dict[str, dict[str, object]] = {}
            for lane in ready:
                lane_id = str(lane["lane_id"])
                number = int(lane_id.removeprefix("lane-"))
                args = Namespace(
                    project_lane_id=lane_id,
                    project_checkout=str(self.checkout),
                    project_coordinator_root=str(self.temp / "state"),
                    project_anchor_id=self.anchor,
                    project_recovery_root=str(self.temp / "recovery"),
                    project_lane_root=str(self.temp / "lanes"),
                    project_integration_ref=self.integration_ref,
                    lease_id=f"{lane_id}-lease",
                )
                binding = agent_runner.resolve_project_lane_start(
                    args,
                    agent_name="openbuild_implementation_balanced",
                    repo=Path(str(lane["worktree"])),
                    allowed_files=[f"file-{number}.txt"],
                )
                assert binding is not None
                bindings[lane_id] = binding
                runtime_tickets.append(
                    int(binding["lane_binding"]["runtime"]["ticket"])
                )
            runtime_state = self.store.read_state(self.anchor)["state"]["runtime"]
            snapshots.append(runtime_state)
            self.assertEqual(
                len(
                    [
                        item
                        for item in runtime_state["jobs"]
                        if item["status"] == "running"
                    ]
                ),
                len(ready),
            )

            for lane in ready:
                lane_id = str(lane["lane_id"])
                number = int(lane_id.removeprefix("lane-"))
                terminal_lanes[lane_id] = self._terminalize_existing_lane(
                    lane_id,
                    f"file-{number}.txt",
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(bindings),
            ) as pool:
                released = list(
                    pool.map(
                        lambda binding: agent_runner.release_project_lane_runtime(
                            {"project_lane": binding},
                        ),
                        bindings.values(),
                    )
                )
            self.assertTrue(
                all(
                    item is not None and item["status"] == "complete"
                    for item in released
                )
            )

            registries = {
                str(lane["worktree"]): self._terminal_registry(lane)
                for lane in terminal_lanes.values()
            }

            def registry_factory(worktree: Path, *, state_root: Path):
                del state_root
                value = mock.Mock()
                value.state.return_value = registries[str(worktree)]
                return value

            with mock.patch(
                "project_state.RecoveryRegistry",
                side_effect=registry_factory,
            ), mock.patch(
                "project_integrator.RecoveryRegistry",
                side_effect=registry_factory,
            ):
                for lane in ready:
                    lane_id = str(lane["lane_id"])
                    intent = self.integrator.enqueue(
                        lane_id,
                        validation_argv=[
                            "git",
                            "diff",
                            "--check",
                            "HEAD^",
                            "HEAD",
                        ],
                    )
                    current_lane = next(
                        item
                        for item in self.store.read_state(
                            self.anchor,
                        )["state"]["lanes"]
                        if item["lane_id"] == lane_id
                    )
                    self.assertEqual(
                        intent["result"]["dependency_stale"],
                        current_lane.get("integration_stale"),
                    )
                    result = self.integrator.integrate_next()
                    assert result is not None
                    self.assertEqual(result["status"], "released")
                    integration_order.append(result["result"]["lane_id"])
                    pending.remove(int(lane_id.removeprefix("lane-")))
                    current_lanes = self.store.read_state(
                        self.anchor,
                    )["state"]["lanes"]
                    for candidate in current_lanes:
                        candidate_number = int(
                            candidate["lane_id"].removeprefix("lane-"),
                        )
                        if (
                            candidate_number in pending
                            and candidate.get("integration_stale") is not None
                            and candidate.get("writer") is None
                            and candidate.get("state")
                            in {"waiting-for-scope", "creating", "ready"}
                        ):
                            self.lanes.refresh_integration_stale(
                                candidate["lane_id"],
                                allowed_set_digest=f"{candidate_number + 1:064x}",
                                specification_revision="R-032",
                            )

        final = self.store.read_state(self.anchor)["state"]["runtime"]
        self.assertEqual(runtime_tickets, list(range(1, 11)))
        self.assertEqual(
            integration_order,
            [f"lane-{number}" for number in range(10)],
        )
        self.assertEqual([item["ticket"] for item in final["completed"]], list(range(1, 11)))
        self.assertTrue(all(item["status"] == "complete" for item in final["completed"]))
        self.assertEqual(len({item["namespace"] for item in final["completed"]}), 10)
        self.assertTrue(all(len([job for job in snapshot["jobs"] if job["status"] == "running"]) <= 2 for snapshot in snapshots))

    def test_runtime_validation_rejects_ticket_and_namespace_tampering(self) -> None:
        self.runtime.configure_capacity(2)
        self.runtime.acquire("valid-a", port=9123)
        self.runtime.acquire("valid-b")
        state_path = self.temp / "state" / "states" / f"{self.anchor}.json"
        original = json.loads(state_path.read_text(encoding="utf-8"))
        mutations = {
            "duplicate-ticket": lambda value: value["runtime"]["jobs"][1].__setitem__(
                "ticket",
                value["runtime"]["jobs"][0]["ticket"],
            ),
            "namespace": lambda value: value["runtime"]["jobs"][0].__setitem__(
                "namespace",
                "ob-forged",
            ),
            "lane-alias": lambda value: value["runtime"]["jobs"][1].__setitem__(
                "lane_id",
                value["runtime"]["jobs"][0]["lane_id"],
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                tampered = json.loads(json.dumps(original))
                mutate(tampered)
                tampered.pop("digest")
                tampered["digest"] = _digest(tampered)
                state_path.write_text(
                    json.dumps(tampered, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                with self.assertRaises(ProjectStateError):
                    self.store._read_state_strict(self.anchor)
        state_path.write_text(
            json.dumps(original, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    unittest.main()
