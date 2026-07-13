#!/usr/bin/env python3
"""Validate the public OpenBuild package without third-party dependencies."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "openbuild"
SKILL = PLUGIN / "skills" / "build"
BLINDSPOT_PROTOCOL = SKILL / "references" / "blindspot-protocol.md"
IMPLEMENTATION_DELEGATION = SKILL / "references" / "implementation-delegation.md"

REQUIRED = [
    ROOT / ".agents" / "plugins" / "marketplace.json",
    ROOT / ".gitattributes",
    ROOT / ".gitignore",
    ROOT / "README.md",
    ROOT / "README.ru.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "LICENSE",
    ROOT / "CHANGELOG.md",
    PLUGIN / ".codex-plugin" / "plugin.json",
    SKILL / "SKILL.md",
    SKILL / "agents" / "openai.yaml",
    SKILL / "references" / "spec-template.md",
    BLINDSPOT_PROTOCOL,
    SKILL / "references" / "code-discovery.md",
    IMPLEMENTATION_DELEGATION,
    SKILL / "references" / "minimality-protocol.md",
    SKILL / "references" / "model-routing.md",
    SKILL / "references" / "review-protocol.md",
    SKILL / "references" / "tdd-workflow.md",
    SKILL / "references" / "versioning.md",
    ROOT / "scripts" / "test_validate_package.py",
]

TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".toml", ".py"}
SEMVER_IDENTIFIER = r"(?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER_PRERELEASE = rf"{SEMVER_IDENTIFIER}(?:\.{SEMVER_IDENTIFIER})*"
SEMVER_BUILD = r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*"
SEMVER = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-{SEMVER_PRERELEASE})?(?:\+{SEMVER_BUILD})?$"
)
SEMVER_PARTS = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    rf"(?:-(?P<prerelease>{SEMVER_PRERELEASE}))?(?:\+{SEMVER_BUILD})?$"
)
MANIFEST_RELATIVE = "plugins/openbuild/.codex-plugin/plugin.json"
VERSION_SYNC_PATHS = {MANIFEST_RELATIVE, "CHANGELOG.md", "README.md", "README.ru.md"}
SEARCH_AGENT = "openbuild-search-separate"
SEARCH_DISPATCH_FAILURES = {
    "profile-not-discoverable",
    "selector-unavailable",
    "model-unavailable",
    "quota-exhausted",
    "spawn-failed",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def read_text(path: Path, errors: list[str]) -> str:
    data = path.read_bytes()
    relative = path.relative_to(ROOT)
    if data.startswith(b"\xef\xbb\xbf"):
        fail(errors, f"{relative}: UTF-8 BOM is not allowed")
    if b"\r" in data:
        fail(errors, f"{relative}: CR/CRLF detected; repository text must use LF")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(errors, f"{relative}: not valid UTF-8 ({exc})")
        return ""


def markdown_section(text: str, heading: str) -> str:
    """Return one Markdown section without matching tokens from later sections."""

    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return ""

    level = len(heading) - len(heading.lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end])


def validate_search_dispatch_trace(events: list[dict[str, str]]) -> list[str]:
    """Validate a compact observable trace for the first repository lookup."""

    errors: list[str] = []
    lookup_index = next(
        (index for index, event in enumerate(events) if event.get("event") == "repository-search"),
        None,
    )
    if lookup_index is None:
        return ["search dispatch trace: missing repository-search event"]

    prior_events = events[:lookup_index]
    dispatches = [event for event in prior_events if event.get("event") == "search-dispatch"]
    if not dispatches:
        errors.append("search dispatch trace: exact agent dispatch must precede repository search")
        return errors

    dispatch = dispatches[0]
    if dispatch.get("agent") != SEARCH_AGENT:
        errors.append(f"search dispatch trace: first dispatch must select exact agent {SEARCH_AGENT}")

    result = dispatch.get("result")
    fallback_reason = dispatch.get("fallback_reason", "")
    if result == "selected":
        if fallback_reason not in {"", "none"}:
            errors.append("search dispatch trace: selected route must not report a fallback reason")
        if events[lookup_index].get("actor") != SEARCH_AGENT:
            errors.append("search dispatch trace: selected exact agent must own the first repository search")
    elif result == "failed":
        if fallback_reason not in SEARCH_DISPATCH_FAILURES:
            errors.append("search dispatch trace: failed dispatch must use an allowed fallback reason")
    else:
        errors.append("search dispatch trace: dispatch result must be selected or failed")

    receipt_events = [
        (index, event)
        for index, event in enumerate(prior_events)
        if event.get("event") == "search-routing-receipt"
    ]
    if not receipt_events:
        errors.append("search dispatch trace: routing receipt must precede repository search")
        return errors

    receipt_index, receipt = receipt_events[-1]
    dispatch_index = prior_events.index(dispatch)
    if receipt_index <= dispatch_index:
        errors.append("search dispatch trace: routing receipt must follow the exact dispatch attempt")
    required_fields = {
        "search_agent",
        "dispatch_method",
        "configured_model",
        "observed_agent",
        "observed_model",
        "pool",
        "fallback_reason",
    }
    missing = sorted(field for field in required_fields if field not in receipt)
    if missing:
        errors.append(f"search dispatch trace: routing receipt missing fields {missing}")
    if receipt.get("search_agent") != SEARCH_AGENT:
        errors.append(f"search dispatch trace: routing receipt must name {SEARCH_AGENT}")
    if receipt.get("dispatch_method") not in {"per-spawn-model", "exact-custom-agent", "unavailable"}:
        errors.append("search dispatch trace: routing receipt has invalid dispatch method")
    if result == "selected" and receipt.get("pool") != "separate":
        errors.append("search dispatch trace: selected exact agent must record the confirmed separate pool")
    expected_reason = "none" if result == "selected" else fallback_reason
    if receipt.get("fallback_reason") != expected_reason:
        errors.append("search dispatch trace: routing receipt fallback reason must match dispatch outcome")

    return errors


def validate_auto_routing_contract(
    skill_text: str,
    protocol_text: str,
    metadata_text: str,
    readme: str,
    readme_ru: str,
) -> list[str]:
    errors: list[str] = []
    invocation = markdown_section(skill_text, "## Parse the invocation")
    if "`$build auto <idea-or-path>`" not in invocation:
        errors.append("SKILL.md invocation contract: missing explicit auto mode")
    if "`$build <idea-or-path>`: treat as `auto`" not in invocation:
        errors.append("SKILL.md invocation contract: bare invocation must use auto phase routing")
    selection = markdown_section(skill_text, "## Select the specification safely")
    for token in ["workflow target", "first incomplete phase", "legacy `Ready`"]:
        if token not in selection:
            errors.append(f"SKILL.md auto-routing contract: missing {token}")
    lifecycle = markdown_section(protocol_text, "## Lifecycle routing")
    for token in [
        "workflow target",
        "first incomplete phase",
        "`new` and `refine`",
        "`run` and `full`",
        "`auto`",
        "| `Draft`, `Questions`",
        "| Legacy `Ready`",
        "| `In progress` | implementation",
        "| `Complete` | verification",
        "full acceptance set",
        "focused and risk-based signals",
        "documentation/version",
        "rollout/rollback",
    ]:
        if token not in lifecycle:
            errors.append(f"blindspot-protocol.md lifecycle routing: missing {token}")
    if "auto mode" not in metadata_text:
        errors.append("agents/openai.yaml: default prompt must select auto mode")
    readme_routing = markdown_section(readme, "## How automatic phase routing works")
    if not readme_routing:
        errors.append("README.md: missing automatic phase-routing section")
    else:
        for token in ["workflow target", "the first incomplete phase", "Explicit modes and paths", "legacy specification", "complete acceptance evidence"]:
            if token not in readme_routing:
                errors.append(f"README.md automatic phase routing: missing {token}")
    readme_ru_routing = markdown_section(readme_ru, "## Как работает автоматический выбор этапа")
    if not readme_ru_routing:
        errors.append("README.ru.md: missing automatic phase-routing section")
    else:
        for token in ["цель workflow", "первый незавершённый этап", "Явные режимы и пути", "Legacy-спецификация", "полному acceptance evidence"]:
            if token not in readme_ru_routing:
                errors.append(f"README.ru.md automatic phase routing: missing {token}")
    return errors


def validate_blindspot_contract(
    skill_text: str,
    protocol_text: str,
    template_text: str,
    readme: str,
    readme_ru: str,
) -> list[str]:
    errors: list[str] = []
    audit = markdown_section(skill_text, "## Audit blind spots")
    if "[the specification readiness protocol](references/blindspot-protocol.md)" not in audit:
        errors.append("SKILL.md blind-spot section: missing readiness protocol link")

    for heading, label in [
        ("## Coverage model", "coverage model"),
        ("## Decision memory and deduplication", "decision memory"),
        ("## Adaptive critic loop", "adaptive critic loop"),
        ("## Critic result", "critic result"),
        ("## Ready gate", "Ready gate"),
    ]:
        if not markdown_section(protocol_text, heading):
            errors.append(f"blindspot-protocol.md: missing {label} section")

    coverage = markdown_section(protocol_text, "## Coverage model")
    for token in ["B-###", "gap", "covered", "not applicable", "repository fact", "technical decision", "product decision", "new authority"]:
        if token not in coverage:
            errors.append(f"blindspot-protocol.md coverage model: missing {token}")

    decision_memory = markdown_section(protocol_text, "## Decision memory and deduplication")
    for token in [
        "D-###",
        "Decision key",
        "legacy IDs",
        "resolved",
        "reopened",
        "new evidence",
        "do not ask it again",
        "conditional child decision",
    ]:
        if token not in decision_memory:
            errors.append(f"blindspot-protocol.md decision memory: missing {token}")

    critic_loop = markdown_section(protocol_text, "## Adaptive critic loop")
    for token in [
        "decision memory",
        "coverage ledger",
        "semantic specification inputs",
        "Do not increment it for audit metadata",
        "closure verdict remains bound",
        "low",
        "medium",
        "high",
        "critical",
        "unchanged tuple",
        "sequential separated root-perspective passes",
        "non-trivial low work",
        "two complementary",
        "separate closure pass for high",
        "three complementary",
        "Missing model/tier metadata alone",
        "missing required perspective coverage",
        "self-review, limited",
    ]:
        if token not in critic_loop:
            errors.append(f"blindspot-protocol.md adaptive critic loop: missing {token}")

    ready_gate = markdown_section(protocol_text, "## Ready gate")
    for token in [
        "coverage ledger",
        "gap",
        "blocking product decisions",
        "material contradiction",
        "missing new authority",
        "critic finding",
        "acceptance criteria",
        "current specification revision",
        "COVERED",
    ]:
        if token not in ready_gate:
            errors.append(f"blindspot-protocol.md Ready gate: missing {token}")

    risks = markdown_section(template_text, "## 9. Risks and blind spots")
    ledger_header = "ID | Concern | Status | Disposition | Evidence or decision | Next action"
    if ledger_header not in risks or "B-###" not in risks or "D-###" not in risks:
        errors.append("spec-template.md coverage ledger: missing durable IDs or required columns")

    critic_result = markdown_section(protocol_text, "## Critic result")
    for token in [
        "Specification revision:",
        "Perspective:",
        "Verdict: COVERED | GAPS",
        "Coverage:",
        "New gaps:",
        "Reopen requests:",
        "Duplicate/resolved references:",
    ]:
        if token not in critic_result:
            errors.append(f"blindspot-protocol.md critic result: missing {token}")

    readme_blindspots = markdown_section(readme, "## How blind-spot critique works")
    if not readme_blindspots:
        errors.append("README.md: missing blind-spot critique section")
    else:
        for token in ["stable `D-###` IDs", "A resolved ID is a locked constraint", "Reopening is allowed only", "same critic perspective/tier", "not a claim of literal omniscience"]:
            if token not in readme_blindspots:
                errors.append(f"README.md blind-spot critique: missing {token}")
    readme_ru_blindspots = markdown_section(readme_ru, "## Как работает критика blind spots")
    if not readme_ru_blindspots:
        errors.append("README.ru.md: missing blind-spot critique section")
    else:
        for token in ["стабильные IDs `D-###`", "Решённый ID становится зафиксированным ограничением", "Переоткрытие допустимо только", "одна perspective/tier не повторяется", "не заявление о буквальном всеведении"]:
            if token not in readme_ru_blindspots:
                errors.append(f"README.ru.md blind-spot critique: missing {token}")
    return errors


def validate_implementation_delegation_contract(
    skill_text: str,
    protocol_text: str,
    model_routing: str,
    tdd_workflow: str,
    readme: str,
    readme_ru: str,
) -> list[str]:
    errors: list[str] = []
    implementation = markdown_section(skill_text, "## Implement milestones")
    if "[adaptive implementation delegation](references/implementation-delegation.md)" not in implementation:
        errors.append("SKILL.md implementation section: missing adaptive delegation link")

    for heading, label in [
        ("## Delegation modes", "delegation modes"),
        ("## Single-writer lease", "single-writer lease"),
        ("## Worker contract", "worker contract"),
        ("## Root handoff gate", "root handoff gate"),
    ]:
        if not markdown_section(protocol_text, heading):
            errors.append(f"implementation-delegation.md: missing {label} section")

    lease = markdown_section(protocol_text, "## Single-writer lease")
    for token in ["one active writer", "Allowed files", "Forbidden files", "Baseline", "Stop conditions", "otherwise no lease is granted"]:
        if token not in lease:
            errors.append(f"implementation-delegation.md single-writer lease: missing {token}")

    modes = markdown_section(protocol_text, "## Delegation modes")
    for token in ["`root-only`", "`bounded-worker`", "`sequential-workers`", "parallel write-heavy", "`critical`"]:
        if token not in modes:
            errors.append(f"implementation-delegation.md delegation modes: missing {token}")

    worker = markdown_section(protocol_text, "## Worker contract")
    for token in ["specification", "version", "stage, commit, push", "product or architecture decisions", "stop before all test and production code edits"]:
        if token not in worker:
            errors.append(f"implementation-delegation.md worker contract: missing {token}")

    handoff = markdown_section(protocol_text, "## Root handoff gate")
    for token in [
        "Recheck branch",
        "allowed",
        "Reread the implementation",
        "Rerun the focused green check independently",
        "version/changelog/documentation",
        "progressive review",
        "Git exclusively root-owned",
    ]:
        if token not in handoff:
            errors.append(f"implementation-delegation.md root handoff: missing {token}")

    if "## Implementation worker routing" not in model_routing or "Implementation worker" not in model_routing:
        errors.append("model-routing.md: missing Implementation worker routing contract")
    if "bounded implementation worker" not in tdd_workflow:
        errors.append("tdd-workflow.md: missing bounded implementation worker contract")
    tdd_steps = markdown_section(tdd_workflow, "## Red → green → refactor")
    route_position = tdd_steps.find("Select the risk-matched root or bounded implementation worker")
    edit_position = tdd_steps.find("Under that lease, add or modify the test")
    if route_position < 0 or edit_position < 0 or route_position >= edit_position:
        errors.append("tdd-workflow.md: risk-matched writer route and lease must precede every test code edit")
    readme_delegation = markdown_section(readme, "## How adaptive implementation delegation works")
    if not readme_delegation:
        errors.append("README.md: missing adaptive implementation-delegation section")
    else:
        for token in ["one active writer", "exact allowed files", "The root does not edit", "strictly sequentially"]:
            if token not in readme_delegation:
                errors.append(f"README.md adaptive implementation delegation: missing {token}")
    readme_ru_delegation = markdown_section(readme_ru, "## Как работает адаптивная делегация реализации")
    if not readme_ru_delegation:
        errors.append("README.ru.md: missing adaptive implementation-delegation section")
    else:
        for token in ["одновременно пишет только один агент", "точный список разрешённых файлов", "root не редактирует", "строго последовательно"]:
            if token not in readme_ru_delegation:
                errors.append(f"README.ru.md adaptive implementation delegation: missing {token}")
    return errors


def validate_changelog_contract(changelog: str, version: str) -> list[str]:
    errors: list[str] = []
    unreleased = markdown_section(changelog, "## [Unreleased]")
    if not unreleased:
        errors.append("CHANGELOG.md: missing Unreleased section")
        return errors

    release_heading = next(
        (
            line
            for line in changelog.splitlines()
            if re.fullmatch(rf"## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}", line)
        ),
        None,
    )
    if release_heading:
        current_section = markdown_section(changelog, release_heading)
        current_label = release_heading
    elif contains_exact_version(unreleased, version):
        current_section = unreleased
        current_label = "CHANGELOG.md Unreleased"
    else:
        errors.append(f"CHANGELOG.md: missing current manifest version {version} in Unreleased or a dated release")
        return errors

    for token in [
        "blind-spot",
        "single-writer",
        "`auto`",
        "separate usage pool",
        "Risk-matched-model coding",
        "Deterministic contract validation",
    ]:
        if token not in current_section:
            errors.append(f"{current_label}: missing current workflow note {token}")
    return errors


def validate_release_docs_contract(readme: str, readme_ru: str, version: str) -> list[str]:
    errors: list[str] = []
    for label, text in [("README.md", readme), ("README.ru.md", readme_ru)]:
        for token in [
            f"--ref v{version}",
            f"/tree/v{version}/plugins/openbuild/skills/build",
        ]:
            if token not in text:
                errors.append(f"{label}: released version {version} is not pinned by {token}")
    return errors


def validate_usage_routing_contract(
    skill_text: str,
    model_routing: str,
    code_discovery: str,
    implementation: str,
    readme: str,
    readme_ru: str,
) -> list[str]:
    errors: list[str] = []

    search_preflight = markdown_section(skill_text, "## Initialize search routing")
    for token in [
        "Before locating a specification",
        "separate-pool circuit-breaker",
        "every repository lookup",
        "any new file/symbol/grep lookup",
        "Spawn the custom agent named `openbuild-search-separate`",
        "A generic subagent, a descriptive task name",
        "exact dispatch succeeds or returns an allowed fallback reason",
    ]:
        if token not in search_preflight:
            category = "exact agent dispatch" if "agent" in token or "exact dispatch" in token else "search preflight"
            errors.append(f"SKILL.md {category}: missing {token}")
    preflight_position = skill_text.find("## Initialize search routing")
    selection_position = skill_text.find("## Select the specification safely")
    baseline_position = skill_text.find("## Establish the baseline")
    if preflight_position < 0 or selection_position < 0 or baseline_position < 0 or not (preflight_position < selection_position < baseline_position):
        errors.append("SKILL.md search preflight: must precede specification selection and baseline discovery")

    skill_discovery = markdown_section(skill_text, "## Discover repository evidence")
    for token in [
        "before any repository grep",
        "dispatch the exact confirmed separate-usage search agent first",
        "main-pool model",
        "root search only",
    ]:
        if token not in skill_discovery:
            errors.append(f"SKILL.md usage routing: missing {token}")
    skill_implementation = markdown_section(skill_text, "## Implement milestones")
    for token in ["risk-matched writer tier", "Escalate only on task evidence", "preserve the same TDD/minimality/validation gates"]:
        if token not in skill_implementation:
            errors.append(f"SKILL.md risk-matched writer routing: missing {token}")

    search_order = markdown_section(model_routing, "## Search usage-pool order")
    for token in [
        "**Separate usage pool:**",
        "openbuild-search-separate",
        "**Efficient main-pool fallback:**",
        "openbuild-search-fallback",
        "open a circuit breaker",
        "without retrying the same failed route for every grep",
        "Do not scrape or infer remaining quota",
        "Do not silently skip it",
        "select `openbuild-search-separate` by exact custom-agent name",
        "generic subagent, task name, or profile mention does not count as selection",
        "profile-not-discoverable",
        "selector-unavailable",
        "model-unavailable",
        "quota-exhausted",
        "spawn-failed",
        "routing receipt",
        "configured_model",
        "observed_model",
        "fallback_reason",
    ]:
        if token not in search_order:
            if token in SEARCH_DISPATCH_FAILURES:
                category = "fallback reason"
            elif token.startswith("select `openbuild") or "does not count" in token:
                category = "exact agent dispatch"
            else:
                category = "search usage-pool order"
            errors.append(f"model-routing.md {category}: missing {token}")
    ordered_search_tokens = [
        "**Separate usage pool:**",
        "**Efficient main-pool fallback:**",
        "**Role-only fallback:**",
        "**Generic subagent fallback:**",
        "**Root fallback:**",
    ]
    search_positions = [search_order.find(token) for token in ordered_search_tokens]
    if any(position < 0 for position in search_positions) or search_positions != sorted(search_positions):
        errors.append("model-routing.md search usage-pool order: separate pool must precede every fallback branch")

    implementation_route = markdown_section(model_routing, "## Implementation worker routing")
    for token in [
        "minimum sufficient proven coding tier",
        "openbuild-implementation-fast",
        "openbuild-implementation-balanced",
        "openbuild-implementation-strongest",
        "Escalate only on evidence",
        "Missing model/tier metadata alone does not block low or medium implementation",
        "High work still requires a confirmed strong route",
        "critical work requires the strongest proven route",
        "stop before every test or production code edit",
        "rather than silently lowering the risk floor",
    ]:
        if token not in implementation_route:
            errors.append(f"model-routing.md implementation routing: missing {token}")

    setup = markdown_section(model_routing, "## `$build setup-models`")
    for token in [
        "openbuild-search-separate",
        "openbuild-search-fallback",
        "openbuild-implementation-fast",
        "openbuild-implementation-balanced",
        "openbuild-implementation-strongest",
        "confirmed usage pool",
        "workspace-write",
    ]:
        if token not in setup:
            errors.append(f"model-routing.md setup-models: missing {token}")

    mandatory_search = markdown_section(code_discovery, "## Mandatory routing rule")
    for token in [
        "`rg --files`",
        "openbuild-search-separate",
        "openbuild-search-fallback",
        "new grep or lookup",
        "circuit breaker",
        "do not pay for repeated failed attempts",
        "before the root runs any new repository search command",
        "generic spawn or task label",
    ]:
        if token not in mandatory_search:
            category = "exact agent dispatch" if "root runs" in token or "generic spawn" in token else "usage routing"
            errors.append(f"code-discovery.md {category}: missing {token}")

    routing_receipt = markdown_section(code_discovery, "## Search routing receipt")
    for token in [
        "search_agent: openbuild-search-separate",
        "dispatch_method:",
        "configured_model:",
        "observed_agent:",
        "observed_model:",
        "pool:",
        "dispatch_result:",
        "fallback_reason:",
        "usage dashboard as secondary evidence",
    ]:
        if token not in routing_receipt:
            errors.append(f"code-discovery.md routing receipt: missing {token}")

    for token in [
        "risk-matched coding model for every complexity class",
        "openbuild-implementation-fast",
        "openbuild-implementation-balanced",
        "openbuild-implementation-strongest",
        "Read-only search/discovery",
        "Missing model/tier metadata alone does not block low or medium implementation",
        "For high work require a confirmed strong route",
        "for critical work require the strongest proven route",
        "stop before all test and production code edits",
    ]:
        if token not in implementation:
            errors.append(f"implementation-delegation.md risk-matched writer routing: missing {token}")

    readme_usage = markdown_section(readme, "## How usage-aware model routing works")
    if not readme_usage:
        errors.append("README.md: missing usage-aware model-routing section")
    else:
        for token in [
            "Search always attempts a confirmed separate-usage route first",
            "exact custom agent `openbuild-search-separate`",
            "routing receipt",
            "fallback_reason",
            "current-run circuit breaker",
            "does not scrape the private usage dashboard",
            "risk-matched writer",
            "openbuild-implementation-fast",
            "openbuild-implementation-balanced",
            "Escalation",
            "model_reasoning_effort",
        ]:
            if token not in readme_usage:
                errors.append(f"README.md usage-aware model routing: missing {token}")

    readme_ru_usage = markdown_section(readme_ru, "## Как работает usage-aware routing моделей")
    if not readme_ru_usage:
        errors.append("README.ru.md: missing usage-aware model-routing section")
    else:
        for token in [
            "exact custom agent `openbuild-search-separate`",
            "routing receipt",
            "fallback_reason",
            "Поиск всегда сначала пытается использовать подтверждённый separate-usage route",
            "circuit breaker на текущий run",
            "не скрейпит приватную usage page",
            "risk-matched writer",
            "openbuild-implementation-fast",
            "openbuild-implementation-balanced",
            "Эскалация",
            "model_reasoning_effort",
        ]:
            if token not in readme_ru_usage:
                errors.append(f"README.ru.md usage-aware model routing: missing {token}")
    return errors


def validate_json(path: Path, errors: list[str]) -> dict:
    text = read_text(path, errors)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(errors, f"{path.relative_to(ROOT)}: invalid JSON ({exc})")
        return {}
    if not isinstance(value, dict):
        fail(errors, f"{path.relative_to(ROOT)}: root must be an object")
        return {}
    return value


def validate_local_links(path: Path, text: str, errors: list[str]) -> None:
    pattern = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)")
    for match in pattern.finditer(text):
        target = match.group(1).strip().strip("<>").split("#", 1)[0]
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            fail(errors, f"{path.relative_to(ROOT)}: missing local link target {target}")


def semver_key(value: str) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    match = SEMVER_PARTS.fullmatch(value)
    if not match:
        raise ValueError(f"invalid SemVer: {value}")
    prerelease = match.group("prerelease")
    parts: tuple[tuple[int, int | str], ...] = ()
    if prerelease is not None:
        parts = tuple((0, int(item)) if item.isdigit() else (1, item) for item in prerelease.split("."))
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if prerelease is None else 0,
        parts,
    )


def contains_exact_version(text: str, version: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z.-]){re.escape(version)}(?![0-9A-Za-z.-])", text) is not None


def validate_semver_contract(errors: list[str]) -> None:
    valid = ["0.2.0-dev.2", "0.2.0", "1.0.0-alpha.1", "1.0.0+build.01"]
    invalid = ["0.2.0-dev..2", "0.2.0-dev.01", "01.0.0", "1.0.0-", "1.0.0+build..1"]
    for value in valid:
        if not SEMVER.fullmatch(value):
            fail(errors, f"internal SemVer validator rejected valid case {value}")
    for value in invalid:
        if SEMVER.fullmatch(value):
            fail(errors, f"internal SemVer validator accepted invalid case {value}")


def git_output(*args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def normalized_paths(*outputs: str | None) -> set[str]:
    result: set[str] = set()
    for output in outputs:
        if output:
            result.update(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())
    return result


def commit_requires_version_bump(paths: set[str], *, commit_exists: bool = False) -> bool:
    """OpenBuild assigns a unique SemVer version to every commit after the root."""

    return commit_exists or bool(paths)


def is_public_package_path(path: str) -> bool:
    relative = Path(path.replace("\\", "/"))
    if any(part in {".git", ".tmp", "__pycache__"} for part in relative.parts):
        return False
    if relative.as_posix() == "TZ.md":
        return False
    if relative.as_posix().startswith("plugins/openbuild/"):
        return True
    return relative.suffix.lower() in TEXT_SUFFIXES or relative.name in {"LICENSE", ".gitignore", ".gitattributes"}


def text_from_snapshot(revision: str, path: str) -> str | None:
    selector = f":{path}" if revision == "INDEX" else f"{revision}:{path}"
    return git_output("show", selector)


def version_from_git(revision: str) -> str | None:
    text = text_from_snapshot(revision, MANIFEST_RELATIVE)
    if text is None:
        return None
    try:
        value = json.loads(text).get("version")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) and SEMVER.fullmatch(value) else None


def validate_version_snapshot(
    revision: str,
    previous_revision: str,
    changed_paths: set[str],
    errors: list[str],
    context: str,
) -> None:
    missing = VERSION_SYNC_PATHS - changed_paths
    if missing:
        fail(errors, f"version commit gate ({context}): synchronized files missing from one diff: {sorted(missing)}")
        return

    current = version_from_git(revision)
    previous = version_from_git(previous_revision)
    if current is None or previous is None:
        fail(errors, f"version commit gate ({context}): could not read strict SemVer manifests")
        return
    if semver_key(current) <= semver_key(previous):
        fail(errors, f"version commit gate ({context}): version did not increase ({previous} -> {current})")

    for path in ["README.md", "README.ru.md", "CHANGELOG.md"]:
        text = text_from_snapshot(revision, path)
        if text is None or not contains_exact_version(text, current):
            fail(errors, f"version commit gate ({context}): {path} does not contain exact version {current}")


def validate_version_progression(current: str, errors: list[str], commit_gate: bool) -> None:
    if git_output("rev-parse", "--is-inside-work-tree") != "true":
        return

    tracked_working = git_output("diff", "--name-only", "HEAD", "--")
    untracked_working = git_output("ls-files", "--others", "--exclude-standard")
    working_paths = normalized_paths(tracked_working, untracked_working)

    if commit_gate:
        unstaged_paths = normalized_paths(
            git_output("diff", "--name-only", "--"),
            untracked_working,
        )
        unstaged_package_files = {path for path in unstaged_paths if is_public_package_path(path)}
        if unstaged_package_files:
            fail(
                errors,
                f"commit gate: public package files are not fully staged: {sorted(unstaged_package_files)}",
            )
            return

        staged_paths = normalized_paths(git_output("diff", "--cached", "--name-only", "HEAD", "--"))
        if staged_paths:
            if commit_requires_version_bump(staged_paths):
                validate_version_snapshot("INDEX", "HEAD", staged_paths, errors, "index versus HEAD")
            return
        if commit_requires_version_bump(working_paths):
            fail(errors, "version commit gate: stage the complete task diff before validation")
            return

        committed_paths = normalized_paths(
            git_output("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "HEAD", "--")
        )
        parent_exists = git_output("rev-parse", "HEAD^") is not None
        if commit_requires_version_bump(committed_paths, commit_exists=parent_exists):
            validate_version_snapshot("HEAD", "HEAD^", committed_paths, errors, "HEAD versus HEAD^")
        return

    previous_revision: str | None = None
    context = ""
    if commit_requires_version_bump(working_paths):
        previous_revision = "HEAD"
        context = "working tree versus HEAD"
    else:
        committed_paths = normalized_paths(
            git_output("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "HEAD", "--")
        )
        if commit_requires_version_bump(
            committed_paths,
            commit_exists=git_output("rev-parse", "HEAD^") is not None,
        ):
            previous_revision = "HEAD^"
            context = "HEAD versus HEAD^"

    if previous_revision is None:
        return
    previous = version_from_git(previous_revision)
    if previous is None:
        return
    if semver_key(current) <= semver_key(previous):
        fail(
            errors,
            f"plugin.json: repository commit changed ({context}) but version did not increase "
            f"({previous} -> {current})",
        )


def public_text_files() -> list[Path]:
    result: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in {".git", ".tmp", "__pycache__"} for part in relative.parts):
            continue
        if relative.as_posix() == "TZ.md":
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", ".gitignore", ".gitattributes"}:
            result.append(path)
    return result


def main() -> int:
    args = sys.argv[1:]
    if any(arg != "--commit-gate" for arg in args) or len(args) > 1:
        print("Usage: python scripts/validate_package.py [--commit-gate]")
        return 2
    commit_gate = "--commit-gate" in args
    errors: list[str] = []
    validate_semver_contract(errors)

    for path in REQUIRED:
        if not path.is_file():
            fail(errors, f"missing required file: {path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    plugin = validate_json(PLUGIN / ".codex-plugin" / "plugin.json", errors)
    marketplace = validate_json(ROOT / ".agents" / "plugins" / "marketplace.json", errors)

    if plugin.get("name") != "openbuild":
        fail(errors, "plugin.json: name must be openbuild")
    version = plugin.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        fail(errors, "plugin.json: version must be strict SemVer")
    if isinstance(version, str) and SEMVER.fullmatch(version):
        validate_version_progression(version, errors, commit_gate)
    if plugin.get("license") != "MIT":
        fail(errors, "plugin.json: license must be MIT")
    if plugin.get("skills") != "./skills/":
        fail(errors, "plugin.json: skills must use ./skills/")

    entries = marketplace.get("plugins")
    if marketplace.get("name") != "openbuild" or not isinstance(entries, list) or len(entries) != 1:
        fail(errors, "marketplace.json: expected one plugin in the openbuild marketplace")
    elif entries[0].get("name") != "openbuild" or entries[0].get("source", {}).get("path") != "./plugins/openbuild":
        fail(errors, "marketplace.json: plugin name/path mismatch")

    skill_text = read_text(SKILL / "SKILL.md", errors)
    if not re.search(r"(?m)^name: build$", skill_text):
        fail(errors, "SKILL.md: missing name: build")
    if len(skill_text.splitlines()) > 500:
        fail(errors, "SKILL.md: exceeds the 500-line progressive-disclosure limit")
    required_skill_tokens = [
        "[code discovery](references/code-discovery.md)",
        "[the minimality protocol](references/minimality-protocol.md)",
        "[the TDD workflow](references/tdd-workflow.md)",
        "[the specification readiness protocol](references/blindspot-protocol.md)",
        "[adaptive implementation delegation](references/implementation-delegation.md)",
        "[versioning](references/versioning.md)",
        "TDD-first",
        "attempt budget",
        "version impact",
        "separate-usage",
        "risk-matched writer tier",
    ]
    for token in required_skill_tokens:
        if token not in skill_text:
            fail(errors, f"SKILL.md: missing orchestration contract {token}")

    minimality_text = read_text(SKILL / "references" / "minimality-protocol.md", errors)
    for token in ["## Decision ladder", "## Non-negotiable safeguards", "Minimality decision:"]:
        if token not in minimality_text:
            fail(errors, f"minimality-protocol.md: missing contract {token}")
    for path, token in [
        (SKILL / "references" / "tdd-workflow.md", "Minimality decision:"),
        (SKILL / "references" / "review-protocol.md", "Minimality assessment:"),
        (SKILL / "references" / "spec-template.md", "Minimality decision:"),
        (SKILL / "references" / "spec-template.md", "Search routing receipt:"),
    ]:
        if token not in read_text(path, errors):
            fail(errors, f"{path.name}: missing minimality contract {token}")

    metadata_text = read_text(SKILL / "agents" / "openai.yaml", errors)
    if 'allow_implicit_invocation: false' not in metadata_text:
        fail(errors, "agents/openai.yaml: implicit invocation must be disabled")
    if "this Build skill" not in metadata_text or "auto mode" not in metadata_text:
        fail(errors, "agents/openai.yaml: default prompt must be invocation-neutral and select auto mode")

    readme = read_text(ROOT / "README.md", errors)
    readme_ru = read_text(ROOT / "README.ru.md", errors)
    required_docs_tokens = [
        "codex plugin marketplace add",
        "codex plugin add openbuild@openbuild",
        "$openbuild:build",
        "$build new",
        "$build refine",
        "$build run",
        "$build full",
        "$build auto",
        "$build setup-models",
        "$skill-installer",
        "openbuild-discovery",
        "openbuild-search-separate",
        "openbuild-search-fallback",
        "openbuild-implementation-fast",
        "openbuild-implementation-balanced",
        "openbuild-implementation-strongest",
        "openbuild-review-fast",
        "TDD-first",
        "CONTRIBUTING.md",
    ]
    for token in required_docs_tokens:
        if token not in readme:
            fail(errors, f"README.md: missing documented token {token}")
        if token not in readme_ru:
            fail(errors, f"README.ru.md: missing documented token {token}")

    required_doc_sections = [
        ("## How automatic phase routing works", "## Как работает автоматический выбор этапа"),
        ("## How automatic code discovery works", "## Как работает автоматический поиск по коду"),
        ("## How usage-aware model routing works", "## Как работает usage-aware routing моделей"),
        ("## How blind-spot critique works", "## Как работает критика blind spots"),
        ("## How TDD-first implementation works", "## Как работает TDD-first реализация"),
        ("## How adaptive implementation delegation works", "## Как работает адаптивная делегация реализации"),
        ("## How evidence-gated minimality works", "## Как работает evidence-gated minimality"),
        ("## How progressive review works", "## Как работает progressive review"),
        ("## Git and safety policy", "## Git и безопасность"),
    ]
    for english, russian in required_doc_sections:
        if english not in readme:
            fail(errors, f"README.md: missing required section {english}")
        if russian not in readme_ru:
            fail(errors, f"README.ru.md: missing required section {russian}")

    template_text = read_text(SKILL / "references" / "spec-template.md", errors)
    blindspot_text = read_text(BLINDSPOT_PROTOCOL, errors)
    implementation_delegation_text = read_text(IMPLEMENTATION_DELEGATION, errors)
    code_discovery_text = read_text(SKILL / "references" / "code-discovery.md", errors)
    model_routing_text = read_text(SKILL / "references" / "model-routing.md", errors)
    tdd_workflow_text = read_text(SKILL / "references" / "tdd-workflow.md", errors)
    errors.extend(validate_auto_routing_contract(skill_text, blindspot_text, metadata_text, readme, readme_ru))
    errors.extend(validate_blindspot_contract(skill_text, blindspot_text, template_text, readme, readme_ru))
    errors.extend(
        validate_implementation_delegation_contract(
            skill_text,
            implementation_delegation_text,
            model_routing_text,
            tdd_workflow_text,
            readme,
            readme_ru,
        )
    )
    errors.extend(
        validate_usage_routing_contract(
            skill_text,
            model_routing_text,
            code_discovery_text,
            implementation_delegation_text,
            readme,
            readme_ru,
        )
    )

    if "TZ.md" not in read_text(ROOT / ".gitignore", errors).splitlines():
        fail(errors, ".gitignore: local TZ.md must be ignored")
    if "## [0.2.0] - 2026-07-10" not in read_text(ROOT / "CHANGELOG.md", errors):
        fail(errors, "CHANGELOG.md: missing 0.2.0 release entry")
    if "## [0.3.1] - 2026-07-12" not in read_text(ROOT / "CHANGELOG.md", errors):
        fail(errors, "CHANGELOG.md: missing 0.3.1 release entry")
    if "## [0.4.0] - 2026-07-12" not in read_text(ROOT / "CHANGELOG.md", errors):
        fail(errors, "CHANGELOG.md: missing 0.4.0 release entry")
    changelog = read_text(ROOT / "CHANGELOG.md", errors)
    for token in ["openbuild-discovery", "TDD-first", "minimality", "version impact"]:
        if token not in changelog:
            fail(errors, f"CHANGELOG.md: missing historical contract {token}")
    if isinstance(version, str) and not contains_exact_version(changelog, version):
        fail(errors, f"CHANGELOG.md: current plugin version {version} is not documented")
    if isinstance(version, str):
        errors.extend(validate_changelog_contract(changelog, version))
        if re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE):
            errors.extend(validate_release_docs_contract(readme, readme_ru, version))

    contributing = read_text(ROOT / "CONTRIBUTING.md", errors)
    for token in [
        "Semantic Versioning",
        "plugins/openbuild/.codex-plugin/plugin.json",
        "version impact",
        "prerelease counter",
        "Every OpenBuild commit",
        "immutable",
    ]:
        if token not in contributing:
            fail(errors, f"CONTRIBUTING.md: missing versioning contract {token}")

    versioning_text = read_text(SKILL / "references" / "versioning.md", errors)
    for token in [
        "Version impact",
        "every Build-created commit",
        "prerelease",
        "patch",
        "minor",
        "major",
        "immutable",
    ]:
        if token not in versioning_text:
            fail(errors, f"references/versioning.md: missing contract {token}")

    for path, text in [(ROOT / "README.md", readme), (ROOT / "README.ru.md", readme_ru)]:
        if isinstance(version, str) and not contains_exact_version(text, version):
            fail(errors, f"{path.name}: current plugin version {version} is not documented")
        for stale in ["immutable stable tag", "### Stable `v0.1.0`", "stable tags"]:
            if stale.lower() in text.lower():
                fail(errors, f"{path.name}: stale stable-release wording {stale!r}")
    if not read_text(ROOT / "LICENSE", errors).startswith("MIT License"):
        fail(errors, "LICENSE: expected MIT license text")

    forbidden = ["[TO" + "DO", "TO" + "DO:", "C:" + "\\Users\\", "BIAS" + "MACHINE"]
    fixed_model = re.compile(r"\b(?:gpt[\s\-_‑–—]?\d|o\d(?:[-._][a-z0-9]+)?|claude[\s\-_‑–—]?\d|gemini[\s\-_‑–—]?\d)", re.IGNORECASE)
    active_model_assignment = re.compile(
        r'''(?im)^\s*["']?(?:model|model_id)["']?\s*[:=]\s*["'](?![<{])([^"']+)["']'''
    )
    for path in public_text_files():
        text = read_text(path, errors)
        relative = path.relative_to(ROOT)
        for marker in forbidden:
            if marker in text:
                fail(errors, f"{relative}: forbidden marker {marker!r}")
        if fixed_model.search(text):
            fail(errors, f"{relative}: fixed model slug is not allowed")
        assignment = active_model_assignment.search(text)
        if assignment:
            fail(errors, f"{relative}: active fixed model assignment is not allowed ({assignment.group(1)!r})")
        if path.suffix.lower() == ".md":
            validate_local_links(path, text, errors)

    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}")
        return 1

    print("OpenBuild package validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
