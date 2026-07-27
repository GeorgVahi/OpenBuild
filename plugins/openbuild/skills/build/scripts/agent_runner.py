#!/usr/bin/env python3
"""Run an OpenBuild custom-agent profile through an explicit Codex CLI model selection."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple

if sys.version_info < (3, 11):
    raise SystemExit("OpenBuild agent_runner.py requires Python 3.11 or newer")

import tomllib

# The control plane is intentionally private and separate from the public
# receipt schema.  The script is also loaded directly by focused unit tests.
_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)
from recovery_state import (
    RecoveryRegistry,
    RecoveryStateError,
    durable_write_private_bytes,
    durable_write_private_json,
)
from discovery_contract import (
    DiscoveryContractError,
    compute_worktree_fingerprint,
    read_regular_file_no_follow,
    validate_discovery_result,
)
from project_lanes import ProjectLaneCoordinator, ProjectLaneError
from project_migration import TRANSITION_IDS
from project_runtime import ProjectRuntimeCoordinator, ProjectRuntimeError
from project_state import (
    ProjectStateError,
    ProjectStateStore,
    _absolute_no_follow,
    _assert_no_link_or_reparse_ancestors,
)


SUPPORTED_AGENTS = {
    "openbuild_search_separate",
    "openbuild_search_balanced",
    "openbuild_search_strong",
    "openbuild_search_strongest",
    "openbuild_implementation_fast",
    "openbuild_implementation_luna_xhigh",
    "openbuild_implementation_balanced",
    "openbuild_implementation_strong",
    "openbuild_implementation_sol_high",
    "openbuild_implementation_strongest",
    "openbuild_review_fast",
    "openbuild_review_luna_xhigh",
    "openbuild_review_balanced",
    "openbuild_review_strong",
    "openbuild_review_sol_high",
    "openbuild_review_strongest",
}
AGENT_NAME = re.compile(r"^[a-z0-9_]+$")
LEASE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
API_CREDENTIALS = {"CODEX_API_KEY", "OPENAI_API_KEY"}
PROVIDER_ENVIRONMENT_OVERRIDES = {
    "CHATGPT_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
}
TERMINAL_EVENTS = {"turn.completed", "turn.failed"}
RAW_SEARCH_ERROR_TYPES = {
    "model_not_found",
    "model_not_available",
    "model_access_denied",
    "usage_limit_exceeded",
}
NON_ERROR_JSONL_EVENT_TYPES = {
    "thread.started",
    "turn.started",
    "item.started",
    "item.updated",
    "item.completed",
    "message",
}
SCHEMA_VERSION = 1
OBSERVATION_BUDGET_SECONDS = 900
NONRECOVERY_ALLOWED_SET_DOMAIN = b"openbuild-nonrecovery-allowed-set-v1\0"
LEGACY_REVIEW_PROGRESS_DOMAIN = b"openbuild.review-progress.v1\0"
REVIEW_PROGRESS_DOMAIN = b"openbuild.review-progress.v2\0"
REVIEW_LEDGER_DOMAIN = b"openbuild.review-progress-ledger.v1\0"
REVIEW_DISPATCH_DOMAIN = b"openbuild.review-dispatch.v1\0"
BROWSER_QA_FINDING_DOMAIN = b"openbuild.review-finding.v1\0"
BROWSER_QA_DOMAIN = b"openbuild.browser-qa.v1\0"
ROOT_COMPLETION_SOURCE_SCHEMA = "openbuild.root-completion-source.v1"
REVIEW_MAX_STEPS_PER_DIFF = 3
REVIEW_LEDGER_MAX_ENTRIES = 256
REVIEW_LEDGER_MAX_BYTES = 1024 * 1024
RUN_HANDLE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{10}$")
PACKAGED_PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
SEARCH_DEVELOPER_INSTRUCTIONS = (
    "You are the already-delegated read-only Explorer. Do not spawn or delegate to another agent.\n\n"
    "When code discovery, broad rg, route or symbol lookup, owner mapping, or cross-file evidence gathering is needed:\n"
    "- perform repository search, rg, rg --files, Get-Content, and local file reading yourself;\n"
    "- do not edit files, write configuration, make product or architecture decisions, commit, push, or answer the user;\n"
    "- return exactly one UTF-8 JSON object and no Markdown fences or surrounding prose;\n"
    "- use schema openbuild.discovery.v1 with exactly these fields: schema, worktree_fingerprint, summary, owners, couplings, tests, flows, constraints, uncertainties;\n"
    "- copy the runtime-provided worktree_fingerprint object exactly; it is owner-verified before and after the run;\n"
    "- make owners, couplings, tests, and flows flat arrays whose items directly use exactly path, line_start, line_end, symbol, reason and optional kind/related_path; make owners and tests non-empty;\n"
    "- make constraints and uncertainties arrays of bounded strings, never evidence objects or nested structures;\n"
    "- keep every path repository-relative and every line range tight: line_end - line_start + 1 must be at most 200, and one item must never combine distant symbols; include relevant constraints, uncertainties, negative results, and the search stop condition in the bounded fields;\n"
    "- never cite generated build-output, vendor, dependency, cache, coverage, or artifact paths; source directories named build remain valid evidence; keep raw logs and large file dumps out of the result.\n\n"
    "The main process validates the strict JSON, paths, ranges, owner/test evidence, and fingerprint before consuming it."
)
ACTIVE_WORKER_CHILD: Any | None = None
ACTIVE_WINDOWS_JOB: Any | None = None
ACTIVE_WORKER_FINALIZING = False
_WINDOWS_CREATE_SUSPENDED = 0x00000004
_CLONE_PIDFD = 0x00001000
_CLONE_INTO_CGROUP = 0x200000000
_SYS_CLONE3 = 435
ROUTING_RUNG_BY_AGENT = {
    **{
        f"openbuild_{role}_fast": "luna-medium"
        for role in ("implementation", "review")
    },
    **{
        f"openbuild_{role}_luna_xhigh": "luna-xhigh"
        for role in ("implementation", "review")
    },
    **{
        f"openbuild_{role}_balanced": "terra-medium"
        for role in ("implementation", "review")
    },
    **{
        f"openbuild_{role}_strong": "terra-xhigh"
        for role in ("implementation", "review")
    },
    **{
        f"openbuild_{role}_sol_high": "sol-high"
        for role in ("implementation", "review")
    },
    **{
        f"openbuild_{role}_strongest": "sol-xhigh"
        for role in ("implementation", "review")
    },
}
KNOWN_MODEL_EFFORT_RUNG = {
    ("gpt-5.6-luna", "medium"): "luna-medium",
    ("gpt-5.6-luna", "xhigh"): "luna-xhigh",
    ("gpt-5.6-terra", "medium"): "terra-medium",
    ("gpt-5.6-terra", "xhigh"): "terra-xhigh",
    ("gpt-5.6-sol", "high"): "sol-high",
    ("gpt-5.6-sol", "xhigh"): "sol-xhigh",
}
KNOWN_ROUTING_MODELS = {model for model, _ in KNOWN_MODEL_EFFORT_RUNG}


class RunnerError(RuntimeError):
    """A safe, user-actionable runner failure."""


class AgentProfile(NamedTuple):
    name: str
    description: str
    model: str
    reasoning_effort: str
    sandbox: str
    developer_instructions: str
    source: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def activation_window(now: datetime | None = None) -> dict[str, str]:
    """Return the immutable public observation window for a newly activated run."""
    activated_at = now or datetime.now(timezone.utc)
    if activated_at.tzinfo is None:
        raise RunnerError("activation timestamp must be timezone-aware")
    activated_at = activated_at.astimezone(timezone.utc)
    return {
        "activated_at": activated_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "observation_started_at": activated_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "observation_deadline_at": (activated_at + timedelta(seconds=OBSERVATION_BUDGET_SECONDS))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_lower_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RunnerError(f"{label} must be a 64-character lowercase SHA-256 digest")
    return value


def automatic_continuation_policy(
    *,
    incomplete: bool,
    attributable_partial_diff: bool,
    root_completion_audited: bool,
    requested_action: str,
) -> dict[str, Any]:
    """Classify a closed incomplete outcome without manufacturing authority.

    The audit is deliberately first: even a routine review/QA continuation
    cannot consume the existing root-completion authority until the owner has
    durably audited the partial diff.  A recovery writer is still a new
    security-relevant executor, never a continuation shortcut.
    """
    if requested_action not in {"run", "direct-fix", "qa", "review", "new-writer"}:
        raise RunnerError("automatic continuation action is unsupported")
    if not incomplete:
        return {"status": "not-applicable", "permission_prompt": False}
    if not attributable_partial_diff:
        return {
            "status": "blocked",
            "reason": "partial-diff-attribution-unavailable",
            "permission_prompt": False,
        }
    if not root_completion_audited:
        return {
            "status": "blocked",
            "reason": "root-completion-audit-required",
            "permission_prompt": False,
        }
    if requested_action == "new-writer":
        return {
            "status": "decision-required",
            "reason": "new-writer-security-action",
            "permission_prompt": True,
        }
    return {
        "status": "continue-automatically",
        "action": requested_action,
        "permission_prompt": False,
    }


def automatic_continuation_record(
    *,
    root_completion_audit: Mapping[str, Any],
    requested_action: str,
) -> dict[str, Any]:
    """Bind the continuation decision to the already durable root audit."""
    if (
        not isinstance(root_completion_audit, Mapping)
        or root_completion_audit.get("event") != "root-completion-authorized"
        or root_completion_audit.get("automatic") is not True
        or root_completion_audit.get("writer_action") != "none"
    ):
        raise RunnerError("automatic continuation requires a valid root-completion audit")
    audit_digest = sha256_bytes(_canonical_json_bytes(root_completion_audit))
    policy = automatic_continuation_policy(
        incomplete=True,
        attributable_partial_diff=True,
        root_completion_audited=True,
        requested_action=requested_action,
    )
    record: dict[str, Any] = {
        "schema": "openbuild.automatic-continuation.v1",
        "root_completion_audit_digest": audit_digest,
        "requested_action": requested_action,
        "policy": policy,
    }
    record["continuation_digest"] = sha256_bytes(
        b"openbuild.automatic-continuation.v1\0" + _canonical_json_bytes(record)
    )
    return record


def _canonical_finding_keys(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise RunnerError(f"{label} must be a list of finding_key values")
    keys = [_require_lower_hex(item, f"{label} finding_key") for item in value]
    if len(keys) != len(set(keys)):
        raise RunnerError(f"{label} contains a duplicate finding_key")
    return sorted(keys)


def review_finding_key(*, owner: str, contract: str, consequence: str) -> str:
    """Derive a wording-independent key from the finding's semantic identity."""
    fields: dict[str, str] = {}
    for label, value in (
        ("owner", owner),
        ("contract", contract),
        ("consequence", consequence),
    ):
        if not isinstance(value, str):
            raise RunnerError(f"review finding {label} must be a string")
        normalized = " ".join(value.strip().casefold().split())
        if not normalized or len(normalized.encode("utf-8")) > 1024:
            raise RunnerError(f"review finding {label} is empty or too large")
        fields[label] = normalized
    return sha256_bytes(BROWSER_QA_FINDING_DOMAIN + _canonical_json_bytes(fields))


def review_progress_record(
    *,
    specification_lineage_digest: str,
    specification_revision: str,
    full_diff_digest: str,
    validation_digest: str,
    acceptance_criteria_digest: str,
    open_finding_keys: list[str],
    closed_finding_keys: list[str],
) -> dict[str, Any]:
    """Create the canonical, path-free review-progress value for one diff epoch."""
    if not isinstance(specification_revision, str) or not re.fullmatch(r"R-[0-9]{3,}", specification_revision):
        raise RunnerError("review progress specification revision is invalid")
    open_keys = _canonical_finding_keys(open_finding_keys, "open finding keys")
    closed_keys = _canonical_finding_keys(closed_finding_keys, "closed finding keys")
    if set(open_keys) & set(closed_keys):
        raise RunnerError("review progress finding_key cannot be both open and closed")
    record: dict[str, Any] = {
        "schema": "openbuild.review-progress.v2",
        "specification_lineage_digest": _require_lower_hex(
            specification_lineage_digest, "review progress specification lineage"
        ),
        "specification_revision": specification_revision,
        "full_diff_digest": _require_lower_hex(full_diff_digest, "review progress full diff"),
        "validation_digest": _require_lower_hex(validation_digest, "review progress validation"),
        "acceptance_criteria_digest": _require_lower_hex(
            acceptance_criteria_digest, "review progress acceptance criteria"
        ),
        "open_finding_keys": open_keys,
        "closed_finding_keys": closed_keys,
    }
    record["progress_digest"] = sha256_bytes(REVIEW_PROGRESS_DOMAIN + _canonical_json_bytes(record))
    return record


def _legacy_review_progress_record(
    *,
    specification_revision: str,
    full_diff_digest: str,
    validation_digest: str,
    acceptance_criteria_digest: str,
    open_finding_keys: list[str],
    closed_finding_keys: list[str],
) -> dict[str, Any]:
    """Rebuild a 2.4.1-pre-release progress value so existing private ledgers remain readable."""
    if not isinstance(specification_revision, str) or not re.fullmatch(r"R-[0-9]{3,}", specification_revision):
        raise RunnerError("review progress specification revision is invalid")
    open_keys = _canonical_finding_keys(open_finding_keys, "open finding keys")
    closed_keys = _canonical_finding_keys(closed_finding_keys, "closed finding keys")
    if set(open_keys) & set(closed_keys):
        raise RunnerError("review progress finding_key cannot be both open and closed")
    record: dict[str, Any] = {
        "schema": "openbuild.review-progress.v1",
        "specification_revision": specification_revision,
        "full_diff_digest": _require_lower_hex(full_diff_digest, "review progress full diff"),
        "validation_digest": _require_lower_hex(validation_digest, "review progress validation"),
        "acceptance_criteria_digest": _require_lower_hex(
            acceptance_criteria_digest, "review progress acceptance criteria"
        ),
        "open_finding_keys": open_keys,
        "closed_finding_keys": closed_keys,
    }
    record["progress_digest"] = sha256_bytes(
        LEGACY_REVIEW_PROGRESS_DOMAIN + _canonical_json_bytes(record)
    )
    return record


def _validate_review_progress(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunnerError(f"{label} must be an object")
    legacy_fields = {
        "schema",
        "specification_revision",
        "full_diff_digest",
        "validation_digest",
        "acceptance_criteria_digest",
        "open_finding_keys",
        "closed_finding_keys",
        "progress_digest",
    }
    fields = legacy_fields | {"specification_lineage_digest"}
    if value.get("schema") == "openbuild.review-progress.v1" and set(value) == legacy_fields:
        record = _legacy_review_progress_record(
            specification_revision=value.get("specification_revision"),
            full_diff_digest=value.get("full_diff_digest"),
            validation_digest=value.get("validation_digest"),
            acceptance_criteria_digest=value.get("acceptance_criteria_digest"),
            open_finding_keys=value.get("open_finding_keys"),
            closed_finding_keys=value.get("closed_finding_keys"),
        )
    elif value.get("schema") == "openbuild.review-progress.v2" and set(value) == fields:
        record = review_progress_record(
            specification_lineage_digest=value.get("specification_lineage_digest"),
            specification_revision=value.get("specification_revision"),
            full_diff_digest=value.get("full_diff_digest"),
            validation_digest=value.get("validation_digest"),
            acceptance_criteria_digest=value.get("acceptance_criteria_digest"),
            open_finding_keys=value.get("open_finding_keys"),
            closed_finding_keys=value.get("closed_finding_keys"),
        )
    else:
        raise RunnerError(f"{label} fields are incomplete or unknown")
    if value.get("schema") != record["schema"] or value.get("progress_digest") != record["progress_digest"]:
        raise RunnerError(f"{label} canonical digest drifted")
    return record


def review_progress_decision(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, str]:
    """Fail closed when another review epoch has no independently visible progress."""
    before = _validate_review_progress(previous, "previous review progress")
    after = _validate_review_progress(current, "current review progress")
    if before.get("specification_lineage_digest") != after.get("specification_lineage_digest"):
        raise RunnerError("review progress specification lineage drifted")
    if before["specification_revision"] != after["specification_revision"]:
        before_revision = int(before["specification_revision"].removeprefix("R-"))
        after_revision = int(after["specification_revision"].removeprefix("R-"))
        if after_revision <= before_revision:
            raise RunnerError("review progress specification revision did not advance")
        if before["full_diff_digest"] == after["full_diff_digest"]:
            raise RunnerError("review progress specification revision changed without a new diff")
    if before["progress_digest"] == after["progress_digest"]:
        return {"status": "automation-exhausted", "reason": "unchanged-progress-digest"}
    before_open = set(before["open_finding_keys"])
    after_open = set(after["open_finding_keys"])
    before_closed = set(before["closed_finding_keys"])
    after_closed = set(after["closed_finding_keys"])
    if not before_closed <= after_closed:
        raise RunnerError("review progress reopened an already closed finding_key")
    removed = before_open - after_open
    if not removed <= after_closed:
        raise RunnerError("review progress dropped a finding_key without closing it")
    persistent = sorted(before_open & after_open)
    if persistent:
        return {"status": "automation-exhausted", "reason": "unchanged-finding-key"}
    closed = after_closed - before_closed
    validation_or_ac_changed = (
        before["validation_digest"] != after["validation_digest"]
        or before["acceptance_criteria_digest"] != after["acceptance_criteria_digest"]
    )
    if (
        before["full_diff_digest"] != after["full_diff_digest"]
        and not validation_or_ac_changed
        and not closed
    ):
        return {"status": "automation-exhausted", "reason": "diff-only-churn"}
    return {"status": "progressed", "reason": "validation-ac-or-finding-change"}


def _review_progress_paths(registry: RecoveryRegistry) -> tuple[Path, Path]:
    return (
        registry.directory / "review-progress-ledger-v1.json",
        registry.directory / "review-progress-ledger-v1.lock",
    )


def _review_dispatch_entry(
    *,
    run_id: str,
    agent_name: str,
    task_name: str,
    progress: Mapping[str, Any],
    decision: Mapping[str, str],
) -> dict[str, Any]:
    if (
        not isinstance(run_id, str)
        or not run_id
        or len(run_id.encode("utf-8")) > 255
        or "/" in run_id
        or "\\" in run_id
    ):
        raise RunnerError("review dispatch run identity is invalid")
    if agent_name not in SUPPORTED_AGENTS or not agent_name.startswith("openbuild_review_"):
        raise RunnerError("review dispatch profile is invalid")
    if not isinstance(task_name, str) or not task_name.strip():
        raise RunnerError("review dispatch task is empty")
    if set(decision) != {"status", "reason"} or decision.get("status") not in {
        "first-review",
        "progressed",
    }:
        raise RunnerError("review dispatch progress decision is not eligible")
    entry: dict[str, Any] = {
        "schema": "openbuild.review-dispatch.v1",
        "run_id": run_id,
        "agent_name": agent_name,
        "task_name": task_name.strip(),
        "progress": _validate_review_progress(progress, "review dispatch progress"),
        "decision": dict(decision),
    }
    entry["entry_digest"] = sha256_bytes(
        REVIEW_DISPATCH_DOMAIN + _canonical_json_bytes(entry)
    )
    return entry


def _review_progress_ledger(
    *,
    workspace_key: str,
    entries: list[Mapping[str, Any]],
) -> dict[str, Any]:
    _require_lower_hex(workspace_key, "review progress workspace key")
    if len(entries) > REVIEW_LEDGER_MAX_ENTRIES:
        raise RunnerError("review progress ledger entry limit exceeded")
    canonical_entries: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for raw in entries:
        if not isinstance(raw, Mapping) or set(raw) != {
            "schema",
            "run_id",
            "agent_name",
            "task_name",
            "progress",
            "decision",
            "entry_digest",
        }:
            raise RunnerError("review progress ledger entry is incomplete or unknown")
        entry = _review_dispatch_entry(
            run_id=raw.get("run_id"),
            agent_name=raw.get("agent_name"),
            task_name=raw.get("task_name"),
            progress=raw.get("progress"),
            decision=raw.get("decision"),
        )
        if raw.get("schema") != entry["schema"] or raw.get("entry_digest") != entry["entry_digest"]:
            raise RunnerError("review progress ledger entry digest drifted")
        if entry["run_id"] in seen_runs:
            raise RunnerError("review progress ledger repeats a run identity")
        seen_runs.add(entry["run_id"])
        canonical_entries.append(entry)
    ledger: dict[str, Any] = {
        "schema": "openbuild.review-progress-ledger.v1",
        "workspace_key": workspace_key,
        "entries": canonical_entries,
    }
    ledger["ledger_digest"] = sha256_bytes(
        REVIEW_LEDGER_DOMAIN + _canonical_json_bytes(ledger)
    )
    if len(_canonical_json_bytes(ledger)) > REVIEW_LEDGER_MAX_BYTES:
        raise RunnerError("review progress ledger byte limit exceeded")
    return ledger


def _read_review_progress_ledger(registry: RecoveryRegistry) -> dict[str, Any]:
    path, _lock_path = _review_progress_paths(registry)
    if not path.is_file():
        return _review_progress_ledger(
            workspace_key=registry.workspace_key,
            entries=[],
        )
    try:
        raw = _read_existing_private_prompt_bytes(
            path,
            maximum=REVIEW_LEDGER_MAX_BYTES,
        )
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RunnerError) as exc:
        raise RunnerError("review progress ledger is unreadable") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "workspace_key",
        "entries",
        "ledger_digest",
    }:
        raise RunnerError("review progress ledger is incomplete or unknown")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise RunnerError("review progress ledger entries are malformed")
    ledger = _review_progress_ledger(
        workspace_key=value.get("workspace_key"),
        entries=entries,
    )
    if (
        value.get("schema") != ledger["schema"]
        or value.get("workspace_key") != registry.workspace_key
        or value.get("ledger_digest") != ledger["ledger_digest"]
    ):
        raise RunnerError("review progress ledger binding drifted")
    return ledger


def review_progress_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    values = (
        getattr(args, "review_specification_lineage_digest", None),
        getattr(args, "review_specification_revision", None),
        getattr(args, "review_full_diff_digest", None),
        getattr(args, "review_validation_digest", None),
        getattr(args, "review_acceptance_criteria_digest", None),
    )
    finding_values = (
        getattr(args, "review_open_finding_key", None) or [],
        getattr(args, "review_closed_finding_key", None) or [],
    )
    is_review = str(getattr(args, "agent", "")).startswith("openbuild_review_")
    if not is_review:
        if any(value is not None for value in values) or any(finding_values):
            raise RunnerError("review progress arguments are valid only for review agents")
        return None
    if any(value is None for value in values):
        raise RunnerError(
            "review dispatch requires specification lineage, revision, full-diff, validation, and acceptance-criteria digests"
        )
    return review_progress_record(
        specification_lineage_digest=values[0],
        specification_revision=values[1],
        full_diff_digest=values[2],
        validation_digest=values[3],
        acceptance_criteria_digest=values[4],
        open_finding_keys=list(finding_values[0]),
        closed_finding_keys=list(finding_values[1]),
    )


def _review_progress_dispatch_decision(
    ledger: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, str]:
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise RunnerError("review progress ledger entries are malformed")
    current_record = _validate_review_progress(current, "current review progress")
    lineage = current_record.get("specification_lineage_digest")
    same_lineage_entries = [
        entry
        for entry in entries
        if isinstance(entry, Mapping)
        and isinstance(entry.get("progress"), Mapping)
        and entry["progress"].get("specification_lineage_digest") == lineage
    ]
    same_diff_attempts = sum(
        1
        for entry in same_lineage_entries
        if isinstance(entry, Mapping)
        and isinstance(entry.get("progress"), Mapping)
        and entry["progress"].get("full_diff_digest") == current_record["full_diff_digest"]
    )
    if same_diff_attempts >= REVIEW_MAX_STEPS_PER_DIFF:
        raise RunnerError("review automation exhausted for the immutable full diff")
    if not same_lineage_entries:
        return {"status": "first-review", "reason": "no-prior-review-progress-for-lineage"}
    previous = same_lineage_entries[-1].get("progress")
    decision = review_progress_decision(previous, current_record)
    if decision["status"] != "progressed":
        raise RunnerError(f"review automation exhausted: {decision['reason']}")
    return decision


def preview_review_dispatch(
    *,
    repo: Path,
    progress: Mapping[str, Any],
) -> dict[str, Any]:
    """Consult owner-private review state without mutating it."""
    registry = RecoveryRegistry(repo)
    ensure_private_run_dir(registry.directory)
    with registry._lock():
        ledger = _read_review_progress_ledger(registry)
        decision = _review_progress_dispatch_decision(ledger, progress)
    return {
        "workspace_key": registry.workspace_key,
        "expected_ledger_digest": ledger["ledger_digest"],
        "progress": _validate_review_progress(progress, "review dispatch progress"),
        "decision": decision,
    }


def commit_review_dispatch(
    *,
    repo: Path,
    run_id: str,
    agent_name: str,
    task_name: str,
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one review attempt only when the consulted ledger is unchanged."""
    if not isinstance(preview, Mapping) or set(preview) != {
        "workspace_key",
        "expected_ledger_digest",
        "progress",
        "decision",
    }:
        raise RunnerError("review dispatch preview is incomplete or unknown")
    registry = RecoveryRegistry(repo)
    ensure_private_run_dir(registry.directory)
    if preview.get("workspace_key") != registry.workspace_key:
        raise RunnerError("review dispatch workspace binding drifted")
    path, _lock_path = _review_progress_paths(registry)
    with registry._lock():
        ledger = _read_review_progress_ledger(registry)
        if ledger["ledger_digest"] != preview.get("expected_ledger_digest"):
            raise RunnerError("review progress changed before dispatch")
        decision = _review_progress_dispatch_decision(ledger, preview.get("progress"))
        if decision != preview.get("decision"):
            raise RunnerError("review dispatch progress decision drifted")
        entry = _review_dispatch_entry(
            run_id=run_id,
            agent_name=agent_name,
            task_name=task_name,
            progress=preview["progress"],
            decision=decision,
        )
        updated = _review_progress_ledger(
            workspace_key=registry.workspace_key,
            entries=[*ledger["entries"], entry],
        )
        try:
            durable_write_private_json(path, updated)
        except (OSError, RecoveryStateError) as exc:
            raise RunnerError(f"durable review progress append failed closed: {exc}") from exc
    return {
        "schema": entry["schema"],
        "entry_digest": entry["entry_digest"],
        "progress_digest": entry["progress"]["progress_digest"],
        "decision": entry["decision"],
    }


def browser_qa_receipt(
    *,
    specification_revision: str,
    pre_worktree_digest: str,
    post_worktree_digest: str,
    argv_digest: str,
    scenario_manifest_digest: str,
    network_guard_digest: str,
    nonce: str,
    child_pid: int,
    child_identity: str,
    exit_code: int | None,
    process_tree_stopped: bool,
    observed_external_requests: int,
    observed_external_actions: int,
    runtime: str = "local-browser",
    scenario_count: int = 1,
    check_count: int = 1,
    passed_checks: int = 1,
) -> dict[str, Any]:
    """Project one verified private browser-substitute observation safely.

    This function accepts only runner-owned observations and projects digests;
    it never emits a raw path, PID, process identity, cookie, environment, or
    nonce.  Callers must retain the private lifecycle evidence separately.
    """
    if not isinstance(specification_revision, str) or not re.fullmatch(r"R-[0-9]{3,}", specification_revision):
        raise RunnerError("browser QA specification revision is invalid")
    for value, label in (
        (pre_worktree_digest, "browser QA pre-worktree"),
        (post_worktree_digest, "browser QA post-worktree"),
        (argv_digest, "browser QA argv"),
        (scenario_manifest_digest, "browser QA scenario manifest"),
        (network_guard_digest, "browser QA network guard"),
        (nonce, "browser QA nonce"),
    ):
        _require_lower_hex(value, label)
    if pre_worktree_digest != post_worktree_digest:
        raise RunnerError("browser QA worktree diff drifted")
    if type(child_pid) is not int or child_pid <= 0 or not isinstance(child_identity, str) or not child_identity:
        raise RunnerError("browser QA child creation identity is unavailable")
    if type(exit_code) is not int or exit_code != 0:
        raise RunnerError("browser QA substitute exit is not successful")
    if process_tree_stopped is not True:
        raise RunnerError("browser QA substitute process tree is live or unknown")
    if type(observed_external_requests) is not int or type(observed_external_actions) is not int:
        raise RunnerError("browser QA external observation is malformed")
    if observed_external_requests != 0 or observed_external_actions != 0:
        raise RunnerError("browser QA observed external request or action")
    if (
        not isinstance(runtime, str)
        or not runtime
        or len(runtime.encode("utf-8")) > 128
        or type(scenario_count) is not int
        or type(check_count) is not int
        or type(passed_checks) is not int
        or scenario_count <= 0
        or check_count <= 0
        or passed_checks != check_count
    ):
        raise RunnerError("browser QA scenario/check evidence is incomplete")
    private_binding = {
        "nonce": nonce,
        "child_pid": child_pid,
        "child_identity": child_identity,
        "argv_digest": argv_digest,
        "scenario_manifest_digest": scenario_manifest_digest,
        "network_guard_digest": network_guard_digest,
        "runtime": runtime,
        "scenario_count": scenario_count,
        "check_count": check_count,
        "passed_checks": passed_checks,
    }
    receipt: dict[str, Any] = {
        "schema": "openbuild.browser-qa.v1",
        "specification_revision": specification_revision,
        "pre_worktree_digest": pre_worktree_digest,
        "post_worktree_digest": post_worktree_digest,
        "argv_digest": argv_digest,
        "scenario_manifest_digest": scenario_manifest_digest,
        "network_guard_digest": network_guard_digest,
        "runtime": runtime,
        "scenario_count": scenario_count,
        "check_count": check_count,
        "passed_checks": passed_checks,
        "evidence_limitation": "isolated-local-substitute",
        "observation_digest": sha256_bytes(BROWSER_QA_DOMAIN + _canonical_json_bytes(private_binding)),
    }
    receipt["receipt_digest"] = sha256_bytes(BROWSER_QA_DOMAIN + _canonical_json_bytes(receipt))
    return receipt


def verify_browser_qa_receipt(
    *,
    receipt: Mapping[str, Any],
    private_evidence: Mapping[str, Any],
    expected_specification_revision: str,
    expected_worktree_digest: str,
    expected_argv_digest: str,
    expected_scenario_manifest_digest: str,
    consumed_receipt_digests: set[str],
) -> dict[str, Any]:
    """Re-derive one current-diff receipt and consume it exactly once."""
    evidence_fields = {
        "specification_revision",
        "pre_worktree_digest",
        "post_worktree_digest",
        "argv_digest",
        "scenario_manifest_digest",
        "network_guard_digest",
        "nonce",
        "child_pid",
        "child_identity",
        "exit_code",
        "process_tree_stopped",
        "observed_external_requests",
        "observed_external_actions",
        "runtime",
        "scenario_count",
        "check_count",
        "passed_checks",
    }
    if not isinstance(private_evidence, Mapping) or set(private_evidence) != evidence_fields:
        raise RunnerError("browser QA private evidence is incomplete or self-authored")
    expected = browser_qa_receipt(**dict(private_evidence))
    if not isinstance(receipt, Mapping) or dict(receipt) != expected:
        raise RunnerError("browser QA receipt is stale, tampered, or replaced")
    if (
        expected["specification_revision"] != expected_specification_revision
        or expected["pre_worktree_digest"] != expected_worktree_digest
        or expected["post_worktree_digest"] != expected_worktree_digest
        or expected["argv_digest"] != expected_argv_digest
        or expected["scenario_manifest_digest"] != expected_scenario_manifest_digest
    ):
        raise RunnerError("browser QA receipt does not bind the current revision or command")
    digest = expected["receipt_digest"]
    if digest in consumed_receipt_digests:
        raise RunnerError("browser QA receipt replayed")
    consumed_receipt_digests.add(digest)
    return expected


def _browser_qa_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Return the deliberately credential-free environment for a QA child."""
    blocked_fragments = (
        "API_KEY",
        "TOKEN",
        "SECRET",
        "COOKIE",
        "PASSWORD",
        "CREDENTIAL",
        "AUTH",
        "PROXY",
    )
    blocked_exact = PROVIDER_ENVIRONMENT_OVERRIDES | {
        "OPENAI_PROVIDER",
        "CODEX_PROVIDER",
        "OPENBUILD_RUNTIME_PORT",
    }
    return {
        key: value
        for key, value in scrub_api_credentials(environment).items()
        if key.upper() not in blocked_exact
        and not any(fragment in key.upper() for fragment in blocked_fragments)
    }


def _validate_browser_qa_scenario(value: Mapping[str, Any]) -> tuple[list[str], str]:
    """Validate the small immutable substitute manifest without publishing it."""
    if not isinstance(value, Mapping) or set(value) != {"schema", "origins"}:
        raise RunnerError("browser QA scenario manifest is incomplete or unknown")
    if value.get("schema") != "openbuild.browser-qa-scenario.v1":
        raise RunnerError("browser QA scenario manifest schema is unsupported")
    origins = value.get("origins")
    if not isinstance(origins, list) or not origins or any(not isinstance(item, str) for item in origins):
        raise RunnerError("browser QA scenario origins are invalid")
    normalized: list[str] = []
    for origin in origins:
        if origin == "file":
            normalized.append(origin)
            continue
        match = re.fullmatch(r"http://(127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?", origin)
        if match is None:
            raise RunnerError("browser QA scenario origin is outside the loopback/file allowlist")
        normalized.append(origin)
    if len(normalized) != len(set(normalized)):
        raise RunnerError("browser QA scenario origins are duplicated")
    manifest = {"schema": value["schema"], "origins": sorted(normalized)}
    return manifest["origins"], sha256_bytes(BROWSER_QA_DOMAIN + _canonical_json_bytes(manifest))


def run_browser_qa_substitute(
    *,
    repo: Path,
    specification_revision: str,
    argv: list[str],
    scenario_manifest: Mapping[str, Any],
    network_guard: Any | None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Run one generic browser QA substitute and emit only a verified receipt.

    The guard must attach while the Windows child is still suspended and emit
    observations independently of child stdout/stderr.  No trusted guard is
    currently synthesized from project code; absence is a fail-closed result.
    """
    if not isinstance(repo, Path) or not repo.is_dir():
        raise RunnerError("browser QA repository is unavailable")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise RunnerError("browser QA argv is malformed")
    if timeout_seconds <= 0:
        raise RunnerError("browser QA timeout is invalid")
    origins, scenario_digest = _validate_browser_qa_scenario(scenario_manifest)
    for item in argv:
        if item.startswith(("http://", "https://")) and item not in origins:
            raise RunnerError("browser QA argv is outside the loopback/file allowlist")
    if os.name != "nt":
        raise RunnerError("browser QA pre-execution network isolation is unavailable")
    if (
        network_guard is None
        or not callable(getattr(network_guard, "attach_suspended", None))
        or not callable(getattr(network_guard, "finalize", None))
    ):
        raise RunnerError("browser QA independent network guard is unavailable")
    try:
        pre = compute_worktree_fingerprint(repo).public["digest"]
    except (DiscoveryContractError, KeyError, TypeError) as exc:
        raise RunnerError("browser QA pre-worktree fingerprint is unavailable") from exc
    nonce = secrets.token_hex(32)
    argv_digest = sha256_bytes(BROWSER_QA_DOMAIN + _canonical_json_bytes({"argv": argv}))
    process: subprocess.Popen[Any] | None = None
    observation: Mapping[str, Any] | None = None
    guard_attachment: Mapping[str, Any] | None = None
    windows_job: Any | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="openbuild-browser-qa-") as profile:
            environment = _browser_qa_environment(os.environ)
            environment["OPENBUILD_BROWSER_QA_PROFILE"] = profile
            environment["OPENBUILD_BROWSER_QA_NONCE"] = nonce
            environment["OPENBUILD_BROWSER_QA_ALLOWED_ORIGINS"] = json.dumps(
                origins,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            options: dict[str, Any]
            if os.name == "nt":
                windows_job = create_windows_kill_job(bind_current=False)
                options = {
                    "creationflags": (
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.CREATE_NO_WINDOW
                        | _WINDOWS_CREATE_SUSPENDED
                    )
                }
            else:
                options = {"start_new_session": True}
            process = subprocess.Popen(
                argv,
                cwd=repo,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                **options,
            )
            identity = process_identity_from_popen(process)
            if identity is None:
                raise RunnerError("browser QA child creation identity is unavailable")
            setattr(process, "_openbuild_process_identity", identity)
            if windows_job is not None:
                assign_windows_process_to_job(windows_job, process)
                verify_windows_process_in_job(windows_job, process)
                guard_attachment = network_guard.attach_suspended(
                    process=process,
                    nonce=nonce,
                    allowed_origins=tuple(origins),
                )
                expected_origin_digest = sha256_bytes(
                    BROWSER_QA_DOMAIN
                    + _canonical_json_bytes({"allowed_origins": sorted(origins)})
                )
                if (
                    not isinstance(guard_attachment, Mapping)
                    or set(guard_attachment)
                    != {
                        "schema",
                        "guard_id",
                        "nonce",
                        "allowed_origins_digest",
                        "enforced_before_resume",
                    }
                    or guard_attachment.get("schema")
                    != "openbuild.browser-network-guard.v1"
                    or not isinstance(guard_attachment.get("guard_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", guard_attachment["guard_id"])
                    or guard_attachment.get("nonce") != nonce
                    or guard_attachment.get("allowed_origins_digest")
                    != expected_origin_digest
                    or guard_attachment.get("enforced_before_resume") is not True
                ):
                    raise RunnerError("browser QA independent network guard did not attach")
                resume_windows_suspended_process(process)
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise RunnerError("browser QA substitute exceeded its observation window") from exc
            if len(stdout) > 1024 * 1024 or len(stderr) > 1024 * 1024:
                raise RunnerError("browser QA substitute output exceeded its evidence limit")
            if process.poll() is None:
                raise RunnerError("browser QA substitute exit is unknown")
            observation = network_guard.finalize(
                attachment=guard_attachment,
                process=process,
            )
            if not isinstance(observation, Mapping) or set(observation) != {
                "schema",
                "guard_id",
                "nonce",
                "independently_observed",
                "external_requests",
                "external_actions",
                "runtime",
                "scenario_count",
                "check_count",
                "passed_checks",
            }:
                raise RunnerError("browser QA independent observation is incomplete")
            if (
                observation.get("schema") != "openbuild.browser-network-observation.v1"
                or observation.get("guard_id") != guard_attachment.get("guard_id")
                or observation.get("nonce") != nonce
                or observation.get("independently_observed") is not True
            ):
                raise RunnerError("browser QA private observation nonce drifted")
            if windows_job is not None:
                tree_deadline = time.monotonic() + 5.0
                while (
                    query_windows_job_active_processes(windows_job) != 0
                    and time.monotonic() < tree_deadline
                ):
                    time.sleep(0.05)
                tree_stopped = query_windows_job_active_processes(windows_job) == 0
            else:
                tree_stopped = process_group_status(process.pid) == "stopped"
            try:
                post = compute_worktree_fingerprint(repo).public["digest"]
            except (DiscoveryContractError, KeyError, TypeError) as exc:
                raise RunnerError("browser QA post-worktree fingerprint is unavailable") from exc
            private_evidence = {
                "specification_revision": specification_revision,
                "pre_worktree_digest": pre,
                "post_worktree_digest": post,
                "argv_digest": argv_digest,
                "scenario_manifest_digest": scenario_digest,
                "network_guard_digest": sha256_bytes(
                    BROWSER_QA_DOMAIN + _canonical_json_bytes(dict(guard_attachment))
                ),
                "nonce": nonce,
                "child_pid": process.pid,
                "child_identity": identity,
                "exit_code": process.returncode,
                "process_tree_stopped": tree_stopped,
                "observed_external_requests": observation["external_requests"],
                "observed_external_actions": observation["external_actions"],
                "runtime": observation["runtime"],
                "scenario_count": observation["scenario_count"],
                "check_count": observation["check_count"],
                "passed_checks": observation["passed_checks"],
            }
            receipt = browser_qa_receipt(**private_evidence)
            return verify_browser_qa_receipt(
                receipt=receipt,
                private_evidence=private_evidence,
                expected_specification_revision=specification_revision,
                expected_worktree_digest=pre,
                expected_argv_digest=argv_digest,
                expected_scenario_manifest_digest=scenario_digest,
                consumed_receipt_digests=set(),
            )
    finally:
        if windows_job is not None:
            try:
                if query_windows_job_active_processes(windows_job) != 0:
                    terminate_guardian_provider("windows-job", windows_job)
            finally:
                close_windows_job(windows_job)
        elif process is not None:
            group_state = process_group_status(process.pid)
            if group_state == "running":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def trusted_browser_network_guard() -> Any | None:
    """Return only an owner-provided guard; project or child evidence is never trusted."""
    return None


def browser_qa_substitute_run(args: argparse.Namespace) -> int:
    """CLI owner for the isolated substitute; fail closed when no guard exists."""
    repo = Path(args.repo).expanduser().resolve()
    scenario_path = Path(args.scenario_file).expanduser().resolve()
    if not repo.is_dir() or not scenario_path.is_file():
        raise RunnerError("browser QA repository or scenario manifest is unavailable")
    try:
        raw = read_regular_file_no_follow(scenario_path)
        if raw is None or len(raw) > 64 * 1024:
            raise RunnerError("browser QA scenario manifest is unavailable or too large")
        scenario = json.loads(raw.decode("utf-8"))
    except (DiscoveryContractError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError("browser QA scenario manifest is unreadable") from exc
    if not isinstance(scenario, Mapping):
        raise RunnerError("browser QA scenario manifest must be an object")
    argv = list(args.qa_argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    receipt = run_browser_qa_substitute(
        repo=repo,
        specification_revision=args.specification_revision,
        argv=argv,
        scenario_manifest=scenario,
        network_guard=trusted_browser_network_guard(),
        timeout_seconds=args.timeout,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def nonrecovery_allowed_set_digest(allowed_files: list[str]) -> str:
    """Bind an ordinary implementation lease to its requested path set."""
    payload = {
        "schema": "openbuild.nonrecovery-allowed-set.v1",
        "paths": sorted(set(allowed_files)),
    }
    return sha256_bytes(NONRECOVERY_ALLOWED_SET_DOMAIN + _canonical_json_bytes(payload))


def discovery_profile_with_fingerprint(
    profile: AgentProfile,
    fingerprint: Mapping[str, Any],
) -> AgentProfile:
    """Bind one owner-captured fingerprint into otherwise canonical search instructions."""
    if not profile.name.startswith("openbuild_search_"):
        return profile
    runtime = json.dumps(
        dict(fingerprint),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return profile._replace(
        developer_instructions=(
            f"{profile.developer_instructions.rstrip()}\n\n"
            "Runtime owner snapshot: copy this exact JSON object into "
            f"worktree_fingerprint: {runtime}"
        )
    )


def profile_descriptor(profile: AgentProfile) -> dict[str, Any]:
    descriptor = {
        "name": profile.name,
        "source_sha256": sha256_file(profile.source) if profile.source.is_file() else None,
        "model": profile.model,
        "reasoning_effort": profile.reasoning_effort,
        "service_tier": None,
        "sandbox": profile.sandbox,
        "read_only": profile.sandbox == "read-only",
        "instructions_sha256": sha256_bytes(profile.developer_instructions.encode("utf-8")),
    }
    return {
        "descriptor": descriptor,
        "sha256": sha256_bytes(_canonical_json_bytes(descriptor)),
    }


def _discovery_route_binding(
    route: Mapping[str, Any],
    *,
    repo: Path,
    codex_home: Path,
    fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    agents = route.get("agents")
    if not isinstance(agents, list) or not agents:
        raise RunnerError("effective discovery route lacks an exact source agent")
    names = [agent.get("name") for agent in agents if isinstance(agent, dict)]
    if len(names) != len(agents) or any(not isinstance(name, str) for name in names):
        raise RunnerError("effective discovery route has malformed agent bindings")
    source_profile = discovery_profile_with_fingerprint(
        load_agent_profile(names[0], repo=repo, codex_home=codex_home),
        fingerprint,
    )
    fallback_name = route.get("availability_fallback_agent")
    source_descriptor = profile_descriptor(source_profile)
    fallback_descriptor: dict[str, Any] | None = None
    if fallback_name is not None:
        if not isinstance(fallback_name, str):
            raise RunnerError("effective discovery route has a malformed fallback profile")
        fallback_profile = discovery_profile_with_fingerprint(
            load_agent_profile(fallback_name, repo=repo, codex_home=codex_home),
            fingerprint,
        )
        fallback_descriptor = profile_descriptor(fallback_profile)
    profile_sequence = [source_descriptor["sha256"]]
    if fallback_descriptor is not None:
        profile_sequence.append(fallback_descriptor["sha256"])
    profile_sequence_sha256 = sha256_bytes(
        _canonical_json_bytes({"profiles": profile_sequence})
    )
    binding = {
        "schema": "openbuild-search-route-binding-v1",
        "map_sha256": route.get("map_sha256"),
        "map_scope": route.get("map_scope"),
        "transport_failure": route.get("transport_failure"),
        "fallback": route.get("fallback"),
        "availability_fallback_agent": route.get("availability_fallback_agent"),
        "availability_fallback_triggers": route.get("availability_fallback_triggers"),
        "agents": names,
        "source_profile_sha256": source_descriptor["sha256"],
        "availability_fallback_profile_sha256": (
            fallback_descriptor["sha256"] if fallback_descriptor is not None else None
        ),
        "profile_sequence_sha256": profile_sequence_sha256,
    }
    if not isinstance(binding["map_sha256"], str):
        raise RunnerError("effective discovery route lacks a map SHA-256")
    return binding


def resolve_discovery_route_binding(
    *,
    repo: Path,
    codex_home: Path,
    fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import model_map

        route = model_map.resolve_model_route(
            repo=repo,
            codex_home=codex_home,
            use_case="discovery",
            risk="default",
        )
    except Exception as exc:
        raise RunnerError(f"cannot resolve discovery route binding: {exc}") from exc
    return _discovery_route_binding(
        route,
        repo=repo,
        codex_home=codex_home,
        fingerprint=fingerprint,
    )


def search_availability_event_stream_is_eligible(
    evidence: Mapping[str, Any],
    *,
    exit_record: Mapping[str, Any] | None = None,
    result_status: str = "missing",
    codex_exit_status: str = "missing",
    codex_exit_code: int | None = None,
) -> bool:
    """Accept only a coherent pre-turn failure stream as availability evidence."""
    termination = exit_record or {}
    failure_message = termination.get("failure_message")
    timed_out = isinstance(failure_message, str) and any(
        token in failure_message.casefold() for token in ("timed out", "timeout")
    )
    exact_exit_code = type(codex_exit_code) is int
    expected_failure = (
        execution_failure_message(codex_exit_code, evidence) if exact_exit_code else None
    )
    return (
        exit_record is not None
        and evidence.get("event_error") is None
        and evidence.get("turn_started") is not True
        and evidence.get("completed") is not True
        and evidence.get("terminal_event") != "turn.completed"
        and evidence.get("structured_stderr_valid", True) is True
        and codex_exit_status == "valid"
        and exact_exit_code
        and codex_exit_code != 0
        and type(termination.get("exit_code")) is int
        and termination.get("exit_code") == codex_exit_code
        and termination.get("success") is False
        and termination.get("terminal_event") == evidence.get("terminal_event")
        and termination.get("failure_message") == expected_failure
        and termination.get("cleanup_errors") == []
        and termination.get("cancelled") is not True
        and not timed_out
        and result_status == "missing"
    )


def _classify_structured_search_error(
    value: Mapping[str, Any],
    *,
    exact_model: str,
) -> str | None:
    code_field = value.get("code")
    type_field = value.get("type")
    if code_field is not None and not isinstance(code_field, str):
        return None
    if type_field is not None and not isinstance(type_field, str):
        return None
    if code_field is not None and type_field is not None and code_field != type_field:
        return None
    code = code_field or type_field
    model = value.get("model")
    rate_limits = value.get("rate_limits")
    limit_name = rate_limits.get("limit_name") if isinstance(rate_limits, dict) else None
    if model == exact_model and code in {
        "model_not_found",
        "model_not_available",
        "model_access_denied",
    }:
        return "model-unavailable"
    if (
        code == "usage_limit_exceeded"
        and limit_name == exact_model
        and (model is None or model == exact_model)
    ):
        return "quota-exhausted"
    return None


def classify_search_availability_failure(
    structured_objects: list[Mapping[str, Any]],
    *,
    exact_model: str,
) -> str | None:
    """Normalize only the closed, model-bound structured vocabulary from R-006."""
    reasons: set[str] = set()
    for value in structured_objects:
        if not isinstance(value, dict):
            return None
        nested = value.get("error")
        if "error" in value:
            if (
                not isinstance(nested, dict)
                or value.get("code") is not None
                or value.get("type") not in {"error", "turn.failed"}
            ):
                return None
            candidate = nested
        else:
            candidate = value
        reason = _classify_structured_search_error(candidate, exact_model=exact_model)
        if reason is None:
            return None
        reasons.add(reason)
    return next(iter(reasons)) if len(reasons) == 1 else None


def _read_structured_stderr(path: Path) -> tuple[list[Mapping[str, Any]], bool]:
    try:
        raw = read_regular_file_no_follow(path)
    except DiscoveryContractError:
        return [], False
    if raw is None:
        return [], True
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return [], False
    result: list[Mapping[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return [], False
        if not isinstance(value, dict):
            return [], False
        result.append(value)
    return result, True


def _windows_move_claim_write_through(source: Path, target: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.MoveFileExW.restype = ctypes.c_int
    if kernel32.MoveFileExW(str(source), str(target), 0x8):
        return
    error = ctypes.get_last_error()
    if error in {80, 183}:
        raise FileExistsError(f"private claim already exists: {target.name}")
    raise RunnerError(f"write-through private claim create failed: {ctypes.WinError(error)}")


def durable_create_private_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    fault: str | None = None,
) -> None:
    """Exclusively create and metadata-commit one JSON authority record."""
    temporary = (
        path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        if os.name == "nt"
        else None
    )
    target = temporary or path
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(target, flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        payload = _canonical_json_bytes(value) + b"\n"
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            if fault == "before-write":
                raise RunnerError("injected failure before private claim write")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if fault == "after-file-fsync":
            raise RunnerError("injected failure after private claim file fsync")
        if fault == "before-metadata-barrier":
            raise RunnerError("injected failure before private claim metadata barrier")
        if temporary is not None:
            _windows_move_claim_write_through(temporary, path)
        else:
            parent = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        if fault == "after-metadata-barrier":
            raise RunnerError("injected failure after private claim metadata barrier")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _create_private_claim(path: Path, value: Mapping[str, Any]) -> None:
    try:
        durable_create_private_json(path, value)
    except FileExistsError as exc:
        raise RunnerError("search availability fallback source was already claimed") from exc


def prepare_search_fallback_claim(
    *,
    source_reference: str,
    expected_map_sha256: str,
    repo: Path,
    codex_home: Path,
    target_profile: AgentProfile,
    task_name: str,
    target_run_dir: Path,
) -> dict[str, Any]:
    """Validate and atomically consume one Spark availability fallback source."""
    if not RUN_HANDLE.fullmatch(source_reference):
        raise RunnerError("search fallback source must be an owner-issued run handle")
    source_dir = resolve_run_reference(source_reference)
    source_request = read_json(source_dir / "request.json")
    if Path(source_request.get("repo", "")).resolve() != repo.resolve():
        raise RunnerError("search fallback source repository binding drifted")
    if source_request.get("task_name") != task_name.strip():
        raise RunnerError("search fallback task binding drifted")
    if source_request.get("search_fallback_source") is not None:
        raise RunnerError("a search fallback run cannot authorize a third agent")
    if source_request.get("search_fallback_binding") is not None:
        raise RunnerError("a Spark source must not carry a fallback binding")
    source_profile_data = source_request.get("profile", {})
    if (
        source_profile_data.get("name") != "openbuild_search_separate"
        or source_profile_data.get("model") != "gpt-5.3-codex-spark"
        or source_profile_data.get("reasoning_effort") != "low"
        or source_profile_data.get("sandbox") != "read-only"
    ):
        raise RunnerError("search fallback source is not the exact Spark profile")
    source_route = source_request.get("discovery_route_binding")
    if not isinstance(source_route, dict):
        raise RunnerError("search fallback source lacks its discovery route binding")
    source_receipt = public_receipt(source_dir)
    if (
        source_receipt.get("status") != "failed"
        or source_receipt.get("process_tree_stopped") is not True
        or source_receipt.get("codex_started") is not True
        or source_receipt.get("codex_exit_evidence") != "valid"
        or source_receipt.get("result_evidence") != "missing"
        or source_receipt.get("cancelled") is not False
        or source_receipt.get("completion_recovered_during_cancel") is not False
    ):
        raise RunnerError("search fallback requires an exact stopped failed Spark process")
    reason = source_receipt.get("transport_failure_reason")
    if reason not in {"model-unavailable", "quota-exhausted"}:
        raise RunnerError("Spark failure is not eligible for availability fallback")
    expected_fingerprint = source_request.get("discovery_fingerprint")
    if not isinstance(expected_fingerprint, dict):
        raise RunnerError("search fallback source lacks a discovery fingerprint")
    try:
        current = compute_worktree_fingerprint(repo)
    except DiscoveryContractError as exc:
        raise RunnerError(str(exc)) from exc
    if current.public != expected_fingerprint:
        raise RunnerError("search fallback source worktree fingerprint drifted")

    current_route = resolve_discovery_route_binding(
        repo=repo,
        codex_home=codex_home,
        fingerprint=expected_fingerprint,
    )
    if (
        source_route != current_route
        or source_route.get("map_sha256") != expected_map_sha256
        or source_route.get("transport_failure") != "availability-fallback"
        or source_route.get("availability_fallback_agent") != "openbuild_search_balanced"
        or reason not in source_route.get("availability_fallback_triggers", [])
        or not source_route.get("agents")
        or source_route["agents"][0] != "openbuild_search_separate"
        or target_profile.name != "openbuild_search_balanced"
    ):
        raise RunnerError("effective discovery fallback route or map binding drifted")

    source_static = load_agent_profile(
        "openbuild_search_separate", repo=repo, codex_home=codex_home
    )
    source_effective = discovery_profile_with_fingerprint(source_static, expected_fingerprint)
    source_descriptor = profile_descriptor(source_effective)
    target_descriptor = profile_descriptor(target_profile)
    expected_sequence_sha256 = sha256_bytes(
        _canonical_json_bytes(
            {"profiles": [source_descriptor["sha256"], target_descriptor["sha256"]]}
        )
    )
    if (
        source_request.get("profile_descriptor_sha256") != source_descriptor["sha256"]
        or source_route.get("source_profile_sha256") != source_descriptor["sha256"]
        or source_route.get("availability_fallback_profile_sha256")
        != target_descriptor["sha256"]
        or source_route.get("profile_sequence_sha256") != expected_sequence_sha256
        or source_descriptor["descriptor"]["instructions_sha256"]
        != target_descriptor["descriptor"]["instructions_sha256"]
        or target_profile.model != "gpt-5.6-terra"
        or target_profile.reasoning_effort != "medium"
        or target_profile.sandbox != "read-only"
    ):
        raise RunnerError("search fallback profile descriptor binding drifted")
    sequence_sha256 = expected_sequence_sha256
    binding = {
        "schema": "openbuild-search-fallback-claim-v1",
        "source_receipt_sha256": sha256_bytes(
            _canonical_json_bytes(
                {
                    key: source_receipt.get(key)
                    for key in (
                        "run_handle",
                        "agent_name",
                        "configured_model",
                        "terminal_event",
                        "codex_exit_evidence",
                        "codex_exit_code",
                        "process_tree_stopped",
                        "transport_failure_reason",
                        "prompt_sha256",
                    )
                }
            )
        ),
        "source_handle_sha256": sha256_bytes(source_reference.encode("utf-8")),
        "target_run_handle": public_run_handle(target_run_dir),
        "reason": reason,
        "map_sha256": expected_map_sha256,
        "profile_sequence_sha256": sequence_sha256,
        "source_profile_sha256": source_descriptor["sha256"],
        "target_profile_sha256": target_descriptor["sha256"],
        "instructions_sha256": target_descriptor["descriptor"]["instructions_sha256"],
        "prompt_snapshot_id": source_request.get("prompt_snapshot_id"),
        "prompt_sha256": source_request.get("prompt_sha256"),
        "claimed_at": utc_now(),
    }
    _create_private_claim(source_dir / "search-fallback-claim.json", binding)
    return binding


def sign_guardian_message(
    secret: bytes,
    kind: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if len(secret) != 32 or not kind:
        raise RunnerError("guardian IPC requires a 32-byte secret and non-empty kind")
    body = {"kind": kind, "payload": dict(payload)}
    body["authentication"] = hmac.new(
        secret,
        b"openbuild-guardian-ipc-v1\0" + _canonical_json_bytes(body),
        hashlib.sha256,
    ).hexdigest()
    return body


def verify_guardian_message(
    message: Mapping[str, Any],
    secret: bytes,
    expected_kind: str,
) -> dict[str, Any]:
    if message.get("kind") != expected_kind:
        raise RunnerError("guardian IPC message kind does not match the expected transition")
    payload = message.get("payload")
    authentication = message.get("authentication")
    if not isinstance(payload, dict) or not isinstance(authentication, str):
        raise RunnerError("guardian IPC authentication is missing")
    expected = sign_guardian_message(secret, expected_kind, payload)["authentication"]
    if not hmac.compare_digest(authentication, expected):
        raise RunnerError("guardian IPC authentication failed")
    return dict(payload)


def write_guardian_message(
    path: Path,
    secret: bytes,
    kind: str,
    payload: Mapping[str, Any],
) -> None:
    atomic_write_json(path, sign_guardian_message(secret, kind, payload))


def read_guardian_message(
    path: Path,
    secret: bytes,
    expected_kind: str,
    *,
    publish_retry_timeout: float = 1.0,
) -> dict[str, Any]:
    """Read an atomically published IPC message across transient Windows sharing locks."""
    deadline = time.monotonic() + publish_retry_timeout
    while True:
        try:
            return verify_guardian_message(read_json(path), secret, expected_kind)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def await_worker_containment_gate(
    run_dir: Path,
    *,
    expected_pid: int,
    expected_identity: str,
    timeout: float,
) -> dict[str, Any]:
    path = run_dir / "containment-bound.json"
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise RunnerError("authenticated containment gate was not committed before worker startup")
        time.sleep(0.02)
    try:
        secret = (run_dir / "guardian.key").read_bytes()
    except OSError as exc:
        raise RunnerError(f"guardian IPC key is unavailable: {exc}") from exc
    payload = read_guardian_message(path, secret, "containment-bound")
    if (
        int(payload.get("worker_pid") or 0) != expected_pid
        or payload.get("worker_identity") != expected_identity
    ):
        raise RunnerError("containment gate does not match the creation-bound worker")
    return payload


def parse_linux_cgroup_events(value: str) -> dict[str, int]:
    events: dict[str, int] = {}
    for line in value.splitlines():
        parts = line.split()
        if len(parts) != 2:
            raise RunnerError("Linux cgroup.events is malformed")
        try:
            events[parts[0]] = int(parts[1])
        except ValueError as exc:
            raise RunnerError("Linux cgroup.events is malformed") from exc
    if "populated" not in events:
        raise RunnerError("Linux cgroup.events lacks the populated state")
    return events


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    if os.name == "nt":
        protect_windows_private_file(path, windows_current_user_sid())


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(value)
    os.replace(temporary, path)
    if os.name == "nt":
        protect_windows_private_file(path, windows_current_user_sid())


def _windows_security_apis() -> tuple[Any, Any]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CreateDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    kernel32.CreateDirectoryW.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int
    advapi32.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.GetSecurityDescriptorControl.restype = ctypes.c_int
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    advapi32.GetAclInformation.restype = ctypes.c_int
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = ctypes.c_int
    advapi32.SetFileSecurityW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    advapi32.SetFileSecurityW.restype = ctypes.c_int
    return kernel32, advapi32


def windows_sid_string(sid: Any) -> str:
    kernel32, advapi32 = _windows_security_apis()
    value = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(value)):
        raise RunnerError(f"cannot serialize a Windows security identifier: {ctypes.WinError()}")
    try:
        if not value.value:
            raise RunnerError("Windows returned an empty security identifier")
        return value.value
    finally:
        kernel32.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def windows_current_user_sid() -> str:
    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    kernel32, advapi32 = _windows_security_apis()
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise RunnerError(f"cannot inspect the current Windows user token: {ctypes.WinError()}")
    try:
        required = ctypes.c_uint32()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise RunnerError(f"cannot size the current Windows user token: {ctypes.WinError()}")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise RunnerError(f"cannot read the current Windows user token: {ctypes.WinError()}")
        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        return windows_sid_string(token_user.user.sid)
    finally:
        kernel32.CloseHandle(token)


def create_windows_private_directory(path: Path, user_sid: str) -> None:
    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint32),
            ("security_descriptor", ctypes.c_void_p),
            ("inherit_handle", ctypes.c_int),
        ]

    kernel32, advapi32 = _windows_security_apis()
    descriptor = ctypes.c_void_p()
    sddl = f"O:{user_sid}G:{user_sid}D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{user_sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,
        ctypes.byref(descriptor),
        None,
    ):
        raise RunnerError(f"cannot build a private Windows run-directory DACL: {ctypes.WinError()}")
    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    try:
        if not kernel32.CreateDirectoryW(str(path), ctypes.byref(attributes)):
            raise RunnerError(f"cannot create a private Windows run directory {path}: {ctypes.WinError()}")
    finally:
        kernel32.LocalFree(descriptor)


def protect_windows_private_file(path: Path, user_sid: str) -> None:
    kernel32, advapi32 = _windows_security_apis()
    descriptor = ctypes.c_void_p()
    sddl = (
        f"O:{user_sid}G:{user_sid}D:P"
        f"(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{user_sid})"
    )
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,
        ctypes.byref(descriptor),
        None,
    ):
        raise RunnerError(f"cannot build a private Windows file DACL: {ctypes.WinError()}")
    try:
        security_information = 0x00000001 | 0x00000004 | 0x80000000
        if not advapi32.SetFileSecurityW(
            str(path), security_information, descriptor
        ):
            raise RunnerError(
                f"cannot protect private Windows file {path}: {ctypes.WinError()}"
            )
    finally:
        kernel32.LocalFree(descriptor)


def windows_object_is_private(path: Path, user_sid: str, *, directory: bool) -> bool:
    class AclSizeInformation(ctypes.Structure):
        _fields_ = [
            ("ace_count", ctypes.c_uint32),
            ("acl_bytes_in_use", ctypes.c_uint32),
            ("acl_bytes_free", ctypes.c_uint32),
        ]

    kernel32, advapi32 = _windows_security_apis()
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    error = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,
        0x00000001 | 0x00000004,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if error:
        raise RunnerError(f"cannot inspect Windows run-directory security for {path}: {ctypes.WinError(error)}")
    try:
        if not owner or windows_sid_string(owner) != user_sid or not dacl:
            return False
        control = ctypes.c_uint16()
        revision = ctypes.c_uint32()
        if not advapi32.GetSecurityDescriptorControl(
            descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ) or not control.value & 0x1000:
            return False
        information = AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(information),
            ctypes.sizeof(information),
            2,
        ):
            raise RunnerError(f"cannot inspect the Windows run-directory DACL for {path}")
        user_has_full_access = False
        allowed_sids = {user_sid, "S-1-5-18", "S-1-5-32-544"}
        for index in range(information.ace_count):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise RunnerError(f"cannot inspect Windows run-directory DACL entry {index}")
            address = int(ace_pointer.value or 0)
            ace_type = ctypes.c_ubyte.from_address(address).value
            ace_flags = ctypes.c_ubyte.from_address(address + 1).value
            ace_size = ctypes.c_uint16.from_address(address + 2).value
            if ace_type != 0 or ace_size < 12:
                return False
            mask = ctypes.c_uint32.from_address(address + 4).value
            ace_sid = windows_sid_string(ctypes.c_void_p(address + 8))
            if ace_sid not in allowed_sids or ace_flags & 0x10:
                return False
            if ace_sid == user_sid:
                user_has_full_access = mask & 0x001F01FF == 0x001F01FF and (
                    not directory or ace_flags & 0x03 == 0x03
                )
        return user_has_full_access
    finally:
        kernel32.LocalFree(descriptor)


def windows_directory_is_private(path: Path, user_sid: str) -> bool:
    return windows_object_is_private(path, user_sid, directory=True)


def ensure_private_run_dir(path: Path) -> None:
    existed = path.exists()
    if os.name == "nt":
        if existed:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            if not path.is_dir() or path.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise RunnerError(f"Windows run directory must be a real local directory: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        user_sid = windows_current_user_sid()
        if not existed:
            create_windows_private_directory(path, user_sid)
        if not windows_directory_is_private(path, user_sid):
            raise RunnerError(
                f"Windows run directory must have a protected current-user-only DACL: {path}"
            )
        return
    path.mkdir(parents=True, exist_ok=True)
    metadata = path.stat()
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        raise RunnerError(f"run directory is not owned by the current user: {path}")
    if existed and metadata.st_mode & 0o077:
        raise RunnerError(f"run directory must not be accessible to group/other users: {path}")
    os.chmod(path, 0o700)


def open_private_binary(path: Path, *, append: bool = False) -> Any:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "ab" if append else "wb")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerError(f"missing run artifact: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError(f"invalid run artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunnerError(f"invalid run artifact {path}: expected a JSON object")
    return value


def expected_sandbox(agent_name: str) -> str:
    if agent_name.startswith(("openbuild_search_", "openbuild_review_")):
        return "read-only"
    if agent_name.startswith("openbuild_implementation_"):
        return "workspace-write"
    raise RunnerError(f"unsupported OpenBuild agent: {agent_name}")


def validate_lease_id(agent_name: str, lease_id: str | None) -> str | None:
    value = lease_id.strip() if isinstance(lease_id, str) else ""
    if agent_name.startswith("openbuild_implementation_"):
        if not value or not LEASE_ID.fullmatch(value):
            raise RunnerError("implementation dispatch requires a safe non-empty --lease-id")
        return value
    if value:
        raise RunnerError("--lease-id is valid only for implementation agents")
    return None


def recovery_registry_for_agent(
    agent_name: str,
    repo: Path,
    *,
    state_root: Path | None = None,
) -> RecoveryRegistry | None:
    """Return the single-writer owner only for write-capable implementation lanes."""

    if not agent_name.startswith("openbuild_implementation_"):
        return None
    return RecoveryRegistry(repo, state_root=state_root)


_PROJECT_LANE_ARGUMENTS = (
    "project_lane_id",
    "project_checkout",
    "project_coordinator_root",
    "project_anchor_id",
    "project_recovery_root",
    "project_lane_root",
    "project_integration_ref",
)
_PROJECT_LANE_REQUEST_FIELDS = {
    "schema",
    "lane_id",
    "project_checkout",
    "coordinator_root",
    "anchor_id",
    "recovery_root",
    "lane_root",
    "integration_ref",
    "lane_binding",
}


def recovery_registry_for_request(
    request: Mapping[str, Any],
) -> RecoveryRegistry | None:
    profile = request.get("profile")
    repo_value = request.get("repo")
    if not isinstance(profile, Mapping) or not isinstance(repo_value, str):
        raise RunnerError("implementation request registry binding is malformed")
    project_lane = request.get("project_lane")
    state_root = None
    if project_lane is not None:
        if (
            not isinstance(project_lane, Mapping)
            or set(project_lane) != _PROJECT_LANE_REQUEST_FIELDS
            or not isinstance(project_lane.get("recovery_root"), str)
        ):
            raise RunnerError("project lane request registry binding is malformed")
        try:
            state_root = Path(str(project_lane["recovery_root"])).expanduser().resolve(
                strict=True
            )
        except OSError as exc:
            raise RunnerError("project lane recovery root is unavailable") from exc
    return recovery_registry_for_agent(
        str(profile.get("name")),
        Path(repo_value),
        state_root=state_root,
    )


def _project_lane_recovery_root(value: object) -> Path:
    """Accept an absent registry root without resolving through an ancestor."""
    root = _absolute_no_follow(Path(str(value)))
    _assert_no_link_or_reparse_ancestors(root)
    return root


def _project_lane_coordinator(
    project_lane: Mapping[str, Any],
) -> ProjectLaneCoordinator:
    if (
        not isinstance(project_lane, Mapping)
        or set(project_lane) != _PROJECT_LANE_REQUEST_FIELDS
        or project_lane.get("schema") != "project-lane-request-v1"
        or not all(
            isinstance(project_lane.get(field), str) and project_lane[field]
            for field in (
                "lane_id",
                "project_checkout",
                "coordinator_root",
                "anchor_id",
                "recovery_root",
                "lane_root",
                "integration_ref",
            )
        )
        or not isinstance(project_lane.get("lane_binding"), Mapping)
    ):
        raise RunnerError("project lane request binding is malformed")
    try:
        checkout = Path(str(project_lane["project_checkout"])).expanduser().resolve(
            strict=True
        )
        coordinator_root = Path(
            str(project_lane["coordinator_root"])
        ).expanduser().resolve(strict=True)
        recovery_root = _project_lane_recovery_root(project_lane["recovery_root"])
        lane_root = Path(str(project_lane["lane_root"])).expanduser().resolve(
            strict=True
        )
        store = ProjectStateStore(
            checkout,
            coordinator_root=coordinator_root,
        )
        return ProjectLaneCoordinator(
            checkout,
            store,
            str(project_lane["anchor_id"]),
            recovery_root=recovery_root,
            lane_root=lane_root,
            integration_ref=str(project_lane["integration_ref"]),
        )
    except (OSError, ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane coordinator rejected the request: {exc}") from exc


def resolve_project_lane_start(
    args: argparse.Namespace,
    *,
    agent_name: str,
    repo: Path,
    allowed_files: list[str],
) -> dict[str, Any] | None:
    values = {
        field: getattr(args, field, None)
        for field in _PROJECT_LANE_ARGUMENTS
    }
    supplied = [
        isinstance(value, str) and bool(value.strip())
        for value in values.values()
    ]
    if not any(supplied):
        return None
    if not all(supplied):
        raise RunnerError("project lane options must be supplied together")
    if not agent_name.startswith("openbuild_implementation_"):
        raise RunnerError("project lane options are valid only for implementation agents")
    if not allowed_files:
        raise RunnerError("project lane dispatch requires an explicit allowed-file set")
    try:
        project_lane = {
            "schema": "project-lane-request-v1",
            "lane_id": str(values["project_lane_id"]).strip(),
            "project_checkout": str(
                Path(str(values["project_checkout"])).expanduser().resolve(
                    strict=True
                )
            ),
            "coordinator_root": str(
                Path(str(values["project_coordinator_root"]))
                .expanduser()
                .resolve(strict=True)
            ),
            "anchor_id": str(values["project_anchor_id"]).strip(),
            "recovery_root": str(
                _project_lane_recovery_root(values["project_recovery_root"])
            ),
            "lane_root": str(
                Path(str(values["project_lane_root"]))
                .expanduser()
                .resolve(strict=True)
            ),
            "integration_ref": str(values["project_integration_ref"]).strip(),
            "lane_binding": {},
        }
        coordinator = _project_lane_coordinator(project_lane)
        lane_registry_state = RecoveryRegistry(
            repo,
            state_root=Path(project_lane["recovery_root"]),
        ).state()
        reserved_lease = lane_registry_state.get("lease")
        lease_kind = (
            "recovery-target"
            if (
                isinstance(reserved_lease, Mapping)
                and reserved_lease.get("lease_kind") == "recovery-target"
                and reserved_lease.get("state") == "reserved"
            )
            else "normal-contained"
        )
        runtime_claim_receipt: dict[str, bool] = {}
        project_lane["lane_binding"] = coordinator.runner_writer_binding(
            project_lane["lane_id"],
            repo,
            allowed_files,
            require_ready=True,
            lease_kind=lease_kind,
            runtime_owner=getattr(args, "lease_id", None),
            runtime_claim=getattr(args, "_project_runtime_claim", None),
            runtime_claim_receipt=runtime_claim_receipt,
        )
        setattr(
            args,
            "_project_runtime_claim_acquired",
            runtime_claim_receipt.get("acquired") is True,
        )
        return project_lane
    except (
        OSError,
        ProjectLaneError,
        ProjectStateError,
        RecoveryStateError,
    ) as exc:
        raise RunnerError(f"project lane rejected runner start: {exc}") from exc


def resolve_project_lane_recovery_authorization(
    args: argparse.Namespace,
    *,
    repo: Path,
    checkpoint: Mapping[str, Any],
) -> dict[str, Any] | None:
    values = {
        field: getattr(args, field, None)
        for field in _PROJECT_LANE_ARGUMENTS
    }
    supplied = [
        isinstance(value, str) and bool(value.strip())
        for value in values.values()
    ]
    if not any(supplied):
        return None
    if not all(supplied):
        raise RunnerError("project lane options must be supplied together")
    checkpoint_digest = checkpoint.get("checkpoint_digest")
    if (
        checkpoint.get("disposition") != "recovery-eligible"
        or not re.fullmatch(r"[0-9a-f]{64}", str(checkpoint_digest))
    ):
        raise RunnerError(
            "project lane recovery authorization requires an eligible checkpoint"
        )
    try:
        project_lane = {
            "schema": "project-lane-request-v1",
            "lane_id": str(values["project_lane_id"]).strip(),
            "project_checkout": str(
                Path(str(values["project_checkout"])).expanduser().resolve(
                    strict=True
                )
            ),
            "coordinator_root": str(
                Path(str(values["project_coordinator_root"]))
                .expanduser()
                .resolve(strict=True)
            ),
            "anchor_id": str(values["project_anchor_id"]).strip(),
            "recovery_root": str(
                Path(str(values["project_recovery_root"]))
                .expanduser()
                .resolve(strict=True)
            ),
            "lane_root": str(
                Path(str(values["project_lane_root"]))
                .expanduser()
                .resolve(strict=True)
            ),
            "integration_ref": str(values["project_integration_ref"]).strip(),
            "lane_binding": {},
        }
        coordinator = _project_lane_coordinator(project_lane)
        lane = coordinator.lane_projection(project_lane["lane_id"])
        if (
            lane.get("state") != "recovery-ready"
            or lane.get("writer") is not None
            or lane.get("recovery_checkpoint_digest") != checkpoint_digest
        ):
            raise ProjectLaneError(
                "project lane is not bound to this recovery checkpoint"
            )
        allowed_paths = RecoveryRegistry(
            repo,
            state_root=Path(project_lane["recovery_root"]),
        ).checkpoint_allowed_paths(checkpoint)
        project_lane["lane_binding"] = coordinator.runner_writer_binding(
            project_lane["lane_id"],
            repo,
            allowed_paths,
            require_ready=False,
            lease_kind="recovery-target",
        )
        return project_lane
    except (
        OSError,
        ProjectLaneError,
        ProjectStateError,
        RecoveryStateError,
    ) as exc:
        raise RunnerError(
            f"project lane rejected recovery authorization: {exc}"
        ) from exc


def _verified_project_lane(
    request: Mapping[str, Any],
    *,
    allow_completed_runtime_replay: bool = False,
) -> tuple[ProjectLaneCoordinator, Mapping[str, Any]] | None:
    project_lane = request.get("project_lane")
    if project_lane is None:
        return None
    if not isinstance(project_lane, Mapping):
        raise RunnerError("project lane request binding is malformed")
    coordinator = _project_lane_coordinator(project_lane)
    try:
        repo = Path(str(request.get("repo"))).expanduser().resolve(strict=True)
        binding = coordinator.verify_runner_writer_binding(
            project_lane["lane_binding"],
            repo,
            runtime_owner=(
                request.get("lease_id")
                if isinstance(project_lane.get("lane_binding"), Mapping)
                and "runtime" in project_lane["lane_binding"]
                else None
            ),
            runtime_claim=(
                request.get("project_runtime_claim")
                if isinstance(project_lane.get("lane_binding"), Mapping)
                and "runtime" in project_lane["lane_binding"]
                else None
            ),
            allow_completed_runtime_replay=allow_completed_runtime_replay,
        )
    except (OSError, ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane binding verification failed: {exc}") from exc
    return coordinator, binding


_PROJECT_RUNTIME_BINDING_FIELDS = {
    "schema",
    "job_id",
    "lane_id",
    "ticket",
    "namespace",
    "namespaces",
    "port",
    "owner_digest",
}
_PROJECT_RUNTIME_NAMESPACE_KINDS = {
    "port",
    "test-db",
    "compose",
    "temp",
    "build",
}
_PROJECT_RUNTIME_ENVIRONMENT_KEYS = {
    "OPENBUILD_RUNTIME_NAMESPACE",
    "OPENBUILD_RUNTIME_PORT_NAMESPACE",
    "OPENBUILD_RUNTIME_PORT",
    "OPENBUILD_TEST_DB_NAMESPACE",
    "COMPOSE_PROJECT_NAME",
    "OPENBUILD_TEMP_NAMESPACE",
    "OPENBUILD_BUILD_NAMESPACE",
}


def _project_runtime_binding(
    request: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    project_lane = request.get("project_lane")
    if project_lane is None:
        return None
    lane_binding = (
        project_lane.get("lane_binding")
        if isinstance(project_lane, Mapping)
        else None
    )
    runtime = (
        lane_binding.get("runtime")
        if isinstance(lane_binding, Mapping)
        else None
    )
    if runtime is None:
        return None
    namespaces = runtime.get("namespaces") if isinstance(runtime, Mapping) else None
    if (
        not isinstance(runtime, Mapping)
        or set(runtime) != _PROJECT_RUNTIME_BINDING_FIELDS
        or runtime.get("schema") != "project-lane-runtime-v1"
        or not isinstance(runtime.get("job_id"), str)
        or not isinstance(runtime.get("lane_id"), str)
        or not isinstance(runtime.get("ticket"), int)
        or runtime["ticket"] < 1
        or not isinstance(runtime.get("namespace"), str)
        or not re.fullmatch(r"ob-[a-z0-9-]{1,80}", runtime["namespace"])
        or not isinstance(namespaces, Mapping)
        or set(namespaces) != _PROJECT_RUNTIME_NAMESPACE_KINDS
        or any(
            not isinstance(value, str)
            or not re.fullmatch(r"ob-[a-z0-9-]{1,80}", value)
            for value in namespaces.values()
        )
        or (
            runtime.get("port") is not None
            and (
                not isinstance(runtime["port"], int)
                or isinstance(runtime["port"], bool)
                or not 1 <= runtime["port"] <= 65535
            )
        )
        or not re.fullmatch(r"[0-9a-f]{64}", str(runtime.get("owner_digest")))
    ):
        raise RunnerError("project lane runtime binding is malformed")
    return runtime


def project_runtime_environment(
    request: Mapping[str, Any],
) -> dict[str, str]:
    """Apply only opaque lane namespaces and an explicitly leased port."""

    runtime = _project_runtime_binding(request)
    if runtime is None:
        return {}
    namespaces = runtime["namespaces"]
    assert isinstance(namespaces, Mapping)
    environment = {
        "OPENBUILD_RUNTIME_NAMESPACE": str(runtime["namespace"]),
        "OPENBUILD_RUNTIME_PORT_NAMESPACE": str(namespaces["port"]),
        "OPENBUILD_TEST_DB_NAMESPACE": str(namespaces["test-db"]),
        "COMPOSE_PROJECT_NAME": str(namespaces["compose"]),
        "OPENBUILD_TEMP_NAMESPACE": str(namespaces["temp"]),
        "OPENBUILD_BUILD_NAMESPACE": str(namespaces["build"]),
    }
    if runtime["port"] is not None:
        environment["OPENBUILD_RUNTIME_PORT"] = str(runtime["port"])
    return environment


def release_project_lane_runtime(
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    runtime = _project_runtime_binding(request)
    if runtime is None:
        return None
    project_lane = request.get("project_lane")
    assert isinstance(project_lane, Mapping)
    coordinator = _project_lane_coordinator(project_lane)
    try:
        return ProjectRuntimeCoordinator(
            coordinator.store,
            coordinator.anchor_id,
        ).release(
            str(runtime["job_id"]),
            owner_digest=str(runtime["owner_digest"]),
        )
    except ProjectRuntimeError as exc:
        raise RunnerError(
            f"project lane runtime release failed closed: {exc}"
        ) from exc


def attach_project_lane_writer(request: Mapping[str, Any]) -> dict[str, Any] | None:
    verified = _verified_project_lane(request)
    if verified is None:
        return None
    coordinator, binding = verified
    registry = recovery_registry_for_request(request)
    lease_id = request.get("lease_id")
    if registry is None or not isinstance(lease_id, str):
        raise RunnerError("project lane request lacks its lane-local writer lease")
    state = registry.state()
    lease = state.get("lease")
    lease_kind = lease.get("lease_kind") if isinstance(lease, Mapping) else None
    run_id = (
        lease.get("plan", {}).get("run_id")
        if lease_kind == "recovery-target" and isinstance(lease, Mapping)
        else lease.get("run_id")
        if isinstance(lease, Mapping)
        else None
    )
    if (
        not isinstance(lease, Mapping)
        or lease.get("lease_id") != lease_id
        or not isinstance(run_id, str)
        or not run_id
        or lease.get("state") not in {"running", "active"}
        or lease_kind not in {"normal-contained", "recovery-target"}
        or lease.get("recovery_capable") is not True
        or lease.get("allowed_set_digest")
        != request.get("lifecycle_allowed_set_digest")
    ):
        raise RunnerError("project lane writer is not an active contained lease")
    try:
        return coordinator.attach_contained_writer(
            str(binding["lane_id"]),
            lease_id=lease_id,
            run_id=run_id,
            allowed_set_digest=str(lease["allowed_set_digest"]),
            lease_kind=str(lease_kind),
            recovery_checkpoint_digest=(
                str(lease["checkpoint_digest"])
                if lease_kind == "recovery-target"
                else None
            ),
        )
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane writer attach failed closed: {exc}") from exc


def project_lane_safe_stop_binding(
    request: Mapping[str, Any],
    *,
    require_active_registry: bool,
) -> tuple[ProjectLaneCoordinator, dict[str, Any]] | None:
    """Return only the exact registry-published safe-stop bound to this run."""

    project_lane = request.get("project_lane")
    if project_lane is None:
        return None
    if not isinstance(project_lane, Mapping):
        raise RunnerError("project lane request binding is malformed")
    coordinator = _project_lane_coordinator(project_lane)
    lane_id = project_lane.get("lane_id")
    lease_id = request.get("lease_id")
    allowed_set_digest = request.get("lifecycle_allowed_set_digest")
    root_binding = request.get("root_completion_source_binding")
    expected_run_id = (
        root_binding.get("run_id")
        if isinstance(root_binding, Mapping)
        else None
    )
    if (
        not isinstance(lane_id, str)
        or not isinstance(lease_id, str)
        or not isinstance(allowed_set_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", allowed_set_digest)
        or not isinstance(expected_run_id, str)
        or not expected_run_id
    ):
        raise RunnerError("project lane safe-stop request binding is malformed")
    try:
        lane = coordinator.lane_projection(lane_id)
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane safe-stop lookup failed closed: {exc}") from exc
    intent = lane.get("safe_stop")
    if intent is None:
        return None
    intent_writer = (
        intent.get("writer")
        if isinstance(intent, Mapping)
        else None
    )
    if (
        not isinstance(intent, dict)
        or intent.get("status") not in {"requested", "stopping", "completed"}
        or not re.fullmatch(r"[0-9a-f]{64}", str(intent.get("intent_id")))
        or not isinstance(intent_writer, dict)
    ):
        raise RunnerError("project lane safe-stop binding changed")
    if (
        intent_writer.get("lease_id") != lease_id
        or intent_writer.get("allowed_set_digest") != allowed_set_digest
        or intent_writer.get("run_id") != expected_run_id
    ):
        if intent.get("status") == "completed":
            return None
        raise RunnerError("project lane safe-stop binding changed")
    if intent.get("status") in {"requested", "stopping"} and (
        lane.get("writer") != intent_writer
        or lane.get("state") != "running"
    ):
        raise RunnerError("project lane safe-stop binding changed")
    if require_active_registry:
        registry = recovery_registry_for_request(request)
        state = registry.state() if registry is not None else None
        lease = state.get("lease") if isinstance(state, Mapping) else None
        lease_kind = lease.get("lease_kind") if isinstance(lease, Mapping) else None
        run_id = (
            lease.get("plan", {}).get("run_id")
            if lease_kind == "recovery-target" and isinstance(lease, Mapping)
            else lease.get("run_id") if isinstance(lease, Mapping) else None
        )
        if (
            not isinstance(lease, Mapping)
            or lease.get("lease_id") != lease_id
            or lease.get("state") not in {"running", "active"}
            or lease.get("allowed_set_digest") != allowed_set_digest
            or lease_kind != intent_writer.get("lease_kind")
            or run_id != intent_writer.get("run_id")
        ):
            raise RunnerError("project lane safe-stop writer is not live and exact")
    return coordinator, dict(intent)


def consume_project_lane_safe_stop(request: Mapping[str, Any]) -> dict[str, Any] | None:
    binding = project_lane_safe_stop_binding(request, require_active_registry=True)
    if binding is None:
        return None
    coordinator, intent = binding
    if intent.get("status") == "stopping":
        return intent
    try:
        lane = coordinator.lane_projection(str(intent["lane_id"]))
        consumed = coordinator.consume_safe_stop_rebind(
            str(intent["lane_id"]),
            writer=dict(lane["writer"]),
            intent_id=str(intent["intent_id"]),
        )
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane safe-stop consumption failed closed: {exc}") from exc
    result = consumed.get("safe_stop")
    if not isinstance(result, dict) or result.get("status") != "stopping":
        raise RunnerError("project lane safe-stop consumption is not durable")
    return result


def complete_project_lane_safe_stop(
    request: Mapping[str, Any],
    intent_id: str,
    *,
    recovery_checkpoint_digest: str | None,
    preserved_changes: bool,
) -> dict[str, Any]:
    binding = project_lane_safe_stop_binding(request, require_active_registry=False)
    if binding is None:
        raise RunnerError("project lane safe-stop completion is absent")
    coordinator, intent = binding
    if intent.get("intent_id") != intent_id or intent.get("status") != "stopping":
        raise RunnerError("project lane safe-stop completion binding changed")
    try:
        completed = coordinator.complete_safe_stop_rebind(
            str(intent["lane_id"]),
            intent_id=intent_id,
            recovery_checkpoint_digest=recovery_checkpoint_digest,
            preserved_changes=preserved_changes,
        )
        release_project_lane_runtime(request)
        return completed
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane safe-stop completion failed closed: {exc}") from exc


def safe_stop_checkpoint_binding(
    registry: RecoveryRegistry,
    checkpoint: Mapping[str, Any] | None,
) -> tuple[str | None, bool]:
    """Return only a revalidated eligible checkpoint and its allowed-set delta."""

    if not isinstance(checkpoint, Mapping):
        return None, False
    verified = registry.revalidate_checkpoint(checkpoint)
    if verified.get("disposition") != "recovery-eligible":
        return None, False
    pre = verified.get("pre_snapshot")
    candidate = verified.get("candidate_snapshot")
    if not isinstance(pre, Mapping) or not isinstance(candidate, Mapping):
        raise RunnerError("safe-stop checkpoint snapshots are malformed")
    checkpoint_digest = verified.get("checkpoint_digest")
    if not re.fullmatch(r"[0-9a-f]{64}", str(checkpoint_digest)):
        raise RunnerError("safe-stop checkpoint digest is malformed")
    preserved_changes = (
        pre.get("allowed_inventory_digest")
        != candidate.get("allowed_inventory_digest")
    )
    return str(checkpoint_digest), preserved_changes


def materialize_project_lane_safe_stop_receipt(
    path: Path,
    completed_intent: Mapping[str, Any],
) -> None:
    """Materialize the lane-owner completion after its durable CAS."""

    if (
        completed_intent.get("status") != "completed"
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(completed_intent.get("intent_id")),
        )
        or completed_intent.get("completed_state")
        not in {"ready", "recovery-ready"}
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(completed_intent.get("terminal_archive")),
        )
    ):
        raise RunnerError("project lane safe-stop completion receipt is invalid")
    atomic_write_json(
        path,
        {
            "schema": "project-lane-safe-stop-rebind-v1",
            "intent_id": completed_intent["intent_id"],
            "lane_id": completed_intent["lane_id"],
            "state": completed_intent["completed_state"],
            "terminal_archive": completed_intent["terminal_archive"],
            "completed_generation": completed_intent["completed_generation"],
        },
    )


def quarantine_project_lane_writer(
    request: Mapping[str, Any],
    reason: str,
) -> dict[str, Any] | None:
    verified = _verified_project_lane(request)
    if verified is None:
        return None
    coordinator, binding = verified
    try:
        return coordinator.cancel_or_crash(str(binding["lane_id"]), reason)
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane quarantine failed closed: {exc}") from exc


def close_project_lane_writer(
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    project_lane = request.get("project_lane")
    if project_lane is None:
        return None
    if not isinstance(project_lane, Mapping):
        raise RunnerError("project lane request binding is malformed")
    coordinator = _project_lane_coordinator(project_lane)
    try:
        closed = coordinator.close_terminal(str(project_lane["lane_id"]))
        release_project_lane_runtime(request)
        return closed
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(f"project lane terminal close failed closed: {exc}") from exc


def finalize_project_lane_terminal(
    request: Mapping[str, Any],
    reason: str,
) -> dict[str, Any] | None:
    verified = _verified_project_lane(
        request,
        allow_completed_runtime_replay=True,
    )
    if verified is None:
        return None
    coordinator, binding = verified
    try:
        lane = coordinator.lane_projection(str(binding["lane_id"]))
        if lane.get("state") == "closed":
            release_project_lane_runtime(request)
            return lane
        if lane.get("state") not in {"cancelled", "quarantined"}:
            coordinator.cancel_or_crash(str(binding["lane_id"]), reason)
        closed = coordinator.close_terminal(str(binding["lane_id"]))
        release_project_lane_runtime(request)
        return closed
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(
            f"project lane terminal finalization failed closed: {exc}"
        ) from exc


def complete_project_lane_writer(
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    verified = _verified_project_lane(
        request,
        allow_completed_runtime_replay=True,
    )
    if verified is None:
        return None
    coordinator, binding = verified
    try:
        completed = coordinator.record_successful_terminal(
            str(binding["lane_id"]),
        )
        release_project_lane_runtime(request)
        return completed
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(
            f"project lane successful terminal transition failed closed: {exc}"
        ) from exc


def prepare_project_lane_recovery(
    request: Mapping[str, Any],
    checkpoint_digest: str,
) -> dict[str, Any] | None:
    verified = _verified_project_lane(
        request,
        allow_completed_runtime_replay=True,
    )
    if verified is None:
        return None
    coordinator, binding = verified
    try:
        ready = coordinator.record_recovery_ready(
            str(binding["lane_id"]),
            checkpoint_digest,
        )
        release_project_lane_runtime(request)
        return ready
    except (ProjectLaneError, ProjectStateError) as exc:
        raise RunnerError(
            f"project lane recovery transition failed closed: {exc}"
        ) from exc


def validate_recovery_start_options(
    agent_name: str,
    allowed_files: list[str] | None,
    specification_revision: str | None,
    recovery_target_milestone: str | None,
) -> tuple[list[str], str | None, str | None]:
    allowed = [value.strip() for value in (allowed_files or []) if value.strip()]
    revision = specification_revision.strip() if isinstance(specification_revision, str) else ""
    target = recovery_target_milestone.strip() if isinstance(recovery_target_milestone, str) else ""
    if (allowed or revision or target) and not agent_name.startswith("openbuild_implementation_"):
        raise RunnerError("recovery preflight options are valid only for implementation agents")
    if allowed and (not revision or not target):
        raise RunnerError(
            "--allowed-file, --specification-revision, and --recovery-target-milestone must be supplied together"
        )
    if (revision or target) and not allowed:
        raise RunnerError(
            "--allowed-file, --specification-revision, and --recovery-target-milestone must be supplied together"
        )
    return allowed, revision or None, target or None


def _required_string(data: Mapping[str, Any], field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"{path}: required non-empty field {field!r} is missing")
    return value.strip()


def _profile_from_data(data: Mapping[str, Any], path: Path, agent_name: str) -> AgentProfile:
    name = _required_string(data, "name", path)
    if name != agent_name:
        raise RunnerError(f"{path}: selected profile name changed from {agent_name!r} to {name!r}")
    if name not in SUPPORTED_AGENTS or not AGENT_NAME.fullmatch(name):
        raise RunnerError(f"{path}: unsupported or unsafe OpenBuild agent name {name!r}")

    model = _required_string(data, "model", path)
    if any(marker in model for marker in ("<", ">", "\n", "\r")):
        raise RunnerError(f"{path}: model must be a concrete runtime model ID")
    reasoning_effort = _required_string(data, "model_reasoning_effort", path)
    expected_rung = ROUTING_RUNG_BY_AGENT.get(name)
    if expected_rung is not None:
        routing_rung = _required_string(data, "routing_rung", path)
        if routing_rung != expected_rung:
            raise RunnerError(
                f"{path}: {name} requires routing_rung={expected_rung!r}, got {routing_rung!r}"
            )
        if data.get("routing_tuple_confirmed") is not True:
            raise RunnerError(
                f"{path}: {name} requires routing_tuple_confirmed = true"
            )
        known_rung = KNOWN_MODEL_EFFORT_RUNG.get((model, reasoning_effort))
        if model in KNOWN_ROUTING_MODELS and known_rung != expected_rung:
            raise RunnerError(
                f"{path}: known model/effort tuple {model}/{reasoning_effort} does not match "
                f"routing rung {expected_rung}"
            )
    sandbox = _required_string(data, "sandbox_mode", path)
    required_sandbox = expected_sandbox(name)
    if sandbox != required_sandbox:
        raise RunnerError(
            f"{path}: {name} requires sandbox_mode={required_sandbox!r}, got {sandbox!r}"
        )

    developer_instructions = _required_string(data, "developer_instructions", path)
    if name.startswith("openbuild_search_") and developer_instructions != SEARCH_DEVELOPER_INSTRUCTIONS:
        raise RunnerError(
            f"{path}: search profiles must preserve the exact canonical Explorer contract"
        )

    return AgentProfile(
        name=name,
        description=_required_string(data, "description", path),
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox=sandbox,
        developer_instructions=developer_instructions,
        source=path.resolve(),
    )


def _matching_profiles(directory: Path, agent_name: str) -> list[tuple[Path, Mapping[str, Any]]]:
    if not directory.is_dir():
        return []
    matches: list[tuple[Path, Mapping[str, Any]]] = []
    for path in sorted(directory.glob("*.toml")):
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise RunnerError(f"cannot read custom-agent profile {path}: {exc}") from exc
        if data.get("name") == agent_name:
            matches.append((path, data))
    return matches


def load_agent_profile(agent_name: str, *, repo: Path, codex_home: Path) -> AgentProfile:
    """Resolve an exact project, user, then packaged role profile."""

    if agent_name not in SUPPORTED_AGENTS:
        raise RunnerError(f"unsupported OpenBuild agent: {agent_name}")
    scopes = [
        repo.resolve() / ".codex" / "agents",
        codex_home.resolve() / "agents",
        PACKAGED_PROFILE_DIR,
    ]
    for directory in scopes:
        matches = _matching_profiles(directory, agent_name)
        if len(matches) > 1:
            paths = ", ".join(str(path) for path, _ in matches)
            raise RunnerError(f"ambiguous {agent_name!r} profiles in {directory}: {paths}")
        if matches:
            path, data = matches[0]
            return _profile_from_data(data, path, agent_name)
    raise RunnerError(f"packaged OpenBuild profile {agent_name!r} is missing; reinstall OpenBuild")


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_codex_command(
    *,
    codex_bin: str,
    profile: AgentProfile,
    repo: Path,
    result_file: Path,
    is_git_repo: bool,
) -> list[str]:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--color",
        "never",
        "--ephemeral",
        "-m",
        profile.model,
        "-c",
        f"model_reasoning_effort={toml_string(profile.reasoning_effort)}",
        "-c",
        f"developer_instructions={toml_string(agent_developer_instructions(profile))}",
        "-c",
        "features.multi_agent=false",
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'model_provider="openai"',
        "--sandbox",
        profile.sandbox,
        "-C",
        str(repo.resolve()),
        "-o",
        str(result_file.resolve()),
    ]
    if not is_git_repo:
        command.append("--skip-git-repo-check")
    command.append("-")
    return command


def scrub_api_credentials(environment: Mapping[str, str]) -> dict[str, str]:
    """Remove ambient credentials, provider redirects, and managed runtime state."""

    blocked = (
        API_CREDENTIALS
        | PROVIDER_ENVIRONMENT_OVERRIDES
        | _PROJECT_RUNTIME_ENVIRONMENT_KEYS
    )
    return {key: value for key, value in environment.items() if key.upper() not in blocked}


def subscription_config_paths(codex_home: Path, repo: Path) -> list[Path]:
    candidates = [codex_home / "config.toml"]
    candidates.extend(directory / ".codex" / "config.toml" for directory in (repo, *repo.parents))
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique and resolved.is_file():
            unique.append(resolved)
    return unique


def validate_subscription_configuration(codex_home: Path, repo: Path) -> None:
    """Reject effective provider redirects that could bypass the ChatGPT subscription route."""

    for config in subscription_config_paths(codex_home, repo):
        validate_subscription_config_file(config)


def validate_subscription_config_file(config: Path) -> None:
    try:
        with config.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RunnerError(f"cannot validate Codex subscription configuration {config}: {exc}") from exc
    provider = data.get("model_provider")
    if provider not in (None, "openai"):
        raise RunnerError(
            f"{config}: model_provider={provider!r} is not compatible with subscription-only dispatch"
        )
    redirects = sorted(key for key in ("openai_base_url", "chatgpt_base_url") if data.get(key))
    if redirects:
        raise RunnerError(
            f"{config}: provider redirect {', '.join(redirects)} is not allowed for subscription-only dispatch"
        )
    providers = data.get("model_providers")
    if isinstance(providers, dict) and "openai" in providers:
        raise RunnerError(
            f"{config}: custom model_providers.openai is not allowed for subscription-only dispatch"
        )


def classify_login_status(returncode: int, stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    if returncode == 0 and "ChatGPT" in combined:
        return "chatgpt"
    summary = combined.splitlines()[0] if combined else f"exit code {returncode}"
    raise RunnerError(
        "OpenBuild explicit-model dispatch requires Codex CLI authentication through ChatGPT; "
        f"`codex login status` reported: {summary}"
    )


def require_chatgpt_login(codex_bin: str, environment: Mapping[str, str]) -> str:
    try:
        result = subprocess.run(
            [codex_bin, "login", "status"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(environment),
        )
    except OSError as exc:
        raise RunnerError(f"cannot run Codex CLI authentication preflight: {exc}") from exc
    return classify_login_status(result.returncode, result.stdout, result.stderr)


def is_git_repository(repo: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def agent_developer_instructions(profile: AgentProfile) -> str:
    return (
        "You are an already-delegated OpenBuild worker. Perform the bounded role directly. "
        "Do not spawn or delegate to another agent; multi-agent tools are disabled for this run. "
        "Do not change models or reasoning effort. The root remains the orchestrator, decision "
        "owner, Git owner, and final reporter.\n\n"
        f"{profile.developer_instructions.strip()}"
    )


def effective_prompt(profile: AgentProfile, task_name: str, task_prompt: str) -> str:
    if not task_name.strip() or task_name.strip() == profile.name:
        raise RunnerError("task_name must be a non-profile descriptive label")
    if not task_prompt.strip():
        raise RunnerError("the delegated task prompt is empty")
    return (
        f"agent_name: {profile.name}\n"
        f"task_name: {task_name.strip()}\n\n"
        "Bounded task from the OpenBuild root:\n"
        f"{task_prompt.strip()}\n"
    )


def read_prompt_snapshot(path: Path, expected_sha256: str) -> str:
    prompt_bytes = path.read_bytes()
    if sha256_bytes(prompt_bytes) != expected_sha256:
        raise RunnerError("delegated prompt changed after dispatch; refusing stale execution")
    try:
        return prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunnerError(f"delegated prompt snapshot is not UTF-8: {exc}") from exc


_PROMPT_SNAPSHOT_DOMAIN = b"openbuild-prompt-snapshot-v1\0"
MAX_PROMPT_BYTES = 1024 * 1024


class PromptSnapshotTransitionContext:
    """One O4/O8 parent receipt shared by prompt entry-point aliases."""

    def __init__(
        self,
        parent: Any,
        *,
        transition_id: str,
        project_id: str,
        workspace_key: str,
        epoch: int,
        attempt_id: str,
        authority_receipt: Mapping[str, Any],
    ) -> None:
        if transition_id not in {
            "O4.prompt-snapshot.stage",
            "O8.prompt-snapshot.gc",
        } or getattr(parent, "transition_id", None) != transition_id:
            raise RunnerError("prompt transition context has a substituted ID")
        if (
            not isinstance(project_id, str)
            or not project_id
            or not re.fullmatch(r"[0-9a-f]{64}", workspace_key)
            or type(epoch) is not int
            or epoch < 0
            or not isinstance(attempt_id, str)
            or not attempt_id
            or not isinstance(authority_receipt, Mapping)
            or set(authority_receipt)
            != {"receipt_id", "attempt_id", "status", "active_incident", "channels"}
            or authority_receipt.get("attempt_id") != attempt_id
            or authority_receipt.get("status") != "issued"
            or authority_receipt.get("active_incident") is not False
            or not isinstance(authority_receipt.get("channels"), Mapping)
            or set(authority_receipt["channels"]) != {"C1", "C2", "C3", "C4", "C5"}
            or any(
                not isinstance(channel, Mapping)
                or channel.get("verdict") != "clean"
                for channel in authority_receipt["channels"].values()
            )
        ):
            raise RunnerError("prompt transition lacks a fresh typed C1-C5 receipt")
        self.parent = parent
        self.transition_id = transition_id
        self.project_id = project_id
        self.workspace_key = workspace_key
        self.epoch = epoch
        self.attempt_id = attempt_id

    def validate(self, registry: RecoveryRegistry) -> None:
        try:
            receipt = self.parent._reload()
        except Exception as exc:
            raise RunnerError("prompt transition parent receipt is invalid") from exc
        if (
            receipt.get("transition_id") != self.transition_id
            or receipt.get("project_id") != self.project_id
            or receipt.get("epoch") != self.epoch
            or receipt.get("attempt_id") != self.attempt_id
            or receipt.get("status") not in {"issued", "active"}
            or registry.workspace_key != self.workspace_key
        ):
            raise RunnerError("prompt transition binding changed or crossed projects")

    def run_sink(
        self,
        sink: str,
        action: Callable[[], Any],
        *,
        visible: Callable[[], bool] | None = None,
    ) -> Any:
        try:
            return self.parent.run_sink(sink, action, visible=visible)
        except Exception as exc:
            raise RunnerError("guarded prompt transition failed") from exc

    def complete(self) -> None:
        try:
            self.parent.complete()
        except Exception as exc:
            raise RunnerError("prompt transition cursor is incomplete") from exc


class ManagedProjectOperationContext:
    """One-use ordinary O1-O8 gate bound to a fresh C1-C5 receipt."""

    _RECEIPT_KEYS = {
        "receipt_id",
        "project_id",
        "epoch",
        "registry_generation",
        "attempt_id",
        "transition_id",
        "status",
        "active_incident",
        "channels",
    }
    _CHANNEL_KEYS = {
        "channel_id",
        "verdict",
        "complete",
        "evidence_digest",
    }

    def __init__(self, authority_receipt: Mapping[str, Any]) -> None:
        if (
            not isinstance(authority_receipt, Mapping)
            or set(authority_receipt) != self._RECEIPT_KEYS
        ):
            raise RunnerError("managed operation authority receipt is inexact")
        receipt = dict(authority_receipt)
        transition_id = receipt.get("transition_id")
        if (
            not isinstance(transition_id, str)
            or transition_id not in TRANSITION_IDS
            or not re.fullmatch(r"O[1-8]\..+", transition_id)
        ):
            raise RunnerError("managed operation transition ID is unknown")
        for name in ("receipt_id", "project_id", "attempt_id"):
            if not isinstance(receipt.get(name), str) or not receipt[name]:
                raise RunnerError(f"managed operation {name} is invalid")
        if (
            type(receipt.get("epoch")) is not int
            or receipt["epoch"] < 0
            or type(receipt.get("registry_generation")) is not int
            or receipt["registry_generation"] < 0
            or receipt.get("status") != "issued"
            or type(receipt.get("active_incident")) is not bool
        ):
            raise RunnerError("managed operation authority binding is invalid")
        channels = receipt.get("channels")
        if not isinstance(channels, Mapping) or set(channels) != {
            "C1",
            "C2",
            "C3",
            "C4",
            "C5",
        }:
            raise RunnerError("managed operation lacks exact C1-C5 evidence")
        for channel_id, channel in channels.items():
            if (
                not isinstance(channel, Mapping)
                or set(channel) != self._CHANNEL_KEYS
                or channel.get("channel_id") != channel_id
                or channel.get("verdict") != "clean"
                or channel.get("complete") is not True
                or not isinstance(channel.get("evidence_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", channel["evidence_digest"])
            ):
                raise RunnerError("managed operation C1-C5 evidence is not clean")
        self.receipt = receipt
        self.transition_id = transition_id
        self._consumed = False

    def run(self, transition_id: str, action: Callable[[], Any]) -> Any:
        if self._consumed:
            raise RunnerError("managed operation authority receipt was already consumed")
        if transition_id != self.transition_id:
            raise RunnerError("managed operation transition receipt was substituted")
        if self.receipt["active_incident"]:
            raise RunnerError("active incident blocks ordinary managed operation")
        self._consumed = True
        return action()


def _is_component_descendant(path: Path, parent: Path) -> bool:
    """Component-aware containment; never use a string-prefix check."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _prompt_snapshot_paths(registry: RecoveryRegistry) -> tuple[Path, Path, Path]:
    directory = registry.directory
    return directory / "prompt-snapshot.key", directory / "prompt-snapshots", directory / "prompt-snapshots.lock"


def _read_existing_private_prompt_bytes(path: Path, *, maximum: int) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RunnerError("owner prompt snapshot infrastructure is absent") from exc
    reparse = int(getattr(before, "st_file_attributes", 0)) & int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if reparse or stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RunnerError("owner prompt snapshot object is not a stable regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RunnerError("owner prompt snapshot object is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        identity = lambda item: (
            int(item.st_dev),
            int(item.st_ino),
            stat.S_IFMT(int(item.st_mode)),
            int(item.st_size),
            int(item.st_mtime_ns),
        )
        if identity(before) != identity(opened) or opened.st_size > maximum:
            raise RunnerError("owner prompt snapshot identity drifted")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(64 * 1024, maximum + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
            if size > maximum:
                raise RunnerError("owner prompt snapshot exceeds its bound")
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise RunnerError("owner prompt snapshot disappeared") from exc
    if identity(before) != identity(after_open) or identity(after_open) != identity(after):
        raise RunnerError("owner prompt snapshot identity drifted")
    return b"".join(chunks)


def _prompt_snapshot_key(
    registry: RecoveryRegistry,
    *,
    create: bool = True,
) -> bytes:
    key_path, _blobs, _lock = _prompt_snapshot_paths(registry)
    if key_path.is_file():
        try:
            if os.name != "nt":
                metadata = key_path.lstat()
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
                    or metadata.st_mode & 0o077
                ):
                    raise RunnerError("owner prompt snapshot key is not private")
            key = _read_existing_private_prompt_bytes(key_path, maximum=32)
        except OSError as exc:
            raise RunnerError("owner prompt snapshot key is unavailable") from exc
        if len(key) != 32:
            raise RunnerError("owner prompt snapshot key is malformed")
        return key
    if not create:
        raise RunnerError("owner prompt snapshot key is absent")
    ensure_private_run_dir(registry.directory)
    key = secrets.token_bytes(32)
    durable_write_private_bytes(key_path, key)
    return key


def _windows_read_stable_external_prompt(repo: Path, prompt_source: Path) -> bytes:
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", ctypes.c_uint32),
            ("creation_time", FileTime),
            ("access_time", FileTime),
            ("write_time", FileTime),
            ("volume_serial", ctypes.c_uint32),
            ("size_high", ctypes.c_uint32),
            ("size_low", ctypes.c_uint32),
            ("links", ctypes.c_uint32),
            ("file_index_high", ctypes.c_uint32),
            ("file_index_low", ctypes.c_uint32),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.GetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
    kernel32.ReadFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    absolute = Path(os.path.abspath(prompt_source))
    candidates = [Path(absolute.anchor)]
    current = candidates[0]
    for part in absolute.parts[1:]:
        current = current / part
        candidates.append(current)
    generic_read = 0x80000000
    file_read_attributes = 0x00000080
    share_read = 0x00000001
    open_existing = 3
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    invalid_handle = ctypes.c_void_p(-1).value
    handles: list[int] = []

    def information(handle: int) -> ByHandleFileInformation:
        value = ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(
            ctypes.c_void_p(handle), ctypes.byref(value)
        ):
            raise RunnerError(
                f"prompt-identity-unstable: {ctypes.WinError(ctypes.get_last_error())}"
            )
        return value

    def identity(value: ByHandleFileInformation) -> tuple[int, ...]:
        return (
            int(value.attributes),
            int(value.volume_serial),
            int(value.file_index_high),
            int(value.file_index_low),
            int(value.size_high),
            int(value.size_low),
            int(value.write_time.high),
            int(value.write_time.low),
        )

    try:
        final_information: ByHandleFileInformation | None = None
        for index, candidate in enumerate(candidates):
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise RunnerError("prompt-identity-unstable; use owner-private staging API") from exc
            attributes = int(getattr(metadata, "st_file_attributes", 0))
            if candidate.is_symlink() or attributes & reparse_flag:
                raise RunnerError("prompt-identity-unstable; use owner-private staging API")
            final = index == len(candidates) - 1
            handle = kernel32.CreateFileW(
                str(candidate),
                (generic_read | file_read_attributes) if final else file_read_attributes,
                share_read,
                None,
                open_existing,
                open_reparse_point | (0 if final else backup_semantics),
                None,
            )
            if handle in (None, invalid_handle):
                raise RunnerError(
                    f"prompt-identity-unstable: {ctypes.WinError(ctypes.get_last_error())}"
                )
            handle_value = int(handle)
            handles.append(handle_value)
            handle_information = information(handle_value)
            if handle_information.attributes & reparse_flag:
                raise RunnerError("prompt-identity-unstable; use owner-private staging API")
            file_index = (
                int(handle_information.file_index_high) << 32
            ) | int(handle_information.file_index_low)
            if int(metadata.st_ino) != file_index:
                raise RunnerError("prompt-identity-unstable; use owner-private staging API")
            if final:
                final_information = handle_information
        if final_information is None or final_information.attributes & 0x10:
            raise RunnerError("prompt-identity-unstable; use owner-private staging API")
        final_handle = handles[-1]
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(final_handle), buffer, len(buffer), 0
        )
        if not length or length >= len(buffer):
            raise RunnerError("prompt-containment-unprovable; use owner-private staging API")
        final_value = buffer.value
        if final_value.startswith("\\\\?\\UNC\\"):
            final_value = "\\\\" + final_value[8:]
        elif final_value.startswith("\\\\?\\"):
            final_value = final_value[4:]
        final_path = Path(final_value)
        if _is_component_descendant(final_path, repo):
            raise RunnerError("prompt-inside-workspace; use owner-private staging API")
        user_sid = windows_current_user_sid()
        if (
            not windows_directory_is_private(final_path.parent, user_sid)
            or not windows_object_is_private(final_path, user_sid, directory=False)
        ):
            raise RunnerError(
                "prompt-owner-untrusted or prompt-permissions-too-broad; use owner-private staging API"
            )
        before = identity(final_information)
        chunks: list[bytes] = []
        read_buffer = ctypes.create_string_buffer(64 * 1024)
        total = 0
        while True:
            read = ctypes.c_uint32()
            if not kernel32.ReadFile(
                ctypes.c_void_p(final_handle),
                read_buffer,
                len(read_buffer),
                ctypes.byref(read),
                None,
            ):
                raise RunnerError(
                    f"prompt-identity-unstable: {ctypes.WinError(ctypes.get_last_error())}"
                )
            if read.value == 0:
                break
            total += int(read.value)
            if total > MAX_PROMPT_BYTES:
                raise RunnerError("prompt is not bounded UTF-8")
            chunks.append(read_buffer.raw[: read.value])
        if identity(information(final_handle)) != before:
            raise RunnerError("prompt-identity-unstable; use owner-private staging API")
        return b"".join(chunks)
    finally:
        for handle in reversed(handles):
            kernel32.CloseHandle(ctypes.c_void_p(handle))


def _posix_read_stable_external_prompt(repo: Path, prompt_source: Path) -> bytes:
    absolute = Path(os.path.abspath(prompt_source))
    parts = absolute.parts
    if not parts or parts[0] != os.sep:
        raise RunnerError("prompt-containment-unprovable; use owner-private staging API")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        parent_descriptor = os.open(os.sep, directory_flags)
        descriptors.append(parent_descriptor)
        for part in parts[1:-1]:
            parent_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            descriptors.append(parent_descriptor)
        descriptor = os.open(parts[-1], file_flags, dir_fd=parent_descriptor)
        descriptors.append(descriptor)
    except OSError as exc:
        for opened in reversed(descriptors):
            os.close(opened)
        raise RunnerError("prompt-identity-unstable; use owner-private staging API") from exc
    try:
        before = os.fstat(descriptor)
        parent = os.fstat(parent_descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (hasattr(os, "geteuid") and before.st_uid != os.geteuid())
            or before.st_mode & 0o077
        ):
            raise RunnerError(
                "prompt-owner-untrusted or prompt-permissions-too-broad; use owner-private staging API"
            )
        if (
            not stat.S_ISDIR(parent.st_mode)
            or (hasattr(os, "geteuid") and parent.st_uid != os.geteuid())
            or parent.st_mode & 0o077
        ):
            raise RunnerError("prompt-owner-untrusted; use owner-private staging API")
        try:
            if sys.platform == "darwin":
                import fcntl

                resolved = fcntl.fcntl(descriptor, 50, b"\0" * 4096)
                final_path = Path(resolved.split(b"\0", 1)[0].decode("utf-8"))
            else:
                final_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        except (OSError, UnicodeDecodeError) as exc:
            raise RunnerError(
                "prompt-containment-unprovable; use owner-private staging API"
            ) from exc
        if _is_component_descendant(final_path, repo):
            raise RunnerError("prompt-inside-workspace; use owner-private staging API")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 64 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_PROMPT_BYTES:
                raise RunnerError("prompt is not bounded UTF-8")
            chunks.append(block)
        after = os.fstat(descriptor)
        identity_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            raise RunnerError("prompt-identity-unstable; use owner-private staging API")
        return b"".join(chunks)
    finally:
        for opened in reversed(descriptors):
            os.close(opened)


def _read_stable_external_prompt(repo: Path, prompt_source: Path) -> bytes:
    """Read one owner-private external prompt from the same verified object."""
    if os.name == "nt":
        return _windows_read_stable_external_prompt(repo, prompt_source)
    return _posix_read_stable_external_prompt(repo, prompt_source)


def acquire_owner_prompt_snapshot(
    repo: Path,
    prompt_source: Path,
    registry: RecoveryRegistry,
    *,
    transition_context: PromptSnapshotTransitionContext | None = None,
) -> dict[str, str]:
    """Import one stable, private external prompt before any lifecycle mutation."""
    repo = repo.expanduser().resolve(strict=True)
    source = prompt_source.expanduser()
    if not source.is_file():
        raise RunnerError("prompt-identity-unstable; use owner-private staging API")
    source_prompt = _read_stable_external_prompt(repo, source)
    return stage_owner_prompt_snapshot(
        registry,
        source_prompt,
        transition_context=transition_context,
    )


def _prompt_blob_is_visible(
    target: Path,
    *,
    prompt_sha256: str,
) -> bool:
    try:
        return (
            sha256_bytes(
                _read_existing_private_prompt_bytes(
                    target,
                    maximum=MAX_PROMPT_BYTES,
                )
            )
            == prompt_sha256
        )
    except RunnerError:
        return False


def _write_or_reuse_prompt_blob(
    registry: RecoveryRegistry,
    *,
    target: Path,
    source_prompt: bytes,
    prompt_sha256: str,
) -> None:
    if target.exists():
        if not _prompt_blob_is_visible(target, prompt_sha256=prompt_sha256):
            raise RunnerError("owner prompt snapshot identity drifted")
        return
    try:
        durable_write_private_bytes(
            target,
            source_prompt,
            fault=getattr(registry, "fault", None),
        )
    except (OSError, RecoveryStateError) as exc:
        raise RunnerError(f"durable prompt snapshot failed closed: {exc}") from exc


def stage_owner_prompt_snapshot(
    registry: RecoveryRegistry,
    source_prompt: bytes,
    *,
    transition_context: PromptSnapshotTransitionContext | None = None,
) -> dict[str, str]:
    """Persist bounded UTF-8 bytes without putting prompt content on argv."""
    if not isinstance(source_prompt, bytes) or len(source_prompt) > MAX_PROMPT_BYTES:
        raise RunnerError("prompt is not bounded UTF-8")
    try:
        source_prompt.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunnerError("prompt is not bounded UTF-8") from exc
    if (
        transition_context is None
        and getattr(registry, "managed_transition_required", False)
    ):
        raise RunnerError(
            "managed prompt staging requires a guarded transition context"
        )
    prompt_sha256 = sha256_bytes(source_prompt)
    if transition_context is not None:
        if (
            not isinstance(transition_context, PromptSnapshotTransitionContext)
            or transition_context.transition_id != "O4.prompt-snapshot.stage"
        ):
            raise RunnerError("prompt stage transition context was substituted")
        transition_context.validate(registry)
        key_path, blobs, _lock_path = _prompt_snapshot_paths(registry)
        key_sink = f"prompt-key:{registry.workspace_key}"

        def create_or_read_key() -> bytes:
            with registry._lock():
                return _prompt_snapshot_key(registry, create=True)

        key = transition_context.run_sink(
            key_sink,
            create_or_read_key,
            visible=lambda: key_path.is_file()
            and len(_read_existing_private_prompt_bytes(key_path, maximum=32)) == 32,
        )
        if isinstance(key, Mapping) and key.get("status") == "replayed-visible":
            key = _read_existing_private_prompt_bytes(key_path, maximum=32)
        if not isinstance(key, bytes) or len(key) != 32:
            raise RunnerError("prompt snapshot key replay is invalid")
        prompt_snapshot_id = hmac.new(
            key,
            _PROMPT_SNAPSHOT_DOMAIN + bytes.fromhex(prompt_sha256),
            hashlib.sha256,
        ).hexdigest()
        target = blobs / f"{prompt_snapshot_id}.blob"
        blob_sink = f"prompt-blob:{registry.workspace_key}:{prompt_snapshot_id}"

        def write_blob() -> None:
            with registry._lock():
                ensure_private_run_dir(blobs)
                _write_or_reuse_prompt_blob(
                    registry,
                    target=target,
                    source_prompt=source_prompt,
                    prompt_sha256=prompt_sha256,
                )

        transition_context.run_sink(
            blob_sink,
            write_blob,
            visible=lambda: _prompt_blob_is_visible(
                target,
                prompt_sha256=prompt_sha256,
            ),
        )
        transition_context.complete()
        return {
            "prompt_snapshot_id": prompt_snapshot_id,
            "prompt_sha256": prompt_sha256,
        }
    with registry._lock():
        key = _prompt_snapshot_key(registry, create=True)
        _key_path, blobs, _lock_path = _prompt_snapshot_paths(registry)
        ensure_private_run_dir(blobs)
        prompt_snapshot_id = hmac.new(
            key, _PROMPT_SNAPSHOT_DOMAIN + bytes.fromhex(prompt_sha256), hashlib.sha256
        ).hexdigest()
        target = blobs / f"{prompt_snapshot_id}.blob"
        _write_or_reuse_prompt_blob(
            registry,
            target=target,
            source_prompt=source_prompt,
            prompt_sha256=prompt_sha256,
        )
        return {"prompt_snapshot_id": prompt_snapshot_id, "prompt_sha256": prompt_sha256}


def stage_prompt_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise RunnerError(f"repository/workspace directory does not exist: {repo}")
    source_prompt = sys.stdin.buffer.read(MAX_PROMPT_BYTES + 1)
    binding = stage_owner_prompt_snapshot(
        RecoveryRegistry(repo),
        source_prompt,
        transition_context=getattr(args, "transition_context", None),
    )
    print(json.dumps(binding, ensure_ascii=False, sort_keys=True))
    return 0


def read_owner_prompt_snapshot(
    registry: RecoveryRegistry,
    prompt_snapshot_id: str,
    prompt_sha256: str,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", prompt_snapshot_id) or not re.fullmatch(
        r"[0-9a-f]{64}", prompt_sha256
    ):
        raise RunnerError("owner prompt snapshot binding is malformed")
    with registry._read_lock(require_registry=False):
        key = _prompt_snapshot_key(registry, create=False)
        expected_id = hmac.new(
            key, _PROMPT_SNAPSHOT_DOMAIN + bytes.fromhex(prompt_sha256), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_id, prompt_snapshot_id):
            raise RunnerError("owner prompt snapshot binding drifted")
        _key_path, blobs, _lock_path = _prompt_snapshot_paths(registry)
        try:
            prompt = _read_existing_private_prompt_bytes(
                blobs / f"{prompt_snapshot_id}.blob",
                maximum=MAX_PROMPT_BYTES,
            )
        except (OSError, RunnerError) as exc:
            raise RunnerError("owner prompt snapshot is missing") from exc
    if sha256_bytes(prompt) != prompt_sha256:
        raise RunnerError("owner prompt snapshot digest drifted")
    try:
        return prompt.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunnerError("owner prompt snapshot is not UTF-8") from exc


def collect_owner_prompt_snapshot_references(registry: RecoveryRegistry) -> dict[str, set[str]]:
    """Classify private blobs without traversing run directories or public state."""
    with registry._read_lock(require_registry=False):
        return _collect_owner_prompt_snapshot_references_locked(registry)


def _collect_owner_prompt_snapshot_references_locked(
    registry: RecoveryRegistry,
) -> dict[str, set[str]]:
    states = {
        "orphan-unreferenced": set(),
        "grant-referenced": set(),
        "lease-referenced": set(),
        "released": set(),
    }
    _key_path, blobs, _lock_path = _prompt_snapshot_paths(registry)
    blob_ids = {
        path.stem
        for path in blobs.glob("*.blob")
        if re.fullmatch(r"[0-9a-f]{64}", path.stem)
    } if blobs.is_dir() else set()
    if registry.path.is_file():
        state = registry._read_registry_locked(rebarrier=True, allow_quarantine=True)
        for tombstone in state.get("tombstones", []):
            if tombstone.get("event") == "prompt-snapshot-released":
                states["released"].add(tombstone["prompt_snapshot_id"])
        lease = state.get("lease")
        if isinstance(lease, dict):
            plan = lease.get("plan", {})
            snapshot_id = (
                plan.get("prompt_snapshot_id")
                if lease.get("lease_kind") == "recovery-target"
                else lease.get("prompt_snapshot_id")
            )
            if isinstance(snapshot_id, str):
                states["lease-referenced"].add(snapshot_id)
        if registry.sources_directory.is_dir():
            for path in registry.sources_directory.glob("*.json"):
                try:
                    source = registry._read_source_locked(path.stem, rebarrier=True)
                except (OSError, RecoveryStateError) as exc:
                    raise RunnerError(
                        "owner prompt snapshot reference state is unreadable"
                    ) from exc
                authorization = source.get("authorization") if isinstance(source, dict) else None
                snapshot_id = (
                    authorization.get("prompt_snapshot_id")
                    if isinstance(authorization, dict)
                    else None
                )
                if isinstance(snapshot_id, str):
                    states["grant-referenced"].add(snapshot_id)
    states["grant-referenced"] -= states["lease-referenced"]
    states["released"] -= states["grant-referenced"] | states["lease-referenced"]
    states["orphan-unreferenced"] = blob_ids - set().union(*states.values())
    return states


def _garbage_collect_owner_prompt_snapshots_unguarded(
    registry: RecoveryRegistry,
) -> set[str]:
    """Under the owner lock, remove only orphan/released blobs; run trees are excluded."""
    deleted: set[str] = set()
    with registry._lock():
        references = _collect_owner_prompt_snapshot_references_locked(registry)
        active = references["grant-referenced"] | references["lease-referenced"]
        eligible = references["orphan-unreferenced"] | (
            references["released"] - active
        )
        _key_path, blobs, _lock_path = _prompt_snapshot_paths(registry)
        for snapshot_id in eligible:
            target = blobs / f"{snapshot_id}.blob"
            if target.is_file():
                target.unlink()
                deleted.add(snapshot_id)
    return deleted


def garbage_collect_owner_prompt_snapshots(
    registry: RecoveryRegistry,
    *,
    transition_context: PromptSnapshotTransitionContext | None = None,
) -> set[str]:
    if transition_context is None:
        return _garbage_collect_owner_prompt_snapshots_unguarded(registry)
    if (
        not isinstance(transition_context, PromptSnapshotTransitionContext)
        or transition_context.transition_id != "O8.prompt-snapshot.gc"
    ):
        raise RunnerError("prompt GC transition context was substituted")
    transition_context.validate(registry)
    result = transition_context.run_sink(
        f"prompt-gc:{registry.workspace_key}",
        lambda: _garbage_collect_owner_prompt_snapshots_unguarded(registry),
    )
    transition_context.complete()
    if not isinstance(result, set):
        raise RunnerError("prompt GC replay result is invalid")
    return result


def read_event_evidence(path: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "completed": False,
        "event_error": None,
        "failure_message": None,
        "terminal_event_count": 0,
        "terminal_event": None,
        "thread_id": None,
        "usage": None,
        "structured_errors": [],
        "turn_started": False,
    }
    try:
        raw = read_regular_file_no_follow(path)
    except DiscoveryContractError:
        evidence["event_error"] = "events artifact is unreadable or unstable"
        return evidence
    if raw is None:
        return evidence

    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        evidence["event_error"] = f"events are not UTF-8: {exc}"
        return evidence

    last_event_type: str | None = None
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            evidence["event_error"] = f"invalid JSONL at line {line_number}: {exc.msg}"
            break
        if not isinstance(event, dict):
            evidence["event_error"] = f"invalid JSONL at line {line_number}: expected an object"
            break
        event_type = event.get("type")
        last_event_type = event_type if isinstance(event_type, str) else None
        if event_type == "turn.started":
            evidence["turn_started"] = True
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            evidence["thread_id"] = event["thread_id"]
        if event_type in TERMINAL_EVENTS:
            evidence["terminal_event_count"] += 1
            evidence["terminal_event"] = event_type
            if event_type == "turn.completed":
                evidence["usage"] = event.get("usage")
            else:
                error = event.get("error")
                if not evidence["turn_started"]:
                    evidence["structured_errors"].append(event)
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    evidence["failure_message"] = error["message"]
        elif event_type == "error" and not evidence["failure_message"]:
            if not evidence["turn_started"]:
                evidence["structured_errors"].append(event)
            message = event.get("message")
            if isinstance(message, str):
                evidence["failure_message"] = message
        elif event_type == "error":
            if not evidence["turn_started"]:
                evidence["structured_errors"].append(event)
        elif "code" in event or event_type in RAW_SEARCH_ERROR_TYPES:
            if not evidence["turn_started"]:
                evidence["structured_errors"].append(event)
        elif "error" in event or (
            isinstance(event_type, str) and event_type.endswith(".failed")
        ) or event_type not in NON_ERROR_JSONL_EVENT_TYPES:
            evidence["event_error"] = (
                f"unrecognized error-bearing JSONL event at line {line_number}"
            )
            break

    if evidence["event_error"] is None and evidence["terminal_event_count"] > 1:
        evidence["event_error"] = (
            "JSONL must contain at most one terminal turn event; "
            f"found {evidence['terminal_event_count']}"
        )
    if (
        evidence["event_error"] is None
        and evidence["terminal_event"] is not None
        and last_event_type != evidence["terminal_event"]
    ):
        evidence["event_error"] = "terminal turn event must be the last nonblank JSONL event"
    if (
        evidence["event_error"] is None
        and evidence["terminal_event"] == "turn.completed"
        and not (isinstance(evidence["thread_id"], str) and evidence["thread_id"].strip())
    ):
        evidence["event_error"] = (
            "turn.completed requires a preceding thread.started event with a non-empty thread_id"
        )
    evidence["completed"] = evidence["terminal_event"] == "turn.completed" and evidence["event_error"] is None
    return evidence


def final_result_error(path: Path) -> str | None:
    try:
        raw = read_regular_file_no_follow(path)
    except DiscoveryContractError as exc:
        return f"invalid final result artifact: {exc}"
    if raw is None:
        return "missing final result artifact"
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return f"invalid final result artifact: {exc}"
    if not value.strip():
        return "final result artifact is empty"
    return None


def codex_exit_evidence_status(
    run_dir: Path,
    *,
    expected_pid: Any,
    expected_identity: Any,
) -> tuple[int | None, str]:
    path = run_dir / "codex-exit.json"
    if not path.is_file():
        return None, "missing"
    try:
        record = read_json(path)
    except RunnerError:
        return None, "malformed"
    if record.get("pid") != expected_pid or record.get("identity") != expected_identity:
        return None, "identity-mismatch"
    exit_code = record.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return None, "malformed"
    return exit_code, "valid"


def codex_exit_evidence(
    run_dir: Path,
    *,
    expected_pid: Any,
    expected_identity: Any,
) -> tuple[int | None, str | None]:
    exit_code, status = codex_exit_evidence_status(
        run_dir,
        expected_pid=expected_pid,
        expected_identity=expected_identity,
    )
    messages = {
        "missing": "missing creation-bound Codex exit artifact",
        "malformed": "invalid creation-bound Codex exit artifact",
        "identity-mismatch": "Codex exit artifact does not match the dispatched PID and creation identity",
    }
    return exit_code, messages.get(status)


def result_evidence_status(path: Path) -> str:
    error = final_result_error(path)
    if error is None:
        return "valid"
    if error == "missing final result artifact":
        return "missing"
    if error == "final result artifact is empty":
        return "empty"
    return "invalid"


def execution_failure_message(returncode: int, evidence: Mapping[str, Any]) -> str | None:
    if returncode == 0 and evidence.get("completed") is True:
        return None
    structured = evidence.get("failure_message") or evidence.get("event_error")
    if isinstance(structured, str) and structured:
        return structured
    if returncode != 0:
        return f"codex exec exited with code {returncode}"
    return "missing turn.completed"


def resolve_codex_binary(value: str) -> str:
    resolved = shutil.which(value)
    if resolved:
        return resolved
    path = Path(value).expanduser()
    if path.is_file():
        return str(path.resolve())
    raise RunnerError(f"Codex CLI executable not found: {value!r}")


def default_run_root() -> Path:
    return Path(tempfile.gettempdir()) / "openbuild-agent-runs"


def default_run_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return default_run_root() / f"{stamp}-{uuid.uuid4().hex[:10]}"


def resolve_run_reference(value: str) -> Path:
    """Resolve a public generated handle or a caller-retained legacy path."""
    candidate = value.strip()
    if RUN_HANDLE.fullmatch(candidate):
        return (default_run_root().resolve() / candidate).resolve()
    return Path(candidate).expanduser().resolve()


def public_run_handle(run_dir: Path) -> str | None:
    resolved = run_dir.resolve()
    if resolved.parent == default_run_root().resolve() and RUN_HANDLE.fullmatch(resolved.name):
        return resolved.name
    return None


def _windows_kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    kernel32.IsProcessInJob.restype = ctypes.c_int
    kernel32.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.QueryInformationJobObject.restype = ctypes.c_int
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateJobObject.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    return kernel32


def create_windows_kill_job(*, bind_current: bool = True) -> Any:
    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_int64),
            ("per_job_user_time_limit", ctypes.c_int64),
            ("limit_flags", ctypes.c_uint32),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", ctypes.c_uint32),
            ("affinity", ctypes.c_size_t),
            ("priority_class", ctypes.c_uint32),
            ("scheduling_class", ctypes.c_uint32),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operation_count", ctypes.c_uint64),
            ("write_operation_count", ctypes.c_uint64),
            ("other_operation_count", ctypes.c_uint64),
            ("read_transfer_count", ctypes.c_uint64),
            ("write_transfer_count", ctypes.c_uint64),
            ("other_transfer_count", ctypes.c_uint64),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", BasicLimitInformation),
            ("io_info", IoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]

    kernel32 = _windows_kernel32()
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise RunnerError(f"cannot create Windows cleanup Job Object: {ctypes.WinError()}")
    information = ExtendedLimitInformation()
    information.basic_limit_information.limit_flags = 0x00002000
    if not kernel32.SetInformationJobObject(
        handle,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error = ctypes.WinError()
        kernel32.CloseHandle(handle)
        raise RunnerError(f"cannot configure Windows cleanup Job Object: {error}")
    if bind_current and not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        error = ctypes.WinError()
        kernel32.CloseHandle(handle)
        raise RunnerError(f"cannot bind worker to Windows cleanup Job Object: {error}")
    return handle


def assign_windows_process_to_job(job: Any, process: Any) -> None:
    kernel32 = _windows_kernel32()
    process_handle = getattr(process, "_handle", None)
    opened = False
    if not process_handle:
        process_handle = kernel32.OpenProcess(0x001F0FFF, False, int(process.pid))
        opened = True
    if not process_handle:
        raise RunnerError(f"cannot open worker {process.pid} for Job assignment")
    try:
        if not kernel32.AssignProcessToJobObject(job, process_handle):
            raise RunnerError(f"cannot assign worker to Windows cleanup Job Object: {ctypes.WinError()}")
    finally:
        if opened:
            kernel32.CloseHandle(process_handle)


def verify_windows_process_in_job(job: Any, process: Any) -> None:
    kernel32 = _windows_kernel32()
    process_handle = getattr(process, "_handle", None)
    if not process_handle:
        raise RunnerError("suspended Windows worker lacks a creation-bound process handle")
    assigned = ctypes.c_int()
    if not kernel32.IsProcessInJob(process_handle, job, ctypes.byref(assigned)):
        raise RunnerError(f"cannot verify Windows Job assignment: {ctypes.WinError()}")
    if not assigned.value:
        raise RunnerError("Windows worker was not retained by its guardian-owned Job")


def resume_windows_suspended_process(process: Any) -> None:
    process_handle = getattr(process, "_handle", None)
    if not process_handle:
        raise RunnerError("suspended Windows worker lacks a creation-bound process handle")
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    ntdll.NtResumeProcess.restype = ctypes.c_long
    status = int(ntdll.NtResumeProcess(process_handle))
    if status < 0:
        raise RunnerError(f"cannot resume creation-bound Windows worker: NTSTATUS 0x{status & 0xFFFFFFFF:08x}")


def query_windows_job_active_processes(job: Any) -> int:
    class BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("total_user_time", ctypes.c_int64),
            ("total_kernel_time", ctypes.c_int64),
            ("this_period_total_user_time", ctypes.c_int64),
            ("this_period_total_kernel_time", ctypes.c_int64),
            ("total_page_fault_count", ctypes.c_uint32),
            ("total_processes", ctypes.c_uint32),
            ("active_processes", ctypes.c_uint32),
            ("total_terminated_processes", ctypes.c_uint32),
        ]

    information = BasicAccountingInformation()
    if not _windows_kernel32().QueryInformationJobObject(
        job,
        1,
        ctypes.byref(information),
        ctypes.sizeof(information),
        None,
    ):
        raise RunnerError(f"cannot query Windows cleanup Job Object: {ctypes.WinError()}")
    return int(information.active_processes)


def close_windows_job(job: Any) -> None:
    if job and not _windows_kernel32().CloseHandle(job):
        raise RunnerError(f"cannot close Windows cleanup Job Object: {ctypes.WinError()}")


def create_linux_cgroup(guardian_id: str) -> Path:
    if sys.platform != "linux":
        raise RunnerError("Linux cgroup v2 containment is unavailable on this platform")
    if os.environ.get("OPENBUILD_CGROUP_V2_DELEGATION") != "verified-no-migration":
        raise RunnerError("Linux cgroup v2 delegation is not explicitly verified as migration-resistant")
    root = Path(os.environ.get("OPENBUILD_CGROUP_V2_ROOT", "/sys/fs/cgroup")).resolve()
    if not (root / "cgroup.controllers").is_file():
        raise RunnerError("Linux cgroup v2 unified hierarchy is unavailable")
    cgroup = root / f"openbuild-{guardian_id}"
    try:
        cgroup.mkdir(mode=0o700)
    except OSError as exc:
        raise RunnerError(f"cannot create Linux cgroup v2 containment: {exc}") from exc
    if not (cgroup / "cgroup.procs").is_file() or not (cgroup / "cgroup.events").is_file():
        try:
            cgroup.rmdir()
        except OSError:
            pass
        raise RunnerError("Linux cgroup v2 provider did not expose required control files")
    return cgroup


def query_linux_cgroup_members(cgroup: Path) -> set[int]:
    try:
        return {int(value) for value in (cgroup / "cgroup.procs").read_text(encoding="ascii").split()}
    except (OSError, ValueError) as exc:
        raise RunnerError(f"cannot read Linux cgroup v2 membership: {exc}") from exc


_LINUX_CLONE_NEWNS = 0x00020000
_LINUX_CLONE_NEWCGROUP = 0x02000000
_LINUX_MS_RDONLY = 0x00000001
_LINUX_MS_REMOUNT = 0x00000020
_LINUX_MS_BIND = 0x00001000
_LINUX_MS_REC = 0x00004000
_LINUX_MS_PRIVATE = 0x00040000
_LINUX_PR_SET_SECUREBITS = 28
_LINUX_PR_CAPBSET_DROP = 24
_LINUX_PR_SET_NO_NEW_PRIVS = 38
_LINUX_SECUREBITS_LOCKED_NO_ROOT = 0xEF
_LINUX_CAP_VERSION_3 = 0x20080522


def _linux_libc() -> Any:
    return ctypes.CDLL(None, use_errno=True)


def _linux_call(name: str, result: int) -> None:
    if result != 0:
        code = ctypes.get_errno()
        raise RunnerError(f"Linux anti-migration {name} failed: {os.strerror(code)}")


def _decode_linux_mount_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def linux_cgroup2_mounts() -> list[dict[str, Any]]:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RunnerError(f"cannot read Linux mount namespace: {exc}") from exc
    mounts: list[dict[str, Any]] = []
    for line in lines:
        if " - " not in line:
            raise RunnerError("Linux mountinfo is malformed")
        before, after = line.split(" - ", 1)
        left = before.split()
        right = after.split()
        if len(left) < 6 or len(right) < 3:
            raise RunnerError("Linux mountinfo is malformed")
        if right[0] == "cgroup2":
            mounts.append(
                {
                    "root": _decode_linux_mount_path(left[3]),
                    "mountpoint": _decode_linux_mount_path(left[4]),
                    "options": set(left[5].split(",")),
                }
            )
    if not mounts:
        raise RunnerError("Linux anti-migration boundary found no cgroup v2 mount")
    return mounts


def _linux_mount(source: str | None, target: str, flags: int) -> None:
    libc = _linux_libc()
    mount = libc.mount
    mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    mount.restype = ctypes.c_int
    _linux_call(
        f"mount({target})",
        mount(
            source.encode("utf-8") if source is not None else None,
            target.encode("utf-8"),
            None,
            flags,
            None,
        ),
    )


def _linux_drop_all_capabilities() -> None:
    class CapabilityHeader(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]

    class CapabilityData(ctypes.Structure):
        _fields_ = [
            ("effective", ctypes.c_uint32),
            ("permitted", ctypes.c_uint32),
            ("inheritable", ctypes.c_uint32),
        ]

    libc = _linux_libc()
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    _linux_call(
        "securebits lock",
        prctl(_LINUX_PR_SET_SECUREBITS, _LINUX_SECUREBITS_LOCKED_NO_ROOT, 0, 0, 0),
    )
    try:
        cap_last = int(Path("/proc/sys/kernel/cap_last_cap").read_text(encoding="ascii").strip())
    except (OSError, ValueError) as exc:
        raise RunnerError(f"cannot read Linux capability ceiling: {exc}") from exc
    for capability in range(cap_last + 1):
        result = prctl(_LINUX_PR_CAPBSET_DROP, capability, 0, 0, 0)
        if result != 0 and ctypes.get_errno() != errno.EINVAL:
            _linux_call(f"capability bounding drop {capability}", result)
    header = CapabilityHeader(_LINUX_CAP_VERSION_3, 0)
    data = (CapabilityData * 2)()
    capset = libc.capset
    capset.argtypes = [ctypes.POINTER(CapabilityHeader), ctypes.POINTER(CapabilityData)]
    capset.restype = ctypes.c_int
    _linux_call("capability clear", capset(ctypes.byref(header), data))
    _linux_call("no-new-privileges", prctl(_LINUX_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))


def _linux_status_security() -> dict[str, Any]:
    try:
        lines = Path("/proc/self/status").read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise RunnerError(f"cannot read Linux process security state: {exc}") from exc
    values: dict[str, str] = {}
    for line in lines:
        if line.startswith(("CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:", "NoNewPrivs:")):
            key, value = line.split(None, 1)
            values[key.rstrip(":")] = value.strip()
    if any(
        values.get(field) != "0000000000000000"
        for field in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]
    ):
        raise RunnerError("Linux anti-migration worker retained capabilities")
    if values.get("NoNewPrivs") != "1":
        raise RunnerError("Linux anti-migration worker lacks no-new-privileges")
    return {"capabilities_zero": True, "no_new_privs": True}


def _linux_unprivileged_user_namespaces_disabled() -> bool:
    observed = False
    for path in [
        Path("/proc/sys/kernel/unprivileged_userns_clone"),
        Path("/proc/sys/user/max_user_namespaces"),
    ]:
        if not path.is_file():
            continue
        observed = True
        try:
            if path.read_text(encoding="ascii").strip() == "0":
                return True
        except OSError as exc:
            raise RunnerError(f"cannot read Linux user-namespace policy: {exc}") from exc
    if not observed:
        raise RunnerError("Linux user-namespace policy is unavailable")
    return False


def _linux_assert_no_cgroup_control_fds(mounts: list[dict[str, Any]]) -> None:
    mountpoints = [Path(item["mountpoint"]).resolve() for item in mounts]
    try:
        descriptors = list(Path("/proc/self/fd").iterdir())
    except OSError as exc:
        raise RunnerError(f"cannot enumerate Linux worker descriptors: {exc}") from exc
    for descriptor in descriptors:
        try:
            target = descriptor.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if any(target == root or target.is_relative_to(root) for root in mountpoints):
            raise RunnerError("Linux anti-migration worker inherited a cgroup control descriptor")


def establish_linux_anti_migration_boundary(run_dir: Path, worker_identity: str) -> dict[str, Any]:
    """Create kernel-observed cgroup+mount isolation before delegated auth or code."""
    secret = _guardian_secret(run_dir)
    request_path = run_dir / "linux-anti-migration-request.json"
    deadline = time.monotonic() + 20.0
    while not request_path.is_file():
        if time.monotonic() >= deadline:
            raise RunnerError("Linux anti-migration request was not published before worker startup")
        time.sleep(0.05)
    request = read_guardian_message(request_path, secret, "linux-anti-migration-request")
    if (
        int(request.get("worker_pid") or 0) != os.getpid()
        or request.get("worker_identity") != worker_identity
        or not isinstance(request.get("guardian_id"), str)
    ):
        raise RunnerError("Linux anti-migration request changed the creation-bound worker")
    cgroup = Path(str(request.get("cgroup_path") or "")).resolve()
    if not cgroup.is_dir() or os.getpid() not in query_linux_cgroup_members(cgroup):
        raise RunnerError("Linux anti-migration worker is not attached to its planned cgroup")

    libc = _linux_libc()
    unshare = libc.unshare
    unshare.argtypes = [ctypes.c_int]
    unshare.restype = ctypes.c_int
    _linux_call(
        "cgroup+mount namespace creation",
        unshare(_LINUX_CLONE_NEWCGROUP | _LINUX_CLONE_NEWNS),
    )
    _linux_mount(None, "/", _LINUX_MS_REC | _LINUX_MS_PRIVATE)
    for mount in linux_cgroup2_mounts():
        _linux_mount(None, mount["mountpoint"], _LINUX_MS_BIND | _LINUX_MS_REMOUNT | _LINUX_MS_RDONLY)
    _linux_drop_all_capabilities()
    if os.geteuid() == 0:
        raise RunnerError("Linux recovery containment refuses a root-identity worker")
    if not _linux_unprivileged_user_namespaces_disabled():
        raise RunnerError("Linux unprivileged user namespaces could reacquire mount capability")
    security = _linux_status_security()
    mounts = linux_cgroup2_mounts()
    if any("ro" not in mount["options"] or "rw" in mount["options"] for mount in mounts):
        raise RunnerError("Linux cgroup v2 view remained writable after namespace isolation")
    for mount in mounts:
        control = Path(mount["mountpoint"]) / "cgroup.procs"
        try:
            descriptor = os.open(control, os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
                raise RunnerError(f"Linux cgroup write-denial probe failed: {exc}") from exc
        else:
            os.close(descriptor)
            raise RunnerError("Linux cgroup v2 control remained writable inside the worker namespace")
    _linux_assert_no_cgroup_control_fds(mounts)
    try:
        self_cgroup = Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
        cgroup_namespace = os.readlink("/proc/self/ns/cgroup")
        mount_namespace = os.readlink("/proc/self/ns/mnt")
    except OSError as exc:
        raise RunnerError(f"cannot read Linux anti-migration namespace identity: {exc}") from exc
    if self_cgroup != ["0::/"]:
        raise RunnerError("Linux cgroup namespace is not rooted at the contained cgroup")
    receipt = {
        "guardian_id": request["guardian_id"],
        "worker_pid": os.getpid(),
        "worker_identity": worker_identity,
        "cgroup_namespace": cgroup_namespace,
        "mount_namespace": mount_namespace,
        "self_cgroup": "/",
        "cgroup_mount_count": len(mounts),
        "cgroup_mounts_read_only": True,
        "cgroup_write_denied": True,
        "no_cgroup_control_fds": True,
        "unprivileged_user_namespaces_disabled": True,
        **security,
    }
    write_guardian_message(
        run_dir / "linux-anti-migration-ready.json",
        secret,
        "linux-anti-migration-ready",
        receipt,
    )
    return receipt


def validate_linux_anti_migration_receipt(
    receipt: Mapping[str, Any],
    *,
    guardian_id: str,
    worker_pid: int,
    worker_identity: str,
    guardian_cgroup_namespace: str,
    guardian_mount_namespace: str,
) -> None:
    if (
        receipt.get("guardian_id") != guardian_id
        or int(receipt.get("worker_pid") or 0) != worker_pid
        or receipt.get("worker_identity") != worker_identity
    ):
        raise RunnerError("Linux anti-migration receipt changed the guardian or worker binding")
    for field in [
        "cgroup_mounts_read_only",
        "cgroup_write_denied",
        "no_cgroup_control_fds",
        "unprivileged_user_namespaces_disabled",
        "capabilities_zero",
        "no_new_privs",
    ]:
        if receipt.get(field) is not True:
            raise RunnerError(f"Linux anti-migration receipt lacks kernel proof: {field}")
    if int(receipt.get("cgroup_mount_count") or 0) < 1 or receipt.get("self_cgroup") != "/":
        raise RunnerError("Linux anti-migration receipt lacks a rooted read-only cgroup view")
    if (
        not isinstance(receipt.get("cgroup_namespace"), str)
        or not isinstance(receipt.get("mount_namespace"), str)
        or receipt["cgroup_namespace"] == guardian_cgroup_namespace
        or receipt["mount_namespace"] == guardian_mount_namespace
    ):
        raise RunnerError("Linux worker did not enter private cgroup and mount namespaces")


def query_linux_cgroup_populated(cgroup: Path) -> bool:
    try:
        events = parse_linux_cgroup_events((cgroup / "cgroup.events").read_text(encoding="ascii"))
    except OSError as exc:
        raise RunnerError(f"cannot read Linux cgroup v2 zero proof: {exc}") from exc
    return events["populated"] != 0


def close_linux_cgroup(cgroup: Path) -> None:
    if query_linux_cgroup_populated(cgroup):
        raise RunnerError("cannot remove a populated Linux cgroup v2 containment")
    try:
        cgroup.rmdir()
    except OSError as exc:
        raise RunnerError(f"cannot remove Linux cgroup v2 containment: {exc}") from exc


def terminate_guardian_provider(provider: str, handle: Any) -> None:
    if provider == "windows-job":
        if not _windows_kernel32().TerminateJobObject(handle, 1):
            raise RunnerError(f"cannot terminate Windows cleanup Job Object: {ctypes.WinError()}")
        return
    if provider == "linux-cgroup-v2":
        kill_path = handle / "cgroup.kill"
        if not kill_path.is_file():
            raise RunnerError("Linux cgroup v2 provider lacks cgroup.kill")
        try:
            kill_path.write_text("1\n", encoding="ascii", newline="\n")
        except OSError as exc:
            raise RunnerError(f"cannot terminate Linux cgroup v2 containment: {exc}") from exc
        return
    raise RunnerError("unknown containment provider")


def terminate_windows_process_record(record: Mapping[str, Any], timeout: float) -> None:
    pid = int(record.get("pid") or 0)
    expected_identity = record.get("identity")
    if pid <= 0:
        return
    kernel32 = _windows_kernel32()
    handle = kernel32.OpenProcess(0x00101001, False, pid)
    if not handle:
        if process_status(pid) == "stopped":
            return
        raise RunnerError(f"cannot open creation-bound Windows process {pid} for termination")
    try:
        if windows_process_identity_from_handle(handle) != expected_identity:
            return
        exit_code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise RunnerError(f"cannot inspect creation-bound Windows process {pid}")
        if exit_code.value != 259:
            return
        if not kernel32.TerminateProcess(handle, 1):
            raise RunnerError(f"cannot terminate creation-bound Windows process {pid}")
        wait_result = kernel32.WaitForSingleObject(handle, max(1, int(timeout * 1000)))
        if wait_result != 0:
            raise RunnerError(f"creation-bound Windows process {pid} did not stop")
    finally:
        kernel32.CloseHandle(handle)


def process_status(pid: int) -> str:
    if pid <= 0:
        return "stopped"
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = _windows_kernel32()
        ctypes.set_last_error(0)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return "stopped" if ctypes.get_last_error() == 87 else "unknown"
        try:
            exit_code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return "unknown"
            return "running" if exit_code.value == still_active else "stopped"
        finally:
            kernel32.CloseHandle(handle)
    proc_status = procfs_process_status(pid)
    if proc_status is not None:
        return proc_status
    ps_status = ps_process_status(pid)
    if ps_status is not None:
        return ps_status
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        return "running"
    except OSError:
        return "unknown"
    return "running"


def process_is_running(pid: int) -> bool:
    return process_status(pid) == "running"


def darwin_process_start_time(pid: int) -> tuple[int, int] | None:
    """Return macOS' microsecond-resolution kernel process start time."""

    class ProcBsdInfo(ctypes.Structure):
        _fields_ = [
            ("flags", ctypes.c_uint32),
            ("status", ctypes.c_uint32),
            ("xstatus", ctypes.c_uint32),
            ("pid", ctypes.c_uint32),
            ("ppid", ctypes.c_uint32),
            ("uid", ctypes.c_uint32),
            ("gid", ctypes.c_uint32),
            ("ruid", ctypes.c_uint32),
            ("rgid", ctypes.c_uint32),
            ("svuid", ctypes.c_uint32),
            ("svgid", ctypes.c_uint32),
            ("rfu_1", ctypes.c_uint32),
            ("comm", ctypes.c_char * 16),
            ("name", ctypes.c_char * 32),
            ("nfiles", ctypes.c_uint32),
            ("pgid", ctypes.c_uint32),
            ("pjobc", ctypes.c_uint32),
            ("e_tdev", ctypes.c_uint32),
            ("e_tpgid", ctypes.c_uint32),
            ("nice", ctypes.c_int32),
            ("start_tvsec", ctypes.c_uint64),
            ("start_tvusec", ctypes.c_uint64),
        ]

    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_pidinfo.restype = ctypes.c_int
        information = ProcBsdInfo()
        size = libproc.proc_pidinfo(
            pid,
            3,
            0,
            ctypes.byref(information),
            ctypes.sizeof(information),
        )
    except OSError:
        return None
    if size != ctypes.sizeof(information) or information.pid != pid:
        return None
    return int(information.start_tvsec), int(information.start_tvusec)


def parse_procfs_stat(value: str) -> tuple[str, int, str] | None:
    closing = value.rfind(")")
    fields = value[closing + 2 :].split()
    if closing <= 0 or len(fields) <= 19:
        return None
    try:
        return fields[0], int(fields[2]), fields[19]
    except ValueError:
        return None


def read_procfs_stat(pid: int) -> tuple[str, int, str] | None:
    try:
        return parse_procfs_stat(Path(f"/proc/{pid}/stat").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def procfs_process_status(pid: int) -> str | None:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    record = read_procfs_stat(pid)
    if record is not None:
        return "stopped" if record[0] == "Z" else "running"
    return "stopped" if not (proc_root / str(pid)).exists() else "unknown"


def ps_process_status(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return "stopped" if result.returncode in {0, 1} else "unknown"
    return "stopped" if value.startswith("Z") else "running"


def procfs_process_start_ticks(pid: int) -> str | None:
    record = read_procfs_stat(pid)
    return record[2] if record is not None else None


def process_identity(pid: int) -> str | None:
    """Return an OS creation identity that changes when a PID is reused."""

    if pid <= 0:
        return None
    if os.name == "nt":
        process_query_limited_information = 0x1000
        kernel32 = _windows_kernel32()
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            return windows_process_identity_from_handle(handle)
        finally:
            kernel32.CloseHandle(handle)

    proc_start = procfs_process_start_ticks(pid)
    if proc_start is not None:
        return f"proc-starttime:{proc_start}"
    if sys.platform == "darwin":
        started = darwin_process_start_time(pid)
        if started is not None:
            return f"darwin-starttime:{started[0]}:{started[1]}"
    # A second-resolution `ps lstart` value can collide after PID reuse. Unknown is safer:
    # callers refuse activation, signalling, and lease release without a precise identity.
    return None


def windows_process_identity_from_handle(handle: Any) -> str | None:
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    kernel32 = _windows_kernel32()
    created = FileTime()
    exited = FileTime()
    kernel = FileTime()
    user = FileTime()
    if not kernel32.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    value = (created.high << 32) | created.low
    return f"windows-filetime:{value}"


def process_identity_from_popen(process: Any) -> str | None:
    """Bind creation identity to the original child handle, never a bare PID lookup alone."""

    if process.poll() is not None:
        return None
    if os.name == "nt":
        handle = getattr(process, "_handle", None)
        identity = windows_process_identity_from_handle(handle) if handle else None
    else:
        identity = process_identity(process.pid)
    if identity is None or process.poll() is not None:
        return None
    if os.name != "nt" and process_identity(process.pid) != identity:
        return None
    return identity


def process_record_state(record: Mapping[str, Any]) -> str:
    pid = int(record.get("pid") or 0)
    identity = record.get("identity")
    if pid <= 0:
        return "stopped"
    if not isinstance(identity, str) or not identity:
        return "unknown"
    status = process_status(pid)
    if status != "running":
        return status
    current_identity = process_identity(pid)
    if current_identity is None:
        return "unknown"
    return "running" if current_identity == identity else "reused"


def process_record_is_running(record: Mapping[str, Any]) -> bool:
    return process_record_state(record) == "running"


def process_group_status(process_group_id: int) -> str:
    if process_group_id <= 0:
        return "stopped"
    if os.name == "nt":
        return "unknown"
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        pass
    except OSError:
        return "unknown"
    proc_state = procfs_process_group_status(process_group_id)
    if proc_state is not None:
        return proc_state
    return ps_process_group_status(process_group_id)


def procfs_process_group_status(process_group_id: int) -> str | None:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    observed_member = False
    unreadable_member = False
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return "unknown"
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            value = (entry / "stat").read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError):
            unreadable_member = True
            continue
        record = parse_procfs_stat(value)
        if record is None or record[1] != process_group_id:
            continue
        observed_member = True
        if record[0] != "Z":
            return "running"
    if unreadable_member:
        return "unknown"
    if observed_member:
        return "stopped"
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        return "unknown"
    except OSError:
        return "unknown"
    return "unknown"


def ps_process_group_status(process_group_id: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pgid=,stat="],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    observed_member = False
    for line in result.stdout.splitlines():
        fields = line.split(None, 1)
        if len(fields) != 2:
            continue
        try:
            pgid = int(fields[0])
        except ValueError:
            continue
        if pgid != process_group_id:
            continue
        observed_member = True
        if not fields[1].startswith("Z"):
            return "running"
    if observed_member:
        return "stopped"
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return "stopped"
    except OSError:
        return "unknown"
    return "unknown"


def process_tree_record_state(record: Mapping[str, Any]) -> str:
    leader_state = process_record_state(record)
    if leader_state == "reused":
        return "stopped"
    if os.name == "nt" or int(record.get("pid") or 0) <= 0:
        return leader_state
    group_id = int(record.get("process_group_id") or record.get("pid") or 0)
    group_state = process_group_status(group_id)
    if leader_state == "unknown" or group_state == "unknown":
        return "unknown"
    if group_state == "running":
        return "running"
    return "stopped"


def _background_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def _guardian_secret(run_dir: Path) -> bytes:
    try:
        secret = (run_dir / "guardian.key").read_bytes()
    except OSError as exc:
        raise RunnerError(f"guardian IPC key is unavailable: {exc}") from exc
    if len(secret) != 32:
        raise RunnerError("guardian IPC key must contain exactly 32 bytes")
    return secret


def _spawn_worker_process(
    run_dir: Path,
    runner_log: Any,
    *,
    contained: bool,
    provider: str | None = None,
    start_suspended: bool = False,
) -> Any:
    environment = dict(os.environ)
    if contained:
        environment["OPENBUILD_CONTAINED_BY_GUARDIAN"] = "1"
        if provider is not None:
            environment["OPENBUILD_CONTAINMENT_PROVIDER"] = provider
    else:
        environment.pop("OPENBUILD_CONTAINED_BY_GUARDIAN", None)
        environment.pop("OPENBUILD_CONTAINMENT_PROVIDER", None)
    options = _background_options()
    if start_suspended:
        if os.name != "nt":
            raise RunnerError("suspended worker creation is available only on Windows")
        options["creationflags"] |= _WINDOWS_CREATE_SUSPENDED
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_worker", "--run-dir", str(run_dir)],
        stdin=subprocess.DEVNULL,
        stdout=runner_log,
        stderr=runner_log,
        close_fds=True,
        env=environment,
        **options,
    )


class _LinuxClone3Process:
    """Small Popen-compatible owner for a direct clone3 child."""

    def __init__(self, pid: int, pidfd: int, args: list[str]) -> None:
        self.pid = pid
        self.pidfd = pidfd
        self.args = args
        self.returncode: int | None = None

    def _record_status(self, status: int) -> int:
        if os.WIFEXITED(status):
            self.returncode = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self.returncode = -os.WTERMSIG(status)
        else:
            raise RunnerError("clone3 worker produced a non-terminal wait status")
        if self.pidfd >= 0:
            try:
                os.close(self.pidfd)
            except OSError:
                pass
            self.pidfd = -1
        return self.returncode

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        try:
            observed_pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return self.returncode
        if observed_pid == 0:
            return None
        return self._record_status(status)

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.02)

    def send_signal(self, sig: int) -> None:
        if self.poll() is not None:
            return
        if self.pidfd >= 0 and hasattr(signal, "pidfd_send_signal"):
            signal.pidfd_send_signal(self.pidfd, sig)
        else:
            os.kill(self.pid, sig)

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)


class _LinuxCloneArgs(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("pidfd", ctypes.c_uint64),
        ("child_tid", ctypes.c_uint64),
        ("parent_tid", ctypes.c_uint64),
        ("exit_signal", ctypes.c_uint64),
        ("stack", ctypes.c_uint64),
        ("stack_size", ctypes.c_uint64),
        ("tls", ctypes.c_uint64),
        ("set_tid", ctypes.c_uint64),
        ("set_tid_size", ctypes.c_uint64),
        ("cgroup", ctypes.c_uint64),
    ]


def _clone3_process_into_cgroup(
    cgroup_fd: int,
    *,
    argv: list[str],
    environment: Mapping[str, str],
    stdin_fd: int,
    output_fd: int,
) -> _LinuxClone3Process:
    if sys.platform != "linux":
        raise RunnerError("clone3 cgroup creation is available only on Linux")
    pidfd = ctypes.c_int(-1)
    arguments = _LinuxCloneArgs(
        flags=_CLONE_PIDFD | _CLONE_INTO_CGROUP,
        pidfd=ctypes.addressof(pidfd),
        exit_signal=signal.SIGCHLD,
        cgroup=cgroup_fd,
    )
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    result = int(
        libc.syscall(
            ctypes.c_long(_SYS_CLONE3),
            ctypes.byref(arguments),
            ctypes.sizeof(arguments),
        )
    )
    if result == -1:
        error = ctypes.get_errno()
        raise RunnerError(
            f"Linux clone3(CLONE_INTO_CGROUP) failed closed: {os.strerror(error)}"
        )
    if result == 0:
        try:
            os.setsid()
            os.dup2(stdin_fd, 0)
            os.dup2(output_fd, 1)
            os.dup2(output_fd, 2)
            try:
                descriptors = [
                    int(name)
                    for name in os.listdir("/proc/self/fd")
                    if name.isdigit() and int(name) > 2
                ]
            except OSError:
                descriptors = list(range(3, 4096))
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            os.execve(argv[0], argv, dict(environment))
        except BaseException as exc:
            try:
                os.write(2, f"OpenBuild creation-bound exec failed: {exc}\n".encode("utf-8", "replace"))
            except BaseException:
                pass
            os._exit(127)
    if result <= 0 or pidfd.value < 0:
        if result > 0:
            try:
                os.kill(result, signal.SIGKILL)
                os.waitpid(result, 0)
            except OSError:
                pass
        raise RunnerError("clone3 did not return a creation-bound PID and pidfd")
    return _LinuxClone3Process(result, pidfd.value, argv)


def spawn_linux_worker_creation_bound(
    cgroup: Path,
    run_dir: Path,
    runner_log: Any,
    *,
    provider: str,
) -> _LinuxClone3Process:
    """Create the worker inside its cgroup before any worker exec code can run."""
    if provider != "linux-cgroup-v2":
        raise RunnerError("Linux creation-bound spawn requires the cgroup v2 provider")
    environment = dict(os.environ)
    environment["OPENBUILD_CONTAINED_BY_GUARDIAN"] = "1"
    environment["OPENBUILD_CONTAINMENT_PROVIDER"] = provider
    argv = [sys.executable, str(Path(__file__).resolve()), "_worker", "--run-dir", str(run_dir)]
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    cgroup_fd = os.open(cgroup, directory_flags)
    stdin_fd = os.open(os.devnull, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        return _clone3_process_into_cgroup(
            cgroup_fd,
            argv=argv,
            environment=environment,
            stdin_fd=stdin_fd,
            output_fd=runner_log.fileno(),
        )
    finally:
        os.close(stdin_fd)
        os.close(cgroup_fd)


def _guardian_provider_populated(provider: str, handle: Any) -> bool:
    if provider == "windows-job":
        return query_windows_job_active_processes(handle) != 0
    if provider == "linux-cgroup-v2":
        return query_linux_cgroup_populated(handle)
    raise RunnerError("unknown containment provider")


def _guardian_provider_close(provider: str, handle: Any) -> None:
    if provider == "windows-job":
        close_windows_job(handle)
        return
    if provider == "linux-cgroup-v2":
        close_linux_cgroup(handle)
        return
    raise RunnerError("unknown containment provider")


def guardian_run(run_dir: Path) -> int:
    """Own native containment outside the worker until root archives the handoff."""
    secret = _guardian_secret(run_dir)
    guardian_request = read_guardian_message(
        run_dir / "guardian-request.json",
        secret,
        "guardian-request",
    )
    guardian_id = guardian_request.get("guardian_id")
    if not isinstance(guardian_id, str) or not guardian_id:
        raise RunnerError("guardian request lacks a private guardian identity")
    private_request = read_json(run_dir / "request.json")
    agent_name = guardian_request.get("agent_name")
    repo_value = guardian_request.get("repo")
    lease_id = guardian_request.get("lease_id")
    allowed_set_digest = guardian_request.get("allowed_set_digest")
    provider_plan_id = guardian_request.get("provider_plan_id")
    ipc_plan_id = guardian_request.get("ipc_plan_id")
    private_plan = private_request.get("containment_plan")
    if (
        not isinstance(agent_name, str)
        or not isinstance(repo_value, str)
        or not isinstance(lease_id, str)
        or not isinstance(allowed_set_digest, str)
        or not isinstance(provider_plan_id, str)
        or not provider_plan_id
        or not isinstance(ipc_plan_id, str)
        or not ipc_plan_id
        or not isinstance(private_plan, dict)
        or private_request.get("profile", {}).get("name") != agent_name
        or private_request.get("repo") != repo_value
        or private_request.get("lease_id") != lease_id
        or private_request.get("lifecycle_allowed_set_digest") != allowed_set_digest
        or private_plan.get("provider_plan_id") != provider_plan_id
        or private_plan.get("ipc_plan_id") != ipc_plan_id
    ):
        raise RunnerError("guardian request changed the private registry boundary binding")
    registry = recovery_registry_for_request(private_request)
    if registry is None:
        raise RunnerError("containment guardian cannot resolve the implementation registry")
    worker: Any | None = None
    provider: str | None = None
    provider_handle: Any | None = None
    boundary_committed = False
    worker_resumed = False
    try:
        if os.name == "nt":
            provider = "windows-job"
            provider_handle = create_windows_kill_job(bind_current=False)
        elif sys.platform == "linux":
            provider = "linux-cgroup-v2"
            provider_handle = create_linux_cgroup(guardian_id)
        else:
            raise RunnerError("no creation-bound containment provider is available on this platform")

        with open_private_binary(run_dir / "runner.log", append=True) as runner_log:
            if provider == "linux-cgroup-v2":
                worker = spawn_linux_worker_creation_bound(
                    provider_handle,
                    run_dir,
                    runner_log,
                    provider=provider,
                )
                worker_resumed = True
            else:
                worker = _spawn_worker_process(
                    run_dir,
                    runner_log,
                    contained=True,
                    provider=provider,
                    start_suspended=True,
                )
        worker_identity = process_identity_from_popen(worker)
        if worker_identity is None:
            raise RunnerError("guardian cannot record worker creation identity")
        setattr(worker, "_openbuild_process_identity", worker_identity)
        if provider == "windows-job":
            assign_windows_process_to_job(provider_handle, worker)
            verify_windows_process_in_job(provider_handle, worker)
            resume_windows_suspended_process(worker)
            worker_resumed = True
        else:
            if worker.pid not in query_linux_cgroup_members(provider_handle):
                raise RunnerError("Linux worker was not born inside the creation-bound cgroup")
        if not _guardian_provider_populated(provider, provider_handle):
            raise RunnerError("containment provider is empty immediately after worker attachment")
        worker_record = {
            "pid": worker.pid,
            "identity": worker_identity,
            "process_group_id": worker.pid,
            "started_at": utc_now(),
        }
        atomic_write_json(run_dir / "worker.json", worker_record)
        guardian_identity = process_identity(os.getpid())
        if guardian_identity is None:
            raise RunnerError("guardian creation identity is unavailable")
        anti_migration: dict[str, Any] | None = None
        if provider == "linux-cgroup-v2":
            guardian_cgroup_namespace = os.readlink("/proc/self/ns/cgroup")
            guardian_mount_namespace = os.readlink("/proc/self/ns/mnt")
            write_guardian_message(
                run_dir / "linux-anti-migration-request.json",
                secret,
                "linux-anti-migration-request",
                {
                    "guardian_id": guardian_id,
                    "worker_pid": worker.pid,
                    "worker_identity": worker_identity,
                    "cgroup_path": str(provider_handle),
                },
            )
            anti_path = run_dir / "linux-anti-migration-ready.json"
            anti_deadline = time.monotonic() + 20.0
            while not anti_path.is_file():
                if worker.poll() is not None:
                    raise RunnerError("Linux worker exited before anti-migration proof")
                if time.monotonic() >= anti_deadline:
                    raise RunnerError("Linux worker did not publish anti-migration proof")
                if not _guardian_provider_populated(provider, provider_handle):
                    raise RunnerError("Linux cgroup lost the worker before anti-migration proof")
                time.sleep(0.05)
            anti_migration = read_guardian_message(
                anti_path,
                secret,
                "linux-anti-migration-ready",
            )
            validate_linux_anti_migration_receipt(
                anti_migration,
                guardian_id=guardian_id,
                worker_pid=worker.pid,
                worker_identity=worker_identity,
                guardian_cgroup_namespace=guardian_cgroup_namespace,
                guardian_mount_namespace=guardian_mount_namespace,
            )
            if worker.pid not in query_linux_cgroup_members(provider_handle):
                raise RunnerError("Linux worker escaped before the durable process boundary")
        ready_payload = {
            "guardian_id": guardian_id,
            "guardian_pid": os.getpid(),
            "guardian_identity": guardian_identity,
            "provider": provider,
            "provider_plan_id": provider_plan_id,
            "ipc_plan_id": ipc_plan_id,
            "policy": "kill-on-close-no-breakaway" if provider == "windows-job" else "cgroup-v2-populated",
            "active_processes": 1,
            "worker": worker_record,
            "anti_migration": anti_migration,
        }
        write_guardian_message(
            run_dir / "guardian-ready.json",
            secret,
            "guardian-ready",
            ready_payload,
        )

        precommit_request_path = run_dir / "guardian-precommit-request.json"
        precommit_nonce: str | None = None
        boundary_path = run_dir / "containment-bound.json"
        boundary_deadline = time.monotonic() + float(guardian_request.get("boundary_timeout") or 600.0)
        while not boundary_path.is_file():
            if worker.poll() is not None:
                raise RunnerError("contained worker exited before the durable process boundary")
            if time.monotonic() >= boundary_deadline:
                raise RunnerError("durable process boundary was not committed before guardian timeout")
            if not _guardian_provider_populated(provider, provider_handle):
                raise RunnerError("containment provider lost the worker before the durable boundary")
            if precommit_request_path.is_file() and precommit_nonce is None:
                precommit = read_guardian_message(
                    precommit_request_path,
                    secret,
                    "guardian-precommit-request",
                )
                if (
                    precommit.get("guardian_id") != guardian_id
                    or int(precommit.get("worker_pid") or 0) != worker.pid
                    or precommit.get("worker_identity") != worker_identity
                    or precommit.get("provider_plan_id") != provider_plan_id
                    or precommit.get("ipc_plan_id") != ipc_plan_id
                    or not isinstance(precommit.get("precommit_nonce"), str)
                    or not precommit["precommit_nonce"]
                ):
                    raise RunnerError("guardian precommit request changed the creation-bound worker")
                if (
                    provider == "linux-cgroup-v2"
                    and worker.pid not in query_linux_cgroup_members(provider_handle)
                ):
                    raise RunnerError("Linux worker escaped before the precommit attestation")
                precommit_nonce = precommit["precommit_nonce"]
                if not _guardian_provider_populated(provider, provider_handle):
                    raise RunnerError("containment provider failed during precommit arbitration")
                precommit_payload = {
                    "guardian_id": guardian_id,
                    "guardian_pid": os.getpid(),
                    "guardian_identity": guardian_identity,
                    "worker_pid": worker.pid,
                    "worker_identity": worker_identity,
                    "provider": provider,
                    "provider_plan_id": provider_plan_id,
                    "ipc_plan_id": ipc_plan_id,
                    "provider_populated": True,
                    "membership_verified": True,
                    "precommit_nonce": precommit_nonce,
                    "attested_at": utc_now(),
                }
                bound_state = registry.bind_process_unactivated(
                    lease_id,
                    allowed_set_digest=allowed_set_digest,
                    provider_receipt={
                        **{key: value for key, value in ready_payload.items() if key != "worker"},
                        "precommit": precommit_payload,
                    },
                    process_receipt=worker_record,
                )
                boundary_committed = True
                write_guardian_message(
                    run_dir / "guardian-precommit-ready.json",
                    secret,
                    "guardian-precommit-ready",
                    {
                        **precommit_payload,
                        "registry_digest": bound_state["digest"],
                    },
                )
            time.sleep(0.05)
        boundary = read_guardian_message(boundary_path, secret, "containment-bound")
        if (
            precommit_nonce is None
            or boundary.get("precommit_nonce") != precommit_nonce
            or int(boundary.get("worker_pid") or 0) != worker.pid
            or boundary.get("worker_identity") != worker_identity
            or boundary.get("guardian_id") != guardian_id
            or boundary.get("provider_plan_id") != provider_plan_id
            or boundary.get("ipc_plan_id") != ipc_plan_id
        ):
            raise RunnerError("durable process boundary changed precommit, guardian or worker binding")
        boundary_committed = True

        cancel_path = run_dir / "guardian-cancel.json"
        cancellation_applied = False
        while _guardian_provider_populated(provider, provider_handle):
            if (
                provider == "linux-cgroup-v2"
                and worker.poll() is None
                and worker.pid not in query_linux_cgroup_members(provider_handle)
            ):
                raise RunnerError("Linux worker escaped its cgroup after the durable boundary")
            if not cancellation_applied:
                safe_stop = consume_project_lane_safe_stop(private_request)
                if safe_stop is not None:
                    write_guardian_message(
                        run_dir / "guardian-safe-stop.json",
                        secret,
                        "guardian-safe-stop",
                        {
                            "guardian_id": guardian_id,
                            "intent_id": safe_stop["intent_id"],
                            "intent_generation": safe_stop["intent_generation"],
                            "writer": safe_stop["writer"],
                            "consumed_at": utc_now(),
                        },
                    )
                    terminate_guardian_provider(provider, provider_handle)
                    cancellation_applied = True
                elif cancel_path.is_file():
                    cancellation = read_guardian_message(
                        cancel_path,
                        secret,
                        "guardian-cancel",
                    )
                    if cancellation.get("guardian_id") != guardian_id:
                        raise RunnerError("guardian cancellation changed the private guardian identity")
                    terminate_guardian_provider(provider, provider_handle)
                    cancellation_applied = True
            time.sleep(0.1)
        if provider == "linux-cgroup-v2" and worker.poll() is None:
            raise RunnerError("Linux cgroup became empty while the creation-bound worker remained alive")
        zero_payload = {
            "guardian_id": guardian_id,
            "provider": provider,
            "populated": False,
            "identity_verified": True,
            "worker_pid": worker.pid,
            "worker_identity": worker_identity,
            "proved_at": utc_now(),
        }
        write_guardian_message(run_dir / "guardian-zero.json", secret, "guardian-zero", zero_payload)

        close_path = run_dir / "guardian-close.json"
        while not close_path.is_file():
            time.sleep(0.1)
        close_request = read_guardian_message(close_path, secret, "guardian-close")
        if close_request.get("guardian_id") != guardian_id:
            raise RunnerError("guardian close changed the private guardian identity")
        _guardian_provider_close(provider, provider_handle)
        provider_handle = None
        write_guardian_message(
            run_dir / "guardian-closed.json",
            secret,
            "guardian-closed",
            {"guardian_id": guardian_id, "closed": True, "closed_at": utc_now()},
        )
        return 0
    except BaseException as exc:
        cleanup_error: str | None = None
        tree_empty = worker is None
        if worker is not None and not worker_resumed and worker.poll() is None:
            try:
                worker.kill()
                worker.wait(timeout=5.0)
            except BaseException as suspended_cleanup_exc:
                cleanup_error = str(suspended_cleanup_exc) or type(suspended_cleanup_exc).__name__
        if provider is not None and provider_handle is not None:
            try:
                if _guardian_provider_populated(provider, provider_handle):
                    terminate_guardian_provider(provider, provider_handle)
                    cleanup_deadline = time.monotonic() + 5.0
                    while (
                        _guardian_provider_populated(provider, provider_handle)
                        and time.monotonic() < cleanup_deadline
                    ):
                        time.sleep(0.05)
                    if _guardian_provider_populated(provider, provider_handle):
                        raise RunnerError("containment provider remained populated during teardown")
                _guardian_provider_close(provider, provider_handle)
                provider_handle = None
                if worker is not None:
                    try:
                        worker.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        pass
                tree_empty = worker is None or worker.poll() is not None
            except BaseException as cleanup_exc:
                cleanup_error = str(cleanup_exc) or type(cleanup_exc).__name__
        try:
            write_guardian_message(
                run_dir / "guardian-failure.json",
                secret,
                "guardian-failure",
                {
                    "guardian_id": guardian_id,
                    "boundary_committed": boundary_committed,
                    "tree_empty": tree_empty,
                    "no_user_code": not boundary_committed,
                    "failure": str(exc) or type(exc).__name__,
                    "cleanup_error": cleanup_error,
                },
            )
        except BaseException:
            pass
        if not isinstance(exc, Exception):
            raise
        return 1


def await_guardian_launch(
    run_dir: Path,
    secret: bytes,
    guardian: Any,
    *,
    timeout: float = 20.0,
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while True:
        failure_path = run_dir / "guardian-failure.json"
        if failure_path.is_file():
            return "failed", read_guardian_message(
                failure_path, secret, "guardian-failure"
            )
        if (run_dir / "guardian-ready.json").is_file():
            ready = read_guardian_message(
                run_dir / "guardian-ready.json", secret, "guardian-ready"
            )
            if failure_path.is_file():
                return "failed", read_guardian_message(
                    failure_path, secret, "guardian-failure"
                )
            if guardian.poll() is not None:
                if failure_path.is_file():
                    return "failed", read_guardian_message(
                        failure_path, secret, "guardian-failure"
                    )
                raise RunnerError("containment guardian stopped after publishing launch readiness")
            return "ready", ready
        if guardian.poll() is not None:
            raise RunnerError("containment guardian exited without an authenticated launch receipt")
        if time.monotonic() >= deadline:
            raise RunnerError("containment guardian did not publish a launch receipt within 20 seconds")
        time.sleep(0.05)


def await_guardian_precommit(
    run_dir: Path,
    secret: bytes,
    guardian: Any,
    ready: Mapping[str, Any],
    *,
    timeout: float = 20.0,
) -> tuple[str, dict[str, Any]]:
    worker = ready.get("worker")
    if not isinstance(worker, dict):
        raise RunnerError("guardian launch receipt lacks the worker creation receipt")
    precommit_nonce = secrets.token_hex(32)
    write_guardian_message(
        run_dir / "guardian-precommit-request.json",
        secret,
        "guardian-precommit-request",
        {
            "guardian_id": ready.get("guardian_id"),
            "worker_pid": worker.get("pid"),
            "worker_identity": worker.get("identity"),
            "provider_plan_id": ready.get("provider_plan_id"),
            "ipc_plan_id": ready.get("ipc_plan_id"),
            "precommit_nonce": precommit_nonce,
        },
    )
    failure_path = run_dir / "guardian-failure.json"
    response_path = run_dir / "guardian-precommit-ready.json"
    deadline = time.monotonic() + timeout
    while True:
        if failure_path.is_file():
            return "failed", read_guardian_message(
                failure_path, secret, "guardian-failure"
            )
        if response_path.is_file():
            response = read_guardian_message(
                response_path,
                secret,
                "guardian-precommit-ready",
            )
            if failure_path.is_file():
                return "failed", read_guardian_message(
                    failure_path, secret, "guardian-failure"
                )
            if guardian.poll() is not None:
                if failure_path.is_file():
                    return "failed", read_guardian_message(
                        failure_path, secret, "guardian-failure"
                    )
                raise RunnerError("containment guardian stopped after precommit attestation")
            if (
                response.get("guardian_id") != ready.get("guardian_id")
                or response.get("guardian_pid") != ready.get("guardian_pid")
                or response.get("guardian_identity") != ready.get("guardian_identity")
                or int(response.get("worker_pid") or 0) != int(worker.get("pid") or 0)
                or response.get("worker_identity") != worker.get("identity")
                or response.get("provider") != ready.get("provider")
                or response.get("provider_plan_id") != ready.get("provider_plan_id")
                or response.get("ipc_plan_id") != ready.get("ipc_plan_id")
                or response.get("provider_populated") is not True
                or response.get("membership_verified") is not True
                or response.get("precommit_nonce") != precommit_nonce
                or not re.fullmatch(r"[0-9a-f]{64}", str(response.get("registry_digest") or ""))
            ):
                raise RunnerError("guardian precommit attestation changed the launch binding")
            return "ready", response
        if guardian.poll() is not None:
            if failure_path.is_file():
                return "failed", read_guardian_message(
                    failure_path, secret, "guardian-failure"
                )
            raise RunnerError("containment guardian exited before precommit attestation")
        if time.monotonic() >= deadline:
            raise RunnerError("containment guardian did not publish a precommit attestation")
        time.sleep(0.05)


def await_guardian_record(
    run_dir: Path,
    secret: bytes,
    filename: str,
    kind: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    path = run_dir / filename
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if (run_dir / "guardian-failure.json").is_file():
            failure = read_guardian_message(
                run_dir / "guardian-failure.json", secret, "guardian-failure"
            )
            raise RunnerError(
                f"containment guardian failed during terminalization: {failure.get('failure')}"
            )
        if time.monotonic() >= deadline:
            raise RunnerError(f"containment guardian did not publish {filename} within 20 seconds")
        time.sleep(0.05)
    return read_guardian_message(path, secret, kind)


def spawn_containment_guardian(run_dir: Path, runner_log: Any) -> Any:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_guardian", "--run-dir", str(run_dir)],
        stdin=subprocess.DEVNULL,
        stdout=runner_log,
        stderr=runner_log,
        close_fds=True,
        **_background_options(),
    )


def _expected_lease_run_id(lease: Mapping[str, Any]) -> str:
    if lease.get("lease_kind") == "recovery-target":
        plan = lease.get("plan")
        run_id = plan.get("run_id") if isinstance(plan, Mapping) else None
    else:
        run_id = lease.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RecoveryStateError("recovery-capable lease has no exact run ID binding")
    return run_id


def _terminal_binding(receipt: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    fields = (
        "status",
        "agent_name",
        "task_name",
        "lease_id",
        "activated",
        "configured_model",
        "model_reasoning_effort",
        "sandbox",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
        "terminal_event",
        "codex_exit_evidence",
        "codex_exit_code",
        "result_evidence",
        "process_tree_stopped",
    )
    return {"run_id": run_id, **{field: receipt.get(field) for field in fields}}


def _require_private_run_path_identity(run_dir: Path, run_id: str) -> Path:
    """Bind a terminal run to the immutable private paths recorded at creation."""
    try:
        resolved = run_dir.resolve(strict=True)
        request = read_json(resolved / "request.json")
        prompt_value = request.get("prompt_file")
        command = request.get("command")
        if (
            run_dir.name != run_id
            or not isinstance(prompt_value, str)
            or not isinstance(command, list)
            or command.count("-o") != 1
        ):
            raise RunnerError("terminal receipt private run path identity drifted")
        prompt = Path(prompt_value).expanduser().resolve(strict=True)
        expected_prompt = resolved / "prompt.md"
        result_index = command.index("-o") + 1
        if result_index >= len(command) or not isinstance(command[result_index], str):
            raise RunnerError("terminal receipt private run path identity drifted")
        result = Path(command[result_index]).expanduser().resolve(strict=False)
        if (
            prompt.name != "prompt.md"
            or not expected_prompt.is_file()
            or not prompt.samefile(expected_prompt)
            or not prompt.parent.samefile(resolved)
            or result.name != "result.md"
            or not result.parent.samefile(resolved)
        ):
            raise RunnerError("terminal receipt private run path identity drifted")
    except (KeyError, OSError, ValueError) as exc:
        raise RunnerError("terminal receipt private run path identity drifted") from exc
    return resolved


def _terminal_binding_candidate(
    receipt: Mapping[str, Any],
    *,
    run_dir: Path,
    run_id: str,
    format: str,
) -> dict[str, Any]:
    """Reconstruct one immutable terminal digest candidate without publishing paths."""
    resolved = _require_private_run_path_identity(run_dir, run_id)
    fields = (
        "status",
        "agent_name",
        "task_name",
        "lease_id",
        "activated",
        "configured_model",
        "model_reasoning_effort",
        "sandbox",
        "worker_pid",
        "worker_process_identity",
        "codex_pid",
        "codex_process_identity",
        "terminal_event",
        "codex_exit_evidence",
        "codex_exit_code",
        "result_evidence",
        "process_tree_stopped",
    )
    if format == "run-id-v2":
        payload = _terminal_binding(receipt, run_id=run_id)
    elif format == "run-dir-v1":
        # This is the exact v2.2.0/v2.2.1 projection: the path field was
        # first and was serialized with str(run_dir.resolve()).  The tag is
        # deliberately outside the historical payload and therefore hash.
        payload = {"run_dir": str(resolved), **{field: receipt.get(field) for field in fields}}
    else:
        raise RunnerError("terminal receipt binding format is unsupported")
    return {"format": format, "payload": payload}


def _terminal_binding_candidates(
    receipt: Mapping[str, Any], *, run_dir: Path, run_id: str
) -> tuple[dict[str, Any], ...]:
    """Return the only two released private projections in stable order."""
    return (
        _terminal_binding_candidate(receipt, run_dir=run_dir, run_id=run_id, format="run-id-v2"),
        _terminal_binding_candidate(receipt, run_dir=run_dir, run_id=run_id, format="run-dir-v1"),
    )


def _match_terminal_binding(
    receipt: Mapping[str, Any], *, run_dir: Path, run_id: str, stored_digest: str
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", stored_digest):
        raise RunnerError("terminal receipt binding digest is malformed")
    matches = [
        candidate
        for candidate in _terminal_binding_candidates(receipt, run_dir=run_dir, run_id=run_id)
        if sha256_bytes(_canonical_json_bytes(candidate["payload"])) == stored_digest
    ]
    if len(matches) != 1:
        raise RunnerError("terminal receipt binding drifted during reload")
    return matches[0]


def _privacy_safe_classifications(values: tuple[str, ...], label: str) -> list[str]:
    normalized = sorted(set(values))
    if not normalized or any(
        not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value)
        for value in normalized
    ):
        raise RunnerError(f"{label} requires privacy-safe classification tokens")
    return normalized


def classify_recovery_outcome(
    *,
    decision_class: str | None = None,
    missing_safety_evidence: tuple[str, ...] = (),
    exhausted_capabilities: tuple[str, ...] = (),
    terminal_abandonment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one closed, privacy-safe recovery report without writer authority."""
    signals = sum(
        (
            decision_class is not None,
            bool(missing_safety_evidence),
            bool(exhausted_capabilities),
            terminal_abandonment is not None,
        )
    )
    if signals != 1:
        raise RunnerError("recovery outcome requires exactly one closed evidence class")
    if decision_class is not None:
        allowed = {
            "product",
            "architecture",
            "scope",
            "permissions",
            "privacy",
            "security",
            "destructive",
            "external-action",
            "publication",
        }
        if decision_class not in allowed:
            raise RunnerError("decision-required class is outside the closed material set")
        return {
            "outcome": "decision-required",
            "decision_class": decision_class,
            "required_action": "provide-decision",
            "writer_action": "none",
        }
    if missing_safety_evidence:
        return {
            "outcome": "blocked",
            "missing_evidence": _privacy_safe_classifications(
                missing_safety_evidence, "blocked outcome"
            ),
            "required_action": "restore-safety-evidence",
            "writer_action": "none",
        }
    if exhausted_capabilities:
        return {
            "outcome": "automation-exhausted",
            "exhausted_capabilities": _privacy_safe_classifications(
                exhausted_capabilities, "automation-exhausted outcome"
            ),
            "required_action": "none-under-current-authority",
            "writer_action": "none",
        }
    assert terminal_abandonment is not None
    schema = terminal_abandonment.get("schema")
    cause = terminal_abandonment.get("cause")
    if (
        terminal_abandonment.get("outcome") != "terminal-abandoned"
        or (schema, cause)
        not in {
            ("terminal-abandonment-v1", "outside-set-drift"),
            (
                "terminal-abandonment-v2",
                "outside-set-drift-with-preexisting-dirty-overlap",
            ),
            (
                "terminal-abandonment-v3",
                "legacy-normal-outside-set-drift-with-preexisting-dirty-overlap",
            ),
            (
                "terminal-abandonment-v4",
                "legacy-normal-control-plane-and-outside-set-drift-with-"
                "preexisting-dirty-overlap",
            ),
            (
                "terminal-abandonment-v5",
                "legacy-normal-preexisting-dirty-overlap",
            ),
        }
        or terminal_abandonment.get("checkpoint_invalidation") != "completed"
    ):
        raise RunnerError("terminal-abandoned report requires completed exact evidence")
    return {
        "outcome": "terminal-abandoned",
        "schema": schema,
        "cause": cause,
        "required_action": "none",
        "writer_action": "none",
    }


def root_completion_authorization_record(
    *,
    specification_revision: str,
    milestone: str,
    allowed_set_digest: str,
    diff_attribution_digest: str,
) -> dict[str, Any]:
    """Build the privacy-safe audit record required before root-only completion."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", specification_revision):
        raise RunnerError("root completion specification revision is invalid")
    if (
        not isinstance(milestone, str)
        or not milestone.strip()
        or len(milestone) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in milestone)
    ):
        raise RunnerError("root completion milestone is invalid")
    for value, label in (
        (allowed_set_digest, "allowed-set digest"),
        (diff_attribution_digest, "diff-attribution digest"),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise RunnerError(f"root completion {label} must be lowercase SHA-256")
    return {
        "event": "root-completion-authorized",
        "authority": "original-build-request",
        "specification_revision": specification_revision,
        "milestone": milestone,
        "allowed_set_digest": allowed_set_digest,
        "diff_attribution_digest": diff_attribution_digest,
        "automatic": True,
        "writer_action": "none",
    }


def root_completion_source_binding(
    *,
    specification_revision: str,
    milestone: str,
    allowed_set_digest: str,
    lease_kind: str,
    run_id: str,
) -> dict[str, Any]:
    """Bind root-completion inputs before an implementation process can edit."""
    if lease_kind not in {"normal-legacy", "normal-contained", "recovery-target"}:
        raise RunnerError("root completion source lease kind is invalid")
    if not isinstance(specification_revision, str) or not specification_revision.strip():
        raise RunnerError("root completion source specification revision is invalid")
    if not isinstance(milestone, str) or not milestone.strip():
        raise RunnerError("root completion source milestone is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", allowed_set_digest):
        raise RunnerError("root completion source allowed-set digest must be lowercase SHA-256")
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
        raise RunnerError("root completion source run ID is invalid")
    return {
        "schema": ROOT_COMPLETION_SOURCE_SCHEMA,
        "lease_kind": lease_kind,
        "specification_revision": specification_revision,
        "milestone": milestone,
        "allowed_set_digest": allowed_set_digest,
        "run_id": run_id,
    }


def audit_guardian_health(run_dir: Path) -> None:
    ready_path = run_dir / "guardian-ready.json"
    failure_path = run_dir / "guardian-failure.json"
    if not ready_path.is_file() and not failure_path.is_file():
        return
    request = read_json(run_dir / "request.json")
    registry = recovery_registry_for_request(request)
    lease_id = request.get("lease_id")
    reconciliation_path = run_dir / "containment-loss-reconciliation.json"
    if reconciliation_path.is_file():
        if registry is None or not isinstance(lease_id, str):
            raise RunnerError(
                "completed containment-loss reconciliation cannot resolve its registry lease"
            )
        result = read_json(reconciliation_path)
        expected = _containment_loss_reconciliation_result(lease_id)
        state = registry.state()
        if result != expected or not _containment_loss_release_is_complete(
            state,
            lease_id=lease_id,
            run_id=run_dir.name,
        ):
            raise RunnerError(
                "completed containment-loss reconciliation evidence drifted"
            )
        return
    try:
        secret = _guardian_secret(run_dir)
        ready = (
            read_guardian_message(ready_path, secret, "guardian-ready")
            if ready_path.is_file()
            else None
        )
        failure = (
            read_guardian_message(failure_path, secret, "guardian-failure")
            if failure_path.is_file()
            else None
        )
        closed = (
            read_guardian_message(
                run_dir / "guardian-closed.json",
                secret,
                "guardian-closed",
            )
            if (run_dir / "guardian-closed.json").is_file()
            else None
        )
    except RunnerError as exc:
        ready = None
        failure = None
        loss_cause = f"guardian-ipc-loss: {exc}"
    else:
        loss_cause = None
        if isinstance(failure, dict) and failure.get("boundary_committed") is True:
            loss_cause = str(failure.get("failure") or "guardian-loss-after-boundary")
        elif isinstance(closed, dict) and (
            closed.get("closed") is not True
            or not isinstance(ready, dict)
            or closed.get("guardian_id") != ready.get("guardian_id")
        ):
            loss_cause = "guardian-close-authentication-loss"
        elif isinstance(ready, dict) and not isinstance(closed, dict):
            guardian_record = {
                "pid": ready.get("guardian_pid"),
                "identity": ready.get("guardian_identity"),
            }
            guardian_state = process_record_state(guardian_record)
            if guardian_state != "running":
                loss_cause = f"guardian-process-{guardian_state}"
    if loss_cause is None:
        return
    if registry is None or not isinstance(lease_id, str):
        raise RunnerError(f"contained guardian failed after its durable boundary: {loss_cause}")
    state = registry.state()
    if state.get("quarantine") != "containment-loss-after-boundary":
        try:
            registry.quarantine_containment_loss(
                lease_id,
                loss_cause,
            )
        except RecoveryStateError as exc:
            raise RunnerError(f"guardian loss could not be quarantined: {exc}") from exc
    if request.get("project_lane") is not None:
        try:
            quarantine_project_lane_writer(request, "crashed")
        except RunnerError as exc:
            raise RunnerError(
                "contained guardian loss was quarantined lane-locally, but "
                f"project lane quarantine failed closed: {exc}"
            ) from exc
    raise RunnerError(
        "contained guardian failed after the durable process boundary; "
        "the writer lease is quarantined for manual reconciliation"
    )


def _project_lane_recovery_checkpoint_digest(
    run_dir: Path,
    receipt: Mapping[str, Any],
) -> str | None:
    semantic_path = run_dir / "semantic-rejection.json"
    recoverable_outcome = receipt.get("status") == "failed"
    if semantic_path.is_file():
        semantic = read_json(semantic_path)
        recoverable_outcome = semantic.get("disposition") == "blocked"
    if not recoverable_outcome:
        return None
    checkpoint_path = run_dir / "recovery-checkpoint.json"
    if not checkpoint_path.is_file():
        return None
    checkpoint = read_json(checkpoint_path)
    digest = checkpoint.get("checkpoint_digest")
    if (
        checkpoint.get("disposition") != "recovery-eligible"
        or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
    ):
        return None
    return str(digest)


def reconcile_implementation_registry(
    run_dir: Path,
    receipt: Mapping[str, Any],
    *,
    success_verification_digest: str | None = None,
    terminal_abandonment: bool = False,
) -> None:
    """Drive a terminal implementation receipt through one durable owner lifecycle."""
    if receipt.get("status") not in {"completed", "failed"} or receipt.get("process_tree_stopped") is not True:
        return
    request = read_json(run_dir / "request.json")
    agent_name = request["profile"]["name"]
    registry = recovery_registry_for_request(request)
    lease_id = request.get("lease_id")
    if registry is None or not isinstance(lease_id, str):
        return
    safe_stop_receipt_path = run_dir / "safe-stop-rebind.json"
    safe_stop_reconciled = safe_stop_receipt_path.is_file()
    safe_stop_intent: dict[str, Any] | None = None
    safe_stop_completion: dict[str, Any] | None = None
    if request.get("project_lane") is not None and not safe_stop_reconciled:
        binding = project_lane_safe_stop_binding(
            request,
            require_active_registry=False,
        )
        if binding is not None:
            _, safe_stop_intent = binding
            if safe_stop_intent.get("status") == "completed":
                safe_stop_completion = safe_stop_intent
                safe_stop_intent = None
            elif safe_stop_intent.get("status") != "stopping":
                safe_stop_intent = None
    project_lane_close_required = (
        receipt.get("status") == "failed"
        or terminal_abandonment
        or (run_dir / "semantic-rejection.json").is_file()
        or (run_dir / "terminal-abandonment.json").is_file()
    ) and not safe_stop_reconciled and safe_stop_intent is None
    project_lane_quarantined = False
    state = registry.state()
    lease = state.get("lease")
    if safe_stop_completion is not None:
        if (
            lease is not None
            or state.get("outbox") is not None
            or state.get("quarantine") is not None
        ):
            raise RunnerError(
                "completed project lane safe-stop registry is not vacant"
            )
        release_project_lane_runtime(request)
        materialize_project_lane_safe_stop_receipt(
            safe_stop_receipt_path,
            safe_stop_completion,
        )
        garbage_collect_owner_prompt_snapshots(registry)
        return
    if lease is None:
        if safe_stop_reconciled:
            garbage_collect_owner_prompt_snapshots(registry)
            return
        if safe_stop_intent is not None:
            checkpoint_path = run_dir / "recovery-checkpoint.json"
            checkpoint_value = (
                read_json(checkpoint_path)
                if checkpoint_path.is_file()
                else None
            )
            checkpoint_digest, preserved_changes = safe_stop_checkpoint_binding(
                registry,
                checkpoint_value,
            )
            completed = complete_project_lane_safe_stop(
                request,
                str(safe_stop_intent["intent_id"]),
                recovery_checkpoint_digest=checkpoint_digest,
                preserved_changes=preserved_changes,
            )
            materialize_project_lane_safe_stop_receipt(
                safe_stop_receipt_path,
                completed["safe_stop"],
            )
        elif project_lane_close_required and request.get("project_lane") is not None:
            recovery_checkpoint_digest = _project_lane_recovery_checkpoint_digest(
                run_dir,
                receipt,
            )
            if recovery_checkpoint_digest is not None:
                prepare_project_lane_recovery(
                    request,
                    recovery_checkpoint_digest,
                )
            else:
                finalize_project_lane_terminal(
                    request,
                    "crashed" if receipt.get("status") == "failed" else "cancelled",
                )
        elif (
            receipt.get("status") == "completed"
            and request.get("project_lane") is not None
        ):
            complete_project_lane_writer(request)
        garbage_collect_owner_prompt_snapshots(registry)
        return
    if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
        raise RunnerError("terminal receipt does not own the current workspace lease")
    if lease.get("recovery_capable") is not True:
        try:
            registry.release_legacy_terminal(
                lease_id,
                {
                    "success": receipt.get("status") == "completed",
                    "process_tree_stopped": True,
                },
            )
            garbage_collect_owner_prompt_snapshots(registry)
        except RecoveryStateError as exc:
            raise RunnerError(f"legacy implementation lease could not be released: {exc}") from exc
        return
    expected_run_id = _expected_lease_run_id(lease)
    if run_dir.name != expected_run_id:
        raise RunnerError("terminal receipt run ID does not own the current workspace lease")
    if receipt.get("lease_id") != lease_id:
        raise RunnerError("terminal receipt lease does not own the current workspace lease")
    _require_private_run_path_identity(run_dir, expected_run_id)
    if project_lane_close_required and request.get("project_lane") is not None:
        quarantine_project_lane_writer(
            request,
            "crashed" if receipt.get("status") == "failed" else "cancelled",
        )
        project_lane_quarantined = True

    try:
        secret = _guardian_secret(run_dir)
        if (run_dir / "guardian-failure.json").is_file():
            failure = read_guardian_message(
                run_dir / "guardian-failure.json",
                secret,
                "guardian-failure",
            )
            if failure.get("boundary_committed") is True:
                registry.quarantine_containment_loss(
                    lease_id,
                    str(failure.get("failure") or "guardian-loss-after-boundary"),
                )
                raise RecoveryStateError("guardian loss after the durable boundary is quarantined")
        zero = await_guardian_record(
            run_dir,
            secret,
            "guardian-zero.json",
            "guardian-zero",
        )
        allowed_set_digest = request.get("lifecycle_allowed_set_digest") or (
            request.get("recovery_preflight") or {}
        ).get("allowed_set_digest", "")
        binding = _terminal_binding(receipt, run_id=expected_run_id)
        binding_digest = sha256_bytes(_canonical_json_bytes(binding))
        state_name = lease.get("state")
        if state_name in {"running", "active"}:
            state = registry.record_terminal_evidence(
                lease_id,
                {
                    "success": receipt.get("status") == "completed",
                    "binding_digest": binding_digest,
                    "binding_format": "run-id-v2",
                    "terminal_event": receipt.get("terminal_event"),
                },
                allowed_set_digest,
            )
            lease = state["lease"]
            state_name = lease["state"]
        else:
            stored_binding = lease.get("terminal_receipt", {}).get("binding_digest")
            if not isinstance(stored_binding, str):
                raise RecoveryStateError("terminal receipt binding drifted during reload")
            _match_terminal_binding(
                receipt,
                run_dir=run_dir,
                run_id=expected_run_id,
                stored_digest=stored_binding,
            )
            binding_digest = stored_binding
        if state_name == "terminal-pending-stop":
            state = registry.prove_contained_tree_empty(
                lease_id,
                zero,
                allowed_set_digest,
            )
            lease = state["lease"]
            state_name = lease["state"]

        semantic_disposition = lease.get("semantic_disposition")
        if terminal_abandonment and not isinstance(semantic_disposition, dict):
            if state_name != "stopped-terminal":
                raise RecoveryStateError(
                    "terminal abandonment requires a stopped contained lease"
                )
            state = registry.record_terminal_abandonment(lease_id)
            lease = state["lease"]
            semantic_disposition = lease["semantic_disposition"]
        if isinstance(semantic_disposition, dict):
            project_lane_close_required = True
            if (
                request.get("project_lane") is not None
                and not project_lane_quarantined
            ):
                quarantine_project_lane_writer(request, "cancelled")
                project_lane_quarantined = True
            if semantic_disposition.get("disposition") == "abandoned":
                if semantic_disposition.get("checkpoint_invalidation") != "completed":
                    state = registry.complete_terminal_abandonment(lease_id)
                    lease = state["lease"]
                    semantic_disposition = lease["semantic_disposition"]
                abandoned_receipt = {
                    "outcome": "terminal-abandoned",
                    "schema": semantic_disposition.get("schema"),
                    "cause": semantic_disposition.get("cause"),
                    "evidence_digest": semantic_disposition.get("evidence_digest"),
                    "checkpoint_allowed": semantic_disposition.get("checkpoint_allowed"),
                    "checkpoint_invalidation": semantic_disposition.get("checkpoint_invalidation"),
                    "checkpoint_digest": semantic_disposition.get("checkpoint_digest"),
                }
                atomic_write_json(run_dir / "terminal-abandonment.json", abandoned_receipt)
            semantic_receipt = {
                "event": "semantic-handoff-rejected",
                "run_id": semantic_disposition.get("run_id"),
                "lease_id": lease_id,
                "disposition": semantic_disposition.get("disposition"),
                "evidence_digest": semantic_disposition.get("evidence_digest"),
                "checkpoint_allowed": semantic_disposition.get("checkpoint_allowed"),
                "checkpoint_invalidation": semantic_disposition.get(
                    "checkpoint_invalidation"
                ),
                "checkpoint_digest": semantic_disposition.get("checkpoint_digest"),
            }
            if (
                semantic_disposition.get("disposition") != "abandoned"
                and semantic_disposition.get("checkpoint_invalidation") != "completed"
            ):
                atomic_write_json(
                    run_dir / "semantic-rejection.json", semantic_receipt
                )
            if semantic_disposition.get("disposition") == "needs-escalation":
                source_state_id = semantic_disposition.get("source_state_id")
                evidence_digest = semantic_disposition.get("evidence_digest")
                if not isinstance(source_state_id, str):
                    raise RecoveryStateError(
                        "semantic escalation has no source checkpoint binding"
                    )
                if not isinstance(evidence_digest, str):
                    raise RecoveryStateError(
                        "semantic escalation has no evidence digest binding"
                    )
                if semantic_disposition.get("checkpoint_invalidation") == "completed":
                    invalidated_checkpoint = registry.public_checkpoint_for_source(
                        source_state_id
                    )
                else:
                    invalidated_checkpoint = registry.invalidate_source_checkpoint(
                        source_state_id,
                        reason="semantic-needs-escalation",
                        evidence_digest=evidence_digest,
                    )
                checkpoint_digest = invalidated_checkpoint.get("checkpoint_digest")
                if not isinstance(checkpoint_digest, str):
                    raise RecoveryStateError(
                        "invalidated source checkpoint has no durable digest"
                    )
                if semantic_disposition.get("checkpoint_invalidation") != "completed":
                    state = registry.complete_source_checkpoint_invalidation(
                        lease_id,
                        source_state_id=source_state_id,
                        checkpoint_digest=checkpoint_digest,
                        evidence_digest=evidence_digest,
                    )
                    lease = state["lease"]
                    semantic_disposition = lease["semantic_disposition"]
                elif semantic_disposition.get("checkpoint_digest") != checkpoint_digest:
                    raise RecoveryStateError(
                        "completed source checkpoint artifact digest drifted"
                    )
                atomic_write_json(
                    run_dir / "recovery-checkpoint.json", invalidated_checkpoint
                )
                semantic_receipt["checkpoint_invalidation"] = "completed"
                semantic_receipt["checkpoint_digest"] = checkpoint_digest
                atomic_write_json(
                    run_dir / "semantic-rejection.json", semantic_receipt
                )
        semantic_success = (
            receipt.get("status") == "completed"
            and not isinstance(semantic_disposition, dict)
            and lease.get("terminal_receipt", {}).get("success") is True
        )

        checkpoint: dict[str, Any] | None = None
        verification_checkpoint: dict[str, Any] | None = None
        preflight = request.get("recovery_preflight")
        if isinstance(preflight, dict) and (
            not isinstance(semantic_disposition, dict)
            or semantic_disposition.get("checkpoint_allowed") is True
        ):
            checkpoint_path = run_dir / "recovery-checkpoint.json"
            try:
                checkpoint = (
                    read_json(checkpoint_path)
                    if checkpoint_path.is_file()
                    else registry.finalize_prepared_checkpoint(
                        preflight,
                        source_receipt_digest=binding_digest,
                    )
                )
                checkpoint = registry.revalidate_checkpoint(checkpoint)
                atomic_write_json(checkpoint_path, checkpoint)
            except RecoveryStateError as checkpoint_exc:
                if semantic_success:
                    raise
                atomic_write_json(
                    run_dir / "recovery-checkpoint-unavailable.json",
                    {
                        "disposition": "recovery-capability-unavailable",
                        "reason": str(checkpoint_exc),
                        "receipt_digest": binding_digest,
                    },
                )
                checkpoint = None

        parent_checkpoint = request.get("recovery_parent_checkpoint")
        if isinstance(parent_checkpoint, dict) and semantic_success:
            verification_checkpoint = registry.revalidate_checkpoint(
                parent_checkpoint,
                persist=False,
            )
            atomic_write_json(
                run_dir / "recovery-parent-verification.json",
                verification_checkpoint,
            )
        else:
            verification_checkpoint = checkpoint

        if semantic_success and state_name == "stopped-terminal":
            if success_verification_digest is None:
                return
            if not re.fullmatch(r"[0-9a-f]{64}", success_verification_digest):
                raise RecoveryStateError("root success verification digest must be lowercase SHA-256")
            if (
                verification_checkpoint is None
                or verification_checkpoint.get("disposition") != "recovery-eligible"
            ):
                raise RecoveryStateError("successful handoff failed the final allowed-set verification")
            payload = {
                "lease_id": lease_id,
                "run_id": run_dir.name,
                "receipt_digest": binding_digest,
                "checkpoint_digest": verification_checkpoint["checkpoint_digest"],
                "allowed_set_digest": allowed_set_digest,
                "root_verification_digest": success_verification_digest,
            }
            event_id = sha256_bytes(
                b"openbuild-contained-handoff-v1\0" + _canonical_json_bytes(payload)
            )
            state = registry.commit_handoff(
                lease_id,
                {"event_id": event_id, "payload": payload},
                allowed_set_digest,
            )
            state = registry.materialize_handoff(
                lease_id,
                run_dir / "implementation-handoffs.jsonl",
            )
            lease = state["lease"]
            state_name = lease["state"]
        elif semantic_success and state_name == "handoff-committed":
            registry.materialize_handoff(
                lease_id,
                run_dir / "implementation-handoffs.jsonl",
            )

        state = registry.state()
        lease = state.get("lease")
        if not isinstance(lease, dict):
            return
        if not lease.get("guardian_close"):
            guardian_id = lease.get("provider_receipt", {}).get("guardian_id")
            write_guardian_message(
                run_dir / "guardian-close.json",
                secret,
                "guardian-close",
                {"guardian_id": guardian_id, "zero_digest": sha256_bytes(_canonical_json_bytes(zero))},
            )
            closed = await_guardian_record(
                run_dir,
                secret,
                "guardian-closed.json",
                "guardian-closed",
            )
            registry.acknowledge_guardian_close(lease_id, closed)
        registry.release_contained_terminal(lease_id)
        if safe_stop_intent is not None:
            checkpoint_digest, preserved_changes = safe_stop_checkpoint_binding(
                registry,
                checkpoint,
            )
            completed = complete_project_lane_safe_stop(
                request,
                str(safe_stop_intent["intent_id"]),
                recovery_checkpoint_digest=checkpoint_digest,
                preserved_changes=preserved_changes,
            )
            materialize_project_lane_safe_stop_receipt(
                safe_stop_receipt_path,
                completed["safe_stop"],
            )
        elif project_lane_close_required:
            recovery_checkpoint_digest = _project_lane_recovery_checkpoint_digest(
                run_dir,
                receipt,
            )
            if recovery_checkpoint_digest is not None:
                prepare_project_lane_recovery(
                    request,
                    recovery_checkpoint_digest,
                )
            else:
                finalize_project_lane_terminal(
                    request,
                    "crashed" if receipt.get("status") == "failed" else "cancelled",
                )
        elif request.get("project_lane") is not None:
            complete_project_lane_writer(request)
        garbage_collect_owner_prompt_snapshots(registry)
    except (OSError, RecoveryStateError) as exc:
        if request.get("project_lane") is not None:
            try:
                retained = registry.state()
                if (
                    retained.get("quarantine") is not None
                    or receipt.get("status") == "failed"
                    or terminal_abandonment
                ):
                    quarantine_project_lane_writer(
                        request,
                        (
                            "crashed"
                            if receipt.get("status") == "failed"
                            else "cancelled"
                        ),
                    )
            except (RecoveryStateError, RunnerError) as lane_exc:
                raise RunnerError(
                    "contained implementation terminalization and project lane "
                    f"quarantine failed closed: {exc}; lane: {lane_exc}"
                ) from exc
        raise RunnerError(f"contained implementation terminalization failed closed: {exc}") from exc


def finalize_success_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_reference(args.run_dir)
    if (run_dir / "semantic-rejection.json").is_file():
        raise RunnerError("root success finalization is forbidden after semantic handoff rejection")
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt.get("status") != "completed":
        raise RunnerError("root success finalization requires an accepted completed runner receipt")
    request = read_json(run_dir / "request.json")
    registry = recovery_registry_for_request(request)
    if registry is not None and any(
        event.get("event") == "semantic-handoff-rejected"
        and event.get("run_id") == run_dir.name
        for event in registry.state().get("history", [])
    ):
        raise RunnerError("root success finalization is forbidden after semantic handoff rejection")
    reconcile_implementation_registry(
        run_dir,
        receipt,
        success_verification_digest=args.primary_signal_digest,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def reject_semantic_handoff_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_reference(args.run_dir)
    semantic_path = run_dir / "semantic-rejection.json"
    existing_semantic = read_json(semantic_path) if semantic_path.is_file() else None
    if isinstance(existing_semantic, dict):
        if (
            existing_semantic.get("disposition") != args.disposition
            or existing_semantic.get("evidence_digest") != args.evidence_digest
        ):
            raise RunnerError("semantic handoff rejection replay binding drifted")
        if existing_semantic.get("checkpoint_invalidation") != "pending":
            raise RunnerError("semantic handoff rejection was already consumed for this run")
    if not re.fullmatch(r"[0-9a-f]{64}", args.evidence_digest):
        raise RunnerError("semantic rejection evidence digest must be lowercase SHA-256")
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt.get("status") != "completed" or receipt.get("process_tree_stopped") is not True:
        raise RunnerError("semantic rejection requires stopped transport-success evidence")
    reconcile_implementation_registry(run_dir, receipt)
    if isinstance(existing_semantic, dict):
        completed_semantic = read_json(semantic_path)
        if completed_semantic.get("checkpoint_invalidation") != "completed":
            raise RunnerError("semantic handoff rejection retry did not complete checkpoint invalidation")
        print(json.dumps(completed_semantic, ensure_ascii=False, indent=2))
        return 0
    if semantic_path.is_file():
        reconstructed_semantic = read_json(semantic_path)
        if (
            reconstructed_semantic.get("disposition") == args.disposition
            and reconstructed_semantic.get("evidence_digest") == args.evidence_digest
        ):
            print(json.dumps(reconstructed_semantic, ensure_ascii=False, indent=2))
            return 0
    request = read_json(run_dir / "request.json")
    registry = recovery_registry_for_request(request)
    lease_id = request.get("lease_id")
    if registry is None or not isinstance(lease_id, str):
        raise RunnerError("semantic rejection requires a recovery-capable implementation lease")
    checkpoint_allowed = args.disposition == "blocked"
    try:
        registry.reject_semantic_handoff(
            lease_id,
            run_id=run_dir.name,
            disposition=args.disposition,
            evidence_digest=args.evidence_digest,
            checkpoint_allowed=checkpoint_allowed,
        )
        reconcile_implementation_registry(run_dir, receipt)
    except RecoveryStateError as exc:
        raise RunnerError(f"semantic handoff rejection failed closed: {exc}") from exc
    semantic_receipt = read_json(semantic_path)
    print(json.dumps(semantic_receipt, ensure_ascii=False, indent=2))
    return 0


def reconcile_terminal_abandonment_run(args: argparse.Namespace) -> int:
    """Privately reconcile the same stopped lifecycle; no caller controls its cause."""
    run_dir = resolve_run_reference(args.run_dir)
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt.get("status") != "completed" or receipt.get("process_tree_stopped") is not True:
        raise RunnerError("terminal abandonment requires stopped transport-success evidence")
    try:
        reconcile_implementation_registry(
            run_dir,
            receipt,
            terminal_abandonment=True,
        )
    except (OSError, RecoveryStateError) as exc:
        raise RunnerError(f"terminal abandonment failed closed: {exc}") from exc
    print(json.dumps(read_json(run_dir / "terminal-abandonment.json"), ensure_ascii=False, indent=2))
    return 0


def _containment_loss_reconciliation_result(lease_id: str) -> dict[str, Any]:
    return {
        "outcome": "containment-loss-reconciled",
        "schema": "containment-loss-reconciliation-v1",
        "lease_id": lease_id,
        "registry_vacant": True,
        "checkpoint_invalidated": True,
        "handoff_accepted": False,
        "writer_action": "none",
    }


def _containment_loss_release_is_complete(
    state: Mapping[str, Any], *, lease_id: str, run_id: str
) -> bool:
    if (
        state.get("lease") is not None
        or state.get("outbox") is not None
        or state.get("quarantine") is not None
    ):
        return False
    reconciled = [
        event
        for event in state.get("history", [])
        if event.get("event") == "containment-loss-reconciled"
        and event.get("lease_id") == lease_id
        and event.get("run_id") == run_id
    ]
    recorded = [
        event
        for event in state.get("history", [])
        if event.get("event") == "terminal-abandonment-recorded"
        and event.get("lease_id") == lease_id
        and event.get("run_id") == run_id
        and event.get("disposition") == "abandoned"
    ]
    completed = [
        event
        for event in state.get("history", [])
        if event.get("event") == "terminal-abandonment-completed"
        and event.get("lease_id") == lease_id
        and event.get("run_id") == run_id
    ]
    released = [
        event
        for event in state.get("history", [])
        if event.get("event") == "contained-terminal-released"
        and event.get("lease_id") == lease_id
        and event.get("run_id") == run_id
        and event.get("semantic_disposition") == "abandoned"
        and event.get("terminal_success") is False
        and event.get("handoff_digest") is None
        and event.get("outbox_digest") is None
    ]
    return len(reconciled) == len(recorded) == len(completed) == len(released) == 1


def _orphan_containment_loss_observation(
    run_dir: Path,
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the exact Windows Job boundary after its guardian died pre-zero."""
    provider = lease.get("provider_receipt")
    process = lease.get("process_receipt")
    if not isinstance(provider, Mapping) or not isinstance(process, Mapping):
        raise RecoveryStateError(
            "orphan containment-loss reconciliation lacks process ownership evidence"
        )
    precommit = provider.get("precommit")
    if (
        provider.get("provider") != "windows-job"
        or provider.get("policy") != "kill-on-close-no-breakaway"
        or provider.get("anti_migration") is not None
        or provider.get("active_processes") != 1
        or not isinstance(precommit, Mapping)
        or precommit.get("provider_populated") is not True
        or precommit.get("membership_verified") is not True
    ):
        raise RecoveryStateError(
            "orphan containment-loss reconciliation requires the exact "
            "Windows kill-on-close boundary"
        )
    try:
        secret = _guardian_secret(run_dir)
        ready = read_guardian_message(
            run_dir / "guardian-ready.json", secret, "guardian-ready"
        )
        precommit_ready = read_guardian_message(
            run_dir / "guardian-precommit-ready.json",
            secret,
            "guardian-precommit-ready",
        )
        boundary = read_guardian_message(
            run_dir / "containment-bound.json", secret, "containment-bound"
        )
        worker_artifact = read_json(run_dir / "worker.json")
        codex = read_json(run_dir / "codex.json")
        codex_spawn = read_json(run_dir / "codex-spawn.json")
        activation = read_json(run_dir / "activate.json")
    except (OSError, RunnerError, ValueError) as exc:
        raise RecoveryStateError(
            f"orphan containment-loss reconciliation evidence is unreadable: {exc}"
        ) from exc

    expected_ready = {
        **{key: value for key, value in provider.items() if key != "precommit"},
        "worker": dict(process),
    }
    if ready != expected_ready or worker_artifact != process:
        raise RecoveryStateError(
            "orphan containment-loss reconciliation guardian evidence drifted"
        )
    precommit_registry_digest = precommit_ready.get("registry_digest")
    precommit_payload = dict(precommit_ready)
    precommit_payload.pop("registry_digest", None)
    if (
        precommit_payload != precommit
        or not isinstance(precommit_registry_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", precommit_registry_digest) is None
    ):
        raise RecoveryStateError(
            "orphan containment-loss reconciliation precommit evidence drifted"
        )
    expected_boundary = {
        "guardian_id": provider.get("guardian_id"),
        "worker_pid": process.get("pid"),
        "worker_identity": process.get("identity"),
        "allowed_set_digest": lease.get("allowed_set_digest"),
        "provider_plan_id": provider.get("provider_plan_id"),
        "ipc_plan_id": provider.get("ipc_plan_id"),
        "precommit_nonce": precommit.get("precommit_nonce"),
    }
    if boundary != expected_boundary:
        raise RecoveryStateError(
            "orphan containment-loss reconciliation boundary evidence drifted"
        )
    expected_codex_fields = {
        "pid",
        "identity",
        "process_group_id",
        "started_at",
    }
    if (
        set(codex) != expected_codex_fields
        or codex_spawn
        != {
            **codex,
            "state": "started",
            "worker_pid": process.get("pid"),
        }
        or activation.get("codex_pid") != codex.get("pid")
        or activation.get("codex_process_identity") != codex.get("identity")
        or not isinstance(
            activation.get("root_completion_source_binding_digest"), str
        )
        or re.fullmatch(
            r"[0-9a-f]{64}",
            activation["root_completion_source_binding_digest"],
        )
        is None
    ):
        raise RecoveryStateError(
            "orphan containment-loss reconciliation Codex evidence drifted"
        )

    guardian_state = process_record_state(
        {
            "pid": provider.get("guardian_pid"),
            "identity": provider.get("guardian_identity"),
        }
    )
    worker_state = process_record_state(process)
    codex_state = process_tree_record_state(codex)
    if (
        guardian_state not in {"stopped", "reused"}
        or worker_state not in {"stopped", "reused"}
        or codex_state not in {"stopped", "reused"}
    ):
        raise RecoveryStateError(
            "orphan containment-loss reconciliation original processes are not stopped"
        )
    observation_basis = {
        "schema": "containment-loss-orphan-reconciliation-v1",
        "provider": provider["provider"],
        "policy": provider["policy"],
        "guardian_pid": provider["guardian_pid"],
        "guardian_identity": provider["guardian_identity"],
        "guardian_state": guardian_state,
        "worker_pid": process["pid"],
        "worker_identity": process["identity"],
        "worker_state": worker_state,
        "codex_pid": codex["pid"],
        "codex_identity": codex["identity"],
        "codex_state": codex_state,
        "guardian_ready_digest": sha256_bytes(_canonical_json_bytes(ready)),
        "precommit_ready_digest": sha256_bytes(
            _canonical_json_bytes(precommit_ready)
        ),
        "containment_bound_digest": sha256_bytes(
            _canonical_json_bytes(boundary)
        ),
    }
    observation_path = run_dir / "containment-loss-orphan-observation.json"
    if observation_path.is_file():
        try:
            existing = read_json(observation_path)
        except (OSError, RunnerError, ValueError) as exc:
            raise RecoveryStateError(
                f"orphan containment-loss reconciliation observation is unreadable: {exc}"
            ) from exc
        reconciled_at = existing.get("reconciled_at")
        existing_basis = dict(existing)
        existing_basis.pop("reconciled_at", None)
        if (
            existing_basis != observation_basis
            or not isinstance(reconciled_at, str)
            or not reconciled_at
        ):
            raise RecoveryStateError(
                "orphan containment-loss reconciliation observation replay drifted"
            )
        return dict(existing)
    observation = {**observation_basis, "reconciled_at": utc_now()}
    atomic_write_json(observation_path, observation)
    return observation


def reconcile_containment_loss_run(args: argparse.Namespace) -> int:
    """Reconcile exact post-zero or Windows pre-zero guardian loss without handoff."""
    run_dir = resolve_run_reference(args.run_dir)
    request = read_json(run_dir / "request.json")
    lease_id = request.get("lease_id")
    registry = recovery_registry_for_request(request)
    if registry is None or not isinstance(lease_id, str):
        raise RunnerError("containment-loss reconciliation cannot resolve its registry lease")
    _require_private_run_path_identity(run_dir, run_dir.name)
    try:
        state = registry.state()
        lease = state.get("lease")
        if lease is None:
            if not _containment_loss_release_is_complete(
                state, lease_id=lease_id, run_id=run_dir.name
            ):
                raise RecoveryStateError(
                    "containment-loss reconciliation has no exact completed release"
                )
        else:
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or _expected_lease_run_id(lease) != run_dir.name
            ):
                raise RecoveryStateError(
                    "containment-loss reconciliation does not own the current lease"
                )
            if request.get("project_lane") is not None:
                quarantine_project_lane_writer(request, "crashed")
            reconciled = [
                event
                for event in state.get("history", [])
                if event.get("event") == "containment-loss-reconciled"
                and event.get("lease_id") == lease_id
                and event.get("run_id") == run_dir.name
            ]
            semantic = lease.get("semantic_disposition")
            if reconciled:
                if (
                    len(reconciled) != 1
                    or state.get("quarantine") is not None
                    or not isinstance(semantic, Mapping)
                    or semantic.get("disposition") != "abandoned"
                ):
                    raise RecoveryStateError(
                        "containment-loss reconciliation replay is not authoritative"
                    )
            else:
                post_zero = (
                    state.get("quarantine") == "containment-loss-after-boundary"
                    and lease.get("state") == "stopped-terminal"
                    and semantic is None
                    and state.get("outbox") is None
                    and isinstance(lease.get("zero_proof"), Mapping)
                    and lease.get("guardian_close") is None
                    and not (run_dir / "guardian-failure.json").exists()
                    and not (run_dir / "guardian-closed.json").exists()
                )
                orphan_pre_zero = (
                    state.get("quarantine") == "containment-loss-after-boundary"
                    and lease.get("lease_kind") == "normal-contained"
                    and lease.get("state") == "running"
                    and semantic is None
                    and state.get("outbox") is None
                    and lease.get("terminal_receipt") is None
                    and lease.get("zero_proof") is None
                    and lease.get("guardian_close") is None
                    and not (run_dir / "guardian-failure.json").exists()
                    and not (run_dir / "guardian-closed.json").exists()
                    and not (run_dir / "guardian-zero.json").exists()
                )
                if not post_zero and not orphan_pre_zero:
                    raise RecoveryStateError(
                        "containment-loss reconciliation requires exact post-zero or "
                        "Windows orphan quarantine"
                    )
                if orphan_pre_zero:
                    observation = _orphan_containment_loss_observation(
                        run_dir, lease
                    )
                    state = registry.record_orphan_containment_loss_abandonment(
                        lease_id,
                        observation,
                    )
                else:
                    secret = _guardian_secret(run_dir)
                    ready = read_guardian_message(
                        run_dir / "guardian-ready.json", secret, "guardian-ready"
                    )
                    zero = read_guardian_message(
                        run_dir / "guardian-zero.json", secret, "guardian-zero"
                    )
                    provider = lease.get("provider_receipt")
                    process = lease.get("process_receipt")
                    if not isinstance(provider, Mapping) or not isinstance(
                        process, Mapping
                    ):
                        raise RecoveryStateError(
                            "containment-loss reconciliation lacks process "
                            "ownership evidence"
                        )
                    expected_ready = {
                        **{
                            key: value
                            for key, value in provider.items()
                            if key != "precommit"
                        },
                        "worker": dict(process),
                    }
                    if ready != expected_ready or zero != lease.get("zero_proof"):
                        raise RecoveryStateError(
                            "containment-loss reconciliation guardian evidence drifted"
                        )
                    receipt = public_receipt(run_dir)
                    if (
                        receipt.get("status") != "completed"
                        or receipt.get("process_tree_stopped") is not True
                        or receipt.get("lease_id") != lease_id
                    ):
                        raise RecoveryStateError(
                            "containment-loss reconciliation requires stopped "
                            "terminal receipt"
                        )
                    terminal_binding = lease.get("terminal_receipt", {}).get(
                        "binding_digest"
                    )
                    if not isinstance(terminal_binding, str):
                        raise RecoveryStateError(
                            "containment-loss reconciliation terminal binding is "
                            "missing"
                        )
                    _match_terminal_binding(
                        receipt,
                        run_dir=run_dir,
                        run_id=run_dir.name,
                        stored_digest=terminal_binding,
                    )
                    guardian_state = process_record_state(
                        {
                            "pid": provider.get("guardian_pid"),
                            "identity": provider.get("guardian_identity"),
                        }
                    )
                    worker_state = process_record_state(process)
                    if guardian_state not in {
                        "stopped",
                        "reused",
                    } or worker_state not in {
                        "stopped",
                        "reused",
                    }:
                        raise RecoveryStateError(
                            "containment-loss reconciliation original processes "
                            "are not stopped"
                        )
                    state = registry.record_containment_loss_abandonment(
                        lease_id,
                        {
                            "schema": "containment-loss-reconciliation-v1",
                            "guardian_pid": provider["guardian_pid"],
                            "guardian_identity": provider["guardian_identity"],
                            "guardian_state": guardian_state,
                            "worker_pid": process["pid"],
                            "worker_identity": process["identity"],
                            "worker_state": worker_state,
                            "reconciled_at": utc_now(),
                        },
                    )

            lease = state.get("lease")
            if not isinstance(lease, Mapping):
                raise RecoveryStateError(
                    "containment-loss reconciliation lost its pending lease"
                )
            semantic = lease.get("semantic_disposition")
            if not isinstance(semantic, Mapping) or semantic.get("disposition") != "abandoned":
                raise RecoveryStateError(
                    "containment-loss reconciliation did not record abandonment"
                )
            if semantic.get("checkpoint_invalidation") != "completed":
                state = registry.complete_terminal_abandonment(lease_id)
            lease = state.get("lease")
            if isinstance(lease, Mapping) and lease.get("guardian_close") is None:
                state = registry.acknowledge_containment_loss_close(lease_id)
            registry.release_contained_terminal(lease_id)
            garbage_collect_owner_prompt_snapshots(registry)
    except RecoveryStateError as exc:
        raise RunnerError(f"containment-loss reconciliation failed closed: {exc}") from exc
    if request.get("project_lane") is not None:
        finalize_project_lane_terminal(request, "crashed")

    result = _containment_loss_reconciliation_result(lease_id)
    atomic_write_json(run_dir / "containment-loss-reconciliation.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _post_commit_root_completion_blocked() -> dict[str, Any]:
    return {
        "outcome": "blocked",
        "missing_evidence": ["missing-evidence"],
        "required_action": "restore-safety-evidence",
        "writer_action": "none",
    }


def _post_commit_root_completion_result(task_commit: str) -> dict[str, Any]:
    return {
        "outcome": "terminal-root-completed",
        "schema": "terminal-root-completion-v1",
        "task_commit": task_commit,
        "registry_vacant": True,
        "writer_action": "none",
    }


def _post_commit_root_completion_completed(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the private full-tuple artifact written only after release."""
    required = {
        "schema",
        "lease_id",
        "run_id",
        "source_state_id",
        "task_commit",
        "parent_commit",
        "root_verification_digest",
        "producer_allowed_set_digest",
        "remediation_scope_digest",
        "action_snapshot_id",
        "action_snapshot_sha256",
        "user_action_digest",
        "authorization_digest",
        "authorization_consumption",
        "terminal_binding_format",
        "terminal_binding_digest",
        "checkpoint_digest",
        "archive_digest",
    }
    if (
        not isinstance(binding, Mapping)
        or set(binding) != required
        or binding.get("schema") != "terminal-root-completion-artifact-v1"
        or binding.get("authorization_consumption") != "consumed"
        or binding.get("terminal_binding_format") != "run-dir-v1"
    ):
        raise RecoveryStateError("post-commit completed replay binding drifted")
    return dict(binding)


def _read_private_remediation_scope(repo: Path, path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    try:
        value = json.loads(_read_stable_external_prompt(repo, path).decode("utf-8"))
    except (OSError, UnicodeError, ValueError, RunnerError) as exc:
        raise RecoveryStateError("post-commit remediation scope is unavailable") from exc
    if not isinstance(value, dict):
        raise RecoveryStateError("post-commit remediation scope is malformed")
    return value


def _require_legacy_post_commit_binding(
    run_dir: Path, receipt: Mapping[str, Any], registry: RecoveryRegistry
) -> str:
    state = registry.state()
    lease = state.get("lease")
    if not isinstance(lease, Mapping):
        raise RecoveryStateError("post-commit terminal lease is unavailable")
    run_id = _expected_lease_run_id(lease)
    stored_digest = lease.get("terminal_receipt", {}).get("binding_digest")
    if not isinstance(stored_digest, str):
        raise RecoveryStateError("post-commit terminal binding is unavailable")
    matched = _match_terminal_binding(
        receipt,
        run_dir=run_dir,
        run_id=run_id,
        stored_digest=stored_digest,
    )
    if matched.get("format") != "run-dir-v1":
        raise RecoveryStateError("post-commit remediation requires a legacy terminal binding")
    return stored_digest


def stage_post_commit_root_completion_action_run(args: argparse.Namespace) -> int:
    """Create one canonical confirmed action snapshot without issuing capability."""
    try:
        run_dir = resolve_run_reference(args.run_dir)
        request = read_json(run_dir / "request.json")
        registry = recovery_registry_for_request(request)
        if registry is None:
            raise RecoveryStateError("post-commit registry is unavailable")
        audit_guardian_health(run_dir)
        receipt = public_receipt(run_dir)
        if receipt.get("status") != "completed" or receipt.get("process_tree_stopped") is not True:
            raise RecoveryStateError("post-commit terminal transport evidence is unavailable")
        _require_legacy_post_commit_binding(run_dir, receipt, registry)
        scope = _read_private_remediation_scope(Path(request["repo"]), args.remediation_scope_file)
        snapshot = registry.build_post_commit_root_completion_action_snapshot(
            run_id=run_dir.name,
            task_commit=args.task_commit,
            root_verification_digest=args.root_verification_digest,
            source_checkpoint_digest=scope["source_checkpoint_digest"],
            remediation_scope=scope,
        )
        binding = stage_owner_prompt_snapshot(registry, _canonical_json_bytes(snapshot))
    except (OSError, KeyError, RecoveryStateError, RunnerError):
        print(json.dumps(_post_commit_root_completion_blocked(), ensure_ascii=False))
        return 0
    print(
        json.dumps(
            {
                "outcome": "action-snapshot-confirmed",
                "action_snapshot_id": binding["prompt_snapshot_id"],
                "action_snapshot_sha256": binding["prompt_sha256"],
                "writer_action": "none",
            },
            ensure_ascii=False,
        )
    )
    return 0


def authorize_post_commit_root_completion_run(args: argparse.Namespace) -> int:
    """Hidden same-account issuance; stdout exposes only an opaque handle."""
    try:
        run_dir = resolve_run_reference(args.run_dir)
        request = read_json(run_dir / "request.json")
        registry = recovery_registry_for_request(request)
        if registry is None:
            raise RecoveryStateError("post-commit registry is unavailable")
        audit_guardian_health(run_dir)
        receipt = public_receipt(run_dir)
        if receipt.get("status") != "completed" or receipt.get("process_tree_stopped") is not True:
            raise RecoveryStateError("post-commit terminal transport evidence is unavailable")
        _require_legacy_post_commit_binding(run_dir, receipt, registry)
        scope = _read_private_remediation_scope(Path(request["repo"]), args.remediation_scope_file)
        snapshot = json.loads(
            read_owner_prompt_snapshot(
                registry,
                args.action_snapshot_id,
                args.action_snapshot_sha256,
            )
        )
        if not isinstance(snapshot, dict):
            raise RecoveryStateError("post-commit action snapshot is malformed")
        action = registry.stage_post_commit_root_completion_action(
            run_id=run_dir.name,
            task_commit=args.task_commit,
            root_verification_digest=args.root_verification_digest,
            source_checkpoint_digest=scope["source_checkpoint_digest"],
            remediation_scope=scope,
            action_snapshot=snapshot,
            action_snapshot_id=args.action_snapshot_id,
            action_snapshot_sha256=args.action_snapshot_sha256,
        )
        authorization = registry.issue_post_commit_root_completion_authorization(action)
    except (OSError, KeyError, ValueError, RecoveryStateError, RunnerError):
        print(json.dumps(_post_commit_root_completion_blocked(), ensure_ascii=False))
        return 0
    print(
        json.dumps(
            {
                "outcome": "authorization-issued",
                "authorization_handle": authorization["authorization_handle"],
                "writer_action": "none",
            },
            ensure_ascii=False,
        )
    )
    return 0


def finalize_post_commit_root_completion_run(args: argparse.Namespace) -> int:
    """Consume an opaque private capability and close the retained terminal lease."""
    task_commit = args.task_commit
    completed_path: Path | None = None
    try:
        run_dir = resolve_run_reference(args.run_dir)
        completed_path = run_dir / "terminal-root-completion.json"
        audit_guardian_health(run_dir)
        receipt = public_receipt(run_dir)
        if receipt.get("status") != "completed" or receipt.get("process_tree_stopped") is not True:
            raise RecoveryStateError("post-commit terminal transport evidence is unavailable")
        request = read_json(run_dir / "request.json")
        registry = recovery_registry_for_request(request)
        lease_id = request.get("lease_id")
        if registry is None or not isinstance(lease_id, str):
            raise RecoveryStateError("post-commit registry lease is unavailable")
        scope = _read_private_remediation_scope(Path(request["repo"]), args.remediation_scope_file)
        registry_state = registry.state()
        prior_lease = registry_state.get("lease")
        if prior_lease is None:
            replay_binding = registry.post_commit_root_completion_replay_binding(
                lease_id=lease_id,
                run_id=run_dir.name,
                task_commit=task_commit,
                root_verification_digest=args.root_verification_digest,
                authorization_handle=args.authorization_handle,
                remediation_scope_digest=scope["digest"],
            )
            completed = _post_commit_root_completion_completed(replay_binding)
            if completed_path.is_file():
                if read_json(completed_path) != completed:
                    raise RecoveryStateError("post-commit completed replay binding drifted")
            else:
                durable_write_private_json(completed_path, completed)
            print(json.dumps(_post_commit_root_completion_result(task_commit), ensure_ascii=False))
            return 0
        if completed_path.is_file():
            raise RecoveryStateError("post-commit completed artifact preceded terminal release")
        _require_legacy_post_commit_binding(run_dir, receipt, registry)
        # The post-commit transition owns exact stopped-terminal replay.
        # Generic reconciliation would persist the mixed-drift candidate before
        # the authorization-bound intent and must never pre-empt these phases.
        registry.finalize_post_commit_root_completion(
            lease_id,
            run_id=run_dir.name,
            task_commit=task_commit,
            root_verification_digest=args.root_verification_digest,
            authorization_handle=args.authorization_handle,
            remediation_scope=scope,
            terminal_binding_format="run-dir-v1",
        )
        registry.complete_post_commit_root_completion(lease_id)
        secret = _guardian_secret(run_dir)
        state = registry.state()
        lease = state.get("lease")
        if not isinstance(lease, Mapping):
            raise RecoveryStateError("post-commit lease disappeared before guardian closure")
        if not lease.get("guardian_close"):
            guardian_id = lease.get("provider_receipt", {}).get("guardian_id")
            write_guardian_message(
                run_dir / "guardian-close.json",
                secret,
                "guardian-close",
                {"guardian_id": guardian_id, "zero_digest": sha256_bytes(_canonical_json_bytes(lease["zero_proof"]))},
            )
            registry.acknowledge_guardian_close(
                lease_id,
                await_guardian_record(run_dir, secret, "guardian-closed.json", "guardian-closed"),
            )
        registry.release_contained_terminal(lease_id)
        garbage_collect_owner_prompt_snapshots(registry)
        replay_binding = registry.post_commit_root_completion_replay_binding(
            lease_id=lease_id,
            run_id=run_dir.name,
            task_commit=task_commit,
            root_verification_digest=args.root_verification_digest,
            authorization_handle=args.authorization_handle,
            remediation_scope_digest=scope["digest"],
        )
        completed = _post_commit_root_completion_completed(replay_binding)
        assert completed_path is not None
        durable_write_private_json(completed_path, completed)
    except (OSError, KeyError, RecoveryStateError, RunnerError):
        print(json.dumps(_post_commit_root_completion_blocked(), ensure_ascii=False))
        return 0
    print(json.dumps(_post_commit_root_completion_result(task_commit), ensure_ascii=False))
    return 0


def _validate_legacy_root_completion_release(
    *,
    run_dir: Path,
    request: Mapping[str, Any],
    release: Mapping[str, Any],
    specification_revision: str,
    milestone: str,
    allowed_set_digest: str,
) -> None:
    """Accept only an activated, failed normal-legacy run with no handoff path."""
    if (
        release.get("success") is not False
        or request.get("recovery_target") is not False
        or request.get("recovery_preflight") is not None
        or request.get("lifecycle_allowed_set_digest") != allowed_set_digest
        or request.get("task_name") != milestone
        or (run_dir / "implementation-handoffs.jsonl").exists()
        or (run_dir / "terminal-abandonment.json").exists()
    ):
        raise RunnerError("root completion audit legacy release binding drifted")
    if not re.fullmatch(r"[0-9a-f]{64}", allowed_set_digest):
        raise RunnerError("root completion audit legacy allowed scope is malformed")

    source_binding_present = "root_completion_source_binding" in request
    source_binding = request.get("root_completion_source_binding")
    source_binding_digest = None
    if not source_binding_present:
        # Version 2.3.3 first emitted the non-empty normal-legacy digest but did
        # not persist the structured revision binding.  Keep this migration
        # deliberately limited to its exact checkpoint-limit downgrade shape
        # and a revision token already bound into the immutable task label.
        revision_match = re.fullmatch(r"R-([0-9]+)", specification_revision)
        revision_token = f"r{revision_match.group(1)}" if revision_match else None
        task_tokens = re.split(r"[^A-Za-z0-9]+", milestone)
        if (
            request.get("recovery_capability_unavailable") != "checkpoint byte limit exceeded"
            or revision_token is None
            or revision_token not in task_tokens
        ):
            raise RunnerError("root completion audit legacy revision binding is unavailable")
    elif source_binding is None:
        raise RunnerError("root completion audit legacy source binding is explicitly unavailable")
    else:
        expected_source = root_completion_source_binding(
            specification_revision=specification_revision,
            milestone=milestone,
            allowed_set_digest=allowed_set_digest,
            lease_kind="normal-legacy",
            run_id=run_dir.name,
        )
        if source_binding != expected_source:
            raise RunnerError("root completion audit legacy source binding drifted")
        source_binding_digest = sha256_bytes(_canonical_json_bytes(expected_source))

    activation_path = run_dir / "activate.json"
    activated_receipt_path = run_dir / "dispatch-activated-receipt.json"
    if not activation_path.is_file() or not activated_receipt_path.is_file():
        raise RunnerError("root completion audit requires legacy activation evidence")
    _require_private_run_path_identity(run_dir, run_dir.name)
    activation = read_json(activation_path)
    activated_receipt = read_json(activated_receipt_path)
    terminal_receipt = public_receipt(run_dir)
    codex_pid = activation.get("codex_pid")
    codex_identity = activation.get("codex_process_identity")
    if not isinstance(codex_pid, int) or codex_pid <= 0 or not isinstance(codex_identity, str):
        raise RunnerError("root completion audit legacy activation identity is malformed")
    for receipt, expected_status, stopped in (
        (activated_receipt, "running", False),
        (terminal_receipt, "failed", True),
    ):
        if (
            receipt.get("status") != expected_status
            or receipt.get("activated") is not True
            or receipt.get("lease_id") != request.get("lease_id")
            or receipt.get("task_name") != milestone
            or receipt.get("agent_name") != request.get("profile", {}).get("name")
            or receipt.get("codex_pid") != codex_pid
            or receipt.get("codex_process_identity") != codex_identity
            or receipt.get("process_tree_stopped") is not stopped
            or receipt.get("root_completion_source_binding_digest")
            != source_binding_digest
        ):
            raise RunnerError("root completion audit legacy process evidence drifted")


def record_root_completion_authorization_run(args: argparse.Namespace) -> int:
    """Persist the privacy-safe T-004 audit only after exact terminal vacancy."""
    run_dir = resolve_run_reference(args.run_dir)
    request = read_json(run_dir / "request.json")
    registry = recovery_registry_for_request(request)
    lease_id = request.get("lease_id")
    if registry is None or not isinstance(lease_id, str):
        raise RunnerError("root completion audit requires an implementation lifecycle")
    state = registry.state()
    if (
        state.get("lease") is not None
        or state.get("outbox") is not None
        or state.get("quarantine") is not None
    ):
        raise RunnerError("root completion audit requires exact registry vacancy")
    lease_history = [
        event
        for event in state.get("history", [])
        if event.get("lease_id") == lease_id
    ]
    contained_history = [
        event
        for event in lease_history
        if event.get("event") == "contained-terminal-released"
    ]
    contained_releases = [
        event
        for event in contained_history
        if event.get("terminal_success") is False
        and event.get("handoff_digest") is None
        and event.get("outbox_digest") is None
    ]
    legacy_history = [
        event
        for event in lease_history
        if event.get("event") == "legacy-terminal-released"
    ]
    if request.get("task_name") != args.milestone:
        raise RunnerError("root completion audit milestone drifted")
    legacy_mode = (
        request.get("recovery_preflight") is None
        and request.get("recovery_target") is False
    )
    if not legacy_mode:
        if len(contained_releases) != 1:
            raise RunnerError("root completion audit requires one contained no-handoff terminal release")
        release = contained_releases[0]
        if release.get("allowed_set_digest") != args.allowed_set_digest:
            raise RunnerError("root completion audit allowed scope drifted")
        preflight = request.get("recovery_preflight") or {}
        if preflight.get("specification_revision") != args.specification_revision:
            raise RunnerError("root completion audit specification revision drifted")
    else:
        if (
            len(legacy_history) != 1
            or legacy_history[0].get("success") is not False
            or len(lease_history) != 1
        ):
            raise RunnerError("root completion audit requires one exact legacy failure release")
        _validate_legacy_root_completion_release(
            run_dir=run_dir,
            request=request,
            release=legacy_history[0],
            specification_revision=args.specification_revision,
            milestone=args.milestone,
            allowed_set_digest=args.allowed_set_digest,
        )
    record = root_completion_authorization_record(
        specification_revision=args.specification_revision,
        milestone=args.milestone,
        allowed_set_digest=args.allowed_set_digest,
        diff_attribution_digest=args.diff_attribution_digest,
    )
    path = run_dir / "root-completion-authorized.json"
    if path.is_file():
        if read_json(path) != record:
            raise RunnerError("root completion audit replay binding drifted")
    try:
        durable_write_private_json(
            path,
            record,
            fault=getattr(args, "durability_fault", None),
        )
    except (OSError, RecoveryStateError) as exc:
        raise RunnerError(f"durable root completion audit failed closed: {exc}") from exc
    continuation = automatic_continuation_record(
        root_completion_audit=record,
        requested_action=getattr(args, "continuation_action", "run"),
    )
    continuation_path = run_dir / "automatic-continuation.json"
    if continuation_path.is_file() and read_json(continuation_path) != continuation:
        raise RunnerError("automatic continuation replay binding drifted")
    try:
        durable_write_private_json(
            continuation_path,
            continuation,
            fault=getattr(args, "durability_fault", None),
        )
    except (OSError, RecoveryStateError) as exc:
        raise RunnerError(f"durable automatic continuation failed closed: {exc}") from exc
    print(json.dumps({**record, "continuation": continuation}, ensure_ascii=False, indent=2))
    return 0


def authorize_recovery_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    checkpoint_path = Path(args.checkpoint_file).expanduser().resolve()
    prompt_file_value = getattr(args, "prompt_file", None)
    prompt_path = Path(prompt_file_value).expanduser() if prompt_file_value else None
    staged_snapshot_id = getattr(args, "prompt_snapshot_id", None)
    staged_prompt_sha256 = getattr(args, "prompt_sha256", None)
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not repo.is_dir() or not checkpoint_path.is_file():
        raise RunnerError("recovery authorization requires an existing repo and checkpoint")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RunnerError("reserved recovery run directory must be absent or empty")
    lease_id = validate_lease_id("openbuild_implementation_fast", args.lease_id)
    if lease_id is None:
        raise RunnerError("recovery target lease ID is required")
    setattr(args, "_project_runtime_claim", run_dir.name)
    try:
        checkpoint = read_json(checkpoint_path)
        project_lane = resolve_project_lane_recovery_authorization(
            args,
            repo=repo,
            checkpoint=checkpoint,
        )
        registry = recovery_registry_for_agent(
            "openbuild_implementation_fast",
            repo,
            state_root=(
                Path(project_lane["recovery_root"])
                if project_lane is not None
                else None
            ),
        )
        if registry is None:
            raise RecoveryStateError("implementation recovery registry is unavailable")
        state = registry.state()
        existing = state.get("lease")
        if isinstance(existing, dict):
            plan = existing.get("plan", {})
            if (
                existing.get("lease_id") != lease_id
                or existing.get("lease_kind") != "recovery-target"
                or plan.get("run_id") != run_dir.name
                or existing.get("source_state_id") != checkpoint.get("source_state_id")
            ):
                raise RecoveryStateError("workspace is occupied by another recovery lifecycle")
            if staged_snapshot_id or staged_prompt_sha256:
                if (
                    staged_snapshot_id != plan.get("prompt_snapshot_id")
                    or staged_prompt_sha256 != plan.get("prompt_sha256")
                ):
                    raise RecoveryStateError("recovery prompt replay binding drifted")
            elif prompt_path is not None:
                replay_prompt = _read_stable_external_prompt(repo, prompt_path)
                if sha256_bytes(replay_prompt) != plan.get("prompt_sha256"):
                    raise RecoveryStateError("recovery prompt replay binding drifted")
            read_owner_prompt_snapshot(
                registry, plan["prompt_snapshot_id"], plan["prompt_sha256"]
            )
            output = {
                "event": "recovery-target-reserved",
                "lease_id": lease_id,
                "grant_id": existing.get("grant_id"),
                "target_milestone": existing.get("target_milestone"),
                "allowed_set_digest": existing.get("allowed_set_digest"),
                "reconstructed": True,
            }
        else:
            if staged_snapshot_id or staged_prompt_sha256:
                if not staged_snapshot_id or not staged_prompt_sha256:
                    raise RunnerError("owner prompt snapshot binding is incomplete")
                read_owner_prompt_snapshot(
                    registry, staged_snapshot_id, staged_prompt_sha256
                )
                prompt_binding = {
                    "prompt_snapshot_id": staged_snapshot_id,
                    "prompt_sha256": staged_prompt_sha256,
                }
            else:
                if prompt_path is None or not prompt_path.is_file():
                    raise RunnerError("prompt-identity-unstable; use owner-private staging API")
                prompt_binding = acquire_owner_prompt_snapshot(repo, prompt_path, registry)
            registry.initialize()
            checkpoint = registry.revalidate_checkpoint(checkpoint)
            grant = registry.grant_authorization(
                checkpoint,
                user_action_digest=args.user_action_digest,
                specification_revision=args.specification_revision,
                prompt_snapshot_id=prompt_binding["prompt_snapshot_id"],
                prompt_sha256=prompt_binding["prompt_sha256"],
            )
            registry.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": lease_id,
                    "run_id": run_dir.name,
                    "prompt_snapshot_id": prompt_binding["prompt_snapshot_id"],
                    "prompt_sha256": prompt_binding["prompt_sha256"],
                    "launch_token": secrets.token_hex(32),
                    "provider_plan_id": uuid.uuid4().hex,
                    "ipc_plan_id": uuid.uuid4().hex,
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                },
            )
            output = {
                "event": "recovery-target-reserved",
                "lease_id": lease_id,
                "reconstructed": False,
                "authorization": grant,
            }
    except RecoveryStateError as exc:
        raise RunnerError(f"recovery authorization failed closed: {exc}") from exc
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def classify_public_failure(
    *,
    evidence: Mapping[str, Any],
    result_error: str | None,
    exit_record: Mapping[str, Any],
    status: str,
    codex_exit_status: str,
) -> str | None:
    """Project private diagnostic detail onto one closed public classification."""
    if status != "failed":
        return None
    if evidence.get("failure_message"):
        return "agent-terminal-failure"
    if evidence.get("event_error"):
        return "event-stream-invalid"
    if result_error:
        return "result-evidence-invalid"
    if exit_record.get("failure_message"):
        return "runner-failure"
    if evidence.get("completed") and codex_exit_status != "valid":
        return "codex-exit-evidence-invalid"
    return "terminal-record-missing"


def public_receipt(run_dir: Path) -> dict[str, Any]:
    request = read_json(run_dir / "request.json")
    profile = request["profile"]
    activation = (
        read_json(run_dir / "activate.json")
        if (run_dir / "activate.json").is_file()
        else {}
    )
    exit_record = read_json(run_dir / "exit.json") if (run_dir / "exit.json").is_file() else None
    worker = read_json(run_dir / "worker.json") if (run_dir / "worker.json").is_file() else {}
    codex_process = read_json(run_dir / "codex.json") if (run_dir / "codex.json").is_file() else {}
    if not worker and exit_record and exit_record.get("worker_pid"):
        worker = {
            "pid": exit_record.get("worker_pid"),
            "identity": exit_record.get("worker_process_identity"),
            "process_group_id": exit_record.get("worker_process_group_id"),
        }
    if not codex_process and exit_record and exit_record.get("codex_pid"):
        codex_process = {
            "pid": exit_record.get("codex_pid"),
            "identity": exit_record.get("codex_process_identity"),
            "process_group_id": exit_record.get("codex_process_group_id"),
        }
    spawn_record = (
        read_json(run_dir / "codex-spawn.json")
        if (run_dir / "codex-spawn.json").is_file()
        else {}
    )
    codex_spawn_unconfirmed = False
    if not codex_process and spawn_record:
        if (
            spawn_record.get("state") == "started"
            and spawn_record.get("pid")
            and spawn_record.get("identity")
        ):
            codex_process = {
                "pid": spawn_record.get("pid"),
                "identity": spawn_record.get("identity"),
                "process_group_id": spawn_record.get("process_group_id"),
            }
        else:
            codex_spawn_unconfirmed = True
    evidence = read_event_evidence(run_dir / "events.jsonl")
    worker_state = process_record_state(worker)
    codex_state = "unknown" if codex_spawn_unconfirmed else process_record_state(codex_process)
    process_records = [
        record
        for record in (worker, codex_process)
        if int(record.get("pid") or 0) > 0
    ]
    process_tree_stopped = (
        bool(process_records)
        and not codex_spawn_unconfirmed
        and all(process_tree_record_state(record) == "stopped" for record in process_records)
    )
    if (run_dir / "guardian-ready.json").is_file():
        guardian_zero = False
        try:
            secret = _guardian_secret(run_dir)
            ready = read_guardian_message(
                run_dir / "guardian-ready.json",
                secret,
                "guardian-ready",
            )
            if (run_dir / "guardian-zero.json").is_file():
                zero = read_guardian_message(
                    run_dir / "guardian-zero.json",
                    secret,
                    "guardian-zero",
                )
                guardian_zero = (
                    zero.get("guardian_id") == ready.get("guardian_id")
                    and zero.get("populated") is False
                    and zero.get("identity_verified") is True
                )
        except RunnerError:
            guardian_zero = False
        process_tree_stopped = process_tree_stopped and guardian_zero
    if exit_record:
        if (
            exit_record.get("startup_process_stopped") is True
            and not (run_dir / "guardian-ready.json").is_file()
        ):
            process_tree_stopped = True
        elif (
            exit_record.get("startup_process_stopped") is False
            and codex_spawn_unconfirmed
        ):
            process_tree_stopped = False
    result_error = final_result_error(run_dir / "result.md") if evidence["completed"] else None
    if (
        result_error is None
        and evidence["completed"]
        and profile.get("name", "").startswith("openbuild_search_")
    ):
        expected_fingerprint = request.get("discovery_fingerprint")
        if not isinstance(expected_fingerprint, dict):
            result_error = "discovery result lacks an owner fingerprint"
        else:
            try:
                validate_discovery_result(
                    run_dir / "result.md",
                    repo=Path(request["repo"]),
                    expected_public=expected_fingerprint,
                )
            except DiscoveryContractError as exc:
                result_error = str(exc)
    codex_exit_code, codex_exit_status = codex_exit_evidence_status(
        run_dir,
        expected_pid=codex_process.get("pid"),
        expected_identity=codex_process.get("identity"),
    )
    result_status = result_evidence_status(run_dir / "result.md")
    if evidence["completed"] and result_error is not None and result_status == "valid":
        result_status = "invalid"

    if exit_record is not None and not process_tree_stopped:
        status = "running"
    elif exit_record is not None:
        status = (
            "completed"
            if (
                exit_record.get("success") is True
                and evidence["completed"]
                and result_error is None
                and codex_exit_status == "valid"
                and codex_exit_code == 0
            )
            else "failed"
        )
    else:
        status = "failed" if process_tree_stopped else "running"

    structured_errors = list(evidence.get("structured_errors", []))
    structured_stderr_valid = True
    if not evidence.get("turn_started"):
        stderr_errors, structured_stderr_valid = _read_structured_stderr(
            run_dir / "stderr.log"
        )
        structured_errors.extend(stderr_errors)
    evidence["structured_stderr_valid"] = structured_stderr_valid
    transport_failure_reason = None
    if (
        status == "failed"
        and process_tree_stopped
        and bool(codex_process.get("pid"))
        and profile.get("name") == "openbuild_search_separate"
        and profile.get("model") == "gpt-5.3-codex-spark"
        and request.get("search_fallback_source") is None
        and search_availability_event_stream_is_eligible(
            evidence,
            exit_record=exit_record,
            result_status=result_status,
            codex_exit_status=codex_exit_status,
            codex_exit_code=codex_exit_code,
        )
    ):
        transport_failure_reason = classify_search_availability_failure(
            structured_errors,
            exact_model="gpt-5.3-codex-spark",
        )
    fallback_binding = request.get("search_fallback_binding")
    if (
        request.get("search_fallback_source") is None
        or not isinstance(fallback_binding, dict)
    ):
        fallback_binding = {}

    return {
        "schema_version": SCHEMA_VERSION,
        "run_handle": public_run_handle(run_dir),
        "status": status,
        "dispatch_method": "codex-exec-explicit-model",
        "dispatch_result": "selected" if status in {"running", "completed"} else "failed",
        "agent_name": profile["name"],
        "task_name": request["task_name"],
        "lease_id": request.get("lease_id"),
        "activated": bool(activation),
        "activated_at": activation.get("activated_at"),
        "observation_started_at": activation.get("observation_started_at"),
        "observation_deadline_at": activation.get("observation_deadline_at"),
        "root_completion_source_binding_digest": activation.get(
            "root_completion_source_binding_digest"
        ),
        "configured_model": profile["model"],
        "model_reasoning_effort": profile["reasoning_effort"],
        "observed_agent": profile["name"] if status == "completed" else None,
        "observed_model": profile["model"] if status == "completed" else None,
        "sandbox": profile["sandbox"],
        "auth_mode": request["auth_mode"],
        "prompt_source_classification": "owner-private-snapshot",
        "prompt_sha256": request.get("prompt_sha256"),
        "instructions_sha256": (request.get("profile_descriptor") or {}).get(
            "instructions_sha256"
        ),
        "profile_descriptor_sha256": request.get("profile_descriptor_sha256"),
        "transport_failure_reason": transport_failure_reason
        or fallback_binding.get("reason"),
        "search_fallback_source_digest": fallback_binding.get("source_handle_sha256"),
        "search_fallback_profile_sequence_sha256": fallback_binding.get(
            "profile_sequence_sha256"
        ),
        "worker_pid": worker.get("pid"),
        "worker_process_identity": worker.get("identity"),
        "worker_process_group_id": worker.get("process_group_id"),
        "worker_process_state": worker_state,
        "codex_pid": codex_process.get("pid"),
        "codex_process_identity": codex_process.get("identity"),
        "codex_process_group_id": codex_process.get("process_group_id"),
        "codex_process_state": codex_state,
        "codex_started": bool(codex_process.get("pid")),
        "codex_spawn_attempted": bool(spawn_record or codex_process.get("pid")),
        "thread_id": evidence["thread_id"],
        "terminal_event": evidence["terminal_event"],
        "codex_exit_evidence": codex_exit_status,
        "codex_exit_code": codex_exit_code,
        "result_evidence": result_status,
        "cancelled": bool((exit_record or {}).get("cancelled")),
        "completion_recovered_during_cancel": bool(
            (exit_record or {}).get("completion_recovered_during_cancel")
        ),
        "process_tree_stopped": process_tree_stopped,
        "selection_evidence": (
            "explicit -m and model_reasoning_effort argv accepted through turn.completed"
            if status == "completed"
            else (
                "explicit -m and model_reasoning_effort argv recorded; terminal completion pending"
                if status == "running"
                else "explicit selection did not produce an accepted turn.completed"
            )
        ),
        "failure_message": classify_public_failure(
            evidence=evidence,
            result_error=result_error,
            exit_record=exit_record or {},
            status=status,
            codex_exit_status=codex_exit_status,
        ),
        "usage": evidence["usage"],
    }


def apply_preboundary_guardian_failure(
    registry: RecoveryRegistry,
    lease_id: str,
    containment_plan: Mapping[str, Any],
    guardian_receipt: Mapping[str, Any],
    *,
    run_dir: Path,
    runner_log: Any,
) -> tuple[Any, str]:
    if guardian_receipt.get("boundary_committed") is True:
        raise RunnerError("containment guardian failed after the durable process boundary")
    if (
        guardian_receipt.get("tree_empty") is not True
        or guardian_receipt.get("no_user_code") is not True
        or guardian_receipt.get("cleanup_error")
    ):
        raise RunnerError("pre-boundary containment teardown is unproven")
    cause = str(guardian_receipt.get("failure") or "containment-provider-unavailable")
    if containment_plan.get("recovery_target") is True:
        registry.fail_recovery_target_before_boundary(
            lease_id,
            cause,
            {"tree_empty": True, "no_user_code": True},
        )
        raise RunnerError("recovery target containment failed before process binding")
    registry.containment_failed_before_boundary(lease_id, cause)
    registry.prove_fallback_teardown(
        lease_id,
        {"tree_empty": True, "no_user_code": True},
    )
    registry.claim_normal_fallback(
        lease_id,
        str(containment_plan["fallback_token"]),
    )
    return _spawn_worker_process(run_dir, runner_log, contained=False), "fallback"


def _start_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    prompt_file_value = getattr(args, "prompt_file", None)
    prompt_file = Path(prompt_file_value).expanduser() if prompt_file_value else None
    staged_snapshot_id = getattr(args, "prompt_snapshot_id", None)
    staged_prompt_sha256 = getattr(args, "prompt_sha256", None)
    search_fallback_source = getattr(args, "search_fallback_source", None)
    expected_map_sha256 = getattr(args, "expected_map_sha256", None)
    if not repo.is_dir():
        raise RunnerError(f"repository/workspace directory does not exist: {repo}")
    if bool(search_fallback_source) != bool(expected_map_sha256):
        raise RunnerError("search fallback source and expected map SHA-256 must be provided together")
    if search_fallback_source and (
        prompt_file is not None or staged_snapshot_id or staged_prompt_sha256
    ):
        raise RunnerError("search fallback reuses the source prompt; no replacement prompt is allowed")
    if search_fallback_source and args.agent != "openbuild_search_balanced":
        raise RunnerError("search availability fallback target must be openbuild_search_balanced")
    lease_id = validate_lease_id(args.agent, args.lease_id)
    allowed_files, specification_revision, recovery_target_milestone = validate_recovery_start_options(
        args.agent,
        getattr(args, "allowed_file", None),
        getattr(args, "specification_revision", None),
        getattr(args, "recovery_target_milestone", None),
    )
    run_dir = (
        Path(args.run_dir).expanduser().resolve()
        if args.run_dir
        else default_run_dir().resolve()
    )
    setattr(args, "_project_runtime_claim", run_dir.name)
    project_lane = resolve_project_lane_start(
        args,
        agent_name=args.agent,
        repo=repo,
        allowed_files=allowed_files,
    )
    if project_lane is not None:
        setattr(
            args,
            "_project_lane_runtime_request",
            {"project_lane": project_lane},
        )
        setattr(
            args,
            "_project_lane_runtime_release_owned",
            getattr(args, "_project_runtime_claim_acquired", False) is True,
        )
    registry = recovery_registry_for_agent(
        args.agent,
        repo,
        state_root=(
            Path(project_lane["recovery_root"])
            if project_lane is not None
            else None
        ),
    )
    registry_lease_id = lease_id
    recovery_target_lease: dict[str, Any] | None = None
    if registry is not None and registry_lease_id is not None:
        try:
            existing = registry.state().get("lease")
        except RecoveryStateError as exc:
            raise RunnerError(f"workspace recovery registry rejected start: {exc}") from exc
        if existing is not None:
            if (
                isinstance(existing, dict)
                and existing.get("lease_id") == registry_lease_id
                and existing.get("lease_kind") == "recovery-target"
                and existing.get("state") == "reserved"
            ):
                recovery_target_lease = existing
            else:
                raise RunnerError("workspace recovery registry rejected start: workspace is not vacant")
    prompt_owner = registry or RecoveryRegistry(repo)
    fallback_source_request: dict[str, Any] | None = None
    if recovery_target_lease is not None:
        target_plan = recovery_target_lease.get("plan", {})
        try:
            task_prompt = read_owner_prompt_snapshot(
                prompt_owner,
                target_plan["prompt_snapshot_id"],
                target_plan["prompt_sha256"],
            )
        except (KeyError, RunnerError) as exc:
            raise RunnerError("reserved recovery target lacks a valid immutable prompt snapshot") from exc
        prompt_binding = {
            "prompt_snapshot_id": target_plan["prompt_snapshot_id"],
            "prompt_sha256": target_plan["prompt_sha256"],
        }
    elif search_fallback_source:
        if not RUN_HANDLE.fullmatch(search_fallback_source):
            raise RunnerError("search fallback source must be an owner-issued run handle")
        source_dir = resolve_run_reference(search_fallback_source)
        fallback_source_request = read_json(source_dir / "request.json")
        prompt_binding = {
            "prompt_snapshot_id": fallback_source_request.get("prompt_snapshot_id"),
            "prompt_sha256": fallback_source_request.get("prompt_sha256"),
        }
        if not all(isinstance(value, str) and value for value in prompt_binding.values()):
            raise RunnerError("search fallback source prompt binding is incomplete")
        task_prompt = read_prompt_snapshot(
            source_dir / "prompt.md",
            prompt_binding["prompt_sha256"],
        )
    else:
        if staged_snapshot_id or staged_prompt_sha256:
            if not staged_snapshot_id or not staged_prompt_sha256:
                raise RunnerError("owner prompt snapshot binding is incomplete")
            prompt_binding = {
                "prompt_snapshot_id": staged_snapshot_id,
                "prompt_sha256": staged_prompt_sha256,
            }
        else:
            if prompt_file is None or not prompt_file.is_file():
                raise RunnerError("prompt-identity-unstable; use owner-private staging API")
            prompt_binding = acquire_owner_prompt_snapshot(repo, prompt_file, prompt_owner)
        task_prompt = read_owner_prompt_snapshot(
            prompt_owner,
            prompt_binding["prompt_snapshot_id"],
            prompt_binding["prompt_sha256"],
        )
    source_prompt = task_prompt.encode("utf-8")

    if run_dir.exists() and any(run_dir.iterdir()):
        raise RunnerError(f"run directory must be absent or empty: {run_dir}")
    ensure_private_run_dir(run_dir)
    review_progress = review_progress_from_args(args)
    review_dispatch_preview = (
        preview_review_dispatch(repo=repo, progress=review_progress)
        if review_progress is not None
        else None
    )

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()
    validate_subscription_configuration(codex_home, repo)
    profile = load_agent_profile(args.agent, repo=repo, codex_home=codex_home)
    discovery_fingerprint: dict[str, Any] | None = None
    discovery_route_binding: dict[str, Any] | None = None
    if profile.name.startswith("openbuild_search_"):
        try:
            current_fingerprint = compute_worktree_fingerprint(repo)
        except DiscoveryContractError as exc:
            raise RunnerError(str(exc)) from exc
        if fallback_source_request is not None:
            expected_fingerprint = fallback_source_request.get("discovery_fingerprint")
            if not isinstance(expected_fingerprint, dict) or current_fingerprint.public != expected_fingerprint:
                raise RunnerError("search fallback source worktree fingerprint drifted")
            discovery_fingerprint = expected_fingerprint
        else:
            discovery_fingerprint = current_fingerprint.public
        profile = discovery_profile_with_fingerprint(profile, discovery_fingerprint)
        if profile.name == "openbuild_search_separate" and not search_fallback_source:
            discovery_route_binding = resolve_discovery_route_binding(
                repo=repo,
                codex_home=codex_home,
                fingerprint=discovery_fingerprint,
            )
            if discovery_route_binding["agents"][0] != profile.name:
                raise RunnerError(
                    "exact Spark profile does not match the effective discovery route source"
                )
    descriptor = profile_descriptor(profile)
    codex_bin = resolve_codex_binary(args.codex_bin)
    environment = scrub_api_credentials(os.environ)
    auth_mode = require_chatgpt_login(codex_bin, environment)
    search_fallback_binding: dict[str, Any] | None = None
    if search_fallback_source:
        search_fallback_binding = prepare_search_fallback_claim(
            source_reference=search_fallback_source,
            expected_map_sha256=expected_map_sha256,
            repo=repo,
            codex_home=codex_home,
            target_profile=profile,
            task_name=args.task_name,
            target_run_dir=run_dir,
        )
    result_file = run_dir / "result.md"
    command = build_codex_command(
        codex_bin=codex_bin,
        profile=profile,
        repo=repo,
        result_file=result_file,
        is_git_repo=is_git_repository(repo),
    )
    effective_prompt(profile, args.task_name, task_prompt)
    review_dispatch_binding: dict[str, Any] | None = None
    if review_dispatch_preview is not None:
        review_entry = _review_dispatch_entry(
            run_id=run_dir.name,
            agent_name=profile.name,
            task_name=args.task_name,
            progress=review_dispatch_preview["progress"],
            decision=review_dispatch_preview["decision"],
        )
        review_dispatch_binding = {
            "schema": review_entry["schema"],
            "entry_digest": review_entry["entry_digest"],
            "progress_digest": review_entry["progress"]["progress_digest"],
            "decision": review_entry["decision"],
        }
    prompt_snapshot = run_dir / "prompt.md"
    request = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "agent_name": profile.name,
        "task_name": args.task_name.strip(),
        "lease_id": lease_id,
        "repo": str(repo),
        "codex_home": str(codex_home),
        "prompt_source": str(prompt_file) if prompt_file is not None else None,
        "prompt_file": str(prompt_snapshot),
        "prompt_snapshot_id": prompt_binding["prompt_snapshot_id"],
        "prompt_sha256": prompt_binding["prompt_sha256"],
        "profile_source": str(profile.source),
        "profile": {
            "name": profile.name,
            "description": profile.description,
            "model": profile.model,
            "reasoning_effort": profile.reasoning_effort,
            "sandbox": profile.sandbox,
            "developer_instructions": profile.developer_instructions,
        },
        "profile_descriptor": descriptor["descriptor"],
        "profile_descriptor_sha256": descriptor["sha256"],
        "discovery_fingerprint": discovery_fingerprint,
        "discovery_route_binding": discovery_route_binding,
        "search_fallback_source": search_fallback_source,
        "search_fallback_binding": search_fallback_binding,
        "review_progress": review_progress,
        "review_dispatch": review_dispatch_binding,
        "auth_mode": auth_mode,
        "activation_timeout": args.activation_timeout,
        "command": command,
        "recovery_preflight": None,
        "recovery_parent_checkpoint": None,
        "recovery_capability_unavailable": None,
        "lifecycle_allowed_set_digest": (
            nonrecovery_allowed_set_digest(allowed_files) if registry is not None else ""
        ),
        "root_completion_source_binding": None,
        "recovery_target": False,
        "containment_plan": None,
        "project_lane": project_lane,
        "project_runtime_claim": (
            run_dir.name
            if project_lane is not None
            else None
        ),
    }

    if registry is not None and registry_lease_id is not None:
        try:
            registry_state = registry.initialize()
        except RecoveryStateError as exc:
            raise RunnerError(f"workspace recovery registry rejected start: {exc}") from exc
        existing_lease = registry_state.get("lease")
        if existing_lease is not None:
            if (
                isinstance(existing_lease, dict)
                and existing_lease.get("lease_id") == registry_lease_id
                and existing_lease.get("lease_kind") == "recovery-target"
                and existing_lease.get("state") == "reserved"
            ):
                recovery_target_lease = existing_lease
                target_plan = existing_lease.get("plan", {})
                if (
                    target_plan.get("run_id") != run_dir.name
                    or target_plan.get("prompt_snapshot_id") != request["prompt_snapshot_id"]
                    or target_plan.get("prompt_sha256") != request["prompt_sha256"]
                    or existing_lease.get("target_milestone") != request["task_name"]
                ):
                    raise RunnerError("reserved recovery target run, prompt or milestone binding drifted")
                if not (allowed_files and specification_revision and recovery_target_milestone):
                    raise RunnerError("reserved recovery target requires structured next-checkpoint options")
                parent_checkpoint = registry.public_checkpoint_for_source(
                    existing_lease["source_state_id"]
                )
                if parent_checkpoint.get("specification_revision") != specification_revision:
                    raise RunnerError("reserved recovery target specification revision drifted")
                registry.assert_checkpoint_allowed_paths(parent_checkpoint, allowed_files)
                request["recovery_parent_checkpoint"] = parent_checkpoint
                request["lifecycle_allowed_set_digest"] = existing_lease["allowed_set_digest"]
                request["recovery_target"] = True
            else:
                raise RunnerError("workspace recovery registry rejected start: workspace is not vacant")
        if allowed_files and specification_revision and recovery_target_milestone:
            source_id = sha256_bytes(
                f"{registry_lease_id}\0{run_dir.name}\0{request['prompt_sha256']}".encode("utf-8")
            )
            try:
                request["recovery_preflight"] = registry.prepare_source_checkpoint(
                    source_id=source_id,
                    source_lease_id=registry_lease_id,
                    source_milestone=request["task_name"],
                    target_milestone=recovery_target_milestone,
                    allowed_paths=allowed_files,
                    specification_revision=specification_revision,
                )
            except RecoveryStateError as exc:
                request["recovery_capability_unavailable"] = str(exc)
    if project_lane is not None and request.get("recovery_preflight") is None:
        raise RunnerError(
            "project lane dispatch requires a recovery-capable contained source boundary"
        )
    if recovery_target_lease is not None:
        target_plan = recovery_target_lease["plan"]
        request["containment_plan"] = {
            "guardian_id": uuid.uuid4().hex,
            "provider_plan_id": target_plan["provider_plan_id"],
            "ipc_plan_id": target_plan["ipc_plan_id"],
            "contained_launch_token": target_plan["launch_token"],
            "fallback_token": None,
            "recovery_target": True,
        }
    elif request.get("recovery_preflight") is not None:
        request["lifecycle_allowed_set_digest"] = request["recovery_preflight"][
            "allowed_set_digest"
        ]
        request["containment_plan"] = {
            "guardian_id": uuid.uuid4().hex,
            "provider_plan_id": uuid.uuid4().hex,
            "ipc_plan_id": uuid.uuid4().hex,
            "contained_launch_token": secrets.token_hex(32),
            "fallback_token": secrets.token_hex(32),
            "recovery_target": False,
        }
    if (
        registry is not None
        and allowed_files
        and specification_revision
        and recovery_target_milestone
    ):
        request["root_completion_source_binding"] = root_completion_source_binding(
            specification_revision=specification_revision,
            milestone=request["task_name"],
            allowed_set_digest=request["lifecycle_allowed_set_digest"],
            lease_kind=(
                "recovery-target"
                if recovery_target_lease is not None
                else (
                    "normal-contained"
                    if request.get("recovery_preflight") is not None
                    else "normal-legacy"
                )
            ),
            run_id=run_dir.name,
        )
    try:
        durable_write_private_bytes(prompt_snapshot, source_prompt)
        durable_write_private_json(run_dir / "request.json", request)
    except (OSError, RecoveryStateError) as exc:
        raise RunnerError(f"durable run prompt binding failed closed: {exc}") from exc

    if review_dispatch_preview is not None:
        review_dispatch = commit_review_dispatch(
            repo=repo,
            run_id=run_dir.name,
            agent_name=profile.name,
            task_name=request["task_name"],
            preview=review_dispatch_preview,
        )
        if review_dispatch != review_dispatch_binding:
            raise RunnerError("review dispatch ledger binding drifted after request commit")
    if (
        registry is not None
        and registry_lease_id is not None
        and recovery_target_lease is None
    ):
        preflight = request.get("recovery_preflight")
        reservation_acquired = False
        try:
            registry.reserve_normal(
                registry_lease_id,
                allowed_set_digest=request["lifecycle_allowed_set_digest"],
                recovery_capable=preflight is not None,
                source_state_id=(preflight or {}).get("source_state_id"),
                run_id=run_dir.name,
                prompt_snapshot_id=request["prompt_snapshot_id"],
                prompt_sha256=request["prompt_sha256"],
                containment_plan=request.get("containment_plan"),
            )
            reservation_acquired = True
            if preflight is not None:
                registry.bind_reserved_source_snapshot(registry_lease_id, preflight)
        except RecoveryStateError as exc:
            if reservation_acquired:
                try:
                    registry.release_unactivated_reservation(registry_lease_id)
                except RecoveryStateError as release_exc:
                    raise RunnerError(
                        "workspace recovery registry rejected the reserved source boundary "
                        f"and retained its lease: {exc}; release failed: {release_exc}"
                    ) from exc
            raise RunnerError(f"workspace recovery registry rejected start: {exc}") from exc

    if registry is not None:
        try:
            prompt_owner.mark_prompt_snapshot_released(
                request["prompt_snapshot_id"],
                request["prompt_sha256"],
            )
            garbage_collect_owner_prompt_snapshots(prompt_owner)
        except (OSError, RunnerError, RecoveryStateError) as exc:
            if registry_lease_id is not None and recovery_target_lease is None:
                try:
                    registry.release_unactivated_reservation(registry_lease_id)
                except RecoveryStateError as release_exc:
                    raise RunnerError(
                        "owner prompt release marker failed and the unactivated lease was retained: "
                        f"{exc}; release failed: {release_exc}"
                    ) from exc
            raise RunnerError(f"owner prompt release marker failed before spawn: {exc}") from exc
    else:
        garbage_collect_owner_prompt_snapshots(prompt_owner)

    worker: Any | None = None
    worker_record: dict[str, Any] = {}
    launch_mode = "unstarted"
    fallback_bind_attempted = False
    fallback_bind_verified = False
    setattr(args, "_project_lane_startup_cleanup", True)
    try:
        runner_log = open_private_binary(run_dir / "runner.log", append=True)
        try:
            containment_plan = request.get("containment_plan")
            if (
                registry is not None
                and registry_lease_id is not None
                and isinstance(containment_plan, dict)
            ):
                secret = secrets.token_bytes(32)
                atomic_write_bytes(run_dir / "guardian.key", secret)
                write_guardian_message(
                    run_dir / "guardian-request.json",
                    secret,
                    "guardian-request",
                    {
                        "guardian_id": containment_plan["guardian_id"],
                        "provider_plan_id": containment_plan["provider_plan_id"],
                        "ipc_plan_id": containment_plan["ipc_plan_id"],
                        "agent_name": profile.name,
                        "repo": str(repo),
                        "lease_id": registry_lease_id,
                        "allowed_set_digest": request["lifecycle_allowed_set_digest"],
                        "boundary_timeout": max(600.0, float(args.activation_timeout)),
                    },
                )
                if containment_plan.get("recovery_target") is True:
                    registry.claim_launch(
                        registry_lease_id,
                        containment_plan["contained_launch_token"],
                    )
                else:
                    registry.claim_contained_launch(
                        registry_lease_id,
                        containment_plan["contained_launch_token"],
                    )
                guardian = spawn_containment_guardian(run_dir, runner_log)
                disposition, guardian_receipt = await_guardian_launch(run_dir, secret, guardian)
                if disposition == "ready":
                    candidate_worker = guardian_receipt.get("worker")
                    if not isinstance(candidate_worker, dict):
                        raise RunnerError("guardian launch receipt lacks the worker creation receipt")
                    worker_record = dict(candidate_worker)
                    disposition, precommit_receipt = await_guardian_precommit(
                        run_dir,
                        secret,
                        guardian,
                        guardian_receipt,
                    )
                    if disposition == "failed":
                        guardian_receipt = precommit_receipt
                    else:
                        bound_state = registry.state()
                        bound_lease = bound_state.get("lease")
                        bound_plan = (
                            bound_lease.get("plan", {})
                            if isinstance(bound_lease, dict)
                            and bound_lease.get("lease_kind") == "recovery-target"
                            else bound_lease.get("containment_plan", {})
                            if isinstance(bound_lease, dict)
                            else {}
                        )
                        provider_receipt = (
                            bound_lease.get("provider_receipt", {})
                            if isinstance(bound_lease, dict)
                            else {}
                        )
                        if (
                            bound_state.get("digest") != precommit_receipt.get("registry_digest")
                            or not isinstance(bound_lease, dict)
                            or bound_lease.get("lease_id") != registry_lease_id
                            or bound_lease.get("state") != "process-bound-unactivated"
                            or bound_lease.get("allowed_set_digest")
                            != request["lifecycle_allowed_set_digest"]
                            or bound_lease.get("process_receipt") != worker_record
                            or bound_plan.get("provider_plan_id")
                            != containment_plan["provider_plan_id"]
                            or bound_plan.get("ipc_plan_id") != containment_plan["ipc_plan_id"]
                            or guardian_receipt.get("provider_plan_id")
                            != containment_plan["provider_plan_id"]
                            or guardian_receipt.get("ipc_plan_id")
                            != containment_plan["ipc_plan_id"]
                            or precommit_receipt.get("provider_plan_id")
                            != containment_plan["provider_plan_id"]
                            or precommit_receipt.get("ipc_plan_id")
                            != containment_plan["ipc_plan_id"]
                            or provider_receipt.get("provider_plan_id")
                            != containment_plan["provider_plan_id"]
                            or provider_receipt.get("ipc_plan_id")
                            != containment_plan["ipc_plan_id"]
                            or provider_receipt.get("precommit", {}).get("provider_plan_id")
                            != containment_plan["provider_plan_id"]
                            or provider_receipt.get("precommit", {}).get("ipc_plan_id")
                            != containment_plan["ipc_plan_id"]
                            or provider_receipt.get("precommit", {})
                            .get("precommit_nonce")
                            != precommit_receipt.get("precommit_nonce")
                        ):
                            raise RunnerError(
                                "guardian precommit did not atomically commit the registry boundary"
                            )
                        write_guardian_message(
                            run_dir / "containment-bound.json",
                            secret,
                            "containment-bound",
                            {
                                "guardian_id": containment_plan["guardian_id"],
                                "worker_pid": worker_record["pid"],
                                "worker_identity": worker_record["identity"],
                                "allowed_set_digest": request["lifecycle_allowed_set_digest"],
                                "provider_plan_id": containment_plan["provider_plan_id"],
                                "ipc_plan_id": containment_plan["ipc_plan_id"],
                                "precommit_nonce": precommit_receipt["precommit_nonce"],
                            },
                        )
                        worker = guardian
                        launch_mode = "contained"
                if disposition == "failed":
                    worker, launch_mode = apply_preboundary_guardian_failure(
                        registry,
                        registry_lease_id,
                        containment_plan,
                        guardian_receipt,
                        run_dir=run_dir,
                        runner_log=runner_log,
                    )
            else:
                worker = _spawn_worker_process(run_dir, runner_log, contained=False)
                launch_mode = "legacy"
        finally:
            runner_log.close()
        if launch_mode != "contained":
            worker_identity = process_identity_from_popen(worker)
            if worker_identity is None:
                raise RunnerError("cannot record worker process creation identity")
            setattr(worker, "_openbuild_process_identity", worker_identity)
            worker_record = {
                "pid": worker.pid,
                "identity": worker_identity,
                "process_group_id": worker.pid,
                "started_at": utc_now(),
            }
            atomic_write_json(run_dir / "worker.json", worker_record)
            if registry is not None and registry_lease_id is not None:
                if launch_mode == "fallback":
                    fallback_bind_attempted = True
                    fallback_bound = registry.bind_fallback_process_unactivated(
                        registry_lease_id,
                        process_receipt=worker_record,
                    )
                    fallback_bound_lease = fallback_bound.get("lease")
                    fallback_bound_digest = fallback_bound.get("digest")
                    if (
                        not isinstance(fallback_bound_digest, str)
                        or re.fullmatch(r"[0-9a-f]{64}", fallback_bound_digest) is None
                        or not isinstance(fallback_bound_lease, dict)
                        or fallback_bound_lease.get("lease_id") != registry_lease_id
                        or fallback_bound_lease.get("lease_kind") != "normal-fallback"
                        or fallback_bound_lease.get("recovery_capable") is not False
                        or fallback_bound_lease.get("state")
                        != "ordinary-process-bound-unactivated"
                        or fallback_bound_lease.get("process_receipt") != worker_record
                    ):
                        raise RunnerError(
                            "ordinary fallback process bind did not return its exact durable receipt"
                        )
                    fallback_bind_verified = True
                else:
                    registry.bind_legacy_process_unactivated(
                        registry_lease_id,
                        process_receipt=worker_record,
                    )
        startup_deadline = time.monotonic() + 20.0
        while not (run_dir / "codex.json").is_file():
            worker_state = process_record_state(worker_record)
            if (run_dir / "exit.json").is_file() or worker_state == "stopped":
                raise RunnerError("worker exited before the Codex process became ready")
            if worker_state == "unknown":
                raise RunnerError("worker process identity became unobservable before Codex was ready")
            if time.monotonic() >= startup_deadline:
                raise RunnerError("worker did not publish a Codex process identity within 20 seconds")
            time.sleep(0.05)
        receipt = public_receipt(run_dir)
        if (
            receipt["status"] != "running"
            or receipt.get("activated") is not False
            or not receipt.get("codex_process_identity")
        ):
            raise RunnerError("worker did not publish a valid unactivated running receipt")
        atomic_write_json(run_dir / "dispatch-unactivated-receipt.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except BaseException as exc:
        codex_record: dict[str, Any] = {}
        codex_spawn_attempted = False
        cleanup_errors: list[str] = []
        try:
            if worker is not None:
                terminate_spawned_process(worker, process_group=True, grace_seconds=2.0)
        except BaseException as cleanup_exc:
            cleanup_errors.append(f"worker cleanup: {cleanup_exc or type(cleanup_exc).__name__}")
        codex_path = run_dir / "codex.json"
        spawn_path = run_dir / "codex-spawn.json"
        if codex_path.is_file():
            codex_spawn_attempted = True
            try:
                codex_record = read_json(codex_path)
            except BaseException as artifact_exc:
                cleanup_errors.append(
                    f"Codex artifact read: {artifact_exc or type(artifact_exc).__name__}"
                )
                codex_record = {}
        elif spawn_path.is_file():
            codex_spawn_attempted = True
            try:
                spawn_record = read_json(spawn_path)
                if (
                    spawn_record.get("state") == "started"
                    and spawn_record.get("pid")
                    and spawn_record.get("identity")
                ):
                    codex_record = spawn_record
            except BaseException as artifact_exc:
                cleanup_errors.append(
                    f"Codex spawn artifact read: {artifact_exc or type(artifact_exc).__name__}"
                )
        try:
            if codex_record:
                terminate_process_tree({}, codex_record, 2.0)
        except BaseException as cleanup_exc:
            cleanup_errors.append(f"Codex cleanup: {cleanup_exc or type(cleanup_exc).__name__}")
        try:
            worker_stopped = worker is None or (
                bool(worker_record) and process_record_state(worker_record) == "stopped"
            )
            startup_process_stopped = not cleanup_errors and worker_stopped and (
                (bool(codex_record) and process_tree_record_state(codex_record) == "stopped")
                or not codex_spawn_attempted
            )
        except BaseException as verify_exc:
            cleanup_errors.append(
                f"cleanup verification: {verify_exc or type(verify_exc).__name__}"
            )
            startup_process_stopped = False
        record_error: BaseException | None = None
        if not (run_dir / "exit.json").is_file():
            try:
                startup_exit_code, startup_exit_evidence = codex_exit_evidence_status(
                    run_dir,
                    expected_pid=codex_record.get("pid"),
                    expected_identity=codex_record.get("identity"),
                )
                atomic_write_json(
                    run_dir / "exit.json",
                    {
                        "finished_at": utc_now(),
                        "exit_code": startup_exit_code,
                        "codex_exit_evidence": startup_exit_evidence,
                        "success": False,
                        "terminal_event": None,
                        "failure_message": str(exc) or type(exc).__name__,
                        "cancelled": True,
                        "process_tree_stopped": startup_process_stopped,
                        "startup_process_stopped": startup_process_stopped,
                        "worker_pid": worker_record.get("pid") or getattr(worker, "pid", None),
                        "worker_process_identity": worker_record.get("identity"),
                        "worker_process_group_id": worker_record.get("process_group_id")
                        or getattr(worker, "pid", None),
                        "codex_pid": codex_record.get("pid"),
                        "codex_process_identity": codex_record.get("identity"),
                        "codex_process_group_id": codex_record.get("process_group_id"),
                        "codex_started": bool(codex_record.get("pid")),
                        "cleanup_errors": cleanup_errors,
                    },
                )
            except BaseException as record_exc:
                record_error = record_exc
        if not isinstance(exc, Exception):
            if record_error is not None:
                raise exc from record_error
            raise
        if record_error is not None:
            raise RunnerError(
                f"startup cleanup was attempted but failure receipt could not be written: {record_error}; "
                f"artifacts: {run_dir}"
            ) from record_error
        fallback_launch_quarantined = False
        if registry is not None and registry_lease_id is not None:
            try:
                registry_state = registry.state()
                registry_lease = registry_state.get("lease")
                if isinstance(registry_lease, dict) and (
                    registry_lease.get("state") == "ordinary-fallback-claimed"
                    or (
                        registry_lease.get("state") == "ordinary-process-bound-unactivated"
                        and fallback_bind_attempted
                        and not fallback_bind_verified
                    )
                ):
                    registry.quarantine_fallback_launch(
                        registry_lease_id,
                        (
                            "fallback-process-bind-ambiguous"
                            if fallback_bind_attempted
                            else "fallback-spawn-or-identity-ambiguous"
                        ),
                    )
                    fallback_launch_quarantined = True
            except RecoveryStateError as quarantine_exc:
                raise RunnerError(
                    f"{exc}; ambiguous fallback launch could not be quarantined: {quarantine_exc}"
                ) from exc
        if cleanup_errors:
            raise RunnerError(
                f"{exc}; startup cleanup was not confirmed for {run_dir}: {'; '.join(cleanup_errors)}"
            ) from exc
        if not startup_process_stopped:
            raise RunnerError(
                f"{exc}; startup cleanup is unconfirmed because creation-bound stopped-process "
                f"evidence is unavailable; artifacts: {run_dir}"
            ) from exc
        if (
            registry is not None
            and registry_lease_id is not None
            and not fallback_launch_quarantined
        ):
            try:
                registry_state = registry.state()
                registry_lease = registry_state.get("lease")
                if not isinstance(registry_lease, dict):
                    pass
                elif registry_lease.get("state") in {
                    "reserved",
                    "normal-preflight-reserved",
                    "normal-snapshot-bound",
                }:
                    registry.release_unactivated_reservation(registry_lease_id)
                elif registry_lease.get("recovery_capable") is False:
                    registry.release_legacy_terminal(
                        registry_lease_id,
                        {"success": False, "process_tree_stopped": True},
                    )
                elif registry_lease.get("state") == "process-bound-unactivated":
                    try:
                        registry.containment_failed_before_boundary(
                            registry_lease_id,
                            "startup-failure-after-containment-boundary",
                        )
                    except RecoveryStateError as quarantine_exc:
                        if "quarantined" not in str(quarantine_exc):
                            raise
                else:
                    raise RecoveryStateError(
                        f"startup stopped in retained recovery lifecycle {registry_lease.get('state')}"
                    )
            except RecoveryStateError as release_exc:
                raise RunnerError(
                    f"{exc}; startup stopped but private workspace reservation could not be released: {release_exc}"
                ) from exc
        if (
            project_lane is not None
            and getattr(args, "_project_lane_runtime_release_owned", False)
        ):
            try:
                release_project_lane_runtime(request)
            except RunnerError as release_exc:
                raise RunnerError(
                    f"{exc}; startup stopped but project runtime capacity was retained: "
                    f"{release_exc}"
                ) from exc
        raise RunnerError(f"{exc}; startup process tree stopped; artifacts: {run_dir}") from exc


def start_run(args: argparse.Namespace) -> int:
    """Release project runtime admission when pre-dispatch setup fails."""

    setattr(args, "_project_lane_runtime_request", None)
    setattr(args, "_project_lane_startup_cleanup", False)
    setattr(args, "_project_runtime_claim_acquired", False)
    setattr(args, "_project_lane_runtime_release_owned", False)
    try:
        return _start_run(args)
    except BaseException as exc:
        runtime_request = getattr(
            args,
            "_project_lane_runtime_request",
            None,
        )
        if (
            isinstance(runtime_request, Mapping)
            and not getattr(args, "_project_lane_startup_cleanup", False)
            and getattr(args, "_project_lane_runtime_release_owned", False)
        ):
            try:
                release_project_lane_runtime(runtime_request)
            except RunnerError as release_exc:
                raise RunnerError(
                    f"{exc}; pre-dispatch project runtime capacity was retained: "
                    f"{release_exc}"
                ) from exc
        raise


def communicate_after_activation(
    process: Any,
    *,
    run_dir: Path,
    prompt: bytes,
    process_identity_value: str,
    timeout: float,
) -> None:
    activation_deadline = time.monotonic() + timeout
    while not (run_dir / "activate.json").is_file():
        if process.poll() is not None:
            raise RunnerError(f"codex exec exited before activation with code {process.returncode}")
        if time.monotonic() >= activation_deadline:
            terminate_spawned_process(process, process_group=True)
            raise RunnerError("activation timeout expired before the root released the task prompt")
        time.sleep(0.05)
    activation = read_json(run_dir / "activate.json")
    if (
        int(activation.get("codex_pid") or 0) != process.pid
        or activation.get("codex_process_identity") != process_identity_value
        or process_identity_from_popen(process) != process_identity_value
    ):
        raise RunnerError("activation does not match the live creation-bound Codex process")
    process.communicate(input=prompt)


def await_worker_record(run_dir: Path, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    path = run_dir / "worker.json"
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise RunnerError("root did not publish the worker creation identity")
        time.sleep(0.02)
    record = read_json(path)
    if int(record.get("pid") or 0) != os.getpid():
        raise RunnerError("worker record PID does not match the spawned worker")
    if process_record_state(record) != "running":
        raise RunnerError("worker creation identity cannot be verified before Codex spawn")
    return record


def worker_termination_handler(signum: int, _frame: Any) -> None:
    child = ACTIVE_WORKER_CHILD
    if child is not None and child.poll() is not None:
        return
    if child is None and ACTIVE_WORKER_FINALIZING:
        return
    if child is not None:
        terminate_spawned_process(child, process_group=True, grace_seconds=2.0)
    raise SystemExit(128 + signum)


def spawn_tracked_codex_process(
    command: list[str],
    *,
    stdout: Any,
    stderr: Any,
    environment: Mapping[str, str],
    spawn_marker: Path,
) -> Any:
    global ACTIVE_WORKER_CHILD
    previous_mask: set[signal.Signals] | None = None
    if os.name != "nt" and hasattr(signal, "pthread_sigmask"):
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK,
            {signal.SIGINT, signal.SIGTERM},
        )
    try:
        atomic_write_json(
            spawn_marker,
            {
                "state": "attempting",
                "attempted_at": utc_now(),
                "worker_pid": os.getpid(),
            },
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            env=dict(environment),
            **_background_options(),
        )
        ACTIVE_WORKER_CHILD = process
        identity = process_identity_from_popen(process)
        if identity is None:
            raise RunnerError("cannot record Codex process creation identity")
        setattr(process, "_openbuild_process_identity", identity)
        atomic_write_json(
            spawn_marker,
            {
                "state": "started",
                "started_at": utc_now(),
                "pid": process.pid,
                "identity": identity,
                "process_group_id": process.pid,
                "worker_pid": os.getpid(),
            },
        )
        return process
    finally:
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def worker_run(run_dir: Path) -> int:
    global ACTIVE_WINDOWS_JOB, ACTIVE_WORKER_CHILD, ACTIVE_WORKER_FINALIZING
    ACTIVE_WORKER_FINALIZING = False
    if os.name != "nt":
        os.umask(0o077)
        signal.signal(signal.SIGTERM, worker_termination_handler)
        signal.signal(signal.SIGINT, worker_termination_handler)
    contained_by_guardian = os.environ.get("OPENBUILD_CONTAINED_BY_GUARDIAN") == "1"
    if contained_by_guardian:
        worker_identity = process_identity(os.getpid())
        if worker_identity is None:
            raise RunnerError("contained worker creation identity is unavailable")
        provider = os.environ.get("OPENBUILD_CONTAINMENT_PROVIDER")
        if provider == "linux-cgroup-v2":
            establish_linux_anti_migration_boundary(run_dir, worker_identity)
        elif sys.platform == "linux":
            raise RunnerError("Linux contained worker lacks an anti-migration provider")
        await_worker_containment_gate(
            run_dir,
            expected_pid=os.getpid(),
            expected_identity=worker_identity,
            timeout=600.0,
        )
    await_worker_record(run_dir)
    request = read_json(run_dir / "request.json")
    profile_data = request["profile"]
    profile = AgentProfile(
        name=profile_data["name"],
        description=profile_data["description"],
        model=profile_data["model"],
        reasoning_effort=profile_data["reasoning_effort"],
        sandbox=profile_data["sandbox"],
        developer_instructions=profile_data["developer_instructions"],
        source=Path(request["profile_source"]),
    )
    prompt_file = Path(request["prompt_file"])
    failure_message: str | None = None
    pending_base_exception: BaseException | None = None
    worker_cleanup_errors: list[str] = []
    returncode = 1
    evidence: dict[str, Any] = {"completed": False, "terminal_event": None}
    try:
        task_prompt = read_prompt_snapshot(prompt_file, request["prompt_sha256"])
        prompt = effective_prompt(profile, request["task_name"], task_prompt).encode("utf-8")
        environment = scrub_api_credentials(os.environ)
        environment.update(project_runtime_environment(request))
        validate_subscription_configuration(Path(request["codex_home"]), Path(request["repo"]))
        if os.name == "nt" and ACTIVE_WINDOWS_JOB is None and not contained_by_guardian:
            ACTIVE_WINDOWS_JOB = create_windows_kill_job()
        require_chatgpt_login(request["command"][0], environment)
        with open_private_binary(run_dir / "events.jsonl") as stdout, open_private_binary(
            run_dir / "stderr.log"
        ) as stderr:
            process: Any | None = None
            child_exception: BaseException | None = None
            cleanup_exception: BaseException | None = None
            try:
                process = spawn_tracked_codex_process(
                    request["command"],
                    stdout=stdout,
                    stderr=stderr,
                    environment=environment,
                    spawn_marker=run_dir / "codex-spawn.json",
                )
                codex_identity = getattr(process, "_openbuild_process_identity", None)
                if not isinstance(codex_identity, str) or not codex_identity:
                    codex_identity = process_identity_from_popen(process)
                if codex_identity is None:
                    raise RunnerError("cannot record Codex process creation identity")
                setattr(process, "_openbuild_process_identity", codex_identity)
                atomic_write_json(
                    run_dir / "codex.json",
                    {
                        "pid": process.pid,
                        "identity": codex_identity,
                        "process_group_id": process.pid,
                        "started_at": utc_now(),
                    },
                )
                communicate_after_activation(
                    process,
                    run_dir=run_dir,
                    prompt=prompt,
                    process_identity_value=codex_identity,
                    timeout=float(request["activation_timeout"]),
                )
                if isinstance(process.returncode, bool) or not isinstance(process.returncode, int):
                    raise RunnerError("Codex process finished without an integer exit code")
                atomic_write_json(
                    run_dir / "codex-exit.json",
                    {
                        "finished_at": utc_now(),
                        "pid": process.pid,
                        "identity": codex_identity,
                        "exit_code": process.returncode,
                    },
                )
                ACTIVE_WORKER_FINALIZING = True
            except BaseException as exc:
                child_exception = exc
            finally:
                tracked_process = process or ACTIVE_WORKER_CHILD
                try:
                    if tracked_process is not None:
                        terminate_spawned_process(tracked_process, process_group=True)
                except BaseException as exc:
                    cleanup_exception = exc
                    worker_cleanup_errors.append(str(exc) or type(exc).__name__)
                ACTIVE_WORKER_CHILD = None
            if child_exception is not None:
                raise child_exception
            if cleanup_exception is not None:
                raise cleanup_exception
            if process is not None:
                returncode = process.returncode
        evidence = read_event_evidence(run_dir / "events.jsonl")
        result_error = final_result_error(run_dir / "result.md") if evidence.get("completed") else None
        failure_message = result_error or execution_failure_message(returncode, evidence)
    except BaseException as exc:
        failure_message = str(exc) or type(exc).__name__
        if not isinstance(exc, Exception):
            pending_base_exception = exc

    success = returncode == 0 and evidence.get("completed") is True and failure_message is None
    try:
        atomic_write_json(
            run_dir / "exit.json",
            {
                "finished_at": utc_now(),
                "exit_code": returncode,
                "success": success,
                "terminal_event": evidence.get("terminal_event"),
                "failure_message": failure_message,
                "cleanup_errors": worker_cleanup_errors,
            },
        )
    except BaseException as record_exc:
        if pending_base_exception is not None:
            raise pending_base_exception from record_exc
        raise
    if pending_base_exception is not None:
        raise pending_base_exception
    return 0 if success else 1


def status_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_reference(args.run_dir)
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    reconcile_implementation_registry(run_dir, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 1 if receipt["status"] == "failed" else 0


def activate_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_reference(args.run_dir)
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt["status"] != "running":
        reconcile_implementation_registry(run_dir, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt["status"] == "completed" else 1
    if not receipt.get("codex_pid") or not receipt.get("codex_process_identity"):
        raise RunnerError("Codex process is not ready for activation")
    activation_path = run_dir / "activate.json"
    request_path = run_dir / "request.json"
    request = read_json(request_path) if request_path.is_file() else None
    root_completion_binding_digest = None
    if request is not None:
        source_binding = request.get("root_completion_source_binding")
        if isinstance(source_binding, Mapping):
            root_completion_binding_digest = sha256_bytes(
                _canonical_json_bytes(source_binding)
            )
    if activation_path.is_file():
        activation = read_json(activation_path)
        if (
            activation.get("codex_pid") != receipt["codex_pid"]
            or activation.get("codex_process_identity") != receipt["codex_process_identity"]
        ):
            raise RunnerError("existing activation does not match the live creation-bound Codex process")
    else:
        registry = recovery_registry_for_request(request) if request is not None else None
        lease_id = request.get("lease_id") if request is not None else None
        if (
            request is not None
            and registry is not None
            and isinstance(lease_id, str)
        ):
            allowed_set_digest = request.get("lifecycle_allowed_set_digest") or (
                request.get("recovery_preflight") or {}
            ).get("allowed_set_digest", "")
            state = registry.state_for_activation()
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
                raise RunnerError("workspace activation lease is missing or changed")
            if lease.get("state") in {
                "process-bound-unactivated",
                "ordinary-process-bound-unactivated",
                "running",
                "active",
                "legacy-running",
            }:
                registry.commit_activation(lease_id, allowed_set_digest)
            else:
                raise RunnerError("workspace activation lifecycle is not resumable")
    if request is not None:
        attach_project_lane_writer(request)
    if not activation_path.is_file():
        atomic_write_json(
            activation_path,
            {
                **activation_window(),
                "codex_pid": receipt["codex_pid"],
                "codex_process_identity": receipt["codex_process_identity"],
                "root_completion_source_binding_digest": root_completion_binding_digest,
            },
        )
    receipt = public_receipt(run_dir)
    atomic_write_json(run_dir / "dispatch-activated-receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 1 if receipt["status"] == "failed" else 0


def dispatch_run(args: argparse.Namespace) -> int:
    """Atomically create the unactivated receipt and activate that exact run.

    Legacy callers may still use ``start`` and ``activate`` independently.  Normal
    OpenBuild orchestration uses this owner-side sequence so no root action can
    interleave between the durable unactivated and activated receipts.
    """
    if not getattr(args, "run_dir", None):
        args.run_dir = str(default_run_dir().resolve())
    start_output = io.StringIO()
    with contextlib.redirect_stdout(start_output):
        started = start_run(args)
    if started != 0:
        print(start_output.getvalue(), end="")
        return started
    run_dir = getattr(args, "run_dir", None)
    if not isinstance(run_dir, str) or not run_dir:
        raise RunnerError("dispatch did not retain the started run directory")
    resolved_run_dir = Path(run_dir).expanduser().resolve()
    unactivated = read_json(resolved_run_dir / "dispatch-unactivated-receipt.json")
    if unactivated.get("status") != "running" or unactivated.get("activated") is not False:
        raise RunnerError("dispatch requires the durable unactivated receipt for the exact started run")
    with contextlib.redirect_stdout(io.StringIO()):
        activated = activate_run(argparse.Namespace(run_dir=run_dir))
    activated_receipt = read_json(resolved_run_dir / "dispatch-activated-receipt.json")
    print(json.dumps(activated_receipt, ensure_ascii=False, indent=2))
    return activated


def wait_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_reference(args.run_dir)
    deadline = time.monotonic() + args.timeout
    while True:
        audit_guardian_health(run_dir)
        receipt = public_receipt(run_dir)
        if receipt["status"] != "running":
            reconcile_implementation_registry(run_dir, receipt)
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0 if receipt["status"] == "completed" else 1
        if time.monotonic() >= deadline:
            receipt["status"] = "timeout"
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0 if args.soft_timeout_exit_zero else 3
        time.sleep(args.poll_seconds)


def _wait_until_stopped(records: list[Mapping[str, Any]], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        states = [process_tree_record_state(record) for record in records]
        if all(state == "stopped" for state in states):
            return True
        time.sleep(0.1)
    return all(process_tree_record_state(record) == "stopped" for record in records)


def terminate_spawned_process(
    process: Any,
    *,
    process_group: bool,
    grace_seconds: float = 5.0,
) -> None:
    if os.name == "nt":
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired as exc:
                raise RunnerError(f"spawned process {process.pid} did not stop") from exc
        return

    if process_group:
        if process.poll() is not None:
            return
        expected_identity = getattr(process, "_openbuild_process_identity", None)
        current_identity = process_identity_from_popen(process)
        if current_identity is None:
            if process.poll() is not None:
                return
            raise RunnerError(f"spawned process {process.pid} creation identity is unknown")
        if expected_identity is not None and current_identity != expected_identity:
            raise RunnerError(
                f"spawned process {process.pid} creation identity changed; refusing group signal"
            )
        setattr(process, "_openbuild_process_identity", current_identity)
        group_state = process_group_status(process.pid)
        if group_state == "unknown":
            raise RunnerError(f"spawned process group {process.pid} liveness is unknown")
        if group_state == "stopped":
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline and process_group_status(process.pid) == "running":
            time.sleep(0.05)
        if process_group_status(process.pid) != "stopped":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline and process_group_status(process.pid) == "running":
                time.sleep(0.05)
        if process_group_status(process.pid) != "stopped":
            raise RunnerError(f"spawned process group {process.pid} did not stop")
        process.wait(timeout=grace_seconds)
        return

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"spawned process {process.pid} did not stop") from exc


def terminate_process_tree(
    worker: Mapping[str, Any],
    codex: Mapping[str, Any],
    grace_seconds: float,
) -> None:
    records = [record for record in (worker, codex) if int(record.get("pid") or 0) > 0]
    states = [process_tree_record_state(record) for record in records]
    if any(state == "unknown" for state in states):
        raise RunnerError("process liveness or creation identity is unknown; do not release the writer lease")
    if not records or all(state == "stopped" for state in states):
        return
    if os.name == "nt":
        for record, state in zip(records, states):
            if state == "running":
                terminate_windows_process_record(record, grace_seconds)
    else:
        for record, state in zip(records, states):
            if state == "running":
                try:
                    os.killpg(
                        int(record.get("process_group_id") or record["pid"]),
                        signal.SIGTERM,
                    )
                except ProcessLookupError:
                    pass
        if not _wait_until_stopped(records, grace_seconds):
            for record in records:
                if process_tree_record_state(record) == "running":
                    try:
                        os.killpg(
                            int(record.get("process_group_id") or record["pid"]),
                            signal.SIGKILL,
                        )
                    except ProcessLookupError:
                        pass
    if not _wait_until_stopped(records, grace_seconds):
        raise RunnerError("worker process tree did not stop; do not release the writer lease")


def cancel_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_reference(args.run_dir)
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt["status"] != "running":
        reconcile_implementation_registry(run_dir, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt["status"] == "completed" else 1
    worker_record = {
        "pid": receipt.get("worker_pid"),
        "identity": receipt.get("worker_process_identity"),
        "process_group_id": receipt.get("worker_process_group_id"),
    }
    codex_record = {
        "pid": receipt.get("codex_pid"),
        "identity": receipt.get("codex_process_identity"),
        "process_group_id": receipt.get("codex_process_group_id"),
    }
    if (run_dir / "guardian-ready.json").is_file():
        secret = _guardian_secret(run_dir)
        ready = read_guardian_message(
            run_dir / "guardian-ready.json",
            secret,
            "guardian-ready",
        )
        write_guardian_message(
            run_dir / "guardian-cancel.json",
            secret,
            "guardian-cancel",
            {"guardian_id": ready.get("guardian_id"), "cancelled_at": utc_now()},
        )
        await_guardian_record(
            run_dir,
            secret,
            "guardian-zero.json",
            "guardian-zero",
            timeout=max(20.0, float(args.grace_seconds)),
        )
        if not _wait_until_stopped([worker_record, codex_record], args.grace_seconds):
            raise RunnerError("contained worker records did not stop after guardian cancellation")
    else:
        terminate_process_tree(worker_record, codex_record, args.grace_seconds)
    receipt = public_receipt(run_dir)
    if receipt["status"] == "completed":
        reconcile_implementation_registry(run_dir, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    evidence = read_event_evidence(run_dir / "events.jsonl")
    result_error = final_result_error(run_dir / "result.md") if evidence.get("completed") else None
    recovered_exit_code, recovered_exit_status = codex_exit_evidence_status(
        run_dir,
        expected_pid=receipt.get("codex_pid"),
        expected_identity=receipt.get("codex_process_identity"),
    )
    _, recovered_exit_error = codex_exit_evidence(
        run_dir,
        expected_pid=receipt.get("codex_pid"),
        expected_identity=receipt.get("codex_process_identity"),
    )
    if (
        not (run_dir / "exit.json").is_file()
        and evidence.get("completed") is True
        and result_error is None
        and recovered_exit_error is None
        and recovered_exit_code == 0
    ):
        atomic_write_json(
            run_dir / "exit.json",
            {
                "finished_at": utc_now(),
                "exit_code": 0,
                "codex_exit_evidence": "valid",
                "success": True,
                "terminal_event": "turn.completed",
                "failure_message": None,
                "completion_recovered_during_cancel": True,
                "process_tree_stopped": True,
                "worker_pid": receipt.get("worker_pid"),
                "worker_process_identity": receipt.get("worker_process_identity"),
                "codex_pid": receipt.get("codex_pid"),
                "codex_process_identity": receipt.get("codex_process_identity"),
                "codex_started": bool(receipt.get("codex_started")),
            },
        )
        receipt = public_receipt(run_dir)
        reconcile_implementation_registry(run_dir, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    if not (run_dir / "exit.json").is_file():
        recovery_failure = None
        if evidence.get("completed") is True and result_error is None:
            recovery_failure = recovered_exit_error or (
                f"codex exec exited with code {recovered_exit_code}"
                if recovered_exit_code is not None
                else "Codex exit code is unavailable"
            )
        atomic_write_json(
            run_dir / "exit.json",
            {
                "finished_at": utc_now(),
                "exit_code": recovered_exit_code,
                "codex_exit_evidence": recovered_exit_status,
                "success": False,
                "terminal_event": evidence.get("terminal_event"),
                "failure_message": recovery_failure
                or "cancelled by the OpenBuild root; process tree confirmed stopped",
                "cancelled": True,
                "process_tree_stopped": True,
                "worker_pid": receipt.get("worker_pid"),
                "worker_process_identity": receipt.get("worker_process_identity"),
                "codex_pid": receipt.get("codex_pid"),
                "codex_process_identity": receipt.get("codex_process_identity"),
                "codex_started": bool(receipt.get("codex_started")),
            },
        )
    receipt = public_receipt(run_dir)
    reconcile_implementation_registry(run_dir, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "completed" else 1


def add_project_lane_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-lane-id")
    parser.add_argument("--project-checkout")
    parser.add_argument("--project-coordinator-root")
    parser.add_argument("--project-anchor-id")
    parser.add_argument("--project-recovery-root")
    parser.add_argument("--project-lane-root")
    parser.add_argument("--project-integration-ref")


def add_review_progress_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--review-specification-lineage-digest")
    parser.add_argument("--review-specification-revision")
    parser.add_argument("--review-full-diff-digest")
    parser.add_argument("--review-validation-digest")
    parser.add_argument("--review-acceptance-criteria-digest")
    parser.add_argument("--review-open-finding-key", action="append", default=[])
    parser.add_argument("--review-closed-finding-key", action="append", default=[])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="start one explicit-model Codex agent asynchronously")
    start.add_argument("--agent", required=True, choices=sorted(SUPPORTED_AGENTS))
    start.add_argument("--task-name", required=True)
    start.add_argument("--repo", required=True)
    start_prompt = start.add_mutually_exclusive_group(required=False)
    start_prompt.add_argument("--prompt-file")
    start_prompt.add_argument("--prompt-snapshot-id")
    start.add_argument("--prompt-sha256")
    start.add_argument("--search-fallback-source")
    start.add_argument("--expected-map-sha256")
    start.add_argument("--run-dir")
    start.add_argument("--lease-id")
    start.add_argument("--allowed-file", action="append", default=[])
    start.add_argument("--specification-revision")
    start.add_argument("--recovery-target-milestone")
    add_project_lane_arguments(start)
    add_review_progress_arguments(start)
    start.add_argument("--activation-timeout", type=float, default=300.0)
    start.add_argument("--codex-bin", default=os.environ.get("OPENBUILD_CODEX_BIN", "codex"))
    start.set_defaults(handler=start_run)

    dispatch = subparsers.add_parser(
        "dispatch",
        help="start and immediately activate one explicit-model Codex agent",
    )
    dispatch.add_argument("--agent", required=True, choices=sorted(SUPPORTED_AGENTS))
    dispatch.add_argument("--task-name", required=True)
    dispatch.add_argument("--repo", required=True)
    dispatch_prompt = dispatch.add_mutually_exclusive_group(required=False)
    dispatch_prompt.add_argument("--prompt-file")
    dispatch_prompt.add_argument("--prompt-snapshot-id")
    dispatch.add_argument("--prompt-sha256")
    dispatch.add_argument("--search-fallback-source")
    dispatch.add_argument("--expected-map-sha256")
    dispatch.add_argument("--run-dir")
    dispatch.add_argument("--lease-id")
    dispatch.add_argument("--allowed-file", action="append", default=[])
    dispatch.add_argument("--specification-revision")
    dispatch.add_argument("--recovery-target-milestone")
    add_project_lane_arguments(dispatch)
    add_review_progress_arguments(dispatch)
    dispatch.add_argument("--activation-timeout", type=float, default=300.0)
    dispatch.add_argument("--codex-bin", default=os.environ.get("OPENBUILD_CODEX_BIN", "codex"))
    dispatch.set_defaults(handler=dispatch_run)

    status = subparsers.add_parser("status", help="print the current audited run receipt")
    status.add_argument("--run-dir", required=True)
    status.set_defaults(handler=status_run)

    activate = subparsers.add_parser("activate", help="release the task prompt to a ready worker")
    activate.add_argument("--run-dir", required=True)
    activate.set_defaults(handler=activate_run)

    wait = subparsers.add_parser("wait", help="wait for a terminal JSONL event and print the receipt")
    wait.add_argument("--run-dir", required=True)
    wait.add_argument("--timeout", type=float, default=1800.0)
    wait.add_argument("--poll-seconds", type=float, default=1.0)
    wait.add_argument(
        "--soft-timeout-exit-zero",
        action="store_true",
        help="return zero for a non-terminal observation timeout while preserving status=timeout",
    )
    wait.set_defaults(handler=wait_run)

    cancel = subparsers.add_parser("cancel", help="stop a running worker process tree")
    cancel.add_argument("--run-dir", required=True)
    cancel.add_argument("--grace-seconds", type=float, default=5.0)
    cancel.set_defaults(handler=cancel_run)

    stage_prompt = subparsers.add_parser(
        "stage-prompt",
        help="stage bounded UTF-8 prompt bytes from stdin in owner-private storage",
    )
    stage_prompt.add_argument("--repo", required=True)
    stage_prompt.set_defaults(handler=stage_prompt_run)

    browser_qa = subparsers.add_parser(
        "_browser-qa-substitute",
        help=argparse.SUPPRESS,
    )
    browser_qa.add_argument("--repo", required=True)
    browser_qa.add_argument("--specification-revision", required=True)
    browser_qa.add_argument("--scenario-file", required=True)
    browser_qa.add_argument("--timeout", type=float, default=60.0)
    browser_qa.add_argument("qa_argv", nargs=argparse.REMAINDER)
    browser_qa.set_defaults(handler=browser_qa_substitute_run)

    worker = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--run-dir", required=True)
    worker.set_defaults(handler=lambda args: worker_run(Path(args.run_dir).resolve()))
    guardian = subparsers.add_parser("_guardian", help=argparse.SUPPRESS)
    guardian.add_argument("--run-dir", required=True)
    guardian.set_defaults(handler=lambda args: guardian_run(Path(args.run_dir).resolve()))
    finalize = subparsers.add_parser("_finalize-success", help=argparse.SUPPRESS)
    finalize.add_argument("--run-dir", required=True)
    finalize.add_argument("--primary-signal-digest", required=True)
    finalize.set_defaults(handler=finalize_success_run)
    reject = subparsers.add_parser("_reject-handoff", help=argparse.SUPPRESS)
    reject.add_argument("--run-dir", required=True)
    reject.add_argument("--disposition", choices=["blocked", "needs-escalation"], required=True)
    reject.add_argument("--evidence-digest", required=True)
    reject.set_defaults(handler=reject_semantic_handoff_run)
    abandon = subparsers.add_parser("_reconcile-terminal-abandonment", help=argparse.SUPPRESS)
    abandon.add_argument("--run-dir", required=True)
    abandon.set_defaults(handler=reconcile_terminal_abandonment_run)
    containment_loss = subparsers.add_parser(
        "_reconcile-containment-loss", help=argparse.SUPPRESS
    )
    containment_loss.add_argument("--run-dir", required=True)
    containment_loss.set_defaults(handler=reconcile_containment_loss_run)
    post_commit_action = subparsers.add_parser(
        "_stage-post-commit-root-completion-action", help=argparse.SUPPRESS
    )
    post_commit_action.add_argument("--run-dir", required=True)
    post_commit_action.add_argument("--task-commit", required=True)
    post_commit_action.add_argument("--root-verification-digest", required=True)
    post_commit_action.add_argument("--remediation-scope-file", required=True)
    post_commit_action.set_defaults(handler=stage_post_commit_root_completion_action_run)
    post_commit_authorize = subparsers.add_parser(
        "_authorize-post-commit-root-completion", help=argparse.SUPPRESS
    )
    post_commit_authorize.add_argument("--run-dir", required=True)
    post_commit_authorize.add_argument("--task-commit", required=True)
    post_commit_authorize.add_argument("--root-verification-digest", required=True)
    post_commit_authorize.add_argument("--remediation-scope-file", required=True)
    post_commit_authorize.add_argument("--action-snapshot-id", required=True)
    post_commit_authorize.add_argument("--action-snapshot-sha256", required=True)
    post_commit_authorize.set_defaults(handler=authorize_post_commit_root_completion_run)
    post_commit_finalize = subparsers.add_parser(
        "_finalize-post-commit-root-completion", help=argparse.SUPPRESS
    )
    post_commit_finalize.add_argument("--run-dir", required=True)
    post_commit_finalize.add_argument("--task-commit", required=True)
    post_commit_finalize.add_argument("--root-verification-digest", required=True)
    post_commit_finalize.add_argument("--authorization-handle", required=True)
    post_commit_finalize.add_argument("--remediation-scope-file", required=True)
    post_commit_finalize.set_defaults(handler=finalize_post_commit_root_completion_run)
    root_completion = subparsers.add_parser(
        "_record-root-completion", help=argparse.SUPPRESS
    )
    root_completion.add_argument("--run-dir", required=True)
    root_completion.add_argument("--specification-revision", required=True)
    root_completion.add_argument("--milestone", required=True)
    root_completion.add_argument("--allowed-set-digest", required=True)
    root_completion.add_argument("--diff-attribution-digest", required=True)
    root_completion.add_argument(
        "--continuation-action",
        choices=["run", "direct-fix", "qa", "review", "new-writer"],
        default="run",
    )
    root_completion.set_defaults(handler=record_root_completion_authorization_run)
    authorize = subparsers.add_parser("_authorize-recovery", help=argparse.SUPPRESS)
    authorize.add_argument("--repo", required=True)
    authorize.add_argument("--checkpoint-file", required=True)
    authorize_prompt = authorize.add_mutually_exclusive_group(required=True)
    authorize_prompt.add_argument("--prompt-file")
    authorize_prompt.add_argument("--prompt-snapshot-id")
    authorize.add_argument("--prompt-sha256")
    authorize.add_argument("--run-dir", required=True)
    authorize.add_argument("--lease-id", required=True)
    authorize.add_argument("--user-action-digest", required=True)
    authorize.add_argument("--specification-revision", required=True)
    add_project_lane_arguments(authorize)
    authorize.set_defaults(handler=authorize_recovery_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except RunnerError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
