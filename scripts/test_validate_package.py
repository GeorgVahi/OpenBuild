"""Contract tests for the OpenBuild package validator."""

from __future__ import annotations

import unittest

from validate_package import (
    BLINDSPOT_PROTOCOL,
    IMPLEMENTATION_DELEGATION,
    REVIEW_PROTOCOL,
    ROOT,
    SKILL,
    VERSION_SYNC_PATHS,
    commit_requires_version_bump,
    validate_auto_routing_contract,
    validate_blindspot_contract,
    validate_changelog_contract,
    validate_implementation_delegation_contract,
    validate_implementation_dispatch_trace,
    validate_release_docs_contract,
    validate_review_escalation_trace,
    validate_search_dispatch_trace,
    validate_usage_routing_contract,
)


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

    def test_blindspot_docs_explain_dedup_and_closure(self) -> None:
        readme = self.readme.replace("A resolved ID is a locked constraint", "A resolved ID is recorded")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))

        readme_ru = self.readme_ru.replace("Решённый ID становится зафиксированным ограничением", "Решённый ID записывается")
        self.assertTrue(any("README.ru.md" in error for error in self.validate(readme_ru=readme_ru)))

    def test_blindspot_contract_is_present_in_template_and_both_readmes(self) -> None:
        template = self.template_text.replace("Evidence or decision", "Evidence")
        self.assertTrue(any("coverage ledger" in error for error in self.validate(template_text=template)))

        readme = self.readme.replace("## How blind-spot critique works", "## Specification checks")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))

        readme_ru = self.readme_ru.replace("## Как работает критика blind spots", "## Проверка спецификации")
        self.assertTrue(any("README.ru.md" in error for error in self.validate(readme_ru=readme_ru)))


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

    def test_lifecycle_matrix_and_public_explanation_are_required(self) -> None:
        protocol = self.protocol_text.replace("| `In progress` |", "| `Active` |")
        self.assertTrue(any("lifecycle routing" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace("full acceptance set", "primary signal only")
        self.assertTrue(any("lifecycle routing" in error for error in self.validate(protocol_text=protocol)))

        readme = self.readme.replace("the first incomplete phase", "a suitable phase")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))


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
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_implementation_delegation_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("protocol_text", self.protocol_text),
            overrides.get("model_routing", self.model_routing),
            overrides.get("tdd_workflow", self.tdd_workflow),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
        )

    def test_adaptive_delegation_protocol_is_required_and_linked(self) -> None:
        self.assertTrue(IMPLEMENTATION_DELEGATION.is_file())
        self.assertEqual(self.validate(), [])

    def test_shared_workspace_allows_only_one_bounded_writer(self) -> None:
        mutated = self.protocol_text.replace("one active writer", "an active writer")
        self.assertTrue(any("single-writer" in error for error in self.validate(protocol_text=mutated)))

    def test_delegation_contract_is_present_in_model_tdd_and_docs(self) -> None:
        model_routing = self.model_routing.replace("Implementation worker", "Implementation helper")
        self.assertTrue(any("model-routing.md" in error for error in self.validate(model_routing=model_routing)))

        tdd_workflow = self.tdd_workflow.replace("bounded implementation worker", "implementation helper")
        self.assertTrue(any("tdd-workflow.md" in error for error in self.validate(tdd_workflow=tdd_workflow)))

        route = "Select the risk-matched root or bounded implementation worker"
        edit = "Under that lease, add or modify the test"
        tdd_workflow = self.tdd_workflow.replace(route, "__EDIT_ORDER__").replace(edit, route).replace("__EDIT_ORDER__", edit)
        self.assertTrue(any("must precede every test code edit" in error for error in self.validate(tdd_workflow=tdd_workflow)))

        readme = self.readme.replace(
            "## How adaptive implementation delegation works",
            "## Implementation delegation",
        )
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))

        readme_ru = self.readme_ru.replace(
            "## Как работает адаптивная делегация реализации",
            "## Делегация реализации",
        )
        self.assertTrue(any("README.ru.md" in error for error in self.validate(readme_ru=readme_ru)))

    def test_delegation_modes_root_handoff_and_docs_body_are_required(self) -> None:
        protocol = self.protocol_text.replace("`sequential-workers`", "`multiple-workers`")
        self.assertTrue(any("delegation modes" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace("Git exclusively root-owned", "Git controlled")
        self.assertTrue(any("root handoff" in error for error in self.validate(protocol_text=protocol)))

        readme = self.readme.replace("one active writer", "an active writer")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))


