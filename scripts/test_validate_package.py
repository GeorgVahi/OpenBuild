"""Contract tests for the OpenBuild package validator."""

from __future__ import annotations

import unittest

from validate_package import (
    BLINDSPOT_PROTOCOL,
    IMPLEMENTATION_DELEGATION,
    ROOT,
    SKILL,
    VERSION_SYNC_PATHS,
    commit_requires_version_bump,
    validate_auto_routing_contract,
    validate_blindspot_contract,
    validate_changelog_contract,
    validate_implementation_delegation_contract,
    validate_release_docs_contract,
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

        route = "Select the strongest proven root or bounded implementation worker"
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
    def test_released_manifest_version_has_dated_section(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.4.0] - 2026-07-12", changelog)
        self.assertEqual(validate_changelog_contract(changelog, "0.4.0"), [])

        mutated = changelog.replace("## [0.4.0] - 2026-07-12", "## [next] - 2026-07-12")
        self.assertTrue(any("current manifest version" in error for error in validate_changelog_contract(mutated, "0.4.0")))

    def test_released_version_is_pinned_in_both_install_channels(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.assertEqual(validate_release_docs_contract(readme, readme_ru, "0.4.0"), [])

        mutated = readme.replace("--ref v0.4.0", "--ref main")
        self.assertTrue(any("README.md" in error for error in validate_release_docs_contract(mutated, readme_ru, "0.4.0")))


class UsageRoutingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.model_routing = (SKILL / "references" / "model-routing.md").read_text(encoding="utf-8")
        self.code_discovery = (SKILL / "references" / "code-discovery.md").read_text(encoding="utf-8")
        self.implementation = IMPLEMENTATION_DELEGATION.read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")

    def validate(self, **overrides: str) -> list[str]:
        return validate_usage_routing_contract(
            overrides.get("skill_text", self.skill_text),
            overrides.get("model_routing", self.model_routing),
            overrides.get("code_discovery", self.code_discovery),
            overrides.get("implementation", self.implementation),
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

    def test_search_quota_failure_opens_one_run_circuit_breaker(self) -> None:
        model_routing = self.model_routing.replace("open a circuit breaker", "fall back")
        self.assertTrue(any("search usage-pool" in error for error in self.validate(model_routing=model_routing)))

        discovery = self.code_discovery.replace("do not pay for repeated failed attempts", "retry later")
        self.assertTrue(any("code-discovery.md" in error for error in self.validate(code_discovery=discovery)))

    def test_every_code_edit_uses_strongest_proven_route(self) -> None:
        implementation = self.implementation.replace("strongest proven coding model for every complexity class", "suitable coding model")
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        injected = self.model_routing.replace(
            "## `$build setup-models`",
            "An unknown worker is a disclosed fallback.\n\n## `$build setup-models`",
        )
        self.assertTrue(any("forbidden unproven writer fallback" in error for error in self.validate(model_routing=injected)))

        implementation = self.implementation.replace(
            "only when its effective coding model is proven strongest",
            "when all stronger routes returned an observed failure",
        )
        self.assertTrue(any("forbidden downgrade" in error for error in self.validate(implementation=implementation)))

    def test_usage_routing_is_explained_in_both_readmes(self) -> None:
        readme = self.readme.replace("Search always attempts a confirmed separate-usage route first", "Search selects a suitable route")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))

        readme_ru = self.readme_ru.replace("Поиск всегда сначала пытается использовать подтверждённый separate-usage route", "Поиск выбирает подходящий route")
        self.assertTrue(any("README.ru.md" in error for error in self.validate(readme_ru=readme_ru)))


if __name__ == "__main__":
    unittest.main()
