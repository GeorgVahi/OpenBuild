"""Contract tests for OpenBuild's explicit-model Codex runner."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "plugins" / "openbuild" / "skills" / "build" / "scripts" / "agent_runner.py"
SPEC = importlib.util.spec_from_file_location("openbuild_agent_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load agent runner from {RUNNER_PATH}")
agent_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_runner)


class AgentProfileResolutionTests(unittest.TestCase):
    def write_profile(self, root: Path, filename: str, **overrides: str) -> Path:
        agents = root / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        values = {
            "name": "openbuild_review_strong",
            "description": "Review one bounded OpenBuild diff.",
            "model": "model-from-profile",
            "model_reasoning_effort": "high",
            "sandbox_mode": "read-only",
            "developer_instructions": "Review only. Do not edit or delegate further.",
        }
        values.update(overrides)
        lines = [f'{key} = {json.dumps(value)}' for key, value in values.items()]
        path = agents / filename
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return path

    def test_project_profile_wins_over_user_profile_by_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"
            self.write_profile(user_home, "user.toml", model="user-model")
            self.write_profile(repo / ".codex", "project.toml", model="project-model")

            profile = agent_runner.load_agent_profile(
                "openbuild_review_strong",
                repo=repo,
                codex_home=user_home,
            )

            self.assertEqual(profile.model, "project-model")
            self.assertEqual(profile.reasoning_effort, "high")
            self.assertEqual(profile.sandbox, "read-only")
            self.assertEqual(profile.source, repo / ".codex" / "agents" / "project.toml")

    def test_user_profile_wins_over_packaged_default_by_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"
            source = self.write_profile(user_home, "user.toml", model="user-model")

            profile = agent_runner.load_agent_profile(
                "openbuild_review_strong",
                repo=repo,
                codex_home=user_home,
            )

            self.assertEqual(profile.model, "user-model")
            self.assertEqual(profile.source, source)

    def test_duplicate_exact_profiles_fail_closed_before_packaged_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"
            self.write_profile(user_home, "first.toml")
            self.write_profile(user_home, "second.toml", model="second-model")

            with self.assertRaisesRegex(agent_runner.RunnerError, "ambiguous"):
                agent_runner.load_agent_profile(
                    "openbuild_review_strong",
                    repo=repo,
                    codex_home=user_home,
                )

    def test_packaged_spark_profile_makes_code_discovery_zero_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"

            profile = agent_runner.load_agent_profile(
                "openbuild_search_separate",
                repo=repo,
                codex_home=user_home,
            )

            self.assertEqual(profile.model, "gpt-5.3-codex-spark")
            self.assertEqual(profile.reasoning_effort, "low")
            self.assertEqual(profile.sandbox, "read-only")
            for token in [
                "rg",
                "Get-Content",
                "path:line",
                "snippet/signature",
                "why it matters",
                "targeted",
            ]:
                with self.subTest(token=token):
                    self.assertIn(token, profile.developer_instructions)

    def test_project_search_profile_can_override_model_but_not_search_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / ".codex" / "agents").mkdir(parents=True)
            user_home = root / "codex-home"
            self.write_profile(
                user_home,
                "search.toml",
                name="openbuild_search_separate",
                model="confirmed-user-search-model",
                model_reasoning_effort="minimal",
                developer_instructions=agent_runner.SEARCH_DEVELOPER_INSTRUCTIONS,
            )
            self.write_profile(
                repo / ".codex",
                "search.toml",
                name="openbuild_search_separate",
                model="untrusted-project-search-model",
                model_reasoning_effort="high",
                developer_instructions=agent_runner.SEARCH_DEVELOPER_INSTRUCTIONS,
            )

            profile = agent_runner.load_agent_profile(
                "openbuild_search_separate",
                repo=repo,
                codex_home=user_home,
            )

            self.assertEqual(profile.model, "untrusted-project-search-model")
            self.assertEqual(profile.reasoning_effort, "high")
            self.assertEqual(profile.source, repo / ".codex" / "agents" / "search.toml")

    def test_search_profile_cannot_weaken_the_canonical_discovery_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"
            self.write_profile(
                user_home,
                "search.toml",
                name="openbuild_search_separate",
                model="user-search-model",
                developer_instructions="Search and edit whatever seems useful.",
            )

            with self.assertRaisesRegex(agent_runner.RunnerError, "canonical Explorer contract"):
                agent_runner.load_agent_profile(
                    "openbuild_search_separate",
                    repo=repo,
                    codex_home=user_home,
                )

    def test_every_supported_role_has_a_zero_setup_packaged_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            expected = {
                "openbuild_search_separate": ("gpt-5.3-codex-spark", "low", "read-only"),
                "openbuild_search_balanced": ("gpt-5.6-terra", "medium", "read-only"),
                "openbuild_search_strong": ("gpt-5.6-sol", "high", "read-only"),
                "openbuild_search_strongest": ("gpt-5.6-sol", "xhigh", "read-only"),
                "openbuild_implementation_fast": ("gpt-5.6-terra", "low", "workspace-write"),
                "openbuild_implementation_balanced": ("gpt-5.6-terra", "medium", "workspace-write"),
                "openbuild_implementation_strong": ("gpt-5.6-sol", "high", "workspace-write"),
                "openbuild_implementation_strongest": ("gpt-5.6-sol", "xhigh", "workspace-write"),
                "openbuild_review_fast": ("gpt-5.6-luna", "low", "read-only"),
                "openbuild_review_balanced": ("gpt-5.6-terra", "medium", "read-only"),
                "openbuild_review_strong": ("gpt-5.6-sol", "high", "read-only"),
                "openbuild_review_strongest": ("gpt-5.6-sol", "xhigh", "read-only"),
            }

            self.assertEqual(agent_runner.SUPPORTED_AGENTS, set(expected))
            for agent_name, configured in expected.items():
                profile = agent_runner.load_agent_profile(
                    agent_name,
                    repo=repo,
                    codex_home=root / "codex-home",
                )
                with self.subTest(agent_name=agent_name):
                    self.assertEqual(
                        (profile.model, profile.reasoning_effort, profile.sandbox),
                        configured,
                    )
                    self.assertEqual(
                        profile.source.parent,
                        agent_runner.PACKAGED_PROFILE_DIR.resolve(),
                    )

    def test_deprecated_search_fallback_is_not_supported(self) -> None:
        self.assertNotIn("openbuild_search_fallback", agent_runner.SUPPORTED_AGENTS)

    def test_incomplete_profile_is_rejected_instead_of_inheriting_parent_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"
            self.write_profile(user_home, "incomplete.toml", model_reasoning_effort="")

            with self.assertRaisesRegex(agent_runner.RunnerError, "model_reasoning_effort"):
                agent_runner.load_agent_profile(
                    "openbuild_review_strong",
                    repo=repo,
                    codex_home=user_home,
                )

    def test_role_sandbox_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            user_home = root / "codex-home"
            self.write_profile(user_home, "unsafe-review.toml", sandbox_mode="workspace-write")

            with self.assertRaisesRegex(agent_runner.RunnerError, "read-only"):
                agent_runner.load_agent_profile(
                    "openbuild_review_strong",
                    repo=repo,
                    codex_home=user_home,
                )


class CodexInvocationTests(unittest.TestCase):
    def profile(self) -> object:
        return agent_runner.AgentProfile(
            name="openbuild_implementation_balanced",
            description="Implement one bounded milestone.",
            model="selected-model",
            reasoning_effort="high",
            sandbox="workspace-write",
            developer_instructions="Edit only the leased files.",
            source=Path("profile.toml"),
        )

    def test_command_pins_model_effort_sandbox_jsonl_and_result_file(self) -> None:
        command = agent_runner.build_codex_command(
            codex_bin="codex",
            profile=self.profile(),
            repo=Path("C:/repo"),
            result_file=Path("C:/run/result.md"),
            is_git_repo=True,
        )

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--json", command)
        self.assertEqual(command[command.index("-m") + 1], "selected-model")
        self.assertEqual(
            command[command.index("-c") + 1],
            'model_reasoning_effort="high"',
        )
        config_values = [command[index + 1] for index, value in enumerate(command) if value == "-c"]
        self.assertIn("features.multi_agent=false", config_values)
        self.assertIn('forced_login_method="chatgpt"', config_values)
        self.assertIn('model_provider="openai"', config_values)
        developer_config = next(
            value for value in config_values if value.startswith("developer_instructions=")
        )
        self.assertIn("Do not spawn or delegate to another agent", developer_config)
        self.assertIn("Edit only the leased files", developer_config)
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(command[command.index("-C") + 1], str(Path("C:/repo").resolve()))
        self.assertEqual(command[-1], "-")
        self.assertNotIn("--skip-git-repo-check", command)

    def test_non_git_artifact_run_uses_explicit_repo_check_override(self) -> None:
        command = agent_runner.build_codex_command(
            codex_bin="codex",
            profile=self.profile(),
            repo=Path("C:/artifact"),
            result_file=Path("C:/run/result.md"),
            is_git_repo=False,
        )

        self.assertIn("--skip-git-repo-check", command)

    def test_implementation_requires_a_lease_id_before_start(self) -> None:
        with self.assertRaisesRegex(agent_runner.RunnerError, "--lease-id"):
            agent_runner.validate_lease_id("openbuild_implementation_fast", None)
        self.assertEqual(
            agent_runner.validate_lease_id("openbuild_implementation_fast", "M-001:writer"),
            "M-001:writer",
        )
        with self.assertRaisesRegex(agent_runner.RunnerError, "only for implementation"):
            agent_runner.validate_lease_id("openbuild_review_fast", "M-001"),

    def test_start_rejects_a_preexisting_activation_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            run_dir.mkdir()
            agent_runner.atomic_write_json(run_dir / "activate.json", {"stale": True})

            with self.assertRaisesRegex(agent_runner.RunnerError, "absent or empty"):
                agent_runner.start_run(
                    Namespace(
                        repo=str(repo),
                        prompt_file=str(prompt),
                        agent="openbuild_review_fast",
                        lease_id=None,
                        run_dir=str(run_dir),
                    )
                )

    def test_popen_identity_rejects_a_child_that_exits_during_capture(self) -> None:
        process = mock.Mock(pid=123)
        process.poll.side_effect = [None, 7]
        with mock.patch.object(agent_runner.os, "name", "posix"), mock.patch.object(
            agent_runner, "process_identity", return_value="captured-identity"
        ):
            self.assertIsNone(agent_runner.process_identity_from_popen(process))

    def test_second_resolution_ps_identity_is_never_used_after_procfs_failure(self) -> None:
        with mock.patch.object(agent_runner.os, "name", "posix"), mock.patch.object(
            agent_runner, "procfs_process_start_ticks", return_value=None
        ), mock.patch.object(agent_runner.sys, "platform", "linux"), mock.patch.object(
            agent_runner.subprocess, "run"
        ) as run:
            self.assertIsNone(agent_runner.process_identity(123))

        run.assert_not_called()

    def test_darwin_identity_distinguishes_same_second_pid_reuse(self) -> None:
        with mock.patch.object(agent_runner.os, "name", "posix"), mock.patch.object(
            agent_runner, "procfs_process_start_ticks", return_value=None
        ), mock.patch.object(agent_runner.sys, "platform", "darwin"), mock.patch.object(
            agent_runner,
            "darwin_process_start_time",
            side_effect=[(1_700_000_000, 100), (1_700_000_000, 101)],
        ):
            first = agent_runner.process_identity(123)
            second = agent_runner.process_identity(123)

        self.assertEqual(first, "darwin-starttime:1700000000:100")
        self.assertEqual(second, "darwin-starttime:1700000000:101")
        self.assertNotEqual(first, second)

    def test_start_interrupt_stops_child_and_records_failure_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="interrupt_cleanup",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", return_value=process
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", side_effect=KeyboardInterrupt
            ), mock.patch.object(agent_runner, "terminate_spawned_process") as terminate:
                with self.assertRaises(KeyboardInterrupt):
                    agent_runner.start_run(args)

            terminate.assert_called_once_with(process, process_group=True, grace_seconds=2.0)
            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertFalse(exit_record["success"])
            self.assertFalse(exit_record["process_tree_stopped"])
            self.assertEqual(agent_runner.public_receipt(run_dir)["status"], "running")

    def test_startup_cleanup_never_claims_stopped_without_creation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="unconfirmed_startup_cleanup",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", return_value=process
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", return_value=None
            ), mock.patch.object(agent_runner, "terminate_spawned_process"):
                with self.assertRaisesRegex(
                    agent_runner.RunnerError,
                    "startup cleanup is unconfirmed",
                ):
                    agent_runner.start_run(args)

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertFalse(exit_record["startup_process_stopped"])
            self.assertNotIn("startup process tree stopped", exit_record["failure_message"])

    def test_startup_spawn_attempt_without_codex_identity_is_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="unconfirmed_codex_spawn",
                activation_timeout=300.0,
                codex_bin="codex",
            )

            def spawn_worker(*_args: object, **_kwargs: object) -> object:
                agent_runner.atomic_write_json(
                    run_dir / "codex-spawn.json",
                    {"state": "attempting", "worker_pid": 123},
                )
                return process

            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", side_effect=spawn_worker
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", return_value="worker-created-1"
            ), mock.patch.object(agent_runner, "process_record_state", return_value="stopped"), mock.patch.object(
                agent_runner, "terminate_spawned_process"
            ):
                with self.assertRaisesRegex(agent_runner.RunnerError, "startup cleanup is unconfirmed"):
                    agent_runner.start_run(args)

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertFalse(exit_record["startup_process_stopped"])
            self.assertIsNone(exit_record["exit_code"])
            self.assertEqual(exit_record["codex_exit_evidence"], "missing")
            receipt = agent_runner.public_receipt(run_dir)
            self.assertFalse(receipt["process_tree_stopped"])
            self.assertEqual(receipt["status"], "running")
            self.assertEqual(receipt["codex_process_state"], "unknown")

    def test_start_cleanup_error_does_not_replace_the_original_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="interrupt_cleanup_failure",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", return_value=process
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", side_effect=KeyboardInterrupt
            ), mock.patch.object(
                agent_runner,
                "terminate_spawned_process",
                side_effect=RuntimeError("injected cleanup failure"),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    agent_runner.start_run(args)

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertFalse(exit_record["startup_process_stopped"])
            self.assertIn("injected cleanup failure", exit_record["cleanup_errors"][0])

    def test_start_receipt_error_does_not_replace_the_original_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="interrupt_receipt_failure",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            real_atomic_write_json = agent_runner.atomic_write_json

            def fail_exit_record(path: Path, value: object) -> None:
                if path.name == "exit.json":
                    raise OSError("injected exit record failure")
                real_atomic_write_json(path, value)

            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", return_value=process
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", side_effect=KeyboardInterrupt
            ), mock.patch.object(agent_runner, "terminate_spawned_process"), mock.patch.object(
                agent_runner, "atomic_write_json", side_effect=fail_exit_record
            ):
                with self.assertRaises(KeyboardInterrupt):
                    agent_runner.start_run(args)

            self.assertFalse((run_dir / "exit.json").exists())

    def test_unexpected_worker_record_error_still_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="artifact_cleanup",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            real_atomic_write_json = agent_runner.atomic_write_json

            def fail_worker_record(path: Path, value: object) -> None:
                if path.name == "worker.json":
                    raise RuntimeError("injected worker record failure")
                real_atomic_write_json(path, value)

            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", return_value=process
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", return_value="worker-created-1"
            ), mock.patch.object(agent_runner, "atomic_write_json", side_effect=fail_worker_record), mock.patch.object(
                agent_runner, "terminate_spawned_process"
            ) as terminate, mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                with self.assertRaisesRegex(agent_runner.RunnerError, "injected worker record failure"):
                    agent_runner.start_run(args)

            terminate.assert_called_once_with(process, process_group=True, grace_seconds=2.0)
            self.assertTrue(agent_runner.read_json(run_dir / "exit.json")["process_tree_stopped"])

    def test_start_receipt_output_failure_stops_the_unactivated_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = root / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8", newline="\n")
            run_dir = root / "run"
            process = mock.Mock(pid=123)
            process.poll.return_value = None
            profile = self.profile()._replace(
                name="openbuild_review_fast",
                sandbox="read-only",
            )
            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_review_fast",
                lease_id=None,
                run_dir=str(run_dir),
                task_name="receipt_output_failure",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            ready_receipt = {
                "status": "running",
                "activated": False,
                "codex_process_identity": "codex-created-1",
            }

            def spawn_worker(*_args: object, **_kwargs: object) -> object:
                agent_runner.atomic_write_json(
                    run_dir / "codex.json",
                    {
                        "pid": 222,
                        "identity": "codex-created-1",
                        "process_group_id": 222,
                    },
                )
                return process

            def stop_worker(*_args: object, **_kwargs: object) -> None:
                process.poll.return_value = 0

            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner.subprocess, "Popen", side_effect=spawn_worker
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", return_value="worker-created-1"
            ), mock.patch.object(
                agent_runner, "public_receipt", return_value=ready_receipt
            ), mock.patch.object(
                agent_runner, "terminate_spawned_process", side_effect=stop_worker
            ) as terminate_worker, mock.patch.object(
                agent_runner, "terminate_process_tree"
            ) as terminate_codex, mock.patch.object(
                agent_runner, "process_tree_record_state", return_value="stopped"
            ), mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ), mock.patch(
                "builtins.print", side_effect=BrokenPipeError("output pipe closed")
            ):
                with self.assertRaisesRegex(agent_runner.RunnerError, "output pipe closed"):
                    agent_runner.start_run(args)

            terminate_worker.assert_called_once_with(process, process_group=True, grace_seconds=2.0)
            terminate_codex.assert_called_once()
            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertTrue(exit_record["startup_process_stopped"])
            self.assertIn("output pipe closed", exit_record["failure_message"])

    @unittest.skipUnless(os.name == "nt", "Windows Job Object ordering contract")
    def test_windows_job_exists_before_worker_auth_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            prompt = run_dir / "prompt.md"
            prompt_bytes = b"bounded task\n"
            prompt.write_bytes(prompt_bytes)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {
                        "name": "openbuild_review_fast",
                        "description": "fixture",
                        "model": "fixture-model",
                        "reasoning_effort": "low",
                        "sandbox": "read-only",
                        "developer_instructions": "read only",
                    },
                    "profile_source": "profile.toml",
                    "prompt_file": str(prompt),
                    "prompt_sha256": agent_runner.sha256_bytes(prompt_bytes),
                    "task_name": "job_before_auth",
                    "codex_home": str(run_dir / "codex-home"),
                    "repo": str(run_dir),
                    "command": ["codex"],
                    "activation_timeout": 10.0,
                },
            )
            order: list[str] = []

            def create_job() -> object:
                order.append("job")
                return object()

            def stop_at_auth(*_args: object, **_kwargs: object) -> str:
                order.append("auth")
                raise agent_runner.RunnerError("injected auth stop")

            with mock.patch.object(agent_runner, "await_worker_record"), mock.patch.object(
                agent_runner, "validate_subscription_configuration"
            ), mock.patch.object(
                agent_runner, "create_windows_kill_job", side_effect=create_job
            ), mock.patch.object(
                agent_runner, "require_chatgpt_login", side_effect=stop_at_auth
            ), mock.patch.object(
                agent_runner, "ACTIVE_WINDOWS_JOB", None
            ), mock.patch.object(agent_runner, "spawn_tracked_codex_process") as spawn:
                self.assertEqual(agent_runner.worker_run(run_dir), 1)

            self.assertEqual(order, ["job", "auth"])
            spawn.assert_not_called()

    def test_prompt_is_not_sent_before_explicit_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            process = mock.Mock()
            process.poll.return_value = None
            with mock.patch.object(
                agent_runner.time, "monotonic", side_effect=[0.0, 2.0]
            ), mock.patch.object(agent_runner, "terminate_spawned_process") as terminate:
                with self.assertRaisesRegex(agent_runner.RunnerError, "activation timeout"):
                    agent_runner.communicate_after_activation(
                        process,
                        run_dir=Path(temp),
                        prompt=b"must-not-be-sent",
                        process_identity_value="codex-created-1",
                        timeout=1.0,
                    )

            process.communicate.assert_not_called()
            terminate.assert_called_once_with(process, process_group=True)

    def test_prompt_snapshot_is_hashed_and_decoded_from_one_read(self) -> None:
        path = mock.Mock()
        prompt = "bounded prompt\n".encode()
        path.read_bytes.return_value = prompt

        value = agent_runner.read_prompt_snapshot(path, agent_runner.sha256_bytes(prompt))

        self.assertEqual(value, "bounded prompt\n")
        path.read_bytes.assert_called_once_with()

    def test_api_credentials_are_removed_for_subscription_auth(self) -> None:
        env = agent_runner.scrub_api_credentials(
            {
                "PATH": os.environ.get("PATH", ""),
                "CODEX_API_KEY": "secret-codex-key",
                "OPENAI_API_KEY": "secret-openai-key",
                "OPENAI_BASE_URL": "https://untrusted.invalid",
                "CHATGPT_BASE_URL": "https://untrusted.invalid",
                "UNCHANGED": "value",
            }
        )

        self.assertNotIn("CODEX_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("OPENAI_BASE_URL", env)
        self.assertNotIn("CHATGPT_BASE_URL", env)
        self.assertEqual(env["UNCHANGED"], "value")

    def test_user_provider_redirect_is_rejected_for_subscription_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex_home = Path(temp)
            (codex_home / "config.toml").write_text(
                'model_provider = "openai"\nopenai_base_url = "https://proxy.invalid"\n',
                encoding="utf-8",
                newline="\n",
            )

            with self.assertRaisesRegex(agent_runner.RunnerError, "provider redirect"):
                agent_runner.validate_subscription_configuration(codex_home, codex_home)

    def test_project_nested_openai_provider_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            repo = root / "repo"
            (repo / ".codex").mkdir(parents=True)
            (repo / ".codex" / "config.toml").write_text(
                '[model_providers.openai]\nbase_url = "https://proxy.invalid"\n',
                encoding="utf-8",
                newline="\n",
            )

            with self.assertRaisesRegex(agent_runner.RunnerError, "model_providers.openai"):
                agent_runner.validate_subscription_configuration(codex_home, repo)

    def test_chatgpt_login_status_is_required(self) -> None:
        self.assertEqual(
            agent_runner.classify_login_status(0, "Logged in using ChatGPT", ""),
            "chatgpt",
        )
        with self.assertRaisesRegex(agent_runner.RunnerError, "ChatGPT"):
            agent_runner.classify_login_status(0, "Logged in using an API key", "")

    def test_activation_file_must_match_live_codex_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "activate.json",
                {"codex_pid": 999, "codex_process_identity": "wrong"},
            )
            process = mock.Mock(pid=123)
            process.poll.return_value = None

            with self.assertRaisesRegex(agent_runner.RunnerError, "creation-bound"):
                agent_runner.communicate_after_activation(
                    process,
                    run_dir=run_dir,
                    prompt=b"must-not-run",
                    process_identity_value="codex-created-1",
                    timeout=1.0,
                )

            process.communicate.assert_not_called()

    def test_activate_returns_failure_if_post_write_receipt_failed(self) -> None:
        running = {
            "status": "running",
            "codex_pid": 123,
            "codex_process_identity": "codex-created-1",
        }
        failed = running | {"status": "failed"}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            agent_runner,
            "public_receipt",
            side_effect=[running, failed],
        ), redirect_stdout(io.StringIO()):
            result = agent_runner.activate_run(Namespace(run_dir=temp))

        self.assertEqual(result, 1)

    def test_worker_interrupt_after_popen_records_failure_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            prompt = run_dir / "prompt.md"
            prompt_bytes = b"bounded task\n"
            prompt.write_bytes(prompt_bytes)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {
                        "name": "openbuild_review_fast",
                        "description": "fixture",
                        "model": "fixture-model",
                        "reasoning_effort": "low",
                        "sandbox": "read-only",
                        "developer_instructions": "read only",
                    },
                    "profile_source": "profile.toml",
                    "prompt_file": str(prompt),
                    "prompt_sha256": agent_runner.sha256_bytes(prompt_bytes),
                    "task_name": "worker_interrupt",
                    "codex_home": str(run_dir / "codex-home"),
                    "repo": str(run_dir),
                    "command": ["codex"],
                    "activation_timeout": 10.0,
                },
            )
            with mock.patch.object(agent_runner, "await_worker_record"), mock.patch.object(
                agent_runner, "validate_subscription_configuration"
            ), mock.patch.object(agent_runner, "require_chatgpt_login", return_value="chatgpt"), mock.patch.object(
                agent_runner, "create_windows_kill_job", return_value=object()
            ), mock.patch.object(agent_runner, "ACTIVE_WINDOWS_JOB", None), mock.patch.object(
                agent_runner, "spawn_tracked_codex_process", side_effect=KeyboardInterrupt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    agent_runner.worker_run(run_dir)

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertFalse(exit_record["success"])
            self.assertEqual(exit_record["failure_message"], "KeyboardInterrupt")

    def test_worker_cleanup_error_does_not_replace_the_original_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            prompt = run_dir / "prompt.md"
            prompt_bytes = b"bounded task\n"
            prompt.write_bytes(prompt_bytes)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {
                        "name": "openbuild_review_fast",
                        "description": "fixture",
                        "model": "fixture-model",
                        "reasoning_effort": "low",
                        "sandbox": "read-only",
                        "developer_instructions": "read only",
                    },
                    "profile_source": "profile.toml",
                    "prompt_file": str(prompt),
                    "prompt_sha256": agent_runner.sha256_bytes(prompt_bytes),
                    "task_name": "worker_cleanup_interrupt",
                    "codex_home": str(run_dir / "codex-home"),
                    "repo": str(run_dir),
                    "command": ["codex"],
                    "activation_timeout": 10.0,
                },
            )
            process = mock.Mock(pid=456)
            with mock.patch.object(agent_runner, "await_worker_record"), mock.patch.object(
                agent_runner, "validate_subscription_configuration"
            ), mock.patch.object(agent_runner, "require_chatgpt_login", return_value="chatgpt"), mock.patch.object(
                agent_runner, "create_windows_kill_job", return_value=object()
            ), mock.patch.object(agent_runner, "ACTIVE_WINDOWS_JOB", None), mock.patch.object(
                agent_runner, "ACTIVE_WORKER_CHILD", None
            ), mock.patch.object(
                agent_runner, "spawn_tracked_codex_process", return_value=process
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", side_effect=KeyboardInterrupt
            ), mock.patch.object(
                agent_runner,
                "terminate_spawned_process",
                side_effect=RuntimeError("injected worker cleanup failure"),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    agent_runner.worker_run(run_dir)

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertEqual(exit_record["failure_message"], "KeyboardInterrupt")
            self.assertIn("injected worker cleanup failure", exit_record["cleanup_errors"])

    def test_worker_receipt_error_does_not_replace_the_original_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            prompt = run_dir / "prompt.md"
            prompt_bytes = b"bounded task\n"
            prompt.write_bytes(prompt_bytes)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {
                        "name": "openbuild_review_fast",
                        "description": "fixture",
                        "model": "fixture-model",
                        "reasoning_effort": "low",
                        "sandbox": "read-only",
                        "developer_instructions": "read only",
                    },
                    "profile_source": "profile.toml",
                    "prompt_file": str(prompt),
                    "prompt_sha256": agent_runner.sha256_bytes(prompt_bytes),
                    "task_name": "worker_receipt_interrupt",
                    "codex_home": str(run_dir / "codex-home"),
                    "repo": str(run_dir),
                    "command": ["codex"],
                    "activation_timeout": 10.0,
                },
            )
            real_atomic_write_json = agent_runner.atomic_write_json

            def fail_exit_record(path: Path, value: object) -> None:
                if path.name == "exit.json":
                    raise OSError("injected worker exit record failure")
                real_atomic_write_json(path, value)

            with mock.patch.object(agent_runner, "await_worker_record"), mock.patch.object(
                agent_runner, "validate_subscription_configuration"
            ), mock.patch.object(agent_runner, "require_chatgpt_login", return_value="chatgpt"), mock.patch.object(
                agent_runner, "create_windows_kill_job", return_value=object()
            ), mock.patch.object(agent_runner, "ACTIVE_WINDOWS_JOB", None), mock.patch.object(
                agent_runner, "ACTIVE_WORKER_CHILD", None
            ), mock.patch.object(
                agent_runner, "spawn_tracked_codex_process", side_effect=KeyboardInterrupt
            ), mock.patch.object(agent_runner, "atomic_write_json", side_effect=fail_exit_record):
                with self.assertRaises(KeyboardInterrupt):
                    agent_runner.worker_run(run_dir)

            self.assertFalse((run_dir / "exit.json").exists())


class RunEvidenceTests(unittest.TestCase):
    def write_events(self, path: Path, *events: dict[str, object]) -> None:
        path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
            newline="\n",
        )

    def test_only_turn_completed_is_accepted_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            self.write_events(
                events,
                {"type": "thread.started", "thread_id": "thread-1"},
                {"type": "turn.completed", "usage": {"output_tokens": 42}},
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertEqual(evidence["thread_id"], "thread-1")
            self.assertEqual(evidence["terminal_event"], "turn.completed")
            self.assertTrue(evidence["completed"])

    def test_turn_completed_without_a_nonempty_thread_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            self.write_events(
                events,
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertFalse(evidence["completed"])
            self.assertIn("thread.started", evidence["event_error"])

    def test_turn_failed_is_never_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            self.write_events(
                events,
                {"type": "thread.started", "thread_id": "thread-2"},
                {"type": "turn.failed", "error": {"message": "model unavailable"}},
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertEqual(evidence["terminal_event"], "turn.failed")
            self.assertFalse(evidence["completed"])
            self.assertEqual(
                agent_runner.execution_failure_message(1, evidence),
                "model unavailable",
            )

    def test_turn_completed_must_be_the_last_jsonl_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            self.write_events(
                events,
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
                {"type": "item.completed", "item": {"type": "message"}},
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertFalse(evidence["completed"])
            self.assertIn("last nonblank", evidence["event_error"])

    def test_multiple_terminal_events_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            self.write_events(
                events,
                {"type": "turn.failed", "error": {"message": "first"}},
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertFalse(evidence["completed"])
            self.assertIn("at most one", evidence["event_error"])

    def test_malformed_jsonl_is_reported_as_failed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            events.write_text('{"type":"thread.started"}\nnot-json\n', encoding="utf-8", newline="\n")

            evidence = agent_runner.read_event_evidence(events)

            self.assertFalse(evidence["completed"])
            self.assertIn("line 2", evidence["event_error"])

    def test_receipt_stays_running_while_worker_finalizes_after_codex_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "race_check",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "profile": {
                        "name": "openbuild_review_strong",
                        "model": "selected-model",
                        "reasoning_effort": "high",
                        "sandbox": "read-only",
                    },
                },
            )
            agent_runner.atomic_write_json(run_dir / "worker.json", {"pid": 111})
            agent_runner.atomic_write_json(run_dir / "codex.json", {"pid": 222})
            agent_runner.atomic_write_json(
                run_dir / "exit.json",
                {"success": True, "failure_message": None},
            )
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "thread.started", "thread_id": "thread-exit-evidence"},
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )

            with mock.patch.object(
                agent_runner,
                "process_record_state",
                side_effect=lambda record: "running" if record.get("pid") == 111 else "stopped",
            ):
                receipt = agent_runner.public_receipt(run_dir)

            self.assertEqual(receipt["status"], "running")
            self.assertIsNone(receipt["failure_message"])

    def test_current_identity_checks_recover_from_a_historical_startup_cleanup_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "cleanup_recovery",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "profile": {
                        "name": "openbuild_review_strong",
                        "model": "selected-model",
                        "reasoning_effort": "high",
                        "sandbox": "read-only",
                    },
                },
            )
            agent_runner.atomic_write_json(
                run_dir / "worker.json",
                {"pid": 111, "identity": "worker-created-1"},
            )
            agent_runner.atomic_write_json(
                run_dir / "codex.json",
                {"pid": 222, "identity": "codex-created-1"},
            )
            agent_runner.atomic_write_json(
                run_dir / "exit.json",
                {
                    "success": False,
                    "failure_message": "startup interrupted",
                    "startup_process_stopped": False,
                    "cleanup_errors": ["initial cleanup was inconclusive"],
                },
            )

            with mock.patch.object(agent_runner, "process_record_state", return_value="stopped"):
                receipt = agent_runner.public_receipt(run_dir)

            self.assertTrue(receipt["process_tree_stopped"])
            self.assertEqual(receipt["status"], "failed")

    def test_completed_event_without_final_result_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "missing_result",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "profile": {
                        "name": "openbuild_review_strong",
                        "model": "selected-model",
                        "reasoning_effort": "high",
                        "sandbox": "read-only",
                    },
                },
            )
            agent_runner.atomic_write_json(
                run_dir / "worker.json", {"pid": 111, "identity": "worker-id"}
            )
            agent_runner.atomic_write_json(
                run_dir / "codex.json", {"pid": 222, "identity": "codex-id"}
            )
            agent_runner.atomic_write_json(
                run_dir / "exit.json", {"success": True, "failure_message": None}
            )
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "thread.started", "thread_id": "thread-exit-evidence"},
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )

            with mock.patch.object(agent_runner, "process_record_state", return_value="stopped"):
                receipt = agent_runner.public_receipt(run_dir)

            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["failure_message"], "missing final result artifact")

    def test_completed_receipt_requires_creation_bound_zero_exit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "exit_evidence",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "profile": {
                        "name": "openbuild_review_strong",
                        "model": "selected-model",
                        "reasoning_effort": "high",
                        "sandbox": "read-only",
                    },
                },
            )
            agent_runner.atomic_write_json(
                run_dir / "worker.json", {"pid": 111, "identity": "worker-id"}
            )
            agent_runner.atomic_write_json(
                run_dir / "codex.json", {"pid": 222, "identity": "codex-id"}
            )
            agent_runner.atomic_write_json(
                run_dir / "exit.json", {"success": True, "failure_message": None}
            )
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "thread.started", "thread_id": "thread-bound-exit"},
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )
            (run_dir / "result.md").write_text("done\n", encoding="utf-8", newline="\n")

            with mock.patch.object(agent_runner, "process_record_state", return_value="stopped"):
                missing_exit = agent_runner.public_receipt(run_dir)
                agent_runner.atomic_write_json(
                    run_dir / "codex-exit.json",
                    {"pid": 222, "identity": "codex-id", "exit_code": 0},
                )
                completed = agent_runner.public_receipt(run_dir)

            self.assertEqual(missing_exit["status"], "failed")
            self.assertEqual(missing_exit["codex_exit_evidence"], "missing")
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["codex_exit_evidence"], "valid")
            self.assertEqual(completed["codex_exit_code"], 0)
            self.assertEqual(completed["result_evidence"], "valid")

    @unittest.skipUnless(os.name == "nt", "Windows process-tree contract")
    def test_windows_cancel_targets_an_orphaned_codex_process(self) -> None:
        running = {111: False, 222: True}
        with mock.patch.object(
            agent_runner,
            "process_record_state",
            side_effect=lambda record: "running" if running.get(record.get("pid"), False) else "stopped",
        ), mock.patch.object(agent_runner, "terminate_windows_process_record") as terminate, mock.patch.object(
            agent_runner,
            "_wait_until_stopped",
            return_value=True,
        ):
            agent_runner.terminate_process_tree(
                {"pid": 111, "identity": "old-worker"},
                {"pid": 222, "identity": "live-codex"},
                0.1,
            )

        terminate.assert_called_once_with(
            {"pid": 222, "identity": "live-codex"},
            0.1,
        )

    def test_reused_pid_does_not_resurrect_a_stale_process_record(self) -> None:
        with mock.patch.object(agent_runner, "process_status", return_value="running"), mock.patch.object(
            agent_runner,
            "process_identity",
            return_value="new-process-identity",
        ):
            self.assertFalse(
                agent_runner.process_record_is_running(
                    {"pid": 123, "identity": "old-process-identity"}
                )
            )

    def test_posix_reused_leader_never_targets_the_old_process_group(self) -> None:
        record = {
            "pid": 123,
            "identity": "old-process-identity",
            "process_group_id": 123,
        }
        with mock.patch.object(agent_runner.os, "name", "posix"), mock.patch.object(
            agent_runner, "process_record_state", return_value="reused"
        ), mock.patch.object(agent_runner, "process_group_status", return_value="running") as group_status, mock.patch.object(
            agent_runner.os, "killpg", create=True
        ) as killpg:
            self.assertEqual(agent_runner.process_tree_record_state(record), "stopped")
            agent_runner.terminate_process_tree(record, {}, 0.1)

        group_status.assert_not_called()
        killpg.assert_not_called()

    def test_spawned_process_cleanup_never_signals_after_the_child_was_reaped(self) -> None:
        process = mock.Mock(pid=123)
        process.poll.return_value = 0
        process._openbuild_process_identity = "old-process-identity"
        with mock.patch.object(agent_runner.os, "name", "posix"), mock.patch.object(
            agent_runner, "process_identity_from_popen", return_value="reused-process-identity"
        ) as identity, mock.patch.object(agent_runner.os, "killpg", create=True) as killpg:
            agent_runner.terminate_spawned_process(process, process_group=True, grace_seconds=0.1)

        identity.assert_not_called()
        killpg.assert_not_called()

    def test_spawned_process_cleanup_refuses_a_creation_identity_mismatch(self) -> None:
        process = mock.Mock(pid=123)
        process.poll.return_value = None
        process._openbuild_process_identity = "old-process-identity"
        with mock.patch.object(agent_runner.os, "name", "posix"), mock.patch.object(
            agent_runner,
            "process_identity_from_popen",
            return_value="reused-process-identity",
        ), mock.patch.object(agent_runner.os, "killpg", create=True) as killpg:
            with self.assertRaisesRegex(agent_runner.RunnerError, "identity changed"):
                agent_runner.terminate_spawned_process(process, process_group=True, grace_seconds=0.1)

        killpg.assert_not_called()

    def test_unknown_process_identity_blocks_stopped_confirmation(self) -> None:
        with mock.patch.object(agent_runner, "process_record_state", return_value="unknown"):
            with self.assertRaisesRegex(agent_runner.RunnerError, "liveness"):
                agent_runner.terminate_process_tree(
                    {"pid": 111, "identity": "worker-id"},
                    {},
                    0.1,
                )

    def test_spawned_process_cleanup_forces_a_second_stop_attempt(self) -> None:
        process = mock.Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("worker", 0.1), 0]
        agent_runner.terminate_spawned_process(
            process,
            process_group=True,
            grace_seconds=0.1,
        )

        self.assertEqual(process.wait.call_count, 2)
        if os.name == "nt":
            process.terminate.assert_called_once_with()
            process.kill.assert_called_once_with()

    @unittest.skipIf(os.name == "nt", "POSIX process-group lifecycle")
    def test_posix_group_cleanup_reaps_term_and_kill_zombies(self) -> None:
        scripts = [
            (
                "import time; print('ready', flush=True); time.sleep(60)",
                -signal.SIGTERM,
            ),
            (
                "import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)",
                -signal.SIGKILL,
            ),
        ]
        for script, expected_returncode in scripts:
            with self.subTest(expected_returncode=expected_returncode):
                process = subprocess.Popen(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                try:
                    self.assertEqual(process.stdout.readline().strip(), "ready")
                    identity = agent_runner.process_identity_from_popen(process)
                    self.assertIsNotNone(identity)
                    process._openbuild_process_identity = identity

                    agent_runner.terminate_spawned_process(
                        process,
                        process_group=True,
                        grace_seconds=0.2,
                    )

                    self.assertEqual(process.returncode, expected_returncode)
                    self.assertEqual(agent_runner.process_group_status(process.pid), "stopped")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

    def test_group_liveness_ignores_zombie_only_ps_members(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["ps"],
            returncode=0,
            stdout="123 Z\n123 Z+\n",
            stderr="",
        )
        with mock.patch.object(agent_runner.subprocess, "run", return_value=completed), mock.patch.object(
            agent_runner.os, "killpg", create=True
        ) as killpg:
            self.assertEqual(agent_runner.ps_process_group_status(123), "stopped")

        killpg.assert_not_called()

    def test_worker_signal_handler_stops_an_unpublished_codex_child(self) -> None:
        child = mock.Mock()
        child.poll.return_value = None
        with mock.patch.object(agent_runner, "ACTIVE_WORKER_CHILD", child), mock.patch.object(
            agent_runner, "ACTIVE_WORKER_FINALIZING", False
        ), mock.patch.object(
            agent_runner, "terminate_spawned_process"
        ) as terminate:
            with self.assertRaises(SystemExit):
                agent_runner.worker_termination_handler(signal.SIGTERM, None)

        terminate.assert_called_once_with(child, process_group=True, grace_seconds=2.0)

    def test_worker_signal_handler_preserves_completed_child_finalization(self) -> None:
        child = mock.Mock()
        child.poll.return_value = 0
        with mock.patch.object(agent_runner, "ACTIVE_WORKER_CHILD", child), mock.patch.object(
            agent_runner, "ACTIVE_WORKER_FINALIZING", False
        ), mock.patch.object(agent_runner, "terminate_spawned_process") as terminate:
            agent_runner.worker_termination_handler(signal.SIGTERM, None)

        terminate.assert_not_called()

    def test_worker_signal_handler_preserves_persisted_exit_finalization(self) -> None:
        with mock.patch.object(agent_runner, "ACTIVE_WORKER_CHILD", None), mock.patch.object(
            agent_runner, "ACTIVE_WORKER_FINALIZING", True
        ):
            agent_runner.worker_termination_handler(signal.SIGTERM, None)

    @unittest.skipIf(os.name == "nt", "POSIX signal finalization race")
    def test_real_posix_term_after_child_exit_does_not_abort_worker_finalization(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        child.wait(timeout=5)
        previous = signal.getsignal(signal.SIGTERM)
        try:
            signal.signal(signal.SIGTERM, agent_runner.worker_termination_handler)
            with mock.patch.object(agent_runner, "ACTIVE_WORKER_CHILD", child), mock.patch.object(
                agent_runner, "ACTIVE_WORKER_FINALIZING", False
            ):
                os.kill(os.getpid(), signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_cancel_returns_success_if_run_completed_during_shutdown(self) -> None:
        running = {"status": "running", "worker_pid": 111, "codex_pid": 222}
        completed = {"status": "completed", "worker_pid": 111, "codex_pid": 222}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            agent_runner,
            "public_receipt",
            side_effect=[running, completed],
        ), mock.patch.object(agent_runner, "terminate_process_tree"):
            with redirect_stdout(io.StringIO()):
                result = agent_runner.cancel_run(
                    Namespace(run_dir=temp, grace_seconds=0.1)
                )

        self.assertEqual(result, 0)

    def test_cancel_recovers_valid_completion_before_exit_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "thread.started", "thread_id": "thread-race"},
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )
            (run_dir / "result.md").write_text("done\n", encoding="utf-8", newline="\n")
            agent_runner.atomic_write_json(
                run_dir / "codex-exit.json",
                {
                    "pid": 222,
                    "identity": "codex-id",
                    "exit_code": 0,
                },
            )
            running = {
                "status": "running",
                "worker_pid": 111,
                "worker_process_identity": "worker-id",
                "codex_pid": 222,
                "codex_process_identity": "codex-id",
            }
            failed_after_stop = running | {"status": "failed"}
            completed = running | {"status": "completed"}
            with mock.patch.object(
                agent_runner,
                "public_receipt",
                side_effect=[running, failed_after_stop, completed],
            ), mock.patch.object(agent_runner, "terminate_process_tree"), redirect_stdout(io.StringIO()):
                result = agent_runner.cancel_run(Namespace(run_dir=temp, grace_seconds=0.1))

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertEqual(result, 0)
            self.assertTrue(exit_record["success"])
            self.assertTrue(exit_record["completion_recovered_during_cancel"])

    def test_cancel_rejects_completed_evidence_with_a_nonzero_codex_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "thread.started", "thread_id": "thread-nonzero"},
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )
            (run_dir / "result.md").write_text("done\n", encoding="utf-8", newline="\n")
            agent_runner.atomic_write_json(
                run_dir / "codex-exit.json",
                {
                    "pid": 222,
                    "identity": "codex-id",
                    "exit_code": 7,
                },
            )
            running = {
                "status": "running",
                "worker_pid": 111,
                "worker_process_identity": "worker-id",
                "codex_pid": 222,
                "codex_process_identity": "codex-id",
            }
            failed_after_stop = running | {"status": "failed"}
            with mock.patch.object(
                agent_runner,
                "public_receipt",
                side_effect=[running, failed_after_stop, failed_after_stop],
            ), mock.patch.object(agent_runner, "terminate_process_tree"), redirect_stdout(io.StringIO()):
                result = agent_runner.cancel_run(Namespace(run_dir=temp, grace_seconds=0.1))

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertEqual(result, 1)
            self.assertFalse(exit_record["success"])
            self.assertEqual(exit_record["exit_code"], 7)
            self.assertEqual(exit_record["failure_message"], "codex exec exited with code 7")
            self.assertNotIn("completion_recovered_during_cancel", exit_record)

    def test_cancel_records_unknown_exit_without_a_creation_bound_artifact(self) -> None:
        running = {
            "status": "running",
            "worker_pid": 111,
            "worker_process_identity": "worker-id",
            "codex_pid": 222,
            "codex_process_identity": "codex-id",
            "codex_started": True,
        }
        failed = running | {"status": "failed"}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            agent_runner,
            "public_receipt",
            side_effect=[running, failed, failed],
        ), mock.patch.object(agent_runner, "terminate_process_tree"), redirect_stdout(io.StringIO()):
            run_dir = Path(temp)
            result = agent_runner.cancel_run(Namespace(run_dir=temp, grace_seconds=0.1))

            exit_record = agent_runner.read_json(run_dir / "exit.json")
            self.assertEqual(result, 1)
            self.assertIsNone(exit_record["exit_code"])
            self.assertEqual(exit_record["codex_exit_evidence"], "missing")

    def test_codex_exit_evidence_rejects_missing_malformed_and_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            exit_code, error = agent_runner.codex_exit_evidence(
                run_dir,
                expected_pid=222,
                expected_identity="codex-id",
            )
            self.assertIsNone(exit_code)
            self.assertIn("missing", error)

            (run_dir / "codex-exit.json").write_text("not-json\n", encoding="utf-8", newline="\n")
            exit_code, error = agent_runner.codex_exit_evidence(
                run_dir,
                expected_pid=222,
                expected_identity="codex-id",
            )
            self.assertIsNone(exit_code)
            self.assertIn("invalid creation-bound", error)

            agent_runner.atomic_write_json(
                run_dir / "codex-exit.json",
                {"pid": 222, "identity": "different-codex", "exit_code": 0},
            )
            exit_code, error = agent_runner.codex_exit_evidence(
                run_dir,
                expected_pid=222,
                expected_identity="codex-id",
            )
            self.assertIsNone(exit_code)
            self.assertIn("does not match", error)

    def test_cancel_never_overwrites_an_existing_failed_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )
            (run_dir / "result.md").write_text("done\n", encoding="utf-8", newline="\n")
            original_exit = {
                "success": False,
                "exit_code": 7,
                "failure_message": "real CLI failure",
            }
            agent_runner.atomic_write_json(run_dir / "exit.json", original_exit)
            running = {
                "status": "running",
                "worker_pid": 111,
                "worker_process_identity": "worker-id",
                "codex_pid": 222,
                "codex_process_identity": "codex-id",
            }
            failed = running | {"status": "failed"}
            with mock.patch.object(
                agent_runner,
                "public_receipt",
                side_effect=[running, failed, failed],
            ), mock.patch.object(agent_runner, "terminate_process_tree"), redirect_stdout(io.StringIO()):
                result = agent_runner.cancel_run(Namespace(run_dir=temp, grace_seconds=0.1))

            self.assertEqual(result, 1)
            self.assertEqual(agent_runner.read_json(run_dir / "exit.json"), original_exit)

    @unittest.skipIf(os.name == "nt", "POSIX permission contract")
    def test_run_artifacts_are_private_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_json(run_dir / "receipt.json", {"ok": True})

            self.assertEqual(run_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual((run_dir / "receipt.json").stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "nt", "Windows DACL contract")
    def test_new_windows_run_directory_has_a_protected_current_user_dacl(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "secure-run"
            agent_runner.ensure_private_run_dir(run_dir)
            user_sid = agent_runner.windows_current_user_sid()

            self.assertTrue(agent_runner.windows_directory_is_private(run_dir, user_sid))

    @unittest.skipUnless(os.name == "nt", "Windows DACL contract")
    def test_existing_windows_run_directory_with_inherited_acl_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "weak-run"
            run_dir.mkdir()

            with self.assertRaisesRegex(agent_runner.RunnerError, "current-user-only DACL"):
                agent_runner.ensure_private_run_dir(run_dir)


if __name__ == "__main__":
    unittest.main()
