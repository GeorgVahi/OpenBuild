"""Contract tests for the OpenBuild package validator."""

from __future__ import annotations

import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_package import (
    BLINDSPOT_PROTOCOL,
    CANONICAL_AGENT_IDS,
    EXACT_DISPATCH_METHODS,
    IMPLEMENTATION_DELEGATION,
    PACKAGED_SEARCH_INSTRUCTIONS,
    PACKAGED_SEARCH_MODEL,
    REVIEW_MAX_TIER_BY_RISK,
    REVIEW_PROTOCOL,
    ROOT,
    SKILL,
    VERSION_SYNC_PATHS,
    commit_requires_version_bump,
    migration_entry_id,
    migration_plan_id,
    migration_supported_mappings,
    validate_auto_routing_contract,
    validate_agent_usage_report_contract,
    validate_blindspot_contract,
    validate_changelog_contract,
    validate_decision_authority_trace,
    validate_implementation_delegation_contract,
    validate_implementation_dispatch_trace,
    validate_packaged_agent_profile,
    validate_packaged_search_profile,
    validate_profile_migration_trace,
    validate_recovery_control_plane,
    validate_release_docs_contract,
    validate_review_escalation_trace,
    validate_safe_artifact_reader_contract,
    validate_search_dispatch_trace,
    validate_search_availability_classifier_contract,
    validate_usage_routing_contract,
)


