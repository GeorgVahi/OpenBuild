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
    validate_decision_authority_trace,
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

        readme = self.readme.replace("decision application receipt", "change summary")
        self.assertTrue(any("README.md" in error for error in self.validate(readme=readme)))


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
    def test_release_manifest_version_and_latest_release_are_documented(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.4.0] - 2026-07-12", changelog)
        self.assertEqual(validate_changelog_contract(changelog, "1.1.1"), [])

        mutated = changelog.replace("## [1.1.1] - 2026-07-13", "## [next] - 2026-07-13")
        self.assertTrue(any("current manifest version" in error for error in validate_changelog_contract(mutated, "1.1.1")))

    def test_released_version_is_pinned_in_both_install_channels(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.assertEqual(validate_release_docs_contract(readme, readme_ru, "1.1.1"), [])

        mutated = readme.replace("--ref v1.1.1", "--ref main")
        self.assertTrue(any("README.md" in error for error in validate_release_docs_contract(mutated, readme_ru, "1.1.1")))


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
