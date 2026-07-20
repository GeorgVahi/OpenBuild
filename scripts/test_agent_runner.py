"""Contract tests for OpenBuild's explicit-model Codex runner."""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "plugins" / "openbuild" / "skills" / "build" / "scripts" / "agent_runner.py"
SPEC = importlib.util.spec_from_file_location("openbuild_agent_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load agent runner from {RUNNER_PATH}")
agent_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_runner)


def _attempt_linux_cgroup_migration(targets: dict[str, str]) -> dict[str, bool]:
    denied: dict[str, bool] = {}
    for name, path in targets.items():
        try:
            descriptor = os.open(path, os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
            try:
                os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            finally:
                os.close(descriptor)
        except OSError:
            denied[name] = True
        else:
            denied[name] = False
    return denied


def _containment_plan(
    *,
    guardian_id: str = "guardian-1",
    provider_plan_id: str = "provider-plan",
    ipc_plan_id: str = "ipc-plan",
) -> dict[str, object]:
    return {
        "guardian_id": guardian_id,
        "provider_plan_id": provider_plan_id,
        "ipc_plan_id": ipc_plan_id,
        "contained_launch_token": "contained-token",
        "fallback_token": "fallback-token",
        "recovery_target": False,
    }


def _process_receipt(
    *, pid: int = 123, identity: str = "worker-1"
) -> dict[str, object]:
    return {
        "pid": pid,
        "identity": identity,
        "process_group_id": pid,
        "started_at": "2026-07-15T00:00:00Z",
    }


def _provider_receipt(
    *,
    guardian_id: str = "guardian-1",
    provider_plan_id: str = "provider-plan",
    ipc_plan_id: str = "ipc-plan",
    worker: dict[str, object] | None = None,
    precommit_nonce: str = "precommit-1",
) -> dict[str, object]:
    process = worker or _process_receipt()
    return {
        "guardian_id": guardian_id,
        "guardian_pid": 999,
        "guardian_identity": "guardian-created-1",
        "provider": "windows-job",
        "provider_plan_id": provider_plan_id,
        "ipc_plan_id": ipc_plan_id,
        "policy": "kill-on-close-no-breakaway",
        "active_processes": 1,
        "anti_migration": None,
        "precommit": {
            "guardian_id": guardian_id,
            "guardian_pid": 999,
            "guardian_identity": "guardian-created-1",
            "worker_pid": process["pid"],
            "worker_identity": process["identity"],
            "provider": "windows-job",
            "provider_plan_id": provider_plan_id,
            "ipc_plan_id": ipc_plan_id,
            "provider_populated": True,
            "membership_verified": True,
            "precommit_nonce": precommit_nonce,
            "attested_at": "2026-07-15T00:00:01Z",
        },
    }


def _zero_proof(
    *,
    guardian_id: str = "guardian-1",
    provider: str = "windows-job",
    worker_pid: int = 123,
    worker_identity: str = "worker-1",
) -> dict[str, object]:
    return {
        "guardian_id": guardian_id,
        "provider": provider,
        "populated": False,
        "identity_verified": True,
        "worker_pid": worker_pid,
        "worker_identity": worker_identity,
        "proved_at": "2026-07-15T00:00:02Z",
    }


def _guardian_close(*, guardian_id: str = "guardian-1") -> dict[str, object]:
    return {
        "guardian_id": guardian_id,
        "closed": True,
        "closed_at": "2026-07-15T00:00:03Z",
    }


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
        rung_by_name = agent_runner.ROUTING_RUNG_BY_AGENT
        if values["name"] in rung_by_name:
            values["routing_rung"] = rung_by_name[values["name"]]
            values["routing_tuple_confirmed"] = True
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


class SearchAvailabilityFallbackTests(unittest.TestCase):
    write_profile = AgentProfileResolutionTests.write_profile

    def test_structured_classifier_accepts_only_exact_model_bound_vocabulary(self) -> None:
        spark = "gpt-5.3-codex-spark"
        positives = (
            (
                {"type": "error", "error": {"code": "model_not_found", "model": spark}},
                "model-unavailable",
            ),
            (
                {
                    "type": "turn.failed",
                    "error": {
                        "type": "usage_limit_exceeded",
                        "rate_limits": {"limit_name": spark},
                    },
                },
                "quota-exhausted",
            ),
            (
                {
                    "type": "error",
                    "error": {
                        "type": "usage_limit_exceeded",
                        "model": spark,
                        "rate_limits": {"limit_name": spark},
                    },
                },
                "quota-exhausted",
            ),
        )
        for value, expected in positives:
            with self.subTest(expected=expected):
                self.assertEqual(
                    agent_runner.classify_search_availability_failure(
                        [value], exact_model=spark
                    ),
                    expected,
                )

        negatives = (
            {"type": "error", "message": f"model_not_found: {spark}"},
            {"type": "usage_limit_exceeded", "model": "gpt-5.6-terra"},
            {"type": "usage_limit_exceeded", "model": spark},
            {"type": "usage_limit_exceeded"},
            {"code": "rate_limit_exceeded", "model": spark},
            {"code": "network_unavailable", "model": spark},
            {
                "type": "usage_limit_exceeded",
                "rate_limits": {"limit_name": "workspace_member_usage_limit_reached"},
            },
            {
                "type": "usage_limit_exceeded",
                "model": "gpt-5.6-terra",
                "rate_limits": {"limit_name": spark},
            },
            {"type": "usage_limit_exceeded", "rate_limits": spark},
        )
        for value in negatives:
            with self.subTest(value=value):
                self.assertIsNone(
                    agent_runner.classify_search_availability_failure(
                        [value], exact_model=spark
                    )
                )

    def test_structured_classifier_rejects_mixed_or_conflicting_failures(self) -> None:
        spark = "gpt-5.3-codex-spark"
        eligible_model = {
            "type": "error",
            "error": {"code": "model_not_found", "model": spark},
        }
        eligible_quota = {
            "type": "turn.failed",
            "error": {
                "type": "usage_limit_exceeded",
                "rate_limits": {"limit_name": spark},
            },
        }
        conflicts = (
            {"type": "error", "error": {"code": "authentication_failed"}},
            {"type": "error", "error": {"code": "network_error"}},
            {"type": "error", "error": {"code": "unknown_failure"}},
            eligible_quota,
        )
        for conflict in conflicts:
            with self.subTest(conflict=conflict):
                self.assertIsNone(
                    agent_runner.classify_search_availability_failure(
                        [eligible_model, conflict], exact_model=spark
                    )
                )
        for conflict in (
            {
                "code": "model_not_found",
                "type": "authentication_error",
                "model": spark,
            },
            {
                "code": "usage_limit_exceeded",
                "type": "model_not_found",
                "model": spark,
                "rate_limits": {"limit_name": spark},
            },
        ):
            with self.subTest(same_payload_conflict=conflict):
                self.assertIsNone(
                    agent_runner.classify_search_availability_failure(
                        [conflict], exact_model=spark
                    )
                )

    def test_search_profiles_share_runtime_instruction_digest(self) -> None:
        fingerprint = {
            "algorithm": "sha256",
            "digest": "a" * 64,
            "files": 2,
            "bytes": 12,
            "inventory": "git-tracked-untracked-nonignored-v1",
        }
        source = agent_runner.AgentProfile(
            name="openbuild_search_separate",
            description="source",
            model="gpt-5.3-codex-spark",
            reasoning_effort="low",
            sandbox="read-only",
            developer_instructions=agent_runner.SEARCH_DEVELOPER_INSTRUCTIONS,
            source=ROOT
            / "plugins"
            / "openbuild"
            / "skills"
            / "build"
            / "profiles"
            / "openbuild_search_separate.toml",
        )
        target = source._replace(
            name="openbuild_search_balanced",
            model="gpt-5.6-terra",
            reasoning_effort="medium",
            source=source.source.with_name("openbuild_search_balanced.toml"),
        )
        source = agent_runner.discovery_profile_with_fingerprint(source, fingerprint)
        target = agent_runner.discovery_profile_with_fingerprint(target, fingerprint)
        source_descriptor = agent_runner.profile_descriptor(source)
        target_descriptor = agent_runner.profile_descriptor(target)
        self.assertEqual(
            source_descriptor["descriptor"]["instructions_sha256"],
            target_descriptor["descriptor"]["instructions_sha256"],
        )
        self.assertNotEqual(source_descriptor["sha256"], target_descriptor["sha256"])

    def test_search_fallback_claim_is_atomic_and_one_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            claim = Path(temp) / "claim.json"
            agent_runner._create_private_claim(claim, {"schema": "claim-v1"})
            self.assertEqual(json.loads(claim.read_text(encoding="utf-8"))["schema"], "claim-v1")
            with self.assertRaisesRegex(agent_runner.RunnerError, "already claimed"):
                agent_runner._create_private_claim(claim, {"schema": "claim-v1"})

    def test_search_fallback_claim_uses_durable_exclusive_owner_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            claim = Path(temp) / "claim.json"
            value = {"schema": "claim-v1"}
            with mock.patch.object(agent_runner, "durable_create_private_json") as create:
                agent_runner._create_private_claim(claim, value)
            create.assert_called_once_with(claim, value)

    def test_search_fallback_claim_after_metadata_barrier_is_durably_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            claim = Path(temp) / "claim.json"
            value = {"schema": "claim-v1"}
            with self.assertRaisesRegex(
                agent_runner.RunnerError,
                "after private claim metadata barrier",
            ):
                agent_runner.durable_create_private_json(
                    claim,
                    value,
                    fault="after-metadata-barrier",
                )
            self.assertEqual(json.loads(claim.read_text(encoding="utf-8")), value)
            with self.assertRaises(FileExistsError):
                agent_runner.durable_create_private_json(claim, value)

    def test_search_fallback_claim_blocks_replay_after_target_durable_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_claim = root / "source" / "search-fallback-claim.json"
            source_claim.parent.mkdir()
            value = {
                "schema": "openbuild-search-fallback-claim-v1",
                "target_run_handle": "20260719T000001Z-0123456789",
            }
            agent_runner._create_private_claim(source_claim, value)
            target = root / "target"
            agent_runner.ensure_private_run_dir(target)
            for durable_record in ("request.json", "worker.json"):
                agent_runner.durable_write_private_json(
                    target / durable_record,
                    {"schema": durable_record, "source_claim": value},
                )
                with self.subTest(durable_record=durable_record), self.assertRaisesRegex(
                    agent_runner.RunnerError, "already claimed"
                ):
                    agent_runner._create_private_claim(source_claim, value)

    def test_availability_requires_a_coherent_pre_turn_failure_stream(self) -> None:
        base = {
            "completed": False,
            "event_error": None,
            "terminal_event": "turn.failed",
            "turn_started": False,
        }
        clean_exit = {
            "success": False,
            "terminal_event": "turn.failed",
            "exit_code": 1,
            "failure_message": "codex exec exited with code 1",
            "cleanup_errors": [],
        }
        self.assertTrue(
            agent_runner.search_availability_event_stream_is_eligible(
                base,
                exit_record=clean_exit,
                codex_exit_status="valid",
                codex_exit_code=1,
            )
        )
        for mutation in (
            {"event_error": "invalid JSONL"},
            {"terminal_event": "turn.completed"},
            {"completed": True},
            {"turn_started": True},
            {"structured_stderr_valid": False},
        ):
            with self.subTest(mutation=mutation):
                self.assertFalse(
                    agent_runner.search_availability_event_stream_is_eligible(
                        {**base, **mutation},
                        exit_record=clean_exit,
                        codex_exit_status="valid",
                        codex_exit_code=1,
                    )
                )

        for exit_record, result_status, codex_exit_status, codex_exit_code in (
            ({**clean_exit, "cancelled": True}, "missing", "valid", 1),
            (
                {**clean_exit, "failure_message": "activation timed out after 300 seconds"},
                "missing",
                "valid",
                1,
            ),
            ({**clean_exit, "cleanup_errors": ["runner cleanup failed"]}, "missing", "valid", 1),
            ({**clean_exit, "failure_message": "runner cleanup failed"}, "missing", "valid", 1),
            (
                {
                    **clean_exit,
                    "exit_code": 0,
                    "failure_message": "codex exec exited with code 0",
                },
                "missing",
                "valid",
                0,
            ),
            (clean_exit, "missing", "missing", None),
            (clean_exit, "missing", "invalid", None),
            (None, "missing", "valid", 1),
            (clean_exit, "valid", "valid", 1),
            (clean_exit, "empty", "valid", 1),
            (clean_exit, "invalid", "valid", 1),
        ):
            with self.subTest(
                exit_record=exit_record,
                result_status=result_status,
                codex_exit_status=codex_exit_status,
            ):
                self.assertFalse(
                    agent_runner.search_availability_event_stream_is_eligible(
                        base,
                        exit_record=exit_record,
                        result_status=result_status,
                        codex_exit_status=codex_exit_status,
                        codex_exit_code=codex_exit_code,
                    )
                )

    def test_search_fallback_authorization_binds_source_route_profiles_and_prompt(self) -> None:
        source_handle = f"20260719T000000Z-{os.urandom(5).hex()}"
        target_handle = f"20260719T000001Z-{os.urandom(5).hex()}"
        source_dir = agent_runner.default_run_root() / source_handle
        source_dir.mkdir(parents=True)
        try:
            fingerprint = {
                "algorithm": "sha256",
                "digest": "a" * 64,
                "files": 2,
                "bytes": 12,
                "inventory": "git-tracked-untracked-nonignored-v1",
            }
            source_static = agent_runner.load_agent_profile(
                "openbuild_search_separate", repo=ROOT, codex_home=Path(tempfile.gettempdir())
            )
            target_static = agent_runner.load_agent_profile(
                "openbuild_search_balanced", repo=ROOT, codex_home=Path(tempfile.gettempdir())
            )
            source = agent_runner.discovery_profile_with_fingerprint(source_static, fingerprint)
            target = agent_runner.discovery_profile_with_fingerprint(target_static, fingerprint)
            source_descriptor = agent_runner.profile_descriptor(source)
            request = {
                "repo": str(ROOT),
                "task_name": "discover-owner",
                "search_fallback_source": None,
                "prompt_snapshot_id": "b" * 64,
                "prompt_sha256": "c" * 64,
                "discovery_fingerprint": fingerprint,
                "profile_descriptor_sha256": source_descriptor["sha256"],
                "profile": {
                    "name": source.name,
                    "model": source.model,
                    "reasoning_effort": source.reasoning_effort,
                    "sandbox": source.sandbox,
                },
            }
            (source_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
            receipt = {
                "run_handle": source_handle,
                "status": "failed",
                "agent_name": source.name,
                "configured_model": source.model,
                "terminal_event": "turn.failed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 1,
                "result_evidence": "missing",
                "cancelled": False,
                "completion_recovered_during_cancel": False,
                "process_tree_stopped": True,
                "codex_started": True,
                "transport_failure_reason": "model-unavailable",
                "prompt_sha256": "c" * 64,
            }
            route = {
                "map_sha256": "d" * 64,
                "map_scope": "packaged",
                "transport_failure": "availability-fallback",
                "fallback": "targeted-root",
                "availability_fallback_agent": "openbuild_search_balanced",
                "availability_fallback_triggers": ["model-unavailable", "quota-exhausted"],
                "agents": [{"name": "openbuild_search_separate"}],
            }
            request["discovery_route_binding"] = agent_runner._discovery_route_binding(
                route,
                repo=ROOT,
                codex_home=Path(tempfile.gettempdir()),
                fingerprint=fingerprint,
            )
            (source_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
            current = mock.Mock(public=fingerprint)
            fake_map = mock.Mock()
            fake_map.resolve_model_route.return_value = route
            with (
                mock.patch.object(agent_runner, "public_receipt", return_value=receipt),
                mock.patch.object(
                    agent_runner, "compute_worktree_fingerprint", return_value=current
                ),
                mock.patch.object(
                    agent_runner,
                    "load_agent_profile",
                    side_effect=lambda name, **_kwargs: (
                        source_static
                        if name == "openbuild_search_separate"
                        else target_static
                    ),
                ) as load_profile,
                mock.patch.dict(sys.modules, {"model_map": fake_map}),
            ):
                request["search_fallback_binding"] = {"reason": "model-unavailable"}
                (source_dir / "request.json").write_text(
                    json.dumps(request), encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    agent_runner.RunnerError, "must not carry a fallback binding"
                ):
                    agent_runner.prepare_search_fallback_claim(
                        source_reference=source_handle,
                        expected_map_sha256="d" * 64,
                        repo=ROOT,
                        codex_home=Path(tempfile.gettempdir()),
                        target_profile=target,
                        task_name="discover-owner",
                        target_run_dir=agent_runner.default_run_root() / target_handle,
                    )
                request["search_fallback_binding"] = None
                (source_dir / "request.json").write_text(
                    json.dumps(request), encoding="utf-8"
                )
                fake_map.resolve_model_route.return_value = {**route, "map_sha256": "e" * 64}
                with self.assertRaisesRegex(agent_runner.RunnerError, "map binding drifted"):
                    agent_runner.prepare_search_fallback_claim(
                        source_reference=source_handle,
                        expected_map_sha256="d" * 64,
                        repo=ROOT,
                        codex_home=Path(tempfile.gettempdir()),
                        target_profile=target,
                        task_name="discover-owner",
                        target_run_dir=agent_runner.default_run_root() / target_handle,
                    )
                fake_map.resolve_model_route.return_value = route
                drifted_target = target_static._replace(
                    source=target_static.source.with_name("shadowed-search-balanced.toml")
                )
                load_profile.side_effect = lambda name, **_kwargs: (
                    source_static
                    if name == "openbuild_search_separate"
                    else drifted_target
                )
                with self.assertRaisesRegex(agent_runner.RunnerError, "map binding drifted"):
                    agent_runner.prepare_search_fallback_claim(
                        source_reference=source_handle,
                        expected_map_sha256="d" * 64,
                        repo=ROOT,
                        codex_home=Path(tempfile.gettempdir()),
                        target_profile=target,
                        task_name="discover-owner",
                        target_run_dir=agent_runner.default_run_root() / target_handle,
                    )
                load_profile.side_effect = lambda name, **_kwargs: (
                    source_static
                    if name == "openbuild_search_separate"
                    else target_static
                )
                binding = agent_runner.prepare_search_fallback_claim(
                    source_reference=source_handle,
                    expected_map_sha256="d" * 64,
                    repo=ROOT,
                    codex_home=Path(tempfile.gettempdir()),
                    target_profile=target,
                    task_name="discover-owner",
                    target_run_dir=agent_runner.default_run_root() / target_handle,
                )
                self.assertEqual(binding["reason"], "model-unavailable")
                self.assertEqual(binding["prompt_sha256"], "c" * 64)
                with self.assertRaisesRegex(agent_runner.RunnerError, "already claimed"):
                    agent_runner.prepare_search_fallback_claim(
                        source_reference=source_handle,
                        expected_map_sha256="d" * 64,
                        repo=ROOT,
                        codex_home=Path(tempfile.gettempdir()),
                        target_profile=target,
                        task_name="discover-owner",
                        target_run_dir=agent_runner.default_run_root() / target_handle,
                    )
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)

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
                "openbuild.discovery.v1",
                "worktree_fingerprint",
                "line_start",
                "owners",
                "tests",
                "flat arrays",
                "arrays of bounded strings",
                "line_end - line_start + 1",
                "never combine distant symbols",
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
                "openbuild_implementation_fast": ("gpt-5.6-luna", "medium", "workspace-write"),
                "openbuild_implementation_balanced": ("gpt-5.6-terra", "medium", "workspace-write"),
                "openbuild_implementation_luna_xhigh": ("gpt-5.6-luna", "xhigh", "workspace-write"),
                "openbuild_implementation_strong": ("gpt-5.6-terra", "xhigh", "workspace-write"),
                "openbuild_implementation_sol_high": ("gpt-5.6-sol", "high", "workspace-write"),
                "openbuild_implementation_strongest": ("gpt-5.6-sol", "xhigh", "workspace-write"),
                "openbuild_review_fast": ("gpt-5.6-luna", "medium", "read-only"),
                "openbuild_review_balanced": ("gpt-5.6-terra", "medium", "read-only"),
                "openbuild_review_luna_xhigh": ("gpt-5.6-luna", "xhigh", "read-only"),
                "openbuild_review_strong": ("gpt-5.6-terra", "xhigh", "read-only"),
                "openbuild_review_sol_high": ("gpt-5.6-sol", "high", "read-only"),
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
    def private_run_request_identity(self, run_dir: Path) -> dict[str, object]:
        agent_runner.atomic_write_bytes(run_dir / "prompt.md", b"fixture\n")
        return {
            "prompt_file": str(run_dir / "prompt.md"),
            "command": ["codex", "-o", str(run_dir / "result.md")],
        }

    def test_m1_legacy_run_dir_terminal_binding_reloads_without_path_leak(self) -> None:
        """A 2.2.1 receipt hashed ``str(run_dir.resolve())``, not the run ID."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            (repo / "allowed.txt").write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)

            run_dir = root / "legacy-run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id=run_dir.name,
                source_lease_id="legacy-lease",
                source_milestone="M1",
                target_milestone="M1-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-007",
            )
            owner.reserve_normal(
                "legacy-lease",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id=run_dir.name,
                prompt_sha256="a" * 64,
                containment_plan=_containment_plan(),
            )
            owner.bind_reserved_source_snapshot("legacy-lease", preflight)
            owner.claim_contained_launch("legacy-lease", "contained-token")
            owner.bind_process_unactivated(
                "legacy-lease",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=_provider_receipt(),
                process_receipt=_process_receipt(),
            )
            owner.commit_activation("legacy-lease", preflight["allowed_set_digest"])
            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_bytes(run_dir / "prompt.md", b"fixture\n")
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_strong"},
                    "repo": str(repo),
                    "lease_id": "legacy-lease",
                    "prompt_file": str(run_dir / "prompt.md"),
                    "command": ["codex", "-o", str(run_dir / "result.md")],
                    "lifecycle_allowed_set_digest": preflight["allowed_set_digest"],
                    "recovery_preflight": preflight,
                },
            )
            secret = bytes.fromhex("55" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-zero.json", secret, "guardian-zero", _zero_proof()
            )
            receipt = {
                "status": "completed",
                "agent_name": "openbuild_implementation_strong",
                "task_name": "M1",
                "lease_id": "legacy-lease",
                "activated": True,
                "configured_model": "fixture",
                "model_reasoning_effort": "high",
                "sandbox": "workspace-write",
                "worker_pid": 123,
                "worker_process_identity": "worker-1",
                "codex_pid": 456,
                "codex_process_identity": "codex-1",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
                "process_tree_stopped": True,
            }
            legacy = agent_runner._terminal_binding_candidate(
                receipt, run_dir=run_dir, run_id=run_dir.name, format="run-dir-v1"
            )
            owner.record_terminal_evidence(
                "legacy-lease",
                {
                    "success": True,
                    "binding_digest": agent_runner.sha256_bytes(
                        agent_runner._canonical_json_bytes(legacy["payload"])
                    ),
                    "terminal_event": "turn.completed",
                },
                preflight["allowed_set_digest"],
            )

            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ):
                agent_runner.reconcile_implementation_registry(run_dir, receipt)

            state = owner.state()
            self.assertEqual(state["lease"]["state"], "stopped-terminal")
            stored = state["lease"]["terminal_receipt"]
            self.assertNotIn("binding_format", stored)  # no rewrite-on-read
            self.assertNotIn(str(run_dir.resolve()), json.dumps(stored, sort_keys=True))
            self.assertEqual(
                agent_runner._require_legacy_post_commit_binding(run_dir, receipt, owner),
                stored["binding_digest"],
            )

            current = agent_runner._terminal_binding_candidate(
                receipt, run_dir=run_dir, run_id=run_dir.name, format="run-id-v2"
            )
            current_digest = agent_runner.sha256_bytes(
                agent_runner._canonical_json_bytes(current["payload"])
            )
            self.assertEqual(
                agent_runner._match_terminal_binding(
                    receipt,
                    run_dir=run_dir,
                    run_id=run_dir.name,
                    stored_digest=current_digest,
                )["format"],
                "run-id-v2",
            )
            copied_run_dir = root / "copied-parent" / run_dir.name
            copied_run_dir.parent.mkdir()
            shutil.copytree(run_dir, copied_run_dir)
            with self.assertRaisesRegex(
                agent_runner.RunnerError, "private run path identity drifted"
            ):
                agent_runner._match_terminal_binding(
                    receipt,
                    run_dir=copied_run_dir,
                    run_id=run_dir.name,
                    stored_digest=current_digest,
                )
            with self.assertRaisesRegex(agent_runner.RunnerError, "digest is malformed"):
                agent_runner._match_terminal_binding(
                    receipt,
                    run_dir=run_dir,
                    run_id=run_dir.name,
                    stored_digest="not-a-digest",
                )
            with mock.patch.object(
                agent_runner,
                "_terminal_binding_candidates",
                return_value=(current, current),
            ):
                with self.assertRaisesRegex(
                    agent_runner.RunnerError, "binding drifted during reload"
                ):
                    agent_runner._match_terminal_binding(
                        receipt,
                        run_dir=run_dir,
                        run_id=run_dir.name,
                        stored_digest=current_digest,
                    )
            current_registry = mock.Mock()
            current_registry.state.return_value = {
                "lease": {
                    "lease_kind": "normal",
                    "run_id": run_dir.name,
                    "terminal_receipt": {
                        "binding_digest": current_digest
                    },
                }
            }
            with self.assertRaisesRegex(
                agent_runner.RecoveryStateError, "legacy terminal binding"
            ):
                agent_runner._require_legacy_post_commit_binding(
                    run_dir, receipt, current_registry
                )

    def test_m1_post_commit_scope_uses_stable_private_import_without_generic_reconcile(self) -> None:
        repo = Path("repo").resolve()
        scope_path = Path("private-scope.json")
        expected = {"schema": "remediation-scope-v1", "digest": "a" * 64}
        with mock.patch.object(
            agent_runner,
            "_read_stable_external_prompt",
            return_value=json.dumps(expected).encode("utf-8"),
        ) as stable_read:
            self.assertEqual(
                agent_runner._read_private_remediation_scope(repo, str(scope_path)),
                expected,
            )
        stable_read.assert_called_once_with(repo, scope_path)

        with mock.patch.object(
            agent_runner, "_read_stable_external_prompt", return_value=b"[]"
        ):
            with self.assertRaisesRegex(
                agent_runner.RecoveryStateError, "scope is malformed"
            ):
                agent_runner._read_private_remediation_scope(repo, str(scope_path))

        finalize_source = inspect.getsource(
            agent_runner.finalize_post_commit_root_completion_run
        )
        self.assertNotIn("reconcile_implementation_registry(", finalize_source)
        replay_call = "post_commit_root_completion_replay_binding("
        self.assertIn(replay_call, finalize_source)
        self.assertLess(
            finalize_source.index(replay_call),
            finalize_source.index("if completed_path.is_file():"),
        )
        self.assertIn("terminal-root-completion-artifact-v1", inspect.getsource(
            agent_runner._post_commit_root_completion_completed
        ))

        authorize_source = inspect.getsource(
            agent_runner.authorize_post_commit_root_completion_run
        )
        self.assertIn("read_owner_prompt_snapshot(", authorize_source)
        self.assertIn("args.action_snapshot_id", authorize_source)
        self.assertIn("args.action_snapshot_sha256", authorize_source)

        parser = agent_runner.build_parser()
        parsed = parser.parse_args(
            [
                "_authorize-post-commit-root-completion",
                "--run-dir",
                "opaque-run",
                "--task-commit",
                "a" * 40,
                "--root-verification-digest",
                "b" * 64,
                "--remediation-scope-file",
                "private-scope.json",
                "--action-snapshot-id",
                "c" * 64,
                "--action-snapshot-sha256",
                "d" * 64,
            ]
        )
        self.assertEqual(parsed.action_snapshot_id, "c" * 64)
        self.assertEqual(parsed.action_snapshot_sha256, "d" * 64)

    def test_post_commit_handler_chain_closes_artifact_fault_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "opaque-run"
            run_dir.mkdir()
            task_commit = "a" * 40
            request = {
                "repo": str(Path(temp) / "repo"),
                "lease_id": "lease-1",
                "profile": {"name": "openbuild_implementation_strong"},
            }
            scope = {
                "schema": "remediation-scope-v1",
                "source_checkpoint_digest": "b" * 64,
                "digest": "c" * 64,
            }
            snapshot = {"schema": "post-commit-root-completion-user-action-v1"}
            binding = {
                "schema": "terminal-root-completion-artifact-v1",
                "lease_id": "lease-1",
                "run_id": run_dir.name,
                "source_state_id": "source-1",
                "task_commit": task_commit,
                "parent_commit": "d" * 40,
                "root_verification_digest": "e" * 64,
                "producer_allowed_set_digest": "f" * 64,
                "remediation_scope_digest": scope["digest"],
                "action_snapshot_id": "1" * 64,
                "action_snapshot_sha256": "2" * 64,
                "user_action_digest": "3" * 64,
                "authorization_digest": "4" * 64,
                "authorization_consumption": "consumed",
                "terminal_binding_format": "run-dir-v1",
                "terminal_binding_digest": "5" * 64,
                "checkpoint_digest": "6" * 64,
                "archive_digest": "7" * 64,
            }
            registry = mock.Mock()
            registry.build_post_commit_root_completion_action_snapshot.return_value = snapshot
            registry.stage_post_commit_root_completion_action.return_value = {
                "action_handle": "8" * 64,
                "action_digest": "9" * 64,
            }
            registry.issue_post_commit_root_completion_authorization.return_value = {
                "authorization_handle": "0" * 64,
                "authorization_digest": "1" * 64,
            }
            retained = {"lease": {"guardian_close": True, "zero_proof": {}}}
            registry.state.side_effect = [retained, retained, {"lease": None}]
            registry.post_commit_root_completion_replay_binding.return_value = binding
            stage_args = Namespace(
                run_dir=run_dir.name,
                task_commit=task_commit,
                root_verification_digest="e" * 64,
                remediation_scope_file="private-scope.json",
            )
            authorize_args = Namespace(
                **vars(stage_args),
                action_snapshot_id="1" * 64,
                action_snapshot_sha256="2" * 64,
            )
            finalize_args = Namespace(
                **vars(stage_args), authorization_handle="0" * 64
            )

            output = io.StringIO()
            with (
                mock.patch.object(agent_runner, "resolve_run_reference", return_value=run_dir),
                mock.patch.object(agent_runner, "read_json", return_value=request),
                mock.patch.object(agent_runner, "recovery_registry_for_agent", return_value=registry),
                mock.patch.object(agent_runner, "audit_guardian_health"),
                mock.patch.object(
                    agent_runner,
                    "public_receipt",
                    return_value={"status": "completed", "process_tree_stopped": True},
                ),
                mock.patch.object(agent_runner, "_require_legacy_post_commit_binding"),
                mock.patch.object(agent_runner, "_read_private_remediation_scope", return_value=scope),
                mock.patch.object(
                    agent_runner,
                    "stage_owner_prompt_snapshot",
                    return_value={
                        "prompt_snapshot_id": "1" * 64,
                        "prompt_sha256": "2" * 64,
                    },
                ),
                mock.patch.object(
                    agent_runner,
                    "read_owner_prompt_snapshot",
                    return_value=json.dumps(snapshot),
                ),
                mock.patch.object(agent_runner, "_guardian_secret", return_value=b"secret"),
                mock.patch.object(agent_runner, "garbage_collect_owner_prompt_snapshots"),
                mock.patch.object(
                    agent_runner,
                    "durable_write_private_json",
                    side_effect=[
                        agent_runner.RecoveryStateError("private artifact write fault"),
                        None,
                    ],
                ) as durable_write,
                redirect_stdout(output),
            ):
                self.assertEqual(
                    agent_runner.stage_post_commit_root_completion_action_run(stage_args), 0
                )
                self.assertEqual(
                    agent_runner.authorize_post_commit_root_completion_run(authorize_args), 0
                )
                self.assertEqual(
                    agent_runner.finalize_post_commit_root_completion_run(finalize_args), 0
                )
                self.assertEqual(
                    agent_runner.finalize_post_commit_root_completion_run(finalize_args), 0
                )

            outcomes = [json.loads(line)["outcome"] for line in output.getvalue().splitlines()]
            self.assertEqual(
                outcomes,
                [
                    "action-snapshot-confirmed",
                    "authorization-issued",
                    "blocked",
                    "terminal-root-completed",
                ],
            )
            registry.release_contained_terminal.assert_called_once_with("lease-1")
            self.assertEqual(durable_write.call_count, 2)

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

    def private_prompt(self, root: Path, content: bytes = b"bounded task\n") -> Path:
        directory = root / "prompt-owner"
        agent_runner.ensure_private_run_dir(directory)
        prompt = directory / "prompt.md"
        agent_runner.atomic_write_bytes(prompt, content)
        return prompt

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

    def test_recovery_registry_is_owned_only_by_implementation_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            state_root = root / "private-state"
            self.assertIsNone(
                agent_runner.recovery_registry_for_agent(
                    "openbuild_review_fast",
                    repo,
                    state_root=state_root,
                )
            )
            owner = agent_runner.recovery_registry_for_agent(
                "openbuild_implementation_fast",
                repo,
                state_root=state_root,
            )
            self.assertIsNotNone(owner)
            self.assertTrue(owner.directory.is_relative_to(state_root))
            self.assertFalse((repo / ".openbuild").exists())

    def test_recovery_preflight_options_are_structured_and_implementation_only(self) -> None:
        self.assertEqual(
            agent_runner.validate_recovery_start_options(
                "openbuild_implementation_fast",
                ["plugins/openbuild", "scripts/test_agent_runner.py"],
                "R-029",
                "M2b-recovery",
            ),
            (["plugins/openbuild", "scripts/test_agent_runner.py"], "R-029", "M2b-recovery"),
        )
        with self.assertRaisesRegex(agent_runner.RunnerError, "implementation"):
            agent_runner.validate_recovery_start_options(
                "openbuild_review_fast",
                ["scripts"],
                "R-029",
                "M2b-recovery",
            )
        with self.assertRaisesRegex(agent_runner.RunnerError, "together"):
            agent_runner.validate_recovery_start_options(
                "openbuild_implementation_fast",
                ["scripts"],
                None,
                "M2b-recovery",
            )

    def test_start_rejects_a_preexisting_activation_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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
            prompt = self.private_prompt(root)
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

    def test_guardian_ipc_is_authenticated_and_kind_bound(self) -> None:
        secret = bytes.fromhex("11" * 32)
        message = agent_runner.sign_guardian_message(
            secret,
            "guardian-ready",
            {"guardian_id": "guardian-1", "active_processes": 1},
        )

        self.assertEqual(
            agent_runner.verify_guardian_message(message, secret, "guardian-ready")["guardian_id"],
            "guardian-1",
        )
        tampered = json.loads(json.dumps(message))
        tampered["payload"]["active_processes"] = 0
        with self.assertRaisesRegex(agent_runner.RunnerError, "authentication"):
            agent_runner.verify_guardian_message(tampered, secret, "guardian-ready")
        with self.assertRaisesRegex(agent_runner.RunnerError, "kind"):
            agent_runner.verify_guardian_message(message, secret, "guardian-zero")

    def test_guardian_ipc_retries_a_transient_atomic_publish_lock(self) -> None:
        secret = bytes.fromhex("77" * 32)
        message = agent_runner.sign_guardian_message(
            secret,
            "guardian-ready",
            {"guardian_id": "guardian-1"},
        )
        with mock.patch.object(
            agent_runner,
            "read_json",
            side_effect=[PermissionError("sharing violation"), message],
        ) as reader:
            payload = agent_runner.read_guardian_message(
                Path("guardian-ready.json"),
                secret,
                "guardian-ready",
            )

        self.assertEqual(payload, {"guardian_id": "guardian-1"})
        self.assertEqual(reader.call_count, 2)

    def test_guardian_failure_wins_over_an_already_published_ready_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            secret = bytes.fromhex("78" * 32)
            agent_runner.write_guardian_message(
                run_dir / "guardian-ready.json",
                secret,
                "guardian-ready",
                {"guardian_id": "guardian-1"},
            )
            agent_runner.write_guardian_message(
                run_dir / "guardian-failure.json",
                secret,
                "guardian-failure",
                {
                    "guardian_id": "guardian-1",
                    "boundary_committed": False,
                    "tree_empty": True,
                    "no_user_code": True,
                    "failure": "ready-then-provider-loss",
                },
            )
            guardian = mock.Mock()
            guardian.poll.return_value = 1

            disposition, receipt = agent_runner.await_guardian_launch(
                run_dir,
                secret,
                guardian,
                timeout=0.1,
            )

        self.assertEqual(disposition, "failed")
        self.assertFalse(receipt["boundary_committed"])

    def test_guardian_precommit_rejects_each_plan_id_drift(self) -> None:
        for field in ("provider_plan_id", "ipc_plan_id"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                run_dir = Path(temp)
                secret = bytes.fromhex("79" * 32)
                worker = {"pid": 123, "identity": "worker-created-1"}
                ready = {
                    "guardian_id": "guardian-1",
                    "guardian_pid": 999,
                    "guardian_identity": "guardian-created-1",
                    "provider": "windows-job",
                    "provider_plan_id": "provider-plan-1",
                    "ipc_plan_id": "ipc-plan-1",
                    "worker": worker,
                }
                response = {
                    **{key: value for key, value in ready.items() if key != "worker"},
                    "worker_pid": worker["pid"],
                    "worker_identity": worker["identity"],
                    "provider_populated": True,
                    "membership_verified": True,
                    "precommit_nonce": "ab" * 32,
                    "registry_digest": "cd" * 32,
                }
                response[field] = f"drifted-{field}"
                agent_runner.write_guardian_message(
                    run_dir / "guardian-precommit-ready.json",
                    secret,
                    "guardian-precommit-ready",
                    response,
                )
                guardian = mock.Mock()
                guardian.poll.return_value = None

                with mock.patch.object(
                    agent_runner.secrets,
                    "token_hex",
                    return_value="ab" * 32,
                ), self.assertRaisesRegex(agent_runner.RunnerError, "launch binding"):
                    agent_runner.await_guardian_precommit(
                        run_dir,
                        secret,
                        guardian,
                        ready,
                        timeout=0.1,
                    )

    def test_guardian_rejects_each_private_plan_id_drift_before_process_creation(self) -> None:
        for field in ("provider_plan_id", "ipc_plan_id"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                run_dir = Path(temp)
                secret = bytes.fromhex("7a" * 32)
                agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
                agent_runner.atomic_write_json(
                    run_dir / "request.json",
                    {
                        "profile": {"name": "openbuild_implementation_fast"},
                        "repo": str(run_dir),
                        "lease_id": "lease-1",
                        "lifecycle_allowed_set_digest": "ab" * 32,
                        "containment_plan": {
                            "provider_plan_id": "provider-plan-1",
                            "ipc_plan_id": "ipc-plan-1",
                        },
                    },
                )
                guardian_request = {
                    "guardian_id": "guardian-1",
                    "agent_name": "openbuild_implementation_fast",
                    "repo": str(run_dir),
                    "lease_id": "lease-1",
                    "allowed_set_digest": "ab" * 32,
                    "provider_plan_id": "provider-plan-1",
                    "ipc_plan_id": "ipc-plan-1",
                }
                guardian_request[field] = f"drifted-{field}"
                agent_runner.write_guardian_message(
                    run_dir / "guardian-request.json",
                    secret,
                    "guardian-request",
                    guardian_request,
                )

                with self.assertRaisesRegex(agent_runner.RunnerError, "registry boundary binding"):
                    agent_runner.guardian_run(run_dir)

    def test_ready_then_preboundary_failure_terminates_recovery_target_without_binding(self) -> None:
        registry = mock.Mock()
        with self.assertRaisesRegex(agent_runner.RunnerError, "before process binding"):
            agent_runner.apply_preboundary_guardian_failure(
                registry,
                "target-lease",
                {"recovery_target": True, "fallback_token": None},
                {
                    "boundary_committed": False,
                    "tree_empty": True,
                    "no_user_code": True,
                    "failure": "ready-then-provider-loss",
                    "cleanup_error": None,
                },
                run_dir=Path("target-run"),
                runner_log=mock.Mock(),
            )

        registry.fail_recovery_target_before_boundary.assert_called_once_with(
            "target-lease",
            "ready-then-provider-loss",
            {"tree_empty": True, "no_user_code": True},
        )
        registry.bind_process_unactivated.assert_not_called()

    def test_stopped_guardian_after_boundary_quarantines_writer_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_fast"},
                    "repo": str(run_dir),
                    "lease_id": "lease-1",
                },
            )
            secret = bytes.fromhex("55" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-ready.json",
                secret,
                "guardian-ready",
                {
                    "guardian_id": "guardian-1",
                    "guardian_pid": 999,
                    "guardian_identity": "guardian-created-1",
                },
            )
            registry = mock.Mock()
            registry.state.return_value = {"quarantine": None}
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=registry,
            ), mock.patch.object(
                agent_runner,
                "process_record_state",
                return_value="stopped",
            ):
                with self.assertRaisesRegex(agent_runner.RunnerError, "quarantined"):
                    agent_runner.audit_guardian_health(run_dir)

            registry.quarantine_containment_loss.assert_called_once_with(
                "lease-1",
                "guardian-process-stopped",
            )

    def test_containment_gate_rejects_tamper_before_worker_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            secret = bytes.fromhex("22" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            message = agent_runner.sign_guardian_message(
                secret,
                "containment-bound",
                {"worker_pid": 123, "worker_identity": "worker-1"},
            )
            message["payload"]["worker_identity"] = "tampered"
            agent_runner.atomic_write_json(run_dir / "containment-bound.json", message)

            with self.assertRaisesRegex(agent_runner.RunnerError, "authentication"):
                agent_runner.await_worker_containment_gate(
                    run_dir,
                    expected_pid=123,
                    expected_identity="worker-1",
                    timeout=0.1,
                )

    def test_linux_cgroup_events_require_exact_populated_zero(self) -> None:
        self.assertEqual(
            agent_runner.parse_linux_cgroup_events("populated 0\nfrozen 0\n"),
            {"populated": 0, "frozen": 0},
        )
        with self.assertRaisesRegex(agent_runner.RunnerError, "populated"):
            agent_runner.parse_linux_cgroup_events("frozen 0\n")
        with self.assertRaisesRegex(agent_runner.RunnerError, "malformed"):
            agent_runner.parse_linux_cgroup_events("populated maybe\n")

    def test_linux_cgroup_provider_is_fail_closed_without_verified_delegation(self) -> None:
        with mock.patch.object(agent_runner.sys, "platform", "linux"), mock.patch.dict(
            agent_runner.os.environ,
            {},
            clear=True,
        ):
            with self.assertRaisesRegex(agent_runner.RunnerError, "explicitly verified"):
                agent_runner.create_linux_cgroup("guardian-1")

    def test_linux_cgroup_membership_and_zero_proof_use_control_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cgroup = Path(temp)
            (cgroup / "cgroup.procs").write_text("", encoding="ascii")
            (cgroup / "cgroup.events").write_text("populated 1\nfrozen 0\n", encoding="ascii")

            (cgroup / "cgroup.procs").write_text("123\n", encoding="ascii", newline="\n")
            self.assertEqual(agent_runner.query_linux_cgroup_members(cgroup), {123})
            self.assertTrue(agent_runner.query_linux_cgroup_populated(cgroup))
            (cgroup / "cgroup.events").write_text("populated 0\nfrozen 0\n", encoding="ascii")
            self.assertFalse(agent_runner.query_linux_cgroup_populated(cgroup))

    def test_linux_worker_is_creation_bound_to_cgroup_before_exec(self) -> None:
        guardian_source = inspect.getsource(agent_runner.guardian_run)
        spawn_source = inspect.getsource(agent_runner.spawn_linux_worker_creation_bound)
        clone_source = inspect.getsource(agent_runner._clone3_process_into_cgroup)

        self.assertIn("spawn_linux_worker_creation_bound(", guardian_source)
        self.assertNotIn("attach_linux_process_to_cgroup", inspect.getsource(agent_runner))
        self.assertNotIn('(cgroup / "cgroup.procs").write_text', inspect.getsource(agent_runner))
        self.assertIn("_clone3_process_into_cgroup", spawn_source)
        self.assertIn("_CLONE_INTO_CGROUP", clone_source)

    def test_linux_anti_migration_receipt_requires_kernel_observed_boundary(self) -> None:
        receipt = {
            "guardian_id": "guardian-1",
            "worker_pid": 123,
            "worker_identity": "worker-1",
            "cgroup_namespace": "cgroup:[2]",
            "mount_namespace": "mnt:[2]",
            "self_cgroup": "/",
            "cgroup_mount_count": 1,
            "cgroup_mounts_read_only": True,
            "cgroup_write_denied": True,
            "no_cgroup_control_fds": True,
            "unprivileged_user_namespaces_disabled": True,
            "capabilities_zero": True,
            "no_new_privs": True,
        }
        expected = {
            "guardian_id": "guardian-1",
            "worker_pid": 123,
            "worker_identity": "worker-1",
            "guardian_cgroup_namespace": "cgroup:[1]",
            "guardian_mount_namespace": "mnt:[1]",
        }

        agent_runner.validate_linux_anti_migration_receipt(receipt, **expected)

        for field in [
            "cgroup_mounts_read_only",
            "cgroup_write_denied",
            "no_cgroup_control_fds",
            "unprivileged_user_namespaces_disabled",
            "capabilities_zero",
            "no_new_privs",
        ]:
            with self.subTest(field=field):
                altered = dict(receipt, **{field: False})
                with self.assertRaisesRegex(agent_runner.RunnerError, field):
                    agent_runner.validate_linux_anti_migration_receipt(altered, **expected)

        with self.assertRaisesRegex(agent_runner.RunnerError, "private cgroup and mount"):
            agent_runner.validate_linux_anti_migration_receipt(
                dict(receipt, cgroup_namespace="cgroup:[1]"),
                **expected,
            )
        with self.assertRaisesRegex(agent_runner.RunnerError, "guardian or worker binding"):
            agent_runner.validate_linux_anti_migration_receipt(
                dict(receipt, worker_pid=456),
                **expected,
            )

    def test_linux_anti_migration_rejects_delegation_marker_as_proof(self) -> None:
        with self.assertRaisesRegex(agent_runner.RunnerError, "kernel proof"):
            agent_runner.validate_linux_anti_migration_receipt(
                {
                    "guardian_id": "guardian-1",
                    "worker_pid": 123,
                    "worker_identity": "worker-1",
                    "delegation": "verified-no-migration",
                },
                guardian_id="guardian-1",
                worker_pid=123,
                worker_identity="worker-1",
                guardian_cgroup_namespace="cgroup:[1]",
                guardian_mount_namespace="mnt:[1]",
            )

    def test_linux_mount_path_decoder_handles_mountinfo_octal_escapes(self) -> None:
        self.assertEqual(
            agent_runner._decode_linux_mount_path("/sys/fs/cgroup/team\\040one"),
            "/sys/fs/cgroup/team one",
        )

    @unittest.skipUnless(
        sys.platform == "linux" and os.environ.get("OPENBUILD_LINUX_ANTI_MIGRATION_TEST") == "1",
        "requires the publication-gate Linux cgroup v2 delegation fixture",
    )
    def test_linux_descendant_cannot_migrate_to_parent_or_sibling_cgroup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            (repo / "allowed.txt").write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            state_base = root / "localappdata"
            guardian_id = f"escape-fixture-{os.getpid()}"
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(state_base)}):
                owner = agent_runner.RecoveryRegistry(repo)
                preflight = owner.prepare_source_checkpoint(
                    source_id="guardian-fixture-source",
                    source_lease_id="guardian-fixture-lease",
                    source_milestone="fixture",
                    target_milestone="fixture-recovery",
                    allowed_paths=["allowed.txt"],
                    specification_revision="R-029",
                )
                owner.reserve_normal(
                    "guardian-fixture-lease",
                    allowed_set_digest=preflight["allowed_set_digest"],
                    recovery_capable=True,
                    source_state_id=preflight["source_state_id"],
                    run_id="run",
                    prompt_sha256="a" * 64,
                    containment_plan=_containment_plan(guardian_id=guardian_id),
                )
                owner.bind_reserved_source_snapshot("guardian-fixture-lease", preflight)
                owner.claim_contained_launch("guardian-fixture-lease", "contained-token")
            run_dir = root / "run"
            agent_runner.ensure_private_run_dir(run_dir)
            secret = bytes.fromhex("66" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            cgroup = agent_runner.create_linux_cgroup(guardian_id)
            sibling = cgroup.parent / f"openbuild-sibling-{guardian_id}"
            sibling.mkdir(mode=0o700)
            output = run_dir / "escape-result.json"
            creation_output = run_dir / "creation-bound-result.json"
            targets = {
                "parent": str(cgroup.parent / "cgroup.procs"),
                "sibling": str(sibling / "cgroup.procs"),
            }
            worker_script = "\n".join(
                [
                    "import importlib.util, json, os, subprocess, sys",
                    "from pathlib import Path",
                    "self_cgroup = Path('/proc/self/cgroup').read_text(encoding='ascii')",
                    "descendant = subprocess.run([sys.executable, '-c', \"from pathlib import Path; print(Path('/proc/self/cgroup').read_text(encoding='ascii'))\"], check=True, capture_output=True, text=True)",
                    "Path(os.environ['CREATION_OUTPUT']).write_text(json.dumps({'worker': self_cgroup, 'descendant': descendant.stdout}, sort_keys=True), encoding='utf-8')",
                    f"spec = importlib.util.spec_from_file_location('fixture_runner', {str(RUNNER_PATH)!r})",
                    "runner = importlib.util.module_from_spec(spec)",
                    "spec.loader.exec_module(runner)",
                    "identity = runner.process_identity(os.getpid())",
                    "runner.establish_linux_anti_migration_boundary(Path(os.environ['RUN_DIR']), identity)",
                    f"attempt = \"import json,os,sys; sys.path.insert(0, {str(ROOT)!r}); \" + "
                    "          \"from scripts.test_agent_runner import _attempt_linux_cgroup_migration; \" + "
                    "          \"print(json.dumps(_attempt_linux_cgroup_migration(json.loads(os.environ['TARGETS'])), sort_keys=True))\"",
                    "completed = subprocess.run([sys.executable, '-c', attempt], check=True, capture_output=True, text=True)",
                    "Path(os.environ['OUTPUT']).write_text(completed.stdout, encoding='utf-8')",
                ]
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "RUN_DIR": str(run_dir),
                    "OUTPUT": str(output),
                    "CREATION_OUTPUT": str(creation_output),
                    "TARGETS": json.dumps(targets),
                }
            )
            fixture_log = run_dir / "creation-bound-fixture.log"
            with fixture_log.open("ab", buffering=0) as output_handle:
                cgroup_fd = os.open(
                    cgroup,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
                )
                stdin_fd = os.open(
                    os.devnull,
                    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
                )
                try:
                    worker = agent_runner._clone3_process_into_cgroup(
                        cgroup_fd,
                        argv=[sys.executable, "-c", worker_script],
                        environment=environment,
                        stdin_fd=stdin_fd,
                        output_fd=output_handle.fileno(),
                    )
                finally:
                    os.close(stdin_fd)
                    os.close(cgroup_fd)
            try:
                worker_identity = agent_runner.process_identity_from_popen(worker)
                self.assertIsNotNone(worker_identity)
                agent_runner.write_guardian_message(
                    run_dir / "linux-anti-migration-request.json",
                    secret,
                    "linux-anti-migration-request",
                    {
                        "guardian_id": guardian_id,
                        "worker_pid": worker.pid,
                        "worker_identity": worker_identity,
                        "cgroup_path": str(cgroup),
                    },
                )
                returncode = worker.wait(timeout=30.0)
                fixture_log_text = fixture_log.read_text(encoding="utf-8", errors="replace")
                self.assertEqual(returncode, 0, fixture_log_text)
                creation = json.loads(creation_output.read_text(encoding="utf-8"))
                self.assertEqual(creation["worker"], creation["descendant"])
                self.assertIn(f"/{cgroup.name}", creation["worker"])
                receipt = agent_runner.read_guardian_message(
                    run_dir / "linux-anti-migration-ready.json",
                    secret,
                    "linux-anti-migration-ready",
                )
                agent_runner.validate_linux_anti_migration_receipt(
                    receipt,
                    guardian_id=guardian_id,
                    worker_pid=worker.pid,
                    worker_identity=worker_identity,
                    guardian_cgroup_namespace=os.readlink("/proc/self/ns/cgroup"),
                    guardian_mount_namespace=os.readlink("/proc/self/ns/mnt"),
                )
                self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {
                    "parent": True,
                    "sibling": True,
                })
                self.assertFalse(agent_runner.query_linux_cgroup_populated(cgroup))
            finally:
                if worker.poll() is None:
                    agent_runner.terminate_guardian_provider("linux-cgroup-v2", cgroup)
                    worker.wait(timeout=5.0)
                if cgroup.is_dir() and not agent_runner.query_linux_cgroup_populated(cgroup):
                    agent_runner.close_linux_cgroup(cgroup)
                sibling.rmdir()

    @unittest.skipUnless(os.name == "nt", "native Windows Job Object containment")
    def test_windows_guardian_job_contains_and_kills_descendants_on_close(self) -> None:
        job = agent_runner.create_windows_kill_job(bind_current=False)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess,sys,time; "
                    "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    "time.sleep(30)"
                ),
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            agent_runner.assign_windows_process_to_job(job, process)
            deadline = agent_runner.time.monotonic() + 5.0
            active = 0
            while agent_runner.time.monotonic() < deadline:
                active = agent_runner.query_windows_job_active_processes(job)
                if active >= 2:
                    break
                agent_runner.time.sleep(0.05)
            self.assertGreaterEqual(active, 2)
        finally:
            agent_runner.close_windows_job(job)
        process.wait(timeout=5.0)
        self.assertIsNotNone(process.returncode)

    @unittest.skipUnless(os.name == "nt", "native Windows guardian lifecycle")
    def test_windows_suspended_worker_cannot_run_before_job_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "worker-ran.txt"
            job = agent_runner.create_windows_kill_job(bind_current=False)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')",
                    str(marker),
                ],
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.CREATE_NO_WINDOW
                    | agent_runner._WINDOWS_CREATE_SUSPENDED
                ),
            )
            try:
                agent_runner.time.sleep(0.2)
                self.assertFalse(marker.exists())
                agent_runner.assign_windows_process_to_job(job, process)
                agent_runner.verify_windows_process_in_job(job, process)
                agent_runner.resume_windows_suspended_process(process)
                process.wait(timeout=5.0)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(marker.read_text(encoding="utf-8"), "ran")
            finally:
                agent_runner.close_windows_job(job)
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5.0)

    @unittest.skipUnless(os.name == "nt", "native Windows guardian lifecycle")
    def test_windows_guardian_stays_outside_job_until_authenticated_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            state_base = root / "local-app-data"
            owner = agent_runner.RecoveryRegistry(
                repo,
                state_root=state_base / "openbuild" / "recovery",
            )
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="guardian-fixture",
                source_lease_id="guardian-fixture-lease",
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            owner.reserve_normal(
                "guardian-fixture-lease",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id="run",
                prompt_sha256="a" * 64,
                containment_plan=_containment_plan(guardian_id="guardian-fixture"),
            )
            owner.bind_reserved_source_snapshot("guardian-fixture-lease", preflight)
            owner.claim_contained_launch("guardian-fixture-lease", "contained-token")
            run_dir = Path(temp) / "run"
            agent_runner.ensure_private_run_dir(run_dir)
            prompt = run_dir / "prompt.md"
            prompt_bytes = b"bounded task\n"
            prompt.write_bytes(prompt_bytes)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {
                        "name": "openbuild_implementation_fast",
                        "description": "fixture",
                        "model": "fixture-model",
                        "reasoning_effort": "medium",
                        "sandbox": "workspace-write",
                        "developer_instructions": "bounded",
                    },
                    "profile_source": "profile.toml",
                    "agent_name": "openbuild_implementation_fast",
                    "lease_id": "guardian-fixture-lease",
                    "prompt_file": str(prompt),
                    "prompt_sha256": agent_runner.sha256_bytes(prompt_bytes),
                    "task_name": "guardian_lifecycle",
                    "codex_home": str(run_dir / "codex-home"),
                    "repo": str(repo),
                    "lifecycle_allowed_set_digest": preflight["allowed_set_digest"],
                    "recovery_preflight": preflight,
                    "containment_plan": {
                        "provider_plan_id": "provider-plan",
                        "ipc_plan_id": "ipc-plan",
                    },
                    "command": [str(run_dir / "missing-codex.exe")],
                    "activation_timeout": 10.0,
                },
            )
            secret = bytes.fromhex("33" * 32)
            guardian_id = "guardian-fixture"
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-request.json",
                secret,
                "guardian-request",
                {
                    "guardian_id": guardian_id,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "agent_name": "openbuild_implementation_fast",
                    "repo": str(repo),
                    "lease_id": "guardian-fixture-lease",
                    "allowed_set_digest": preflight["allowed_set_digest"],
                    "boundary_timeout": 10.0,
                },
            )
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(state_base)}):
                with agent_runner.open_private_binary(run_dir / "runner.log", append=True) as log:
                    guardian = agent_runner.spawn_containment_guardian(run_dir, log)
            try:
                disposition, ready = agent_runner.await_guardian_launch(
                    run_dir,
                    secret,
                    guardian,
                    timeout=10.0,
                )
                self.assertEqual(disposition, "ready")
                self.assertEqual(ready["provider"], "windows-job")
                self.assertEqual(ready["guardian_id"], guardian_id)
                self.assertEqual(ready["provider_plan_id"], "provider-plan")
                self.assertEqual(ready["ipc_plan_id"], "ipc-plan")
                self.assertIsNone(guardian.poll())
                worker = ready["worker"]
                precommit_disposition, precommit = agent_runner.await_guardian_precommit(
                    run_dir,
                    secret,
                    guardian,
                    ready,
                    timeout=10.0,
                )
                self.assertEqual(precommit_disposition, "ready")
                agent_runner.write_guardian_message(
                    run_dir / "containment-bound.json",
                    secret,
                    "containment-bound",
                    {
                        "guardian_id": guardian_id,
                        "worker_pid": worker["pid"],
                        "worker_identity": worker["identity"],
                        "allowed_set_digest": preflight["allowed_set_digest"],
                        "provider_plan_id": "provider-plan",
                        "ipc_plan_id": "ipc-plan",
                        "precommit_nonce": precommit["precommit_nonce"],
                    },
                )
                zero = agent_runner.await_guardian_record(
                    run_dir,
                    secret,
                    "guardian-zero.json",
                    "guardian-zero",
                    timeout=10.0,
                )
                self.assertFalse(zero["populated"])
                self.assertIsNone(guardian.poll())
                agent_runner.write_guardian_message(
                    run_dir / "guardian-close.json",
                    secret,
                    "guardian-close",
                    {"guardian_id": guardian_id},
                )
                closed = agent_runner.await_guardian_record(
                    run_dir,
                    secret,
                    "guardian-closed.json",
                    "guardian-closed",
                    timeout=10.0,
                )
                self.assertTrue(closed["closed"])
                guardian.wait(timeout=5.0)
                self.assertEqual(guardian.returncode, 0)
            finally:
                if guardian.poll() is None:
                    guardian.terminate()
                    guardian.wait(timeout=5.0)

    def test_terminal_receipt_drives_contained_outbox_close_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)

            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id="source-1",
                source_lease_id="lease-1",
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            owner.reserve_normal(
                "lease-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id="run",
                prompt_sha256="a" * 64,
                containment_plan=_containment_plan(),
            )
            owner.bind_reserved_source_snapshot("lease-1", preflight)
            owner.claim_contained_launch("lease-1", "contained-token")
            owner.bind_process_unactivated(
                "lease-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=_provider_receipt(),
                process_receipt=_process_receipt(),
            )
            owner.commit_activation("lease-1", preflight["allowed_set_digest"])

            run_dir = root / "run"
            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_fast"},
                    "repo": str(repo),
                    "lease_id": "lease-1",
                    "recovery_preflight": preflight,
                    **self.private_run_request_identity(run_dir),
                },
            )
            secret = bytes.fromhex("44" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-zero.json",
                secret,
                "guardian-zero",
                _zero_proof(),
            )
            agent_runner.write_guardian_message(
                run_dir / "guardian-closed.json",
                secret,
                "guardian-closed",
                _guardian_close(),
            )
            receipt = {
                "run_dir": str(run_dir),
                "status": "completed",
                "agent_name": "openbuild_implementation_fast",
                "task_name": "M2c-source",
                "lease_id": "lease-1",
                "activated": True,
                "configured_model": "fixture",
                "model_reasoning_effort": "medium",
                "sandbox": "workspace-write",
                "worker_pid": 123,
                "worker_process_identity": "worker-1",
                "codex_pid": 456,
                "codex_process_identity": "codex-1",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
                "process_tree_stopped": True,
            }
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=owner,
            ):
                agent_runner.reconcile_implementation_registry(run_dir, receipt)
                pending = owner.state()
                self.assertEqual(pending["lease"]["state"], "stopped-terminal")
                self.assertIsNone(pending["outbox"])
                self.assertFalse((run_dir / "guardian-close.json").exists())
                with self.assertRaisesRegex(agent_runner.RunnerError, "verification digest"):
                    agent_runner.reconcile_implementation_registry(
                        run_dir,
                        receipt,
                        success_verification_digest="not-a-digest",
                    )
                agent_runner.reconcile_implementation_registry(
                    run_dir,
                    receipt,
                    success_verification_digest="f" * 64,
                )
                agent_runner.reconcile_implementation_registry(run_dir, receipt)

            state = owner.state()
            self.assertIsNone(state["lease"])
            self.assertIsNone(state["outbox"])
            self.assertEqual(state["history"][-1]["event"], "contained-terminal-released")
            self.assertEqual(
                len((run_dir / "implementation-handoffs.jsonl").read_text(encoding="utf-8").splitlines()),
                1,
            )
            self.assertTrue((run_dir / "guardian-close.json").is_file())

    def test_semantic_rejection_closes_transport_without_handoff(self) -> None:
        for disposition in ("blocked", "needs-escalation"):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo = root / "repo"
                repo.mkdir()
                subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "tests@example.invalid"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
                allowed = repo / "allowed.txt"
                allowed.write_text("seed\n", encoding="utf-8", newline="\n")
                subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)

                run_dir = root / f"run-{disposition}"
                owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
                owner.initialize()
                preflight = owner.prepare_source_checkpoint(
                    source_id=run_dir.name,
                    source_lease_id="lease-1",
                    source_milestone="M2c-source",
                    target_milestone="M2c-recovery",
                    allowed_paths=["allowed.txt"],
                    specification_revision="R-029",
                )
                owner.reserve_normal(
                    "lease-1",
                    allowed_set_digest=preflight["allowed_set_digest"],
                    recovery_capable=True,
                    source_state_id=preflight["source_state_id"],
                    run_id=run_dir.name,
                    prompt_sha256="a" * 64,
                    containment_plan=_containment_plan(),
                )
                owner.bind_reserved_source_snapshot("lease-1", preflight)
                owner.claim_contained_launch("lease-1", "contained-token")
                owner.bind_process_unactivated(
                    "lease-1",
                    allowed_set_digest=preflight["allowed_set_digest"],
                    provider_receipt=_provider_receipt(),
                    process_receipt=_process_receipt(),
                )
                owner.commit_activation("lease-1", preflight["allowed_set_digest"])
                if disposition == "blocked":
                    allowed.write_text("partial edit\n", encoding="utf-8", newline="\n")

                agent_runner.ensure_private_run_dir(run_dir)
                agent_runner.atomic_write_json(
                    run_dir / "request.json",
                    {
                        "profile": {"name": "openbuild_implementation_fast"},
                        "repo": str(repo),
                        "lease_id": "lease-1",
                        "lifecycle_allowed_set_digest": preflight["allowed_set_digest"],
                        "recovery_preflight": preflight,
                        **self.private_run_request_identity(run_dir),
                    },
                )
                secret = bytes.fromhex("55" * 32)
                agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
                agent_runner.write_guardian_message(
                    run_dir / "guardian-zero.json",
                    secret,
                    "guardian-zero",
                    _zero_proof(),
                )
                agent_runner.write_guardian_message(
                    run_dir / "guardian-closed.json",
                    secret,
                    "guardian-closed",
                    _guardian_close(),
                )
                receipt = {
                    "run_dir": str(run_dir),
                    "status": "completed",
                    "agent_name": "openbuild_implementation_fast",
                    "task_name": "M2c-source",
                    "lease_id": "lease-1",
                    "activated": True,
                    "configured_model": "fixture",
                    "model_reasoning_effort": "medium",
                    "sandbox": "workspace-write",
                    "worker_pid": 123,
                    "worker_process_identity": "worker-1",
                    "codex_pid": 456,
                    "codex_process_identity": "codex-1",
                    "terminal_event": "turn.completed",
                    "codex_exit_evidence": "valid",
                    "codex_exit_code": 0,
                    "result_evidence": "valid",
                    "process_tree_stopped": True,
                }
                reject_args = Namespace(
                    run_dir=str(run_dir),
                    disposition=disposition,
                    evidence_digest="e" * 64,
                )
                finalize_args = Namespace(
                    run_dir=str(run_dir),
                    primary_signal_digest="f" * 64,
                )
                with mock.patch.object(
                    agent_runner, "audit_guardian_health"
                ), mock.patch.object(
                    agent_runner, "public_receipt", return_value=receipt
                ), mock.patch.object(
                    agent_runner, "recovery_registry_for_agent", return_value=owner
                ), redirect_stdout(io.StringIO()):
                    if disposition == "needs-escalation":
                        with mock.patch.object(
                            owner,
                            "invalidate_source_checkpoint",
                            side_effect=agent_runner.RecoveryStateError(
                                "injected checkpoint invalidation failure"
                            ),
                        ):
                            with self.assertRaisesRegex(
                                agent_runner.RunnerError,
                                "checkpoint invalidation failure",
                            ):
                                agent_runner.reject_semantic_handoff_run(reject_args)
                        pending = owner.state()
                        self.assertIsNotNone(pending["lease"])
                        self.assertFalse((run_dir / "guardian-close.json").exists())
                        semantic = agent_runner.read_json(
                            run_dir / "semantic-rejection.json"
                        )
                        self.assertEqual(
                            semantic["checkpoint_invalidation"], "pending"
                        )
                        original_atomic_write_json = agent_runner.atomic_write_json

                        def fail_checkpoint_artifact(path, value):
                            if path.name == "recovery-checkpoint.json":
                                raise OSError("injected checkpoint artifact failure")
                            return original_atomic_write_json(path, value)

                        with mock.patch.object(
                            agent_runner,
                            "atomic_write_json",
                            side_effect=fail_checkpoint_artifact,
                        ):
                            with self.assertRaisesRegex(
                                agent_runner.RunnerError,
                                "checkpoint artifact failure",
                            ):
                                agent_runner.reject_semantic_handoff_run(reject_args)
                        artifact_pending = owner.state()
                        self.assertIsNotNone(artifact_pending["lease"])
                        self.assertEqual(
                            artifact_pending["lease"]["semantic_disposition"][
                                "checkpoint_invalidation"
                            ],
                            "completed",
                        )
                        self.assertFalse((run_dir / "guardian-close.json").exists())
                        semantic = agent_runner.read_json(
                            run_dir / "semantic-rejection.json"
                        )
                        self.assertEqual(
                            semantic["checkpoint_invalidation"], "pending"
                        )
                    self.assertEqual(agent_runner.reject_semantic_handoff_run(reject_args), 0)
                    with self.assertRaisesRegex(agent_runner.RunnerError, "already consumed"):
                        agent_runner.reject_semantic_handoff_run(reject_args)
                    with self.assertRaisesRegex(agent_runner.RunnerError, "forbidden"):
                        agent_runner.finalize_success_run(finalize_args)

                state = owner.state()
                self.assertIsNone(state["lease"])
                self.assertIsNone(state["outbox"])
                self.assertFalse((run_dir / "implementation-handoffs.jsonl").exists())
                self.assertTrue((run_dir / "guardian-close.json").is_file())
                semantic = agent_runner.read_json(run_dir / "semantic-rejection.json")
                self.assertEqual(semantic["disposition"], disposition)
                checkpoint = agent_runner.read_json(run_dir / "recovery-checkpoint.json")
                if disposition == "blocked":
                    self.assertEqual(checkpoint["disposition"], "recovery-eligible")
                else:
                    self.assertEqual(checkpoint["disposition"], "recovery-ineligible")
                    self.assertIn("semantic-needs-escalation", checkpoint["reasons"])
                    with self.assertRaisesRegex(
                        agent_runner.RecoveryStateError, "semantic escalation"
                    ):
                        owner.revalidate_checkpoint(checkpoint)

    def test_ac04_to_ac12_terminal_abandonment_reconciles_retained_lease_without_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)

            run_dir = root / "outside-drift-run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            recovery_prompt = agent_runner.stage_owner_prompt_snapshot(
                owner, b"bounded recovery attempt\n"
            )
            preflight = owner.prepare_source_checkpoint(
                source_id=run_dir.name,
                source_lease_id="lease-1",
                source_milestone="M2-source",
                target_milestone="M2-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-005",
            )
            owner.reserve_normal(
                "lease-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id=run_dir.name,
                prompt_sha256="a" * 64,
                containment_plan=_containment_plan(),
            )
            owner.bind_reserved_source_snapshot("lease-1", preflight)
            owner.claim_contained_launch("lease-1", "contained-token")
            owner.bind_process_unactivated(
                "lease-1",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=_provider_receipt(),
                process_receipt=_process_receipt(),
            )
            owner.commit_activation("lease-1", preflight["allowed_set_digest"])

            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_strong"},
                    "task_name": "M2-source",
                    "repo": str(repo),
                    "lease_id": "lease-1",
                    "lifecycle_allowed_set_digest": preflight["allowed_set_digest"],
                    "recovery_preflight": preflight,
                    **self.private_run_request_identity(run_dir),
                },
            )
            secret = bytes.fromhex("55" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-zero.json",
                secret,
                "guardian-zero",
                _zero_proof(),
            )
            agent_runner.write_guardian_message(
                run_dir / "guardian-closed.json",
                secret,
                "guardian-closed",
                _guardian_close(),
            )
            receipt = {
                "run_dir": str(run_dir),
                "status": "completed",
                "agent_name": "openbuild_implementation_strong",
                "task_name": "M2-source",
                "lease_id": "lease-1",
                "activated": True,
                "configured_model": "fixture",
                "model_reasoning_effort": "xhigh",
                "sandbox": "workspace-write",
                "worker_pid": 123,
                "worker_process_identity": "worker-1",
                "codex_pid": 456,
                "codex_process_identity": "codex-1",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
                "process_tree_stopped": True,
            }
            (repo / "orchestrator-artifact.txt").write_text(
                "outside the allowed set\n", encoding="utf-8", newline="\n"
            )
            (run_dir / "result.md").write_text(
                "NEEDS_ESCALATION: semantic result cannot accept the drifted checkpoint\n",
                encoding="utf-8",
                newline="\n",
            )

            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner,
                "garbage_collect_owner_prompt_snapshots",
                wraps=agent_runner.garbage_collect_owner_prompt_snapshots,
            ) as prompt_gc:
                agent_runner.reconcile_implementation_registry(run_dir, receipt)
                self.assertEqual(owner.state()["lease"]["state"], "stopped-terminal")
                checkpoint = agent_runner.read_json(run_dir / "recovery-checkpoint.json")
                self.assertEqual(checkpoint["reasons"], ["outside-set-drift"])
                self.assertFalse((run_dir / "implementation-handoffs.jsonl").exists())
                checkpoint_path = run_dir / "attempted-recovery-checkpoint.json"
                agent_runner.atomic_write_json(checkpoint_path, checkpoint)
                state_before_attempt = owner.path.read_bytes()
                with self.assertRaisesRegex(agent_runner.RunnerError, "occupied"):
                    agent_runner.authorize_recovery_run(
                        Namespace(
                            repo=str(repo),
                            checkpoint_file=str(checkpoint_path),
                            prompt_file=None,
                            prompt_snapshot_id=recovery_prompt["prompt_snapshot_id"],
                            prompt_sha256=recovery_prompt["prompt_sha256"],
                            run_dir=str(root / "replacement-run"),
                            lease_id="replacement-lease",
                            user_action_digest="b" * 64,
                            specification_revision="R-005",
                        )
                    )
                self.assertEqual(owner.path.read_bytes(), state_before_attempt)
                self.assertFalse((root / "replacement-run").exists())
                with mock.patch.object(
                    agent_runner, "audit_guardian_health"
                ), mock.patch.object(
                    agent_runner, "public_receipt", return_value=receipt
                ), redirect_stdout(io.StringIO()):
                    agent_runner.reconcile_terminal_abandonment_run(
                        Namespace(run_dir=str(run_dir))
                    )
                self.assertGreaterEqual(prompt_gc.call_count, 1)

            state = owner.state()
            self.assertIsNone(state["lease"])
            self.assertIsNone(state["outbox"])
            self.assertEqual(state["history"][-1]["semantic_disposition"], "abandoned")
            self.assertFalse(state["history"][-1]["terminal_success"])
            self.assertFalse((run_dir / "implementation-handoffs.jsonl").exists())
            self.assertTrue((run_dir / "guardian-close.json").is_file())
            abandonment = agent_runner.read_json(run_dir / "terminal-abandonment.json")
            self.assertEqual(abandonment["outcome"], "terminal-abandoned")
            self.assertEqual(abandonment["cause"], "outside-set-drift")
            self.assertFalse(abandonment["checkpoint_allowed"])
            self.assertFalse(
                (
                    agent_runner._prompt_snapshot_paths(owner)[1]
                    / f"{recovery_prompt['prompt_snapshot_id']}.blob"
                ).exists()
            )
            audit_output = io.StringIO()
            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), redirect_stdout(audit_output):
                self.assertEqual(
                    agent_runner.record_root_completion_authorization_run(
                        Namespace(
                            run_dir=str(run_dir),
                            specification_revision="R-005",
                            milestone="M2-source",
                            allowed_set_digest=preflight["allowed_set_digest"],
                            diff_attribution_digest="d" * 64,
                        )
                    ),
                    0,
                )
            audit = json.loads(audit_output.getvalue())
            self.assertEqual(audit["event"], "root-completion-authorized")
            self.assertTrue((run_dir / "root-completion-authorized.json").is_file())
            reloaded_owner = agent_runner.RecoveryRegistry(
                repo, state_root=root / "state"
            )
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=reloaded_owner,
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(
                    agent_runner.record_root_completion_authorization_run(
                        Namespace(
                            run_dir=str(run_dir),
                            specification_revision="R-005",
                            milestone="M2-source",
                            allowed_set_digest=preflight["allowed_set_digest"],
                            diff_attribution_digest="d" * 64,
                        )
                    ),
                    0,
                )
            allowed.write_text("root completion after audit\n", encoding="utf-8", newline="\n")

    def test_ac14_recovery_overlap_abandonment_does_not_authorize_root_or_mutate_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "core.autocrlf", "false"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Tests"], cwd=repo, check=True
            )
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "baseline"],
                cwd=repo,
                check=True,
            )
            allowed.write_text(
                "preexisting user change\n", encoding="utf-8", newline="\n"
            )

            run_dir = root / "recovery-overlap-run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            prompt = agent_runner.stage_owner_prompt_snapshot(
                owner, b"bounded recovery overlap attempt\n"
            )
            checkpoint = owner.capture_checkpoint(
                source_id="source-1",
                source_lease_id="source-lease",
                source_receipt_digest="a" * 64,
                source_milestone="M2-source",
                target_milestone="M2-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-005",
            )
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="b" * 64,
                specification_revision="R-005",
                prompt_snapshot_id=prompt["prompt_snapshot_id"],
                prompt_sha256=prompt["prompt_sha256"],
            )
            owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "recovery-lease",
                    "run_id": run_dir.name,
                    "prompt_snapshot_id": prompt["prompt_snapshot_id"],
                    "prompt_sha256": prompt["prompt_sha256"],
                    "launch_token": "d" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            recovery_preflight = owner.prepare_source_checkpoint(
                source_id="recovery-overlap-next-source",
                source_lease_id="recovery-lease",
                source_milestone="M2-recovery",
                target_milestone="M3",
                allowed_paths=["allowed.txt"],
                specification_revision="R-005",
            )
            owner.claim_launch("recovery-lease", "d" * 64)
            owner.bind_process_unactivated(
                "recovery-lease",
                allowed_set_digest=checkpoint["allowed_set_digest"],
                provider_receipt=_provider_receipt(),
                process_receipt=_process_receipt(),
            )
            owner.commit_activation(
                "recovery-lease", checkpoint["allowed_set_digest"]
            )

            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_strong"},
                    "task_name": "M2-recovery",
                    "repo": str(repo),
                    "lease_id": "recovery-lease",
                    "lifecycle_allowed_set_digest": checkpoint[
                        "allowed_set_digest"
                    ],
                    "recovery_preflight": recovery_preflight,
                    "recovery_parent_checkpoint": checkpoint,
                    "recovery_target": True,
                    **self.private_run_request_identity(run_dir),
                },
            )
            secret = bytes.fromhex("55" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-zero.json",
                secret,
                "guardian-zero",
                _zero_proof(),
            )
            agent_runner.write_guardian_message(
                run_dir / "guardian-closed.json",
                secret,
                "guardian-closed",
                _guardian_close(),
            )
            receipt = {
                "run_dir": str(run_dir),
                "status": "completed",
                "agent_name": "openbuild_implementation_strong",
                "task_name": "M2-recovery",
                "lease_id": "recovery-lease",
                "activated": True,
                "configured_model": "fixture",
                "model_reasoning_effort": "xhigh",
                "sandbox": "workspace-write",
                "worker_pid": 123,
                "worker_process_identity": "worker-1",
                "codex_pid": 456,
                "codex_process_identity": "codex-1",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
                "process_tree_stopped": True,
            }
            allowed.write_text(
                "recovery writer change\n", encoding="utf-8", newline="\n"
            )
            outside = repo / "orchestrator-artifact.txt"
            outside.write_text("outside drift\n", encoding="utf-8", newline="\n")
            (run_dir / "result.md").write_text(
                "NEEDS_ESCALATION: legacy normal overlap requires reconciliation\n",
                encoding="utf-8",
                newline="\n",
            )
            status_before = subprocess.run(
                ["git", "status", "--porcelain=v2", "-z"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            diff_before = subprocess.run(
                ["git", "diff", "--binary", "--no-ext-diff"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            index_before = (repo / ".git" / "index").read_bytes()
            attribution_receipt = {
                "status_sha256": agent_runner.sha256_bytes(status_before),
                "diff_sha256": agent_runner.sha256_bytes(diff_before),
                "index_sha256": agent_runner.sha256_bytes(index_before),
            }
            diff_attribution_digest = agent_runner.sha256_bytes(
                json.dumps(
                    attribution_receipt,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )

            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ):
                with self.assertRaisesRegex(
                    agent_runner.RunnerError, "exact registry vacancy"
                ):
                    agent_runner.record_root_completion_authorization_run(
                        Namespace(
                            run_dir=str(run_dir),
                            specification_revision="R-005",
                            milestone="M2-recovery",
                            allowed_set_digest=checkpoint["allowed_set_digest"],
                            diff_attribution_digest=diff_attribution_digest,
                        )
                    )
                self.assertFalse((run_dir / "root-completion-authorized.json").exists())
                with mock.patch.object(
                    agent_runner, "audit_guardian_health"
                ), mock.patch.object(
                    agent_runner, "public_receipt", return_value=receipt
                ), redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        agent_runner.reconcile_terminal_abandonment_run(
                            Namespace(run_dir=str(run_dir))
                        ),
                        0,
                    )

            state = owner.state()
            abandonment = agent_runner.read_json(run_dir / "terminal-abandonment.json")
            self.assertIsNone(state["lease"])
            self.assertIsNone(state["outbox"])
            self.assertEqual(abandonment["schema"], "terminal-abandonment-v2")
            self.assertEqual(
                abandonment["cause"],
                "outside-set-drift-with-preexisting-dirty-overlap",
            )
            self.assertFalse((run_dir / "implementation-handoffs.jsonl").exists())
            self.assertFalse((run_dir / "root-completion-authorized.json").exists())
            audit_output = io.StringIO()
            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), redirect_stdout(audit_output):
                self.assertEqual(
                    agent_runner.record_root_completion_authorization_run(
                        Namespace(
                            run_dir=str(run_dir),
                            specification_revision="R-005",
                            milestone="M2-recovery",
                            allowed_set_digest=checkpoint["allowed_set_digest"],
                            diff_attribution_digest=diff_attribution_digest,
                        )
                    ),
                    0,
                )
            expected_audit = agent_runner.root_completion_authorization_record(
                specification_revision="R-005",
                milestone="M2-recovery",
                allowed_set_digest=checkpoint["allowed_set_digest"],
                diff_attribution_digest=diff_attribution_digest,
            )
            self.assertEqual(json.loads(audit_output.getvalue()), expected_audit)
            self.assertEqual(
                agent_runner.read_json(run_dir / "root-completion-authorized.json"),
                expected_audit,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--porcelain=v2", "-z"],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout,
                status_before,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "diff", "--binary", "--no-ext-diff"],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout,
                diff_before,
            )
            self.assertEqual((repo / ".git" / "index").read_bytes(), index_before)
            self.assertEqual(allowed.read_text(encoding="utf-8"), "recovery writer change\n")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside drift\n")

    def test_legacy_normal_overlap_reconciles_v3_without_handoff_or_repo_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "core.autocrlf", "false"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Tests"], cwd=repo, check=True
            )
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "baseline"],
                cwd=repo,
                check=True,
            )
            allowed.write_text(
                "preexisting user change\n", encoding="utf-8", newline="\n"
            )

            run_dir = root / "legacy-normal-overlap-run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            preflight = owner.prepare_source_checkpoint(
                source_id=run_dir.name,
                source_lease_id="normal-lease",
                source_milestone="M2-source",
                target_milestone="M2-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-015",
            )
            owner.reserve_normal(
                "normal-lease",
                allowed_set_digest=preflight["allowed_set_digest"],
                recovery_capable=True,
                source_state_id=preflight["source_state_id"],
                run_id=run_dir.name,
                prompt_sha256="a" * 64,
                containment_plan=_containment_plan(),
            )
            owner.bind_reserved_source_snapshot("normal-lease", preflight)
            owner.claim_contained_launch("normal-lease", "contained-token")
            owner.bind_process_unactivated(
                "normal-lease",
                allowed_set_digest=preflight["allowed_set_digest"],
                provider_receipt=_provider_receipt(),
                process_receipt=_process_receipt(),
            )
            owner.commit_activation(
                "normal-lease", preflight["allowed_set_digest"]
            )

            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_strong"},
                    "task_name": "M2-source",
                    "repo": str(repo),
                    "lease_id": "normal-lease",
                    "lifecycle_allowed_set_digest": preflight[
                        "allowed_set_digest"
                    ],
                    "recovery_preflight": preflight,
                    **self.private_run_request_identity(run_dir),
                },
            )
            secret = bytes.fromhex("55" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            agent_runner.write_guardian_message(
                run_dir / "guardian-zero.json",
                secret,
                "guardian-zero",
                _zero_proof(),
            )
            agent_runner.write_guardian_message(
                run_dir / "guardian-closed.json",
                secret,
                "guardian-closed",
                _guardian_close(),
            )
            receipt = {
                "run_dir": str(run_dir),
                "status": "completed",
                "agent_name": "openbuild_implementation_strong",
                "task_name": "M2-source",
                "lease_id": "normal-lease",
                "activated": True,
                "configured_model": "fixture",
                "model_reasoning_effort": "xhigh",
                "sandbox": "workspace-write",
                "worker_pid": 123,
                "worker_process_identity": "worker-1",
                "codex_pid": 456,
                "codex_process_identity": "codex-1",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
                "process_tree_stopped": True,
            }
            allowed.write_text("writer change\n", encoding="utf-8", newline="\n")
            outside = repo / "orchestrator-artifact.txt"
            outside.write_text("outside drift\n", encoding="utf-8", newline="\n")
            status_before = subprocess.run(
                ["git", "status", "--porcelain=v2", "-z"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            diff_before = subprocess.run(
                ["git", "diff", "--binary", "--no-ext-diff"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            index_before = (repo / ".git" / "index").read_bytes()

            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner, "audit_guardian_health"
            ), mock.patch.object(
                agent_runner, "public_receipt", return_value=receipt
            ), redirect_stdout(io.StringIO()):
                agent_runner.reconcile_implementation_registry(run_dir, receipt)
                checkpoint = agent_runner.read_json(
                    run_dir / "recovery-checkpoint.json"
                )
                self.assertEqual(
                    checkpoint["reasons"],
                    ["outside-set-drift", "preexisting-dirty-overlap"],
                )
                self.assertEqual(
                    agent_runner.reconcile_terminal_abandonment_run(
                        Namespace(run_dir=str(run_dir))
                    ),
                    0,
                )

            state = owner.state()
            abandonment = agent_runner.read_json(run_dir / "terminal-abandonment.json")
            self.assertIsNone(state["lease"])
            self.assertIsNone(state["outbox"])
            self.assertEqual(abandonment["schema"], "terminal-abandonment-v3")
            self.assertEqual(
                abandonment["cause"],
                "legacy-normal-outside-set-drift-with-preexisting-dirty-overlap",
            )
            self.assertFalse(abandonment["checkpoint_allowed"])
            self.assertFalse((run_dir / "implementation-handoffs.jsonl").exists())
            self.assertFalse((run_dir / "root-completion-authorized.json").exists())
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--porcelain=v2", "-z"],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout,
                status_before,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "diff", "--binary", "--no-ext-diff"],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout,
                diff_before,
            )
            self.assertEqual((repo / ".git" / "index").read_bytes(), index_before)
            self.assertEqual(allowed.read_text(encoding="utf-8"), "writer change\n")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside drift\n")

    def test_ac09_ac13_root_completion_audit_is_durable_before_authorization(self) -> None:
        fault_stages = (
            "before-write",
            "after-file-fsync",
            "after-replace",
            "before-metadata-barrier",
            "after-metadata-barrier",
        )
        for fault_stage in fault_stages:
            with self.subTest(fault_stage=fault_stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                run_dir = root / "run"
                agent_runner.ensure_private_run_dir(run_dir)
                repo = root / "repo"
                repo.mkdir()
                request = {
                    "profile": {"name": "openbuild_implementation_fast"},
                    "repo": str(repo),
                    "lease_id": "lease-root-audit",
                    "task_name": "M2-source",
                    "recovery_preflight": {"specification_revision": "R-005"},
                }
                agent_runner.atomic_write_json(run_dir / "request.json", request)
                registry = mock.Mock()
                registry.state.return_value = {
                    "lease": None,
                    "outbox": None,
                    "quarantine": None,
                    "history": [
                        {
                            "event": "contained-terminal-released",
                            "lease_id": "lease-root-audit",
                            "terminal_success": False,
                            "handoff_digest": None,
                            "outbox_digest": None,
                            "allowed_set_digest": "a" * 64,
                        }
                    ],
                }
                arguments = Namespace(
                    run_dir=str(run_dir),
                    specification_revision="R-005",
                    milestone="M2-source",
                    allowed_set_digest="a" * 64,
                    diff_attribution_digest="d" * 64,
                    durability_fault=fault_stage,
                )
                with mock.patch.object(
                    agent_runner, "recovery_registry_for_agent", return_value=registry
                ), redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    agent_runner.RunnerError, "durable root completion audit"
                ):
                    agent_runner.record_root_completion_authorization_run(arguments)

                path = run_dir / "root-completion-authorized.json"
                if path.is_file():
                    persisted = agent_runner.read_json(path)
                    self.assertEqual(
                        persisted,
                        agent_runner.root_completion_authorization_record(
                            specification_revision="R-005",
                            milestone="M2-source",
                            allowed_set_digest="a" * 64,
                            diff_attribution_digest="d" * 64,
                        ),
                    )
                arguments.durability_fault = None
                with mock.patch.object(
                    agent_runner, "recovery_registry_for_agent", return_value=registry
                ), redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        agent_runner.record_root_completion_authorization_run(arguments),
                        0,
                    )
                self.assertEqual(
                    agent_runner.read_json(path),
                    agent_runner.root_completion_authorization_record(
                        specification_revision="R-005",
                        milestone="M2-source",
                        allowed_set_digest="a" * 64,
                        diff_attribution_digest="d" * 64,
                    ),
                )

    def test_ac04_ac05_ac13_terminal_reconcile_rejects_normal_and_recovery_run_mismatch(self) -> None:
        for lease_kind in ("normal-contained", "recovery-target"):
            with self.subTest(lease_kind=lease_kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo = root / "repo"
                repo.mkdir()
                subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "tests@example.invalid"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Tests"], cwd=repo, check=True
                )
                (repo / "allowed.txt").write_text(
                    "seed\n", encoding="utf-8", newline="\n"
                )
                subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "commit", "--quiet", "-m", "baseline"],
                    cwd=repo,
                    check=True,
                )
                owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
                owner.initialize()
                expected_run_id = f"expected-{lease_kind}"
                lease_id = f"lease-{lease_kind}"

                if lease_kind == "normal-contained":
                    preflight = owner.prepare_source_checkpoint(
                        source_id=expected_run_id,
                        source_lease_id=lease_id,
                        source_milestone="source",
                        target_milestone="target",
                        allowed_paths=["allowed.txt"],
                        specification_revision="R-005",
                    )
                    owner.reserve_normal(
                        lease_id,
                        allowed_set_digest=preflight["allowed_set_digest"],
                        recovery_capable=True,
                        source_state_id=preflight["source_state_id"],
                        run_id=expected_run_id,
                        prompt_sha256="a" * 64,
                        containment_plan=_containment_plan(),
                    )
                    owner.bind_reserved_source_snapshot(lease_id, preflight)
                    owner.claim_contained_launch(lease_id, "contained-token")
                    allowed_set_digest = preflight["allowed_set_digest"]
                else:
                    checkpoint = owner.capture_checkpoint(
                        source_id="source-1",
                        source_lease_id="source-lease",
                        source_receipt_digest="a" * 64,
                        source_milestone="source",
                        target_milestone="target",
                        allowed_paths=["allowed.txt"],
                        specification_revision="R-005",
                    )
                    checkpoint = owner.revalidate_checkpoint(checkpoint)
                    grant = owner.grant_authorization(
                        checkpoint,
                        user_action_digest="b" * 64,
                        specification_revision="R-005",
                    )
                    owner.consume_grant_and_reserve(
                        grant_id=grant["grant_id"],
                        checkpoint=checkpoint,
                        target_plan={
                            "lease_id": lease_id,
                            "run_id": expected_run_id,
                            "prompt_sha256": "c" * 64,
                            "launch_token": "d" * 64,
                            "provider_plan_id": "provider-plan",
                            "ipc_plan_id": "ipc-plan",
                            "allowed_set_digest": checkpoint["allowed_set_digest"],
                        },
                    )
                    owner.claim_launch(lease_id, "d" * 64)
                    allowed_set_digest = checkpoint["allowed_set_digest"]

                owner.bind_process_unactivated(
                    lease_id,
                    allowed_set_digest=allowed_set_digest,
                    provider_receipt=_provider_receipt(),
                    process_receipt=_process_receipt(),
                )
                owner.commit_activation(lease_id, allowed_set_digest)
                mismatched_run = root / "different-run"
                mismatched_run.mkdir()
                agent_runner.atomic_write_json(
                    mismatched_run / "request.json",
                    {
                        "profile": {"name": "openbuild_implementation_strong"},
                        "repo": str(repo),
                        "lease_id": lease_id,
                    },
                )
                before = {
                    path.relative_to(owner.state_root).as_posix(): path.read_bytes()
                    for path in owner.state_root.rglob("*")
                    if path.is_file()
                }
                with mock.patch.object(
                    agent_runner, "recovery_registry_for_agent", return_value=owner
                ), self.assertRaisesRegex(agent_runner.RunnerError, "run ID"):
                    agent_runner.reconcile_implementation_registry(
                        mismatched_run,
                        {"status": "completed", "process_tree_stopped": True},
                        terminal_abandonment=True,
                    )
                after = {
                    path.relative_to(owner.state_root).as_posix(): path.read_bytes()
                    for path in owner.state_root.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)

    def test_ac09_ac11_ac18_closed_outcomes_and_root_completion_audit_are_executable(self) -> None:
        decision = agent_runner.classify_recovery_outcome(decision_class="external-action")
        blocked = agent_runner.classify_recovery_outcome(
            missing_safety_evidence=("process-identity", "containment-zero")
        )
        exhausted = agent_runner.classify_recovery_outcome(
            exhausted_capabilities=("configured-writer-route",)
        )
        abandoned = agent_runner.classify_recovery_outcome(
            terminal_abandonment={
                "outcome": "terminal-abandoned",
                "schema": "terminal-abandonment-v1",
                "cause": "outside-set-drift",
                "checkpoint_invalidation": "completed",
            }
        )
        recovery_overlap_abandoned = agent_runner.classify_recovery_outcome(
            terminal_abandonment={
                "outcome": "terminal-abandoned",
                "schema": "terminal-abandonment-v2",
                "cause": "outside-set-drift-with-preexisting-dirty-overlap",
                "checkpoint_invalidation": "completed",
            }
        )
        legacy_normal_overlap_abandoned = agent_runner.classify_recovery_outcome(
            terminal_abandonment={
                "outcome": "terminal-abandoned",
                "schema": "terminal-abandonment-v3",
                "cause": "legacy-normal-outside-set-drift-with-preexisting-dirty-overlap",
                "checkpoint_invalidation": "completed",
            }
        )
        audit = agent_runner.root_completion_authorization_record(
            specification_revision="R-005",
            milestone="M2",
            allowed_set_digest="a" * 64,
            diff_attribution_digest="b" * 64,
        )

        self.assertEqual(decision["required_action"], "provide-decision")
        self.assertEqual(blocked["outcome"], "blocked")
        self.assertEqual(exhausted["outcome"], "automation-exhausted")
        self.assertEqual(abandoned["outcome"], "terminal-abandoned")
        self.assertEqual(recovery_overlap_abandoned["schema"], "terminal-abandonment-v2")
        self.assertEqual(
            legacy_normal_overlap_abandoned["schema"], "terminal-abandonment-v3"
        )
        self.assertEqual(audit["event"], "root-completion-authorized")
        self.assertEqual(audit["authority"], "original-build-request")
        self.assertTrue(audit["automatic"])
        for record in (
            decision,
            blocked,
            exhausted,
            abandoned,
            recovery_overlap_abandoned,
            legacy_normal_overlap_abandoned,
            audit,
        ):
            self.assertEqual(record["writer_action"], "none")
            rendered = json.dumps(record)
            self.assertNotIn(str(ROOT), rendered)
            self.assertNotIn("authorize-recovery", rendered)

    def test_implementation_start_commits_containment_before_worker_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            run_dir = root / "run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            prompt_binding = agent_runner.stage_owner_prompt_snapshot(
                owner, b"bounded task\n"
            )
            profile = self.profile()._replace(
                name="openbuild_implementation_fast",
                sandbox="workspace-write",
            )
            guardian = mock.Mock()
            guardian.poll.return_value = None
            worker = {
                "pid": 123,
                "identity": "worker-created-1",
                "process_group_id": 123,
                "started_at": agent_runner.utc_now(),
            }
            ready = {
                "guardian_id": "guardian-private",
                "guardian_pid": 999,
                "guardian_identity": "guardian-created-1",
                "provider": "windows-job",
                "policy": "kill-on-close-no-breakaway",
                "active_processes": 1,
                "worker": worker,
            }
            public = {
                "status": "running",
                "activated": False,
                "codex_process_identity": "codex-created-1",
            }
            durable_sequence: list[str] = []
            durable_bytes = agent_runner.durable_write_private_bytes
            durable_json = agent_runner.durable_write_private_json
            release_snapshot = owner.mark_prompt_snapshot_released

            def record_durable_bytes(path, value, *, fault=None):
                durable_bytes(path, value, fault=fault)
                durable_sequence.append(path.name)

            def record_durable_json(path, value, *, fault=None):
                durable_json(path, value, fault=fault)
                durable_sequence.append(path.name)

            def record_release(snapshot_id, prompt_sha256):
                self.assertEqual(durable_sequence, ["prompt.md", "request.json"])
                self.assertEqual((run_dir / "prompt.md").read_bytes(), b"bounded task\n")
                self.assertEqual(
                    agent_runner.read_json(run_dir / "request.json")["prompt_sha256"],
                    prompt_binding["prompt_sha256"],
                )
                return release_snapshot(snapshot_id, prompt_sha256)

            def guardian_launch(*_args: object, **_kwargs: object):
                agent_runner.atomic_write_json(
                    run_dir / "codex.json",
                    {"pid": 456, "identity": "codex-created-1", "process_group_id": 456},
                )
                plan = agent_runner.read_json(run_dir / "request.json")["containment_plan"]
                ready["guardian_id"] = plan["guardian_id"]
                ready["provider_plan_id"] = plan["provider_plan_id"]
                ready["ipc_plan_id"] = plan["ipc_plan_id"]
                return "ready", ready

            def guardian_precommit(*_args: object, **_kwargs: object):
                provider_receipt = _provider_receipt(
                    guardian_id=ready["guardian_id"],
                    provider_plan_id=ready["provider_plan_id"],
                    ipc_plan_id=ready["ipc_plan_id"],
                    worker=worker,
                    precommit_nonce="precommit-1",
                )
                precommit = provider_receipt["precommit"]
                allowed_set_digest = owner.state()["lease"]["allowed_set_digest"]
                bound = owner.bind_process_unactivated(
                    "lease-1",
                    allowed_set_digest=allowed_set_digest,
                    provider_receipt=provider_receipt,
                    process_receipt=worker,
                )
                return "ready", {**precommit, "registry_digest": bound["digest"]}

            args = Namespace(
                repo=str(repo),
                prompt_file=None,
                prompt_snapshot_id=prompt_binding["prompt_snapshot_id"],
                prompt_sha256=prompt_binding["prompt_sha256"],
                agent="openbuild_implementation_fast",
                lease_id="lease-1",
                allowed_file=["allowed.txt"],
                specification_revision="R-029",
                recovery_target_milestone="M2c-recovery",
                run_dir=str(run_dir),
                task_name="M2c-source",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner, "spawn_containment_guardian", return_value=guardian
            ), mock.patch.object(
                agent_runner, "await_guardian_launch", side_effect=guardian_launch
            ), mock.patch.object(
                agent_runner,
                "await_guardian_precommit",
                side_effect=guardian_precommit,
            ), mock.patch.object(
                agent_runner, "public_receipt", return_value=public
            ), mock.patch.object(
                agent_runner,
                "durable_write_private_bytes",
                side_effect=record_durable_bytes,
            ), mock.patch.object(
                agent_runner,
                "durable_write_private_json",
                side_effect=record_durable_json,
            ), mock.patch.object(
                owner,
                "mark_prompt_snapshot_released",
                side_effect=record_release,
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(agent_runner.start_run(args), 0)

            state = owner.state()
            self.assertEqual(state["lease"]["state"], "process-bound-unactivated")
            self.assertTrue(state["lease"]["recovery_capable"])
            request = agent_runner.read_json(run_dir / "request.json")
            self.assertIsNone(request["prompt_source"])
            self.assertEqual((run_dir / "prompt.md").read_bytes(), b"bounded task\n")
            secret = (run_dir / "guardian.key").read_bytes()
            boundary = agent_runner.read_guardian_message(
                run_dir / "containment-bound.json",
                secret,
                "containment-bound",
            )
            self.assertEqual(boundary["worker_identity"], "worker-created-1")
            self.assertEqual(
                boundary["allowed_set_digest"],
                state["lease"]["allowed_set_digest"],
            )
            request_plan = agent_runner.read_json(run_dir / "request.json")["containment_plan"]
            self.assertEqual(boundary["provider_plan_id"], request_plan["provider_plan_id"])
            self.assertEqual(boundary["ipc_plan_id"], request_plan["ipc_plan_id"])
            self.assertEqual(
                state["lease"]["provider_receipt"]["provider_plan_id"],
                request_plan["provider_plan_id"],
            )
            self.assertEqual(
                state["lease"]["provider_receipt"]["ipc_plan_id"],
                request_plan["ipc_plan_id"],
            )
            self.assertEqual(durable_sequence, ["prompt.md", "request.json"])

    def test_preboundary_provider_failure_uses_one_nonrecovery_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            prompt = self.private_prompt(root)
            run_dir = root / "run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            profile = self.profile()._replace(
                name="openbuild_implementation_fast",
                sandbox="workspace-write",
            )
            guardian = mock.Mock()
            guardian.poll.return_value = 1
            ready = {
                "guardian_id": "guardian-private",
                "guardian_pid": 999,
                "guardian_identity": "guardian-created-1",
                "provider": "windows-job",
                "worker": {
                    "pid": 123,
                    "identity": "worker-created-1",
                    "process_group_id": 123,
                },
            }
            fallback_process = mock.Mock(pid=321)
            fallback_process.poll.return_value = None
            public = {
                "status": "running",
                "activated": False,
                "codex_process_identity": "codex-created-1",
            }

            def spawn_fallback(*_args: object, **_kwargs: object):
                agent_runner.atomic_write_json(
                    run_dir / "codex.json",
                    {"pid": 456, "identity": "codex-created-1", "process_group_id": 456},
                )
                return fallback_process

            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_implementation_fast",
                lease_id="lease-1",
                allowed_file=["allowed.txt"],
                specification_revision="R-029",
                recovery_target_milestone="M2c-recovery",
                run_dir=str(run_dir),
                task_name="M2c-source",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner, "spawn_containment_guardian", return_value=guardian
            ), mock.patch.object(
                agent_runner,
                "await_guardian_launch",
                return_value=("ready", ready),
            ), mock.patch.object(
                agent_runner,
                "await_guardian_precommit",
                return_value=(
                    "failed",
                    {
                        "guardian_id": "guardian-private",
                        "boundary_committed": False,
                        "tree_empty": True,
                        "no_user_code": True,
                        "failure": "ready-then-provider-loss",
                        "cleanup_error": None,
                    },
                ),
            ), mock.patch.object(
                agent_runner, "_spawn_worker_process", side_effect=spawn_fallback
            ) as spawn, mock.patch.object(
                agent_runner, "process_identity_from_popen", return_value="fallback-created-1"
            ), mock.patch.object(
                agent_runner, "public_receipt", return_value=public
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(agent_runner.start_run(args), 0)

            self.assertEqual(spawn.call_count, 1)
            state = owner.state()
            self.assertEqual(state["lease"]["lease_kind"], "normal-fallback")
            self.assertFalse(state["lease"]["recovery_capable"])
            self.assertEqual(state["lease"]["state"], "ordinary-process-bound-unactivated")

    def test_checkpoint_byte_limit_uses_a_valid_legacy_activation_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("larger than one byte\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)

            prompt = self.private_prompt(root)
            run_dir = root / "run"
            owner = agent_runner.RecoveryRegistry(
                repo,
                state_root=root / "state",
                max_bytes=1,
            )
            profile = self.profile()._replace(
                name="openbuild_implementation_fast",
                sandbox="workspace-write",
            )
            process = mock.Mock(pid=321)
            process.poll.return_value = None
            running = {
                "status": "running",
                "activated": False,
                "codex_pid": 456,
                "codex_process_identity": "codex-created-1",
            }

            def spawn_worker(*_args: object, **_kwargs: object) -> object:
                agent_runner.atomic_write_json(
                    run_dir / "codex.json",
                    {"pid": 456, "identity": "codex-created-1", "process_group_id": 456},
                )
                return process

            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_implementation_fast",
                lease_id="lease-1",
                allowed_file=["allowed.txt"],
                specification_revision="R-029",
                recovery_target_milestone="M2c-recovery",
                run_dir=str(run_dir),
                task_name="M2c-source",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner, "_spawn_worker_process", side_effect=spawn_worker
            ), mock.patch.object(
                agent_runner, "process_identity_from_popen", return_value="worker-created-1"
            ), mock.patch.object(
                agent_runner, "public_receipt", return_value=running
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(agent_runner.start_run(args), 0)

            request = agent_runner.read_json(run_dir / "request.json")
            self.assertEqual(request["recovery_capability_unavailable"], "checkpoint byte limit exceeded")
            self.assertRegex(request["lifecycle_allowed_set_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                owner.state()["lease"]["allowed_set_digest"],
                request["lifecycle_allowed_set_digest"],
            )

            activated = running | {"activated": True}
            with mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner, "public_receipt", side_effect=[running, activated]
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(agent_runner.activate_run(Namespace(run_dir=str(run_dir))), 0)

            lease = owner.state()["lease"]
            self.assertEqual(lease["state"], "legacy-running")
            self.assertEqual(
                lease["activation_allowed_set_digest"],
                request["lifecycle_allowed_set_digest"],
            )

    def test_ambiguous_fallback_faults_are_quarantined_before_release(self) -> None:
        for fault_stage in (
            "before-popen",
            "after-popen",
            "before-bind",
            "after-visible-bind",
            "mismatched-bind-receipt",
        ):
            with self.subTest(fault_stage=fault_stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo = root / "repo"
                repo.mkdir()
                subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "tests@example.invalid"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
                allowed = repo / "allowed.txt"
                allowed.write_text("seed\n", encoding="utf-8", newline="\n")
                subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
                prompt = self.private_prompt(root)
                run_dir = root / "run"
                owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
                profile = self.profile()._replace(
                    name="openbuild_implementation_fast",
                    sandbox="workspace-write",
                )
                guardian = mock.Mock()
                guardian.poll.return_value = 1
                ready = {
                    "guardian_id": "guardian-private",
                    "guardian_pid": 999,
                    "guardian_identity": "guardian-created-1",
                    "provider": "windows-job",
                    "worker": {
                        "pid": 123,
                        "identity": "worker-created-1",
                        "process_group_id": 123,
                    },
                }
                fallback_process = mock.Mock(pid=321)
                fallback_process.poll.return_value = None

                def spawn_fallback(*_args: object, **_kwargs: object):
                    if fault_stage == "before-popen":
                        raise OSError("fallback Popen failed")
                    return fallback_process

                def bind_fallback(*args: object, **kwargs: object):
                    if fault_stage == "before-bind":
                        raise agent_runner.RecoveryStateError("injected failure before fallback bind")
                    if fault_stage == "mismatched-bind-receipt":
                        return {
                            "digest": "d" * 64,
                            "lease": {
                                "lease_id": "lease-1",
                                "lease_kind": "normal-fallback",
                                "recovery_capable": False,
                                "state": "ordinary-process-bound-unactivated",
                                "process_receipt": {"pid": 999, "identity": "wrong"},
                            },
                        }
                    result = agent_runner.RecoveryRegistry.bind_fallback_process_unactivated(
                        owner, *args, **kwargs
                    )
                    if fault_stage == "after-visible-bind":
                        raise agent_runner.RecoveryStateError(
                            "injected failure after visible fallback bind"
                        )
                    return result

                args = Namespace(
                    repo=str(repo),
                    prompt_file=str(prompt),
                    agent="openbuild_implementation_fast",
                    lease_id="lease-1",
                    allowed_file=["allowed.txt"],
                    specification_revision="R-029",
                    recovery_target_milestone="M2c-recovery",
                    run_dir=str(run_dir),
                    task_name="M2c-source",
                    activation_timeout=300.0,
                    codex_bin="codex",
                )
                identity = None if fault_stage == "after-popen" else "fallback-created-1"
                with mock.patch.object(
                    agent_runner, "validate_subscription_configuration"
                ), mock.patch.object(
                    agent_runner, "load_agent_profile", return_value=profile
                ), mock.patch.object(
                    agent_runner, "resolve_codex_binary", return_value="codex"
                ), mock.patch.object(
                    agent_runner, "require_chatgpt_login", return_value="chatgpt"
                ), mock.patch.object(
                    agent_runner, "is_git_repository", return_value=True
                ), mock.patch.object(
                    agent_runner, "recovery_registry_for_agent", return_value=owner
                ), mock.patch.object(
                    agent_runner, "spawn_containment_guardian", return_value=guardian
                ), mock.patch.object(
                    agent_runner, "await_guardian_launch", return_value=("ready", ready)
                ), mock.patch.object(
                    agent_runner,
                    "await_guardian_precommit",
                    return_value=(
                        "failed",
                        {
                            "guardian_id": "guardian-private",
                            "boundary_committed": False,
                            "tree_empty": True,
                            "no_user_code": True,
                            "failure": "ready-then-provider-loss",
                            "cleanup_error": None,
                        },
                    ),
                ), mock.patch.object(
                    agent_runner, "_spawn_worker_process", side_effect=spawn_fallback
                ), mock.patch.object(
                    agent_runner, "process_identity_from_popen", return_value=identity
                ), mock.patch.object(
                    owner, "bind_fallback_process_unactivated", side_effect=bind_fallback
                ), mock.patch.object(
                    agent_runner, "terminate_spawned_process"
                ), mock.patch.object(
                    agent_runner, "process_record_state", return_value="stopped"
                ), redirect_stdout(io.StringIO()):
                    with self.assertRaises(agent_runner.RunnerError):
                        agent_runner.start_run(args)

                state = json.loads(owner.path.read_text(encoding="utf-8"))
                self.assertEqual(state["quarantine"], "fallback-launch-ambiguous")
                expected_state = (
                    "ordinary-process-bound-unactivated"
                    if fault_stage == "after-visible-bind"
                    else "ordinary-fallback-claimed"
                )
                self.assertEqual(state["lease"]["state"], expected_state)
                if fault_stage == "after-visible-bind":
                    self.assertEqual(state["lease"]["process_receipt"]["pid"], 321)
                else:
                    self.assertNotIn("process_receipt", state["lease"])

    def test_reserved_recovery_target_uses_its_consumed_plan_without_normal_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            allowed = repo / "allowed.txt"
            allowed.write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            prompt_bytes = b"bounded recovery task\n"
            prompt = self.private_prompt(root, prompt_bytes)
            run_dir = root / "target-run"
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            checkpoint = owner.capture_checkpoint(
                source_id="source-1",
                source_lease_id="source-lease",
                source_receipt_digest="a" * 64,
                source_milestone="M2c-source",
                target_milestone="M2c-recovery",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            prompt_binding = agent_runner.acquire_owner_prompt_snapshot(repo, prompt, owner)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="b" * 64,
                specification_revision="R-029",
                prompt_snapshot_id=prompt_binding["prompt_snapshot_id"],
                prompt_sha256=prompt_binding["prompt_sha256"],
            )
            owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "target-lease",
                    "run_id": run_dir.name,
                    "prompt_snapshot_id": prompt_binding["prompt_snapshot_id"],
                    "prompt_sha256": agent_runner.sha256_bytes(prompt_bytes),
                    "launch_token": "c" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            profile = self.profile()._replace(
                name="openbuild_implementation_fast",
                sandbox="workspace-write",
            )
            guardian = mock.Mock()
            guardian.poll.return_value = None
            worker = {
                "pid": 123,
                "identity": "worker-created-1",
                "process_group_id": 123,
                "started_at": agent_runner.utc_now(),
            }
            ready = {
                "guardian_id": "guardian-private",
                "guardian_pid": 999,
                "guardian_identity": "guardian-created-1",
                "provider": "windows-job",
                "provider_plan_id": "provider-plan",
                "ipc_plan_id": "ipc-plan",
                "policy": "kill-on-close-no-breakaway",
                "active_processes": 1,
                "worker": worker,
            }

            def guardian_launch(*_args: object, **_kwargs: object):
                agent_runner.atomic_write_json(
                    run_dir / "codex.json",
                    {"pid": 456, "identity": "codex-created-1", "process_group_id": 456},
                )
                return "ready", ready

            def guardian_precommit(*_args: object, **_kwargs: object):
                provider_receipt = _provider_receipt(
                    guardian_id="guardian-private",
                    provider_plan_id="provider-plan",
                    ipc_plan_id="ipc-plan",
                    worker=worker,
                    precommit_nonce="precommit-2",
                )
                precommit = provider_receipt["precommit"]
                bound = owner.bind_process_unactivated(
                    "target-lease",
                    allowed_set_digest=checkpoint["allowed_set_digest"],
                    provider_receipt=provider_receipt,
                    process_receipt=worker,
                )
                return "ready", {**precommit, "registry_digest": bound["digest"]}

            args = Namespace(
                repo=str(repo),
                prompt_file=str(prompt),
                agent="openbuild_implementation_fast",
                lease_id="target-lease",
                allowed_file=["allowed.txt"],
                specification_revision="R-029",
                recovery_target_milestone="M2c-recovery-next",
                run_dir=str(run_dir),
                task_name="M2c-recovery",
                activation_timeout=300.0,
                codex_bin="codex",
            )
            public = {
                "status": "running",
                "activated": False,
                "codex_process_identity": "codex-created-1",
            }
            with mock.patch.object(agent_runner, "validate_subscription_configuration"), mock.patch.object(
                agent_runner, "load_agent_profile", return_value=profile
            ), mock.patch.object(agent_runner, "resolve_codex_binary", return_value="codex"), mock.patch.object(
                agent_runner, "require_chatgpt_login", return_value="chatgpt"
            ), mock.patch.object(agent_runner, "is_git_repository", return_value=True), mock.patch.object(
                agent_runner, "recovery_registry_for_agent", return_value=owner
            ), mock.patch.object(
                agent_runner, "spawn_containment_guardian", return_value=guardian
            ), mock.patch.object(
                agent_runner, "await_guardian_launch", side_effect=guardian_launch
            ), mock.patch.object(
                agent_runner,
                "await_guardian_precommit",
                side_effect=guardian_precommit,
            ), mock.patch.object(
                agent_runner, "public_receipt", return_value=public
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(agent_runner.start_run(args), 0)

            state = owner.state()
            self.assertEqual(state["lease"]["lease_kind"], "recovery-target")
            self.assertEqual(state["lease"]["state"], "process-bound-unactivated")
            request = agent_runner.read_json(run_dir / "request.json")
            self.assertTrue(request["recovery_target"])
            self.assertEqual(
                request["lifecycle_allowed_set_digest"],
                checkpoint["allowed_set_digest"],
            )
            self.assertEqual(
                request["recovery_parent_checkpoint"]["checkpoint_digest"],
                checkpoint["checkpoint_digest"],
            )

    def test_explicit_recovery_authorization_reserves_once_without_exposing_nonce(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            (repo / "allowed.txt").write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            checkpoint = owner.capture_checkpoint(
                source_id="source-1",
                source_lease_id="source-lease",
                source_receipt_digest="a" * 64,
                source_milestone="source",
                target_milestone="target",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            checkpoint_path = root / "checkpoint.json"
            agent_runner.atomic_write_json(checkpoint_path, checkpoint)
            prompt = self.private_prompt(root, b"bounded recovery\n")
            args = Namespace(
                repo=str(repo),
                checkpoint_file=str(checkpoint_path),
                prompt_file=str(prompt),
                run_dir=str(root / "target-run"),
                lease_id="target-lease",
                user_action_digest="b" * 64,
                specification_revision="R-029",
            )
            first_output = io.StringIO()
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=owner,
            ), redirect_stdout(first_output):
                self.assertEqual(agent_runner.authorize_recovery_run(args), 0)
            first = json.loads(first_output.getvalue())

            self.assertEqual(first["event"], "recovery-target-reserved")
            self.assertEqual(first["authorization"]["event"], "recovery-authorization-granted")
            self.assertNotIn("authorization_nonce", first_output.getvalue())
            self.assertEqual(owner.state()["lease"]["lease_kind"], "recovery-target")
            second_output = io.StringIO()
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=owner,
            ), redirect_stdout(second_output):
                self.assertEqual(agent_runner.authorize_recovery_run(args), 0)
            self.assertTrue(json.loads(second_output.getvalue())["reconstructed"])
            state = owner.state()
            self.assertEqual(len(state["consumed_grants"]), 1)
            plan = state["lease"]["plan"]
            source = owner._read_source_locked(state["lease"]["source_state_id"])
            authorization = source["authorization"]
            consumed = state["consumed_grants"][0]
            for field in ("prompt_snapshot_id", "prompt_sha256"):
                self.assertEqual(authorization[field], plan[field])
                self.assertEqual(consumed[field], plan[field])

            prior_digest = state["digest"]
            prompt.write_text("different prompt\n", encoding="utf-8", newline="\n")
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=owner,
            ), self.assertRaisesRegex(
                agent_runner.RunnerError, "prompt replay binding drifted"
            ):
                agent_runner.authorize_recovery_run(args)
            self.assertEqual(owner.state()["digest"], prior_digest)

    def test_recovery_target_terminal_success_verifies_parent_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            (repo / "allowed.txt").write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            prompt_bytes = b"terminal recovery prompt\n"
            prompt_binding = agent_runner.stage_owner_prompt_snapshot(
                owner, prompt_bytes
            )
            parent = owner.capture_checkpoint(
                source_id="source-1",
                source_lease_id="source-lease",
                source_receipt_digest="a" * 64,
                source_milestone="source",
                target_milestone="target",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            parent = owner.revalidate_checkpoint(parent)
            grant = owner.grant_authorization(
                parent,
                user_action_digest="b" * 64,
                specification_revision="R-029",
                prompt_snapshot_id=prompt_binding["prompt_snapshot_id"],
                prompt_sha256=prompt_binding["prompt_sha256"],
            )
            owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=parent,
                target_plan={
                    "lease_id": "target-lease",
                    "run_id": "run",
                    "prompt_snapshot_id": prompt_binding["prompt_snapshot_id"],
                    "prompt_sha256": prompt_binding["prompt_sha256"],
                    "launch_token": "d" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": parent["allowed_set_digest"],
                },
            )
            current = owner.prepare_source_checkpoint(
                source_id="target-source",
                source_lease_id="target-lease",
                source_milestone="target",
                target_milestone="target-next",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            owner.claim_launch("target-lease", "d" * 64)
            owner.bind_process_unactivated(
                "target-lease",
                allowed_set_digest=parent["allowed_set_digest"],
                provider_receipt=_provider_receipt(),
                process_receipt=_process_receipt(),
            )
            owner.commit_activation("target-lease", parent["allowed_set_digest"])
            run_dir = root / "run"
            agent_runner.ensure_private_run_dir(run_dir)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "profile": {"name": "openbuild_implementation_fast"},
                    "repo": str(repo),
                    "lease_id": "target-lease",
                    "recovery_preflight": current,
                    "recovery_parent_checkpoint": parent,
                    "lifecycle_allowed_set_digest": parent["allowed_set_digest"],
                    **self.private_run_request_identity(run_dir),
                },
            )
            secret = bytes.fromhex("66" * 32)
            agent_runner.atomic_write_bytes(run_dir / "guardian.key", secret)
            for filename, kind, payload in [
                (
                    "guardian-zero.json",
                    "guardian-zero",
                    _zero_proof(),
                ),
                (
                    "guardian-closed.json",
                    "guardian-closed",
                    _guardian_close(),
                ),
            ]:
                agent_runner.write_guardian_message(run_dir / filename, secret, kind, payload)
            receipt = {
                "run_dir": str(run_dir),
                "status": "completed",
                "agent_name": "openbuild_implementation_fast",
                "task_name": "target",
                "lease_id": "target-lease",
                "activated": True,
                "configured_model": "fixture",
                "model_reasoning_effort": "medium",
                "sandbox": "workspace-write",
                "worker_pid": 123,
                "worker_process_identity": "worker-1",
                "codex_pid": 456,
                "codex_process_identity": "codex-1",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
                "process_tree_stopped": True,
            }
            with mock.patch.object(
                agent_runner,
                "recovery_registry_for_agent",
                return_value=owner,
            ):
                agent_runner.reconcile_implementation_registry(
                    run_dir,
                    receipt,
                    success_verification_digest="f" * 64,
                )

            self.assertIsNone(owner.state()["lease"])
            self.assertTrue((run_dir / "recovery-parent-verification.json").is_file())
            self.assertTrue((run_dir / "implementation-handoffs.jsonl").is_file())
            source = owner.read_private_source(parent["source_state_id"])
            self.assertIsNone(source["authorization"])
            self.assertTrue(
                any(
                    event.get("event") == "authorization-retired"
                    and event.get("grant_id") == grant["grant_id"]
                    for event in owner.state()["history"]
                )
            )
            self.assertFalse(
                (
                    agent_runner._prompt_snapshot_paths(owner)[1]
                    / f"{prompt_binding['prompt_snapshot_id']}.blob"
                ).exists()
            )

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

    def test_ac01_ac02_ac19_ac21_ac22_external_prompt_is_stably_imported_before_owner_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            inside = repo / "prompt.md"
            inside.write_text("inside\n", encoding="utf-8", newline="\n")
            inside.chmod(0o600)
            broad_directory = root / "broad-owner"
            agent_runner.ensure_private_run_dir(broad_directory)
            broad = broad_directory / "prompt.md"
            broad.write_bytes(b"broad prompt\n")
            if os.name != "nt":
                broad.chmod(0o644)
            external = self.private_prompt(root, b"private prompt\n")
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")

            with self.assertRaisesRegex(agent_runner.RunnerError, "prompt-inside-workspace"):
                agent_runner.acquire_owner_prompt_snapshot(repo, inside, owner)
            with self.assertRaisesRegex(
                agent_runner.RunnerError,
                "prompt-owner-untrusted|prompt-permissions-too-broad",
            ):
                agent_runner.acquire_owner_prompt_snapshot(repo, broad, owner)
            self.assertFalse(owner.path.exists())

            snapshot = agent_runner.acquire_owner_prompt_snapshot(repo, external, owner)
            external.write_text("swapped\n", encoding="utf-8", newline="\n")
            loaded = agent_runner.read_owner_prompt_snapshot(
                owner, snapshot["prompt_snapshot_id"], snapshot["prompt_sha256"]
            )

            self.assertEqual(loaded, "private prompt\n")
            self.assertRegex(snapshot["prompt_snapshot_id"], r"^[0-9a-f]{64}$")
            self.assertNotIn(str(external), json.dumps(snapshot, sort_keys=True))
            self.assertEqual(
                agent_runner.collect_owner_prompt_snapshot_references(owner)["orphan-unreferenced"],
                {snapshot["prompt_snapshot_id"]},
            )

    def test_ac20_ac22_staged_prompt_is_cross_bound_retired_and_collected_without_run_artifact_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Tests"], cwd=repo, check=True
            )
            (repo / "allowed.txt").write_text(
                "seed\n", encoding="utf-8", newline="\n"
            )
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "baseline"],
                cwd=repo,
                check=True,
            )
            owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
            owner.initialize()
            prompt_bytes = b"staged recovery prompt\n"
            binding = agent_runner.stage_owner_prompt_snapshot(owner, prompt_bytes)
            self.assertEqual(
                agent_runner.stage_owner_prompt_snapshot(owner, prompt_bytes), binding
            )
            released = owner.mark_prompt_snapshot_released(
                binding["prompt_snapshot_id"], binding["prompt_sha256"]
            )
            self.assertEqual(
                owner.mark_prompt_snapshot_released(
                    binding["prompt_snapshot_id"], binding["prompt_sha256"]
                )["digest"],
                released["digest"],
            )
            self.assertIn(
                binding["prompt_snapshot_id"],
                agent_runner.collect_owner_prompt_snapshot_references(owner)["released"],
            )
            checkpoint = owner.capture_checkpoint(
                source_id="source-1",
                source_lease_id="source-lease",
                source_receipt_digest="a" * 64,
                source_milestone="source",
                target_milestone="target",
                allowed_paths=["allowed.txt"],
                specification_revision="R-029",
            )
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="b" * 64,
                specification_revision="R-029",
                prompt_snapshot_id=binding["prompt_snapshot_id"],
                prompt_sha256=binding["prompt_sha256"],
            )
            grant_references = agent_runner.collect_owner_prompt_snapshot_references(owner)
            self.assertIn(
                binding["prompt_snapshot_id"], grant_references["grant-referenced"]
            )
            self.assertNotIn(binding["prompt_snapshot_id"], grant_references["released"])
            self.assertEqual(agent_runner.garbage_collect_owner_prompt_snapshots(owner), set())
            self.assertEqual(
                agent_runner.read_owner_prompt_snapshot(
                    owner, binding["prompt_snapshot_id"], binding["prompt_sha256"]
                ),
                prompt_bytes.decode("utf-8"),
            )
            owner.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": "target-lease",
                    "run_id": "target-run",
                    "prompt_snapshot_id": binding["prompt_snapshot_id"],
                    "prompt_sha256": binding["prompt_sha256"],
                    "launch_token": "c" * 64,
                    "provider_plan_id": "provider-plan",
                    "ipc_plan_id": "ipc-plan",
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            self.assertIn(
                binding["prompt_snapshot_id"],
                agent_runner.collect_owner_prompt_snapshot_references(owner)[
                    "lease-referenced"
                ],
            )
            self.assertEqual(agent_runner.garbage_collect_owner_prompt_snapshots(owner), set())

            run_dir = root / "target-run"
            agent_runner.ensure_private_run_dir(run_dir)
            run_prompt = run_dir / "prompt.md"
            agent_runner.atomic_write_bytes(run_prompt, prompt_bytes)
            owner.claim_launch("target-lease", "c" * 64)
            owner.fail_recovery_target_before_boundary(
                "target-lease",
                "fixture-stop",
                {"tree_empty": True, "no_user_code": True},
            )
            retired = owner.retire_authorization(
                source_state_id=checkpoint["source_state_id"],
                grant_id=grant["grant_id"],
            )
            self.assertEqual(retired["history"][-1]["event"], "authorization-retired")
            self.assertEqual(
                owner.retire_authorization(
                    source_state_id=checkpoint["source_state_id"],
                    grant_id=grant["grant_id"],
                )["digest"],
                retired["digest"],
            )
            self.assertEqual(
                agent_runner.garbage_collect_owner_prompt_snapshots(owner),
                {binding["prompt_snapshot_id"]},
            )
            self.assertEqual(run_prompt.read_bytes(), prompt_bytes)

    def test_ac14_ac22_prompt_gc_fails_closed_on_invalid_private_source(self) -> None:
        mutations = {
            "unknown-field": lambda value: value.__setitem__("unknown_private", True),
            "malformed-authorization": lambda value: value.__setitem__(
                "authorization", {"prompt_snapshot_id": "a" * 64}
            ),
            "digest-drift": lambda value: value.__setitem__("digest", "0" * 64),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repo = root / "repo"
                repo.mkdir()
                subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "tests@example.invalid"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Tests"], cwd=repo, check=True
                )
                (repo / "allowed.txt").write_text(
                    "seed\n", encoding="utf-8", newline="\n"
                )
                subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "commit", "--quiet", "-m", "baseline"],
                    cwd=repo,
                    check=True,
                )
                owner = agent_runner.RecoveryRegistry(repo, state_root=root / "state")
                owner.initialize()
                binding = agent_runner.stage_owner_prompt_snapshot(
                    owner, b"private source GC prompt\n"
                )
                checkpoint = owner.capture_checkpoint(
                    source_id=f"source-{label}",
                    source_lease_id="source-lease",
                    source_receipt_digest="a" * 64,
                    source_milestone="source",
                    target_milestone="target",
                    allowed_paths=["allowed.txt"],
                    specification_revision="R-005",
                )
                checkpoint = owner.revalidate_checkpoint(checkpoint)
                owner.grant_authorization(
                    checkpoint,
                    user_action_digest="b" * 64,
                    specification_revision="R-005",
                    prompt_snapshot_id=binding["prompt_snapshot_id"],
                    prompt_sha256=binding["prompt_sha256"],
                )
                source_path = owner.source_path(checkpoint["source_state_id"])
                source = agent_runner.read_json(source_path)
                mutate(source)
                if label != "digest-drift":
                    canonical = dict(source)
                    canonical.pop("digest", None)
                    source["digest"] = agent_runner.sha256_bytes(
                        agent_runner._canonical_json_bytes(canonical)
                    )
                agent_runner.atomic_write_json(source_path, source)
                blob = (
                    agent_runner._prompt_snapshot_paths(owner)[1]
                    / f"{binding['prompt_snapshot_id']}.blob"
                )
                with self.assertRaisesRegex(
                    agent_runner.RunnerError, "reference state is unreadable"
                ):
                    agent_runner.garbage_collect_owner_prompt_snapshots(owner)
                self.assertTrue(blob.is_file())

    def test_ac20_blob_grant_and_reservation_faults_preserve_one_prompt_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
            (repo / "allowed.txt").write_text("seed\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "allowed.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repo, check=True)
            state_root = root / "state"
            owner = agent_runner.RecoveryRegistry(repo, state_root=state_root)
            owner.initialize()
            agent_runner._prompt_snapshot_key(owner)
            prompt_bytes = b"fault-bound prompt\n"
            for fault_stage in (
                "before-write",
                "after-file-fsync",
                "after-replace",
                "before-metadata-barrier",
                "after-metadata-barrier",
            ):
                faulting_owner = agent_runner.RecoveryRegistry(
                    repo, state_root=state_root, fault=fault_stage
                )
                with self.subTest(fault_stage=fault_stage), self.assertRaisesRegex(
                    agent_runner.RunnerError, "durable prompt snapshot"
                ):
                    agent_runner.stage_owner_prompt_snapshot(
                        faulting_owner, prompt_bytes
                    )
                binding = agent_runner.stage_owner_prompt_snapshot(owner, prompt_bytes)
                self.assertEqual(
                    agent_runner.read_owner_prompt_snapshot(
                        owner,
                        binding["prompt_snapshot_id"],
                        binding["prompt_sha256"],
                    ),
                    prompt_bytes.decode("utf-8"),
                )
            binding = agent_runner.stage_owner_prompt_snapshot(owner, prompt_bytes)

            checkpoint = owner.capture_checkpoint(
                source_id="fault-source",
                source_lease_id="source-lease",
                source_receipt_digest="a" * 64,
                source_milestone="source",
                target_milestone="target",
                allowed_paths=["allowed.txt"],
                specification_revision="R-005",
            )
            checkpoint = owner.revalidate_checkpoint(checkpoint)
            faulting_grant_owner = agent_runner.RecoveryRegistry(
                repo, state_root=state_root, fault="after-replace"
            )
            with self.assertRaises(agent_runner.RecoveryStateError):
                faulting_grant_owner.grant_authorization(
                    checkpoint,
                    user_action_digest="b" * 64,
                    specification_revision="R-005",
                    prompt_snapshot_id=binding["prompt_snapshot_id"],
                    prompt_sha256=binding["prompt_sha256"],
                )
            owner = agent_runner.RecoveryRegistry(repo, state_root=state_root)
            grant = owner.grant_authorization(
                checkpoint,
                user_action_digest="b" * 64,
                specification_revision="R-005",
                prompt_snapshot_id=binding["prompt_snapshot_id"],
                prompt_sha256=binding["prompt_sha256"],
            )
            private_grant = owner.read_private_source(checkpoint["source_state_id"])[
                "authorization"
            ]
            self.assertEqual(
                private_grant["prompt_snapshot_id"], binding["prompt_snapshot_id"]
            )
            self.assertEqual(private_grant["prompt_sha256"], binding["prompt_sha256"])

            plan = {
                "lease_id": "target-lease",
                "run_id": "target-run",
                "prompt_snapshot_id": binding["prompt_snapshot_id"],
                "prompt_sha256": binding["prompt_sha256"],
                "launch_token": "c" * 64,
                "provider_plan_id": "provider-plan",
                "ipc_plan_id": "ipc-plan",
                "allowed_set_digest": checkpoint["allowed_set_digest"],
            }
            faulting_reservation_owner = agent_runner.RecoveryRegistry(
                repo, state_root=state_root, fault="after-replace"
            )
            with self.assertRaises(agent_runner.RecoveryStateError):
                faulting_reservation_owner.consume_grant_and_reserve(
                    grant_id=grant["grant_id"],
                    checkpoint=checkpoint,
                    target_plan=plan,
                )
            reserved = agent_runner.RecoveryRegistry(repo, state_root=state_root).state()
            self.assertEqual(reserved["lease"]["plan"], plan)
            self.assertEqual(
                reserved["consumed_grants"][-1]["prompt_snapshot_id"],
                binding["prompt_snapshot_id"],
            )
            self.assertEqual(
                agent_runner.garbage_collect_owner_prompt_snapshots(
                    agent_runner.RecoveryRegistry(repo, state_root=state_root)
                ),
                set(),
            )

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

    def test_dispatch_starts_then_immediately_activates_the_same_run(self) -> None:
        args = Namespace(run_dir=str(ROOT))
        with mock.patch.object(agent_runner, "start_run", return_value=0) as start, mock.patch.object(
            agent_runner, "activate_run", return_value=0
        ) as activate, mock.patch.object(
            agent_runner, "read_json", return_value={"status": "running", "activated": False}
        ):
            self.assertEqual(agent_runner.dispatch_run(args), 0)

        start.assert_called_once_with(args)
        activate.assert_called_once()
        self.assertEqual(Path(activate.call_args.args[0].run_dir).resolve(), ROOT.resolve())

    def test_dispatch_emits_only_the_activated_receipt(self) -> None:
        args = Namespace(run_dir=str(ROOT))

        def receipt(path: Path) -> dict[str, object]:
            if path.name == "dispatch-unactivated-receipt.json":
                return {"status": "running", "activated": False}
            if path.name == "dispatch-activated-receipt.json":
                return {"status": "running", "activated": True}
            raise AssertionError(path)

        output = io.StringIO()
        with mock.patch.object(
            agent_runner, "start_run", side_effect=lambda _args: print('{"activated": false}') or 0
        ), mock.patch.object(
            agent_runner, "activate_run", side_effect=lambda _args: print('{"activated": true}') or 0
        ), mock.patch.object(agent_runner, "read_json", side_effect=receipt), redirect_stdout(output):
            self.assertEqual(agent_runner.dispatch_run(args), 0)

        self.assertEqual(json.loads(output.getvalue()), {"status": "running", "activated": True})

    def test_dispatch_allocates_one_run_before_starting_when_none_is_supplied(self) -> None:
        args = Namespace(run_dir=None)
        run_dir = ROOT / ".tmp" / "dispatch-fixture"
        with mock.patch.object(agent_runner, "default_run_dir", return_value=run_dir), mock.patch.object(
            agent_runner, "start_run", return_value=0
        ) as start, mock.patch.object(agent_runner, "activate_run", return_value=0) as activate, mock.patch.object(
            agent_runner, "read_json", return_value={"status": "running", "activated": False}
        ):
            self.assertEqual(agent_runner.dispatch_run(args), 0)

        self.assertEqual(args.run_dir, str(run_dir.resolve()))
        start.assert_called_once_with(args)
        self.assertEqual(activate.call_args.args[0].run_dir, str(run_dir.resolve()))

    def test_generated_run_handle_resolves_only_inside_private_run_root(self) -> None:
        handle = "20260717T120000Z-0123456789"
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            agent_runner,
            "default_run_root",
            return_value=Path(temp),
        ):
            self.assertEqual(
                agent_runner.resolve_run_reference(handle),
                (Path(temp) / handle).resolve(),
            )
            explicit = Path(temp) / "caller-owned-run"
            self.assertEqual(
                agent_runner.resolve_run_reference(str(explicit)),
                explicit.resolve(),
            )

    def test_activation_window_is_an_immutable_nine_hundred_second_budget(self) -> None:
        window = agent_runner.activation_window(
            datetime(2026, 7, 16, 12, 0, 0, 123456, tzinfo=timezone.utc)
        )

        self.assertEqual(window["activated_at"], "2026-07-16T12:00:00.123456Z")
        self.assertEqual(window["observation_started_at"], window["activated_at"])
        self.assertEqual(window["observation_deadline_at"], "2026-07-16T12:15:00.123456Z")

    def test_dispatch_is_the_new_parser_command_while_start_and_activate_remain_available(self) -> None:
        parser = agent_runner.build_parser()

        self.assertIs(
            parser.parse_args(
                [
                    "dispatch",
                    "--agent",
                    "openbuild_review_fast",
                    "--task-name",
                    "fixture",
                    "--repo",
                    ".",
                    "--prompt-file",
                    "prompt.md",
                ]
            ).handler,
            agent_runner.dispatch_run,
        )
        self.assertIs(parser.parse_args(["start", "--agent", "openbuild_review_fast", "--task-name", "fixture", "--repo", ".", "--prompt-file", "prompt.md"]).handler, agent_runner.start_run)
        self.assertIs(
            parser.parse_args(
                [
                    "dispatch",
                    "--agent",
                    "openbuild_review_fast",
                    "--task-name",
                    "staged-fixture",
                    "--repo",
                    ".",
                    "--prompt-snapshot-id",
                    "a" * 64,
                    "--prompt-sha256",
                    "b" * 64,
                ]
            ).handler,
            agent_runner.dispatch_run,
        )
        self.assertIs(
            parser.parse_args(["stage-prompt", "--repo", "."]).handler,
            agent_runner.stage_prompt_run,
        )
        self.assertIs(
            parser.parse_args(["activate", "--run-dir", "."]).handler,
            agent_runner.activate_run,
        )

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

    def test_structured_error_after_turn_started_is_not_availability_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            self.write_events(
                events,
                {"type": "thread.started", "thread_id": "thread-2"},
                {"type": "turn.started"},
                {
                    "type": "turn.failed",
                    "error": {
                        "type": "usage_limit_exceeded",
                        "rate_limits": {"limit_name": "gpt-5.3-codex-spark"},
                    },
                },
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertTrue(evidence["turn_started"])
            self.assertEqual(evidence["structured_errors"], [])

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

    def test_structured_availability_error_followed_by_malformed_jsonl_is_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            events.write_text(
                '{"type":"error","error":{"code":"model_not_found","model":"gpt-5.3-codex-spark"}}\nnot-json\n',
                encoding="utf-8",
                newline="\n",
            )

            evidence = agent_runner.read_event_evidence(events)

            self.assertEqual(len(evidence["structured_errors"]), 1)
            self.assertIsNotNone(evidence["event_error"])
            self.assertFalse(
                agent_runner.search_availability_event_stream_is_eligible(evidence)
            )

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

    def test_public_receipt_redacts_private_run_profile_and_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "20260717T120000Z-0123456789"
            run_dir.mkdir()
            profile_source = run_dir / "private-profile.toml"
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "privacy_boundary",
                    "profile_source": str(profile_source),
                    "auth_mode": "chatgpt",
                    "prompt_sha256": "a" * 64,
                    "profile": {
                        "name": "openbuild_review_strong",
                        "model": "selected-model",
                        "reasoning_effort": "high",
                        "sandbox": "read-only",
                    },
                },
            )

            with mock.patch.object(
                agent_runner,
                "default_run_root",
                return_value=run_dir.parent,
            ):
                receipt = agent_runner.public_receipt(run_dir)

            rendered = json.dumps(receipt)
            self.assertEqual(receipt["run_handle"], run_dir.name)
            self.assertEqual(receipt["prompt_source_classification"], "owner-private-snapshot")
            self.assertEqual(receipt["prompt_sha256"], "a" * 64)
            self.assertNotIn("run_dir", receipt)
            self.assertNotIn("profile_source", receipt)
            self.assertNotIn("artifacts", receipt)
            self.assertNotIn(str(run_dir), rendered)
            self.assertNotIn(str(profile_source), rendered)
            self.assertNotIn("events.jsonl", rendered)

    def test_public_failure_message_is_a_closed_classification_for_every_private_source(self) -> None:
        sensitive = f"{ROOT} private-snapshot-{'a' * 64} raw prompt fragment"
        cases = [
            (
                "agent-terminal-failure",
                {"failure_message": sensitive, "event_error": None, "completed": False},
                None,
                {},
                "failed",
                "missing",
            ),
            (
                "event-stream-invalid",
                {"failure_message": None, "event_error": sensitive, "completed": False},
                None,
                {},
                "failed",
                "missing",
            ),
            (
                "result-evidence-invalid",
                {"failure_message": None, "event_error": None, "completed": True},
                sensitive,
                {},
                "failed",
                "valid",
            ),
            (
                "runner-failure",
                {"failure_message": None, "event_error": None, "completed": False},
                None,
                {"failure_message": sensitive},
                "failed",
                "missing",
            ),
            (
                "codex-exit-evidence-invalid",
                {"failure_message": None, "event_error": None, "completed": True},
                None,
                {},
                "failed",
                "identity-mismatch",
            ),
            (
                "terminal-record-missing",
                {"failure_message": None, "event_error": None, "completed": False},
                None,
                {},
                "failed",
                "missing",
            ),
        ]
        for expected, evidence, result_error, exit_record, status, exit_status in cases:
            with self.subTest(expected=expected):
                value = agent_runner.classify_public_failure(
                    evidence=evidence,
                    result_error=result_error,
                    exit_record=exit_record,
                    status=status,
                    codex_exit_status=exit_status,
                )
                self.assertEqual(value, expected)
                self.assertNotIn(sensitive, json.dumps(value))

        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "failure-privacy",
                    "profile_source": sensitive,
                    "auth_mode": "chatgpt",
                    "prompt_sha256": "a" * 64,
                    "profile": {
                        "name": "openbuild_review_strong",
                        "model": "selected-model",
                        "reasoning_effort": "high",
                        "sandbox": "read-only",
                    },
                },
            )
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "turn.failed", "error": {"message": sensitive}},
            )
            agent_runner.atomic_write_json(
                run_dir / "exit.json",
                {
                    "success": False,
                    "failure_message": sensitive,
                    "startup_process_stopped": True,
                },
            )
            receipt = agent_runner.public_receipt(run_dir)
            self.assertEqual(receipt["failure_message"], "agent-terminal-failure")
            self.assertNotIn(sensitive, json.dumps(receipt))

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
            self.assertEqual(receipt["failure_message"], "result-evidence-invalid")

    def test_completed_search_with_invalid_result_cannot_authorize_availability_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "invalid_search_result",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "search_fallback_source": None,
                    "search_fallback_binding": {"reason": "model-unavailable"},
                    "profile": {
                        "name": "openbuild_search_separate",
                        "model": "gpt-5.3-codex-spark",
                        "reasoning_effort": "low",
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
            agent_runner.atomic_write_json(
                run_dir / "codex-exit.json",
                {"pid": 222, "identity": "codex-id", "exit_code": 0},
            )
            self.write_events(
                run_dir / "events.jsonl",
                {"type": "thread.started", "thread_id": "thread-invalid-search"},
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
                {"type": "turn.completed", "usage": {"output_tokens": 1}},
            )

            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                receipt = agent_runner.public_receipt(run_dir)

            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["failure_message"], "result-evidence-invalid")
            self.assertIsNone(receipt["transport_failure_reason"])

    def test_mixed_pre_turn_failures_cannot_authorize_availability_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "mixed_search_failure",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "search_fallback_source": None,
                    "profile": {
                        "name": "openbuild_search_separate",
                        "model": "gpt-5.3-codex-spark",
                        "reasoning_effort": "low",
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
                run_dir / "exit.json",
                {"success": False, "failure_message": "codex exec exited with code 1"},
            )
            self.write_events(
                run_dir / "events.jsonl",
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
                {"type": "error", "error": {"code": "authentication_failed"}},
            )

            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                receipt = agent_runner.public_receipt(run_dir)

            self.assertEqual(receipt["status"], "failed")
            self.assertIsNone(receipt["transport_failure_reason"])

            for raw_error in (
                {
                    "type": "usage_limit_exceeded",
                    "rate_limits": {"limit_name": "gpt-5.3-codex-spark"},
                },
                {"code": "authentication_failed"},
                {"type": "item.completed", "code": "authentication_failed"},
                {"type": "unknown_failure"},
            ):
                with self.subTest(raw_error=raw_error):
                    self.write_events(
                        run_dir / "events.jsonl",
                        {
                            "type": "error",
                            "error": {
                                "code": "model_not_found",
                                "model": "gpt-5.3-codex-spark",
                            },
                        },
                        raw_error,
                    )
                    with mock.patch.object(
                        agent_runner, "process_record_state", return_value="stopped"
                    ):
                        receipt = agent_runner.public_receipt(run_dir)
                    self.assertEqual(receipt["status"], "failed")
                    self.assertIsNone(receipt["transport_failure_reason"])

            self.write_events(
                run_dir / "events.jsonl",
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
            )
            (run_dir / "stderr.log").write_text(
                json.dumps({"code": "authentication_failed"}) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                receipt = agent_runner.public_receipt(run_dir)
            self.assertEqual(receipt["status"], "failed")
            self.assertIsNone(receipt["transport_failure_reason"])

            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            self.write_events(
                run_dir / "events.jsonl",
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
                {"type": "item.failed", "error": {"code": "network_error"}},
            )
            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                receipt = agent_runner.public_receipt(run_dir)
            self.assertEqual(receipt["status"], "failed")
            self.assertIsNone(receipt["transport_failure_reason"])

            self.write_events(
                run_dir / "events.jsonl",
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
            )
            for malformed_stderr in (b"not-json\n", b"\xff"):
                with self.subTest(malformed_stderr=malformed_stderr):
                    (run_dir / "stderr.log").write_bytes(malformed_stderr)
                    with mock.patch.object(
                        agent_runner, "process_record_state", return_value="stopped"
                    ):
                        receipt = agent_runner.public_receipt(run_dir)
                    self.assertEqual(receipt["status"], "failed")
                    self.assertIsNone(receipt["transport_failure_reason"])

            (run_dir / "stderr.log").unlink()
            (run_dir / "stderr.log").mkdir()
            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                receipt = agent_runner.public_receipt(run_dir)
            self.assertEqual(receipt["status"], "failed")
            self.assertIsNone(receipt["transport_failure_reason"])

    def test_availability_receipt_requires_clean_runner_and_bound_codex_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "clean_search_failure",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "search_fallback_source": None,
                    "profile": {
                        "name": "openbuild_search_separate",
                        "model": "gpt-5.3-codex-spark",
                        "reasoning_effort": "low",
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
            clean_exit = {
                "success": False,
                "terminal_event": None,
                "exit_code": 1,
                "failure_message": "codex exec exited with code 1",
                "cleanup_errors": [],
            }
            agent_runner.atomic_write_json(run_dir / "exit.json", clean_exit)
            self.write_events(
                run_dir / "events.jsonl",
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
            )

            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                missing = agent_runner.public_receipt(run_dir)
                self.assertEqual(missing["codex_exit_evidence"], "missing")
                self.assertIsNone(missing["transport_failure_reason"])

                (run_dir / "codex-exit.json").write_text(
                    "not-json\n", encoding="utf-8", newline="\n"
                )
                malformed = agent_runner.public_receipt(run_dir)
                self.assertEqual(malformed["codex_exit_evidence"], "malformed")
                self.assertIsNone(malformed["transport_failure_reason"])

                agent_runner.atomic_write_json(
                    run_dir / "codex-exit.json",
                    {"pid": 222, "identity": "codex-id", "exit_code": 1},
                )
                agent_runner.atomic_write_json(
                    run_dir / "exit.json",
                    {**clean_exit, "cleanup_errors": ["runner cleanup failed"]},
                )
                cleanup_failed = agent_runner.public_receipt(run_dir)
                self.assertIsNone(cleanup_failed["transport_failure_reason"])

                request = agent_runner.read_json(run_dir / "request.json")
                request["search_fallback_binding"] = {
                    "reason": "model-unavailable",
                    "source_handle_sha256": "a" * 64,
                }
                agent_runner.atomic_write_json(run_dir / "request.json", request)
                injected_binding = agent_runner.public_receipt(run_dir)
                self.assertIsNone(injected_binding["transport_failure_reason"])
                request["search_fallback_binding"] = None
                agent_runner.atomic_write_json(run_dir / "request.json", request)

                agent_runner.atomic_write_json(
                    run_dir / "exit.json",
                    {**clean_exit, "failure_message": "runner cleanup failed"},
                )
                runner_failed = agent_runner.public_receipt(run_dir)
                self.assertIsNone(runner_failed["transport_failure_reason"])

                agent_runner.atomic_write_json(run_dir / "exit.json", clean_exit)
                eligible = agent_runner.public_receipt(run_dir)
                self.assertEqual(eligible["codex_exit_evidence"], "valid")
                self.assertEqual(eligible["transport_failure_reason"], "model-unavailable")

    def test_nonregular_result_artifact_cannot_authorize_availability_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "nonregular_search_result",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "search_fallback_source": None,
                    "profile": {
                        "name": "openbuild_search_separate",
                        "model": "gpt-5.3-codex-spark",
                        "reasoning_effort": "low",
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
                run_dir / "exit.json",
                {"success": False, "failure_message": "codex exec exited with code 1"},
            )
            self.write_events(
                run_dir / "events.jsonl",
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                },
            )
            result_path = run_dir / "result.md"

            result_path.mkdir()
            with mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                directory_receipt = agent_runner.public_receipt(run_dir)
            self.assertEqual(directory_receipt["result_evidence"], "invalid")
            self.assertIsNone(directory_receipt["transport_failure_reason"])
            result_path.rmdir()

            try:
                result_path.symlink_to(run_dir / "missing-result-target")
            except OSError:
                symlink_metadata = os.stat_result(
                    (agent_runner.stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                )
                lstat_context = mock.patch.object(
                    Path, "lstat", return_value=symlink_metadata
                )
            else:
                lstat_context = mock.patch.object(Path, "lstat", wraps=Path.lstat)
            with lstat_context, mock.patch.object(
                agent_runner, "process_record_state", return_value="stopped"
            ):
                symlink_receipt = agent_runner.public_receipt(run_dir)
            self.assertEqual(symlink_receipt["result_evidence"], "invalid")
            self.assertIsNone(symlink_receipt["transport_failure_reason"])

    def test_nonregular_structured_evidence_cannot_authorize_availability_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            agent_runner.atomic_write_json(
                run_dir / "request.json",
                {
                    "task_name": "nonregular_structured_evidence",
                    "profile_source": "profile.toml",
                    "auth_mode": "chatgpt",
                    "search_fallback_source": None,
                    "profile": {
                        "name": "openbuild_search_separate",
                        "model": "gpt-5.3-codex-spark",
                        "reasoning_effort": "low",
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
                run_dir / "exit.json",
                {"success": False, "failure_message": "codex exec exited with code 1"},
            )
            eligible = {
                "type": "error",
                "error": {
                    "code": "model_not_found",
                    "model": "gpt-5.3-codex-spark",
                },
            }
            original_lstat = Path.lstat

            def receipt_with_mode(target_name: str, mode: int | None) -> dict[str, object]:
                events_path = run_dir / "events.jsonl"
                stderr_path = run_dir / "stderr.log"
                for path in (events_path, stderr_path):
                    if path.is_dir():
                        path.rmdir()
                    elif path.exists() or path.is_symlink():
                        path.unlink()
                target = run_dir / target_name
                if target_name == "stderr.log":
                    self.write_events(events_path, eligible)
                else:
                    stderr_path.write_text(json.dumps(eligible) + "\n", encoding="utf-8")
                if mode is None:
                    target.mkdir()
                    lstat_context = nullcontext()
                else:
                    metadata = os.stat_result((mode, 0, 0, 0, 0, 0, 0, 0, 0, 0))

                    def fake_lstat(path: Path) -> os.stat_result:
                        if path == target:
                            return metadata
                        return original_lstat(path)

                    lstat_context = mock.patch.object(
                        Path, "lstat", autospec=True, side_effect=fake_lstat
                    )
                with lstat_context, mock.patch.object(
                    agent_runner, "process_record_state", return_value="stopped"
                ):
                    return agent_runner.public_receipt(run_dir)

            for target_name in ("events.jsonl", "stderr.log"):
                for label, mode in (
                    ("directory", None),
                    ("broken-symlink", agent_runner.stat.S_IFLNK),
                    ("fifo", agent_runner.stat.S_IFIFO),
                ):
                    with self.subTest(target=target_name, object_type=label):
                        receipt = receipt_with_mode(target_name, mode)
                        self.assertEqual(receipt["status"], "failed")
                        self.assertIsNone(receipt["transport_failure_reason"])

    def test_artifact_readers_reject_regular_file_replacement_between_check_and_open(
        self,
    ) -> None:
        readers = {
            "events.jsonl": lambda path: agent_runner.read_event_evidence(path)[
                "event_error"
            ]
            is not None,
            "stderr.log": lambda path: agent_runner._read_structured_stderr(path)[1]
            is False,
            "result.md": lambda path: agent_runner.final_result_error(path) is not None,
        }
        payloads = {
            "events.jsonl": json.dumps(
                {
                    "type": "error",
                    "error": {
                        "code": "model_not_found",
                        "model": "gpt-5.3-codex-spark",
                    },
                }
            )
            + "\n",
            "stderr.log": json.dumps(
                {
                    "code": "model_not_found",
                    "model": "gpt-5.3-codex-spark",
                }
            )
            + "\n",
            "result.md": "valid-looking result\n",
        }
        reader_os = agent_runner.read_regular_file_no_follow.__globals__["os"]

        for name, reader in readers.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / name
                replacement = root / f"replacement-{name}"
                original = root / f"original-{name}"
                target.write_text(payloads[name], encoding="utf-8", newline="\n")
                replacement.write_text(payloads[name], encoding="utf-8", newline="\n")
                real_open = reader_os.open
                swapped = False

                def swap_before_open(
                    path: object,
                    flags: int,
                    *args: object,
                ) -> int:
                    nonlocal swapped
                    if not swapped and Path(path) == target:
                        swapped = True
                        target.replace(original)
                        replacement.replace(target)
                    return real_open(path, flags, *args)

                with mock.patch.object(
                    reader_os,
                    "open",
                    side_effect=swap_before_open,
                ):
                    self.assertTrue(reader(target))
                self.assertTrue(swapped)

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

    def test_wait_can_report_a_soft_observation_timeout_without_cli_failure(self) -> None:
        receipt = {
            "schema_version": 1,
            "status": "running",
            "worker_pid": 111,
            "codex_pid": 222,
        }
        for soft_timeout_exit_zero, expected_exit in ((False, 3), (True, 0)):
            with self.subTest(soft_timeout_exit_zero=soft_timeout_exit_zero):
                args = Namespace(
                    run_dir=".",
                    timeout=0.0,
                    poll_seconds=1.0,
                    soft_timeout_exit_zero=soft_timeout_exit_zero,
                )
                output = io.StringIO()
                with mock.patch.object(agent_runner, "audit_guardian_health"), mock.patch.object(
                    agent_runner, "public_receipt", return_value=receipt.copy()
                ), redirect_stdout(output):
                    result = agent_runner.wait_run(args)

                self.assertEqual(result, expected_exit)
                observed = json.loads(output.getvalue())
                self.assertEqual(observed["status"], "timeout")
                self.assertEqual(observed["worker_pid"], 111)
                self.assertEqual(observed["codex_pid"], 222)

    def test_wait_soft_timeout_flag_is_explicit_and_off_by_default(self) -> None:
        parser = agent_runner.build_parser()
        default = parser.parse_args(["wait", "--run-dir", "."])
        soft = parser.parse_args(
            ["wait", "--run-dir", ".", "--soft-timeout-exit-zero"]
        )

        self.assertFalse(default.soft_timeout_exit_zero)
        self.assertTrue(soft.soft_timeout_exit_zero)

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