class SearchAvailabilityClassifierPackageTests(unittest.TestCase):
    def test_package_requires_complete_stream_and_same_payload_consistency(self) -> None:
        runner = (SKILL / "scripts" / "agent_runner.py").read_text(encoding="utf-8")
        self.assertEqual(validate_search_availability_classifier_contract(runner), [])

        for token in (
            "for value in structured_objects:",
            "code_field != type_field",
            "return next(iter(reasons)) if len(reasons) == 1 else None",
            "RAW_SEARCH_ERROR_TYPES",
            "NON_ERROR_JSONL_EVENT_TYPES",
            'elif "code" in event or event_type in RAW_SEARCH_ERROR_TYPES:',
            "event_type not in NON_ERROR_JSONL_EVENT_TYPES",
            'evidence.get("structured_stderr_valid", True) is True',
            'codex_exit_status == "valid"',
            "codex_exit_code != 0",
            'termination.get("cleanup_errors") == []',
            'termination.get("failure_message") == expected_failure',
            'source_receipt.get("codex_exit_evidence") != "valid"',
            'source_receipt.get("result_evidence") != "missing"',
            'source_request.get("search_fallback_binding") is not None',
            'request.get("search_fallback_source") is None',
        ):
            with self.subTest(token=token):
                mutated = runner.replace(token, "removed fail-closed classifier guard")
                self.assertTrue(
                    any(
                        "search availability classifier" in error
                        for error in validate_search_availability_classifier_contract(mutated)
                    )
                )

    def test_package_requires_descriptor_bound_same_object_artifact_reads(self) -> None:
        runner = (SKILL / "scripts" / "agent_runner.py").read_text(encoding="utf-8")
        discovery = (SKILL / "scripts" / "discovery_contract.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(validate_safe_artifact_reader_contract(runner, discovery), [])

        for token in (
            "read_regular_file_no_follow,",
            "raw = read_regular_file_no_follow(path)",
            "except DiscoveryContractError:",
        ):
            with self.subTest(runner_token=token):
                mutated = runner.replace(token, "removed safe artifact reader guard")
                self.assertTrue(
                    any(
                        "safe artifact reader" in error
                        for error in validate_safe_artifact_reader_contract(
                            mutated,
                            discovery,
                        )
                    )
                )

        for token in (
            "def read_regular_file_no_follow(",
            'getattr(os, "O_NOFOLLOW", 0)',
            "opened_before = os.fstat(descriptor)",
            "chunk = os.read(descriptor, 1024 * 1024)",
            "opened_after = os.fstat(descriptor)",
            "_is_link_or_reparse(opened_before)",
            "_file_identity(before) != _file_identity(opened_before)",
            "_file_identity(opened_after) != _file_identity(after)",
            "raw = read_regular_file_no_follow(",
        ):
            with self.subTest(discovery_token=token):
                mutated = discovery.replace(token, "removed safe artifact reader guard")
                self.assertTrue(
                    any(
                        "safe artifact reader" in error
                        for error in validate_safe_artifact_reader_contract(
                            runner,
                            mutated,
                        )
                    )
                )

        reopened = discovery.replace(
            "raw = read_regular_file_no_follow(",
            "raw = result_path.read_bytes() or read_regular_file_no_follow(",
            1,
        )
        self.assertTrue(
            any(
                "must not reopen" in error
                for error in validate_safe_artifact_reader_contract(runner, reopened)
            )
        )


class RecoveryControlPlanePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = (SKILL / "scripts" / "agent_runner.py").read_text(encoding="utf-8")
        self.recovery = (SKILL / "scripts" / "recovery_state.py").read_text(encoding="utf-8")

    def test_packaged_recovery_owner_is_complete_and_private(self) -> None:
        self.assertEqual(validate_recovery_control_plane(self.runner, self.recovery), [])

        mutations = [
            ("recovery", 'READER_FLOOR = "2.3.5"', 'READER_FLOOR = "1"', "reader floor"),
            (
                "recovery",
                "state = self._read_registry_for_write_locked(rebarrier=True)",
                "state = self._read_registry_locked(rebarrier=True)",
                "pending abandonment reader floor before source replay",
            ),
            ("runner", '"run-dir-v1"', '"run-dir-v0"', "legacy terminal binding compatibility"),
            ("recovery", '"terminal-root-completion-v1"', '"terminal-root-completion-v0"', "post-commit terminal schema"),
            ("recovery", '"remediation-scope-v1"', '"remediation-scope-v0"', "post-commit remediation scope"),
            ("recovery", "finalize_post_commit_root_completion", "trust_post_commit_root_completion", "atomic post-commit finalization"),
            ("recovery", "complete_post_commit_root_completion", "trust_post_commit_completion", "post-commit checkpoint invalidation"),
            ("recovery", "post_commit_root_completion_replay_binding", "trust_post_commit_replay", "full-tuple completed replay"),
            ("recovery", '"authorization_consumption": "consumed"', '"authorization_consumption": "issued"', "intent-authoritative capability consumption"),
            ("recovery", 'b"openbuild-workspace-v2\\0"', 'b"openbuild-workspace-v1\\0"', "workspace key"),
            ("recovery", '"--porcelain=v2"', '"--porcelain=v1"', "Git provenance"),
            ("recovery", '"ls-files", "--stage", "-v", "-z"', '"ls-files", "--stage", "-z"', "Git index flags"),
            ("recovery", "_reject_snapshot_reparse_point(metadata)", "trust_snapshot_reparse_point(metadata)", "Windows reparse points"),
            ("recovery", "_lstat_snapshot_path(relative)", "_trust_snapshot_path(relative)", "Windows reparse ancestors"),
            ("recovery", "_windows_open_snapshot_chain", "_windows_open_following_chain", "snapshot TOCTOU boundary"),
            ("recovery", 'getattr(os, "O_NOFOLLOW", 0)', "0", "snapshot TOCTOU boundary"),
            ("recovery", 'b"openbuild-content-v1\\0"', 'b"content\\0"', "keyed privacy"),
            ("recovery", "DEFAULT_MAX_RECORDS = 100_000", "DEFAULT_MAX_RECORDS = 0", "inventory limits"),
            (
                "recovery",
                '_require_hex(allowed_set_digest, "activation allowed-set digest")',
                'allowed_set_digest = str(allowed_set_digest)',
                "activation digest format boundary",
            ),
            (
                "recovery",
                "_validate_public_checkpoint",
                "trust_public_checkpoint",
                "public checkpoint schema",
            ),
            (
                "recovery",
                "self._validate_registry(state)",
                "self._trust_registry(state)",
                "pre-publication registry schema gate",
            ),
            (
                "recovery",
                'self._validate_source(state, state["source_state_id"])',
                'self._trust_source(state, state["source_state_id"])',
                "pre-publication source schema gate",
            ),
            (
                "recovery",
                "_validate_contained_process_binding(lease)",
                "_validate_provider_receipt(lease)",
                "contained receipt binding",
            ),
            (
                "recovery",
                "_validate_terminal_identity_binding(lease)",
                "_validate_zero_proof(lease.get(\"zero_proof\"))",
                "terminal identity binding",
            ),
            (
                "recovery",
                "self._validate_semantic_registry_binding(state)",
                "self._validate_registry_history(state)",
                "semantic registry binding",
            ),
            (
                "recovery",
                "self._require_zero_write_source_locked(str(lease.get(\"source_state_id\")))",
                "self._trust_zero_write_source(str(lease.get(\"source_state_id\")))",
                "semantic zero-write proof",
            ),
            ("runner", 'if not agent_name.startswith("openbuild_implementation_"):', 'if not agent_name:', "implementation-only"),
            ("runner", "create_windows_kill_job(bind_current=False)", "create_windows_kill_job()", "outside-Job Windows guardian"),
            ("runner", "_WINDOWS_CREATE_SUSPENDED", "_WINDOWS_CREATE_IMMEDIATE", "creation-suspended Windows worker"),
            ("runner", "_CLONE_INTO_CGROUP", "_CLONE_AFTER_CGROUP", "creation-bound Linux worker"),
            ("runner", "spawn_linux_worker_creation_bound", "spawn_linux_worker_then_attach", "creation-bound Linux worker"),
            (
                "runner",
                "def query_linux_cgroup_members(cgroup: Path) -> set[int]:",
                "def attach_linux_process_to_cgroup(cgroup: Path, pid: int) -> None:\n"
                "    (cgroup / \"cgroup.procs\").write_text(str(pid))\n\n"
                "def query_linux_cgroup_members(cgroup: Path) -> set[int]:",
                "creation-bound Linux worker",
            ),
            ("runner", "verify_windows_process_in_job", "trust_windows_process_in_job", "verified Windows Job attachment"),
            ("runner", "establish_linux_anti_migration_boundary", "establish_linux_boundary", "native Linux anti-migration boundary"),
            ("runner", "await_guardian_precommit", "await_guardian_ready", "fresh guardian precommit attestation"),
            ("runner", "bound_state = registry.bind_process_unactivated", "bound_state = registry.state", "guardian-owned registry commit"),
            ("recovery", "reject_semantic_handoff", "accept_semantic_handoff", "semantic handoff rejection"),
            ("recovery", "complete_source_checkpoint_invalidation", "trust_source_checkpoint_invalidation", "semantic checkpoint invalidation completion"),
            ("recovery", "resolve_visible_commit=True", "resolve_visible_commit=False", "decidable guardian registry commit"),
            ("recovery", "bind_reserved_source_snapshot", "trust_prepared_source_snapshot", "reserved source provenance boundary"),
            ("recovery", '"activation-provenance-drift"', '"activation-provenance-trusted"', "activation provenance boundary"),
            ("recovery", 'b"openbuild-terminal-archive-v1\\0"', 'b"openbuild-terminal-v0\\0"', "contained terminal archive"),
            ("runner", "registry.bind_reserved_source_snapshot", "registry.trust_prepared_source_snapshot", "reserved source provenance boundary"),
            ("runner", 'private_plan.get("provider_plan_id") != provider_plan_id', 'private_plan.get("provider_plan_id") == provider_plan_id', "guardian provider-plan binding"),
            ("runner", 'private_plan.get("ipc_plan_id") != ipc_plan_id', 'private_plan.get("ipc_plan_id") == ipc_plan_id', "guardian IPC-plan binding"),
            ("runner", "reject_semantic_handoff_run", "accept_semantic_handoff_run", "root semantic rejection gate"),
            ("runner", "registry.complete_source_checkpoint_invalidation", "registry.trust_source_checkpoint_invalidation", "root semantic invalidation completion"),
            ("recovery", "quarantine_fallback_launch", "release_fallback_launch", "ambiguous fallback quarantine"),
            (
                "recovery",
                'lease["state"] = "ordinary-process-bound-unactivated"\n            return self._commit_registry_locked(state, resolve_visible_commit=True)',
                'lease["state"] = "ordinary-process-bound-unactivated"\n            return self._commit_registry_locked(state)',
                "fallback process bind",
            ),
            (
                "runner",
                "ordinary fallback process bind did not return its exact durable receipt",
                "ordinary fallback process bind is trusted",
                "fallback process receipt verification",
            ),
            ("runner", "reconcile_implementation_registry", "reconcile_registry", "runner terminal lifecycle"),
            ("runner", '"--soft-timeout-exit-zero"', '"--strict-timeout-only"', "soft observation timeout"),
            ("runner", "return 0 if args.soft_timeout_exit_zero else 3", "return 3", "soft observation timeout"),
            ("recovery", "terminal-abandonment-v1", "terminal-abandonment-v0", "terminal abandonment schema"),
            ("recovery", "terminal-abandonment-v2", "terminal-abandonment-v0", "recovery overlap abandonment schema"),
            ("recovery", "terminal-abandonment-v3", "terminal-abandonment-v0", "legacy normal overlap abandonment schema"),
            (
                "recovery",
                "record_containment_loss_abandonment",
                "trust_containment_loss_abandonment",
                "containment-loss abandonment transition",
            ),
            (
                "recovery",
                "acknowledge_containment_loss_close",
                "trust_containment_loss_close",
                "containment-loss guardian close",
            ),
            ("runner", "terminal-abandonment-v2", "terminal-abandonment-v0", "runner recovery overlap public result"),
            ("runner", "terminal-abandonment-v3", "terminal-abandonment-v0", "runner legacy normal overlap public result"),
            (
                "runner",
                '"_reconcile-containment-loss"',
                '"_force-unlock-containment"',
                "containment-loss reconciliation command",
            ),
            (
                "recovery",
                "terminal-abandoned-recovery-overlap",
                "terminal-abandoned-recovery-overlap-v0",
                "recovery overlap abandonment invalidation",
            ),
            (
                "recovery",
                "terminal-abandoned-legacy-normal-overlap",
                "terminal-abandoned-legacy-normal-overlap-v0",
                "legacy normal overlap abandonment invalidation",
            ),
            ("recovery", "record_terminal_abandonment", "record_generic_abandonment", "terminal abandonment transition"),
            ("recovery", "persist=False", "persist=True", "terminal abandonment no-mutation gate"),
            ("recovery", "retire_authorization", "retain_authorization", "prompt authorization retirement"),
            ("recovery", "mark_prompt_snapshot_released", "keep_prompt_snapshot", "prompt snapshot release"),
            (
                "recovery",
                "expected_run_id = _lease_run_id(lease)",
                'expected_run_id = lease.get("run_id")',
                "shared lease run binding",
            ),
            (
                "recovery",
                '"terminal abandonment recovery authorization binding is incomplete"',
                '"terminal abandonment authorization is trusted"',
                "abandonment authorization retirement",
            ),
            ("runner", "acquire_owner_prompt_snapshot", "read_untrusted_prompt", "stable prompt import"),
            ("runner", "stage_owner_prompt_snapshot", "stage_workspace_prompt", "owner-private prompt staging"),
            ("runner", "windows_object_is_private", "trust_windows_object", "private Windows prompt DACL"),
            ("runner", "prompt_owner.mark_prompt_snapshot_released", "prompt_owner.keep_prompt_snapshot", "normal prompt release"),
            (
                "runner",
                "durable_write_private_bytes(prompt_snapshot, source_prompt)",
                "atomic_write_bytes(prompt_snapshot, source_prompt)",
                "durable prompt binding",
            ),
            (
                "runner",
                "garbage_collect_owner_prompt_snapshots(prompt_owner)",
                "retain_owner_prompt_snapshots(prompt_owner)",
                "prompt snapshot GC",
            ),
            (
                "runner",
                "registry._read_source_locked(path.stem, rebarrier=True)",
                "json.loads(path.read_text(encoding=\"utf-8\"))",
                "authoritative prompt GC scan",
            ),
            (
                "recovery",
                "recovery terminal release authorization binding",
                "recovery terminal release authorization trusted",
                "recovery terminal authorization retirement",
            ),
            (
                "runner",
                "_expected_lease_run_id(lease)",
                "request.get(\"lease_id\")",
                "terminal exact run binding",
            ),
            (
                "runner",
                "_terminal_binding(receipt, run_id=expected_run_id)",
                "_terminal_binding(receipt)",
                "terminal exact run receipt",
            ),
            (
                "runner",
                "_match_terminal_binding",
                "_trust_terminal_binding",
                "terminal binding compatibility match",
            ),
            (
                "runner",
                "def classify_recovery_outcome(",
                "def describe_recovery_outcome(",
                "closed recovery outcomes",
            ),
            (
                "runner",
                "def root_completion_authorization_record(",
                "def root_completion_note(",
                "root completion audit",
            ),
            (
                "runner",
                "def record_root_completion_authorization_run(",
                "def print_root_completion_authorization_run(",
                "durable root completion audit",
            ),
            (
                "runner",
                '"_record-root-completion"',
                '"_describe-root-completion"',
                "root completion audit command",
            ),
            (
                "runner",
                "states[\"released\"] -= states[\"grant-referenced\"] | states[\"lease-referenced\"]",
                "states[\"grant-referenced\"] -= states[\"released\"]",
                "active prompt reference precedence",
            ),
            (
                "runner",
                "def classify_public_failure(",
                "def expose_private_failure(",
                "public failure classification",
            ),
            (
                "runner",
                '"failure_message": classify_public_failure(',
                '"failure_message": evidence["failure_message"]',
                "public failure projection",
            ),
            (
                "runner",
                '"external-action",',
                '"external",',
                "external-action outcome class",
            ),
            (
                "runner",
                '"run_handle": public_run_handle(run_dir)',
                '"run_dir": str(run_dir.resolve())',
                "public receipt path redaction",
            ),
            (
                "runner",
                '"prompt_source_classification": "owner-private-snapshot"',
                '"profile_source": request["profile_source"]',
                "public receipt prompt classification",
            ),
            ("runner", "_reconcile-terminal-abandonment", "_force-unlock", "terminal abandonment command"),
            ("runner", "_stage-post-commit-root-completion-action", "_stage-force-unlock", "hidden post-commit action snapshot command"),
            ("runner", "_authorize-post-commit-root-completion", "_authorize-force-unlock", "hidden post-commit authorization command"),
            ("runner", "_finalize-post-commit-root-completion", "_finalize-force-unlock", "hidden post-commit finalization command"),
            ("runner", "_post_commit_root_completion_blocked", "_post_commit_root_completion_raw", "privacy-safe post-commit blocked output"),
            ("runner", "_post_commit_root_completion_result", "_post_commit_root_completion_raw", "privacy-safe post-commit completed output"),
            ("runner", "registry.post_commit_root_completion_replay_binding", "registry.trust_post_commit_root_completion", "full-tuple completed replay"),
        ]
        for field, token, replacement, expected in mutations:
            with self.subTest(expected=expected):
                runner = self.runner if field != "runner" else self.runner.replace(token, replacement)
                recovery = self.recovery if field != "recovery" else self.recovery.replace(token, replacement)
                self.assertTrue(
                    any(expected in error for error in validate_recovery_control_plane(runner, recovery))
                )


class RunnerOnlyRoutingContractTests(unittest.TestCase):
    def test_only_explicit_cli_dispatch_is_accepted(self) -> None:
        self.assertEqual(EXACT_DISPATCH_METHODS, {"codex-exec-explicit-model"})

    def test_packaged_writer_profiles_lock_one_pre_edit_next_rung_or_terminal_stop(self) -> None:
        profile_path = SKILL / "profiles" / "openbuild_implementation_strong.toml"
        profile = tomllib.loads(profile_path.read_text(encoding="utf-8"))
        edge = (
            "Before the first edit, a capability escalation may name only "
            "`openbuild_implementation_sol_high` as the next rung."
        )
        for instructions, expected in [
            (profile["developer_instructions"].replace(edge, ""), "exactly one named pre-edit"),
            (profile["developer_instructions"] + edge, "exactly one named pre-edit"),
            (
                profile["developer_instructions"].replace(edge, "") + "\n" + edge,
                "must precede post-edit",
            ),
        ]:
            with self.subTest(expected=expected):
                altered = dict(profile, developer_instructions=instructions)
                self.assertTrue(
                    any(expected in error for error in validate_packaged_agent_profile(
                        "openbuild_implementation_strong", altered
                    ))
                )

    def test_packaged_strongest_reviewer_is_critical_only(self) -> None:
        profile_path = SKILL / "profiles" / "openbuild_review_strongest.toml"
        profile = tomllib.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(
            validate_packaged_agent_profile("openbuild_review_strongest", profile), []
        )

        altered = dict(
            profile,
            developer_instructions=profile["developer_instructions"].replace(
                "This Sol/xhigh profile is critical-only and is never the next rung for a non-critical review.",
                "This profile may adjudicate an escalated non-critical review.",
            ),
        )
        self.assertTrue(
            any(
                "critical-only" in error
                for error in validate_packaged_agent_profile(
                    "openbuild_review_strongest", altered
                )
            )
        )

        terminal_path = SKILL / "profiles" / "openbuild_implementation_sol_high.toml"
        terminal = tomllib.loads(terminal_path.read_text(encoding="utf-8"))
        terminal["developer_instructions"] = terminal["developer_instructions"].replace(
            "Capability escalation is forbidden;", "Capability escalation may continue;"
        )
        self.assertTrue(
            any(
                "terminal writer" in error
                for error in validate_packaged_agent_profile("openbuild_implementation_sol_high", terminal)
            )
        )

    def test_packaged_profiles_lock_their_effective_routing_rung(self) -> None:
        profile_path = SKILL / "profiles" / "openbuild_review_fast.toml"
        profile = tomllib.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(
            validate_packaged_agent_profile("openbuild_review_fast", profile), []
        )
        for field, value in (
            ("routing_rung", "sol-high"),
            ("routing_tuple_confirmed", False),
        ):
            with self.subTest(field=field):
                altered = dict(profile, **{field: value})
                self.assertTrue(
                    any(
                        field in error
                        for error in validate_packaged_agent_profile(
                            "openbuild_review_fast", altered
                        )
                    )
                )

    def test_deprecated_unknown_agent_routes_are_absent_from_runtime_contract(self) -> None:
        self.assertNotIn("openbuild_search_fallback", CANONICAL_AGENT_IDS)
        paths = [
            SKILL / "SKILL.md",
            SKILL / "references" / "code-discovery.md",
            SKILL / "references" / "model-routing.md",
            SKILL / "references" / "implementation-delegation.md",
            SKILL / "references" / "review-protocol.md",
            ROOT / "scripts" / "validate_package.py",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for token in [
            "openbuild_search_fallback",
            "per-spawn-model",
            "exact-custom-agent",
            "role-only",
            "generic-subagent",
            "configured-unverified",
            "selector-unavailable",
            "tier-unproven",
        ]:
            with self.subTest(token=token):
                self.assertNotIn(token, combined)


class ConfigurableModelMapContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.routing = (SKILL / "references" / "model-routing.md").read_text(encoding="utf-8")
        interview_path = SKILL / "references" / "model-map-interview.md"
        self.interview = interview_path.read_text(encoding="utf-8") if interview_path.is_file() else ""
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")

    def test_configure_models_is_a_documented_build_command(self) -> None:
        for text in (self.skill, self.routing, self.readme, self.readme_ru):
            with self.subTest(document=text[:24]):
                self.assertIn("configure-models", text)
        self.assertIn("setup-models", self.skill)
        self.assertIn("backward-compatible alias", self.routing)

    def test_interview_is_deep_adaptive_and_plain_language(self) -> None:
        for token in [
            "project or user scope",
            "available model evidence",
            "speed, quality, and usage limits",
            "Discovery",
            "Specification critics",
            "Implementation",
            "Review",
            "Critical work",
            "recommended option first",
            "one to three questions",
            "final preview",
            "exact diff",
            "explicit permission",
            "restore packaged defaults",
        ]:
            with self.subTest(token=token):
                self.assertIn(token.lower(), self.interview.lower())

    def test_model_map_precedence_and_fail_closed_rules_are_normative(self) -> None:
        for token in [
            ".codex/openbuild/model-map.toml",
            "$CODEX_HOME/openbuild/model-map.toml",
            "project → user → packaged",
            "transport failure",
            "semantic-before-edit",
            "single-writer",
            "critical_confirmed",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, self.routing)

    def test_every_dispatch_resolves_the_user_map_before_agent_runner(self) -> None:
        for use_case in ("discovery", "critic", "implementation", "review"):
            with self.subTest(use_case=use_case):
                self.assertIn(
                    f"model_map.py resolve --use-case {use_case}",
                    self.skill,
                )
        self.assertIn("map_source", self.skill)
        self.assertIn("map_sha256", self.skill)
        self.assertIn("route step", self.skill)

    def test_interview_configures_exact_profiles_and_complete_routes(self) -> None:
        for token in [
            "model",
            "reasoning effort",
            "max_steps",
            "escalation_triggers",
            "low, medium, high, and critical",
            "openbuild_search_balanced",
            "openbuild_search_strong",
            "openbuild_search_strongest",
            "model_map.py validate",
            "one launcher smoke per distinct model/effort/sandbox tuple",
            "routing_rung",
            "routing_tuple_confirmed = true",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, self.interview)


class PerCommitVersionGateTests(unittest.TestCase):
    def test_every_nonempty_commit_requires_a_version_bump(self) -> None:
        examples = [
            {"plugins/openbuild/skills/build/SKILL.md"},
            {"README.md"},
            {"CONTRIBUTING.md"},
            {"scripts/validate_package.py"},
            {"LICENSE"},
        ]

        for changed_paths in examples:
            with self.subTest(changed_paths=changed_paths):
                self.assertTrue(commit_requires_version_bump(changed_paths))

    def test_no_pending_commit_does_not_require_a_version_bump(self) -> None:
        self.assertFalse(commit_requires_version_bump(set()))

    def test_even_an_empty_created_commit_requires_a_version_bump(self) -> None:
        self.assertTrue(commit_requires_version_bump(set(), commit_exists=True))

    def test_every_versioned_commit_synchronizes_public_version_metadata(self) -> None:
        self.assertEqual(
            VERSION_SYNC_PATHS,
            {
                "plugins/openbuild/.codex-plugin/plugin.json",
                "CHANGELOG.md",
                "README.md",
                "README.ru.md",
            },
        )


class BlindspotWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.protocol_text = BLINDSPOT_PROTOCOL.read_text(encoding="utf-8") if BLINDSPOT_PROTOCOL.is_file() else ""
        self.template_text = (SKILL / "references" / "spec-template.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_blindspot_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("protocol_text", self.protocol_text),
            overrides.get("template_text", self.template_text),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
        )

    def test_blindspot_protocol_is_required_and_linked(self) -> None:
        self.assertTrue(BLINDSPOT_PROTOCOL.is_file())
        self.assertEqual(self.validate(), [])

    def test_resolved_decisions_cannot_be_reasked_without_reopen_evidence(self) -> None:
        mutated = self.protocol_text.replace("do not ask it again", "ask it again")
        self.assertTrue(any("decision memory" in error for error in self.validate(protocol_text=mutated)))

        mutated = self.protocol_text.replace("new evidence", "new information")
        self.assertTrue(any("decision memory" in error for error in self.validate(protocol_text=mutated)))

    def test_ready_depends_on_complete_coverage_not_question_count(self) -> None:
        mutated = self.protocol_text.replace("coverage ledger", "question total") + "\n\n## Appendix\n\ncoverage ledger\n"
        self.assertTrue(any("Ready gate" in error for error in self.validate(protocol_text=mutated)))

    def test_critic_loop_has_progress_bounds_and_risk_depth(self) -> None:
        mutated = self.protocol_text.replace("unchanged tuple", "unchanged pass")
        self.assertTrue(any("adaptive critic loop" in error for error in self.validate(protocol_text=mutated)))

    def test_critic_schema_and_root_fallback_preserve_risk_depth(self) -> None:
        mutated = self.protocol_text.replace("Reopen requests:", "Review requests:")
        self.assertTrue(any("critic result" in error for error in self.validate(protocol_text=mutated)))

        mutated = self.protocol_text.replace("sequential separated root-perspective passes", "one root pass")
        self.assertTrue(any("adaptive critic loop" in error for error in self.validate(protocol_text=mutated)))

        mutated = self.protocol_text.replace("one generalist for non-trivial low work", "no low fallback")
        self.assertTrue(any("adaptive critic loop" in error for error in self.validate(protocol_text=mutated)))

        mutated = self.protocol_text.replace("separate closure pass for high", "no extra high closure")
        self.assertTrue(any("adaptive critic loop" in error for error in self.validate(protocol_text=mutated)))

    def test_audit_metadata_does_not_invalidate_its_own_closure(self) -> None:
        mutated = self.protocol_text.replace("Do not increment it for audit metadata", "Increment it for audit metadata")
        self.assertTrue(any("adaptive critic loop" in error for error in self.validate(protocol_text=mutated)))

    def test_blindspot_contract_is_present_in_internal_template(self) -> None:
        template = self.template_text.replace("Evidence or decision", "Evidence")
        self.assertTrue(any("coverage ledger" in error for error in self.validate(template_text=template)))

    def test_linked_normative_sources_are_mapped_before_synthesis(self) -> None:
        skill = self.skill_text.replace("every in-scope normative file", "selected files")
        self.assertTrue(any("source map" in error for error in self.validate(skill_text=skill)))

        skill = self.skill_text.replace("every outgoing normative edge", "some references")
        self.assertTrue(any("source map" in error for error in self.validate(skill_text=skill)))

        protocol = self.protocol_text.replace(
            "Do not infer that the root silently overrides",
            "Assume that the root overrides",
        )
        self.assertTrue(any("source map" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace(
            "every mapped source is reachable from the selected root",
            "the listed source count is accepted",
        )
        self.assertTrue(any("source map" in error for error in self.validate(protocol_text=protocol)))

        template = self.template_text.replace("### Specification source map", "### Specification files")
        self.assertTrue(any("source map" in error for error in self.validate(template_text=template)))

    def test_user_owns_product_impact_and_technical_choices_stay_outcome_neutral(self) -> None:
        skill = self.skill_text.replace("The user owns any choice", "The root owns any choice")
        self.assertTrue(any("decision authority" in error for error in self.validate(skill_text=skill)))

        skill = self.skill_text.replace(
            "Initial source mapping cannot self-declare a user deferral",
            "The root can defer a source during mapping",
        )
        self.assertTrue(any("decision authority" in error for error in self.validate(skill_text=skill)))

        protocol = self.protocol_text.replace(
            "When classification is mixed or uncertain",
            "When the category is ambiguous, let the root choose; otherwise",
        )
        self.assertTrue(any("decision authority" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace("structured reconciliation receipt", "reconciliation note")
        self.assertTrue(any("decision authority" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace(
            "record type, governed target, source revision, and positive line number",
            "non-empty authority note",
        )
        self.assertTrue(any("decision authority" in error for error in self.validate(protocol_text=protocol)))

        template = self.template_text.replace("### Technical decision ledger", "### Implementation notes")
        self.assertTrue(any("decision authority" in error for error in self.validate(template_text=template)))

    def test_normative_edits_wait_for_answers_and_emit_application_receipts(self) -> None:
        protocol = self.protocol_text.replace(
            "Do not change that dependent normative specification content",
            "Change dependent normative specification content",
        )
        self.assertTrue(any("application gate" in error for error in self.validate(protocol_text=protocol)))

        skill = self.skill_text.replace("decision application receipt", "decision summary")
        self.assertTrue(any("normative edit gate" in error for error in self.validate(skill_text=skill)))

        skill = self.skill_text.replace(
            "cannot replace a locked `D-###`",
            "may replace a locked decision",
        )
        self.assertTrue(any("normative edit gate" in error for error in self.validate(skill_text=skill)))

        protocol = self.protocol_text.replace(
            "invalidates every prior normative write/application authorization",
            "retains the prior write authorization",
        )
        self.assertTrue(any("application gate" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace(
            "complete set of affected `(target, change)` tuples",
            "decision ID",
        )
        self.assertTrue(any("application gate" in error for error in self.validate(protocol_text=protocol)))



class AutoRoutingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.protocol_text = BLINDSPOT_PROTOCOL.read_text(encoding="utf-8")
        self.metadata_text = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_auto_routing_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("protocol_text", self.protocol_text),
            overrides.get("metadata_text", self.metadata_text),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
        )

    def test_bare_invocation_uses_auto_phase_routing(self) -> None:
        self.assertEqual(self.validate(), [])

        mutated = self.skill_text.replace("`$build <idea-or-path>`: treat as `auto`", "`$build <idea-or-path>`: treat as `full`")
        self.assertTrue(any("bare invocation" in error for error in self.validate(skill_text=mutated)))

    def test_auto_routing_is_the_default_public_prompt(self) -> None:
        metadata = self.metadata_text.replace("auto mode", "full mode")
        self.assertTrue(any("openai.yaml" in error for error in self.validate(metadata_text=metadata)))

    def test_lifecycle_matrix_is_required(self) -> None:
        protocol = self.protocol_text.replace("| `In progress` |", "| `Active` |")
        self.assertTrue(any("lifecycle routing" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace("full acceptance set", "primary signal only")
        self.assertTrue(any("lifecycle routing" in error for error in self.validate(protocol_text=protocol)))



class ImplementationDelegationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.protocol_text = (
            IMPLEMENTATION_DELEGATION.read_text(encoding="utf-8")
            if IMPLEMENTATION_DELEGATION.is_file()
            else ""
        )
        self.model_routing = (SKILL / "references" / "model-routing.md").read_text(encoding="utf-8")
        self.tdd_workflow = (SKILL / "references" / "tdd-workflow.md").read_text(encoding="utf-8")
        self.review_protocol = (SKILL / "references" / "review-protocol.md").read_text(encoding="utf-8")
        self.versioning_text = (SKILL / "references" / "versioning.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.runner_text = (SKILL / "scripts" / "agent_runner.py").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_implementation_delegation_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("protocol_text", self.protocol_text),
            overrides.get("model_routing", self.model_routing),
            overrides.get("tdd_workflow", self.tdd_workflow),
            overrides.get("review_protocol", self.review_protocol),
            overrides.get("versioning_text", self.versioning_text),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
            overrides.get("runner_text", self.runner_text),
        )

    def test_adaptive_delegation_protocol_is_required_and_linked(self) -> None:
        self.assertTrue(IMPLEMENTATION_DELEGATION.is_file())
        self.assertEqual(self.validate(), [])

    def test_shared_workspace_allows_only_one_bounded_writer(self) -> None:
        mutated = self.protocol_text.replace("one active writer", "an active writer")
        self.assertTrue(any("single-writer" in error for error in self.validate(protocol_text=mutated)))

    def test_delegation_contract_is_present_in_model_and_tdd(self) -> None:
        model_routing = self.model_routing.replace("Implementation worker", "Implementation helper")
        self.assertTrue(any("model-routing.md" in error for error in self.validate(model_routing=model_routing)))

        tdd_workflow = self.tdd_workflow.replace("bounded implementation worker", "implementation helper")
        self.assertTrue(any("tdd-workflow.md" in error for error in self.validate(tdd_workflow=tdd_workflow)))

        route = "Resolve `implementation.<risk>` through the effective model map"
        edit = "Under that lease, add or modify the test"
        tdd_workflow = self.tdd_workflow.replace(route, "__EDIT_ORDER__").replace(edit, route).replace("__EDIT_ORDER__", edit)
        self.assertTrue(any("must precede every test code edit" in error for error in self.validate(tdd_workflow=tdd_workflow)))

    def test_delegation_modes_and_root_handoff_are_required(self) -> None:
        protocol = self.protocol_text.replace("`sequential-workers`", "`multiple-workers`")
        self.assertTrue(any("delegation modes" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace("Git exclusively root-owned", "Git controlled")
        self.assertTrue(any("root handoff" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace(
            "Do not repair an edited or failed milestone through a replacement lease without new explicit user authority",
            "Repair that milestone through a new route",
        )
        self.assertTrue(any("root handoff" in error for error in self.validate(protocol_text=protocol)))

        tdd_workflow = self.tdd_workflow.replace(
            "keep the milestone blocked, and create no replacement writer",
            "select a fallback writer",
        )
        self.assertTrue(any("failed exact writer recovery" in error for error in self.validate(tdd_workflow=tdd_workflow)))

    def test_automatic_orchestration_contract_cannot_regress_to_manual_control(self) -> None:
        skill = self.skill_text.replace(
            "external controller timeout of at least 120 seconds",
            "the controller default timeout",
        )
        self.assertTrue(
            any("dispatch controller timeout" in error for error in self.validate(skill_text=skill))
        )

        routing = self.model_routing.replace(
            "external controller timeout of at least 120 seconds",
            "the controller default timeout",
        )
        self.assertTrue(
            any("dispatch controller timeout" in error for error in self.validate(model_routing=routing))
        )

        protocol = self.protocol_text.replace(
            "external controller timeout of at least 120 seconds",
            "the controller default timeout",
        )
        self.assertTrue(
            any("dispatch controller timeout" in error for error in self.validate(protocol_text=protocol))
        )

        skill = self.skill_text.replace(
            "activated `normal-legacy` failure release",
            "any legacy release",
        )
        self.assertTrue(
            any("legacy timeout release audit" in error for error in self.validate(skill_text=skill))
        )

        routing = self.model_routing.replace(
            "activated `normal-legacy` failure release",
            "any legacy release",
        )
        self.assertTrue(
            any("legacy timeout release audit" in error for error in self.validate(model_routing=routing))
        )

        protocol = self.protocol_text.replace(
            "activated `normal-legacy` failure release",
            "any legacy release",
        )
        self.assertTrue(
            any("legacy timeout release audit" in error for error in self.validate(protocol_text=protocol))
        )

        skill = self.skill_text.replace("runner-owned `dispatch`", "manual `start`")
        self.assertTrue(
            any("runner-owned dispatch" in error for error in self.validate(skill_text=skill))
        )

        routing = self.model_routing.replace(
            "one immutable 900-second observation budget", "manual observation windows"
        )
        self.assertTrue(
            any("automatic deadline" in error for error in self.validate(model_routing=routing))
        )

        protocol = self.protocol_text.replace(
            "normalized-malformed-needs-escalation", "manual-escalation"
        )
        self.assertTrue(
            any("malformed escalation" in error for error in self.validate(protocol_text=protocol))
        )

        protocol = self.protocol_text.replace("same-profile-retry", "manual-retry")
        self.assertTrue(
            any("same-profile retry" in error for error in self.validate(protocol_text=protocol))
        )

        runner = self.runner_text.replace("dispatch-unactivated-receipt.json", "manual-receipt")
        self.assertTrue(
            any("durable unactivated receipt" in error for error in self.validate(runner_text=runner))
        )

        runner = self.runner_text.replace(
            "def nonrecovery_allowed_set_digest",
            "def unbound_nonrecovery_paths",
        )
        self.assertTrue(
            any("ordinary activation allowed-set binding" in error for error in self.validate(runner_text=runner))
        )

        runner = self.runner_text.replace(
            "def root_completion_source_binding(",
            "def unbound_root_completion_source(",
        )
        self.assertTrue(
            any("root completion source binding" in error for error in self.validate(runner_text=runner))
        )

        runner = self.runner_text.replace(
            "def _validate_legacy_root_completion_release(",
            "def _trust_any_legacy_release(",
        )
        self.assertTrue(
            any("legacy timeout root completion audit" in error for error in self.validate(runner_text=runner))
        )

        skill = self.skill_text.replace(
            "Only a new recovery target writer requires explicit user opt-in",
            "Every failed contained run requires explicit user opt-in",
        )
        self.assertTrue(
            any("recovery target authority boundary" in error for error in self.validate(skill_text=skill))
        )

        tdd_workflow = self.tdd_workflow.replace("runner-owned `dispatch`", "manual `start` and `activate`")
        self.assertTrue(
            any("tdd-workflow.md automatic orchestration" in error for error in self.validate(tdd_workflow=tdd_workflow))
        )

        readme = self.readme.replace(
            "continues observing automatically within one immutable 15-minute budget",
            "asks whether to continue after the third checkpoint",
        )
        self.assertTrue(
            any("README.md automatic orchestration" in error for error in self.validate(readme=readme))
        )

        readme_ru = self.readme_ru.replace(
            "Только новый checkpoint-bound recovery target writer требует явного разрешения пользователя",
            "Любое продолжение требует явного разрешения пользователя",
        )
        self.assertTrue(
            any("README.ru.md automatic orchestration" in error for error in self.validate(readme_ru=readme_ru))
        )

    def test_recovery_autonomy_contract_cannot_regress_to_permission_prompts(self) -> None:
        skill = self.skill_text.replace(
            "_reconcile-terminal-abandonment --run-dir <path>",
            "ask the user to authorize recovery",
        )
        self.assertTrue(
            any("same-lifecycle abandonment" in error for error in self.validate(skill_text=skill))
        )

        protocol = self.protocol_text.replace(
            "required_action=provide-decision",
            "required_action=authorize-recovery",
        )
        self.assertTrue(
            any("decision outcome" in error for error in self.validate(protocol_text=protocol))
        )

        routing = self.model_routing.replace(
            "asks for permission that cannot change the evidence",
            "asks for permission to continue",
        )
        self.assertTrue(
            any("no-useless-permission" in error for error in self.validate(model_routing=routing))
        )

        tdd = self.tdd_workflow.replace(
            "terminal-abandonment-v1",
            "manual-recovery-v1",
        )
        self.assertTrue(
            any("abandonment fixture" in error for error in self.validate(tdd_workflow=tdd))
        )

        skill = self.skill_text.replace(
            "terminal-abandonment-v2", "manual-recovery-v2"
        )
        self.assertTrue(
            any("v2 terminal outcome" in error for error in self.validate(skill_text=skill))
        )

        skill = self.skill_text.replace(
            "terminal-abandonment-v3", "manual-recovery-v3"
        )
        self.assertTrue(
            any("v3 terminal outcome" in error for error in self.validate(skill_text=skill))
        )

        skill = self.skill_text.replace(
            "_reconcile-containment-loss --run-dir <path>",
            "_force-unlock-containment --run-dir <path>",
        )
        self.assertTrue(
            any(
                "containment-loss reconciliation" in error
                for error in self.validate(skill_text=skill)
            )
        )

        protocol = self.protocol_text.replace(
            "The sole quarantine exception is private `_reconcile-containment-loss`",
            "Any quarantine may be cleared manually",
        )
        self.assertTrue(
            any(
                "containment-loss reconciliation" in error
                for error in self.validate(protocol_text=protocol)
            )
        )

        protocol = self.protocol_text.replace(
            "exact sorted pair `[outside-set-drift, preexisting-dirty-overlap]`",
            "generic mixed reasons",
        )
        self.assertTrue(
            any("missing exact pair" in error for error in self.validate(protocol_text=protocol))
        )

        routing = self.model_routing.replace(
            "Exact `[outside-set-drift, preexisting-dirty-overlap]` uses terminal abandonment v2 for a recovery-target and v3 for a legacy `normal-contained` lease",
            "mixed reasons resume routing",
        )
        self.assertTrue(
            any("v2/v3 routing" in error for error in self.validate(model_routing=routing))
        )

        routing = self.model_routing.replace(
            "An exact post-zero `containment-loss-after-boundary` quarantine",
            "Any quarantine",
        )
        self.assertTrue(
            any(
                "containment-loss reconciliation" in error
                for error in self.validate(model_routing=routing)
            )
        )

        tdd = self.tdd_workflow.replace(
            "terminal-abandonment-v2", "manual-recovery-v2"
        )
        self.assertTrue(
            any("v2 fixture" in error for error in self.validate(tdd_workflow=tdd))
        )

        tdd = self.tdd_workflow.replace(
            "terminal-abandonment-v3", "manual-recovery-v3"
        )
        self.assertTrue(
            any("v3 fixture" in error for error in self.validate(tdd_workflow=tdd))
        )

        tdd = self.tdd_workflow.replace(
            "Post-zero containment-loss reconciliation must additionally reproduce",
            "Containment loss needs no dedicated fixture",
        )
        self.assertTrue(
            any(
                "containment-loss reconciliation" in error
                for error in self.validate(tdd_workflow=tdd)
            )
        )

        review = self.review_protocol.replace(
            "legacy `normal-contained` v3",
            "generic mixed recovery",
        )
        self.assertTrue(
            any("v3 review boundary" in error for error in self.validate(review_protocol=review))
        )

        review = self.review_protocol.replace(
            "post-zero containment-loss diffs additionally prove",
            "containment-loss diffs need no additional proof",
        )
        self.assertTrue(
            any(
                "containment-loss reconciliation" in error
                for error in self.validate(review_protocol=review)
            )
        )

        versioning = self.versioning_text.replace(
            "first new durable transition raises the floor to 2.3.5 before source invalidation",
            "reader floor remains unchanged",
        )
        self.assertTrue(
            any("reader-floor rollout" in error for error in self.validate(versioning_text=versioning))
        )

class ChangelogContractTests(unittest.TestCase):
    def test_release_manifest_version_and_latest_release_are_documented(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(validate_changelog_contract(changelog, "2.3.5"), [])
        self.assertNotIn("## [2.1.1]", changelog)

        mutated = changelog.replace("## [2.3.5]", "## [next]", 1)
        self.assertTrue(any("current manifest version" in error for error in validate_changelog_contract(mutated, "2.3.5")))

    def test_released_version_is_pinned_in_both_install_channels(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.assertEqual(validate_release_docs_contract(readme, readme_ru, "2.3.5"), [])

        mutated = readme.replace("--ref v2.3.5", "--ref main")
        self.assertTrue(any("README.md" in error for error in validate_release_docs_contract(mutated, readme_ru, "2.3.5")))


class DecisionAuthorityTraceTests(unittest.TestCase):
    @staticmethod
    def source_map(
        *paths: str,
        complete: str = "true",
        root: str = "TZ.md",
        decisions: dict[str, str] | None = None,
        links: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        decisions = decisions or {}
        links = links or {
            path: ",".join(candidate for candidate in paths if path == root and candidate != root) or "none"
            for path in paths
        }
        sources = [
            {
                "event": "spec-source",
                "path": path,
                "authority": "user specification",
                "revision": "current",
                "normative_scope": "task product contract",
                "decision_ids": decisions.get(path, "none"),
                "normative_links": links.get(path, "none"),
                "link_evidence": f"{path}: audited normative references",
                "editable": "yes",
                "reconciliation": "aligned",
            }
            for path in paths
        ]
        return [
            *sources,
            {
                "event": "spec-source-map",
                "root": root,
                "source_count": str(len(sources)),
                "complete": complete,
            },
        ]

    @staticmethod
    def application(
        decision_id: str,
        target: str,
        change: str,
        answer_source: str,
        selected_outcome: str,
    ) -> dict[str, str]:
        return {
            "event": "decision-application",
            "decision_id": decision_id,
            "target": target,
            "change": change,
            "answer_source": answer_source,
            "selected_outcome": selected_outcome,
            "changed_sections": change,
            "changed_criteria": "none",
            "preserved_invariants": "all unrelated locked decisions",
        }

    def test_user_decision_precedes_normative_spec_rebuild(self) -> None:
        trace = [
            *self.source_map(
                "TZ.md",
                "TZ/09.md",
                "TZ/12.md",
                decisions={"TZ/09.md": "D-006"},
            ),
            {
                "event": "locked-decision",
                "decision_id": "D-006",
                "source": "TZ/09.md",
                "status": "resolved",
                "selected_outcome": "web-only duels",
            },
            {
                "event": "gap-classified",
                "gap_id": "B-007",
                "decision_id": "D-007",
                "disposition": "product-decision",
                "impact": "eligibility,platform",
            },
            {
                "event": "question-presented",
                "decision_id": "D-007",
                "current_state": "linked specifications disagree on age and platform behavior",
                "options": "Android contract|web 18+",
                "consequences": "audience and release gates",
                "risks": "compliance and fragmented behavior",
                "recommendation": "separate platform contracts",
                "affected_scope": "platform matrix,roadmap",
            },
            {
                "event": "user-decision",
                "decision_id": "D-007",
                "selection": "separate platform contracts",
                "source": "user reply 2",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-007",
                "basis": "user-decision",
                "target": "TZ.md",
                "change": "platform matrix and roadmap",
                "answer_source": "user reply 2",
                "selected_outcome": "separate platform contracts",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-006",
                "basis": "locked-decision",
                "target": "TZ/09.md",
                "change": "duel platform invariant",
                "answer_source": "TZ/09.md",
                "selected_outcome": "web-only duels",
            },
            self.application(
                "D-007",
                "TZ.md",
                "platform matrix and roadmap",
                "user reply 2",
                "separate platform contracts",
            ),
            self.application(
                "D-006",
                "TZ/09.md",
                "duel platform invariant",
                "TZ/09.md",
                "web-only duels",
            ),
            {
                "event": "decision-application-receipt",
                "application_count": "2",
                "preserved_decisions": "D-006",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        self.assertEqual(validate_decision_authority_trace(trace), [])

    def test_normative_rewrite_cannot_happen_while_question_is_open(self) -> None:
        trace = [
            *self.source_map("TZ.md", "TZ/11.md"),
            {
                "event": "gap-classified",
                "gap_id": "B-008",
                "decision_id": "D-008",
                "disposition": "product-decision",
                "impact": "monetization,rewards",
            },
            {
                "event": "question-presented",
                "decision_id": "D-008",
                "current_state": "Alpha reward sources conflict",
                "options": "remove|gate|launch",
                "consequences": "changes Alpha rewards",
                "risks": "store rejection and legal exposure",
                "recommendation": "gate",
                "affected_scope": "rewards specification,acceptance criteria,roadmap",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-008",
                "basis": "root-adjudication",
                "target": "TZ/11.md",
                "change": "Alpha reward policy",
                "answer_source": "root preference",
                "selected_outcome": "gate",
            },
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("user decision must precede" in error for error in errors))

    def test_product_impact_cannot_be_relabelled_as_technical(self) -> None:
        trace = [
            *self.source_map("TZ.md"),
            {
                "event": "gap-classified",
                "gap_id": "B-004",
                "decision_id": "T-004",
                "disposition": "technical-decision",
                "impact": "pricing",
            },
            {
                "event": "technical-decision",
                "decision_id": "T-004",
                "preserves_locked_outcomes": "false",
                "normative_effect": "true",
                "preservation_evidence": "none",
            },
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("product-impacting gap" in error for error in errors))
        self.assertTrue(any("technical decision" in error for error in errors))

    def test_user_answer_does_not_authorize_adjacent_root_adjudication(self) -> None:
        trace = [
            *self.source_map("TZ.md", "TZ/12.md"),
            {
                "event": "user-decision",
                "decision_id": "D-014",
                "selection": "publish after first completed battle",
                "source": "user reply 4",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-015",
                "basis": "root-adjudication",
                "target": "TZ/12.md",
                "change": "admin MFA policy",
                "answer_source": "root preference",
                "selected_outcome": "require MFA",
            },
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("user decision must precede" in error for error in errors))

    def test_ready_requires_complete_source_map_and_application_receipt(self) -> None:
        trace = [
            *self.source_map(
                "TZ.md",
                "TZ/09.md",
                complete="false",
                decisions={"TZ/09.md": "D-006"},
            ),
            {
                "event": "locked-decision",
                "decision_id": "D-006",
                "source": "TZ/09.md",
                "status": "resolved",
                "selected_outcome": "web-only duels",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-006",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "duel platform invariant",
                "answer_source": "TZ/09.md",
                "selected_outcome": "web-only duels",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("source map" in error for error in errors))
        self.assertTrue(any("application receipt" in error for error in errors))

    def test_application_receipt_must_cover_every_normative_write(self) -> None:
        trace = [
            *self.source_map(
                "TZ.md",
                "TZ/09.md",
                decisions={"TZ/09.md": "D-006"},
            ),
            {
                "event": "locked-decision",
                "decision_id": "D-006",
                "source": "TZ/09.md",
                "status": "resolved",
                "selected_outcome": "web-only duels",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-006",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "duel platform invariant",
                "answer_source": "TZ/09.md",
                "selected_outcome": "web-only duels",
            },
            {
                "event": "decision-application-receipt",
                "application_count": "0",
                "preserved_decisions": "D-006",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("omits normative writes" in error for error in errors))

    def test_reopening_invalidates_the_old_locked_answer(self) -> None:
        trace = [
            *self.source_map("TZ.md", decisions={"TZ.md": "D-001"}),
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "web-only",
            },
            {
                "event": "decision-reopened",
                "decision_id": "D-001",
                "evidence": "new platform contract",
                "changed_consequence": "web-only now blocks required Android scope",
            },
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "web-only",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "platform availability",
                "answer_source": "TZ.md",
                "selected_outcome": "web-only",
            },
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("non-reopened resolved" in error for error in errors))
        self.assertTrue(any("user decision must precede" in error for error in errors))

    def test_complete_source_map_requires_structured_provenance(self) -> None:
        trace = [
            {
                "event": "spec-source-map",
                "root": "",
                "source_count": "0",
                "complete": "true",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("structured sources" in error for error in errors))
        self.assertTrue(any("source map root" in error for error in errors))

    def test_gap_impact_uses_a_closed_schema(self) -> None:
        trace = [
            *self.source_map("TZ.md"),
            {
                "event": "gap-classified",
                "gap_id": "B-020",
                "decision_id": "T-020",
                "disposition": "technical-decision",
                "impact": "market-fit",
            },
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("closed canonical schema" in error for error in errors))

    def test_application_mapping_must_match_answer_and_write_provenance(self) -> None:
        trace = [
            *self.source_map(
                "TZ.md",
                "TZ/09.md",
                decisions={"TZ/09.md": "D-006"},
            ),
            {
                "event": "locked-decision",
                "decision_id": "D-006",
                "source": "TZ/09.md",
                "status": "resolved",
                "selected_outcome": "web-only duels",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-006",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "duel platform invariant",
                "answer_source": "TZ/09.md",
                "selected_outcome": "web-only duels",
            },
            self.application(
                "D-006",
                "TZ.md",
                "duel platform invariant",
                "TZ.md",
                "global duels",
            ),
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("answer source does not match" in error for error in errors))
        self.assertTrue(any("outcome does not match" in error for error in errors))

    def test_answered_independent_decision_can_apply_while_another_remains_open(self) -> None:
        trace = [
            *self.source_map("TZ.md"),
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "audience unspecified",
                "options": "13+|18+",
                "consequences": "changes eligible audience",
                "risks": "compliance and reach",
                "recommendation": "18+",
                "affected_scope": "audience contract",
            },
            {
                "event": "question-presented",
                "decision_id": "D-002",
                "current_state": "reward policy unspecified",
                "options": "deterministic|chance-based",
                "consequences": "changes rewards",
                "risks": "platform policy",
                "recommendation": "deterministic",
                "affected_scope": "rewards contract",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "18+",
                "source": "user reply 1",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "user-decision",
                "target": "TZ.md",
                "change": "audience contract",
                "answer_source": "user reply 1",
                "selected_outcome": "18+",
            },
            self.application("D-001", "TZ.md", "audience contract", "user reply 1", "18+"),
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "none",
                "remaining_open": "D-002",
            },
        ]

        self.assertEqual(validate_decision_authority_trace(trace), [])

    def test_complete_source_map_requires_closed_structured_links(self) -> None:
        trace = [
            *self.source_map(
                "TZ.md",
                "TZ/known.md",
                links={
                    "TZ.md": "TZ/known.md,TZ/missing.md",
                    "TZ/known.md": "none",
                },
            ),
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("unmapped normative links" in error for error in errors))
        self.assertTrue(any("complete specification source map" in error for error in errors))

        unreachable = [
            *self.source_map(
                "TZ.md",
                "TZ/orphan.md",
                links={"TZ.md": "none", "TZ/orphan.md": "none"},
            ),
            {"event": "ready", "open_decisions": "none"},
        ]
        self.assertTrue(
            any("unreachable specification sources" in error for error in validate_decision_authority_trace(unreachable))
        )

    def test_conflict_reconciliation_requires_authority_not_free_text(self) -> None:
        trace = self.source_map("TZ.md", "TZ/09.md")
        trace[1]["reconciliation"] = "conflict"
        trace.extend(
            [
                {
                    "event": "spec-source-reconciled",
                    "path": "TZ/09.md",
                    "reconciliation": "aligned",
                    "evidence": "root preference",
                },
                {"event": "ready", "open_decisions": "none"},
            ]
        )

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("conflict resolution requires" in error for error in errors))
        self.assertTrue(any("unreconciled specification sources" in error for error in errors))

    def test_initial_defer_and_unstructured_precedence_are_not_authority(self) -> None:
        deferred = self.source_map("TZ.md")
        deferred[0]["reconciliation"] = "deferred"
        deferred[0]["deferred_by"] = "root preference"
        deferred.append({"event": "ready", "open_decisions": "none"})
        self.assertTrue(
            any("post-map user-decision reconciliation" in error for error in validate_decision_authority_trace(deferred))
        )

        precedence = self.source_map("TZ.md", "TZ/09.md")
        precedence[1]["reconciliation"] = "conflict"
        precedence.extend(
            [
                {
                    "event": "spec-source-reconciled",
                    "path": "TZ/09.md",
                    "reconciliation": "aligned",
                    "resolution_basis": "explicit-precedence",
                    "authority_source": "TZ.md",
                    "authority_record": "root preference",
                    "evidence": "root preference",
                },
                {"event": "ready", "open_decisions": "none"},
            ]
        )
        precedence_errors = validate_decision_authority_trace(precedence)
        self.assertTrue(any("structured authority record" in error for error in precedence_errors))
        self.assertTrue(any("unreconciled specification sources" in error for error in precedence_errors))

    def test_user_answer_can_reconcile_a_mapped_source_conflict(self) -> None:
        trace = self.source_map("TZ.md", "TZ/09.md")
        trace[1]["reconciliation"] = "conflict"
        trace.extend(
            [
                {
                    "event": "gap-classified",
                    "gap_id": "B-021",
                    "decision_id": "D-021",
                    "disposition": "product-decision",
                    "impact": "platform,scope",
                },
                {
                    "event": "question-presented",
                    "decision_id": "D-021",
                    "current_state": "root and linked platform contracts conflict",
                    "options": "web-only|multiplatform",
                    "consequences": "changes availability and roadmap",
                    "risks": "scope expansion or lost reach",
                    "recommendation": "web-only for Alpha",
                    "affected_scope": "platform contract,roadmap",
                },
                {
                    "event": "user-decision",
                    "decision_id": "D-021",
                    "selection": "web-only",
                    "source": "user reply 3",
                },
                {
                    "event": "spec-source-reconciled",
                    "path": "TZ/09.md",
                    "reconciliation": "aligned",
                    "resolution_basis": "user-decision",
                    "decision_id": "D-021",
                    "answer_source": "user reply 3",
                    "selected_outcome": "web-only",
                    "evidence": "user selected web-only",
                },
                {"event": "ready", "open_decisions": "none"},
            ]
        )

        self.assertEqual(validate_decision_authority_trace(trace), [])

    def test_structured_precedence_record_can_reconcile_a_conflict(self) -> None:
        trace = self.source_map("TZ.md", "TZ/09.md")
        trace[1]["reconciliation"] = "conflict"
        trace.extend(
            [
                {
                    "event": "spec-source-reconciled",
                    "path": "TZ/09.md",
                    "reconciliation": "aligned",
                    "resolution_basis": "explicit-precedence",
                    "authority_source": "TZ.md",
                    "authority_record_type": "precedence",
                    "authority_record_target": "TZ/09.md",
                    "authority_record_revision": "current",
                    "authority_record_line": "42",
                    "evidence": "TZ.md:42 explicitly gives the platform matrix precedence",
                },
                {"event": "ready", "open_decisions": "none"},
            ]
        )

        self.assertEqual(validate_decision_authority_trace(trace), [])

    def test_locked_decision_must_be_declared_by_provenance_source(self) -> None:
        trace = [
            *self.source_map("TZ.md"),
            {
                "event": "locked-decision",
                "decision_id": "D-999",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "root-selected outcome",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-999",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "invented product contract",
                "answer_source": "TZ.md",
                "selected_outcome": "root-selected outcome",
            },
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("not declared by provenance source" in error for error in errors))
        self.assertTrue(any("user decision must precede" in error for error in errors))

    def test_reopened_decision_cannot_attribute_an_old_write_to_the_new_answer(self) -> None:
        trace = [
            *self.source_map("TZ.md", decisions={"TZ.md": "D-001"}),
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "old",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "TZ.md",
                "selected_outcome": "old",
            },
            {
                "event": "decision-reopened",
                "decision_id": "D-001",
                "evidence": "new platform policy",
                "changed_consequence": "the old choice is no longer viable",
            },
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "old platform contract is invalid",
                "options": "new-a|new-b",
                "consequences": "changes availability",
                "risks": "migration and reach",
                "recommendation": "new-a",
                "affected_scope": "platform contract",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "new-a",
                "source": "user reply 5",
            },
            self.application("D-001", "TZ.md", "platform contract", "user reply 5", "new-a"),
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "none",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("reopened decision requires current normative reapplication" in error for error in errors))
        self.assertTrue(any("earlier normative write" in error for error in errors))

    def test_reopened_decision_can_rebuild_and_receipt_the_current_product_map(self) -> None:
        trace = [
            *self.source_map("TZ.md", decisions={"TZ.md": "D-001"}),
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "old",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "TZ.md",
                "selected_outcome": "old",
            },
            {
                "event": "decision-reopened",
                "decision_id": "D-001",
                "evidence": "new platform policy",
                "changed_consequence": "the old choice is no longer viable",
            },
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "old platform contract is invalid",
                "options": "new-a|new-b",
                "consequences": "changes availability",
                "risks": "migration and reach",
                "recommendation": "new-a",
                "affected_scope": "platform contract",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "new-a",
                "source": "user reply 5",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "user-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "user reply 5",
                "selected_outcome": "new-a",
            },
            self.application("D-001", "TZ.md", "platform contract", "user reply 5", "new-a"),
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "none",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        self.assertEqual(validate_decision_authority_trace(trace), [])

    def test_reopened_decision_can_record_a_user_confirmed_noop(self) -> None:
        trace = [
            *self.source_map("TZ.md", decisions={"TZ.md": "D-001"}),
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "web-only",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "TZ.md",
                "selected_outcome": "web-only",
            },
            {
                "event": "decision-reopened",
                "decision_id": "D-001",
                "evidence": "new platform policy",
                "changed_consequence": "web-only must be reconfirmed",
            },
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "web-only needs confirmation",
                "options": "web-only|multiplatform",
                "consequences": "changes availability",
                "risks": "reach or scope expansion",
                "recommendation": "web-only",
                "affected_scope": "platform contract",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "web-only",
                "source": "user reply 6",
            },
            {
                "event": "decision-noop-application",
                "decision_id": "D-001",
                "answer_source": "user reply 6",
                "selected_outcome": "web-only",
                "confirmed_no_change": "true",
                "affected_targets": "TZ.md::platform contract",
                "reason": "the current product map already matches the reconfirmed outcome",
            },
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "D-001",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        self.assertEqual(validate_decision_authority_trace(trace), [])

    def test_reopened_decision_cannot_noop_a_different_outcome(self) -> None:
        trace = [
            *self.source_map("TZ.md", decisions={"TZ.md": "D-001"}),
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "old",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "TZ.md",
                "selected_outcome": "old",
            },
            {
                "event": "decision-reopened",
                "decision_id": "D-001",
                "evidence": "new platform policy",
                "changed_consequence": "old is no longer viable",
            },
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "old platform contract is invalid",
                "options": "new|remove",
                "consequences": "changes availability",
                "risks": "migration and reach",
                "recommendation": "new",
                "affected_scope": "platform contract",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "new",
                "source": "user reply 7",
            },
            {
                "event": "decision-noop-application",
                "decision_id": "D-001",
                "answer_source": "user reply 7",
                "selected_outcome": "new",
                "confirmed_no_change": "true",
                "affected_targets": "TZ.md::platform contract",
                "reason": "claimed no change",
            },
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "none",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("repeat the pre-reopen outcome" in error for error in errors))
        self.assertTrue(any("reopened decision requires current normative reapplication" in error for error in errors))

    def test_reopened_decision_reapplies_every_previously_affected_target(self) -> None:
        trace = [
            *self.source_map(
                "TZ.md",
                "TZ/09.md",
                decisions={"TZ.md": "D-001"},
            ),
            {
                "event": "locked-decision",
                "decision_id": "D-001",
                "source": "TZ.md",
                "status": "resolved",
                "selected_outcome": "old",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "TZ.md",
                "selected_outcome": "old",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "locked-decision",
                "target": "TZ/09.md",
                "change": "duel availability",
                "answer_source": "TZ.md",
                "selected_outcome": "old",
            },
            {
                "event": "decision-reopened",
                "decision_id": "D-001",
                "evidence": "new platform policy",
                "changed_consequence": "all platform contracts must be rebuilt",
            },
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "old platform contract is invalid",
                "options": "new|remove",
                "consequences": "changes availability",
                "risks": "migration and reach",
                "recommendation": "new",
                "affected_scope": "root and duel platform contracts",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "new",
                "source": "user reply 8",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "user-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "user reply 8",
                "selected_outcome": "new",
            },
            self.application("D-001", "TZ.md", "platform contract", "user reply 8", "new"),
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "none",
                "remaining_open": "none",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("TZ/09.md" in error and "duel availability" in error for error in errors))

    def test_second_user_answer_cannot_replace_a_locked_decision_without_reopen(self) -> None:
        trace = [
            *self.source_map("TZ.md"),
            {
                "event": "question-presented",
                "decision_id": "D-001",
                "current_state": "platform unspecified",
                "options": "a|b",
                "consequences": "changes availability",
                "risks": "reach and scope",
                "recommendation": "a",
                "affected_scope": "platform contract",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "a",
                "source": "user reply 1",
            },
            {
                "event": "normative-spec-write",
                "decision_id": "D-001",
                "basis": "user-decision",
                "target": "TZ.md",
                "change": "platform contract",
                "answer_source": "user reply 1",
                "selected_outcome": "a",
            },
            self.application("D-001", "TZ.md", "platform contract", "user reply 1", "a"),
            {
                "event": "decision-application-receipt",
                "application_count": "1",
                "preserved_decisions": "none",
                "remaining_open": "none",
            },
            {
                "event": "user-decision",
                "decision_id": "D-001",
                "selection": "b",
                "source": "user reply 2",
            },
            {"event": "ready", "open_decisions": "none"},
        ]

        errors = validate_decision_authority_trace(trace)
        self.assertTrue(any("cannot replace a locked decision without decision-reopened" in error for error in errors))
        self.assertTrue(any("stale decision versions" in error for error in errors))


class UsageRoutingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.model_routing = (SKILL / "references" / "model-routing.md").read_text(encoding="utf-8")
        self.code_discovery = (SKILL / "references" / "code-discovery.md").read_text(encoding="utf-8")
        self.implementation = IMPLEMENTATION_DELEGATION.read_text(encoding="utf-8")
        self.review_protocol = REVIEW_PROTOCOL.read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.template_text = (SKILL / "references" / "spec-template.md").read_text(encoding="utf-8")
        self.model_map_interview = (SKILL / "references" / "model-map-interview.md").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_usage_routing_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("model_routing", self.model_routing),
            overrides.get("code_discovery", self.code_discovery),
            overrides.get("implementation", self.implementation),
            overrides.get("review_protocol", self.review_protocol),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
            overrides.get("model_map_interview", self.model_map_interview),
            overrides.get("template_text", self.template_text),
        )

    def test_reasoning_first_owner_docs_cannot_regress_to_the_old_route_ceiling(self) -> None:
        self.assertEqual(self.validate(), [])
        mutations = [
            ("model_map_interview", "one, two, three, four, or five steps"),
            ("implementation", "openbuild_implementation_luna_xhigh"),
            ("review_protocol", "exact configured profile/model-effort step"),
            ("model_routing", "exact canonical openbuild_implementation_* ID from the displayed route"),
            ("template_text", "ordered exact canonical profile/model/effort steps, up to five"),
        ]
        for field, token in mutations:
            with self.subTest(field=field):
                altered = getattr(self, field).replace(token, "stale-route-contract")
                self.assertTrue(
                    any(
                        "reasoning-first owner docs" in error
                        for error in self.validate(**{field: altered})
                    )
                )

    def test_review_result_contract_names_each_reasoning_first_tier(self) -> None:
        for tier in ("luna_xhigh", "sol_high"):
            with self.subTest(tier=tier):
                altered = self.review_protocol.replace(tier, f"missing_{tier}")
                self.assertTrue(
                    any(
                        "review-protocol.md exact reviewer routing" in error
                        for error in self.validate(review_protocol=altered)
                    )
                )

    def validate_agent_usage(self, **overrides: str) -> list[str]:
        return validate_agent_usage_report_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("model_routing", self.model_routing),
            overrides.get("template_text", self.template_text),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
        )

    def test_agent_usage_ledger_counts_created_logical_runs_without_hiding_failures(self) -> None:
        self.assertEqual(self.validate_agent_usage(), [])

        for token, replacement in [
            ("search, critic, implementation, or review agent through the exact runner", "selected agent runs"),
            ("wrapper and its child `codex exec` are one logical run", "wrapper and child are separate runs"),
            ("Pre-spawn dispatch failures do not increment the created-run count", "Dispatch failures increment the count"),
            ("unusable, cancelled, or timed out", "failed"),
        ]:
            with self.subTest(token=token):
                skill_text = self.skill_text.replace(token, replacement)
                self.assertTrue(
                    any("agent usage" in error for error in self.validate_agent_usage(skill_text=skill_text))
                )

    def test_agent_usage_reports_actual_evidence_work_mapping_and_privacy(self) -> None:
        self.assertEqual(self.validate_agent_usage(), [])

        for token, replacement in [
            ("accepted explicit-runner receipt", "configured profile"),
            ("Never create an agent row from a requested label or unverified native dispatch", "Configured labels are accepted"),
            ("AC, milestone, or specification section", "task"),
            ("PID, thread ID, private run path, raw prompt, raw log, token or usage value, or authentication detail", "private runtime details"),
        ]:
            with self.subTest(token=token):
                template_text = self.template_text.replace(token, replacement)
                self.assertTrue(
                    any("agent usage" in error for error in self.validate_agent_usage(template_text=template_text))
                )

    def test_exact_agent_dependency_checkpoint_and_manual_auth_are_required(self) -> None:
        self.assertEqual(self.validate_agent_usage(), [])

        mutations = [
            ("skill_text", "`python --version`", "check Python"),
            ("skill_text", "`codex --version`", "check Codex"),
            ("model_routing", "`winget install -e --id Python.Python.3.12`", "install Python"),
            (
                "model_routing",
                '`powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"`',
                "install Codex CLI",
            ),
            ("model_routing", "`codex login status`", "check login"),
            ("model_routing", "Authentication remains manual", "Automate authentication"),
            ("model_routing", "separate explicit permission", "implicit permission"),
        ]
        for field, token, replacement in mutations:
            with self.subTest(field=field, token=token):
                value = getattr(self, field).replace(token, replacement)
                self.assertTrue(
                    any("dependency checkpoint" in error for error in self.validate_agent_usage(**{field: value}))
                )

    def test_dependency_checkpoint_is_os_aware(self) -> None:
        self.assertEqual(self.validate_agent_usage(), [])

        mutations = [
            ("skill_text", "On Windows, run `python --version`.", "Run `python --version`."),
            (
                "skill_text",
                "On POSIX, run `python3 --version` first and use `python --version` only as a fallback.",
                "On POSIX, run `python --version`.",
            ),
            ("skill_text", "Run `codex --version` on every platform.", "Run `codex --version`."),
            (
                "model_routing",
                "Show the `winget` and standalone PowerShell commands only on Windows.",
                "Show the install commands on every platform.",
            ),
            (
                "model_routing",
                "On POSIX, provide manual, platform-appropriate Python and Codex CLI installation guidance without choosing or running a package manager.",
                "On POSIX, choose a package manager automatically.",
            ),
        ]
        for field, token, replacement in mutations:
            with self.subTest(field=field, token=token):
                value = getattr(self, field).replace(token, replacement)
                self.assertTrue(
                    any(
                        "OS-aware dependency checkpoint" in error
                        for error in self.validate_agent_usage(**{field: value})
                    )
                )

    def test_readmes_are_concise_and_use_exact_four_install_commands(self) -> None:
        self.assertEqual(self.validate_agent_usage(), [])

        for field, token in [
            ("readme", "codex plugin remove openbuild@openbuild"),
            ("readme_ru", "codex plugin marketplace remove openbuild"),
        ]:
            with self.subTest(field=field, token=token):
                value = getattr(self, field).replace(token, "")
                self.assertTrue(
                    any("exactly the four supported commands" in error for error in self.validate_agent_usage(**{field: value}))
                )

        readme = self.readme + "\n## How TDD-first implementation works\n" + ("\n" * 150)
        errors = self.validate_agent_usage(readme=readme)
        self.assertTrue(any("removed verbose section" in error for error in errors))
        self.assertTrue(any("exceeds 140 lines" in error for error in errors))

    def test_russian_routing_diagram_keeps_long_labels_inside_panels(self) -> None:
        svg = (ROOT / "plugins" / "openbuild" / "lib" / "usage-v3-ru.svg").read_text(
            encoding="utf-8"
        )
        self.assertIn('<rect x="822" y="397" width="227" height="105"', svg)
        self.assertIn(
            '<text x="935" y="429" text-anchor="middle" class="small"',
            svg,
        )
        self.assertIn(
            '<text x="258" y="838" text-anchor="middle" class="tiny"',
            svg,
        )
        png = (ROOT / "plugins" / "openbuild" / "lib" / "usage-v3-ru.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(
            (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")),
            (1600, 1000),
        )

    def test_final_agent_heading_is_localized_to_the_response_language(self) -> None:
        self.assertEqual(self.validate_agent_usage(), [])

        for field, token, replacement in [
            (
                "skill_text",
                "Use `Agents` for an English response and `Агенты` for a Russian response.",
                "Use `Agent usage` for every response.",
            ),
            (
                "template_text",
                "The final localized report uses `Agents` for English and `Агенты` for Russian.",
                "The final report uses `Agent usage` for every language.",
            ),
        ]:
            with self.subTest(field=field):
                value = getattr(self, field).replace(token, replacement)
                self.assertTrue(
                    any(
                        "localized agent heading" in error
                        for error in self.validate_agent_usage(**{field: value})
                    )
                )

        self.assertNotIn("`Agent usage`", self.skill_text)
        self.assertNotIn("`Agent usage`", self.template_text)

    def test_configured_search_route_precedes_root_recovery(self) -> None:
        self.assertEqual(self.validate(), [])

        model_routing = self.model_routing.replace("**Configured exact route:**", "**Search worker:**")
        self.assertTrue(any("search usage-pool" in error for error in self.validate(model_routing=model_routing)))

        exact = "**Configured exact route:**"
        recovery = "**Root recovery:**"
        model_routing = self.model_routing.replace(exact, "__SEARCH_ORDER__").replace(recovery, exact).replace("__SEARCH_ORDER__", recovery)
        self.assertTrue(any("must precede root recovery" in error for error in self.validate(model_routing=model_routing)))

    def test_explicit_cli_runner_is_packaged_and_is_the_primary_dispatch(self) -> None:
        self.assertTrue((SKILL / "scripts" / "agent_runner.py").is_file())
        for text in [
            self.skill_text,
            self.model_routing,
            self.code_discovery,
            self.implementation,
            self.review_protocol,
            self.readme,
            self.readme_ru,
        ]:
            self.assertIn("codex-exec-explicit-model", text)
        self.assertIn("agent_runner.py", self.skill_text)
        self.assertIn("turn.completed", self.model_routing)

    def test_packaged_explorer_instruction_is_exact_not_token_matched(self) -> None:
        profile = {
            "name": "openbuild_search_separate",
            "model": PACKAGED_SEARCH_MODEL,
            "model_reasoning_effort": "low",
            "sandbox_mode": "read-only",
            "developer_instructions": PACKAGED_SEARCH_INSTRUCTIONS,
        }
        self.assertEqual(validate_packaged_search_profile(profile), [])

        profile["developer_instructions"] = (
            PACKAGED_SEARCH_INSTRUCTIONS
            + "Semantically alter the contract while retaining all required tokens.\n"
        )
        self.assertTrue(
            any("exact canonical" in error for error in validate_packaged_search_profile(profile))
        )

    def test_search_preflight_precedes_repository_lookup(self) -> None:
        initialized = "## Initialize search routing"
        selection = "## Select the specification safely"
        skill_text = self.skill_text.replace(initialized, "__ROUTING_HEADING__").replace(selection, initialized).replace("__ROUTING_HEADING__", selection)
        self.assertTrue(any("must precede specification selection" in error for error in self.validate(skill_text=skill_text)))

    def test_runtime_safe_profile_ids_and_guided_migration_are_required(self) -> None:
        combined = "\n".join(
            [
                self.skill_text,
                self.model_routing,
                self.code_discovery,
                self.implementation,
                self.review_protocol,
                self.readme,
                self.readme_ru,
            ]
        )
        for profile in [
            "openbuild_search_separate",
            "openbuild_implementation_fast",
            "openbuild_implementation_balanced",
            "openbuild_implementation_strong",
            "openbuild_implementation_strongest",
            "openbuild_review_fast",
            "openbuild_review_balanced",
            "openbuild_review_strong",
            "openbuild_review_strongest",
        ]:
            with self.subTest(profile=profile):
                self.assertIn(profile, combined)
        for token in [
            "immutable `plan_id`",
            "stable `entry_id`",
            "SHA-256",
            "create-if-absent",
            "already-migrated",
            "config-conflict",
            "per-entry authority",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, self.model_routing)

    def test_exact_named_search_agent_dispatch_precedes_repository_search(self) -> None:
        skill_text = self.skill_text.replace(
            "scripts/model_map.py resolve --use-case discovery --risk default",
            "Attempt a suitable search worker",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(skill_text=skill_text)))

        code_discovery = self.code_discovery.replace(
            "before the root runs any new repository search command",
            "early in repository discovery",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(code_discovery=code_discovery)))

        code_discovery = self.code_discovery.replace(
            "All other transport/exact-selection/result failures use only minimum targeted root recovery.",
            "Use legacy `openbuild-discovery` when needed.",
        )
        self.assertTrue(any("legacy openbuild-discovery" in error for error in self.validate(code_discovery=code_discovery)))

    def test_search_and_review_activation_are_runner_owned(self) -> None:
        code_discovery = self.code_discovery.replace("runner-owned `dispatch`", "manual `start` and `activate`")
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(code_discovery=code_discovery)))

        review_protocol = self.review_protocol.replace("runner-owned `dispatch`", "manual `start` and `activate`")
        self.assertTrue(any("exact reviewer routing" in error for error in self.validate(review_protocol=review_protocol)))

    def test_silent_generic_fallback_and_missing_receipt_are_rejected(self) -> None:
        model_routing = self.model_routing.replace(
            "profile-not-discoverable",
            "profile issue",
        )
        self.assertTrue(any("fallback reason" in error for error in self.validate(model_routing=model_routing)))

        discovery = self.code_discovery.replace(
            "Search routing receipt",
            "Search routing summary",
        )
        self.assertTrue(any("routing receipt" in error for error in self.validate(code_discovery=discovery)))

    def test_search_quota_failure_opens_one_run_circuit_breaker(self) -> None:
        model_routing = self.model_routing.replace("opens the circuit breaker", "falls back")
        self.assertTrue(any("search usage-pool" in error for error in self.validate(model_routing=model_routing)))

        discovery = self.code_discovery.replace(
            "All other transport/exact-selection/result failures",
            "Retry all other transport/exact-selection/result failures",
        )
        self.assertTrue(any("code-discovery.md" in error for error in self.validate(code_discovery=discovery)))

    def test_discovery_fallback_preserves_lifecycle_and_path_safeguards(self) -> None:
        for token in (
            "rung metadata is validated after profile precedence resolves",
            "same-OS-account confirmation plus exact legacy binding/commit/remediation/Git evidence",
            "diagnostic root review cannot close an exact-review or release gate",
        ):
            with self.subTest(model_routing=token):
                mutated = self.model_routing.replace(token, "removed safeguard")
                self.assertTrue(
                    any(
                        "preserved lifecycle safeguard" in error
                        for error in self.validate(model_routing=mutated)
                    )
                )

        for token in (
            "coherent pre-turn",
            "complete JSONL/stderr collection",
            "every explicit error record",
            "raw top-level `code`",
            "unrecognized error-bearing event",
            "present JSONL, stderr, and result read",
            "verified regular non-reparse descriptor identity",
            "conflicting `code`/`type` values",
            "JSONL and stderr evidence",
            "Source-time Spark/Terra",
        ):
            with self.subTest(search_order=token):
                mutated = self.model_routing.replace(token, "removed search safeguard")
                self.assertTrue(
                    any(
                        "search usage-pool order" in error
                        for error in self.validate(model_routing=mutated)
                    )
                )

        for token in (
            "literal backslashes fail closed",
            "`.pytest_cache`",
            "`artifacts`",
            "`target`",
            "symlink/reparse escapes",
            "same-object identity checks",
            "Checked-out gitlinks contribute a bounded nested tracked plus untracked/nonignored content fingerprint",
        ):
            with self.subTest(code_discovery=token):
                mutated = self.code_discovery.replace(token, "removed path safeguard")
                self.assertTrue(
                    any(
                        "evidence contract" in error
                        for error in self.validate(code_discovery=mutated)
                    )
                )

    def test_code_edits_use_risk_matched_writer_tiers(self) -> None:
        implementation = self.implementation.replace(
            "effective user, project, or packaged model map for every complexity class",
            "suitable coding model",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        for profile in [
            "openbuild_implementation_fast",
            "openbuild_implementation_balanced",
            "openbuild_implementation_strong",
            "openbuild_implementation_strongest",
        ]:
            model_routing = self.model_routing.replace(profile, "missing-writer-profile")
            self.assertTrue(any("implementation routing" in error for error in self.validate(model_routing=model_routing)))

    def test_exact_named_writer_dispatch_precedes_every_code_edit(self) -> None:
        implementation = self.implementation.replace(
            "Dispatch the first exact profile returned by `<build-skill-root>/scripts/model_map.py resolve --use-case implementation --risk <risk>` before every test or production code edit",
            "Prefer that profile while implementing",
        )
        self.assertTrue(any("exact writer dispatch" in error for error in self.validate(implementation=implementation)))

        implementation = self.implementation.replace(
            "Implementation routing receipt",
            "Implementation routing summary",
        )
        self.assertTrue(any("implementation routing receipt" in error for error in self.validate(implementation=implementation)))

    def test_reviewers_use_exact_profiles_in_a_sequential_ladder(self) -> None:
        model_routing = self.model_routing.replace(
            "Resolve the exact starting reviewer through `model_map.py`",
            "Choose a suitable reviewer",
        )
        self.assertTrue(any("exact reviewer dispatch" in error for error in self.validate(model_routing=model_routing)))

        model_routing = self.model_routing.replace(
            "Run reviewers one at a time in the returned order",
            "Run reviewers in any order",
        )
        self.assertTrue(any("sequential review ladder" in error for error in self.validate(model_routing=model_routing)))

        review_protocol = self.review_protocol.replace(
            "Review routing receipt",
            "Review routing summary",
        )
        self.assertTrue(any("review-protocol.md" in error for error in self.validate(review_protocol=review_protocol)))

        review_protocol = self.review_protocol.replace(
            "The non-critical route ends at Sol/high; Sol/xhigh is critical-only",
            "A non-critical route may continue from Sol/high to Sol/xhigh",
        )
        self.assertTrue(
            any(
                "review-protocol.md" in error
                for error in self.validate(review_protocol=review_protocol)
            )
        )

    def test_writer_escalation_preserves_tdd_and_single_writer_controls(self) -> None:
        model_routing = self.model_routing.replace(
            "Escalate only on evidence",
            "Escalate whenever a stronger model exists",
        )
        self.assertTrue(any("implementation routing" in error for error in self.validate(model_routing=model_routing)))

        implementation = self.implementation.replace(
            "Every created implementation run requires concrete model, effort, and sandbox evidence",
            "Implementation may use an unverified label",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        model_routing = self.model_routing.replace(
            "checkpoint_invalidation=pending",
            "checkpoint invalidation may be attempted later",
        )
        self.assertTrue(
            any(
                "implementation routing" in error
                for error in self.validate(model_routing=model_routing)
            )
        )

    def test_recovery_provenance_docs_lock_index_flags_and_reparse_points(self) -> None:
        for token in (
            "`git ls-files --stage -v -z`",
            "`assume-unchanged`",
            "`skip-worktree`",
            "`FILE_ATTRIBUTE_REPARSE_POINT`",
            "every path component with non-following metadata",
            "holds the same object identity through hashing and enumeration",
            "Immediately before activation",
            "`clone3(CLONE_INTO_CGROUP)`",
            "privacy-safe terminal archive",
            "fallback bind uses the same visible-generation resolution",
            "Before any registry or private-source durable replace",
        ):
            with self.subTest(token=token):
                implementation = self.implementation.replace(token, "omitted safety guard")
                self.assertTrue(
                    any(
                        "implementation-delegation.md" in error
                        for error in self.validate(implementation=implementation)
                    )
                )

    def test_high_start_and_critical_writer_floor_cannot_be_relaxed(self) -> None:
        implementation = self.implementation.replace(
            "`high` | the same Terra/medium → Terra/xhigh → Sol/high ladder",
            "`high` | any configured profile",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        implementation = self.implementation.replace(
            "`critical` | Sol/xhigh `openbuild_implementation_strongest`",
            "`critical` | any configured profile",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))


class SearchDispatchTraceTests(unittest.TestCase):
    @staticmethod
    def selected_trace() -> list[dict[str, object]]:
        running = {
            "event": "search-routing-receipt",
            "search_agent": "openbuild_search_separate",
            "task_name": "fixture_task",
            "dispatch_method": "codex-exec-explicit-model",
            "configured_model": "gpt-5.3-codex-spark",
            "model_reasoning_effort": "low",
            "sandbox": "read-only",
            "observed_agent": "unknown",
            "observed_model": "unknown",
            "terminal_event": "none",
            "activated": False,
            "run_status": "running",
            "pool": "unknown",
            "dispatch_result": "selected",
            "fallback_reason": "none",
            "process_tree_stopped": False,
            "run_dir": "C:/runs/search-1",
            "worker_pid": "111",
            "worker_process_identity": "worker-created-1",
            "codex_pid": "222",
            "codex_process_identity": "codex-created-1",
        }
        return [
            {
                "event": "search-dispatch",
                "agent_name": "openbuild_search_separate",
                "task_name": "fixture_task",
                "result": "selected",
                "fallback_reason": "none",
            },
            running,
            {
                "event": "search-agent-activated",
                "search_agent": "openbuild_search_separate",
                "task_name": "fixture_task",
                "run_dir": "C:/runs/search-1",
                "worker_process_identity": "worker-created-1",
                "codex_process_identity": "codex-created-1",
                "activated": True,
            },
            {"event": "repository-search", "actor": "openbuild_search_separate"},
            running
            | {
                "observed_agent": "openbuild_search_separate",
                "observed_model": "gpt-5.3-codex-spark",
                "terminal_event": "turn.completed",
                "activated": True,
                "run_status": "completed",
                "process_tree_stopped": True,
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
            },
            {
                "event": "search-evidence-consumed",
                "actor": "root",
                "search_agent": "openbuild_search_separate",
                "run_dir": "C:/runs/search-1",
            },
        ]

    @staticmethod
    def failed_trace(reason: str = "cli-unavailable") -> list[dict[str, object]]:
        return [
            {
                "event": "search-dispatch",
                "agent_name": "openbuild_search_separate",
                "task_name": "fixture_task",
                "result": "failed",
                "fallback_reason": reason,
            },
            {
                "event": "search-routing-receipt",
                "search_agent": "openbuild_search_separate",
                "task_name": "fixture_task",
                "dispatch_method": "unavailable",
                "configured_model": "separate-search-model",
                "model_reasoning_effort": "unknown",
                "sandbox": "unknown",
                "observed_agent": "unknown",
                "observed_model": "unknown",
                "terminal_event": "none",
                "activated": False,
                "run_status": "failed",
                "pool": "unknown",
                "dispatch_result": "failed",
                "fallback_reason": reason,
                "process_tree_stopped": True,
                "run_dir": "none",
                "worker_pid": "none",
                "worker_process_identity": "none",
                "codex_pid": "none",
                "codex_process_identity": "none",
            },
            {"event": "repository-search", "actor": "root"},
        ]

    @classmethod
    def timeout_trace(cls) -> list[dict[str, object]]:
        trace = cls.selected_trace()
        running = trace[1]
        terminal = running | {
            "terminal_event": "none",
            "activated": True,
            "run_status": "failed",
            "pool": "unknown",
            "dispatch_result": "failed",
            "fallback_reason": "worker-timeout",
            "process_tree_stopped": True,
            "codex_exit_evidence": "missing",
            "codex_exit_code": "unknown",
            "result_evidence": "missing",
        }
        return [
            trace[0],
            running,
            trace[2],
            {
                "event": "agent-cancellation-confirmed",
                "worker_pid": "111",
                "codex_pid": "222",
                "codex_started": True,
                "worker_stopped": True,
                "codex_stopped": True,
            },
            terminal,
            {"event": "repository-search", "actor": "root"},
        ]

    @classmethod
    def unusable_after_search_trace(cls, actor: str) -> list[dict[str, object]]:
        trace = cls.selected_trace()
        trace[4].update(
            {
                "run_status": "failed",
                "terminal_event": "turn.completed",
                "dispatch_result": "failed",
                "fallback_reason": "unusable-evidence",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
            }
        )
        trace.pop()
        trace.append({"event": "repository-search", "actor": actor})
        return trace

    def test_canonical_agent_name_is_separate_from_task_name(self) -> None:
        trace = self.selected_trace()
        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_task_name_alone_cannot_select_a_profile(self) -> None:
        trace = self.selected_trace()
        trace[0].pop("agent_name")
        trace[0]["task_name"] = "openbuild_search_separate"

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("agent_name" in error for error in errors))

    def test_exact_named_agent_owns_first_search(self) -> None:
        trace = self.selected_trace()
        trace[3]["actor"] = "root"

        self.assertTrue(any("own the first" in error for error in validate_search_dispatch_trace(trace)))

    def test_selected_worker_owns_every_search_until_its_terminal_receipt(self) -> None:
        trace = self.selected_trace()
        trace.pop()
        trace[4] = trace[4] | {
            "terminal_event": "turn.failed",
            "run_status": "failed",
            "dispatch_result": "failed",
            "fallback_reason": "runner-failed",
            "codex_exit_code": 1,
            "result_evidence": "missing",
        }
        trace.insert(4, {"event": "repository-search", "actor": "openbuild_search_fallback"})

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("every repository search" in error for error in errors))

    def test_selected_worker_cannot_search_after_its_terminal_receipt(self) -> None:
        trace = self.selected_trace()
        trace.append({"event": "repository-search", "actor": "openbuild_search_separate"})

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("after its terminal receipt" in error for error in errors))

    def test_root_or_generic_search_cannot_silently_skip_exact_dispatch(self) -> None:
        trace = [{"event": "repository-search", "actor": "root"}]

        self.assertTrue(any("exact agent dispatch" in error for error in validate_search_dispatch_trace(trace)))

    def test_fallback_requires_an_observable_allowed_reason(self) -> None:
        trace = self.failed_trace("unknown-problem")

        self.assertTrue(any("allowed fallback reason" in error for error in validate_search_dispatch_trace(trace)))

    def test_allowed_root_recovery_and_receipt_remain_consistent(self) -> None:
        trace = self.failed_trace()
        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_failed_search_cannot_dispatch_a_replacement_agent(self) -> None:
        trace = self.failed_trace()
        trace.insert(
            -1,
            {
                "event": "search-dispatch",
                "agent_name": "openbuild_search_replacement",
                "task_name": "replacement_fixture",
                "result": "selected",
                "fallback_reason": "none",
            },
        )

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("cannot create a replacement agent" in error for error in errors))

    def test_exact_runner_does_not_require_confirmed_pool_metadata(self) -> None:
        trace = self.selected_trace()
        trace[1]["pool"] = "unknown"
        trace[4]["pool"] = "unknown"

        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_semantically_unusable_search_transitions_to_root_recovery(self) -> None:
        trace = self.unusable_after_search_trace("root")

        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_post_terminal_failed_search_rejects_replacement_actor(self) -> None:
        trace = self.unusable_after_search_trace("replacement")

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("only root-owned recovery" in error for error in errors))

    def test_native_selected_search_is_rejected(self) -> None:
        trace = self.selected_trace()
        trace[1]["dispatch_method"] = "per-spawn-model"
        trace[4]["dispatch_method"] = "per-spawn-model"

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("invalid dispatch method" in error for error in errors))

    def test_failed_explicit_dispatch_accepts_turn_failed_before_fallback(self) -> None:
        trace = self.failed_trace("model-unavailable")
        trace[1]["dispatch_method"] = "codex-exec-explicit-model"
        trace[1]["sandbox"] = "read-only"
        trace[1]["model_reasoning_effort"] = "low"
        trace[1]["terminal_event"] = "turn.failed"
        trace[1]["codex_exit_evidence"] = "valid"
        trace[1]["codex_exit_code"] = 1
        trace[1]["result_evidence"] = "missing"

        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_failed_explicit_dispatch_requires_complete_exit_and_result_evidence(self) -> None:
        trace = self.failed_trace("runner-failed")
        trace[1]["dispatch_method"] = "codex-exec-explicit-model"
        trace[1]["sandbox"] = "read-only"
        trace[1]["model_reasoning_effort"] = "low"
        trace[1]["terminal_event"] = "turn.failed"

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("missing evidence fields" in error for error in errors))

    def test_worker_timeout_fallback_requires_confirmed_process_tree_stop(self) -> None:
        trace = self.timeout_trace()

        self.assertEqual(validate_search_dispatch_trace(trace), [])
        without_confirmation = [event for event in trace if event["event"] != "agent-cancellation-confirmed"]
        self.assertTrue(
            any(
                "cancellation confirmation" in error
                for error in validate_search_dispatch_trace(without_confirmation)
            )
        )

        before_codex_start = [dict(event) for event in trace]
        confirmation = before_codex_start[3]
        confirmation["codex_started"] = False
        confirmation.pop("codex_pid")
        self.assertEqual(validate_search_dispatch_trace(before_codex_start), [])

    def test_receipt_must_follow_the_dispatch_attempt(self) -> None:
        trace = self.selected_trace()
        receipt = trace.pop(1)
        trace.insert(0, receipt)

        self.assertTrue(any("routing receipt" in error for error in validate_search_dispatch_trace(trace)))

    def test_terminal_receipt_must_precede_evidence_consumption(self) -> None:
        trace = self.selected_trace()
        terminal = trace.pop(4)
        trace.insert(6, terminal)

        self.assertTrue(any("precede search evidence" in error for error in validate_search_dispatch_trace(trace)))

    def test_completed_search_rejects_unbound_or_duplicate_evidence_consumption(self) -> None:
        unbound = self.selected_trace()
        unbound.append(
            {
                "event": "search-evidence-consumed",
                "actor": "root",
                "search_agent": "openbuild_search_separate",
                "run_dir": "C:/runs/unknown-search",
            }
        )
        self.assertTrue(
            any("exactly one run-bound" in error for error in validate_search_dispatch_trace(unbound))
        )

        duplicate = self.selected_trace()
        duplicate.append(dict(duplicate[-1]))
        self.assertTrue(
            any("exactly one run-bound" in error for error in validate_search_dispatch_trace(duplicate))
        )

    def test_failed_turn_completed_requires_independent_failure_evidence(self) -> None:
        for exit_evidence, exit_code, result_evidence in [
            ("valid", 7, "valid"),
            ("missing", "unknown", "valid"),
            ("malformed", "unknown", "valid"),
            ("identity-mismatch", "unknown", "valid"),
            ("valid", 0, "missing"),
        ]:
            with self.subTest(
                exit_evidence=exit_evidence,
                exit_code=exit_code,
                result_evidence=result_evidence,
            ):
                trace = self.failed_trace("runner-failed")
                trace[1].update(
                    {
                        "dispatch_method": "codex-exec-explicit-model",
                        "sandbox": "read-only",
                        "terminal_event": "turn.completed",
                        "codex_exit_evidence": exit_evidence,
                        "codex_exit_code": exit_code,
                        "result_evidence": result_evidence,
                    }
                )
                self.assertEqual(validate_search_dispatch_trace(trace), [])

        invalid = self.failed_trace("runner-failed")
        invalid[1].update(
            {
                "dispatch_method": "codex-exec-explicit-model",
                "sandbox": "read-only",
                "terminal_event": "turn.completed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
            }
        )

        self.assertTrue(any("independent" in error for error in validate_search_dispatch_trace(invalid)))

    def test_failed_search_evidence_is_never_consumed(self) -> None:
        trace = self.selected_trace()
        trace[4].update(
            {
                "run_status": "failed",
                "terminal_event": "turn.failed",
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 1,
                "result_evidence": "missing",
            }
        )

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("cannot be consumed" in error for error in errors))

        trace[-1]["run_dir"] = "C:/runs/different-search"
        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("cannot be consumed" in error for error in errors))

    def test_nonvalid_exit_evidence_cannot_carry_an_exit_code(self) -> None:
        trace = self.failed_trace("runner-failed")
        trace[1].update(
            {
                "dispatch_method": "codex-exec-explicit-model",
                "sandbox": "read-only",
                "terminal_event": "turn.failed",
                "codex_exit_evidence": "identity-mismatch",
                "codex_exit_code": 0,
                "result_evidence": "missing",
            }
        )

        errors = validate_search_dispatch_trace(trace)
        self.assertTrue(any("cannot carry" in error for error in errors))


