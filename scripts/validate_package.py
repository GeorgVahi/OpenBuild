#!/usr/bin/env python3
"""Validate the public OpenBuild package without third-party dependencies."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "openbuild"
SKILL = PLUGIN / "skills" / "build"
BLINDSPOT_PROTOCOL = SKILL / "references" / "blindspot-protocol.md"
IMPLEMENTATION_DELEGATION = SKILL / "references" / "implementation-delegation.md"
REVIEW_PROTOCOL = SKILL / "references" / "review-protocol.md"
AGENT_RUNNER = SKILL / "scripts" / "agent_runner.py"
PACKAGED_SEARCH_PROFILE = SKILL / "profiles" / "openbuild_search_separate.toml"
PACKAGED_SEARCH_MODEL = "gpt-5.3-codex-spark"
PACKAGED_SEARCH_INSTRUCTIONS = (
    "You are the already-delegated read-only Explorer. Do not spawn or delegate to another agent.\n\n"
    "When code discovery, broad rg, route or symbol lookup, owner mapping, or cross-file evidence gathering is needed:\n"
    "- perform repository search, rg, rg --files, Get-Content, and local file reading yourself;\n"
    "- do not edit files, write configuration, make product or architecture decisions, commit, push, or answer the user;\n"
    "- return only a compact evidence map with path:line, symbol or route, a short snippet/signature, and why it matters;\n"
    "- include relevant negative results, confidence, and the search stop condition;\n"
    "- keep raw logs and large file dumps out of the result.\n\n"
    "The main process will do targeted reads only after your result, for verification before edits.\n"
)

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
    REVIEW_PROTOCOL,
    AGENT_RUNNER,
    PACKAGED_SEARCH_PROFILE,
    SKILL / "references" / "tdd-workflow.md",
    SKILL / "references" / "versioning.md",
    ROOT / "scripts" / "test_validate_package.py",
    ROOT / "scripts" / "test_agent_runner.py",
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
SEARCH_AGENT = "openbuild_search_separate"
SEARCH_DISPATCH_FAILURES = {
    "profile-not-discoverable",
    "profile-incomplete",
    "cli-unavailable",
    "chatgpt-auth-unavailable",
    "selector-unavailable",
    "model-unavailable",
    "quota-exhausted",
    "sandbox-mismatch",
    "runner-failed",
    "spawn-failed",
    "worker-timeout",
    "unusable-evidence",
}
EXACT_DISPATCH_METHODS = {
    "codex-exec-explicit-model",
    "per-spawn-model",
    "exact-custom-agent",
}
IMPLEMENTATION_AGENT_BY_RISK = {
    "low": ("fast", "openbuild_implementation_fast"),
    "medium": ("balanced", "openbuild_implementation_balanced"),
    "high": ("strongest", "openbuild_implementation_strongest"),
    "critical": ("strongest", "openbuild_implementation_strongest"),
}
REVIEW_AGENT_BY_TIER = {
    "fast": "openbuild_review_fast",
    "balanced": "openbuild_review_balanced",
    "strong": "openbuild_review_strong",
    "strongest": "openbuild_review_strongest",
}
REVIEW_START_BY_RISK = {
    "low": "fast",
    "medium": "balanced",
    "high": "strong",
    "critical": "strongest",
}
REVIEW_TIERS = tuple(REVIEW_AGENT_BY_TIER)
REVIEW_ESCALATION_REASONS = {
    "low-confidence",
    "incomplete-coverage",
    "conflicting-evidence",
    "validation-failure",
    "unresolved-high-impact-finding",
    "material-diff-change",
    "complexity-floor",
}
CANONICAL_AGENT_IDS = {
    "openbuild_search_fallback": "openbuild-search-fallback",
    "openbuild_implementation_fast": "openbuild-implementation-fast",
    "openbuild_implementation_balanced": "openbuild-implementation-balanced",
    "openbuild_implementation_strongest": "openbuild-implementation-strongest",
    "openbuild_review_fast": "openbuild-review-fast",
    "openbuild_review_balanced": "openbuild-review-balanced",
    "openbuild_review_strong": "openbuild-review-strong",
    "openbuild_review_strongest": "openbuild-review-strongest",
}
AGENT_NAME = re.compile(r"^[a-z0-9_]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MIGRATION_ENTRY_BINDING_FIELDS = (
    "scope",
    "source_path",
    "target_path",
    "root_fingerprint",
    "legacy_name",
    "target_name",
    "source_sha256",
    "target_sha256",
    "rendered_sha256",
    "exact_diff",
    "action",
)


def _canonical_sha256(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def migration_entry_id(entry: dict[str, object]) -> str:
    """Return the stable ID that binds one migration entry to its exact preview."""

    return _canonical_sha256({field: entry.get(field) for field in MIGRATION_ENTRY_BINDING_FIELDS})


def migration_supported_mappings() -> list[dict[str, str]]:
    """Return the complete legacy-to-canonical mapping in canonical order."""

    return [
        {"legacy_name": legacy, "target_name": canonical}
        for canonical, legacy in sorted(CANONICAL_AGENT_IDS.items())
    ]


def migration_plan_id(
    entries: list[dict[str, object]], detected_legacy_names: list[str]
) -> str:
    """Return the immutable ID for a complete detected-profile migration preview."""

    payload = {
        "supported_mappings": migration_supported_mappings(),
        "detected_legacy_names": sorted(detected_legacy_names),
        "entry_ids": sorted(str(entry.get("entry_id", "")) for entry in entries),
    }
    return _canonical_sha256(payload)


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


def _receipt_exit_code(receipt: dict[str, object]) -> int | None:
    value = receipt.get("codex_exit_code")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def explicit_success_evidence_is_valid(receipt: dict[str, object]) -> bool:
    return (
        receipt.get("codex_exit_evidence") == "valid"
        and _receipt_exit_code(receipt) == 0
        and receipt.get("result_evidence") == "valid"
    )


def explicit_failure_evidence_is_valid(receipt: dict[str, object]) -> bool:
    exit_evidence = receipt.get("codex_exit_evidence")
    result_evidence = receipt.get("result_evidence")
    exit_code = _receipt_exit_code(receipt)
    return (
        exit_evidence in {"missing", "malformed", "identity-mismatch"}
        or (exit_evidence == "valid" and exit_code is not None and exit_code != 0)
        or result_evidence in {"missing", "empty", "invalid"}
    )


def validate_explicit_terminal_evidence(
    receipt: dict[str, object], *, label: str
) -> list[str]:
    """Require complete, internally consistent runner evidence on every explicit terminal receipt."""

    if receipt.get("dispatch_method") != "codex-exec-explicit-model":
        return []
    errors: list[str] = []
    required = {"codex_exit_evidence", "codex_exit_code", "result_evidence"}
    missing = sorted(field for field in required if field not in receipt)
    if missing:
        return [f"{label}: explicit-model terminal receipt missing evidence fields {missing}"]
    exit_evidence = receipt.get("codex_exit_evidence")
    result_evidence = receipt.get("result_evidence")
    raw_exit_code = receipt.get("codex_exit_code")
    if exit_evidence not in {"valid", "missing", "malformed", "identity-mismatch"}:
        errors.append(f"{label}: explicit-model terminal receipt has invalid exit evidence state")
    if result_evidence not in {"valid", "missing", "empty", "invalid"}:
        errors.append(f"{label}: explicit-model terminal receipt has invalid result evidence state")
    if exit_evidence == "valid" and (
        isinstance(raw_exit_code, bool) or not isinstance(raw_exit_code, int)
    ):
        errors.append(f"{label}: valid exit evidence requires an integer Codex exit code")
    if exit_evidence in {"missing", "malformed", "identity-mismatch"} and (
        raw_exit_code is not None and raw_exit_code != "unknown"
    ):
        errors.append(
            f"{label}: non-valid exit evidence cannot carry a Codex exit code"
        )
    run_status = receipt.get("run_status")
    if run_status == "completed" and not explicit_success_evidence_is_valid(receipt):
        errors.append(f"{label}: completed receipt needs exit code zero and valid result evidence")
    if run_status == "failed" and not explicit_failure_evidence_is_valid(receipt):
        errors.append(
            f"{label}: failed receipt needs independent exit/result failure evidence"
        )
    return errors


def validate_prior_terminal_runner_failure(
    receipts: list[dict[str, object]],
    *,
    label: str,
    bindings: dict[str, object],
) -> list[str]:
    """Require a creation-bound stopped explicit-runner failure before native fallback."""

    errors: list[str] = []
    failures = [
        receipt
        for receipt in receipts
        if receipt.get("dispatch_method") == "codex-exec-explicit-model"
        and receipt.get("run_status") == "failed"
    ]
    if len(failures) != 1:
        return [f"{label}: native selection requires one prior terminal runner failure"]
    failure = failures[0]
    for field, expected in bindings.items():
        if failure.get(field) != expected:
            errors.append(f"{label}: prior runner failure changed route binding {field}")
    errors.extend(validate_explicit_terminal_evidence(failure, label=label))
    if (
        failure.get("dispatch_result") != "failed"
        or failure.get("fallback_reason") not in SEARCH_DISPATCH_FAILURES
        or failure.get("process_tree_stopped") is not True
    ):
        errors.append(
            f"{label}: prior terminal runner failure must be failed with an allowed reason and stopped process tree"
        )
    terminal_event = failure.get("terminal_event")
    if terminal_event not in {None, "none", "turn.failed", "turn.completed"}:
        errors.append(f"{label}: prior terminal runner failure has invalid terminal event")
    if terminal_event == "turn.completed" and not explicit_failure_evidence_is_valid(failure):
        errors.append(
            f"{label}: prior runner turn.completed needs independent exit/result failure evidence"
        )
    return errors


def validate_packaged_search_profile(profile: dict[str, object]) -> list[str]:
    """Lock the portable Spark profile and its discovery instruction exactly."""

    errors: list[str] = []
    expected = {
        "name": SEARCH_AGENT,
        "model": PACKAGED_SEARCH_MODEL,
        "model_reasoning_effort": "low",
        "sandbox_mode": "read-only",
    }
    for field, value in expected.items():
        if profile.get(field) != value:
            errors.append(f"openbuild_search_separate.toml: {field} must be {value!r}")
    if profile.get("developer_instructions") != PACKAGED_SEARCH_INSTRUCTIONS:
        errors.append(
            "openbuild_search_separate.toml: developer_instructions must match the exact canonical Explorer contract"
        )
    return errors


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
    """Validate start -> activation -> worker search -> terminal receipt -> evidence use."""

    errors: list[str] = []
    lookup_indices = [
        index for index, event in enumerate(events) if event.get("event") == "repository-search"
    ]
    if not lookup_indices:
        return ["search dispatch trace: missing repository-search event"]
    lookup_index = lookup_indices[0]
    dispatch_indices = [
        index
        for index, event in enumerate(events[:lookup_index])
        if event.get("event") == "search-dispatch"
    ]
    if not dispatch_indices:
        return ["search dispatch trace: exact agent dispatch must precede repository search"]
    dispatch_index = dispatch_indices[0]
    dispatch = events[dispatch_index]
    agent_name = dispatch.get("agent_name", "")
    task_name = dispatch.get("task_name", "")
    if agent_name != SEARCH_AGENT:
        errors.append(f"search dispatch trace: first dispatch agent_name must select exact agent {SEARCH_AGENT}")
    if not AGENT_NAME.fullmatch(agent_name):
        errors.append("search dispatch trace: agent_name must use the runtime-safe lowercase underscore grammar")
    if not task_name or task_name == agent_name:
        errors.append("search dispatch trace: task_name must be a separate non-profile task label")

    attempt_result = dispatch.get("result")
    attempt_reason = dispatch.get("fallback_reason", "")
    if attempt_result == "selected":
        if attempt_reason not in {"", "none"}:
            errors.append("search dispatch trace: selected route must not report a fallback reason")
    elif attempt_result == "failed":
        if attempt_reason not in SEARCH_DISPATCH_FAILURES:
            errors.append("search dispatch trace: failed dispatch must use an allowed fallback reason")
    else:
        errors.append("search dispatch trace: dispatch result must be selected or failed")

    receipt_fields = {
        "search_agent",
        "task_name",
        "dispatch_method",
        "configured_model",
        "model_reasoning_effort",
        "sandbox",
        "observed_agent",
        "observed_model",
        "terminal_event",
        "activated",
        "run_status",
        "pool",
        "dispatch_result",
        "fallback_reason",
        "process_tree_stopped",
        "run_dir",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
    }

    def validate_common_receipt(receipt: dict[str, str]) -> None:
        missing = sorted(field for field in receipt_fields if field not in receipt)
        if missing:
            errors.append(f"search dispatch trace: routing receipt missing fields {missing}")
        if receipt.get("search_agent") != SEARCH_AGENT:
            errors.append(f"search dispatch trace: routing receipt must name {SEARCH_AGENT}")
        if receipt.get("task_name") != task_name:
            errors.append("search dispatch trace: routing receipt task_name must match the separate task label")
        if receipt.get("dispatch_method") not in EXACT_DISPATCH_METHODS | {"unavailable"}:
            errors.append("search dispatch trace: routing receipt has invalid dispatch method")

    receipts = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("event") == "search-routing-receipt"
    ]
    consumption_events = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("event") == "search-evidence-consumed"
    ]
    prior_receipts = [(index, receipt) for index, receipt in receipts if dispatch_index < index < lookup_index]
    if not prior_receipts:
        errors.append("search dispatch trace: routing receipt must follow dispatch and precede repository search")
        return errors

    if attempt_result == "failed":
        receipt_index, receipt = prior_receipts[-1]
        validate_common_receipt(receipt)
        errors.extend(
            validate_explicit_terminal_evidence(receipt, label="search dispatch trace")
        )
        if (
            receipt.get("dispatch_method") == "codex-exec-explicit-model"
            and receipt.get("sandbox") != "read-only"
        ):
            errors.append("search dispatch trace: explicit search runner must be read-only")
        if receipt.get("run_status") != "failed" or receipt.get("dispatch_result") != "failed":
            errors.append("search dispatch trace: failed dispatch requires a terminal failed receipt")
        fallback_reason = receipt.get("fallback_reason", "")
        if fallback_reason not in SEARCH_DISPATCH_FAILURES or fallback_reason != attempt_reason:
            errors.append("search dispatch trace: failed receipt must preserve the allowed dispatch reason")
        terminal_event = receipt.get("terminal_event")
        if terminal_event not in {None, "none", "turn.failed", "turn.completed"}:
            errors.append("search dispatch trace: failed explicit-model receipt has invalid terminal event")
        if terminal_event == "turn.completed" and not explicit_failure_evidence_is_valid(receipt):
            errors.append("search dispatch trace: failed turn.completed needs independent exit/result failure evidence")
        if receipt.get("process_tree_stopped") is not True:
            errors.append("search dispatch trace: terminal failed receipt must confirm the process tree stopped")
        if consumption_events:
            errors.append("search dispatch trace: failed worker evidence cannot be consumed")
        if events[lookup_index].get("actor") == SEARCH_AGENT:
            errors.append("search dispatch trace: a failed initial dispatch cannot own the fallback search")
        if fallback_reason == "worker-timeout":
            confirmations = [
                event
                for event in events[dispatch_index + 1 : receipt_index]
                if event.get("event") == "agent-cancellation-confirmed"
            ]
            if not confirmations:
                errors.append("search dispatch trace: worker-timeout fallback requires cancellation confirmation")
            else:
                confirmation = confirmations[-1]
                if not confirmation.get("worker_pid"):
                    errors.append("search dispatch trace: cancellation confirmation requires a worker PID")
                if confirmation.get("codex_started") not in {True, False}:
                    errors.append("search dispatch trace: cancellation confirmation needs codex_started state")
                if confirmation.get("codex_started") is True and not confirmation.get("codex_pid"):
                    errors.append("search dispatch trace: started Codex process requires its PID")
                if confirmation.get("worker_stopped") is not True or confirmation.get("codex_stopped") is not True:
                    errors.append("search dispatch trace: cancellation confirmation must prove both processes stopped")
        return errors

    running_receipts = [
        (index, receipt)
        for index, receipt in prior_receipts
        if receipt.get("run_status") == "running"
    ]
    if not running_receipts:
        errors.append("search dispatch trace: selected worker needs an unactivated running receipt before search")
        return errors
    running_index, running = running_receipts[-1]
    validate_common_receipt(running)
    if running.get("dispatch_method") == "codex-exec-explicit-model":
        if (
            running.get("configured_model") != PACKAGED_SEARCH_MODEL
            or running.get("model_reasoning_effort") != "low"
        ):
            errors.append(
                "search dispatch trace: primary packaged runner must use fixed Spark model and low effort"
            )
    else:
        packaged_failures = [
            (index, receipt)
            for index, receipt in prior_receipts
            if index < running_index
            and receipt.get("dispatch_method") == "codex-exec-explicit-model"
            and receipt.get("configured_model") == PACKAGED_SEARCH_MODEL
            and receipt.get("model_reasoning_effort") == "low"
            and receipt.get("run_status") == "failed"
        ]
        if not packaged_failures:
            errors.append(
                "search dispatch trace: native selected search requires a prior terminal packaged runner failure"
            )
        else:
            _, packaged_failure = packaged_failures[-1]
            validate_common_receipt(packaged_failure)
            errors.extend(
                validate_explicit_terminal_evidence(
                    packaged_failure,
                    label="search dispatch trace packaged runner",
                )
            )
            if (
                packaged_failure.get("dispatch_result") != "failed"
                or packaged_failure.get("fallback_reason") not in SEARCH_DISPATCH_FAILURES
                or packaged_failure.get("process_tree_stopped") is not True
            ):
                errors.append(
                    "search dispatch trace: native selection requires a stopped terminal packaged runner failure"
                )
            terminal_event = packaged_failure.get("terminal_event")
            if terminal_event not in {None, "none", "turn.failed", "turn.completed"}:
                errors.append(
                    "search dispatch trace: packaged runner failure has invalid terminal event"
                )
            if (
                terminal_event == "turn.completed"
                and not explicit_failure_evidence_is_valid(packaged_failure)
            ):
                errors.append(
                    "search dispatch trace: packaged runner turn.completed needs independent failure evidence"
                )
            if packaged_failure.get("sandbox") != "read-only":
                errors.append("search dispatch trace: packaged runner failure must preserve read-only sandbox")
        if running.get("dispatch_method") == "per-spawn-model" and (
            running.get("configured_model") in {None, "", "unknown", "unobservable"}
            or running.get("model_reasoning_effort") in {None, "", "unknown", "unobservable"}
        ):
            errors.append(
                "search dispatch trace: per-spawn native fallback requires direct model and reasoning effort"
            )
    if running.get("dispatch_result") != "selected" or running.get("fallback_reason") not in {"", "none"}:
        errors.append("search dispatch trace: running receipt must preserve selected routing")
    if running.get("activated") is not False or running.get("terminal_event") not in {None, "none"}:
        errors.append("search dispatch trace: pre-search receipt must be unactivated and non-terminal")
    if running.get("process_tree_stopped") is not False:
        errors.append("search dispatch trace: running receipt cannot claim a stopped process tree")
    if running.get("pool") != "separate":
        errors.append("search dispatch trace: selected exact agent must record the confirmed separate pool")
    if running.get("sandbox") != "read-only":
        errors.append("search dispatch trace: selected search worker must be read-only")
    for field in ("run_dir", "worker_pid", "worker_process_identity", "codex_pid", "codex_process_identity"):
        if not running.get(field):
            errors.append(f"search dispatch trace: running receipt requires {field}")

    prelookup_failures = [
        (index, receipt)
        for index, receipt in prior_receipts
        if index > running_index and receipt.get("run_status") == "failed"
    ]
    if prelookup_failures:
        terminal_index, terminal = prelookup_failures[-1]
        validate_common_receipt(terminal)
        errors.extend(
            validate_explicit_terminal_evidence(terminal, label="search dispatch trace")
        )
        for field in (
            "search_agent",
            "task_name",
            "dispatch_method",
            "configured_model",
            "model_reasoning_effort",
            "run_dir",
            "worker_pid",
            "worker_process_identity",
            "codex_pid",
            "codex_process_identity",
        ):
            if terminal.get(field) != running.get(field):
                errors.append(f"search dispatch trace: failed terminal receipt changed routing field {field}")
        fallback_reason = terminal.get("fallback_reason", "")
        if terminal.get("dispatch_result") != "failed" or fallback_reason not in SEARCH_DISPATCH_FAILURES:
            errors.append("search dispatch trace: failed terminal receipt needs an allowed fallback reason")
        if terminal.get("process_tree_stopped") is not True:
            errors.append("search dispatch trace: failed terminal receipt must confirm stopped process tree")
        terminal_event = terminal.get("terminal_event")
        if terminal_event not in {None, "none", "turn.failed", "turn.completed"}:
            errors.append("search dispatch trace: failed terminal receipt has invalid terminal event")
        if terminal_event == "turn.completed" and not explicit_failure_evidence_is_valid(terminal):
            errors.append("search dispatch trace: failed turn.completed needs independent exit/result failure evidence")
        if terminal.get("activated") is True:
            activations = [
                event
                for event in events[running_index + 1 : terminal_index]
                if event.get("event") == "search-agent-activated"
            ]
            if len(activations) != 1:
                errors.append("search dispatch trace: activated failed worker needs one matching activation event")
        if events[lookup_index].get("actor") == SEARCH_AGENT:
            errors.append("search dispatch trace: failed worker cannot own the fallback repository search")
        if consumption_events:
            errors.append("search dispatch trace: failed worker evidence cannot be consumed")
        if fallback_reason == "worker-timeout":
            confirmations = [
                event
                for event in events[running_index + 1 : terminal_index]
                if event.get("event") == "agent-cancellation-confirmed"
            ]
            if not confirmations:
                errors.append("search dispatch trace: worker-timeout fallback requires cancellation confirmation")
            else:
                confirmation = confirmations[-1]
                if confirmation.get("worker_stopped") is not True or confirmation.get("codex_stopped") is not True:
                    errors.append("search dispatch trace: cancellation confirmation must prove both processes stopped")
        return errors

    activations = [
        event
        for event in events[running_index + 1 : lookup_index]
        if event.get("event") == "search-agent-activated"
    ]
    if len(activations) != 1:
        errors.append("search dispatch trace: exactly one matching activation must precede worker search")
    else:
        activation = activations[0]
        bindings = {
            "search_agent": SEARCH_AGENT,
            "task_name": task_name,
            "run_dir": running.get("run_dir"),
            "worker_process_identity": running.get("worker_process_identity"),
            "codex_process_identity": running.get("codex_process_identity"),
        }
        for field, expected in bindings.items():
            if activation.get(field) != expected:
                errors.append(f"search dispatch trace: activation changed {field}")
        if activation.get("activated") is not True:
            errors.append("search dispatch trace: activation event must confirm activated true")
    if events[lookup_index].get("actor") != SEARCH_AGENT:
        errors.append("search dispatch trace: selected exact agent must own the first repository search")

    terminal_receipts = [
        (index, receipt)
        for index, receipt in receipts
        if index > lookup_index and receipt.get("run_status") in {"completed", "failed"}
    ]
    if not terminal_receipts:
        errors.append("search dispatch trace: terminal routing receipt must follow worker search")
        return errors
    terminal_index, terminal = terminal_receipts[0]
    worker_searches = [
        event
        for event in events[lookup_index:terminal_index]
        if event.get("event") == "repository-search"
    ]
    if any(event.get("actor") != SEARCH_AGENT for event in worker_searches):
        errors.append(
            "search dispatch trace: every repository search before the selected worker terminal receipt "
            f"must remain owned by {SEARCH_AGENT}"
        )
    if any(
        event.get("event") == "repository-search" and event.get("actor") == SEARCH_AGENT
        for event in events[terminal_index + 1 :]
    ):
        errors.append(
            "search dispatch trace: selected worker cannot perform repository search after its terminal receipt"
        )
    validate_common_receipt(terminal)
    errors.extend(validate_explicit_terminal_evidence(terminal, label="search dispatch trace"))
    for field in (
        "search_agent",
        "task_name",
        "dispatch_method",
        "configured_model",
        "model_reasoning_effort",
        "sandbox",
        "pool",
        "run_dir",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
    ):
        if terminal.get(field) != running.get(field):
            errors.append(f"search dispatch trace: terminal receipt changed routing field {field}")
    if terminal.get("activated") is not True or terminal.get("process_tree_stopped") is not True:
        errors.append("search dispatch trace: terminal receipt must confirm activation and stopped process tree")

    run_status = terminal.get("run_status")
    if run_status == "completed":
        if terminal.get("dispatch_result") != "selected" or terminal.get("fallback_reason") not in {"", "none"}:
            errors.append("search dispatch trace: completed terminal receipt is inconsistent")
        if terminal.get("terminal_event") != "turn.completed":
            errors.append("search dispatch trace: completed explicit-model receipt requires turn.completed")
        if not explicit_success_evidence_is_valid(terminal):
            errors.append("search dispatch trace: completed receipt needs exit code zero and valid result evidence")
        if len(consumption_events) != 1:
            errors.append(
                "search dispatch trace: completed worker needs exactly one run-bound search evidence consumption"
            )
        else:
            consumption_index, consumption = consumption_events[0]
            if (
                consumption.get("actor") != "root"
                or consumption.get("search_agent") != SEARCH_AGENT
                or consumption.get("run_dir") != terminal.get("run_dir")
            ):
                errors.append(
                    "search dispatch trace: completed worker needs exactly one run-bound search evidence consumption"
                )
            elif consumption_index <= terminal_index:
                errors.append("search dispatch trace: terminal receipt must precede search evidence consumption")
    else:
        if terminal.get("dispatch_result") != "failed" or terminal.get("fallback_reason") not in SEARCH_DISPATCH_FAILURES:
            errors.append("search dispatch trace: failed terminal receipt needs an allowed fallback reason")
        terminal_event = terminal.get("terminal_event")
        if terminal_event not in {None, "none", "turn.failed", "turn.completed"}:
            errors.append("search dispatch trace: failed terminal receipt has invalid terminal event")
        if terminal_event == "turn.completed" and not explicit_failure_evidence_is_valid(terminal):
            errors.append("search dispatch trace: failed turn.completed needs independent exit/result failure evidence")
        if consumption_events:
            errors.append("search dispatch trace: failed worker evidence cannot be consumed")
        if terminal.get("fallback_reason") == "worker-timeout":
            confirmations = [
                event
                for event in events[running_index + 1 : terminal_index]
                if event.get("event") == "agent-cancellation-confirmed"
            ]
            if not confirmations or confirmations[-1].get("worker_stopped") is not True or confirmations[-1].get("codex_stopped") is not True:
                errors.append("search dispatch trace: worker-timeout fallback requires stopped-process confirmation")

    return errors


def validate_profile_migration_trace(events: list[dict[str, object]]) -> list[str]:
    """Validate the guided legacy-profile migration plan and per-entry receipts."""

    errors: list[str] = []
    preview_indices = [
        index for index, event in enumerate(events) if event.get("event") == "profile-migration-preview"
    ]
    previews = [events[index] for index in preview_indices]
    if not previews:
        return ["profile migration trace: missing migration preview"]
    if len(previews) != 1:
        errors.append("profile migration trace: exactly one immutable preview is allowed")
    preview = previews[0]
    preview_index = preview_indices[0]

    plan_id = preview.get("plan_id")
    entries = preview.get("entries")
    detected_legacy_names = preview.get("detected_legacy_names")
    if preview.get("supported_mappings") != migration_supported_mappings():
        errors.append(
            "profile migration trace: preview must carry the complete supported legacy mapping"
        )
    if not isinstance(entries, list):
        return errors + ["profile migration trace: preview entries must be a list"]
    if not isinstance(detected_legacy_names, list) or not all(
        isinstance(value, str) for value in detected_legacy_names
    ):
        return errors + [
            "profile migration trace: preview requires the complete detected legacy inventory"
        ]
    if len(detected_legacy_names) != len(set(detected_legacy_names)):
        errors.append("profile migration trace: detected legacy inventory contains duplicates")
    unknown_detected = sorted(set(detected_legacy_names) - set(CANONICAL_AGENT_IDS.values()))
    if unknown_detected:
        errors.append(
            f"profile migration trace: detected legacy inventory contains unknown names {unknown_detected}"
        )

    entries_by_id: dict[str, dict[str, object]] = {}
    targets: set[str] = set()
    represented_legacy_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("profile migration trace: every preview entry must be an object")
            continue
        entry_id = entry.get("entry_id")
        legacy_name = entry.get("legacy_name")
        target_name = entry.get("target_name")
        source_sha256 = entry.get("source_sha256")
        target_sha256 = entry.get("target_sha256")
        rendered_sha256 = entry.get("rendered_sha256")
        action = entry.get("action")
        if not isinstance(entry_id, str) or entry_id in entries_by_id:
            errors.append("profile migration trace: every entry needs a unique stable entry_id")
            continue
        if entry_id != migration_entry_id(entry):
            errors.append(
                f"profile migration trace: {entry_id or '<missing>'} entry_id must bind the canonical entry SHA-256"
            )
        entries_by_id[entry_id] = entry
        if target_name not in CANONICAL_AGENT_IDS:
            errors.append(f"profile migration trace: {entry_id} has an unknown canonical target")
        elif legacy_name != CANONICAL_AGENT_IDS[target_name]:
            errors.append(f"profile migration trace: {entry_id} legacy/canonical mapping is invalid")
        if isinstance(legacy_name, str):
            represented_legacy_names.add(legacy_name)
        if not isinstance(target_name, str) or not AGENT_NAME.fullmatch(target_name):
            errors.append(f"profile migration trace: {entry_id} target must use underscore grammar")
        if isinstance(target_name, str):
            if target_name in targets:
                errors.append(f"profile migration trace: duplicate target {target_name}")
            targets.add(target_name)
        if not isinstance(source_sha256, str) or not SHA256.fullmatch(source_sha256):
            errors.append(f"profile migration trace: {entry_id} needs a source SHA-256 precondition")
        if target_sha256 != "absent" and (
            not isinstance(target_sha256, str) or not SHA256.fullmatch(target_sha256)
        ):
            errors.append(f"profile migration trace: {entry_id} needs target SHA-256 or absent")
        if not isinstance(rendered_sha256, str) or not SHA256.fullmatch(rendered_sha256):
            errors.append(f"profile migration trace: {entry_id} needs the rendered canonical SHA-256")
        scope = entry.get("scope")
        if scope not in {"user", "project"}:
            errors.append(f"profile migration trace: {entry_id} needs user or project scope")
        root_fingerprint = entry.get("root_fingerprint")
        if not isinstance(root_fingerprint, str) or not SHA256.fullmatch(root_fingerprint):
            errors.append(f"profile migration trace: {entry_id} needs a trusted root fingerprint")
        for field, expected_stem in (
            ("source_path", legacy_name),
            ("target_path", target_name),
        ):
            relative_path = entry.get(field)
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or Path(relative_path).is_absolute()
                or ".." in Path(relative_path).parts
                or not isinstance(expected_stem, str)
                or Path(relative_path).name != f"{expected_stem}.toml"
            ):
                errors.append(
                    f"profile migration trace: {entry_id} {field} must be a scope-relative profile path"
                )
        exact_diff = entry.get("exact_diff")
        if (
            not isinstance(exact_diff, str)
            or not exact_diff
            or not isinstance(legacy_name, str)
            or not isinstance(target_name, str)
            or legacy_name not in exact_diff
            or target_name not in exact_diff
        ):
            errors.append(f"profile migration trace: {entry_id} needs the complete exact TOML diff")
        if action not in {"create-if-absent", "already-migrated", "config-conflict"}:
            errors.append(f"profile migration trace: {entry_id} has an invalid action")
        elif action == "create-if-absent" and target_sha256 != "absent":
            errors.append(f"profile migration trace: {entry_id} create-if-absent requires an absent target")
        elif action == "already-migrated" and target_sha256 != rendered_sha256:
            errors.append(f"profile migration trace: {entry_id} already-migrated requires the rendered hash")
        elif action == "config-conflict" and target_sha256 in {"absent", rendered_sha256}:
            errors.append(f"profile migration trace: {entry_id} config-conflict requires a divergent target hash")

    if represented_legacy_names != set(detected_legacy_names):
        errors.append(
            "profile migration trace: entries must cover the complete detected legacy inventory"
        )
    expected_plan_id = migration_plan_id(
        [entry for entry in entries if isinstance(entry, dict)], detected_legacy_names
    )
    if not isinstance(plan_id, str) or plan_id != expected_plan_id:
        errors.append("profile migration trace: plan_id must equal the canonical preview SHA-256")

    approval_fields = (
        "entry_id",
        "source_sha256",
        "target_sha256",
        "rendered_sha256",
        "action",
    )
    approvals: dict[str, dict[str, object]] = {}
    approval_indices: dict[str, int] = {}
    receipts: dict[str, dict[str, object]] = {}
    receipt_indices: dict[str, int] = {}
    for event_index, event in enumerate(events):
        if event.get("plan_id") != plan_id:
            if event.get("event") in {"profile-migration-approval", "profile-migration-receipt"}:
                errors.append("profile migration trace: approval/receipt plan_id must match preview")
            continue
        if event.get("event") == "profile-migration-approval":
            if event_index <= preview_index:
                errors.append(
                    "profile migration trace: authority must follow the displayed preview"
                )
                continue
            approved_entries = event.get("entries")
            if not isinstance(approved_entries, list) or not all(
                isinstance(value, dict) for value in approved_entries
            ):
                errors.append(
                    "profile migration trace: approval must bind per-entry authority to exact precondition hashes"
                )
                continue
            for approved in approved_entries:
                entry_id = approved.get("entry_id")
                if not isinstance(entry_id, str) or entry_id not in entries_by_id:
                    errors.append("profile migration trace: approval references an unknown entry_id")
                    continue
                expected = {
                    field: entries_by_id[entry_id].get(field) for field in approval_fields
                }
                actual = {field: approved.get(field) for field in approval_fields}
                if actual != expected:
                    errors.append(
                        f"profile migration trace: {entry_id} approval must bind exact precondition hashes and action"
                    )
                    continue
                if entry_id in approvals:
                    errors.append(f"profile migration trace: {entry_id} has duplicate authority records")
                approvals[entry_id] = approved
                approval_indices[entry_id] = event_index
        elif event.get("event") == "profile-migration-receipt":
            if event_index <= preview_index:
                errors.append("profile migration trace: receipt must follow the displayed preview")
                continue
            entry_id = event.get("entry_id")
            status = event.get("status")
            if not isinstance(entry_id, str) or entry_id not in entries_by_id:
                errors.append("profile migration trace: receipt references an unknown entry_id")
                continue
            if status not in {"created", "already-migrated", "config-conflict", "hash-drift"}:
                errors.append(f"profile migration trace: {entry_id} has an invalid receipt status")
                continue
            if entry_id in receipts:
                errors.append(f"profile migration trace: {entry_id} has duplicate receipts")
            observed_source = event.get("observed_source_sha256")
            observed_target = event.get("observed_target_sha256")
            result_sha256 = event.get("result_sha256")
            if not all(
                value == "absent" or (isinstance(value, str) and SHA256.fullmatch(value))
                for value in (observed_source, observed_target)
            ):
                errors.append(
                    f"profile migration trace: {entry_id} receipt needs observed precondition hashes"
                )
            if result_sha256 != "not-written" and (
                not isinstance(result_sha256, str) or not SHA256.fullmatch(result_sha256)
            ):
                errors.append(f"profile migration trace: {entry_id} receipt needs a result hash")
            receipts[entry_id] = event
            receipt_indices[entry_id] = event_index

    for entry_id, entry in entries_by_id.items():
        action = entry.get("action")
        receipt = receipts.get(entry_id)
        status = receipt.get("status") if receipt else None
        observed_source = receipt.get("observed_source_sha256") if receipt else None
        observed_target = receipt.get("observed_target_sha256") if receipt else None
        result_sha256 = receipt.get("result_sha256") if receipt else None
        preconditions_match = (
            observed_source == entry.get("source_sha256")
            and observed_target == entry.get("target_sha256")
        )
        if status == "created" and action != "create-if-absent":
            errors.append(f"profile migration trace: {entry_id} created status contradicts preview action")
        if action == "create-if-absent" and status not in {"created", "hash-drift"}:
            errors.append(f"profile migration trace: {entry_id} create-if-absent receipt contradicts preview")
        if status == "created":
            if entry_id not in approvals:
                errors.append(f"profile migration trace: {entry_id} was created without per-entry authority")
            elif approval_indices[entry_id] >= receipt_indices[entry_id]:
                errors.append(f"profile migration trace: {entry_id} was created before per-entry authority")
            if not preconditions_match:
                errors.append(f"profile migration trace: {entry_id} was created after hash drift")
            if result_sha256 != entry.get("rendered_sha256"):
                errors.append(f"profile migration trace: {entry_id} created result must match rendered hash")
        if action == "already-migrated" and status not in {"already-migrated", "hash-drift"}:
            errors.append(f"profile migration trace: {entry_id} already-migrated receipt contradicts preview")
        if action == "config-conflict" and status not in {"config-conflict", "hash-drift"}:
            errors.append(f"profile migration trace: {entry_id} overwrote a divergent target")
        if status == "already-migrated" and (
            not preconditions_match or result_sha256 != entry.get("rendered_sha256")
        ):
            errors.append(f"profile migration trace: {entry_id} already-migrated hashes are inconsistent")
        if status == "config-conflict" and (
            not preconditions_match or result_sha256 != entry.get("target_sha256")
        ):
            errors.append(f"profile migration trace: {entry_id} conflict must preserve the target hash")
        if status == "hash-drift" and (preconditions_match or result_sha256 != "not-written"):
            errors.append(f"profile migration trace: {entry_id} hash-drift must record no write")
        if status is None:
            errors.append(f"profile migration trace: {entry_id} is missing a resumable receipt")

    return errors


def validate_decision_authority_trace(events: list[dict[str, str]]) -> list[str]:
    """Validate that product-impacting specification edits remain user-authorized."""

    errors: list[str] = []
    product_impact_axes = {
        "acceptance",
        "accessibility",
        "age",
        "audience",
        "availability",
        "behavior",
        "billing",
        "capacity",
        "compatibility",
        "compliance",
        "cost",
        "data",
        "economy",
        "eligibility",
        "geography",
        "legal",
        "localization",
        "lock-in",
        "migration",
        "moderation",
        "monetization",
        "non-goal",
        "offline",
        "operations",
        "performance",
        "permissions",
        "platform",
        "pricing",
        "priority",
        "privacy",
        "product-behavior",
        "reliability",
        "responsive",
        "retention",
        "rewards",
        "rollout",
        "safety",
        "scope",
        "security",
        "support",
        "user-flow",
        "ux",
    }
    non_product_impacts = {"authority", "outcome-neutral", "repository-fact"}
    canonical_impacts = product_impact_axes | non_product_impacts
    dispositions = {"new-authority", "product-decision", "repository-fact", "technical-decision"}

    sources: dict[str, dict[str, str]] = {}
    source_links: dict[str, set[str]] = {}
    source_decision_ids: dict[str, set[str]] = {}
    invalid_sources: set[str] = set()
    source_map_seen = False
    source_map_complete = False
    unreconciled_sources: set[str] = set()
    locked_decisions: set[str] = set()
    decision_sources: dict[str, str] = {}
    selected_outcomes: dict[str, str] = {}
    product_decisions: set[str] = set()
    reopened_decisions: set[str] = set()
    presented_questions: set[str] = set()
    user_decision_index: dict[str, int] = {}
    technical_gap_ids: set[str] = set()
    technical_decision_ids: set[str] = set()
    decision_versions: dict[str, int] = {}
    decision_target_history: dict[str, set[tuple[str, str]]] = {}
    pre_reopen_outcomes: dict[str, str] = {}
    reapplications_required: dict[str, set[tuple[str, str]]] = {}
    normative_writes: list[tuple[str, str, str, int, str, str, int]] = []
    applications: dict[tuple[str, str, str], int] = {}
    application_versions: dict[tuple[str, str, str], int] = {}
    last_application_receipt: int | None = None
    final_receipt: dict[str, str] | None = None

    for index, event in enumerate(events):
        kind = event.get("event")
        if kind == "spec-source":
            required = {
                "path",
                "authority",
                "revision",
                "normative_scope",
                "decision_ids",
                "normative_links",
                "link_evidence",
                "editable",
                "reconciliation",
            }
            missing = sorted(field for field in required if not event.get(field))
            if missing:
                errors.append(f"decision authority trace: specification source missing fields {missing}")
            path = event.get("path", "")
            source_invalid = bool(missing)
            if path in sources:
                errors.append(f"decision authority trace: duplicate specification source {path}")
                source_invalid = True
            if event.get("editable") not in {"yes", "no", "unknown"}:
                errors.append("decision authority trace: source editability must be yes, no, or unknown")
                source_invalid = True
            reconciliation = event.get("reconciliation", "")
            if reconciliation not in {"aligned", "conflict", "deferred", "gap"}:
                errors.append("decision authority trace: source reconciliation has an invalid state")
                source_invalid = True
            if reconciliation == "deferred":
                errors.append(
                    "decision authority trace: an initial deferred source requires post-map user-decision reconciliation"
                )
                source_invalid = True
            raw_decision_ids = event.get("decision_ids", "")
            declared_decisions = (
                set()
                if raw_decision_ids == "none"
                else {value.strip() for value in raw_decision_ids.split(",") if value.strip()}
            )
            if not raw_decision_ids or "none" in declared_decisions or any(
                not value.startswith(("D-", "T-")) for value in declared_decisions
            ):
                errors.append("decision authority trace: source decision IDs must be stable D-###/T-### IDs or none")
                source_invalid = True
            raw_links = event.get("normative_links", "")
            links = (
                set()
                if raw_links == "none"
                else {value.strip() for value in raw_links.split(",") if value.strip()}
            )
            if not raw_links or "none" in links:
                errors.append("decision authority trace: source normative links must be mapped paths or none")
                source_invalid = True
            if path:
                sources[path] = event
                source_links[path] = links
                source_decision_ids[path] = declared_decisions
                if source_invalid:
                    invalid_sources.add(path)
                if reconciliation in {"conflict", "gap", "deferred"}:
                    unreconciled_sources.add(path)
            if source_map_seen:
                source_map_complete = False

        elif kind == "spec-source-map":
            source_map_seen = True
            required = {"root", "source_count", "complete"}
            missing = sorted(field for field in required if not event.get(field))
            if missing:
                errors.append(f"decision authority trace: source map missing fields {missing}")
            try:
                source_count = int(event.get("source_count", ""))
            except ValueError:
                source_count = -1
                errors.append("decision authority trace: source map count must be an integer")
            if not sources:
                errors.append("decision authority trace: source map cannot be complete without structured sources")
            if event.get("root") not in sources:
                errors.append("decision authority trace: source map root must reference a structured source")
            if source_count != len(sources):
                errors.append("decision authority trace: source map count does not match structured sources")
            if event.get("complete") not in {"true", "false"}:
                errors.append("decision authority trace: source map complete must be true or false")
            declared_links = set().union(*source_links.values()) if source_links else set()
            unmapped_links = sorted(declared_links - set(sources))
            if unmapped_links:
                errors.append(f"decision authority trace: source graph has unmapped normative links {unmapped_links}")
            root = event.get("root", "")
            reachable: set[str] = set()
            pending = [root] if root in sources else []
            while pending:
                current = pending.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                pending.extend(link for link in source_links.get(current, set()) if link in sources)
            unreachable_sources = sorted(set(sources) - reachable)
            if unreachable_sources:
                errors.append(
                    f"decision authority trace: source graph has unreachable specification sources {unreachable_sources}"
                )
            source_map_complete = (
                event.get("complete") == "true"
                and not missing
                and bool(sources)
                and event.get("root") in sources
                and source_count == len(sources)
                and not invalid_sources
                and not unmapped_links
                and not unreachable_sources
            )

        elif kind == "spec-source-reconciled":
            path = event.get("path", "")
            state = event.get("reconciliation", "")
            original_state = sources.get(path, {}).get("reconciliation")
            if (
                path not in sources
                or original_state not in {"conflict", "gap"}
                or state not in {"aligned", "deferred"}
                or not event.get("evidence")
            ):
                errors.append("decision authority trace: source reconciliation requires a mapped source and evidence")
            else:
                resolution_basis = event.get("resolution_basis", "")
                decision_id = event.get("decision_id", "")
                user_resolved = (
                    resolution_basis == "user-decision"
                    and decision_id.startswith("D-")
                    and decision_id in locked_decisions
                    and decision_id not in reopened_decisions
                    and user_decision_index.get(decision_id, len(events)) < index
                    and event.get("answer_source") == decision_sources.get(decision_id)
                    and event.get("selected_outcome") == selected_outcomes.get(decision_id)
                )
                expected_record_type = {
                    "explicit-precedence": "precedence",
                    "explicit-supersession": "supersession",
                }.get(resolution_basis)
                authority_source = event.get("authority_source", "")
                authority_line = event.get("authority_record_line", "")
                explicit_authority = bool(
                    expected_record_type
                    and authority_source in sources
                    and event.get("authority_record_type") == expected_record_type
                    and event.get("authority_record_target") == path
                    and event.get("authority_record_revision") == sources.get(authority_source, {}).get("revision")
                    and authority_line.isdigit()
                    and int(authority_line) > 0
                    and event.get("evidence", "").startswith(f"{authority_source}:{authority_line}")
                )
                if expected_record_type and not explicit_authority:
                    errors.append(
                        "decision authority trace: explicit precedence/supersession requires a structured authority record"
                    )
                verified_gap = (
                    original_state == "gap"
                    and resolution_basis == "verified-evidence"
                    and authority_source in sources
                    and event.get("authority_record_target") == path
                    and event.get("authority_record_revision") == sources.get(authority_source, {}).get("revision")
                    and authority_line.isdigit()
                    and int(authority_line) > 0
                )
                valid_resolution = user_resolved or explicit_authority or verified_gap
                if original_state == "conflict" and not (user_resolved or explicit_authority):
                    errors.append(
                        "decision authority trace: conflict resolution requires a user decision or explicit precedence/supersession record"
                    )
                    valid_resolution = False
                if state == "deferred" and not user_resolved:
                    errors.append("decision authority trace: deferred source requires a matching user decision")
                    valid_resolution = False
                if not valid_resolution:
                    if original_state != "conflict":
                        errors.append(
                            "decision authority trace: source reconciliation requires structured authority provenance"
                        )
                else:
                    sources[path]["reconciliation"] = state
                    unreconciled_sources.discard(path)

        elif kind == "locked-decision":
            decision_id = event.get("decision_id", "")
            source = event.get("source", "")
            if (
                event.get("status") == "resolved"
                and decision_id.startswith("D-")
                and decision_id not in reopened_decisions
                and source in sources
                and decision_id in source_decision_ids.get(source, set())
                and event.get("selected_outcome")
            ):
                locked_decisions.add(decision_id)
                decision_sources[decision_id] = source
                selected_outcomes[decision_id] = event["selected_outcome"]
                decision_versions[decision_id] = decision_versions.get(decision_id, 0) + 1
            else:
                if source in sources and decision_id.startswith("D-") and decision_id not in source_decision_ids.get(source, set()):
                    errors.append(
                        f"decision authority trace: {decision_id} is not declared by provenance source {source}"
                    )
                errors.append(
                    "decision authority trace: locked decision must be a non-reopened resolved D-### with mapped provenance and outcome"
                )

        elif kind == "gap-classified":
            gap_id = event.get("gap_id", "")
            decision_id = event.get("decision_id", "")
            disposition = event.get("disposition", "")
            impacts = {value.strip() for value in event.get("impact", "").split(",") if value.strip()}
            if not gap_id.startswith("B-"):
                errors.append("decision authority trace: every classified gap requires a stable B-###")
            if disposition not in dispositions:
                errors.append("decision authority trace: gap disposition is invalid")
            unknown_impacts = sorted(impacts - canonical_impacts)
            if not impacts or unknown_impacts:
                errors.append(
                    f"decision authority trace: gap impact must use the closed canonical schema; unknown {unknown_impacts}"
                )
            has_product_impact = bool(impacts & product_impact_axes)
            if has_product_impact:
                product_decisions.add(decision_id)
                if disposition not in {"product-decision", "new-authority"}:
                    errors.append(
                        "decision authority trace: product-impacting gap cannot be relabelled as a technical decision"
                    )
                if not decision_id.startswith("D-"):
                    errors.append("decision authority trace: product-impacting gap requires a stable D-###")
            elif disposition == "technical-decision":
                if impacts != {"outcome-neutral"} or not decision_id.startswith("T-"):
                    errors.append(
                        "decision authority trace: technical gap requires T-### and outcome-neutral impact"
                    )
                technical_gap_ids.add(decision_id)
            elif disposition == "product-decision":
                errors.append("decision authority trace: product decision requires a canonical product impact")
            elif disposition == "repository-fact" and impacts != {"repository-fact"}:
                errors.append("decision authority trace: repository fact requires repository-fact impact")
            elif disposition == "new-authority":
                if impacts != {"authority"} and not has_product_impact:
                    errors.append("decision authority trace: new authority requires authority or product impact")
                if not decision_id.startswith("D-"):
                    errors.append("decision authority trace: new authority requires a stable D-###")
                product_decisions.add(decision_id)

        elif kind == "decision-reopened":
            decision_id = event.get("decision_id", "")
            if (
                decision_id not in locked_decisions
                and decision_id not in user_decision_index
            ) or not event.get("evidence") or not event.get("changed_consequence"):
                errors.append("decision authority trace: reopening requires a resolved D-### and changed evidence")
            pre_reopen_outcomes[decision_id] = selected_outcomes.get(decision_id, "")
            prior_targets = decision_target_history.get(decision_id, set())
            if prior_targets:
                reapplications_required[decision_id] = set(prior_targets)
            locked_decisions.discard(decision_id)
            user_decision_index.pop(decision_id, None)
            decision_sources.pop(decision_id, None)
            selected_outcomes.pop(decision_id, None)
            decision_versions[decision_id] = decision_versions.get(decision_id, 0) + 1
            presented_questions.discard(decision_id)
            product_decisions.add(decision_id)
            reopened_decisions.add(decision_id)
            if any(write[0] == decision_id for write in normative_writes):
                normative_writes = [write for write in normative_writes if write[0] != decision_id]
                applications = {key: value for key, value in applications.items() if key[0] != decision_id}
                application_versions = {
                    key: value for key, value in application_versions.items() if key[0] != decision_id
                }
                last_application_receipt = None
                final_receipt = None

        elif kind == "technical-decision":
            decision_id = event.get("decision_id", "")
            if not decision_id.startswith("T-"):
                errors.append("decision authority trace: technical decision requires a stable T-###")
            if (
                event.get("preserves_locked_outcomes") != "true"
                or event.get("normative_effect") != "false"
                or not event.get("preservation_evidence")
            ):
                errors.append(
                    "decision authority trace: technical decision must preserve locked outcomes and have no normative effect"
                )
            technical_decision_ids.add(decision_id)

        elif kind == "question-presented":
            if not source_map_complete:
                errors.append("decision authority trace: complete source map must precede a decision packet")
            required = {
                "decision_id",
                "current_state",
                "options",
                "consequences",
                "risks",
                "recommendation",
                "affected_scope",
            }
            missing = sorted(field for field in required if not event.get(field))
            if missing:
                errors.append(f"decision authority trace: decision packet missing fields {missing}")
            decision_id = event.get("decision_id", "")
            if not decision_id.startswith("D-"):
                errors.append("decision authority trace: decision packet requires a stable D-###")
            else:
                presented_questions.add(decision_id)
                product_decisions.add(decision_id)

        elif kind == "user-decision":
            decision_id = event.get("decision_id", "")
            if (
                not decision_id.startswith("D-")
                or not event.get("selection")
                or not event.get("source")
            ):
                errors.append("decision authority trace: user decision requires D-###, selection, and answer source")
            else:
                if decision_id in locked_decisions and decision_id not in reopened_decisions:
                    errors.append(
                        "decision authority trace: a user answer cannot replace a locked decision without decision-reopened"
                    )
                user_decision_index[decision_id] = index
                locked_decisions.add(decision_id)
                reopened_decisions.discard(decision_id)
                product_decisions.add(decision_id)
                decision_sources[decision_id] = event["source"]
                selected_outcomes[decision_id] = event["selection"]
                decision_versions[decision_id] = decision_versions.get(decision_id, 0) + 1

        elif kind == "normative-spec-write":
            decision_id = event.get("decision_id", "")
            target = event.get("target", "")
            change = event.get("change", "")
            answer_source = event.get("answer_source", "")
            selected_outcome = event.get("selected_outcome", "")
            if not source_map_complete:
                errors.append("decision authority trace: complete source map must precede a normative spec write")
            if target not in sources or sources.get(target, {}).get("editable") != "yes":
                errors.append("decision authority trace: normative spec write target must be a mapped editable source")
            if not change:
                errors.append("decision authority trace: normative spec write requires a stable change description")
            authority_matches = (
                bool(answer_source)
                and bool(selected_outcome)
                and answer_source == decision_sources.get(decision_id)
                and selected_outcome == selected_outcomes.get(decision_id)
            )
            if not authority_matches:
                errors.append(
                    "decision authority trace: normative spec write requires the current answer source and selected outcome"
                )
            basis = event.get("basis", "")
            preserves_locked = (
                basis == "locked-decision"
                and decision_id in locked_decisions
                and decision_id not in reopened_decisions
                and authority_matches
                and event.get("changes_decision", "false") != "true"
            )
            follows_user_answer = (
                basis == "user-decision"
                and decision_id in locked_decisions
                and decision_id not in reopened_decisions
                and authority_matches
                and user_decision_index.get(decision_id, len(events)) < index
            )
            if not preserves_locked and not follows_user_answer:
                errors.append(
                    f"decision authority trace: user decision must precede normative spec write for {decision_id or 'unknown'}"
                )
            write_key = (decision_id, target, change)
            if any(write[:3] == write_key for write in normative_writes):
                errors.append("decision authority trace: duplicate normative write mapping")
            normative_writes.append(
                (
                    *write_key,
                    index,
                    answer_source,
                    selected_outcome,
                    decision_versions.get(decision_id, 0),
                )
            )
            if preserves_locked or follows_user_answer:
                decision_target_history.setdefault(decision_id, set()).add((target, change))

        elif kind == "decision-application":
            required = {
                "decision_id",
                "target",
                "change",
                "answer_source",
                "selected_outcome",
                "changed_sections",
                "changed_criteria",
                "preserved_invariants",
            }
            missing = sorted(field for field in required if not event.get(field))
            if missing:
                errors.append(f"decision authority trace: decision application missing fields {missing}")
            key = (event.get("decision_id", ""), event.get("target", ""), event.get("change", ""))
            matching_writes = [write for write in normative_writes if write[:3] == key and write[3] < index]
            if not matching_writes:
                errors.append("decision authority trace: decision application must map an earlier normative write")
            decision_id = event.get("decision_id", "")
            matching_write = matching_writes[-1] if matching_writes else None
            expected_answer_source = matching_write[4] if matching_write else decision_sources.get(decision_id)
            expected_outcome = matching_write[5] if matching_write else selected_outcomes.get(decision_id)
            expected_version = matching_write[6] if matching_write else -1
            if event.get("answer_source") != expected_answer_source:
                errors.append("decision authority trace: decision application answer source does not match provenance")
            if event.get("selected_outcome") != expected_outcome:
                errors.append("decision authority trace: decision application outcome does not match the decision")
            if matching_write and expected_version != decision_versions.get(decision_id):
                errors.append("decision authority trace: decision application maps a stale decision version")
            if key in applications:
                errors.append("decision authority trace: duplicate decision application mapping")
            applications[key] = index
            application_versions[key] = expected_version
            if (
                matching_write
                and expected_version == decision_versions.get(decision_id)
                and event.get("answer_source") == expected_answer_source
                and event.get("selected_outcome") == expected_outcome
            ):
                required_targets = reapplications_required.get(decision_id)
                if required_targets is not None:
                    required_targets.discard((event.get("target", ""), event.get("change", "")))
                    if not required_targets:
                        reapplications_required.pop(decision_id, None)

        elif kind == "decision-noop-application":
            required = {
                "decision_id",
                "answer_source",
                "selected_outcome",
                "confirmed_no_change",
                "affected_targets",
                "reason",
            }
            missing = sorted(field for field in required if not event.get(field))
            if missing:
                errors.append(f"decision authority trace: no-op application missing fields {missing}")
            decision_id = event.get("decision_id", "")
            raw_targets = event.get("affected_targets", "")
            covered_targets: set[tuple[str, str]] = set()
            malformed_targets = False
            for value in raw_targets.split("|"):
                if "::" not in value:
                    malformed_targets = True
                    continue
                target, change = (part.strip() for part in value.split("::", 1))
                if not target or not change:
                    malformed_targets = True
                    continue
                covered_targets.add((target, change))
            required_targets = reapplications_required.get(decision_id, set())
            repeats_previous_outcome = (
                bool(pre_reopen_outcomes.get(decision_id))
                and event.get("selected_outcome") == pre_reopen_outcomes.get(decision_id)
            )
            covers_every_target = bool(required_targets) and covered_targets == required_targets and not malformed_targets
            if not repeats_previous_outcome:
                errors.append("decision authority trace: no-op application must repeat the pre-reopen outcome")
            if not covers_every_target:
                errors.append(
                    "decision authority trace: no-op application must cover every pre-reopen target/change"
                )
            valid_noop = (
                decision_id in reapplications_required
                and decision_id in locked_decisions
                and decision_id not in reopened_decisions
                and event.get("confirmed_no_change") == "true"
                and event.get("answer_source") == decision_sources.get(decision_id)
                and event.get("selected_outcome") == selected_outcomes.get(decision_id)
                and user_decision_index.get(decision_id, len(events)) < index
                and not missing
                and repeats_previous_outcome
                and covers_every_target
            )
            if not valid_noop:
                errors.append(
                    "decision authority trace: no-op application requires a matching post-reopen user confirmation"
                )
            key = (decision_id, "<no-op>", event.get("affected_targets", ""))
            if key in applications:
                errors.append("decision authority trace: duplicate decision application mapping")
            applications[key] = index
            application_versions[key] = decision_versions.get(decision_id, -1)
            if valid_noop:
                reapplications_required.pop(decision_id, None)

        elif kind == "decision-application-receipt":
            required = {"application_count", "preserved_decisions", "remaining_open"}
            missing = sorted(field for field in required if not event.get(field))
            if missing:
                errors.append(f"decision authority trace: application receipt missing fields {missing}")
            try:
                application_count = int(event.get("application_count", ""))
            except ValueError:
                application_count = -1
                errors.append("decision authority trace: application receipt count must be an integer")
            if application_count != len(applications):
                errors.append("decision authority trace: application receipt count does not match mappings")
            last_application_receipt = index
            final_receipt = event

        elif kind == "ready":
            if index != len(events) - 1:
                errors.append("decision authority trace: Ready must be the terminal authority event")
            if not source_map_complete:
                errors.append("decision authority trace: Ready requires a complete specification source map")
            if unreconciled_sources:
                errors.append(
                    f"decision authority trace: Ready has unreconciled specification sources {sorted(unreconciled_sources)}"
                )
            if event.get("open_decisions") != "none":
                errors.append("decision authority trace: Ready requires no open user decisions")
            unresolved = sorted(product_decisions - locked_decisions)
            if unresolved:
                errors.append(f"decision authority trace: Ready has unresolved product decisions {unresolved}")
            unanswered_packets = sorted(
                decision_id for decision_id in unresolved if decision_id not in presented_questions
            )
            if unanswered_packets:
                errors.append(f"decision authority trace: product decisions lack decision packets {unanswered_packets}")
            unresolved_technical = sorted(technical_gap_ids - technical_decision_ids)
            if unresolved_technical:
                errors.append(f"decision authority trace: Ready has unresolved technical decisions {unresolved_technical}")
            if reapplications_required:
                remaining_reapplications = sorted(
                    (decision_id, target, change)
                    for decision_id, targets in reapplications_required.items()
                    for target, change in targets
                )
                errors.append(
                    "decision authority trace: reopened decision requires current normative reapplication "
                    f"{remaining_reapplications}"
                )
            write_keys = {write[:3] for write in normative_writes}
            missing_applications = sorted(write_keys - set(applications))
            if missing_applications:
                errors.append(
                    f"decision authority trace: application receipt omits normative writes {missing_applications}"
                )
            stale_applications = sorted(
                key
                for key, version in application_versions.items()
                if version != decision_versions.get(key[0], -1)
            )
            if stale_applications:
                errors.append(
                    f"decision authority trace: Ready has applications from stale decision versions {stale_applications}"
                )
            last_write_index = max((write[3] for write in normative_writes), default=-1)
            last_application_index = max(applications.values(), default=-1)
            if (normative_writes or applications) and (
                last_application_receipt is None
                or last_application_receipt < last_write_index
                or last_application_receipt < last_application_index
            ):
                errors.append("decision authority trace: Ready requires an application receipt after normative writes")
            if final_receipt is not None and final_receipt.get("remaining_open") != "none":
                errors.append("decision authority trace: application receipt still has open decisions")

    return errors


def validate_implementation_dispatch_trace(events: list[dict[str, str]]) -> list[str]:
    """Validate lease → dispatch → running receipt → writes → terminal receipt → release."""

    errors: list[str] = []
    write_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event") in {"test-write", "code-write"}
    ]
    if not write_indexes:
        return ["implementation dispatch trace: missing test-write or code-write event"]
    first_write_index = write_indexes[0]
    last_write_index = write_indexes[-1]

    prior_events = events[:first_write_index]
    lease_events = [
        (index, event)
        for index, event in enumerate(prior_events)
        if event.get("event") == "writer-lease-acquired"
    ]
    if not lease_events:
        return ["implementation dispatch trace: writer lease must be acquired before dispatch"]
    lease_index, lease_event = lease_events[-1]
    lease_id = lease_event.get("lease", "")
    if not lease_id:
        errors.append("implementation dispatch trace: acquired writer lease needs an ID")

    dispatches = [event for event in prior_events if event.get("event") == "implementation-dispatch"]
    if not dispatches:
        return ["implementation dispatch trace: exact writer dispatch must precede every code edit"]

    dispatch = dispatches[-1]
    risk = dispatch.get("risk", "")
    expected = IMPLEMENTATION_AGENT_BY_RISK.get(risk)
    if expected is None:
        errors.append("implementation dispatch trace: risk must be low, medium, high, or critical")
        return errors
    expected_tier, expected_agent = expected
    agent_name = dispatch.get("agent_name", "")
    task_name = dispatch.get("task_name", "")
    if agent_name != expected_agent:
        errors.append(
            f"implementation dispatch trace: {risk} risk agent_name must select exact writer {expected_agent}"
        )
    if not AGENT_NAME.fullmatch(agent_name):
        errors.append("implementation dispatch trace: agent_name must use underscore grammar")
    if not task_name or task_name == agent_name:
        errors.append("implementation dispatch trace: task_name must be a separate non-profile task label")
    if dispatch.get("result") != "selected":
        errors.append("implementation dispatch trace: code edits require a selected exact writer")
    if dispatch.get("fallback_reason", "none") not in {"", "none"}:
        errors.append("implementation dispatch trace: selected exact writer must not report fallback")
    dispatch_index = prior_events.index(dispatch)
    if dispatch_index <= lease_index:
        errors.append("implementation dispatch trace: writer lease must precede exact dispatch")
    if dispatch.get("lease") != lease_id:
        errors.append("implementation dispatch trace: dispatch lease must match the acquired lease")

    receipt_events = [
        (index, event)
        for index, event in enumerate(prior_events)
        if event.get("event") == "implementation-routing-receipt"
    ]
    if not receipt_events:
        errors.append("implementation dispatch trace: implementation routing receipt must precede every code edit")
        return errors

    receipt_index, receipt = receipt_events[-1]
    if receipt_index <= dispatch_index:
        errors.append("implementation dispatch trace: routing receipt must follow exact writer dispatch")
    required_fields = {
        "risk",
        "requested_agent",
        "task_name",
        "requested_tier",
        "dispatch_method",
        "configured_model",
        "model_reasoning_effort",
        "observed_agent",
        "observed_model",
        "sandbox",
        "lease",
        "run_status",
        "dispatch_result",
        "fallback_reason",
        "activated",
        "run_dir",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
        "process_tree_stopped",
    }
    missing = sorted(field for field in required_fields if field not in receipt)
    if missing:
        errors.append(f"implementation dispatch trace: routing receipt missing fields {missing}")
    if receipt.get("risk") != risk:
        errors.append("implementation dispatch trace: receipt risk must match dispatch risk")
    if receipt.get("requested_agent") != expected_agent:
        errors.append("implementation dispatch trace: receipt must name the exact risk-matched writer")
    if receipt.get("task_name") != task_name:
        errors.append("implementation dispatch trace: receipt task_name must match the separate task label")
    if receipt.get("requested_tier") != expected_tier:
        errors.append("implementation dispatch trace: receipt tier must match the risk floor")
    if receipt.get("lease") != lease_id:
        errors.append("implementation dispatch trace: running receipt lease must match the acquired lease")
    dispatch_method = receipt.get("dispatch_method")
    if dispatch_method not in EXACT_DISPATCH_METHODS:
        errors.append("implementation dispatch trace: writer requires an exact dispatch method")
    if dispatch_method == "codex-exec-explicit-model":
        if not receipt.get("model_reasoning_effort"):
            errors.append("implementation dispatch trace: explicit-model receipt needs model_reasoning_effort")
        if receipt.get("terminal_event") not in {None, "none"}:
            errors.append("implementation dispatch trace: running receipt must not claim terminal completion")
    else:
        prior_receipts = [
            prior_receipt
            for index, prior_receipt in receipt_events
            if index < receipt_index
        ]
        errors.extend(
            validate_prior_terminal_runner_failure(
                prior_receipts,
                label="implementation dispatch trace",
                bindings={
                    "risk": risk,
                    "requested_agent": expected_agent,
                    "task_name": task_name,
                    "requested_tier": expected_tier,
                    "lease": lease_id,
                },
            )
        )
        if dispatch_method == "per-spawn-model" and (
            receipt.get("configured_model") in {None, "", "unknown", "unobservable"}
            or receipt.get("model_reasoning_effort") in {None, "", "unknown", "unobservable"}
        ):
            errors.append(
                "implementation dispatch trace: per-spawn native fallback requires direct model and reasoning effort"
            )
    if receipt.get("run_status") != "running":
        errors.append("implementation dispatch trace: pre-write receipt must be running")
    if receipt.get("activated") is not False:
        errors.append("implementation dispatch trace: pre-write receipt must be recorded before activation")
    if receipt.get("process_tree_stopped") is not False:
        errors.append("implementation dispatch trace: running receipt cannot claim a stopped process tree")
    if receipt.get("sandbox") != "workspace-write":
        errors.append("implementation dispatch trace: writer sandbox must be workspace-write")
    if receipt.get("dispatch_result") != "selected":
        errors.append("implementation dispatch trace: receipt must confirm selected writer")
    if receipt.get("fallback_reason") not in {"", "none"}:
        errors.append("implementation dispatch trace: selected writer receipt must not report fallback")

    activation_events = [
        (index, event)
        for index, event in enumerate(events)
        if receipt_index < index < first_write_index
        and event.get("event") == "implementation-agent-activated"
    ]
    if len(activation_events) != 1:
        errors.append(
            "implementation dispatch trace: exactly one activation event must follow the recorded receipt and precede every edit"
        )
    else:
        _, activation = activation_events[0]
        activation_bindings = {
            "lease": lease_id,
            "agent_name": expected_agent,
            "task_name": task_name,
            "run_dir": receipt.get("run_dir"),
            "worker_process_identity": receipt.get("worker_process_identity"),
            "codex_process_identity": receipt.get("codex_process_identity"),
        }
        for field, expected_value in activation_bindings.items():
            if activation.get(field) != expected_value:
                errors.append(
                    f"implementation dispatch trace: activation event changed lease/run binding {field}"
                )
        if activation.get("activated") is not True:
            errors.append("implementation dispatch trace: activation event must confirm activated true")
    if any(events[index].get("actor") != expected_agent for index in write_indexes):
        errors.append("implementation dispatch trace: exact risk-matched writer must own every code edit")

    terminal_receipts = [
        (index, event)
        for index, event in enumerate(events)
        if index > last_write_index
        and event.get("event") == "implementation-routing-receipt"
        and event.get("lease") == lease_id
    ]
    if not terminal_receipts:
        errors.append("implementation dispatch trace: terminal routing receipt must follow writer edits")
        return errors
    terminal_index, terminal = terminal_receipts[0]
    for field in (
        "risk",
        "requested_agent",
        "task_name",
        "requested_tier",
        "dispatch_method",
        "configured_model",
        "model_reasoning_effort",
        "observed_agent",
        "observed_model",
        "terminal_event",
        "sandbox",
        "lease",
        "run_status",
        "dispatch_result",
        "fallback_reason",
        "process_tree_stopped",
        "activated",
        "run_dir",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
        "codex_exit_evidence",
        "codex_exit_code",
        "result_evidence",
    ):
        if field not in terminal:
            errors.append(f"implementation dispatch trace: terminal receipt missing field {field}")
    for field in (
        "risk",
        "requested_agent",
        "task_name",
        "requested_tier",
        "dispatch_method",
        "configured_model",
        "model_reasoning_effort",
        "sandbox",
        "lease",
        "run_dir",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
    ):
        if terminal.get(field) != receipt.get(field):
            errors.append(f"implementation dispatch trace: terminal receipt changed routing field {field}")
    run_status = terminal.get("run_status")
    errors.extend(
        validate_explicit_terminal_evidence(terminal, label="implementation dispatch trace")
    )
    if terminal.get("process_tree_stopped") is not True:
        errors.append("implementation dispatch trace: terminal receipt must confirm stopped process tree")
    if terminal.get("activated") is not True:
        errors.append("implementation dispatch trace: terminal receipt must confirm activation")
    if run_status == "completed":
        if terminal.get("dispatch_result") != "selected" or terminal.get("fallback_reason") not in {"", "none"}:
            errors.append("implementation dispatch trace: completed writer terminal receipt is inconsistent")
        if dispatch_method == "codex-exec-explicit-model" and terminal.get("terminal_event") != "turn.completed":
            errors.append("implementation dispatch trace: terminal explicit-model receipt requires turn.completed")
        if dispatch_method == "codex-exec-explicit-model" and not explicit_success_evidence_is_valid(terminal):
            errors.append(
                "implementation dispatch trace: completed writer needs exit code zero and valid result evidence"
            )
    elif run_status == "failed":
        if terminal.get("dispatch_result") != "failed" or terminal.get("fallback_reason") in {"", "none"}:
            errors.append("implementation dispatch trace: failed writer terminal receipt needs a failure reason")
        terminal_event = terminal.get("terminal_event")
        if terminal_event not in {"turn.failed", "turn.completed", "none", None}:
            errors.append("implementation dispatch trace: failed writer terminal event is invalid")
        if (
            dispatch_method == "codex-exec-explicit-model"
            and terminal_event == "turn.completed"
            and not explicit_failure_evidence_is_valid(terminal)
        ):
            errors.append(
                "implementation dispatch trace: failed turn.completed needs independent exit/result failure evidence"
            )
    else:
        errors.append("implementation dispatch trace: terminal receipt must report completed or failed")

    handoff_events = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("event") == "implementation-handoff-accepted"
    ]
    accepted_handoff_index: int | None = None
    if run_status == "completed":
        valid_handoffs = [
            (index, event) for index, event in handoff_events if index > terminal_index
        ]
        if len(valid_handoffs) != 1 or len(handoff_events) != 1:
            errors.append(
                "implementation dispatch trace: completed writer needs one run-bound accepted handoff after terminal evidence"
            )
        else:
            accepted_handoff_index, handoff = valid_handoffs[0]
            handoff_bindings = {
                "lease": lease_id,
                "agent_name": expected_agent,
                "task_name": task_name,
                "run_dir": terminal.get("run_dir"),
                "worker_process_identity": terminal.get("worker_process_identity"),
                "codex_process_identity": terminal.get("codex_process_identity"),
                "result_evidence": "valid",
            }
            for field, expected_value in handoff_bindings.items():
                if handoff.get(field) != expected_value:
                    errors.append(
                        f"implementation dispatch trace: accepted handoff changed terminal binding {field}"
                    )
    elif handoff_events:
        errors.append("implementation dispatch trace: failed writer result cannot be accepted as a handoff")

    premature_releases = [
        event
        for index, event in enumerate(events)
        if lease_index < index < terminal_index and event.get("event") == "writer-lease-released"
    ]
    if premature_releases:
        errors.append("implementation dispatch trace: writer lease was released before terminal receipt")

    release_events = [
        (index, event)
        for index, event in enumerate(events)
        if index > terminal_index and event.get("event") == "writer-lease-released"
    ]
    if not release_events:
        errors.append("implementation dispatch trace: writer lease release must follow terminal receipt")
    elif release_events[0][1].get("lease") != lease_id:
        errors.append("implementation dispatch trace: released lease must match the acquired lease")
    elif accepted_handoff_index is not None and release_events[0][0] <= accepted_handoff_index:
        errors.append("implementation dispatch trace: lease release must follow accepted handoff")

    return errors


def validate_review_escalation_trace(events: list[dict[str, str]]) -> list[str]:
    """Validate exact read-only reviewer dispatch and evidence-gated tier escalation."""

    errors: list[str] = []
    dispatch_indexes = [
        index for index, event in enumerate(events) if event.get("event") == "review-dispatch"
    ]
    if not dispatch_indexes:
        return ["review escalation trace: missing exact reviewer dispatch"]

    seen: set[tuple[str, str]] = set()
    prior_tier: str | None = None
    prior_result_index: int | None = None
    prior_result: dict[str, str] | None = None

    for position, dispatch_index in enumerate(dispatch_indexes):
        dispatch = events[dispatch_index]
        risk = dispatch.get("risk", "")
        tier = dispatch.get("tier", "")
        agent_name = dispatch.get("agent_name", "")
        task_name = dispatch.get("task_name", "")
        diff_revision = dispatch.get("diff_revision", "")
        expected_start = REVIEW_START_BY_RISK.get(risk)
        expected_agent = REVIEW_AGENT_BY_TIER.get(tier)

        if expected_start is None:
            errors.append("review escalation trace: risk must be low, medium, high, or critical")
            continue
        if position == 0 and tier != expected_start:
            errors.append(
                f"review escalation trace: {risk} risk must start at exact {expected_start} reviewer"
            )
        if expected_agent is None or agent_name != expected_agent:
            errors.append("review escalation trace: dispatch must select the exact agent for its tier")
        if not AGENT_NAME.fullmatch(agent_name):
            errors.append("review escalation trace: agent_name must use underscore grammar")
        if not task_name or task_name == agent_name:
            errors.append("review escalation trace: task_name must be a separate non-profile task label")
        if dispatch.get("result") != "selected":
            errors.append("review escalation trace: review requires a selected exact reviewer")
        key = (diff_revision, tier)
        if key in seen:
            errors.append("review escalation trace: unchanged diff cannot repeat the same reviewer tier")
        seen.add(key)

        if prior_tier is not None and prior_result is not None and prior_result_index is not None:
            if prior_tier in REVIEW_TIERS:
                prior_rank = REVIEW_TIERS.index(prior_tier)
                expected_next = (
                    REVIEW_TIERS[prior_rank + 1]
                    if prior_rank + 1 < len(REVIEW_TIERS)
                    else None
                )
                if tier != expected_next:
                    errors.append("review escalation trace: sequential review ladder cannot skip a proven tier")
            reason = prior_result.get("escalation_reason", "none")
            if reason not in REVIEW_ESCALATION_REASONS:
                errors.append("review escalation trace: stronger reviewer requires a concrete escalation trigger")
            actionable = prior_result.get("actionable_findings", "none") not in {
                "",
                "0",
                "false",
                "none",
            }
            if actionable:
                between = events[prior_result_index + 1 : dispatch_index]
                if not any(event.get("event") == "root-remediation" for event in between):
                    errors.append("review escalation trace: root must remediate actionable findings before escalation")
                if not any(
                    event.get("event") == "validation" and event.get("result") == "green"
                    for event in between
                ):
                    errors.append("review escalation trace: green validation must follow remediation before escalation")

        next_dispatch_index = (
            dispatch_indexes[position + 1] if position + 1 < len(dispatch_indexes) else len(events)
        )
        window = events[dispatch_index + 1 : next_dispatch_index]
        receipts = [
            (offset, event)
            for offset, event in enumerate(window)
            if event.get("event") == "review-routing-receipt"
        ]
        running_receipts = [
            (offset, receipt)
            for offset, receipt in receipts
            if receipt.get("run_status") == "running"
        ]
        terminal_receipts = [
            (offset, receipt)
            for offset, receipt in receipts
            if receipt.get("run_status") in {"completed", "failed"}
        ]
        activations = [
            (offset, event)
            for offset, event in enumerate(window)
            if event.get("event") == "review-agent-activated"
        ]
        results = [
            (offset, event)
            for offset, event in enumerate(window)
            if event.get("event") == "review-result"
        ]
        if len(running_receipts) != 1:
            errors.append(
                "review escalation trace: exact review requires one selected running routing receipt"
            )
        if len(activations) != 1:
            errors.append("review escalation trace: exact review requires one matching activation event")
        if len(results) != 1:
            errors.append("review escalation trace: selected reviewer must return one structured result")
        if not running_receipts or not activations or not results:
            continue

        running_offset, running = running_receipts[0]
        selected_terminal_receipts = [
            (offset, receipt)
            for offset, receipt in terminal_receipts
            if offset > running_offset
        ]
        if len(selected_terminal_receipts) != 1:
            errors.append(
                "review escalation trace: exact review requires one terminal receipt after selected running routing"
            )
            continue
        activation_offset, activation = activations[0]
        terminal_offset, terminal = selected_terminal_receipts[0]
        result_offset, result = results[0]
        if not running_offset < activation_offset < terminal_offset < result_offset:
            errors.append(
                "review escalation trace: lifecycle must be running receipt, activation, terminal receipt, then result"
            )

        required_receipt = {
            "diff_revision",
            "risk_floor",
            "requested_agent",
            "task_name",
            "requested_tier",
            "dispatch_method",
            "configured_model",
            "model_reasoning_effort",
            "observed_agent",
            "observed_model",
            "terminal_event",
            "activated",
            "run_status",
            "sandbox",
            "dispatch_result",
            "fallback_reason",
            "process_tree_stopped",
            "run_dir",
            "worker_pid",
            "worker_process_identity",
            "codex_pid",
            "codex_process_identity",
            "codex_exit_evidence",
            "codex_exit_code",
            "result_evidence",
        }
        for phase, receipt in (("running", running), ("terminal", terminal)):
            missing_receipt = sorted(field for field in required_receipt if field not in receipt)
            if missing_receipt:
                errors.append(
                    f"review escalation trace: {phase} routing receipt missing fields {missing_receipt}"
                )
            if receipt.get("diff_revision") != diff_revision:
                errors.append(f"review escalation trace: {phase} receipt diff revision must match dispatch")
            if receipt.get("risk_floor") != expected_start:
                errors.append(f"review escalation trace: {phase} receipt must record the risk review floor")
            if receipt.get("requested_agent") != expected_agent or receipt.get("requested_tier") != tier:
                errors.append(f"review escalation trace: {phase} receipt must name the exact requested reviewer")
            if receipt.get("task_name") != task_name:
                errors.append(f"review escalation trace: {phase} receipt task_name must match")

        dispatch_method = running.get("dispatch_method")
        if dispatch_method not in EXACT_DISPATCH_METHODS:
            errors.append("review escalation trace: reviewer requires an exact dispatch method")
        if dispatch_method == "codex-exec-explicit-model":
            if not running.get("model_reasoning_effort"):
                errors.append("review escalation trace: explicit-model receipt needs model_reasoning_effort")
            if any(offset < running_offset for offset, _ in receipts):
                errors.append(
                    "review escalation trace: primary explicit runner cannot follow an earlier routing receipt"
                )
        else:
            prior_receipts = [
                prior_receipt
                for offset, prior_receipt in receipts
                if offset < running_offset
            ]
            errors.extend(
                validate_prior_terminal_runner_failure(
                    prior_receipts,
                    label="review escalation trace",
                    bindings={
                        "diff_revision": diff_revision,
                        "risk_floor": expected_start,
                        "requested_agent": expected_agent,
                        "task_name": task_name,
                        "requested_tier": tier,
                    },
                )
            )
            if dispatch_method == "per-spawn-model" and (
                running.get("configured_model") in {None, "", "unknown", "unobservable"}
                or running.get("model_reasoning_effort") in {None, "", "unknown", "unobservable"}
            ):
                errors.append(
                    "review escalation trace: per-spawn native fallback requires direct model and reasoning effort"
                )
        if running.get("activated") is not False or running.get("terminal_event") not in {None, "none"}:
            errors.append("review escalation trace: running receipt must be unactivated and non-terminal")
        if running.get("process_tree_stopped") is not False:
            errors.append("review escalation trace: running receipt cannot claim a stopped process tree")
        running_exit_code = running.get("codex_exit_code")
        if (
            running.get("codex_exit_evidence") != "missing"
            or (running_exit_code is not None and running_exit_code != "unknown")
            or running.get("result_evidence") != "missing"
        ):
            errors.append(
                "review escalation trace: running receipt must carry missing/unknown/missing evidence"
            )
        if running.get("dispatch_result") != "selected" or running.get("fallback_reason") not in {"", "none"}:
            errors.append("review escalation trace: running receipt must preserve selected routing")
        for field in ("run_dir", "worker_pid", "worker_process_identity", "codex_pid", "codex_process_identity"):
            if not running.get(field):
                errors.append(f"review escalation trace: running receipt requires {field}")
        if running.get("sandbox") != "read-only":
            errors.append("review escalation trace: reviewer sandbox must be read-only")

        activation_bindings = {
            "diff_revision": diff_revision,
            "requested_agent": expected_agent,
            "task_name": task_name,
            "run_dir": running.get("run_dir"),
            "worker_process_identity": running.get("worker_process_identity"),
            "codex_process_identity": running.get("codex_process_identity"),
        }
        for field, expected in activation_bindings.items():
            if activation.get(field) != expected:
                errors.append(f"review escalation trace: activation changed {field}")
        if activation.get("activated") is not True:
            errors.append("review escalation trace: activation event must confirm activated true")

        immutable_fields = {
            "diff_revision",
            "risk_floor",
            "requested_agent",
            "task_name",
            "requested_tier",
            "dispatch_method",
            "configured_model",
            "model_reasoning_effort",
            "sandbox",
            "run_dir",
            "worker_pid",
            "worker_process_identity",
            "codex_pid",
            "codex_process_identity",
        }
        for field in immutable_fields:
            if terminal.get(field) != running.get(field):
                errors.append(f"review escalation trace: terminal receipt changed routing field {field}")
        if terminal.get("activated") is not True or terminal.get("process_tree_stopped") is not True:
            errors.append("review escalation trace: terminal receipt must confirm activation and stopped process tree")
        if terminal.get("run_status") != "completed":
            errors.append("review escalation trace: reviewer result requires a completed terminal receipt")
        if terminal.get("dispatch_result") != "selected" or terminal.get("fallback_reason") not in {"", "none"}:
            errors.append("review escalation trace: terminal receipt must preserve selected routing")
        if terminal.get("terminal_event") != "turn.completed":
            errors.append("review escalation trace: completed explicit-model receipt requires turn.completed")
        if terminal.get("observed_agent") != expected_agent:
            errors.append("review escalation trace: terminal receipt must observe the exact reviewer")
        errors.extend(
            validate_explicit_terminal_evidence(
                terminal,
                label="review escalation trace",
            )
        )
        if not explicit_success_evidence_is_valid(terminal):
            errors.append(
                "review escalation trace: terminal receipt needs exit code zero and valid result evidence"
            )

        required_result = {
            "diff_revision",
            "tier",
            "verdict",
            "confidence",
            "coverage",
            "actionable_findings",
            "escalation_reason",
        }
        missing_result = sorted(field for field in required_result if field not in result)
        if missing_result:
            errors.append(f"review escalation trace: reviewer result missing fields {missing_result}")
        if result.get("diff_revision") != diff_revision or result.get("tier") != tier:
            errors.append("review escalation trace: reviewer result must match dispatched tier and diff")
        if result.get("verdict") not in {"ACCEPT", "REVISE", "ESCALATE", "BLOCKED"}:
            errors.append("review escalation trace: reviewer result has an invalid verdict")

        prior_tier = tier
        prior_result = result
        prior_result_index = dispatch_index + 1 + result_offset

    if prior_result is not None:
        final_reason = prior_result.get("escalation_reason", "none")
        actionable = prior_result.get("actionable_findings", "none") not in {
            "",
            "0",
            "false",
            "none",
        }
        incomplete = (
            prior_result.get("verdict") != "ACCEPT"
            or prior_result.get("confidence") == "low"
            or prior_result.get("coverage") != "complete"
        )
        if final_reason in REVIEW_ESCALATION_REASONS or actionable or incomplete:
            if prior_tier == "strongest":
                errors.append("review escalation trace: strongest reviewer left the task blocked")
            else:
                errors.append("review escalation trace: unresolved trigger requires the next reviewer tier")

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

    selection = markdown_section(skill_text, "## Select the specification safely")
    for token in [
        "specification source map",
        "every in-scope normative file",
        "every outgoing normative edge",
        "every source is reachable from the root",
        "Do not assume that the root file overrides",
    ]:
        if token not in selection:
            errors.append(f"SKILL.md specification source map: missing {token}")

    authority = markdown_section(skill_text, "## Protect user decision authority")
    for token in [
        "The user owns any choice",
        "product-impact boundary",
        "T-###",
        "mixed or uncertain",
        "Never silently prefer",
        "Initial source mapping cannot self-declare a user deferral",
    ]:
        if token not in authority:
            errors.append(f"SKILL.md decision authority: missing {token}")

    interview = markdown_section(skill_text, "## Ask product questions before normative edits")
    for token in [
        "Do not change normative specification content",
        "decision application receipt",
        "cannot replace a locked `D-###`",
        "reopened decision invalidates the prior write/application authorization",
        "every previously affected target/change tuple",
        "keep the status at `Questions`",
    ]:
        if token not in interview:
            errors.append(f"SKILL.md normative edit gate: missing {token}")

    for heading, label in [
        ("## Specification source map", "specification source map"),
        ("## Coverage model", "coverage model"),
        ("## Decision authority and conflict protocol", "decision authority"),
        ("## Decision memory and deduplication", "decision memory"),
        ("## Decision application gate", "decision application gate"),
        ("## Adaptive critic loop", "adaptive critic loop"),
        ("## Critic result", "critic result"),
        ("## Ready gate", "Ready gate"),
    ]:
        if not markdown_section(protocol_text, heading):
            errors.append(f"blindspot-protocol.md: missing {label} section")

    source_map = markdown_section(protocol_text, "## Specification source map")
    for token in [
        "every in-scope document linked",
        "every outgoing normative link",
        "every mapped source is reachable from the selected root",
        "decision provenance must explicitly list",
        "cannot self-declare `deferred`",
        "decision record",
        "Do not infer that the root silently overrides",
        "route the conflict through the decision authority protocol",
    ]:
        if token not in source_map:
            errors.append(f"blindspot-protocol.md source map: missing {token}")

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
        "A second user answer cannot overwrite the locked outcome",
        "conditional child decision",
    ]:
        if token not in decision_memory:
            errors.append(f"blindspot-protocol.md decision memory: missing {token}")

    decision_authority = markdown_section(protocol_text, "## Decision authority and conflict protocol")
    for token in [
        "bridge between user intent and implementation",
        "product-impact test",
        "When classification is mixed or uncertain",
        "T-###",
        "Never silently choose",
        "structured reconciliation receipt",
        "record type, governed target, source revision, and positive line number",
        "Free-text evidence",
        "wait for the user's answer",
    ]:
        if token not in decision_authority:
            errors.append(f"blindspot-protocol.md decision authority: missing {token}")

    application_gate = markdown_section(protocol_text, "## Decision application gate")
    for token in [
        "Do not change that dependent normative specification content",
        "An answered independent ID may be applied immediately",
        "decision application receipt",
        "one structured mapping for every normative decision/target/change tuple",
        "exact answer source",
        "Every normative write captures the authorizing decision version",
        "invalidates every prior normative write/application authorization",
        "complete set of affected `(target, change)` tuples",
        "repeats the exact pre-reopen outcome",
        "Every Build-made normative change",
        "cannot authorize a normative product change",
        "keep the specification in `Questions`",
    ]:
        if token not in application_gate:
            errors.append(f"blindspot-protocol.md decision application gate: missing {token}")

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
        "specification source map",
        "gap",
        "blocking product decisions",
        "material contradiction",
        "missing new authority",
        "critic finding",
        "acceptance criteria",
        "current specification revision",
        "COVERED",
        "decision application receipt",
        "Build-made normative change",
        "T-###",
        "current decision version",
    ]:
        if token not in ready_gate:
            errors.append(f"blindspot-protocol.md Ready gate: missing {token}")

    risks = markdown_section(template_text, "## 9. Risks and blind spots")
    ledger_header = "ID | Concern | Status | Disposition | Evidence or decision | Next action"
    if ledger_header not in risks or "B-###" not in risks or "D-###" not in risks:
        errors.append("spec-template.md coverage ledger: missing durable IDs or required columns")
    if "### Decision application receipt" not in risks or "Changed files/sections/ACs/milestones" not in risks:
        errors.append("spec-template.md: missing decision application receipt")

    current_state = markdown_section(template_text, "## 2. Current state and evidence")
    if "### Specification source map" not in current_state or "Normative scope and decision IDs" not in current_state:
        errors.append("spec-template.md: missing specification source map")

    decisions = markdown_section(template_text, "## 3. Decision memory")
    for token in ["### User-owned product decisions", "### Technical decision ledger", "T-001", "### Pending proposals"]:
        if token not in decisions:
            errors.append(f"spec-template.md decision authority: missing {token}")

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
        for token in [
            "Build is a bridge between user intent and code",
            "product-impact test",
            "stable `D-###` IDs",
            "stable `T-###` IDs",
            "normative specification",
            "decision application receipt",
            "A resolved ID is a locked constraint",
            "Reopening is allowed only",
            "same critic perspective/tier",
            "not a claim of literal omniscience",
        ]:
            if token not in readme_blindspots:
                errors.append(f"README.md blind-spot critique: missing {token}")
    readme_ru_blindspots = markdown_section(readme_ru, "## Как работает критика blind spots")
    if not readme_ru_blindspots:
        errors.append("README.ru.md: missing blind-spot critique section")
    else:
        for token in [
            "Build — мост между намерением пользователя и кодом",
            "Product-impact test",
            "стабильные IDs `D-###`",
            "стабильные IDs `T-###`",
            "нормативную спецификацию",
            "decision application receipt",
            "Решённый ID становится зафиксированным ограничением",
            "Переоткрытие допустимо только",
            "одна perspective/tier не повторяется",
            "не заявление о буквальном всеведении",
        ]:
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
    review_protocol: str,
    readme: str,
    readme_ru: str,
) -> list[str]:
    errors: list[str] = []

    explicit_discovery = markdown_section(skill_text, "## Explicit Code Discovery Delegation")
    for token in [
        "first use `tool_search` to expose multi-agent tools if they are not already visible",
        "spawn a read-only `explorer` subagent with `model: gpt-5.3-codex-spark`",
        "delegate repository search, `rg`, `Get-Content`, and local file reading to that subagent",
        "compact evidence map with `path:line`, symbol/route, snippet/signature, and why it matters",
        "do targeted main-process reads only after the subagent result",
        "Fallback to local `rg` only when subagents are unavailable, the search is trivial, or the relevant file is already known",
    ]:
        if token not in explicit_discovery:
            errors.append(f"SKILL.md explicit code discovery delegation: missing {token}")

    search_preflight = markdown_section(skill_text, "## Initialize search routing")
    for token in [
        "Before locating a specification",
        "separate-pool circuit-breaker",
        "every repository lookup",
        "any new file/symbol/grep lookup",
        "Spawn the custom agent named `openbuild_search_separate`",
        "scripts/agent_runner.py",
        "codex-exec-explicit-model",
        "A generic subagent, a descriptive task name",
        "exact dispatch succeeds or returns an allowed fallback reason",
        "Use a native spawn only after the launcher records an allowed terminal failure",
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
        "openbuild_search_separate",
        "**Efficient main-pool fallback:**",
        "openbuild_search_fallback",
        "open a circuit breaker",
        "without retrying the same failed route for every grep",
        "Do not scrape or infer remaining quota",
        "Do not silently skip it",
        "select `openbuild_search_separate` by exact custom-agent name",
        "`agent_name`",
        "`task_name`",
        "generic subagent, task name, or profile mention does not count as selection",
        "profile-not-discoverable",
        "selector-unavailable",
        "model-unavailable",
        "quota-exhausted",
        "spawn-failed",
        "routing receipt",
        "agent_runner.py",
        "codex-exec-explicit-model",
        "turn.completed",
        "configured_model",
        "observed_model",
        "fallback_reason",
        "unactivated `running` routing receipt",
        "only then consume the evidence",
        "exit code of zero",
        "same-named project/user profiles cannot override it",
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
        "openbuild_implementation_fast",
        "openbuild_implementation_balanced",
        "openbuild_implementation_strongest",
        "Escalate only on evidence",
        "Missing model/tier metadata alone does not block low or medium implementation",
        "High work still requires a confirmed strong route",
        "critical work requires the strongest proven route",
        "stop before every test or production code edit",
        "rather than silently lowering the risk floor",
        "acquire the single-writer lease for the exact selected profile",
        "`running` Implementation routing receipt",
        "implementation-agent-activated",
        "`agent_name`",
        "`task_name`",
        "Implementation routing receipt",
        "implementation-handoff-accepted",
        "agent_runner.py",
        "codex-exec-explicit-model",
        "turn.completed",
    ]:
        if token not in implementation_route:
            category = "exact writer dispatch" if "single-writer lease" in token else "implementation routing"
            errors.append(f"model-routing.md {category}: missing {token}")

    review_route = markdown_section(model_routing, "### Exact sequential reviewer dispatch")
    for token in [
        "Dispatch the exact starting reviewer",
        "openbuild_review_fast",
        "openbuild_review_balanced",
        "openbuild_review_strong",
        "openbuild_review_strongest",
        "fast → balanced → strong → strongest",
        "Move exactly one proven tier higher",
        "Review routing receipt",
        "unactivated `running` Review routing receipt",
        "review-agent-activated",
        "creation-bound exit code zero",
        "valid result evidence",
        "agent_runner.py",
        "codex-exec-explicit-model",
        "turn.completed",
        "`agent_name`",
        "`task_name`",
        "Reviewers remain read-only",
    ]:
        if token not in review_route:
            if token.startswith("Dispatch the exact"):
                category = "exact reviewer dispatch"
            elif token == "fast → balanced → strong → strongest":
                category = "sequential review ladder"
            else:
                category = "review routing"
            errors.append(f"model-routing.md {category}: missing {token}")

    setup = markdown_section(model_routing, "## `$build setup-models`")
    for token in [
        "openbuild_search_separate",
        "openbuild_search_fallback",
        "openbuild_implementation_fast",
        "openbuild_implementation_balanced",
        "openbuild_implementation_strongest",
        "openbuild_review_fast",
        "openbuild_review_balanced",
        "openbuild_review_strong",
        "openbuild_review_strongest",
        "confirmed usage pool",
        "workspace-write",
    ]:
        if token not in setup:
            errors.append(f"model-routing.md setup-models: missing {token}")

    migration = markdown_section(model_routing, "### Guided legacy-profile migration")
    for token in [
        "immutable `plan_id`",
        "stable `entry_id`",
        "SHA-256",
        "create-if-absent",
        "already-migrated",
        "config-conflict",
        "per-entry authority",
        "hash-drift",
        "separate displayed plan and permission",
    ]:
        if token not in migration:
            errors.append(f"model-routing.md guided migration: missing {token}")
    for canonical, legacy in CANONICAL_AGENT_IDS.items():
        if canonical not in migration or legacy not in migration:
            errors.append(f"model-routing.md guided migration: missing mapping {legacy} -> {canonical}")

    mandatory_search = markdown_section(code_discovery, "## Mandatory routing rule")
    for token in [
        "`rg --files`",
        "openbuild_search_separate",
        "openbuild_search_fallback",
        "new grep or lookup",
        "circuit breaker",
        "do not pay for repeated failed attempts",
        "before the root runs any new repository search command",
        "generic spawn or task label",
        "agent_runner.py",
        "codex-exec-explicit-model",
        "turn.completed",
    ]:
        if token not in mandatory_search:
            category = "exact agent dispatch" if "root runs" in token or "generic spawn" in token else "usage routing"
            errors.append(f"code-discovery.md {category}: missing {token}")

    routing_receipt = markdown_section(code_discovery, "## Search routing receipt")
    for token in [
        "search_agent: openbuild_search_separate",
        "task_name:",
        "dispatch_method:",
        "configured_model:",
        "observed_agent:",
        "observed_model:",
        "activated: true | false",
        "pool:",
        "dispatch_result:",
        "fallback_reason:",
        "search-agent-activated",
        "search-evidence-consumed",
        "A failed run never emits `search-evidence-consumed`",
        "codex_exit_evidence:",
        "result_evidence:",
        "usage dashboard as secondary evidence",
    ]:
        if token not in routing_receipt:
            errors.append(f"code-discovery.md routing receipt: missing {token}")

    for token in [
        "risk-matched coding model for every complexity class",
        "openbuild_implementation_fast",
        "openbuild_implementation_balanced",
        "openbuild_implementation_strongest",
        "Read-only search/discovery",
        "Missing model/tier metadata alone does not block low or medium implementation",
        "For high work require a confirmed strong route",
        "for critical work require the strongest proven route",
        "stop before all test and production code edits",
        "Dispatch that exact profile before every test or production code edit",
        "`agent_name`",
        "`task_name`",
        "Implementation routing receipt",
        "codex_exit_evidence:",
        "implementation-handoff-accepted",
        "Every terminal explicit-model receipt",
    ]:
        if token not in implementation:
            if token.startswith("Dispatch that exact"):
                category = "exact writer dispatch"
            elif token == "Implementation routing receipt":
                category = "implementation routing receipt"
            else:
                category = "risk-matched writer routing"
            errors.append(f"implementation-delegation.md {category}: missing {token}")

    review_dispatch = markdown_section(review_protocol, "## Exact dispatch and routing receipt")
    for token in [
        "low` → `openbuild_review_fast",
        "medium` → `openbuild_review_balanced",
        "high` → `openbuild_review_strong",
        "critical` → `openbuild_review_strongest",
        "fast → balanced → strong → strongest",
        "Review routing receipt",
        "review-agent-activated",
        "run_status:",
        "process_tree_stopped:",
        "codex_exit_evidence:",
        "codex_exit_code:",
        "result_evidence:",
        "task_name:",
        "sandbox: <read-only",
        "A configured profile with unobservable model metadata may satisfy low or medium selection",
        "High and critical floors still require proven strong/strongest capability",
        "exact non-terminal evidence tuple",
    ]:
        if token not in review_dispatch:
            errors.append(f"review-protocol.md exact reviewer routing: missing {token}")

    readme_usage = markdown_section(readme, "## How usage-aware model routing works")
    if not readme_usage:
        errors.append("README.md: missing usage-aware model-routing section")
    else:
        for token in [
            "Search always attempts a confirmed separate-usage route first",
            "exact custom agent `openbuild_search_separate`",
            "routing receipt",
            "fallback_reason",
            "current-run circuit breaker",
            "does not scrape the private usage dashboard",
            "risk-matched writer",
            "openbuild_implementation_fast",
            "openbuild_implementation_balanced",
            "Implementation routing receipt",
            "implementation-handoff-accepted",
            "Progressive review uses the same `agent_name`/`task_name` separation",
            "openbuild_review_balanced",
            "openbuild_review_strongest",
            "Review routing receipt",
            "review-agent-activated",
            "creation-bound exit code zero",
            "valid result evidence",
            "fast → balanced → strong → strongest",
            "Escalation",
            "model_reasoning_effort",
            "search-evidence-consumed",
        ]:
            if token not in readme_usage:
                errors.append(f"README.md usage-aware model routing: missing {token}")

    readme_ru_usage = markdown_section(readme_ru, "## Как работает usage-aware routing моделей")
    if not readme_ru_usage:
        errors.append("README.ru.md: missing usage-aware model-routing section")
    else:
        for token in [
            "exact custom agent `openbuild_search_separate`",
            "routing receipt",
            "fallback_reason",
            "Поиск всегда сначала пытается использовать подтверждённый separate-usage route",
            "circuit breaker на текущий run",
            "не скрейпит приватную usage page",
            "risk-matched writer",
            "openbuild_implementation_fast",
            "openbuild_implementation_balanced",
            "Implementation routing receipt",
            "implementation-handoff-accepted",
            "Progressive review применяет то же разделение `agent_name`/`task_name`",
            "openbuild_review_balanced",
            "openbuild_review_strongest",
            "Review routing receipt",
            "review-agent-activated",
            "creation-bound exit code zero",
            "valid result evidence",
            "fast → balanced → strong → strongest",
            "Эскалация",
            "model_reasoning_effort",
            "search-evidence-consumed",
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
        (SKILL / "references" / "spec-template.md", "Implementation routing receipt:"),
        (SKILL / "references" / "spec-template.md", "Review routing receipt:"),
    ]:
        if token not in read_text(path, errors):
            fail(errors, f"{path.name}: missing minimality contract {token}")

    metadata_text = read_text(SKILL / "agents" / "openai.yaml", errors)
    if 'allow_implicit_invocation: false' not in metadata_text:
        fail(errors, "agents/openai.yaml: implicit invocation must be disabled")
    if "this Build skill" not in metadata_text or "auto mode" not in metadata_text:
        fail(errors, "agents/openai.yaml: default prompt must be invocation-neutral and select auto mode")

    runner_text = read_text(AGENT_RUNNER, errors)
    for token in [
        "codex-exec-explicit-model",
        "model_reasoning_effort",
        "turn.completed",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "ChatGPT",
        "Do not spawn or delegate to another agent",
        "features.multi_agent=false",
        "forced_login_method",
        "model_provider",
        "--lease-id",
        "process_tree_stopped",
        "activate",
        "process_identity",
        "process_identity_from_popen",
        "create_windows_kill_job",
        "windows_directory_is_private",
        "darwin_process_start_time",
        "ps_process_group_status",
        "codex_exit_evidence",
        "codex-exit.json",
        "ACTIVE_WORKER_FINALIZING",
        "process_tree_record_state",
        "refusing group signal",
        "activation does not match the live creation-bound Codex process",
        "communicate_after_activation",
        "process_record_state",
        "model_providers",
        "final_result_error",
        "prompt.md",
        "Python 3.11",
        "startup cleanup is unconfirmed",
    ]:
        if token not in runner_text:
            fail(errors, f"agent_runner.py: missing explicit-model contract {token}")
    fixed_search_resolution = runner_text.find('if agent_name == "openbuild_search_separate":')
    custom_scope_resolution = runner_text.find(
        'scopes = [repo.resolve() / ".codex" / "agents", codex_home.resolve() / "agents"]'
    )
    if (
        fixed_search_resolution < 0
        or custom_scope_resolution < 0
        or fixed_search_resolution > custom_scope_resolution
    ):
        fail(
            errors,
            "agent_runner.py: packaged Spark profile must resolve before every project/user custom scope",
        )
    windows_job_position = runner_text.find("ACTIVE_WINDOWS_JOB = create_windows_kill_job()")
    worker_auth_position = runner_text.find(
        'require_chatgpt_login(request["command"][0], environment)'
    )
    if windows_job_position < 0 or worker_auth_position < 0 or windows_job_position > worker_auth_position:
        fail(errors, "agent_runner.py: Windows Job Object must exist before worker auth subprocess")

    packaged_profile_text = read_text(PACKAGED_SEARCH_PROFILE, errors)
    try:
        packaged_profile = tomllib.loads(packaged_profile_text)
    except tomllib.TOMLDecodeError as exc:
        fail(errors, f"openbuild_search_separate.toml: invalid TOML ({exc})")
        packaged_profile = {}
    errors.extend(validate_packaged_search_profile(packaged_profile))

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
        "openbuild_search_separate",
        "openbuild_search_fallback",
        "openbuild_implementation_fast",
        "openbuild_implementation_balanced",
        "openbuild_implementation_strongest",
        "openbuild_review_fast",
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
    review_protocol_text = read_text(REVIEW_PROTOCOL, errors)
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
            review_protocol_text,
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
        model_scan_text = text.replace(PACKAGED_SEARCH_MODEL, "")
        if fixed_model.search(model_scan_text):
            fail(errors, f"{relative}: fixed model slug is not allowed")
        assignment = active_model_assignment.search(text)
        if assignment and path != ROOT / "scripts" / "test_agent_runner.py" and not (
            path == PACKAGED_SEARCH_PROFILE and assignment.group(1) == PACKAGED_SEARCH_MODEL
        ):
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
