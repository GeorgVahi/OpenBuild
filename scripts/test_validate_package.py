"""Contract tests for the OpenBuild package validator."""

from __future__ import annotations

import sys
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
    validate_packaged_search_profile,
    validate_profile_migration_trace,
    validate_release_docs_contract,
    validate_review_escalation_trace,
    validate_search_dispatch_trace,
    validate_usage_routing_contract,
)


class RunnerOnlyRoutingContractTests(unittest.TestCase):
    def test_only_explicit_cli_dispatch_is_accepted(self) -> None:
        self.assertEqual(EXACT_DISPATCH_METHODS, {"codex-exec-explicit-model"})

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

    def test_delegation_contract_is_present_in_model_and_tdd(self) -> None:
        model_routing = self.model_routing.replace("Implementation worker", "Implementation helper")
        self.assertTrue(any("model-routing.md" in error for error in self.validate(model_routing=model_routing)))

        tdd_workflow = self.tdd_workflow.replace("bounded implementation worker", "implementation helper")
        self.assertTrue(any("tdd-workflow.md" in error for error in self.validate(tdd_workflow=tdd_workflow)))

        route = "Select the risk-matched root or bounded implementation worker"
        edit = "Under that lease, add or modify the test"
        tdd_workflow = self.tdd_workflow.replace(route, "__EDIT_ORDER__").replace(edit, route).replace("__EDIT_ORDER__", edit)
        self.assertTrue(any("must precede every test code edit" in error for error in self.validate(tdd_workflow=tdd_workflow)))

    def test_delegation_modes_and_root_handoff_are_required(self) -> None:
        protocol = self.protocol_text.replace("`sequential-workers`", "`multiple-workers`")
        self.assertTrue(any("delegation modes" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace("Git exclusively root-owned", "Git controlled")
        self.assertTrue(any("root handoff" in error for error in self.validate(protocol_text=protocol)))

        protocol = self.protocol_text.replace(
            "Do not repair that milestone through the root or a replacement lease",
            "Repair that milestone through a new route",
        )
        self.assertTrue(any("root handoff" in error for error in self.validate(protocol_text=protocol)))

        tdd_workflow = self.tdd_workflow.replace(
            "keep the milestone blocked, and create no replacement writer",
            "select a fallback writer",
        )
        self.assertTrue(any("failed exact writer recovery" in error for error in self.validate(tdd_workflow=tdd_workflow)))



class ChangelogContractTests(unittest.TestCase):
    def test_release_manifest_version_and_latest_release_are_documented(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(validate_changelog_contract(changelog, "2.1.2"), [])
        self.assertNotIn("## [2.1.1]", changelog)

        mutated = changelog.replace("## [2.1.2] - 2026-07-14", "## [next] - 2026-07-14")
        self.assertTrue(any("current manifest version" in error for error in validate_changelog_contract(mutated, "2.1.2")))

    def test_released_version_is_pinned_in_both_install_channels(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_ru = (ROOT / "README.ru.md").read_text(encoding="utf-8")
        self.assertEqual(validate_release_docs_contract(readme, readme_ru, "2.1.2"), [])

        mutated = readme.replace("--ref v2.1.2", "--ref main")
        self.assertTrue(any("README.md" in error for error in validate_release_docs_contract(mutated, readme_ru, "2.1.2")))


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

    def test_exact_spark_search_precedes_root_recovery(self) -> None:
        self.assertEqual(self.validate(), [])

        model_routing = self.model_routing.replace("**Exact Spark route:**", "**Search worker:**")
        self.assertTrue(any("search usage-pool" in error for error in self.validate(model_routing=model_routing)))

        exact = "**Exact Spark route:**"
        recovery = "**Root recovery:**"
        model_routing = self.model_routing.replace(exact, "__SEARCH_ORDER__").replace(recovery, exact).replace("__SEARCH_ORDER__", recovery)
        self.assertTrue(any("exact Spark must precede root recovery" in error for error in self.validate(model_routing=model_routing)))

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
            "start the custom agent named `openbuild_search_separate`",
            "Attempt a suitable search worker",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(skill_text=skill_text)))

        code_discovery = self.code_discovery.replace(
            "before the root runs any new repository search command",
            "early in repository discovery",
        )
        self.assertTrue(any("exact agent dispatch" in error for error in self.validate(code_discovery=code_discovery)))

        code_discovery = self.code_discovery.replace(
            "create no other discovery agent",
            "use legacy `openbuild-discovery` when needed",
        )
        self.assertTrue(any("legacy openbuild-discovery" in error for error in self.validate(code_discovery=code_discovery)))

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
            "openbuild_implementation_fast",
            "openbuild_implementation_balanced",
            "openbuild_implementation_strongest",
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
            "Every created implementation run requires concrete model, effort, and sandbox evidence",
            "Implementation may use an unverified label",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

    def test_high_and_critical_writer_floors_cannot_be_relaxed(self) -> None:
        implementation = self.implementation.replace(
            "`high` | exact `openbuild_implementation_strongest` profile",
            "`high` | any configured profile",
        )
        self.assertTrue(any("implementation-delegation.md" in error for error in self.validate(implementation=implementation)))

        implementation = self.implementation.replace(
            "`critical` | exact `openbuild_implementation_strongest` profile",
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
        tier: str = "strongest",
        agent: str = "openbuild_implementation_strongest",
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
        trace = self.valid_trace(risk="medium")
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
                "owner": "openbuild_implementation_strongest",
            },
            {
                "event": "implementation-dispatch",
                "risk": "high",
                "agent_name": "openbuild_implementation_strongest",
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
    @staticmethod
    def review_cycle(
        tier: str,
        agent: str,
        revision: str,
        *,
        verdict: str,
        findings: str,
        escalation_reason: str,
    ) -> list[dict[str, object]]:
        running: dict[str, object] = {
            "event": "review-routing-receipt",
            "diff_revision": revision,
            "risk_floor": "fast",
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
                "risk": "low",
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
                "balanced",
                "openbuild_review_balanced",
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

    def test_high_risk_starts_with_exact_strong_read_only_reviewer(self) -> None:
        trace = self.review_cycle(
            "balanced",
            "openbuild_review_balanced",
            "D1",
            verdict="ACCEPT",
            findings="none",
            escalation_reason="none",
        )
        trace[0]["risk"] = "high"
        trace[1]["risk_floor"] = "strong"

        errors = validate_review_escalation_trace(trace)
        self.assertTrue(any("must start at exact strong reviewer" in error for error in errors))

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