class ChangelogContractTests(unittest.TestCase):
    def test_development_manifest_version_and_latest_release_are_documented(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.4.0] - 2026-07-12", changelog)
        self.assertEqual(validate_changelog_contract(changelog, "1.0.4"), [])

        mutated = changelog.replace("## [1.0.4] - 2026-07-13", "## [next] - 2026-07-13")
        self.assertTrue(any("current manifest version" in error for error in validate_changelog_contract(mutated, "1.0.4")))

    def test_released_version_is_pinned_in_both_install_channels(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.assertEqual(validate_release_docs_contract(readme, readme_ru, "1.0.4"), [])

        mutated = readme.replace("--ref v1.0.4", "--ref main")
        self.assertTrue(any("README.md" in error for error in validate_release_docs_contract(mutated, readme_ru, "1.0.4")))


class UsageRoutingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.model_routing = (SKILL / "references" / "model-routing.md").read_text(encoding="utf-8")
        self.code_discovery = (SKILL / "references" / "code-discovery.md").read_text(encoding="utf-8")
        self.implementation = IMPLEMENTATION_DELEGATION.read_text(encoding="utf-8")
        self.review_protocol = REVIEW_PROTOCOL.read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_usage_routing_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("model_routing", self.model_routing),
            overrides.get("code_discovery", self.code_discovery),
            overrides.get("implementation", self.implementation),
            overrides.get("review_protocol", self.review_protocol),
            overrides.get("readme", self.readme),
            overrides.get("readme_ru", self.readme_ru),
        )

    def test_separate_usage_search_precedes_main_pool_fallback(self) -> None:
        self.assertEqual(self.validate(), [])

        model_routing = self.model_routing.replace("**Separate usage pool:**", "**Search worker:**")
        self.assertTrue(any("search usage-pool" in error for error in self.validate(model_routing=model_routing)))

        separate = "**Separate usage pool:**"
        efficient = "**Efficient main-pool fallback:**"
        model_routing = self.model_routing.replace(separate, "__SEARCH_ORDER__").replace(efficient, separate).replace("__SEARCH_ORDER__", efficient)
        self.assertTrue(any("separate pool must precede" in error for error in self.validate(model_routing=model_routing)))

    def test_search_preflight_precedes_repository_lookup(self) -> None:
        initialized = "## Initialize search routing"
        selection = "## Select the specification safely"
        skill_text = self.skill_text.replace(initialized, "__ROUTING_HEADING__").replace(selection, initialized).replace("__ROUTING_HEADING__", selection)
        self.assertTrue(any("must precede specification selection" in error for error in self.validate(skill_text=skill_text)))

    def test_exact_named_search_agent_dispatch_precedes_repository_search(self) -> None:
        skill_text = self.skill_text.replace(
            "Spawn the custom agent named `openbuild-search-separate`",
            "Attempt a suitable search worker",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(skill_text=skill_text)))

        model_routing = self.model_routing.replace(
            "select `openbuild-search-separate` by exact custom-agent name",
            "prefer `openbuild-search-separate` when convenient",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(model_routing=model_routing)))

        code_discovery = self.code_discovery.replace(
            "before the root runs any new repository search command",
            "early in repository discovery",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(code_discovery=code_discovery)))

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
        model_routing = self.model_routing.replace("open a circuit breaker", "fall back")
        self.assertTrue(any("search usage-pool" in error for error in self.validate(model_routing=model_routing)))

        discovery = self.code_discovery.replace("do not pay for repeated failed attempts", "retry later")
        self.assertTrue(any("code-discovery.md" in error for error in self.validate(code_discovery=discovery)))

    def test_code_edits_use_risk_matched_writer_tiers(self) -> None:
        implementation = self.implementation.replace(
            "risk-matched coding model for every complexity class",
            "suitable coding model",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        for profile in [
            "openbuild-implementation-fast",
            "openbuild-implementation-balanced",
            "openbuild-implementation-strongest",
        ]:
            model_routing = self.model_routing.replace(profile, "missing-writer-profile")
            self.assertTrue(any("implementation routing" in error for error in self.validate(model_routing=model_routing)))

    def test_exact_named_writer_dispatch_precedes_every_code_edit(self) -> None:
        implementation = self.implementation.replace(
            "Dispatch that exact profile before every test or production code edit",
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
            "Dispatch the exact starting reviewer",
            "Choose a suitable reviewer",
        )
        self.assertTrue(any("exact reviewer dispatch" in error for error in self.validate(model_routing=model_routing)))

        model_routing = self.model_routing.replace(
            "fast → balanced → strong → strongest",
            "fast → strongest",
        )
        self.assertTrue(any("sequential review ladder" in error for error in self.validate(model_routing=model_routing)))

        review_protocol = self.review_protocol.replace(
            "Review routing receipt",
            "Review routing summary",
        )
        self.assertTrue(any("review-protocol.md" in error for error in self.validate(review_protocol=review_protocol)))

    def test_writer_escalation_preserves_tdd_and_single_writer_controls(self) -> None:
        model_routing = self.model_routing.replace(
            "Escalate only on evidence",
            "Escalate whenever a stronger model exists",
        )
        self.assertTrue(any("implementation routing" in error for error in self.validate(model_routing=model_routing)))

        implementation = self.implementation.replace(
            "Missing model/tier metadata alone does not block low or medium implementation",
            "Missing model/tier metadata blocks implementation",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

    def test_high_and_critical_writer_floors_cannot_be_relaxed(self) -> None:
        model_routing = self.model_routing.replace(
            "High work still requires a confirmed strong route",
            "High work may use any configured route",
        )
        self.assertTrue(any("implementation routing" in error for error in self.validate(model_routing=model_routing)))

        model_routing = self.model_routing.replace(
            "critical work requires the strongest proven route",
            "critical work may use a merely configured route",
        )
        self.assertTrue(any("implementation routing" in error for error in self.validate(model_routing=model_routing)))

        implementation = self.implementation.replace(
            "For high work require a confirmed strong route",
            "For high work allow any configured route",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        implementation = self.implementation.replace(
            "for critical work require the strongest proven route",
            "for critical work allow a merely configured route",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

    def test_usage_routing_is_explained_in_both_readmes(self) -> None:
        readme = self.readme.replace("Search always attempts a confirmed separate-usage route first", "Search selects a suitable route")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))

        readme = self.readme.replace("exact custom agent `openbuild-search-separate`", "a suitable worker")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))

        readme_ru = self.readme_ru.replace("Поиск всегда сначала пытается использовать подтверждённый separate-usage route", "Поиск выбирает подходящий route")
        self.assertTrue(any("README.ru.md" in error for error in self.validate(readme_ru=readme_ru)))

        readme_ru = self.readme_ru.replace("exact custom agent `openbuild-search-separate`", "generic worker")
        self.assertTrue(any("README.ru.md" in error for error in self.validate(readme_ru=readme_ru)))


