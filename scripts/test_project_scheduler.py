"""Focused R-032 M4 tests for durable milestone DAG scheduling."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Callable

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

import agent_runner  # type: ignore[import-not-found]
from project_lanes import (  # type: ignore[import-not-found]
    ProjectLaneCoordinator,
    ProjectLaneError,
)
from project_scheduler import (  # type: ignore[import-not-found]
    ProjectScheduler,
    ProjectSchedulerError,
)
from project_state import (  # type: ignore[import-not-found]
    ProjectStateError,
    ProjectStateStore,
    _validate_milestone_dag,
    _validate_milestone_lane_projection,
    _validate_milestone_projection,
    _validate_milestone_transition,
    _digest,
)
from project_scopes import ProjectScopeManager  # type: ignore[import-not-found]
from recovery_state import RecoveryRegistry  # type: ignore[import-not-found]


class MemoryStore:
    """CAS double that runs the production milestone validators."""

    def __init__(self) -> None:
        self.state = {
            "generation": 0,
            "state": "clean",
            "milestones": [],
            "lanes": [],
            "scopes": [],
            "integration_acceptances": [],
        }

    def read_state(self, anchor_id: str) -> dict[str, object]:
        del anchor_id
        return {"status": "present", "state": copy.deepcopy(self.state)}

    def read_milestones(self, anchor_id: str) -> dict[str, object]:
        del anchor_id
        return {
            "status": "present",
            "milestones": copy.deepcopy(self.state["milestones"]),
        }

    def replace_milestone_state(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        milestones: list[dict[str, object]],
    ) -> dict[str, object]:
        del anchor_id
        if expected_generation != self.state["generation"]:
            raise ProjectStateError("project generation changed")
        parsed = [_validate_milestone_projection(item) for item in milestones]
        _validate_milestone_dag(parsed)
        _validate_milestone_transition(self.state["milestones"], parsed)
        _validate_milestone_lane_projection(
            parsed,
            self.state["lanes"],
            self.state["scopes"],
        )
        before = {
            (item["task_id"], item["milestone_id"]): item
            for item in self.state["milestones"]
        }
        completed = [
            item
            for item in parsed
            if item["state"] == "completed"
            and (item["task_id"], item["milestone_id"]) in before
            and before[(item["task_id"], item["milestone_id"])]["state"]
            != "completed"
        ]
        for item in completed:
            lanes = [
                lane
                for lane in self.state["lanes"]
                if lane.get("scheduler_binding")
                == {
                    "schema": "project-scheduler-lane-v1",
                    "task_id": item["task_id"],
                    "milestone_id": item["milestone_id"],
                }
            ]
            if (
                len(lanes) != 1
                or lanes[0].get("state") != "waiting-for-integration"
                or not isinstance(lanes[0].get("writer"), dict)
            ):
                raise ProjectStateError(
                    "milestone completion requires one exact terminal lane"
                )
            acceptances = [
                acceptance
                for acceptance in self.state["integration_acceptances"]
                if acceptance.get("lane_id") == lanes[0].get("lane_id")
            ]
            owned_hard = [
                scope
                for scope in self.state["scopes"]
                if scope.get("owner") == lanes[0].get("lane_id")
                and scope.get("mode") == "hard"
            ]
            if len(acceptances) != 1 or not owned_hard or any(
                scope.get("status") not in {"released", "cancelled"}
                for scope in owned_hard
            ):
                raise ProjectStateError(
                    "milestone completion requires integrated scope release"
                )
        self.state = {
            **self.state,
            "generation": expected_generation + 1,
            "milestones": parsed,
        }
        return copy.deepcopy(self.state)


class ConcurrentMemoryStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.RLock()
        self.initial_publishers = threading.Barrier(2)

    def read_state(self, anchor_id: str) -> dict[str, object]:
        with self.lock:
            return super().read_state(anchor_id)

    def read_milestones(self, anchor_id: str) -> dict[str, object]:
        with self.lock:
            return super().read_milestones(anchor_id)

    def replace_milestone_state(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        milestones: list[dict[str, object]],
    ) -> dict[str, object]:
        if expected_generation == 0:
            self.initial_publishers.wait(timeout=10)
        with self.lock:
            return super().replace_milestone_state(
                anchor_id,
                expected_generation=expected_generation,
                milestones=milestones,
            )


def hard(path: str, kind: str = "file") -> dict[str, str]:
    return {"kind": kind, "path": path, "mode": "hard"}


def soft(path: str, kind: str = "file") -> dict[str, str]:
    return {"kind": kind, "path": path, "mode": "soft"}


class ProjectSchedulerM4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.anchor = "anchor"
        self.scheduler = ProjectScheduler(
            self.store,  # type: ignore[arg-type]
            self.anchor,
            "task-a",
        )

    @staticmethod
    def plan() -> list[dict[str, object]]:
        return [
            {
                "milestone_id": "hotspot",
                "depends_on": [],
                "hard_scopes": [hard("scripts/owner.py")],
                "soft_intents": [soft("docs/intent.md")],
                "primary_signal": "python -m unittest hotspot",
                "red_signal": "hotspot regression",
                "integration_output": "owner commit",
                "hotspot": True,
            },
            {
                "milestone_id": "blocked",
                "depends_on": ["hotspot"],
                "hard_scopes": [hard("scripts/consumer.py")],
                "soft_intents": [],
                "primary_signal": "python -m unittest consumer",
                "red_signal": "consumer regression",
                "integration_output": "consumer commit",
                "hotspot": False,
            },
            {
                "milestone_id": "independent",
                "depends_on": [],
                "hard_scopes": [hard("scripts/independent.py")],
                "soft_intents": [soft("scripts/owner.py")],
                "primary_signal": "python -m unittest independent",
                "red_signal": "independent regression",
                "integration_output": "independent commit",
                "hotspot": False,
            },
        ]

    def mark_terminal(self, milestone_id: str) -> None:
        record = next(
            item
            for item in self.store.state["milestones"]
            if item["task_id"] == "task-a"
            and item["milestone_id"] == milestone_id
        )
        lane_id = f"{milestone_id}-lane"
        writer = {
            "lease_id": f"{milestone_id}-lease",
            "run_id": f"{milestone_id}-run",
            "allowed_set_digest": "a" * 64,
            "lease_kind": "normal-contained",
        }
        self.store.state["lanes"].append(
            {
                "lane_id": lane_id,
                "milestone": f"task-a:{milestone_id}",
                "scheduler_binding": {
                    "schema": "project-scheduler-lane-v1",
                    "task_id": "task-a",
                    "milestone_id": milestone_id,
                },
                "state": "waiting-for-integration",
                "writer": writer,
                "terminal_evidence": "b" * 64,
                "scope_requests": copy.deepcopy(record["hard_scopes"]),
            },
        )
        self.store.state["scopes"].extend(
            {
                **copy.deepcopy(scope),
                "owner": lane_id,
                "status": "released",
            }
            for scope in record["hard_scopes"]
        )
        self.store.state["integration_acceptances"].append(
            {
                "acceptance_id": "c" * 64,
                "lane_id": lane_id,
                "writer": writer,
                "terminal_archive": "b" * 64,
            },
        )

    def test_waiting_is_durable_and_independent_ready_work_progresses(
        self,
    ) -> None:
        status = self.scheduler.publish_plan(self.plan())
        self.assertEqual(status["ready"], ["hotspot", "independent"])
        self.assertEqual(status["waiting"], ["blocked"])
        stored = self.store.read_milestones(self.anchor)["milestones"]
        self.assertTrue(all("writer" not in item for item in stored))
        self.mark_terminal("independent")
        self.assertEqual(
            self.scheduler.complete(
                "independent",
                focused_green=True,
                intermediate_valid=True,
            )["ready"],
            ["hotspot"],
        )
        self.mark_terminal("hotspot")
        self.assertEqual(
            self.scheduler.complete(
                "hotspot",
                focused_green=True,
                intermediate_valid=True,
            )["integration_candidates"],
            ["hotspot", "independent"],
        )
        self.assertEqual(self.scheduler.status()["ready"], ["blocked"])

    def test_plan_rejects_cycles_and_soft_scope_never_blocks(self) -> None:
        with self.assertRaisesRegex(ProjectSchedulerError, "cycle"):
            self.scheduler.publish_plan(
                [
                    {
                        "milestone_id": "a",
                        "depends_on": ["b"],
                        "hard_scopes": [hard("a.py")],
                        "soft_intents": [],
                        "primary_signal": "a",
                        "red_signal": "a",
                        "integration_output": "a",
                        "hotspot": False,
                    },
                    {
                        "milestone_id": "b",
                        "depends_on": ["a"],
                        "hard_scopes": [hard("b.py")],
                        "soft_intents": [],
                        "primary_signal": "b",
                        "red_signal": "b",
                        "integration_output": "b",
                        "hotspot": False,
                    },
                ],
            )
        status = self.scheduler.publish_plan(self.plan())
        self.assertIn("independent", status["ready"])

    def test_completion_fails_closed_without_green_or_valid_intermediate(
        self,
    ) -> None:
        self.scheduler.publish_plan(self.plan())
        with self.assertRaisesRegex(ProjectSchedulerError, "focused green"):
            self.scheduler.complete(
                "hotspot",
                focused_green=False,
                intermediate_valid=True,
            )
        with self.assertRaisesRegex(ProjectSchedulerError, "intermediate"):
            self.scheduler.complete(
                "hotspot",
                focused_green=True,
                intermediate_valid=False,
            )
        self.assertEqual(
            self.scheduler.status()["ready"],
            ["hotspot", "independent"],
        )

    def test_structured_scope_contract_rejects_aliases_modes_and_controls(
        self,
    ) -> None:
        cases = []
        raw = self.plan()
        raw[0]["hard_scopes"] = ["scripts/owner.py"]
        cases.append(raw)
        wrong_mode = self.plan()
        wrong_mode[0]["hard_scopes"] = [soft("scripts/owner.py")]
        cases.append(wrong_mode)
        control = self.plan()
        control[0]["hard_scopes"] = [hard("scripts/\0owner.py")]
        cases.append(control)
        c1_control = self.plan()
        c1_control[0]["hard_scopes"] = [hard("scripts/\u0085owner.py")]
        cases.append(c1_control)
        reserved = self.plan()
        reserved[0]["hard_scopes"] = [hard("CON")]
        cases.append(reserved)
        trailing_alias = self.plan()
        trailing_alias[0]["hard_scopes"] = [hard("scripts/owner.")]
        cases.append(trailing_alias)
        drive_relative = self.plan()
        drive_relative[0]["hard_scopes"] = [hard("C:owner.py")]
        cases.append(drive_relative)
        aliases = self.plan()
        aliases[0]["hard_scopes"] = [
            hard("scripts/Owner.py"),
            hard("scripts/owner.py"),
        ]
        cases.append(aliases)
        overlap = self.plan()
        overlap[0]["soft_intents"] = [soft("scripts/owner.py")]
        cases.append(overlap)
        ancestor = self.plan()
        ancestor[0]["hard_scopes"] = [
            hard("scripts", kind="directory"),
            hard("scripts/owner.py"),
        ]
        cases.append(ancestor)
        cross_kind_alias = self.plan()
        cross_kind_alias[0]["hard_scopes"] = [
            hard("scripts/owner.py"),
            hard("scripts/owner.py", kind="directory"),
        ]
        cases.append(cross_kind_alias)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(
                ProjectSchedulerError,
            ):
                ProjectScheduler(
                    MemoryStore(),  # type: ignore[arg-type]
                    self.anchor,
                    "task-a",
                ).publish_plan(plan)

        direct = {
            "task_id": "task-a",
            "milestone_id": "direct",
            "depends_on": [],
            "hard_scopes": [
                hard("scripts/direct.py"),
                hard("scripts", kind="directory"),
            ],
            "soft_intents": [],
            "primary_signal": "direct",
            "red_signal": "direct",
            "integration_output": "direct",
            "hotspot": False,
            "state": "ready",
        }
        with self.assertRaisesRegex(
            ProjectStateError,
            "ancestor collision",
        ):
            MemoryStore().replace_milestone_state(
                self.anchor,
                expected_generation=0,
                milestones=[direct],
            )

    def test_hotspot_ready_work_is_actionably_prioritized(self) -> None:
        status = self.scheduler.publish_plan(
            [
                {
                    "milestone_id": "a-regular",
                    "depends_on": [],
                    "hard_scopes": [hard("regular.py")],
                    "soft_intents": [],
                    "primary_signal": "regular",
                    "red_signal": "regular",
                    "integration_output": "regular",
                    "hotspot": False,
                },
                {
                    "milestone_id": "z-hotspot",
                    "depends_on": [],
                    "hard_scopes": [hard("hotspot.py")],
                    "soft_intents": [],
                    "primary_signal": "hotspot",
                    "red_signal": "hotspot",
                    "integration_output": "hotspot",
                    "hotspot": True,
                },
            ],
        )
        self.assertEqual(
            status["ready"],
            ["z-hotspot", "a-regular"],
        )

    def test_simultaneous_task_plan_publishers_converge_by_cas(
        self,
    ) -> None:
        store = ConcurrentMemoryStore()
        schedulers = [
            ProjectScheduler(
                store,  # type: ignore[arg-type]
                self.anchor,
                task_id,
            )
            for task_id in ("task-a", "task-b")
        ]
        errors: list[BaseException] = []

        def publish(
            scheduler: ProjectScheduler,
            path: str,
        ) -> None:
            try:
                scheduler.publish_plan(
                    [
                        {
                            "milestone_id": "only",
                            "depends_on": [],
                            "hard_scopes": [hard(path)],
                            "soft_intents": [],
                            "primary_signal": path,
                            "red_signal": path,
                            "integration_output": path,
                            "hotspot": False,
                        },
                    ],
                )
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(
                target=publish,
                args=(scheduler, f"{scheduler.task_id}.py"),
            )
            for scheduler in schedulers
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(
            [
                (item["task_id"], item["milestone_id"])
                for item in store.state["milestones"]
            ],
            [("task-a", "only"), ("task-b", "only")],
        )
        self.assertEqual(store.state["generation"], 2)

    def test_reordered_replay_is_canonical_and_tasks_are_isolated(self) -> None:
        first = self.scheduler.publish_plan(list(reversed(self.plan())))
        replay = self.scheduler.publish_plan(self.plan())
        self.assertEqual(first, replay)
        other = ProjectScheduler(
            self.store,  # type: ignore[arg-type]
            self.anchor,
            "task-b",
        )
        other.publish_plan(
            [
                {
                    "milestone_id": "only",
                    "depends_on": [],
                    "hard_scopes": [hard("other.py")],
                    "soft_intents": [],
                    "primary_signal": "other",
                    "red_signal": "other",
                    "integration_output": "other",
                    "hotspot": False,
                },
            ],
        )
        self.assertEqual(other.status()["ready"], ["only"])
        self.assertEqual(
            self.scheduler.status()["ready"],
            ["hotspot", "independent"],
        )
        identities = [
            (item["task_id"], item["milestone_id"])
            for item in self.store.state["milestones"]
        ]
        self.assertEqual(identities, sorted(identities))

    def test_direct_store_cannot_forge_readiness_or_batch_completion(
        self,
    ) -> None:
        self.scheduler.publish_plan(self.plan())
        state = self.store.read_state(self.anchor)["state"]
        forged = copy.deepcopy(state["milestones"])
        next(
            item for item in forged if item["milestone_id"] == "blocked"
        )["state"] = "ready"
        with self.assertRaisesRegex(ProjectStateError, "dependency-derived"):
            self.store.replace_milestone_state(
                self.anchor,
                expected_generation=state["generation"],
                milestones=forged,
            )
        batch = copy.deepcopy(state["milestones"])
        for item in batch:
            if item["milestone_id"] in {"hotspot", "blocked"}:
                item["state"] = "completed"
                item["validation"] = {
                    "focused_green": True,
                    "intermediate_valid": True,
                }
        with self.assertRaises(ProjectStateError):
            self.store.replace_milestone_state(
                self.anchor,
                expected_generation=state["generation"],
                milestones=batch,
            )

    def test_generation_races_and_state_regression_fail_closed(self) -> None:
        self.scheduler.publish_plan(self.plan())
        generation = self.store.read_state(self.anchor)["state"]["generation"]
        with self.assertRaisesRegex(ProjectStateError, "generation changed"):
            self.store.replace_milestone_state(
                self.anchor,
                expected_generation=generation - 1,
                milestones=[],
            )
        self.mark_terminal("hotspot")
        self.scheduler.complete(
            "hotspot",
            focused_green=True,
            intermediate_valid=True,
        )
        with self.assertRaisesRegex(ProjectSchedulerError, "cannot regress"):
            self.scheduler.wait("hotspot")


class ProjectSchedulerFilesystemM4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_context = tempfile.TemporaryDirectory(
            prefix="openbuild-project-scheduler-",
        )
        self.temp = Path(self.temp_context.name)
        self.checkout = self.temp / "checkout"
        self.checkout.mkdir()
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.checkout / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "-m", "base")
        self.integration_ref = "refs/openbuild/integration"
        self.git("update-ref", self.integration_ref, "HEAD")
        self.coordinator_root = self.temp / "coordinator"
        self.recovery_root = self.temp / "recovery"
        self.lane_root = self.temp / "lanes"
        self.lane_root.mkdir()
        self.store = ProjectStateStore(
            self.checkout,
            coordinator_root=self.coordinator_root,
        )
        capability = self.store.issue_bootstrap_capability(
            "plan",
            "attempt",
        )["bootstrap_capability"]
        self.anchor = self.store.create_anchor(
            capability,
            "plan",
            "attempt",
        )["anchor_id"]
        self.store.bootstrap(self.anchor, "clean")
        self.lanes = ProjectLaneCoordinator(
            self.checkout,
            self.store,
            self.anchor,
            recovery_root=self.recovery_root,
            lane_root=self.lane_root,
            integration_ref=self.integration_ref,
        )
        self.scheduler = ProjectScheduler(
            self.store,
            self.anchor,
            "task-a",
        )

    def tearDown(self) -> None:
        self.temp_context.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd or self.checkout,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def forge_lane_state(
        self,
        lane_id: str,
        *,
        state_name: str,
    ) -> dict[str, object]:
        state_path = (
            self.coordinator_root
            / "states"
            / f"{self.anchor}.json"
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        lane = next(
            item for item in state["lanes"] if item["lane_id"] == lane_id
        )
        if state_name == "waiting-for-integration":
            lane["state"] = state_name
            lane["writer"] = {
                "lease_id": "lease",
                "run_id": "run",
                "allowed_set_digest": "a" * 64,
                "lease_kind": "normal-contained",
            }
            lane["terminal_evidence"] = "d" * 64
        elif state_name == "recovery-ready":
            lane["state"] = state_name
            lane["writer"] = None
            lane["reason"] = "cancelled"
            lane["terminal_from"] = "running"
            lane["terminal_evidence"] = "d" * 64
            lane["recovery_checkpoint_digest"] = "e" * 64
        else:
            raise AssertionError("unsupported forged lane state")
        state["digest"] = _digest(state)
        state_path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        return lane

    def make_fake_codex(self) -> Path:
        source = self.temp / "fake_codex.py"
        source.write_text(
            "\n".join(
                [
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    "if sys.argv[1:] == ['login', 'status']:",
                    "    print('Logged in using ChatGPT')",
                    "    raise SystemExit(0)",
                    "prompt = sys.stdin.read()",
                    "prefix = 'OPENBUILD_TEST_PAYLOAD='",
                    "line = next(",
                    "    item for item in prompt.splitlines()",
                    "    if item.startswith(prefix)",
                    ")",
                    "payload = json.loads(line[len(prefix):])",
                    "repo = Path(sys.argv[sys.argv.index('-C') + 1])",
                    "target = repo / payload['allowed']",
                    "target.parent.mkdir(parents=True, exist_ok=True)",
                    "target.write_text(",
                    "    payload['content'],",
                    "    encoding='utf-8',",
                    "    newline='\\n',",
                    ")",
                    "result = Path(sys.argv[sys.argv.index('-o') + 1])",
                    "result.write_text('completed\\n', encoding='utf-8')",
                    "print(json.dumps({",
                    "    'type': 'thread.started',",
                    "    'thread_id': payload['lane'],",
                    "}), flush=True)",
                    "print(json.dumps({",
                    "    'type': 'turn.completed',",
                    "    'usage': {'output_tokens': 1},",
                    "}), flush=True)",
                ],
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if os.name == "nt":
            command = self.temp / "fake-codex.cmd"
            command.write_text(
                f'@echo off\r\n"{sys.executable}" "{source}" %*\r\n',
                encoding="utf-8",
                newline="",
            )
            return command
        command = self.temp / "fake-codex"
        command.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{source}" "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        command.chmod(0o700)
        return command

    def execute_real_milestone_lifecycle(
        self,
        milestone_id: str,
        lane_id: str,
        allowed: str,
        content: str,
        fake_codex: Path,
        before_integration: (
            Callable[[dict[str, object]], None] | None
        ) = None,
    ) -> dict[str, object]:
        lane = self.lanes.create(
            lane_id,
            self.scheduler.lane_milestone(milestone_id),
            self.lane_root / lane_id,
            [hard(allowed)],
        )
        worktree = Path(str(lane["worktree"]))
        registry = RecoveryRegistry(
            worktree,
            state_root=self.recovery_root,
        )
        prompt = (
            "Run the bounded scheduler lifecycle fixture.\n"
            f"OPENBUILD_TEST_PAYLOAD={json.dumps({'lane': lane_id, 'allowed': allowed, 'content': content})}\n"
        )
        prompt_binding = agent_runner.stage_owner_prompt_snapshot(
            registry,
            prompt.encode("utf-8"),
        )
        run_dir = self.temp / "runs" / lane_id
        codex_home = self.temp / "codex-home"
        codex_home.mkdir(exist_ok=True)
        environment = dict(os.environ)
        environment["CODEX_HOME"] = str(codex_home)
        for credential in agent_runner.API_CREDENTIALS:
            environment.pop(credential, None)
        command = [
            sys.executable,
            str(Path(agent_runner.__file__).resolve()),
            "dispatch",
            "--agent",
            "openbuild_implementation_fast",
            "--task-name",
            f"{lane_id}-scheduler-lifecycle",
            "--repo",
            str(worktree),
            "--prompt-snapshot-id",
            str(prompt_binding["prompt_snapshot_id"]),
            "--prompt-sha256",
            str(prompt_binding["prompt_sha256"]),
            "--lease-id",
            f"{lane_id}-lease",
            "--allowed-file",
            allowed,
            "--specification-revision",
            "R-032",
            "--recovery-target-milestone",
            f"{lane_id}-recovery",
            "--run-dir",
            str(run_dir),
            "--codex-bin",
            str(fake_codex),
            "--project-lane-id",
            lane_id,
            "--project-checkout",
            str(self.checkout),
            "--project-coordinator-root",
            str(self.coordinator_root),
            "--project-anchor-id",
            self.anchor,
            "--project-recovery-root",
            str(self.recovery_root),
            "--project-lane-root",
            str(self.lane_root),
            "--project-integration-ref",
            self.integration_ref,
        ]
        dispatched = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            dispatched.returncode,
            0,
            {"stdout": dispatched.stdout, "stderr": dispatched.stderr},
        )
        deadline = time.monotonic() + 60
        while True:
            receipt = agent_runner.public_receipt(run_dir)
            if receipt["status"] != "running":
                break
            if time.monotonic() >= deadline:
                self.fail(
                    f"{lane_id} runner did not terminalize: "
                    f"{json.dumps(receipt, sort_keys=True)}",
                )
            time.sleep(0.05)
        self.assertEqual(receipt["status"], "completed")
        agent_runner.reconcile_implementation_registry(
            run_dir,
            receipt,
            success_verification_digest="f" * 64,
        )
        terminal_state = self.store.read_state(self.anchor)["state"]
        terminal_lane = next(
            item
            for item in terminal_state["lanes"]
            if item["lane_id"] == lane_id
        )
        self.assertEqual(
            terminal_lane["state"],
            "waiting-for-integration",
        )
        if before_integration is not None:
            before_integration(terminal_lane)
        self.git("add", allowed, cwd=worktree)
        self.git(
            "commit",
            "-m",
            f"integrate {milestone_id}",
            cwd=worktree,
        )
        accepted_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode("ascii").strip()
        self.git(
            "update-ref",
            self.integration_ref,
            accepted_commit,
        )
        acceptance = self.lanes.record_scope_integration_acceptance(
            lane_id,
            admitted_commit=str(terminal_lane["base"]),
            accepted_commit=accepted_commit,
            validation_argv=[
                "git",
                "diff",
                "--check",
                str(terminal_lane["base"]),
                accepted_commit,
            ],
        )
        ProjectScopeManager(
            self.store,
            self.anchor,
            checkout=self.checkout,
        ).release(
            lane_id,
            acceptance=str(acceptance["acceptance_id"]),
        )
        return self.scheduler.complete(
            milestone_id,
            focused_green=True,
            intermediate_valid=True,
        )

    def test_filesystem_reload_and_lane_activation_gate_are_authoritative(
        self,
    ) -> None:
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        with self.assertRaisesRegex(ProjectLaneError, "DAG dependencies"):
            self.lanes.create(
                "blocked-lane",
                self.scheduler.lane_milestone("blocked"),
                self.lane_root / "blocked-lane",
                [hard("scripts/consumer.py")],
            )
        self.assertFalse((self.lane_root / "blocked-lane").exists())
        independent = self.lanes.create(
            "independent-lane",
            self.scheduler.lane_milestone("independent"),
            self.lane_root / "independent-lane",
            [hard("scripts/independent.py")],
        )
        self.assertEqual(
            self.scheduler.wait("blocked")["waiting"],
            ["blocked"],
        )
        reloaded = ProjectStateStore(
            self.checkout,
            coordinator_root=self.coordinator_root,
        )
        self.assertEqual(
            ProjectScheduler(reloaded, self.anchor, "task-a").status(),
            self.scheduler.status(),
        )
        binding = self.lanes.runner_writer_binding(
            "independent-lane",
            Path(str(independent["worktree"])),
            ["scripts/independent.py"],
            require_ready=True,
        )
        self.assertEqual(binding["milestone"], "task-a:independent")
        state = self.store.read_state(self.anchor)["state"]
        self.assertFalse(
            any(
                scope.get("owner") == "blocked-lane"
                for scope in state["scopes"]
            ),
        )

    def test_lane_plan_binding_scopes_duplicates_and_task_isolation(
        self,
    ) -> None:
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        with self.assertRaisesRegex(ProjectLaneError, "not bound"):
            self.lanes.create(
                "unbound-lane",
                {
                    "schema": "project-scheduler-lane-v1",
                    "task_id": "task-a",
                    "milestone_id": "missing",
                },
                self.lane_root / "unbound-lane",
                [hard("scripts/consumer.py")],
            )
        self.assertFalse((self.lane_root / "unbound-lane").exists())
        with self.assertRaisesRegex(ProjectLaneError, "hard scopes differ"):
            self.lanes.create(
                "wrong-scope-lane",
                self.scheduler.lane_milestone("blocked"),
                self.lane_root / "wrong-scope-lane",
                [hard("scripts/wrong.py")],
            )
        self.assertFalse((self.lane_root / "wrong-scope-lane").exists())
        first = self.lanes.create(
            "hotspot-lane",
            self.scheduler.lane_milestone("hotspot"),
            self.lane_root / "hotspot-lane",
            [hard("scripts/owner.py")],
        )
        with self.assertRaisesRegex(ProjectLaneError, "another lane"):
            self.lanes.create(
                "duplicate-lane",
                self.scheduler.lane_milestone("hotspot"),
                self.lane_root / "duplicate-lane",
                [hard("scripts/owner.py")],
            )
        other = ProjectScheduler(
            self.store,
            self.anchor,
            "task-b",
        )
        other.publish_plan(
            [
                {
                    "milestone_id": "blocked",
                    "depends_on": [],
                    "hard_scopes": [hard("scripts/task-b.py")],
                    "soft_intents": [],
                    "primary_signal": "task-b",
                    "red_signal": "task-b",
                    "integration_output": "task-b",
                    "hotspot": False,
                },
            ],
        )
        second = self.lanes.create(
            "task-b-lane",
            other.lane_milestone("blocked"),
            self.lane_root / "task-b-lane",
            [hard("scripts/task-b.py")],
        )
        self.assertEqual(
            first["milestone"],
            "task-a:hotspot",
        )
        self.assertEqual(
            self.lanes.runner_writer_binding(
                "task-b-lane",
                Path(str(second["worktree"])),
                ["scripts/task-b.py"],
                require_ready=True,
            )["milestone"],
            "task-b:blocked",
        )
        self.assertEqual(self.scheduler.status()["waiting"], ["blocked"])
        self.assertEqual(other.status()["ready"], ["blocked"])

    def test_legacy_milestone_names_survive_scheduler_collisions(
        self,
    ) -> None:
        colon = self.lanes.create(
            "legacy-colon",
            "legacy:phase",
            self.lane_root / "legacy-colon",
            [hard("legacy-colon.py")],
        )
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        bare = self.lanes.create(
            "legacy-bare",
            "blocked",
            self.lane_root / "legacy-bare",
            [hard("legacy-bare.py")],
        )
        self.assertNotIn("scheduler_binding", colon)
        self.assertNotIn("scheduler_binding", bare)
        reloaded = ProjectStateStore(
            self.checkout,
            coordinator_root=self.coordinator_root,
        ).read_state(self.anchor)
        self.assertEqual(reloaded["status"], "present")
        self.assertEqual(
            {
                lane["lane_id"]: lane["milestone"]
                for lane in reloaded["state"]["lanes"]
            },
            {
                "legacy-bare": "blocked",
                "legacy-colon": "legacy:phase",
            },
        )
        self.assertEqual(
            self.scheduler.status()["waiting"],
            ["blocked"],
        )

    def test_completion_sink_requires_exact_terminal_registry_receipt(
        self,
    ) -> None:
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        with self.assertRaisesRegex(ProjectSchedulerError, "terminal lane"):
            self.scheduler.complete(
                "hotspot",
                focused_green=True,
                intermediate_valid=True,
            )
        lane = self.lanes.create(
            "independent-lane",
            self.scheduler.lane_milestone("independent"),
            self.lane_root / "independent-lane",
            [hard("scripts/independent.py")],
        )
        state = self.store.read_state(self.anchor)["state"]
        proposed = copy.deepcopy(state["milestones"])
        item = next(
            value
            for value in proposed
            if value["task_id"] == "task-a"
            and value["milestone_id"] == "independent"
        )
        item["state"] = "completed"
        item["validation"] = {
            "focused_green": True,
            "intermediate_valid": True,
        }
        with self.assertRaisesRegex(ProjectStateError, "terminal lane"):
            self.store.replace_milestone_state(
                self.anchor,
                expected_generation=state["generation"],
                milestones=proposed,
            )

        forged = self.forge_lane_state(
            "independent-lane",
            state_name="waiting-for-integration",
        )
        state = self.store.read_state(self.anchor)["state"]
        proposed = copy.deepcopy(state["milestones"])
        item = next(
            value
            for value in proposed
            if value["task_id"] == "task-a"
            and value["milestone_id"] == "independent"
        )
        item["state"] = "completed"
        item["validation"] = {
            "focused_green": True,
            "intermediate_valid": True,
        }
        with self.assertRaisesRegex(
            ProjectStateError,
            "integration acceptance",
        ):
            self.store.replace_milestone_state(
                self.anchor,
                expected_generation=state["generation"],
                milestones=proposed,
            )
        self.assertEqual(lane["milestone"], "task-a:independent")

    def test_waiting_lane_rejects_admission_before_recovery_preflight(
        self,
    ) -> None:
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        before = (
            sorted(self.recovery_root.rglob("*"))
            if self.recovery_root.exists()
            else []
        )
        with self.assertRaisesRegex(
            ProjectLaneError,
            "DAG dependencies",
        ):
            self.lanes.create(
                "blocked-lane",
                self.scheduler.lane_milestone("blocked"),
                self.lane_root / "blocked-lane",
                [hard("scripts/consumer.py")],
            )
        after = (
            sorted(self.recovery_root.rglob("*"))
            if self.recovery_root.exists()
            else []
        )
        self.assertEqual(before, after)
        self.assertFalse((self.lane_root / "blocked-lane").exists())

    def test_direct_sink_rejects_every_waiting_scheduler_lane_state(
        self,
    ) -> None:
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        baseline = self.store.read_state(self.anchor)["state"]
        base = subprocess.run(
            ["git", "rev-parse", self.integration_ref],
            cwd=self.checkout,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode("ascii").strip()
        before_recovery = (
            sorted(self.recovery_root.rglob("*"))
            if self.recovery_root.exists()
            else []
        )
        for state_name in (
            "creating",
            "waiting-for-scope",
            "recovery-ready",
        ):
            with self.subTest(state=state_name):
                lane_id = f"forged-{state_name}"
                lane = {
                    "lane_id": lane_id,
                    "milestone": "task-a:blocked",
                    "scheduler_binding": {
                        "schema": "project-scheduler-lane-v1",
                        "task_id": "task-a",
                        "milestone_id": "blocked",
                    },
                    "reader_floor": "2.3.6",
                    "common": baseline["lane_session"]["common"],
                    "base": base,
                    "branch": f"refs/heads/openbuild/lanes/{lane_id}",
                    "worktree": str(self.lane_root / lane_id),
                    "scopes": ["scripts/consumer.py"],
                    "scope_schema": "project-scopes-v1",
                    "scope_requests": [hard("scripts/consumer.py")],
                    "scope_enqueue_sequence": baseline["generation"] + 1,
                    "state": state_name,
                    "writer": None,
                }
                if state_name == "recovery-ready":
                    lane.update(
                        {
                            "reason": "crashed",
                            "terminal_from": "running",
                            "terminal_evidence": "d" * 64,
                            "recovery_checkpoint_digest": "e" * 64,
                        },
                    )
                with self.assertRaisesRegex(
                    ProjectStateError,
                    "cannot admit",
                ):
                    self.store.replace_lane_state(
                        self.anchor,
                        expected_generation=baseline["generation"],
                        lanes=[lane],
                        scopes=baseline["scopes"],
                    )
                current = self.store.read_state(self.anchor)["state"]
                self.assertEqual(
                    current["generation"],
                    baseline["generation"],
                )
                self.assertEqual(current["lanes"], [])
                self.assertFalse((self.lane_root / lane_id).exists())
        after_recovery = (
            sorted(self.recovery_root.rglob("*"))
            if self.recovery_root.exists()
            else []
        )
        self.assertEqual(before_recovery, after_recovery)

    def test_two_real_runner_lifecycles_integrate_before_dag_unblock(
        self,
    ) -> None:
        self.scheduler.publish_plan(ProjectSchedulerM4Tests.plan())
        fake_codex = self.make_fake_codex()

        def assert_dependent_is_still_denied(
            terminal_lane: dict[str, object],
        ) -> None:
            self.assertEqual(
                terminal_lane["state"],
                "waiting-for-integration",
            )
            before_recovery = (
                sorted(self.recovery_root.rglob("*"))
                if self.recovery_root.exists()
                else []
            )
            with self.assertRaisesRegex(
                ProjectLaneError,
                "DAG dependencies",
            ):
                self.lanes.create(
                    "blocked-real-lane",
                    self.scheduler.lane_milestone("blocked"),
                    self.lane_root / "blocked-real-lane",
                    [hard("scripts/consumer.py")],
                )
            with self.assertRaisesRegex(
                ProjectLaneError,
                "does not exist",
            ):
                self.lanes.runner_writer_binding(
                    "blocked-real-lane",
                    self.lane_root,
                    ["scripts/consumer.py"],
                    require_ready=False,
                    lease_kind="recovery-target",
                )
            after_recovery = (
                sorted(self.recovery_root.rglob("*"))
                if self.recovery_root.exists()
                else []
            )
            self.assertEqual(before_recovery, after_recovery)
            midpoint = self.store.read_state(self.anchor)["state"]
            self.assertEqual(
                next(
                    item
                    for item in midpoint["milestones"]
                    if item["task_id"] == "task-a"
                    and item["milestone_id"] == "blocked"
                )["state"],
                "waiting",
            )
            self.assertFalse(
                any(
                    scope.get("owner") == "blocked-real-lane"
                    for scope in midpoint["scopes"]
                ),
            )
            self.assertFalse(
                (self.lane_root / "blocked-real-lane").exists(),
            )

        after_hotspot = self.execute_real_milestone_lifecycle(
            "hotspot",
            "hotspot-real-lane",
            "scripts/owner.py",
            "hotspot integrated\n",
            fake_codex,
            assert_dependent_is_still_denied,
        )
        self.assertIn("blocked", after_hotspot["ready"])
        blocked = self.execute_real_milestone_lifecycle(
            "blocked",
            "blocked-real-lane",
            "scripts/consumer.py",
            "consumer integrated\n",
            fake_codex,
        )
        self.assertIn("blocked", blocked["completed"])
        self.assertEqual(
            (
                Path(
                    str(
                        next(
                            lane
                            for lane in self.store.read_state(self.anchor)[
                                "state"
                            ]["lanes"]
                            if lane["lane_id"] == "hotspot-real-lane"
                        )["worktree"],
                    ),
                )
                / "scripts"
                / "owner.py"
            ).read_text(encoding="utf-8"),
            "hotspot integrated\n",
        )
        self.assertEqual(
            (
                Path(
                    str(
                        next(
                            lane
                            for lane in self.store.read_state(self.anchor)[
                                "state"
                            ]["lanes"]
                            if lane["lane_id"] == "blocked-real-lane"
                        )["worktree"],
                    ),
                )
                / "scripts"
                / "consumer.py"
            ).read_text(encoding="utf-8"),
            "consumer integrated\n",
        )


if __name__ == "__main__":
    unittest.main()
