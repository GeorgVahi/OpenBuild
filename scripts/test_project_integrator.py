"""Focused M5 integration-owner contract tests.

The fixture uses local Git repositories only.  It intentionally exercises the
same project-state, lane and scope owners as the production integration queue.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
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

from project_integrator import ProjectIntegrator, ProjectIntegratorError  # type: ignore[import-not-found]
from project_lanes import (  # type: ignore[import-not-found]
    ProjectLaneCoordinator,
    ProjectLaneError,
)
from project_scopes import ProjectScopeManager  # type: ignore[import-not-found]
from project_state import (  # type: ignore[import-not-found]
    ProjectStateError,
    ProjectStateStore,
    _VERSION_SURFACES,
    _digest,
    _process_creation_identity,
)
from recovery_state import RecoveryRegistry  # type: ignore[import-not-found]


def hard(path: str) -> dict[str, str]:
    return {"kind": "file", "path": path, "mode": "hard"}


class ProjectIntegratorM5Tests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path.cwd() / ".git" / "t"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix="m5-", dir=test_root))
        self.checkout = self.temp / "checkout"
        self.checkout.mkdir()
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "OpenBuild test")
        (self.checkout / "base.txt").write_text("base\n", encoding="utf-8")
        for relative in ("lane-a.txt", "lane-b.txt"):
            (self.checkout / relative).write_text(
                f"{relative} base\n",
                encoding="utf-8",
            )
        for relative in _VERSION_SURFACES:
            surface = self.checkout.joinpath(*relative.split("/"))
            surface.parent.mkdir(parents=True, exist_ok=True)
            surface.write_text(
                "2.4.0-alpha.6\n",
                encoding="utf-8",
            )
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.integration_ref = "refs/openbuild/integration"
        self.git("update-ref", self.integration_ref, "HEAD")
        self.coordinator_root = self.temp / "c"
        self.recovery_root = self.temp / "r"
        self.lane_root = self.temp / "l"
        self.lane_root.mkdir()
        self.integration_checkout = self.temp / "i"
        self.store = ProjectStateStore(
            self.checkout,
            coordinator_root=self.coordinator_root,
        )
        capability = self.store.issue_bootstrap_capability("plan", "attempt")[
            "bootstrap_capability"
        ]
        self.anchor = self.store.create_anchor(capability, "plan", "attempt")[
            "anchor_id"
        ]
        self.store.bootstrap(self.anchor, "clean")
        self.lanes = ProjectLaneCoordinator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery_root,
            lane_root=self.lane_root,
            integration_ref=self.integration_ref,
        )
        self.integrator = ProjectIntegrator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery_root,
            integration_checkout=self.integration_checkout,
            integration_ref=self.integration_ref,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd or self.checkout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and completed.returncode:
            self.fail(completed.stderr.decode("utf-8", "replace"))
        return completed.stdout.decode("ascii", "strict").strip()

    def terminal_lane(
        self,
        lane_id: str,
        path: str,
        content: str,
        *,
        write_path: str | None = None,
        extra_scopes: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        lane = self.lanes.create(
            lane_id,
            "m5",
            self.lane_root / lane_id,
            [hard(path), *(extra_scopes or [])],
        )
        worktree = Path(str(lane["worktree"]))
        target = write_path or path
        (worktree / target).write_text(content, encoding="utf-8", newline="\n")
        self.git("add", target, cwd=worktree)
        self.git("commit", "-m", lane_id, cwd=worktree)
        state = self.store.read_state(self.anchor)["state"]
        lanes = [dict(item) for item in state["lanes"]]
        terminal = next(item for item in lanes if item["lane_id"] == lane_id)
        terminal["state"] = "running"
        terminal["writer"] = {
            "lease_id": f"{lane_id}-lease",
            "run_id": f"{lane_id}-run",
            "allowed_set_digest": "a" * 64,
            "lease_kind": "normal-contained",
        }
        terminal["dependency_binding"] = {
            **terminal["dependency_binding"],
            "allowed_set_digest": terminal["writer"]["allowed_set_digest"],
        }
        active_registry = mock.Mock()
        active_registry.state.return_value = {
            "lease": {
                **terminal["writer"],
                "state": "running",
            },
            "outbox": None,
            "quarantine": None,
            "history": [],
        }
        with mock.patch("project_state.RecoveryRegistry", return_value=active_registry):
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
    def terminal_registry(lane: dict[str, object]) -> dict[str, object]:
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

    def start_real_lane(
        self,
        lane_id: str,
        path: str,
        *,
        ordinal: int,
        extra_scopes: list[dict[str, str]] | None = None,
    ) -> tuple[dict[str, object], RecoveryRegistry]:
        lane = self.lanes.create(
            lane_id,
            "m5",
            self.lane_root / lane_id,
            [hard(path), *(extra_scopes or [])],
        )
        worktree = Path(str(lane["worktree"]))
        registry = RecoveryRegistry(
            worktree,
            state_root=self.recovery_root,
        )
        lease_id = f"{lane_id}-lease"
        run_id = f"{lane_id}-run"
        guardian_id = f"{lane_id}-guardian"
        provider_plan_id = f"{lane_id}-provider"
        ipc_plan_id = f"{lane_id}-ipc"
        launch_token = hashlib.sha256(
            f"{lane_id}:launch".encode("utf-8")
        ).hexdigest()
        preflight = registry.prepare_source_checkpoint(
            source_id=f"{lane_id}-source",
            source_lease_id=lease_id,
            source_milestone="M5-source",
            target_milestone="M5-recovery",
            allowed_paths=[path],
            specification_revision="R-032",
        )
        registry.reserve_normal(
            lease_id,
            allowed_set_digest=preflight["allowed_set_digest"],
            recovery_capable=True,
            source_state_id=preflight["source_state_id"],
            run_id=run_id,
            containment_plan={
                "guardian_id": guardian_id,
                "provider_plan_id": provider_plan_id,
                "ipc_plan_id": ipc_plan_id,
                "contained_launch_token": launch_token,
                "fallback_token": hashlib.sha256(
                    f"{lane_id}:fallback".encode("utf-8")
                ).hexdigest(),
                "recovery_target": False,
            },
        )
        registry.bind_reserved_source_snapshot(lease_id, preflight)
        registry.claim_contained_launch(lease_id, launch_token)
        worker_pid = 1000 + ordinal
        worker_identity = f"{lane_id}-worker"
        registry.bind_process_unactivated(
            lease_id,
            allowed_set_digest=preflight["allowed_set_digest"],
            provider_receipt={
                "guardian_id": guardian_id,
                "guardian_pid": 2000 + ordinal,
                "guardian_identity": f"{lane_id}-guardian-process",
                "provider": "windows-job",
                "provider_plan_id": provider_plan_id,
                "ipc_plan_id": ipc_plan_id,
                "policy": "kill-on-close-no-breakaway",
                "active_processes": 1,
                "anti_migration": None,
                "precommit": {
                    "guardian_id": guardian_id,
                    "guardian_pid": 2000 + ordinal,
                    "guardian_identity": f"{lane_id}-guardian-process",
                    "worker_pid": worker_pid,
                    "worker_identity": worker_identity,
                    "provider": "windows-job",
                    "provider_plan_id": provider_plan_id,
                    "ipc_plan_id": ipc_plan_id,
                    "provider_populated": True,
                    "membership_verified": True,
                    "precommit_nonce": f"{lane_id}-precommit",
                    "attested_at": "2026-07-24T00:00:01Z",
                },
            },
            process_receipt={
                "pid": worker_pid,
                "identity": worker_identity,
                "process_group_id": worker_pid,
                "started_at": "2026-07-24T00:00:00Z",
            },
        )
        registry.commit_activation(
            lease_id,
            preflight["allowed_set_digest"],
        )
        attached = self.lanes.attach_contained_writer(
            lane_id,
            lease_id=lease_id,
            run_id=run_id,
            allowed_set_digest=preflight["allowed_set_digest"],
        )
        return attached, registry

    def terminalize_real_lane(
        self,
        lane: dict[str, object],
        registry: RecoveryRegistry,
        *,
        success: bool,
    ) -> dict[str, object]:
        writer = lane["writer"]
        assert isinstance(writer, dict)
        lane_id = str(lane["lane_id"])
        active_lease = registry.state()["lease"]
        assert isinstance(active_lease, dict)
        process_receipt = active_lease["process_receipt"]
        provider_receipt = active_lease["provider_receipt"]
        registry.record_terminal_evidence(
            str(writer["lease_id"]),
            {
                "success": success,
                "binding_digest": hashlib.sha256(
                    f"{lane_id}:terminal".encode("utf-8")
                ).hexdigest(),
                "terminal_event": (
                    "turn.completed" if success else "turn.failed"
                ),
            },
            str(writer["allowed_set_digest"]),
        )
        registry.prove_contained_tree_empty(
            str(writer["lease_id"]),
            {
                "populated": False,
                "identity_verified": True,
                "guardian_id": provider_receipt["guardian_id"],
                "provider": "windows-job",
                "worker_pid": process_receipt["pid"],
                "worker_identity": process_receipt["identity"],
                "proved_at": "2026-07-24T00:00:02Z",
            },
            str(writer["allowed_set_digest"]),
        )
        if success:
            registry.commit_handoff(
                str(writer["lease_id"]),
                {
                    "event_id": hashlib.sha256(
                        f"{lane_id}:handoff".encode("utf-8")
                    ).hexdigest(),
                    "payload": {
                        "lease_id": writer["lease_id"],
                        "run_id": writer["run_id"],
                        "receipt_digest": "a" * 64,
                        "checkpoint_digest": "b" * 64,
                        "allowed_set_digest": writer[
                            "allowed_set_digest"
                        ],
                        "root_verification_digest": "d" * 64,
                    },
                },
                str(writer["allowed_set_digest"]),
            )
            registry.materialize_handoff(
                str(writer["lease_id"]),
                registry.directory / "handoff-events.jsonl",
            )
        registry.acknowledge_guardian_close(
            str(writer["lease_id"]),
            {
                "closed": True,
                "guardian_id": provider_receipt["guardian_id"],
                "closed_at": "2026-07-24T00:00:03Z",
            },
        )
        registry.release_contained_terminal(str(writer["lease_id"]))
        if success:
            return self.lanes.record_successful_terminal(lane_id)
        return self.lanes.complete_safe_stop_rebind(
            lane_id,
            intent_id=str(lane["safe_stop"]["intent_id"]),
            preserved_changes=False,
        )

    def test_serialized_integration_accepts_then_releases_once(self) -> None:
        first = self.terminal_lane("first", "first.txt", "first\n")
        second = self.terminal_lane("second", "second.txt", "second\n")
        registries = {
            str(first["worktree"]): self.terminal_registry(first),
            str(second["worktree"]): self.terminal_registry(second),
        }

        def registry_factory(worktree: Path, *, state_root: Path):
            del state_root
            registry = mock.Mock()
            registry.state.return_value = registries[str(worktree)]
            return registry

        validation = ["git", "diff", "--check", "HEAD^", "HEAD"]
        with mock.patch("project_state.RecoveryRegistry", side_effect=registry_factory), mock.patch(
            "project_integrator.RecoveryRegistry", side_effect=registry_factory
        ):
            queued = self.integrator.enqueue("first", validation_argv=validation)
            self.assertEqual(queued["status"], "queued")
            first_result = self.integrator.integrate_next()
            self.assertEqual(first_result["status"], "released")
            self.assertEqual(first_result["ticket"], 1)
            second_result = self.integrator.enqueue("second", validation_argv=validation)
            self.assertEqual(second_result["status"], "queued")
            second_result = self.integrator.integrate_next()
            self.assertEqual(second_result["status"], "released")
            self.assertEqual(second_result["ticket"], 2)
            replay = self.integrator.integrate_next()
        self.assertIsNone(replay)
        state = self.store.read_state(self.anchor)["state"]
        self.assertEqual(
            self.git("rev-parse", self.integration_ref),
            second_result["accepted_commit"],
        )
        self.assertTrue(
            all(
                item["status"] == "released"
                for item in state["scopes"]
                if item.get("owner") in {"first", "second"}
                and item.get("mode") == "hard"
            )
        )
        state_path = (
            self.coordinator_root / "states" / f"{self.anchor}.json"
        )
        tampered = json.loads(state_path.read_text(encoding="utf-8"))
        tampered["integration_queue"][1]["ticket"] = tampered[
            "integration_queue"
        ][0]["ticket"]
        tampered.pop("digest")
        tampered["digest"] = _digest(tampered)
        state_path.write_text(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        with self.assertRaisesRegex(
            ProjectStateError,
            "tickets are not unique",
        ):
            self.store._read_state_strict(self.anchor)

    def test_two_real_lanes_write_together_and_one_integrator_holds_the_queue(
        self,
    ) -> None:
        lane_a, registry_a = self.start_real_lane(
            "real-a",
            "lane-a.txt",
            ordinal=1,
        )
        lane_b, registry_b = self.start_real_lane(
            "real-b",
            "lane-b.txt",
            ordinal=2,
        )
        live = self.store.read_state(self.anchor)["state"]
        self.assertEqual(
            {
                item["lane_id"]: item["state"]
                for item in live["lanes"]
            },
            {"real-a": "running", "real-b": "running"},
        )
        self.assertEqual(
            (
                registry_a.state()["lease"]["state"],
                registry_b.state()["lease"]["state"],
            ),
            ("running", "running"),
        )

        barrier = threading.Barrier(2)

        def commit_lane(
            lane: dict[str, object],
            path: str,
            content: str,
        ) -> str:
            worktree = Path(str(lane["worktree"]))
            barrier.wait(timeout=10)
            (worktree / path).write_text(
                content,
                encoding="utf-8",
                newline="\n",
            )
            self.git("add", path, cwd=worktree)
            self.git("commit", "-m", str(lane["lane_id"]), cwd=worktree)
            return self.git("rev-parse", "HEAD", cwd=worktree)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            commits = [
                pool.submit(
                    commit_lane,
                    lane_a,
                    "lane-a.txt",
                    "lane a result\n",
                ),
                pool.submit(
                    commit_lane,
                    lane_b,
                    "lane-b.txt",
                    "lane b result\n",
                ),
            ]
            self.assertEqual(len({future.result() for future in commits}), 2)

        lane_a = self.terminalize_real_lane(
            lane_a,
            registry_a,
            success=True,
        )
        lane_b = self.terminalize_real_lane(
            lane_b,
            registry_b,
            success=True,
        )
        self.integrator.enqueue(
            "real-a",
            validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
        )
        contender = ProjectIntegrator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery_root,
            integration_checkout=self.integration_checkout,
            integration_ref=self.integration_ref,
        )
        entered = threading.Event()
        resume = threading.Event()
        validate = self.integrator._validate_candidate

        def pause_validation(
            candidate: str,
            argv: list[str],
        ) -> bool:
            entered.set()
            if not resume.wait(timeout=10):
                raise AssertionError("integration contender did not run")
            return validate(candidate, argv)

        with mock.patch.object(
            self.integrator,
            "_validate_candidate",
            side_effect=pause_validation,
        ), concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first_future = pool.submit(self.integrator.integrate_next)
            self.assertTrue(entered.wait(timeout=10))
            with self.assertRaisesRegex(
                ProjectIntegratorError,
                "lease is held by a live owner",
            ):
                contender.integrate_next()
            resume.set()
            first = first_future.result(timeout=30)
        self.assertEqual(first["status"], "released")

        self.integrator.enqueue(
            "real-b",
            validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
        )
        second = contender.integrate_next()
        self.assertEqual(
            (first["ticket"], second["ticket"]),
            (1, 2),
        )
        self.assertEqual(second["status"], "released")
        self.assertEqual(
            self.git("show", f"{self.integration_ref}:lane-a.txt"),
            "lane a result",
        )
        self.assertEqual(
            self.git("show", f"{self.integration_ref}:lane-b.txt"),
            "lane b result",
        )

    def test_same_integrator_instance_rejects_concurrent_reentry(
        self,
    ) -> None:
        lane = self.terminal_lane(
            "same-instance",
            "lane-a.txt",
            "same instance\n",
        )
        registry = self.terminal_registry(lane)

        def registry_factory(worktree: Path, *, state_root: Path):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = registry
            return value

        entered = threading.Event()
        resume = threading.Event()
        validate = self.integrator._validate_candidate

        def pause_validation(
            candidate: str,
            argv: list[str],
        ) -> bool:
            entered.set()
            if not resume.wait(timeout=10):
                raise AssertionError(
                    "same-instance contender did not run",
                )
            return validate(candidate, argv)

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=registry_factory,
        ), mock.patch.object(
            self.integrator,
            "_validate_candidate",
            side_effect=pause_validation,
        ), concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            self.integrator.enqueue(
                "same-instance",
                validation_argv=[
                    "git",
                    "diff",
                    "--check",
                    "HEAD^",
                    "HEAD",
                ],
            )
            first_future = pool.submit(self.integrator.integrate_next)
            self.assertTrue(entered.wait(timeout=10))
            with self.assertRaisesRegex(
                ProjectIntegratorError,
                "invocation is already active",
            ):
                self.integrator.integrate_next()
            resume.set()
            first = first_future.result(timeout=30)
        self.assertEqual(first["status"], "released")

    def test_dead_candidate_preparation_recovers_dirty_checkout(
        self,
    ) -> None:
        lane = self.terminal_lane(
            "dead-candidate",
            "lane-a.txt",
            "dead candidate\n",
        )
        registry = self.terminal_registry(lane)

        def registry_factory(worktree: Path, *, state_root: Path):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = registry
            return value

        helper = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            process_identity = _process_creation_identity(helper.pid)
            self.assertIsInstance(process_identity, str)
            with mock.patch(
                "project_state.RecoveryRegistry",
                side_effect=registry_factory,
            ), mock.patch(
                "project_integrator.RecoveryRegistry",
                side_effect=registry_factory,
            ):
                intent = self.integrator.enqueue(
                    "dead-candidate",
                    validation_argv=[
                        "git",
                        "diff",
                        "--check",
                        "HEAD^",
                        "HEAD",
                    ],
                )
                worktree = self.integrator._ensure_integration_checkout()
                self.assertIsNotNone(self.integrator.checkout_binding)
                state = self.store.read_state(self.anchor)["state"]
                claimed = self.store.claim_next_integration_intent(
                    self.anchor,
                    expected_generation=state["generation"],
                    executor_owner="root",
                    owner_token="a" * 64,
                    pid=helper.pid,
                    process_identity=str(process_identity),
                    checkout=self.integrator.checkout_binding,
                )
                self.assertEqual(
                    claimed["intent_id"],
                    intent["intent_id"],
                )
                self.git(
                    "checkout",
                    "--detach",
                    intent["admitted_tip"],
                    cwd=worktree,
                )
                self.git(
                    "merge",
                    "--no-ff",
                    "--no-commit",
                    intent["result"]["result_commit"],
                    cwd=worktree,
                )
                self.assertNotEqual(
                    self.git(
                        "status",
                        "--porcelain=v1",
                        cwd=worktree,
                    ),
                    "",
                )
                contender = ProjectIntegrator(
                    self.checkout,
                    self.store,
                    self.anchor,
                    recovery_root=self.recovery_root,
                    integration_checkout=self.integration_checkout,
                    integration_ref=self.integration_ref,
                )
                with self.assertRaisesRegex(
                    ProjectIntegratorError,
                    "lease is held by a live owner",
                ):
                    contender.integrate_next()
                self.assertNotEqual(
                    self.git(
                        "status",
                        "--porcelain=v1",
                        cwd=worktree,
                    ),
                    "",
                )
                helper.terminate()
                helper.wait(timeout=10)
                restarted = ProjectIntegrator(
                    self.checkout,
                    self.store,
                    self.anchor,
                    recovery_root=self.recovery_root,
                    integration_checkout=self.integration_checkout,
                    integration_ref=self.integration_ref,
                )
                result = restarted.integrate_next()
            self.assertEqual(result["status"], "released")
            self.assertEqual(
                self.git(
                    "status",
                    "--porcelain=v1",
                    cwd=self.integration_checkout,
                ),
                "",
            )
        finally:
            if helper.poll() is None:
                helper.terminate()
                helper.wait(timeout=10)

    def test_post_cas_fault_replays_under_the_same_fence(self) -> None:
        lane = self.terminal_lane(
            "post-cas",
            "lane-a.txt",
            "post cas\n",
        )
        registry = self.terminal_registry(lane)

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
            queued = self.integrator.enqueue(
                "post-cas",
                validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
            )
            before = self.git("rev-parse", self.integration_ref)
            self.integrator.fault = "after-cas"
            with self.assertRaisesRegex(
                ProjectIntegratorError,
                "injected fault at after-cas",
            ):
                self.integrator.integrate_next()
            moved = self.git("rev-parse", self.integration_ref)
            self.assertNotEqual(moved, before)
            state = self.store.read_state(self.anchor)["state"]
            self.assertEqual(state["integration_fence"]["state"], "prepared")
            replay = ProjectIntegrator(
                self.checkout,
                self.store,
                self.anchor,
                recovery_root=self.recovery_root,
                integration_checkout=self.integration_checkout,
                integration_ref=self.integration_ref,
            ).integrate_next()
        self.assertEqual(replay["status"], "released")
        self.assertIsNone(queued["ticket"])
        self.assertEqual(replay["ticket"], 1)
        self.assertEqual(replay["accepted_commit"], moved)

    def test_validation_failure_and_checked_out_ref_fail_closed(self) -> None:
        lane = self.terminal_lane(
            "validation-fail",
            "lane-a.txt",
            "invalid candidate\n",
        )
        registry = self.terminal_registry(lane)

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
            before = self.git("rev-parse", self.integration_ref)
            self.integrator.enqueue(
                "validation-fail",
                validation_argv=[
                    sys.executable,
                    "-c",
                    "raise SystemExit(19)",
                ],
            )
            result = self.integrator.integrate_next()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["diagnostic"]["code"], "validation-failed")
        self.assertEqual(self.git("rev-parse", self.integration_ref), before)

        ordinary = self.temp / "ordinary"
        self.git("worktree", "add", "--detach", str(ordinary), "HEAD")
        self.git("symbolic-ref", "HEAD", self.integration_ref, cwd=ordinary)
        (ordinary / "dirty.txt").write_text(
            "dirty\n",
            encoding="utf-8",
        )
        checked_out = ProjectIntegrator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery_root,
            integration_checkout=self.temp / "other-integration",
            integration_ref=self.integration_ref,
        )
        with self.assertRaisesRegex(
            ProjectIntegratorError,
            "checked out in an ordinary worktree",
        ):
            checked_out._ensure_integration_checkout()
        with self.assertRaisesRegex(
            ProjectIntegratorError,
            "dedicated OpenBuild ref",
        ):
            ProjectIntegrator(
                self.checkout,
                self.store,
                self.anchor,
                recovery_root=self.recovery_root,
                integration_checkout=self.temp / "invalid-integration",
                integration_ref="refs/heads/main",
            )

    def test_read_dependency_becomes_stale_and_requires_full_rebind(
        self,
    ) -> None:
        producer = self.terminal_lane(
            "producer",
            "shared.txt",
            "producer result\n",
        )
        consumer = self.lanes.create(
            "consumer",
            "m5",
            self.lane_root / "consumer",
            [
                hard("lane-b.txt"),
                {"kind": "file", "path": "shared.txt", "mode": "soft"},
            ],
        )
        registry = self.terminal_registry(producer)

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
                "producer",
                validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
            )
            accepted = self.integrator.integrate_next()
        stale = next(
            item
            for item in self.store.read_state(self.anchor)["state"]["lanes"]
            if item["lane_id"] == "consumer"
        )
        self.assertEqual(
            stale["integration_stale"]["accepted_commit"],
            accepted["accepted_commit"],
        )
        with self.assertRaisesRegex(
            ProjectLaneError,
            "fresh accepted-base rebind",
        ):
            self.lanes.runner_writer_binding(
                "consumer",
                Path(str(consumer["worktree"])),
                ["lane-b.txt"],
                require_ready=True,
            )
        rebound = self.lanes.refresh_integration_stale(
            "consumer",
            allowed_set_digest="9" * 64,
            specification_revision="R-032",
        )
        self.assertNotIn("integration_stale", rebound)
        self.assertEqual(
            rebound["dependency_binding"]["accepted_base"],
            accepted["accepted_commit"],
        )
        self.assertEqual(
            rebound["dependency_binding"]["allowed_set_digest"],
            "9" * 64,
        )

    def test_positive_no_op_release_uses_real_failed_terminal_archive(
        self,
    ) -> None:
        lane, registry = self.start_real_lane(
            "noop",
            "lane-a.txt",
            ordinal=3,
        )
        expansion = ProjectScopeManager(
            self.store,
            self.anchor,
            checkout=self.checkout,
        ).expand(
            "noop",
            [hard("lane-b.txt")],
            pre_write=True,
        )
        stopping = self.lanes.consume_safe_stop_rebind(
            "noop",
            writer=lane["writer"],
            intent_id=expansion["intent_id"],
        )
        ready = self.terminalize_real_lane(
            stopping,
            registry,
            success=False,
        )
        self.assertEqual(ready["state"], "ready")
        before = self.git("rev-parse", self.integration_ref)
        self.integrator.fault = "after-no-op-acceptance"
        with self.assertRaisesRegex(
            ProjectIntegratorError,
            "injected fault at after-no-op-acceptance",
        ):
            self.integrator.abandon_no_change(
                "noop",
                validation_argv=["git", "diff", "--check"],
            )
        after_fault = self.store.read_state(self.anchor)["state"]
        self.assertTrue(
            all(
                item["status"] in {"released", "cancelled"}
                for item in after_fault["scopes"]
                if item.get("owner") == "noop"
                and item.get("mode") == "hard"
            )
        )
        tree = self.git("rev-parse", f"{before}^{{tree}}")
        advanced = self.git(
            "commit-tree",
            tree,
            "-p",
            before,
            "-m",
            "concurrent integration",
        )
        self.git("update-ref", self.integration_ref, advanced)
        self.integrator.fault = None
        released = self.integrator.abandon_no_change(
            "noop",
            validation_argv=["git", "diff", "--check"],
        )
        self.assertEqual(released["status"], "released")
        self.assertEqual(released["accepted_commit"], before)
        self.assertEqual(self.git("rev-parse", self.integration_ref), advanced)
        self.assertTrue(released["replayed"])
        self.assertRegex(released["no_op_archive"], r"^[0-9a-f]{64}$")

    def test_running_stale_consumer_finishes_and_integrates_on_current_tip(
        self,
    ) -> None:
        producer, producer_registry = self.start_real_lane(
            "stale-producer",
            "shared.txt",
            ordinal=7,
        )
        consumer, consumer_registry = self.start_real_lane(
            "stale-consumer",
            "lane-b.txt",
            ordinal=8,
            extra_scopes=[
                {"kind": "file", "path": "shared.txt", "mode": "soft"},
            ],
        )
        producer_worktree = Path(str(producer["worktree"]))
        (producer_worktree / "shared.txt").write_text(
            "producer result\n",
            encoding="utf-8",
            newline="\n",
        )
        self.git("add", "shared.txt", cwd=producer_worktree)
        self.git("commit", "-m", "stale producer", cwd=producer_worktree)
        self.terminalize_real_lane(
            producer,
            producer_registry,
            success=True,
        )
        self.integrator.enqueue(
            "stale-producer",
            validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
        )
        producer_result = self.integrator.integrate_next()
        current = self.store.read_state(self.anchor)["state"]
        stale_consumer = next(
            item
            for item in current["lanes"]
            if item["lane_id"] == "stale-consumer"
        )
        self.assertEqual(stale_consumer["state"], "running")
        self.assertEqual(
            stale_consumer["integration_stale"]["accepted_commit"],
            producer_result["accepted_commit"],
        )
        self.lanes.runner_writer_binding(
            "stale-consumer",
            Path(str(consumer["worktree"])),
            ["lane-b.txt"],
            require_ready=False,
        )
        consumer_worktree = Path(str(consumer["worktree"]))
        (consumer_worktree / "lane-b.txt").write_text(
            "consumer result\n",
            encoding="utf-8",
            newline="\n",
        )
        self.git("add", "lane-b.txt", cwd=consumer_worktree)
        self.git("commit", "-m", "stale consumer", cwd=consumer_worktree)
        self.terminalize_real_lane(
            stale_consumer,
            consumer_registry,
            success=True,
        )
        queued = self.integrator.enqueue(
            "stale-consumer",
            validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
        )
        self.assertIsNotNone(queued["result"]["dependency_stale"])
        consumer_result = self.integrator.integrate_next()
        self.assertEqual(consumer_result["status"], "released")
        final_lane = next(
            item
            for item in self.store.read_state(self.anchor)["state"]["lanes"]
            if item["lane_id"] == "stale-consumer"
        )
        self.assertNotIn("integration_stale", final_lane)
        self.assertEqual(
            (self.integration_checkout / "shared.txt").read_text(
                encoding="utf-8",
            ),
            "producer result\n",
        )
        self.assertEqual(
            (self.integration_checkout / "lane-b.txt").read_text(
                encoding="utf-8",
            ),
            "consumer result\n",
        )

    def test_root_version_finalization_rejects_worker_surfaces_and_binds_payload(
        self,
    ) -> None:
        worker_owned = self.terminal_lane(
            "worker-version",
            "README.md",
            "worker edit\n",
        )
        worker_registry = self.terminal_registry(worker_owned)

        def worker_registry_factory(
            worktree: Path,
            *,
            state_root: Path,
        ):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = worker_registry
            return value

        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=worker_registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=worker_registry_factory,
        ), self.assertRaisesRegex(
            ProjectIntegratorError,
            "root-only version surfaces",
        ):
            self.integrator.enqueue(
                "worker-version",
                validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
            )

        version_lane = self.terminal_lane(
            "version-root",
            "lane-a.txt",
            "versioned result\n",
            extra_scopes=[
                {
                    "kind": "contract",
                    "path": "version-metadata",
                    "mode": "hard",
                }
            ],
        )
        version_registry = self.terminal_registry(version_lane)

        def version_registry_factory(
            worktree: Path,
            *,
            state_root: Path,
        ):
            del worktree, state_root
            value = mock.Mock()
            value.state.return_value = version_registry
            return value

        target = "2.4.0-alpha.7"
        payload = {
            path: (
                (
                    '{"version":"' + target + '"}\n'
                    if path.endswith("plugin.json")
                    else target + "\n"
                ).encode("utf-8")
            )
            for path in _VERSION_SURFACES
        }
        downgrade = {
            path: (
                b'{"version":"2.3.9-alpha.99"}\n'
                if path.endswith("plugin.json")
                else b"2.3.9-alpha.99\n"
            )
            for path in _VERSION_SURFACES
        }
        oversized = dict(payload)
        oversized["README.md"] = b"x" * (140 * 1024)
        with mock.patch(
            "project_state.RecoveryRegistry",
            side_effect=version_registry_factory,
        ), mock.patch(
            "project_integrator.RecoveryRegistry",
            side_effect=version_registry_factory,
        ):
            self.integrator.enqueue(
                "version-root",
                validation_argv=["git", "diff", "--check", "HEAD^", "HEAD"],
            )
            with self.assertRaisesRegex(
                ProjectIntegratorError,
                "would not advance integration order",
            ):
                self.integrator.integrate_next(
                    requested_version_target="2.3.9-alpha.99",
                    version_surfaces=downgrade,
                )
            with self.assertRaisesRegex(
                ProjectIntegratorError,
                "exceeds bounded JSON size",
            ):
                self.integrator.integrate_next(
                    requested_version_target=target,
                    version_surfaces=oversized,
                )
            unclaimed = self.store.read_state(self.anchor)["state"][
                "integration_queue"
            ][0]
            self.assertEqual(unclaimed["status"], "queued")
            self.assertIsNone(unclaimed["ticket"])
            with mock.patch.object(
                self.store,
                "read_version_finalization_payload",
                side_effect=ProjectStateError(
                    "injected payload read failure",
                ),
            ), self.assertRaisesRegex(
                ProjectIntegratorError,
                "candidate preparation failed",
            ):
                self.integrator.integrate_next(
                    requested_version_target=target,
                    version_surfaces=payload,
                )
            self.assertEqual(
                self.git(
                    "status",
                    "--porcelain=v1",
                    cwd=self.integration_checkout,
                ),
                "",
            )
            self.assertEqual(
                self.git(
                    "rev-parse",
                    "HEAD",
                    cwd=self.integration_checkout,
                ),
                self.git("rev-parse", self.integration_ref),
            )
            self.assertEqual(
                self.store.read_state(self.anchor)["state"][
                    "integration_queue"
                ][0]["status"],
                "integrating",
            )
            result = self.integrator.integrate_next(
                requested_version_target=target,
                version_surfaces=payload,
            )
        self.assertEqual(result["status"], "released")
        for relative, expected in payload.items():
            self.assertEqual(
                (
                    self.integration_checkout.joinpath(
                        *relative.split("/")
                    )
                ).read_bytes(),
                expected,
            )

    def test_dirty_user_checkout_and_cas_race_do_not_move_common_ref(self) -> None:
        lane = self.terminal_lane("race", "race.txt", "race\n")
        (self.checkout / "user.txt").write_text("dirty\n", encoding="utf-8")
        before = self.git("rev-parse", self.integration_ref)
        registry = self.terminal_registry(lane)

        def registry_factory(worktree: Path, *, state_root: Path):
            del state_root, worktree
            value = mock.Mock()
            value.state.return_value = registry
            return value

        with mock.patch("project_state.RecoveryRegistry", side_effect=registry_factory), mock.patch(
            "project_integrator.RecoveryRegistry", side_effect=registry_factory
        ):
            self.integrator.enqueue("race", validation_argv=["git", "diff", "--check"])
            self.integrator.fault = "before-cas"
            with self.assertRaisesRegex(ProjectIntegratorError, "injected fault"):
                self.integrator.integrate_next()
            self.integrator.fault = None
            (self.checkout / "concurrent.txt").write_text(
                "concurrent\n",
                encoding="utf-8",
            )
            self.git("add", "concurrent.txt")
            self.git("commit", "-m", "concurrent update")
            competing = self.git("rev-parse", "HEAD")
            self.git("update-ref", self.integration_ref, competing)
            result = self.integrator.integrate_next()
        self.assertNotEqual(competing, before)
        self.assertEqual(self.git("rev-parse", self.integration_ref), competing)
        self.assertEqual(result["status"], "stale")
        self.assertEqual((self.checkout / "user.txt").read_text(encoding="utf-8"), "dirty\n")

    def test_replay_after_candidate_fault_keeps_one_ticket_and_releases_once(self) -> None:
        lane = self.terminal_lane("replay", "replay.txt", "replay\n")
        registry = self.terminal_registry(lane)

        def registry_factory(worktree: Path, *, state_root: Path):
            del state_root, worktree
            value = mock.Mock()
            value.state.return_value = registry
            return value

        with mock.patch("project_state.RecoveryRegistry", side_effect=registry_factory), mock.patch(
            "project_integrator.RecoveryRegistry", side_effect=registry_factory
        ):
            self.integrator.enqueue("replay", validation_argv=["git", "diff", "--check"])
            self.integrator.fault = "after-candidate"
            with self.assertRaisesRegex(ProjectIntegratorError, "injected fault"):
                self.integrator.integrate_next()
            self.integrator.fault = None
            completed = self.integrator.integrate_next()
            replay = self.integrator.integrate_next()
        self.assertEqual(completed["status"], "released")
        self.assertEqual(completed["ticket"], 1)
        self.assertIsNone(replay)
        intents = self.store.read_state(self.anchor)["state"]["integration_queue"]
        self.assertEqual([item["ticket"] for item in intents], [1])

    def test_conflict_and_validation_failure_preserve_branches_and_tickets(self) -> None:
        first = self.terminal_lane(
            "first", "first-scope.txt", "first\n", write_path="base.txt"
        )
        second = self.terminal_lane(
            "second", "second-scope.txt", "second\n", write_path="base.txt"
        )
        registries = {
            str(first["worktree"]): self.terminal_registry(first),
            str(second["worktree"]): self.terminal_registry(second),
        }

        def registry_factory(worktree: Path, *, state_root: Path):
            del state_root
            value = mock.Mock()
            value.state.return_value = registries[str(worktree)]
            return value

        with mock.patch("project_state.RecoveryRegistry", side_effect=registry_factory), mock.patch(
            "project_integrator.RecoveryRegistry", side_effect=registry_factory
        ):
            self.integrator.enqueue("first", validation_argv=["git", "diff", "--check"])
            self.assertEqual(self.integrator.integrate_next()["status"], "released")
            accepted = self.git("rev-parse", self.integration_ref)
            self.integrator.enqueue("second", validation_argv=["git", "diff", "--check"])
            conflict = self.integrator.integrate_next()
        self.assertEqual(conflict["status"], "blocked")
        self.assertEqual(conflict["diagnostic"]["code"], "merge-conflict")
        self.assertEqual(self.git("rev-parse", self.integration_ref), accepted)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/openbuild/lanes/second"),
            self.git("rev-parse", "HEAD", cwd=Path(str(second["worktree"]))),
        )

    def test_abandoned_no_change_refuses_a_changed_or_unbound_lane(self) -> None:
        lane = self.lanes.create(
            "noop",
            "m5-noop",
            self.lane_root / "noop",
            [hard("noop.txt")],
        )
        worktree = Path(str(lane["worktree"]))
        (worktree / "noop.txt").write_text("must remain\n", encoding="utf-8")
        with self.assertRaisesRegex(ProjectIntegratorError, "not eligible"):
            self.integrator.abandon_no_change(
                "noop",
                validation_argv=["git", "diff", "--check"],
            )
        self.assertEqual(
            (worktree / "noop.txt").read_text(encoding="utf-8"),
            "must remain\n",
        )


if __name__ == "__main__":
    unittest.main()