class SearchDispatchTraceTests(unittest.TestCase):
    def test_exact_named_agent_owns_first_search(self) -> None:
        trace = [
            {
                "event": "search-dispatch",
                "agent": "openbuild-search-separate",
                "result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "search-routing-receipt",
                "search_agent": "openbuild-search-separate",
                "dispatch_method": "exact-custom-agent",
                "configured_model": "separate-search-model",
                "observed_agent": "openbuild-search-separate",
                "observed_model": "unknown",
                "pool": "separate",
                "fallback_reason": "none",
            },
            {
                "event": "repository-search",
                "actor": "openbuild-search-separate",
            },
        ]

        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_root_or_generic_search_cannot_silently_skip_exact_dispatch(self) -> None:
        trace = [
            {
                "event": "repository-search",
                "actor": "root",
            },
        ]

        self.assertTrue(any("exact agent dispatch" in error for error in validate_search_dispatch_trace(trace)))

    def test_fallback_requires_an_observable_allowed_reason(self) -> None:
        trace = [
            {
                "event": "search-dispatch",
                "agent": "openbuild-search-separate",
                "result": "failed",
                "fallback_reason": "unknown-problem",
            },
            {
                "event": "search-routing-receipt",
                "search_agent": "openbuild-search-separate",
                "dispatch_method": "unavailable",
                "configured_model": "separate-search-model",
                "observed_agent": "unknown",
                "observed_model": "unknown",
                "pool": "unknown",
                "fallback_reason": "unknown-problem",
            },
            {
                "event": "repository-search",
                "actor": "openbuild-search-fallback",
            },
        ]

        self.assertTrue(any("allowed fallback reason" in error for error in validate_search_dispatch_trace(trace)))

    def test_allowed_fallback_and_receipt_remain_consistent(self) -> None:
        trace = [
            {
                "event": "search-dispatch",
                "agent": "openbuild-search-separate",
                "result": "failed",
                "fallback_reason": "selector-unavailable",
            },
            {
                "event": "search-routing-receipt",
                "search_agent": "openbuild-search-separate",
                "dispatch_method": "unavailable",
                "configured_model": "separate-search-model",
                "observed_agent": "unknown",
                "observed_model": "unknown",
                "pool": "unknown",
                "fallback_reason": "selector-unavailable",
            },
            {
                "event": "repository-search",
                "actor": "openbuild-search-fallback",
            },
        ]

        self.assertEqual(validate_search_dispatch_trace(trace), [])

    def test_receipt_must_follow_the_dispatch_attempt(self) -> None:
        trace = [
            {
                "event": "search-routing-receipt",
                "search_agent": "openbuild-search-separate",
                "dispatch_method": "exact-custom-agent",
                "configured_model": "separate-search-model",
                "observed_agent": "openbuild-search-separate",
                "observed_model": "unknown",
                "pool": "separate",
                "fallback_reason": "none",
            },
            {
                "event": "search-dispatch",
                "agent": "openbuild-search-separate",
                "result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "repository-search",
                "actor": "openbuild-search-separate",
            },
        ]

        self.assertTrue(any("must follow" in error for error in validate_search_dispatch_trace(trace)))