class ProfileMigrationTraceTests(unittest.TestCase):
    @staticmethod
    def preview(action: str = "create-if-absent") -> dict[str, object]:
        target_sha256 = {
            "create-if-absent": "absent",
            "already-migrated": "b" * 64,
            "config-conflict": "c" * 64,
        }[action]
        entry: dict[str, object] = {
            "scope": "user",
            "source_path": "openbuild-implementation-fast.toml",
            "target_path": "openbuild_implementation_fast.toml",
            "root_fingerprint": "d" * 64,
            "legacy_name": "openbuild-implementation-fast",
            "target_name": "openbuild_implementation_fast",
            "source_sha256": "a" * 64,
            "target_sha256": target_sha256,
            "rendered_sha256": "b" * 64,
            "exact_diff": (
                '-name = "openbuild-implementation-fast"\n'
                '+name = "openbuild_implementation_fast"'
            ),
            "action": action,
        }
        entry["entry_id"] = migration_entry_id(entry)
        detected = ["openbuild-implementation-fast"]
        preview: dict[str, object] = {
            "event": "profile-migration-preview",
            "supported_mappings": migration_supported_mappings(),
            "detected_legacy_names": detected,
            "entries": [entry],
        }
        preview["plan_id"] = migration_plan_id([entry], detected)
        return preview

    @staticmethod
    def approval(preview: dict[str, object]) -> dict[str, object]:
        entry = preview["entries"][0]
        return {
            "event": "profile-migration-approval",
            "plan_id": preview["plan_id"],
            "entries": [
                {
                    "entry_id": entry["entry_id"],
                    "source_sha256": entry["source_sha256"],
                    "target_sha256": entry["target_sha256"],
                    "rendered_sha256": entry["rendered_sha256"],
                    "action": entry["action"],
                }
            ],
        }

    @staticmethod
    def receipt(preview: dict[str, object], status: str) -> dict[str, object]:
        entry = preview["entries"][0]
        result_sha256 = {
            "created": entry["rendered_sha256"],
            "already-migrated": entry["rendered_sha256"],
            "config-conflict": entry["target_sha256"],
            "hash-drift": "not-written",
        }[status]
        return {
            "event": "profile-migration-receipt",
            "plan_id": preview["plan_id"],
            "entry_id": entry["entry_id"],
            "status": status,
            "observed_source_sha256": entry["source_sha256"],
            "observed_target_sha256": entry["target_sha256"],
            "result_sha256": result_sha256,
        }

    def test_approved_create_has_a_resumable_receipt(self) -> None:
        preview = self.preview()
        trace = [preview, self.approval(preview), self.receipt(preview, "created")]

        self.assertEqual(validate_profile_migration_trace(trace), [])

    def test_create_without_per_entry_authority_is_rejected(self) -> None:
        preview = self.preview()
        trace = [preview, self.receipt(preview, "created")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("without per-entry authority" in error for error in errors))

    def test_create_before_matching_authority_is_rejected(self) -> None:
        preview = self.preview()
        trace = [preview, self.receipt(preview, "created"), self.approval(preview)]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("before per-entry authority" in error for error in errors))

    def test_authority_before_displayed_preview_is_rejected(self) -> None:
        preview = self.preview()
        trace = [self.approval(preview), preview, self.receipt(preview, "created")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("authority must follow the displayed preview" in error for error in errors))

    def test_config_conflict_cannot_be_written(self) -> None:
        preview = self.preview(action="config-conflict")
        trace = [preview, self.approval(preview), self.receipt(preview, "created")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("overwrote a divergent target" in error for error in errors))

    def test_create_action_cannot_report_already_migrated(self) -> None:
        preview = self.preview()
        trace = [preview, self.receipt(preview, "already-migrated")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("create-if-absent receipt contradicts preview" in error for error in errors))

    def test_action_must_match_the_target_precondition(self) -> None:
        preview = self.preview(action="already-migrated")
        entry = preview["entries"][0]
        entry["target_sha256"] = "absent"
        entry["entry_id"] = migration_entry_id(entry)
        preview["plan_id"] = migration_plan_id(
            [entry], preview["detected_legacy_names"]
        )
        trace = [preview, self.receipt(preview, "already-migrated")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("requires the rendered hash" in error for error in errors))

    def test_preview_inventory_must_cover_every_detected_profile(self) -> None:
        preview = self.preview()
        preview["detected_legacy_names"] = [
            "openbuild-search-fallback",
            "openbuild-review-fast",
        ]
        preview["plan_id"] = migration_plan_id(
            preview["entries"], preview["detected_legacy_names"]
        )
        trace = [preview, self.approval(preview), self.receipt(preview, "created")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("detected legacy inventory" in error for error in errors))

    def test_plan_id_must_bind_the_canonical_preview(self) -> None:
        preview = self.preview()
        preview["plan_id"] = "0" * 64
        trace = [preview, self.approval(preview), self.receipt(preview, "created")]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("canonical preview SHA-256" in error for error in errors))

    def test_approval_must_bind_exact_precondition_hashes(self) -> None:
        preview = self.preview()
        stale_approval = self.approval(preview)
        stale_approval["entries"][0]["source_sha256"] = "e" * 64
        trace = [
            preview,
            stale_approval,
            self.receipt(preview, "created"),
        ]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("exact precondition hashes" in error for error in errors))

    def test_receipt_must_record_precondition_recheck_and_result_hash(self) -> None:
        preview = self.preview()
        trace = [
            preview,
            self.approval(preview),
            {
                "event": "profile-migration-receipt",
                "plan_id": preview["plan_id"],
                "entry_id": preview["entries"][0]["entry_id"],
                "status": "created",
            },
        ]

        errors = validate_profile_migration_trace(trace)
        self.assertTrue(any("observed precondition hashes" in error for error in errors))
        self.assertTrue(any("result hash" in error for error in errors))

    def test_hash_drift_receipt_preserves_unchanged_authority_without_writing(self) -> None:
        preview = self.preview()
        receipt = self.receipt(preview, "hash-drift")
        receipt["observed_target_sha256"] = "e" * 64
        trace = [preview, self.approval(preview), receipt]

        self.assertEqual(validate_profile_migration_trace(trace), [])