class ImplementationDispatchTraceTests(unittest.TestCase):
    def test_low_risk_exact_fast_writer_owns_first_edit(self) -> None:
        trace = [
            {
                "event": "implementation-dispatch",
                "risk": "low",
                "agent": "openbuild-implementation-fast",
                "result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "implementation-routing-receipt",
                "risk": "low",
                "requested_agent": "openbuild-implementation-fast",
                "requested_tier": "fast",
                "dispatch_method": "exact-custom-agent",
                "configured_model": "fast-code-model",
                "observed_agent": "openbuild-implementation-fast",
                "observed_model": "unknown",
                "sandbox": "workspace-write",
                "lease": "M1",
                "dispatch_result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "test-write",
                "actor": "openbuild-implementation-fast",
            },
        ]

        self.assertEqual(validate_implementation_dispatch_trace(trace), [])

    def test_medium_risk_cannot_silently_jump_to_generic_or_strongest_writer(self) -> None:
        trace = [
            {
                "event": "implementation-dispatch",
                "risk": "medium",
                "agent": "openbuild-implementation-strongest",
                "result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "implementation-routing-receipt",
                "risk": "medium",
                "requested_agent": "openbuild-implementation-strongest",
                "requested_tier": "strongest",
                "dispatch_method": "exact-custom-agent",
                "configured_model": "strong-code-model",
                "observed_agent": "openbuild-implementation-strongest",
                "observed_model": "unknown",
                "sandbox": "workspace-write",
                "lease": "M1",
                "dispatch_result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "code-write",
                "actor": "openbuild-implementation-strongest",
            },
        ]

        self.assertTrue(any("openbuild-implementation-balanced" in error for error in validate_implementation_dispatch_trace(trace)))

    def test_writer_receipt_must_precede_the_edit_and_be_write_capable(self) -> None:
        trace = [
            {
                "event": "implementation-dispatch",
                "risk": "high",
                "agent": "openbuild-implementation-strongest",
                "result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "implementation-routing-receipt",
                "risk": "high",
                "requested_agent": "openbuild-implementation-strongest",
                "requested_tier": "strongest",
                "dispatch_method": "exact-custom-agent",
                "configured_model": "strong-code-model",
                "observed_agent": "openbuild-implementation-strongest",
                "observed_model": "unknown",
                "sandbox": "read-only",
                "lease": "M1",
                "dispatch_result": "selected",
                "fallback_reason": "none",
            },
            {
                "event": "code-write",
                "actor": "openbuild-implementation-strongest",
            },
        ]

        self.assertTrue(any("workspace-write" in error for error in validate_implementation_dispatch_trace(trace)))


class ReviewEscalationTraceTests(unittest.TestCase):
    @staticmethod
    def review_cycle(
        tier: str,
        agent: str,
        revision: str,
        *,
        verdict: str,
        findings: str,
        escalation_reason: str,
    ) -> list[dict[str, str]]:
        return [
            {
                "event": "review-dispatch",
                "risk": "low",
                "tier": tier,
                "agent": agent,
                "diff_revision": revision,
                "result": "selected",
            },
            {
                "event": "review-routing-receipt",
                "diff_revision": revision,
                "risk_floor": "fast",
                "requested_agent": agent,
                "requested_tier": tier,
                "dispatch_method": "exact-custom-agent",
                "configured_model": f"{tier}-review-model",
                "observed_agent": agent,
                "observed_model": "unknown",
                "sandbox": "read-only",
                "dispatch_result": "selected",
                "fallback_reason": "none",
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
            },
        ]

    def test_low_risk_escalates_one_tier_after_root_remediation(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild-review-fast",
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
                "balanced",
                "openbuild-review-balanced",
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
            "openbuild-review-fast",
            "D1",
            verdict="REVISE",
            findings="none",
            escalation_reason="low-confidence",
        )
        trace.extend(
            self.review_cycle(
                "strong",
                "openbuild-review-strong",
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
                "openbuild-review-balanced",
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
            "openbuild-review-fast",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace.extend(
            self.review_cycle(
                "balanced",
                "openbuild-review-balanced",
                "D1",
                verdict="ACCEPT",
                findings="none",
                escalation_reason="none",
            )
        )

        self.assertTrue(any("concrete escalation trigger" in error for error in validate_review_escalation_trace(trace)))

    def test_non_accepting_final_result_cannot_close_the_ladder(self) -> None:
        trace = self.review_cycle(
            "fast",
            "openbuild-review-fast",
            "D1",
            verdict="REVISE",
            findings="none",
            escalation_reason="none",
        )

        self.assertTrue(any("requires the next reviewer tier" in error for error in validate_review_escalation_trace(trace)))

    def test_high_risk_starts_with_exact_strong_read_only_reviewer(self) -> None:
        trace = self.review_cycle(
            "balanced",
            "openbuild-review-balanced",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[0]["risk"] = "high"
        trace[1]["risk_floor"] = "strong"

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("must start at exact strong reviewer" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