class ImplementationDispatchTraceTests(unittest.TestCase):
    @staticmethod
    def valid_trace(
        *,
        risk: str = "high",
        tier: str = "balanced",
        agent: str = "openbuild_implementation_balanced",
        task_name: str = "fixture_task",
        lease: str = "M1",
    ) -> list[dict[str, str]]:
        base_receipt = {
            "event": "implementation-routing-receipt",
            "risk": risk,
            "requested_agent": agent,
            "task_name": task_name,
            "requested_tier": tier,
            "dispatch_method": "codex-exec-explicit-model",
            "configured_model": f"{tier}-code-model",
            "model_reasoning_effort": "high",
            "observed_agent": agent,
            "observed_model": "unknown",
            "sandbox": "workspace-write",
            "lease": lease,
            "dispatch_result": "selected",
            "fallback_reason": "none",
            "run_dir": "C:/runs/M1",
            "worker_pid": "111",
            "worker_process_identity": "worker-created-1",
            "codex_pid": "222",
            "codex_process_identity": "codex-created-1",
            "process_tree_stopped": False,
        }
        return [
            {
                "event": "writer-lease-acquired",
                "lease": lease,
                "owner": agent,
            },
            {
                "event": "implementation-dispatch",
                "risk": risk,
                "agent_name": agent,
                "task_name": task_name,
                "lease": lease,
                "result": "selected",
                "fallback_reason": "none",
            },
            base_receipt
            | {"run_status": "running", "terminal_event": "none", "activated": False},
            {
                "event": "implementation-agent-activated",
                "lease": lease,
                "agent_name": agent,
                "task_name": task_name,
                "run_dir": "C:/runs/M1",
                "worker_process_identity": "worker-created-1",
                "codex_process_identity": "codex-created-1",
                "activated": True,
            },
            {"event": "code-write", "actor": agent},
            base_receipt
            | {
                "run_status": "completed",
                "terminal_event": "turn.completed",
                "process_tree_stopped": True,
                "activated": True,
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
            },
            {
                "event": "implementation-handoff-accepted",
                "lease": lease,
                "agent_name": agent,
                "task_name": task_name,
                "run_dir": "C:/runs/M1",
                "worker_process_identity": "worker-created-1",
                "codex_process_identity": "codex-created-1",
                "result_evidence": "valid",
            },
            {"event": "writer-lease-released", "lease": lease},
        ]

    @classmethod
    def escalated_trace(
        cls,
        *,
        risk: str = "high",
        from_tier: str = "balanced",
        from_agent: str = "openbuild_implementation_balanced",
        to_tier: str = "strong",
        to_agent: str = "openbuild_implementation_strong",
        reason: str = "task-complexity-above-tier",
    ) -> list[dict[str, object]]:
        running: dict[str, object] = {
            "event": "implementation-routing-receipt",
            "risk": risk,
            "requested_agent": from_agent,
            "task_name": "capability_probe",
            "requested_tier": from_tier,
            "dispatch_method": "codex-exec-explicit-model",
            "configured_model": "gpt-5.6-terra",
            "model_reasoning_effort": "medium",
            "observed_agent": "unknown",
            "observed_model": "unknown",
            "sandbox": "workspace-write",
            "lease": "M0",
            "dispatch_result": "selected",
            "fallback_reason": "none",
            "run_dir": "C:/runs/M0",
            "worker_pid": "101",
            "worker_process_identity": "worker-created-0",
            "codex_pid": "202",
            "codex_process_identity": "codex-created-0",
            "process_tree_stopped": False,
            "run_status": "running",
            "terminal_event": "none",
            "activated": False,
        }
        return [
            {"event": "writer-lease-acquired", "lease": "M0", "owner": from_agent},
            {
                "event": "implementation-dispatch",
                "risk": risk,
                "tier": from_tier,
                "agent_name": from_agent,
                "task_name": "capability_probe",
                "lease": "M0",
                "result": "selected",
                "fallback_reason": "none",
            },
            running,
            {
                "event": "implementation-agent-activated",
                "lease": "M0",
                "agent_name": from_agent,
                "task_name": "capability_probe",
                "run_dir": "C:/runs/M0",
                "worker_process_identity": "worker-created-0",
                "codex_process_identity": "codex-created-0",
                "activated": True,
            },
            running
            | {
                "observed_agent": from_agent,
                "observed_model": "gpt-5.6-terra",
                "process_tree_stopped": True,
                "run_status": "completed",
                "terminal_event": "turn.completed",
                "activated": True,
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
            },
            {
                "event": "implementation-result",
                "outcome": "needs-escalation",
                "reason": reason,
                "risk": risk,
                "tier": from_tier,
                "agent_name": from_agent,
                "lease": "M0",
                "run_dir": "C:/runs/M0",
            },
            {
                "event": "semantic-handoff-rejected",
                "actor": "root",
                "disposition": "needs-escalation",
                "lease": "M0",
                "run_dir": "C:/runs/M0",
                "evidence_digest": "a" * 64,
                "handoff_created": False,
                "success": False,
                "replayed": False,
            },
            {
                "event": "source-checkpoint-invalidated",
                "actor": "root",
                "lease": "M0",
                "run_dir": "C:/runs/M0",
                "source_state_id": "b" * 64,
                "disposition": "recovery-ineligible",
                "reason": "semantic-needs-escalation",
                "evidence_digest": "a" * 64,
            },
            {
                "event": "guardian-close-acknowledged",
                "lease": "M0",
                "run_dir": "C:/runs/M0",
                "closed": True,
                "process_tree_stopped": True,
            },
            {"event": "writer-lease-released", "lease": "M0"},
            {
                "event": "implementation-escalation-approved",
                "actor": "root",
                "risk": risk,
                "from_tier": from_tier,
                "to_tier": to_tier,
                "reason": reason,
                "lease": "M0",
                "run_dir": "C:/runs/M0",
                "verified_no_writes": True,
                "process_tree_stopped": True,
                "result_evidence": "valid",
            },
            *cls.valid_trace(
                risk=risk,
                tier=to_tier,
                agent=to_agent,
                task_name="implement_after_escalation",
                lease="M1",
            ),
        ]

    @classmethod
    def blocked_trace(cls) -> list[dict[str, object]]:
        trace: list[dict[str, object]] = list(cls.valid_trace())
        trace[6:7] = [
            {
                "event": "implementation-result",
                "outcome": "blocked",
                "reason": "route-blocker",
                "risk": "high",
                "tier": "balanced",
                "agent_name": "openbuild_implementation_balanced",
                "lease": "M1",
                "run_dir": "C:/runs/M1",
            },
            {
                "event": "semantic-handoff-rejected",
                "actor": "root",
                "disposition": "blocked",
                "lease": "M1",
                "run_dir": "C:/runs/M1",
                "evidence_digest": "c" * 64,
                "handoff_created": False,
                "success": False,
                "replayed": False,
            },
            {
                "event": "guardian-close-acknowledged",
                "lease": "M1",
                "run_dir": "C:/runs/M1",
                "closed": True,
                "process_tree_stopped": True,
            },
        ]
        return trace

    def test_canonical_writer_agent_name_is_separate_from_task_name(self) -> None:
        self.assertEqual(
            validate_implementation_dispatch_trace(
                self.valid_trace(task_name="implement_m3", lease="M3")
            ),
            [],
        )

    def test_low_risk_exact_fast_writer_owns_first_edit(self) -> None:
        trace = self.valid_trace(
            risk="low",
            tier="fast",
            agent="openbuild_implementation_fast",
        )
        trace[4]["event"] = "test-write"
        self.assertEqual(validate_implementation_dispatch_trace(trace), [])

    def test_medium_risk_cannot_silently_jump_to_strongest_writer(self) -> None:
        trace = self.valid_trace(
            risk="medium",
            tier="strongest",
            agent="openbuild_implementation_strongest",
        )
        self.assertTrue(
            any(
                "openbuild_implementation_balanced" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_running_receipt_must_precede_edit_and_be_write_capable(self) -> None:
        trace = self.valid_trace()
        trace[2]["sandbox"] = "read-only"
        self.assertTrue(
            any("workspace-write" in error for error in validate_implementation_dispatch_trace(trace))
        )

    def test_native_writer_is_rejected(self) -> None:
        trace = self.valid_trace()
        for receipt in (trace[2], trace[5]):
            receipt["dispatch_method"] = "per-spawn-model"

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("exact dispatch method" in error for error in errors))

    def test_high_risk_starts_with_balanced_writer(self) -> None:
        self.assertEqual(validate_implementation_dispatch_trace(self.valid_trace()), [])

    def test_critical_risk_starts_with_strongest_writer(self) -> None:
        trace = self.valid_trace(
            risk="critical",
            tier="strongest",
            agent="openbuild_implementation_strongest",
        )

        self.assertEqual(validate_implementation_dispatch_trace(trace), [])

    def test_semantic_needs_escalation_allows_exact_next_writer_before_edit(self) -> None:
        self.assertEqual(
            validate_implementation_dispatch_trace(self.escalated_trace()),
            [],
        )

    def test_edited_blocked_result_requires_durable_semantic_rejection(self) -> None:
        trace = self.blocked_trace()
        self.assertEqual(validate_implementation_dispatch_trace(trace), [])

        missing = [
            event for event in trace if event.get("event") != "semantic-handoff-rejected"
        ]
        self.assertTrue(
            any(
                "semantic rejection" in error
                for error in validate_implementation_dispatch_trace(missing)
            )
        )

        replayed = list(trace)
        rejection = next(
            event for event in trace if event.get("event") == "semantic-handoff-rejected"
        )
        replayed.insert(8, dict(rejection))
        self.assertTrue(
            any(
                "exactly one semantic rejection" in error
                for error in validate_implementation_dispatch_trace(replayed)
            )
        )

    def test_edited_blocked_result_rejects_a_replayed_terminal_receipt(self) -> None:
        trace = self.blocked_trace()
        trace.insert(6, dict(trace[5]))

        self.assertTrue(
            any(
                "exactly one terminal routing receipt" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_edited_blocked_result_rejects_a_replayed_lease_release(self) -> None:
        trace = self.blocked_trace()
        trace.append(dict(trace[-1]))

        self.assertTrue(
            any(
                "exactly one writer lease release" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_escalation_requires_rejection_and_checkpoint_invalidation(self) -> None:
        trace = self.escalated_trace()
        without_rejection = [
            event for event in trace if event.get("event") != "semantic-handoff-rejected"
        ]
        self.assertTrue(
            any(
                "semantic-handoff-rejected" in error
                for error in validate_implementation_dispatch_trace(without_rejection)
            )
        )

        without_invalidation = [
            event for event in trace if event.get("event") != "source-checkpoint-invalidated"
        ]
        self.assertTrue(
            any(
                "source-checkpoint-invalidated" in error
                for error in validate_implementation_dispatch_trace(without_invalidation)
            )
        )

    def test_infrastructure_failure_never_authorizes_writer_escalation(self) -> None:
        trace = self.escalated_trace()
        trace[4].update(
            {
                "run_status": "failed",
                "terminal_event": "turn.failed",
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
                "codex_exit_code": 1,
                "result_evidence": "missing",
            }
        )

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("infrastructure" in error for error in errors))

    def test_writer_escalation_cannot_skip_a_tier(self) -> None:
        trace = self.escalated_trace(
            to_tier="strongest",
            to_agent="openbuild_implementation_strongest",
        )

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("one tier" in error for error in errors))

    def test_writer_escalation_is_forbidden_after_any_edit(self) -> None:
        trace = self.escalated_trace()
        trace.insert(4, {"event": "code-write", "actor": "openbuild_implementation_balanced"})

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("before any edit" in error for error in errors))

    def test_writer_escalation_cannot_change_the_milestone_risk(self) -> None:
        trace = self.escalated_trace()
        for event in trace[8:]:
            if "risk" in event:
                event["risk"] = "critical"

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("cannot change the milestone risk" in error for error in errors))

    def test_failed_writer_cannot_be_replaced_before_edit(self) -> None:
        trace = self.valid_trace()
        failed_receipt = dict(trace[2])
        failed_receipt.update(
            {
                "lease": "M0",
                "task_name": "failed_fixture",
                "run_dir": "C:/runs/M0",
                "run_status": "failed",
                "terminal_event": "turn.failed",
                "activated": True,
                "process_tree_stopped": True,
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
                "codex_exit_evidence": "valid",
                "codex_exit_code": 1,
                "result_evidence": "missing",
            }
        )
        trace[0:0] = [
            {
                "event": "writer-lease-acquired",
                "lease": "M0",
                "owner": "openbuild_implementation_balanced",
            },
            {
                "event": "implementation-dispatch",
                "risk": "high",
                "agent_name": "openbuild_implementation_balanced",
                "task_name": "failed_fixture",
                "lease": "M0",
                "result": "selected",
                "fallback_reason": "none",
            },
            failed_receipt,
            {"event": "writer-lease-released", "lease": "M0"},
        ]

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("blocks replacement dispatch and edits" in error for error in errors))

    def test_running_receipt_must_be_recorded_before_activation(self) -> None:
        trace = self.valid_trace()
        trace[2]["activated"] = True
        self.assertTrue(
            any(
                "before activation" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_terminal_receipt_must_confirm_activation(self) -> None:
        trace = self.valid_trace()
        trace[5]["activated"] = False
        self.assertTrue(
            any(
                "confirm activation" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_activation_event_must_precede_first_edit(self) -> None:
        trace = self.valid_trace()
        activation = trace.pop(3)
        trace.insert(5, activation)
        self.assertTrue(
            any(
                "activation event" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_activation_event_cannot_drift_to_another_process(self) -> None:
        trace = self.valid_trace()
        trace[3]["codex_process_identity"] = "different-codex"
        self.assertTrue(
            any(
                "codex_process_identity" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_terminal_receipt_and_release_must_follow_writer_edits(self) -> None:
        trace = self.valid_trace()
        terminal = trace.pop(5)
        trace.insert(4, terminal)
        self.assertTrue(
            any(
                "terminal routing receipt" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_every_write_and_terminal_field_stay_bound_to_the_lease(self) -> None:
        trace = self.valid_trace()
        trace.insert(5, {"event": "code-write", "actor": "root"})
        trace[6]["configured_model"] = "different-model"
        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("every code edit" in error for error in errors))
        self.assertTrue(any("configured_model" in error for error in errors))

    def test_lease_cannot_release_before_terminal_receipt(self) -> None:
        trace = self.valid_trace()
        trace.insert(4, {"event": "writer-lease-released", "lease": "M1"})
        self.assertTrue(
            any(
                "released before terminal" in error
                for error in validate_implementation_dispatch_trace(trace)
            )
        )

    def test_failed_writer_can_release_matching_lease_but_not_handoff(self) -> None:
        trace = self.valid_trace()
        trace.pop(6)
        terminal = trace[5]
        terminal.update(
            {
                "run_status": "failed",
                "terminal_event": "turn.failed",
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
                "process_tree_stopped": True,
                "codex_exit_code": 1,
                "result_evidence": "missing",
            }
        )
        self.assertEqual(validate_implementation_dispatch_trace(trace), [])

    def test_failed_writer_cannot_authorize_an_accepted_handoff(self) -> None:
        trace = self.valid_trace()
        trace[6]["lease"] = "wrong-lease"
        terminal = trace[5]
        terminal.update(
            {
                "run_status": "failed",
                "terminal_event": "turn.failed",
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
                "codex_exit_code": 1,
                "result_evidence": "missing",
            }
        )

        errors = validate_implementation_dispatch_trace(trace)
        self.assertTrue(any("cannot be accepted" in error for error in errors))

    def test_accepted_handoff_before_dispatch_is_never_ignored(self) -> None:
        completed = self.valid_trace()
        completed.insert(0, dict(completed[6]))
        self.assertTrue(
            any("accepted handoff" in error for error in validate_implementation_dispatch_trace(completed))
        )

        failed = self.valid_trace()
        early_handoff = failed.pop(6)
        failed.insert(0, early_handoff)
        failed[6].update(
            {
                "run_status": "failed",
                "terminal_event": "turn.failed",
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
                "codex_exit_code": 1,
                "result_evidence": "missing",
            }
        )
        self.assertTrue(
            any("cannot be accepted" in error for error in validate_implementation_dispatch_trace(failed))
        )

    def test_completed_writer_requires_run_bound_handoff_after_terminal_evidence(self) -> None:
        missing = self.valid_trace()
        missing.pop(6)
        self.assertTrue(
            any(
                "accepted handoff" in error
                for error in validate_implementation_dispatch_trace(missing)
            )
        )

        drifted = self.valid_trace()
        drifted[6]["codex_process_identity"] = "different-codex"
        self.assertTrue(
            any(
                "codex_process_identity" in error
                for error in validate_implementation_dispatch_trace(drifted)
            )
        )

    def test_failed_completed_writer_can_release_with_independent_failure_evidence(self) -> None:
        for exit_evidence, exit_code, result_evidence in [
            ("valid", 7, "valid"),
            ("missing", "unknown", "valid"),
            ("malformed", "unknown", "valid"),
            ("identity-mismatch", "unknown", "valid"),
            ("valid", 0, "invalid"),
        ]:
            with self.subTest(exit_evidence=exit_evidence, result_evidence=result_evidence):
                trace = self.valid_trace()
                trace.pop(6)
                terminal = trace[5]
                terminal.update(
                    {
                        "run_status": "failed",
                        "terminal_event": "turn.completed",
                        "dispatch_result": "failed",
                        "fallback_reason": "runner-failed",
                        "process_tree_stopped": True,
                        "codex_exit_evidence": exit_evidence,
                        "codex_exit_code": exit_code,
                        "result_evidence": result_evidence,
                    }
                )
                self.assertEqual(validate_implementation_dispatch_trace(trace), [])

        invalid = self.valid_trace()
        invalid.pop(6)
        invalid[5].update(
            {
                "run_status": "failed",
                "dispatch_result": "failed",
                "fallback_reason": "runner-failed",
            }
        )
        self.assertTrue(
            any(
                "independent exit/result" in error
                for error in validate_implementation_dispatch_trace(invalid)
            )
        )


class ReviewEscalationTraceTests(unittest.TestCase):
    def test_risk_specific_review_ceiling_is_explicit(self) -> None:
        self.assertEqual(
            REVIEW_MAX_TIER_BY_RISK,
            {
                "low": "sol_high",
                "medium": "sol_high",
                "high": "sol_high",
                "critical": "strongest",
            },
        )

    @staticmethod
    def review_cycle(
        tier: str,
        agent: str,
        revision: str,
        *,
        verdict: str,
        findings: str,
        escalation_reason: str,
        risk: str = "low",
        risk_floor: str = "fast",
    ) -> list[dict[str, object]]:
        running: dict[str, object] = {
            "event": "review-routing-receipt",
            "diff_revision": revision,
            "risk_floor": risk_floor,
            "requested_agent": agent,
            "task_name": "fixture_task",
            "requested_tier": tier,
            "dispatch_method": "codex-exec-explicit-model",
            "configured_model": f"{tier}-review-model",
            "model_reasoning_effort": "high",
            "observed_agent": "unknown",
            "observed_model": "unknown",
            "terminal_event": "none",
            "activated": False,
            "run_status": "running",
            "sandbox": "read-only",
            "dispatch_result": "selected",
            "fallback_reason": "none",
            "process_tree_stopped": False,
            "run_dir": f"C:/runs/review-{revision}-{tier}",
            "worker_pid": "311",
            "worker_process_identity": f"worker-{revision}-{tier}",
            "codex_pid": "322",
            "codex_process_identity": f"codex-{revision}-{tier}",
            "codex_exit_evidence": "missing",
            "codex_exit_code": None,
            "result_evidence": "missing",
        }
        return [
            {
                "event": "review-dispatch",
                "risk": risk,
                "tier": tier,
                "agent_name": agent,
                "task_name": "fixture_task",
                "diff_revision": revision,
                "result": "selected",
            },
            running,
            {
                "event": "review-agent-activated",
                "diff_revision": revision,
                "requested_agent": agent,
                "task_name": "fixture_task",
                "run_dir": f"C:/runs/review-{revision}-{tier}",
                "worker_process_identity": f"worker-{revision}-{tier}",
                "codex_process_identity": f"codex-{revision}-{tier}",
                "activated": True,
            },
            running
            | {
                "observed_agent": agent,
                "observed_model": f"{tier}-review-model",
                "terminal_event": "turn.completed",
                "activated": True,
                "run_status": "completed",
                "process_tree_stopped": True,
                "codex_exit_evidence": "valid",
                "codex_exit_code": 0,
                "result_evidence": "valid",
            },
            {
                "event": "review-result",
                "diff_revision": revision,
                "tier": tier,
                "verdict": verdict,
                "confidence": "high",
                "coverage": "complete",
                "actionable_findings": findings,
                "escalation_reason": escalation_reason,
                "concrete_evidence": "E-1" if escalation_reason != "none" else "none",
            },
        ]

    def test_low_risk_escalates_one_tier_after_root_remediation(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="REVISE",
            findings="F-1",
            escalation_reason="unresolved-high-impact-finding",
        )
        trace.extend(
            [
                {"event": "root-remediation"},
                {"event": "validation", "result": "green"},
            ]
        )
        trace.extend(
            self.review_cycle(
                "luna_xhigh",
                "openbuild_review_luna_xhigh",
                "D2",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
            )
        )

        self.assertEqual(validate_review_escalation_trace(trace), [])

    def test_review_ladder_cannot_skip_a_proven_intermediate_tier(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="REVISE",
            findings="none",
            escalation_reason="low-confidence",
        )
        trace.extend(
            self.review_cycle(
                "strong",
                "openbuild_review_strong",
                "D1",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
            )
        )

        self.assertTrue(any("cannot skip" in error for error in validate_review_escalation_trace(trace)))

    def test_unknown_reviewer_tier_is_rejected_without_crashing_the_trace(self) -> None:
        trace = self.review_cycle(
            "economy",
            "generic-reviewer",
            "D1",
            verdict="REVISE",
            findings="none",
            escalation_reason="low-confidence",
        )
        trace.extend(
            self.review_cycle(
                "balanced",
                "openbuild_review_balanced",
                "D1",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
            )
        )

        self.assertTrue(any("exact agent" in error for error in validate_review_escalation_trace(trace)))

    def test_stronger_reviewer_requires_a_concrete_trigger(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace.extend(
            self.review_cycle(
                "balanced",
                "openbuild_review_balanced",
                "D1",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
            )
        )

        self.assertTrue(any("concrete escalation trigger" in error for error in validate_review_escalation_trace(trace)))

    def test_score_alone_cannot_escalate_a_reviewer(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ESCALATE",
            findings="none",
            escalation_reason="low-confidence",
        )
        trace[4]["concrete_evidence"] = "none"
        trace.extend(
            self.review_cycle(
                "luna_xhigh",
                "openbuild_review_luna_xhigh",
                "D1",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
            )
        )

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("not score alone" in error for error in errors))

    def test_non_accepting_final_result_cannot_close_the_ladder(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="REVISE",
            findings="none",
            escalation_reason="none",
        )

        self.assertTrue(any("requires the next reviewer tier" in error for error in validate_review_escalation_trace(trace)))

    def test_high_risk_starts_with_balanced_read_only_reviewer(self) -> None:
        trace = self.review_cycle(
            "balanced",
            "openbuild_review_balanced",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
            risk="high",
            risk_floor="balanced",
        )

        self.assertEqual(validate_review_escalation_trace(trace), [])

    def test_critical_risk_starts_with_strongest_read_only_reviewer(self) -> None:
        trace = self.review_cycle(
            "strongest",
            "openbuild_review_strongest",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
            risk="critical",
            risk_floor="strongest",
        )

        self.assertEqual(validate_review_escalation_trace(trace), [])

    def test_high_risk_escalates_from_terra_to_sol_only_after_a_finding(self) -> None:
        trace = self.review_cycle(
            "balanced",
            "openbuild_review_balanced",
            "D1",
            verdict="REVISE",
            findings="F-1",
            escalation_reason="unresolved-high-impact-finding",
            risk="high",
            risk_floor="balanced",
        )
        trace.extend(
            [
                {"event": "root-remediation"},
                {"event": "validation", "result": "green"},
            ]
        )
        trace.extend(
            self.review_cycle(
                "strong",
                "openbuild_review_strong",
                "D2",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
                risk="high",
                risk_floor="balanced",
            )
        )

        self.assertEqual(validate_review_escalation_trace(trace), [])

    def test_high_risk_review_cannot_advance_from_sol_high_to_critical_strongest(self) -> None:
        tiers = [
            ("balanced", "openbuild_review_balanced"),
            ("strong", "openbuild_review_strong"),
            ("sol_high", "openbuild_review_sol_high"),
            ("strongest", "openbuild_review_strongest"),
        ]
        trace: list[dict[str, object]] = []
        for index, (tier, agent) in enumerate(tiers):
            trace.extend(
                self.review_cycle(
                    tier,
                    agent,
                    f"D{index + 1}",
                    verdict="ACCEPT" if tier == "strongest" else "REVISE",
                    findings="none" if tier == "strongest" else f"F-{index + 1}",
                    escalation_reason=(
                        "none" if tier == "strongest" else "unresolved-high-impact-finding"
                    ),
                    risk="high",
                    risk_floor="balanced",
                )
            )
            if tier != "strongest":
                trace.extend(
                    [
                        {"event": "root-remediation"},
                        {"event": "validation", "result": "green"},
                    ]
                )

        self.assertTrue(
            any(
                "critical-only" in error
                for error in validate_review_escalation_trace(trace)
            )
        )

    def test_unresolved_terminal_sol_high_is_route_exhausted_not_escalatable(self) -> None:
        tiers = [
            ("balanced", "openbuild_review_balanced"),
            ("strong", "openbuild_review_strong"),
            ("sol_high", "openbuild_review_sol_high"),
        ]
        trace: list[dict[str, object]] = []
        for index, (tier, agent) in enumerate(tiers):
            trace.extend(
                self.review_cycle(
                    tier,
                    agent,
                    f"D{index + 1}",
                    verdict="REVISE",
                    findings=f"F-{index + 1}",
                    escalation_reason="unresolved-high-impact-finding",
                    risk="high",
                    risk_floor="balanced",
                )
            )
            if tier != "sol_high":
                trace.extend(
                    [
                        {"event": "root-remediation"},
                        {"event": "validation", "result": "green"},
                    ]
                )

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("non-critical review route is exhausted" in error for error in errors))
        self.assertFalse(any("requires the next reviewer tier" in error for error in errors))

    def test_review_escalation_cannot_change_the_diff_risk(self) -> None:
        trace = self.review_cycle(
            "balanced",
            "openbuild_review_balanced",
            "D1",
            verdict="REVISE",
            findings="F-1",
            escalation_reason="unresolved-high-impact-finding",
            risk="high",
            risk_floor="balanced",
        )
        trace.extend(
            [
                {"event": "root-remediation"},
                {"event": "validation", "result": "green"},
            ]
        )
        trace.extend(
            self.review_cycle(
                "strong",
                "openbuild_review_strong",
                "D2",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
                risk="critical",
                risk_floor="strongest",
            )
        )

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("cannot change the diff risk" in error for error in errors))

    def test_review_requires_a_matching_activation_event(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace.pop(2)

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("activation event" in error for error in errors))

    def test_native_reviewer_is_rejected(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        for receipt in (trace[1], trace[3]):
            receipt["dispatch_method"] = "per-spawn-model"

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("exact dispatch method" in error for error in errors))

    def test_review_result_must_follow_the_terminal_receipt(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[3], trace[4] = trace[4], trace[3]

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("lifecycle" in error for error in errors))

    def test_review_terminal_requires_independent_exit_and_result_evidence(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[3]["codex_exit_code"] = 1

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("exit code zero" in error for error in errors))

    def test_review_terminal_rejects_a_string_exit_code(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[3]["codex_exit_code"] = "0"

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("integer Codex exit code" in error for error in errors))

    def test_review_terminal_cannot_change_process_identity(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[3]["codex_process_identity"] = "reused-process"

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("codex_process_identity" in error for error in errors))

    def test_review_running_receipt_cannot_claim_terminal_evidence(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild_review_fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[1]["codex_exit_evidence"] = "valid"
        trace[1]["codex_exit_code"] = 0
        trace[1]["result_evidence"] = "valid"

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("missing/unknown/missing" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
