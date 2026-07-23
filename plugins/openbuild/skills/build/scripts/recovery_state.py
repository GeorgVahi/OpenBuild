"""Private recovery registry and checkpoint provenance owned by ``agent_runner``.

The public runner receipt remains schema v1.  Everything in this module is
owner-private operational state; callers must project only the explicitly
returned opaque checkpoint/grant records into Build traces.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


REGISTRY_SCHEMA = 1
IDENTITY_VERSION = 2
READER_FLOOR = "2.4.0"
_LEGACY_READER_FLOORS = {
    "2.2.0",
    "2.2.1",
    "2.2.2",
    "2.2.3",
    "2.2.5",
    "2.3.2",
    "2.3.5",
    "2.3.6",
}
DEFAULT_MAX_RECORDS = 100_000
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024

_DOMAIN_WORKSPACE = b"openbuild-workspace-v2\0"
_DOMAIN_ALLOWED = b"openbuild-allowed-set-v1\0"
_DOMAIN_CHECKPOINT = b"openbuild-checkpoint-v1\0"
_DOMAIN_KEY_ID = b"openbuild-checkpoint-key-id-v1\0"
_DOMAIN_PATH = b"openbuild-path-v1\0"
_DOMAIN_REF = b"openbuild-ref-v1\0"
_DOMAIN_CONTENT = b"openbuild-content-v1\0"
_DOMAIN_SYMLINK = b"openbuild-symlink-v1\0"
_DOMAIN_OBJECT = b"openbuild-object-v1\0"
_DOMAIN_INDEX = b"openbuild-index-v1\0"
_DOMAIN_STATUS = b"openbuild-status-v1\0"
_DOMAIN_INVENTORY = b"openbuild-inventory-v1\0"
_DOMAIN_SOURCE = b"openbuild-source-v1\0"
_DOMAIN_GRANT = b"openbuild-authorization-v1\0"
_DOMAIN_NONCE = b"openbuild-authorization-nonce-v1\0"
_DOMAIN_TERMINAL_ARCHIVE = b"openbuild-terminal-archive-v1\0"
_DOMAIN_TERMINAL_ABANDONMENT = b"openbuild-terminal-abandonment-v1\0"
_DOMAIN_CONTAINMENT_LOSS_RECONCILIATION = b"openbuild-containment-loss-reconciliation-v1\0"
_DOMAIN_REMEDIATION_SCOPE = b"openbuild-remediation-scope-v1\0"
_DOMAIN_POST_COMMIT_ACTION = b"openbuild-post-commit-root-completion-action-v1\0"
_DOMAIN_POST_COMMIT_AUTHORIZATION = b"openbuild-post-commit-root-completion-authorization-v1\0"


class RecoveryStateError(RuntimeError):
    """A recovery invariant failed; callers must not activate a writer."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    copy = dict(value)
    copy.pop("digest", None)
    return hashlib.sha256(_canonical(copy)).hexdigest()


def _domain_digest(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + _canonical(value)).hexdigest()


def _keyed_id(key: bytes, domain: bytes, value: bytes | str | Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        payload = _canonical(value)
    return hmac.new(key, domain + payload, hashlib.sha256).hexdigest()


def _require_hex(value: Any, name: str, *, length: int = 64) -> str:
    if not isinstance(value, str) or len(value) != length:
        raise RecoveryStateError(f"{name} must be a {length}-character lowercase hex value")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise RecoveryStateError(f"{name} must be lowercase hex") from exc
    if value != value.lower():
        raise RecoveryStateError(f"{name} must be lowercase hex")
    return value


def _require_git_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", value):
        raise RecoveryStateError(f"{name} must be a full lowercase Git SHA")
    return value


def _require_exact_object(
    value: Any,
    name: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecoveryStateError(f"{name} must be an object")
    allowed = required | (optional or set())
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise RecoveryStateError(f"{name} fields are incomplete or unknown")
    return value


def _require_string(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RecoveryStateError(f"{name} must be a string")
    return value


def _require_integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise RecoveryStateError(f"{name} must be an integer >= {minimum}")
    return value


def _require_boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise RecoveryStateError(f"{name} must be a boolean")
    return value


def _require_optional_hex(value: Any, name: str) -> None:
    if value is not None:
        _require_hex(value, name)


def _require_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RecoveryStateError(f"{name} must be a string list")
    return value


def _validate_public_inventory_record(value: Any) -> None:
    record = _require_exact_object(
        value,
        "public checkpoint inventory record",
        {"path_id", "kind", "mode", "size", "mtime_ns"},
        {"object_id", "content_id", "symlink_id"},
    )
    _require_hex(record["path_id"], "public checkpoint path ID")
    if record["kind"] not in {"missing", "file", "directory", "symlink"}:
        raise RecoveryStateError("public checkpoint inventory kind is malformed")
    for field in ("mode", "size", "mtime_ns"):
        if record[field] is not None:
            _require_integer(record[field], f"public checkpoint {field}")
    for field in ("object_id", "content_id", "symlink_id"):
        if field in record:
            _require_hex(record[field], f"public checkpoint {field}")


def _validate_public_snapshot(value: Any, name: str) -> None:
    snapshot = _require_exact_object(
        value,
        name,
        {
            "head_id",
            "ref_id",
            "full_index_digest",
            "status_digest",
            "allowed_inventory_digest",
            "ignored_inventory_digest",
            "records_digest",
            "records",
            "record_count",
            "hashed_bytes",
            "outside_set_delta",
        },
    )
    for field in (
        "head_id",
        "ref_id",
        "full_index_digest",
        "status_digest",
        "allowed_inventory_digest",
        "ignored_inventory_digest",
        "records_digest",
    ):
        _require_hex(snapshot[field], f"{name} {field}")
    if not isinstance(snapshot["records"], list):
        raise RecoveryStateError(f"{name} records must be a list")
    for record in snapshot["records"]:
        _validate_public_inventory_record(record)
    _require_integer(snapshot["record_count"], f"{name} record_count")
    _require_integer(snapshot["hashed_bytes"], f"{name} hashed_bytes")
    if snapshot["record_count"] != len(snapshot["records"]):
        raise RecoveryStateError(f"{name} record count drifted")
    if not isinstance(snapshot["outside_set_delta"], list):
        raise RecoveryStateError(f"{name} outside-set delta must be a list")
    for path_id in snapshot["outside_set_delta"]:
        _require_hex(path_id, f"{name} outside-set path ID")


def _validate_private_inventory_record(value: Any) -> None:
    if not isinstance(value, dict):
        raise RecoveryStateError("private checkpoint inventory record must be an object")
    kind = value.get("kind")
    if kind == "missing":
        record = _require_exact_object(
            value,
            "private missing inventory record",
            {"kind", "parent_identity", "collation_key"},
        )
        parent = _require_exact_object(
            record["parent_identity"],
            "private missing parent identity",
            {"platform", "device", "inode"},
        )
        _require_string(parent["platform"], "private missing parent platform")
        _require_integer(parent["device"], "private missing parent device")
        _require_integer(parent["inode"], "private missing parent inode")
        _require_string(record["collation_key"], "private missing collation key")
        return
    required = {"kind", "mode", "size", "mtime_ns", "identity"}
    optional: set[str] = set()
    if kind == "file":
        required |= {"sha256", "content_id"}
    elif kind == "symlink":
        required |= {"symlink_target", "symlink_id", "resolved_identity"}
    elif kind != "directory":
        raise RecoveryStateError("private checkpoint inventory kind is malformed")
    record = _require_exact_object(value, "private checkpoint inventory record", required, optional)
    _require_integer(record["mode"], "private checkpoint mode")
    _require_integer(record["size"], "private checkpoint size")
    _require_integer(record["mtime_ns"], "private checkpoint mtime")
    identity = _require_exact_object(
        record["identity"], "private checkpoint identity", {"device", "inode"}
    )
    _require_integer(identity["device"], "private checkpoint device")
    _require_integer(identity["inode"], "private checkpoint inode")
    if kind == "file":
        _require_hex(record["sha256"], "private checkpoint SHA-256")
        _require_hex(record["content_id"], "private checkpoint content ID")
    elif kind == "symlink":
        _require_string(record["symlink_target"], "private checkpoint symlink target")
        _require_hex(record["symlink_id"], "private checkpoint symlink ID")
        resolved = _require_exact_object(
            record["resolved_identity"],
            "private checkpoint resolved identity",
            {"device", "inode"},
        )
        _require_integer(resolved["device"], "private checkpoint resolved device")
        _require_integer(resolved["inode"], "private checkpoint resolved inode")


def _validate_private_snapshot(value: Any, name: str) -> None:
    snapshot = _require_exact_object(
        value,
        name,
        {
            "head",
            "ref",
            "full_index",
            "status",
            "status_paths",
            "ignored_paths",
            "allowed_paths",
            "records",
            "public",
            "allowed_set_digest",
        },
    )
    _require_string(snapshot["head"], f"{name} HEAD")
    if snapshot["ref"] is not None:
        _require_string(snapshot["ref"], f"{name} ref")
    if not isinstance(snapshot["full_index"], list):
        raise RecoveryStateError(f"{name} full index must be a list")
    for entry in snapshot["full_index"]:
        index_entry = _require_exact_object(
            entry,
            f"{name} full-index entry",
            {"tag", "mode", "object_id", "stage", "path"},
        )
        for field in ("tag", "mode", "object_id", "stage", "path"):
            _require_string(index_entry[field], f"{name} full-index {field}")
        if index_entry["tag"] != "H":
            raise RecoveryStateError(f"{name} full-index tag is unsupported")
    if not isinstance(snapshot["status"], list):
        raise RecoveryStateError(f"{name} status must be a list")
    for entry in snapshot["status"]:
        if not isinstance(entry, dict) or entry.get("kind") not in {"?", "!", "1", "2", "u"}:
            raise RecoveryStateError(f"{name} status entry is malformed")
        kind = entry["kind"]
        required = {"kind", "path"}
        if kind in {"1", "2", "u"}:
            required.add("metadata")
        if kind == "2":
            required.add("original_path")
        status_entry = _require_exact_object(entry, f"{name} status entry", required)
        for field in required - {"kind"}:
            _require_string(status_entry[field], f"{name} status {field}")
    for field in ("status_paths", "ignored_paths", "allowed_paths"):
        _require_string_list(snapshot[field], f"{name} {field}")
    if not snapshot["allowed_paths"]:
        raise RecoveryStateError(f"{name} allowed paths are empty")
    if not isinstance(snapshot["records"], dict):
        raise RecoveryStateError(f"{name} records must be an object")
    for path, record in snapshot["records"].items():
        _require_string(path, f"{name} record path")
        _validate_private_inventory_record(record)
    _validate_public_snapshot(snapshot["public"], f"{name} public projection")
    if snapshot["public"]["record_count"] != len(snapshot["records"]):
        raise RecoveryStateError(f"{name} private/public record count drifted")
    _require_hex(snapshot["allowed_set_digest"], f"{name} allowed-set digest")


def _validate_source_binding(value: Any) -> dict[str, Any]:
    binding = _require_exact_object(
        value,
        "private source binding",
        {
            "source_id",
            "source_lease_id",
            "source_receipt_digest",
            "source_milestone",
            "target_milestone",
            "specification_revision",
        },
    )
    for field in (
        "source_id",
        "source_lease_id",
        "source_milestone",
        "target_milestone",
        "specification_revision",
    ):
        _require_string(binding[field], f"private source {field}")
    _require_optional_hex(binding["source_receipt_digest"], "private source receipt digest")
    return binding


def _validate_public_preflight(value: Any) -> None:
    preflight = _require_exact_object(
        value,
        "public recovery preflight",
        {
            "schema_version",
            "source_state_id",
            "source_binding_id",
            "checkpoint_key_id",
            "allowed_set_digest",
            "source_milestone",
            "target_milestone",
            "specification_revision",
            "pre_snapshot",
            "disposition",
            "preflight_digest",
        },
    )
    if preflight["schema_version"] != 1:
        raise RecoveryStateError("public recovery preflight schema is unsupported")
    for field in (
        "source_state_id",
        "source_binding_id",
        "checkpoint_key_id",
        "allowed_set_digest",
    ):
        _require_hex(preflight[field], f"public recovery preflight {field}")
    for field in ("source_milestone", "target_milestone", "specification_revision"):
        _require_string(preflight[field], f"public recovery preflight {field}")
    if preflight["disposition"] != "recovery-capability-available":
        raise RecoveryStateError("public recovery preflight disposition is malformed")
    _validate_public_snapshot(preflight["pre_snapshot"], "public recovery preflight snapshot")
    digest_value = dict(preflight)
    digest = digest_value.pop("preflight_digest")
    if digest != _domain_digest(_DOMAIN_SOURCE, digest_value):
        raise RecoveryStateError("public recovery preflight digest drifted")


def _validate_public_checkpoint(value: Any) -> None:
    checkpoint = _require_exact_object(
        value,
        "public recovery checkpoint",
        {
            "schema_version",
            "source_state_id",
            "source_binding_id",
            "checkpoint_key_id",
            "allowed_set_digest",
            "source_milestone",
            "target_milestone",
            "specification_revision",
            "authorization_epoch",
            "pre_snapshot",
            "candidate_snapshot",
            "disposition",
            "reasons",
            "checkpoint_digest",
        },
    )
    if checkpoint["schema_version"] != 1:
        raise RecoveryStateError("public recovery checkpoint schema is unsupported")
    for field in (
        "source_state_id",
        "source_binding_id",
        "checkpoint_key_id",
        "allowed_set_digest",
    ):
        _require_hex(checkpoint[field], f"public recovery checkpoint {field}")
    for field in ("source_milestone", "target_milestone", "specification_revision"):
        _require_string(checkpoint[field], f"public recovery checkpoint {field}")
    _require_integer(checkpoint["authorization_epoch"], "public recovery checkpoint epoch")
    _validate_public_snapshot(checkpoint["pre_snapshot"], "public recovery checkpoint pre-snapshot")
    if checkpoint["candidate_snapshot"] is not None:
        _validate_public_snapshot(
            checkpoint["candidate_snapshot"], "public recovery checkpoint candidate snapshot"
        )
    if checkpoint["disposition"] not in {"recovery-eligible", "recovery-ineligible"}:
        raise RecoveryStateError("public recovery checkpoint disposition is malformed")
    reasons = _require_string_list(checkpoint["reasons"], "public recovery checkpoint reasons")
    allowed_reasons = {
        "git-control-plane-drift",
        "outside-set-drift",
        "preexisting-dirty-overlap",
        "semantic-needs-escalation",
        "terminal-abandoned-outside-set-drift",
        "terminal-abandoned-recovery-overlap",
        "terminal-abandoned-legacy-normal-overlap",
        "terminal-abandoned-legacy-normal-dirty-overlap",
        "terminal-abandoned-legacy-normal-control-plane-overlap",
        "post-commit-root-completed",
    }
    if any(reason not in allowed_reasons for reason in reasons):
        raise RecoveryStateError("public recovery checkpoint reason is unsupported")
    digest_value = dict(checkpoint)
    digest = digest_value.pop("checkpoint_digest")
    if digest != _domain_digest(_DOMAIN_CHECKPOINT, digest_value):
        raise RecoveryStateError("public recovery checkpoint digest drifted")


def _validate_private_authorization(value: Any) -> None:
    authorization = _require_exact_object(
        value,
        "private recovery authorization",
        {
            "grant_id",
            "authorization_nonce",
            "authorization_epoch",
            "user_action_digest",
            "specification_revision",
            "source_receipt_digest",
            "checkpoint_digest",
            "allowed_set_digest",
            "target_milestone",
        },
        {"prompt_snapshot_id", "prompt_sha256"},
    )
    for field in (
        "grant_id",
        "authorization_nonce",
        "user_action_digest",
        "source_receipt_digest",
        "checkpoint_digest",
        "allowed_set_digest",
    ):
        _require_hex(authorization[field], f"private recovery authorization {field}")
    if ("prompt_snapshot_id" in authorization) != ("prompt_sha256" in authorization):
        raise RecoveryStateError("private recovery authorization prompt binding is incomplete")
    for field in ("prompt_snapshot_id", "prompt_sha256"):
        if field in authorization:
            _require_hex(authorization[field], f"private recovery authorization {field}")
    _require_integer(authorization["authorization_epoch"], "private recovery authorization epoch")
    _require_string(
        authorization["specification_revision"], "private recovery authorization specification"
    )
    _require_string(authorization["target_milestone"], "private recovery authorization target")


def _terminal_part_digest(name: str, value: Mapping[str, Any]) -> str:
    return _domain_digest(_DOMAIN_TERMINAL_ARCHIVE + name.encode("ascii") + b"\0", value)


def _validate_terminal_archive(value: Mapping[str, Any]) -> None:
    required = {
        "event",
        "lease_id",
        "lease_kind",
        "final_state",
        "allowed_set_digest",
        "terminal_success",
        "terminal_receipt_digest",
        "zero_proof_digest",
        "guardian_close_digest",
        "provider_receipt_digest",
        "process_receipt_digest",
        "semantic_disposition",
        "semantic_disposition_digest",
        "handoff_digest",
        "outbox_digest",
        "archive_digest",
    }
    if set(value) != required or value.get("event") != "contained-terminal-released":
        raise RecoveryStateError("contained terminal archive fields are malformed")
    if not isinstance(value.get("lease_id"), str) or not value["lease_id"]:
        raise RecoveryStateError("contained terminal archive lease is malformed")
    if value.get("lease_kind") not in {"normal-contained", "recovery-target"}:
        raise RecoveryStateError("contained terminal archive lease kind is malformed")
    if value.get("final_state") not in {"stopped-terminal", "handoff-committed"}:
        raise RecoveryStateError("contained terminal archive final state is malformed")
    if not isinstance(value.get("terminal_success"), bool):
        raise RecoveryStateError("contained terminal archive success is malformed")
    for field in (
        "allowed_set_digest",
        "terminal_receipt_digest",
        "zero_proof_digest",
        "guardian_close_digest",
        "provider_receipt_digest",
        "process_receipt_digest",
    ):
        _require_hex(value.get(field), f"contained terminal archive {field}")
    for field in ("semantic_disposition_digest", "handoff_digest", "outbox_digest"):
        if value.get(field) is not None:
            _require_hex(value.get(field), f"contained terminal archive {field}")
    semantic = value.get("semantic_disposition")
    if semantic not in {None, "blocked", "needs-escalation", "abandoned", "root-completed"}:
        raise RecoveryStateError("contained terminal archive semantic disposition is malformed")
    if (semantic is None) != (value.get("semantic_disposition_digest") is None):
        raise RecoveryStateError("contained terminal archive semantic digest is malformed")
    if value["terminal_success"]:
        if semantic is not None or value.get("handoff_digest") is None or value.get("outbox_digest") is None:
            raise RecoveryStateError("successful contained terminal archive lacks handoff evidence")
    elif value.get("handoff_digest") is not None or value.get("outbox_digest") is not None:
        raise RecoveryStateError("failed contained terminal archive cannot retain a handoff")
    archived = dict(value)
    archive_digest = archived.pop("archive_digest", None)
    if archive_digest != _domain_digest(_DOMAIN_TERMINAL_ARCHIVE, archived):
        raise RecoveryStateError("contained terminal archive digest drifted")


def _validate_process_receipt(value: Any) -> None:
    receipt = _require_exact_object(
        value,
        "process receipt",
        set(),
        {
            "pid",
            "identity",
            "process_group_id",
            "started_at",
            "run_id",
            "process_id",
            "creation_identity",
        },
    )
    if not receipt:
        raise RecoveryStateError("process receipt is empty")
    for field in ("pid", "process_group_id"):
        if field in receipt:
            _require_integer(receipt[field], f"process receipt {field}", minimum=1)
    for field in ("identity", "started_at", "run_id", "process_id", "creation_identity"):
        if field in receipt:
            _require_string(receipt[field], f"process receipt {field}")
    if not any(field in receipt for field in ("identity", "creation_identity")):
        raise RecoveryStateError("process receipt lacks a creation identity")


def _validate_provider_receipt(value: Any) -> None:
    receipt = _require_exact_object(
        value,
        "provider receipt",
        {
            "guardian_id",
            "guardian_pid",
            "guardian_identity",
            "provider",
            "provider_plan_id",
            "ipc_plan_id",
            "policy",
            "active_processes",
            "anti_migration",
            "precommit",
        },
    )
    for field in (
        "guardian_id",
        "guardian_identity",
        "provider_plan_id",
        "ipc_plan_id",
        "policy",
    ):
        _require_string(receipt[field], f"provider receipt {field}")
    if receipt["provider"] not in {"windows-job", "linux-cgroup-v2"}:
        raise RecoveryStateError("provider receipt provider is unsupported")
    for field in ("guardian_pid", "active_processes"):
        _require_integer(receipt[field], f"provider receipt {field}", minimum=1)
    anti_migration = receipt.get("anti_migration")
    if anti_migration is not None:
        anti = _require_exact_object(
            anti_migration,
            "Linux anti-migration receipt",
            {
                "guardian_id",
                "worker_pid",
                "worker_identity",
                "cgroup_namespace",
                "mount_namespace",
                "self_cgroup",
                "cgroup_mount_count",
                "cgroup_mounts_read_only",
                "cgroup_write_denied",
                "no_cgroup_control_fds",
                "unprivileged_user_namespaces_disabled",
                "capabilities_zero",
                "no_new_privs",
            },
        )
        for field in (
            "guardian_id",
            "worker_identity",
            "cgroup_namespace",
            "mount_namespace",
            "self_cgroup",
        ):
            _require_string(anti[field], f"Linux anti-migration {field}")
        _require_integer(anti["worker_pid"], "Linux anti-migration worker PID", minimum=1)
        _require_integer(anti["cgroup_mount_count"], "Linux anti-migration mount count", minimum=1)
        for field in (
            "cgroup_mounts_read_only",
            "cgroup_write_denied",
            "no_cgroup_control_fds",
            "unprivileged_user_namespaces_disabled",
            "capabilities_zero",
            "no_new_privs",
        ):
            if anti[field] is not True:
                raise RecoveryStateError(f"Linux anti-migration {field} is not proven")
    proof = _require_exact_object(
        receipt["precommit"],
        "provider precommit receipt",
        {
            "guardian_id",
            "guardian_pid",
            "guardian_identity",
            "worker_pid",
            "worker_identity",
            "provider",
            "provider_plan_id",
            "ipc_plan_id",
            "provider_populated",
            "membership_verified",
            "precommit_nonce",
            "attested_at",
        },
    )
    for field in (
        "guardian_id",
        "guardian_identity",
        "worker_identity",
        "provider_plan_id",
        "ipc_plan_id",
        "precommit_nonce",
        "attested_at",
    ):
        _require_string(proof[field], f"provider precommit {field}")
    if proof["provider"] not in {"windows-job", "linux-cgroup-v2"}:
        raise RecoveryStateError("provider precommit provider is unsupported")
    for field in ("guardian_pid", "worker_pid"):
        _require_integer(proof[field], f"provider precommit {field}", minimum=1)
    for field in ("provider_populated", "membership_verified"):
        if proof[field] is not True:
            raise RecoveryStateError(f"provider precommit {field} is not proven")


def _validate_contained_process_binding(lease: Mapping[str, Any]) -> None:
    plan = lease["plan"] if lease["lease_kind"] == "recovery-target" else lease["containment_plan"]
    provider = lease["provider_receipt"]
    process = lease["process_receipt"]
    precommit = provider["precommit"]
    required_plan_fields = {"provider_plan_id", "ipc_plan_id"}
    if lease["lease_kind"] == "normal-contained":
        required_plan_fields.add("guardian_id")
    if not required_plan_fields.issubset(plan):
        raise RecoveryStateError("contained reserved plan is incomplete at the process boundary")
    for field in ("provider_plan_id", "ipc_plan_id"):
        if provider[field] != plan[field] or precommit[field] != plan[field]:
            raise RecoveryStateError(f"contained {field} binding drifted")
    if lease["lease_kind"] == "normal-contained" and provider["guardian_id"] != plan["guardian_id"]:
        raise RecoveryStateError("contained guardian plan binding drifted")
    for field in ("guardian_id", "guardian_pid", "guardian_identity", "provider"):
        if provider[field] != precommit[field]:
            raise RecoveryStateError(f"contained provider precommit {field} drifted")
    if "pid" not in process or "identity" not in process:
        raise RecoveryStateError("contained process receipt lacks PID or creation identity")
    if precommit["worker_pid"] != process["pid"] or precommit["worker_identity"] != process["identity"]:
        raise RecoveryStateError("contained provider/process identity binding drifted")
    anti_migration = provider["anti_migration"]
    if provider["provider"] == "linux-cgroup-v2":
        if not isinstance(anti_migration, dict):
            raise RecoveryStateError("Linux contained provider lacks anti-migration evidence")
        if (
            anti_migration["guardian_id"] != provider["guardian_id"]
            or anti_migration["worker_pid"] != process["pid"]
            or anti_migration["worker_identity"] != process["identity"]
        ):
            raise RecoveryStateError("Linux anti-migration identity binding drifted")
    elif anti_migration is not None:
        raise RecoveryStateError("Windows contained provider retained Linux anti-migration evidence")


def _validate_containment_plan(value: Any) -> None:
    plan = _require_exact_object(
        value,
        "containment plan",
        set(),
        {
            "guardian_id",
            "provider_plan_id",
            "ipc_plan_id",
            "contained_launch_token",
            "fallback_token",
            "recovery_target",
        },
    )
    if not plan:
        return
    if set(plan) != {
        "guardian_id",
        "provider_plan_id",
        "ipc_plan_id",
        "contained_launch_token",
        "fallback_token",
        "recovery_target",
    }:
        raise RecoveryStateError("containment plan fields are incomplete")
    for field in ("guardian_id", "provider_plan_id", "ipc_plan_id", "contained_launch_token"):
        _require_string(plan[field], f"containment plan {field}")
    if plan["fallback_token"] is not None:
        _require_string(plan["fallback_token"], "containment plan fallback token")
    _require_boolean(plan["recovery_target"], "containment plan recovery target")


def _validate_target_plan(value: Any) -> None:
    plan = _require_exact_object(
        value,
        "recovery target plan",
        {
            "lease_id",
            "run_id",
            "prompt_sha256",
            "launch_token",
            "provider_plan_id",
            "ipc_plan_id",
            "allowed_set_digest",
        },
        {"prompt_snapshot_id"},
    )
    for field in ("lease_id", "run_id", "provider_plan_id", "ipc_plan_id"):
        _require_string(plan[field], f"recovery target plan {field}")
    for field in ("prompt_sha256", "launch_token", "allowed_set_digest"):
        _require_hex(plan[field], f"recovery target plan {field}")
    if "prompt_snapshot_id" in plan:
        _require_hex(plan["prompt_snapshot_id"], "recovery target plan prompt snapshot ID")


def _validate_terminal_receipt(value: Any) -> None:
    receipt = _require_exact_object(
        value,
        "contained terminal receipt",
        {"success", "binding_digest", "terminal_event"},
        {"semantic_rejected", "semantic_evidence_digest", "binding_format"},
    )
    _require_boolean(receipt["success"], "contained terminal success")
    _require_hex(receipt["binding_digest"], "contained terminal binding digest")
    if receipt["terminal_event"] is not None:
        _require_string(receipt["terminal_event"], "contained terminal event")
    if "binding_format" in receipt and receipt["binding_format"] not in {
        "run-id-v2",
        "run-dir-v1",
    }:
        raise RecoveryStateError("contained terminal binding format is unsupported")
    if "semantic_rejected" in receipt:
        if receipt["semantic_rejected"] is not True:
            raise RecoveryStateError("contained terminal semantic rejection is malformed")
        _require_hex(
            receipt.get("semantic_evidence_digest"),
            "contained terminal semantic evidence digest",
        )


def _validate_zero_proof(value: Any) -> None:
    proof = _require_exact_object(
        value,
        "contained zero proof",
        {
            "populated",
            "identity_verified",
            "guardian_id",
            "provider",
            "worker_pid",
            "worker_identity",
            "proved_at",
        },
    )
    if proof["populated"] is not False or proof["identity_verified"] is not True:
        raise RecoveryStateError("contained zero proof is not affirmative")
    for field in ("guardian_id", "worker_identity", "proved_at"):
        _require_string(proof[field], f"contained zero proof {field}")
    if proof["provider"] not in {"windows-job", "linux-cgroup-v2"}:
        raise RecoveryStateError("contained zero proof provider is unsupported")
    _require_integer(proof["worker_pid"], "contained zero proof worker PID", minimum=1)


def _validate_semantic_disposition(value: Any) -> None:
    if isinstance(value, dict) and value.get("disposition") == "abandoned":
        semantic = _require_exact_object(
            value,
            "terminal abandonment disposition",
            {
                "disposition",
                "schema",
                "cause",
                "evidence_digest",
                "checkpoint_allowed",
                "checkpoint_invalidation",
                "run_id",
                "lease_id",
                "source_state_id",
                "source_checkpoint_digest",
                "allowed_set_digest",
                "terminal_binding_digest",
                "zero_proof_digest",
                "candidate_snapshot_digest",
            },
            {"checkpoint_digest"},
        )
        expected = {
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
                "legacy-normal-control-plane-and-outside-set-drift-with-preexisting-dirty-overlap",
            ),
            (
                "terminal-abandonment-v5",
                "legacy-normal-preexisting-dirty-overlap",
            ),
        }
        if (
            (semantic["schema"], semantic["cause"]) not in expected
            or semantic["checkpoint_allowed"] is not False
            or semantic["checkpoint_invalidation"] not in {"pending", "completed"}
        ):
            raise RecoveryStateError("terminal abandonment disposition is malformed")
        for field in (
            "evidence_digest",
            "source_state_id",
            "source_checkpoint_digest",
            "allowed_set_digest",
            "terminal_binding_digest",
            "zero_proof_digest",
            "candidate_snapshot_digest",
        ):
            _require_hex(semantic[field], f"terminal abandonment {field}")
        for field in ("run_id", "lease_id"):
            _require_string(semantic[field], f"terminal abandonment {field}")
        if semantic["checkpoint_invalidation"] == "completed":
            _require_hex(semantic.get("checkpoint_digest"), "terminal abandonment checkpoint digest")
        elif "checkpoint_digest" in semantic:
            raise RecoveryStateError("terminal abandonment checkpoint digest preceded completion")
        return
    if isinstance(value, dict) and value.get("disposition") == "root-completed":
        semantic = _require_exact_object(
            value,
            "terminal root completion disposition",
            {
                "disposition",
                "schema",
                "run_id",
                "lease_id",
                "source_state_id",
                "source_checkpoint_digest",
                "allowed_set_digest",
                "remediation_scope_digest",
                "task_commit",
                "parent_commit",
                "root_verification_digest",
                "user_action_digest",
                "authorization_digest",
                "authorization_consumption",
                "terminal_binding_format",
                "terminal_binding_digest",
                "zero_proof_digest",
                "candidate_snapshot_digest",
                "git_provenance_digest",
                "checkpoint_invalidation",
            },
            {"checkpoint_digest"},
        )
        if (
            semantic["schema"] != "terminal-root-completion-v1"
            or semantic["authorization_consumption"] != "consumed"
            or semantic["terminal_binding_format"] != "run-dir-v1"
            or semantic["checkpoint_invalidation"] not in {"pending", "completed"}
        ):
            raise RecoveryStateError("terminal root completion disposition is malformed")
        for field in (
            "source_state_id",
            "source_checkpoint_digest",
            "allowed_set_digest",
            "remediation_scope_digest",
            "root_verification_digest",
            "user_action_digest",
            "authorization_digest",
            "terminal_binding_digest",
            "zero_proof_digest",
            "candidate_snapshot_digest",
            "git_provenance_digest",
        ):
            _require_hex(semantic[field], f"terminal root completion {field}")
        _require_git_sha(semantic["task_commit"], "terminal root completion task commit")
        _require_git_sha(semantic["parent_commit"], "terminal root completion parent commit")
        for field in ("run_id", "lease_id"):
            _require_string(semantic[field], f"terminal root completion {field}")
        if semantic["checkpoint_invalidation"] == "completed":
            _require_hex(semantic.get("checkpoint_digest"), "terminal root completion checkpoint digest")
        elif "checkpoint_digest" in semantic:
            raise RecoveryStateError("terminal root completion checkpoint digest preceded completion")
        return
    semantic = _require_exact_object(
        value,
        "semantic disposition",
        {
            "disposition",
            "evidence_digest",
            "checkpoint_allowed",
            "checkpoint_invalidation",
            "run_id",
            "source_state_id",
        },
        {"checkpoint_digest"},
    )
    if semantic["disposition"] not in {"blocked", "needs-escalation"}:
        raise RecoveryStateError("semantic disposition is unsupported")
    _require_hex(semantic["evidence_digest"], "semantic disposition evidence digest")
    _require_boolean(semantic["checkpoint_allowed"], "semantic checkpoint allowance")
    _require_string(semantic["run_id"], "semantic disposition run ID")
    _require_hex(semantic["source_state_id"], "semantic disposition source state ID")
    if semantic["disposition"] == "blocked":
        if (
            semantic["checkpoint_allowed"] is not True
            or semantic["checkpoint_invalidation"] != "not-required"
            or "checkpoint_digest" in semantic
        ):
            raise RecoveryStateError("blocked semantic disposition must retain its checkpoint")
    elif (
        semantic["checkpoint_allowed"] is not False
        or semantic["checkpoint_invalidation"] not in {"pending", "completed"}
    ):
        raise RecoveryStateError("semantic escalation must invalidate its checkpoint")
    elif semantic["checkpoint_invalidation"] == "completed":
        _require_hex(semantic.get("checkpoint_digest"), "semantic invalidated checkpoint digest")
    elif "checkpoint_digest" in semantic:
        raise RecoveryStateError("semantic checkpoint digest preceded invalidation completion")


def _validate_terminal_identity_binding(lease: Mapping[str, Any]) -> None:
    proof = lease.get("zero_proof")
    provider = lease.get("provider_receipt")
    process = lease.get("process_receipt")
    if not isinstance(proof, Mapping):
        return
    if not isinstance(provider, Mapping) or not isinstance(process, Mapping):
        raise RecoveryStateError("contained zero proof lacks process ownership evidence")
    if (
        proof.get("guardian_id") != provider.get("guardian_id")
        or proof.get("provider") != provider.get("provider")
        or proof.get("worker_pid") != process.get("pid")
        or proof.get("worker_identity") != process.get("identity")
    ):
        raise RecoveryStateError("contained zero proof identity binding drifted")
    close = lease.get("guardian_close")
    if isinstance(close, Mapping) and close.get("guardian_id") != provider.get("guardian_id"):
        raise RecoveryStateError("guardian close identity binding drifted")


_NORMAL_LEASE_BASE = {
    "lease_id",
    "lease_kind",
    "recovery_capable",
    "state",
    "allowed_set_digest",
    "source_state_id",
    "run_id",
    "prompt_sha256",
    "containment_plan",
}
_RECOVERY_LEASE_BASE = {
    "lease_id",
    "lease_kind",
    "recovery_capable",
    "state",
    "source_state_id",
    "grant_id",
    "authorization_epoch",
    "checkpoint_digest",
    "allowed_set_digest",
    "target_milestone",
    "plan",
}
_LEASE_EXTRAS = {
    "source_snapshot_digest",
    "source_state_digest",
    "contained_launch_token_digest",
    "launch_claim_id",
    "provider_receipt",
    "process_receipt",
    "activation_allowed_set_digest",
    "activation_abort",
    "containment_failure",
    "teardown_proof",
    "fallback_token_digest",
    "terminal_receipt",
    "zero_proof",
    "semantic_disposition",
    "handoff_digest",
    "guardian_close",
    "prompt_snapshot_id",
}


def _validate_lease(value: Any) -> None:
    if not isinstance(value, dict):
        raise RecoveryStateError("recovery registry lease must be an object")
    kind = value.get("lease_kind")
    base = _RECOVERY_LEASE_BASE if kind == "recovery-target" else _NORMAL_LEASE_BASE
    lease = _require_exact_object(value, "recovery registry lease", base, _LEASE_EXTRAS)
    _require_string(lease["lease_id"], "recovery registry lease ID")
    if kind not in {"normal-legacy", "normal-contained", "normal-fallback", "recovery-target"}:
        raise RecoveryStateError("recovery registry lease kind is unsupported")
    recovery_capable = _require_boolean(
        lease["recovery_capable"], "recovery registry recovery capability"
    )
    if recovery_capable != (kind in {"normal-contained", "recovery-target"}):
        raise RecoveryStateError("recovery registry lease capability drifted")
    state = lease["state"]
    states_by_kind = {
        "normal-legacy": {"reserved", "ordinary-process-bound-unactivated", "legacy-running"},
        "normal-contained": {
            "normal-preflight-reserved",
            "normal-snapshot-bound",
            "normal-preflight-launch-claimed",
            "process-bound-unactivated",
            "running",
            "fallback-teardown-pending",
            "fallback-teardown-complete",
            "terminal-pending-stop",
            "stopped-terminal",
            "handoff-committed",
        },
        "normal-fallback": {
            "ordinary-fallback-claimed",
            "ordinary-process-bound-unactivated",
            "legacy-running",
        },
        "recovery-target": {
            "reserved",
            "launch-claimed",
            "process-bound-unactivated",
            "active",
            "terminal-pending-stop",
            "stopped-terminal",
            "handoff-committed",
        },
    }
    if state not in states_by_kind[kind]:
        raise RecoveryStateError("recovery registry lease state is unsupported for its kind")
    if lease["allowed_set_digest"]:
        _require_hex(lease["allowed_set_digest"], "recovery registry allowed-set digest")
    elif recovery_capable:
        raise RecoveryStateError("recovery-capable lease lacks an allowed-set digest")
    if lease["source_state_id"] is not None:
        _require_hex(lease["source_state_id"], "recovery registry source state ID")

    if kind == "recovery-target":
        _require_hex(lease["grant_id"], "recovery registry grant ID")
        _require_integer(lease["authorization_epoch"], "recovery registry authorization epoch")
        _require_hex(lease["checkpoint_digest"], "recovery registry checkpoint digest")
        _require_string(lease["target_milestone"], "recovery registry target milestone")
        _validate_target_plan(lease["plan"])
    else:
        if lease["run_id"] is not None:
            _require_string(lease["run_id"], "recovery registry run ID")
        if lease.get("prompt_snapshot_id") is not None:
            _require_hex(lease["prompt_snapshot_id"], "recovery registry prompt snapshot ID")
        if lease["prompt_sha256"] is not None:
            _require_hex(lease["prompt_sha256"], "recovery registry prompt SHA-256")
        _validate_containment_plan(lease["containment_plan"])

    progression: set[str] = set()
    if kind == "normal-contained":
        if state != "normal-preflight-reserved":
            progression |= {"source_snapshot_digest", "source_state_digest"}
        if state not in {"normal-preflight-reserved", "normal-snapshot-bound"}:
            progression.add("contained_launch_token_digest")
        if state in {"fallback-teardown-pending", "fallback-teardown-complete"}:
            progression.add("containment_failure")
        if state == "fallback-teardown-complete":
            progression.add("teardown_proof")
    elif kind == "normal-fallback":
        progression |= {
            "source_snapshot_digest",
            "source_state_digest",
            "contained_launch_token_digest",
            "containment_failure",
            "teardown_proof",
            "fallback_token_digest",
        }
    elif kind == "recovery-target" and state != "reserved":
        progression.add("launch_claim_id")

    if state == "process-bound-unactivated":
        progression |= {"provider_receipt", "process_receipt"}
    if state == "ordinary-process-bound-unactivated":
        progression.add("process_receipt")
    if state in {"running", "active"}:
        progression |= {"provider_receipt", "process_receipt", "activation_allowed_set_digest"}
    if state == "legacy-running":
        progression |= {"process_receipt", "activation_allowed_set_digest"}
    if state in {"terminal-pending-stop", "stopped-terminal", "handoff-committed"}:
        progression |= {
            "provider_receipt",
            "process_receipt",
            "activation_allowed_set_digest",
            "terminal_receipt",
        }
    if state in {"stopped-terminal", "handoff-committed"}:
        progression.add("zero_proof")
    if state == "handoff-committed":
        progression.add("handoff_digest")
    if not progression.issubset(lease):
        raise RecoveryStateError("recovery registry lease lacks state-specific evidence")

    allowed_extras = set(progression)
    if "prompt_snapshot_id" in lease:
        allowed_extras.add("prompt_snapshot_id")
    if state == "process-bound-unactivated":
        allowed_extras.add("activation_abort")
    if state in {"stopped-terminal", "handoff-committed"}:
        allowed_extras |= {"semantic_disposition", "guardian_close"}
    if set(lease) - base - allowed_extras:
        raise RecoveryStateError("recovery registry lease retains out-of-state evidence")

    for field in (
        "source_snapshot_digest",
        "source_state_digest",
        "contained_launch_token_digest",
        "launch_claim_id",
        "activation_allowed_set_digest",
        "fallback_token_digest",
        "handoff_digest",
    ):
        if field in lease:
            _require_hex(lease[field], f"recovery registry lease {field}")
    if "provider_receipt" in lease:
        _validate_provider_receipt(lease["provider_receipt"])
    if "process_receipt" in lease:
        _validate_process_receipt(lease["process_receipt"])
    if kind in {"normal-contained", "recovery-target"} and "provider_receipt" in lease:
        _validate_contained_process_binding(lease)
    if "activation_abort" in lease:
        abort = _require_exact_object(
            lease["activation_abort"],
            "activation abort",
            {"cause", "expected_snapshot_digest", "observed_snapshot_digest", "error"},
        )
        if abort["cause"] != "provenance-drift":
            raise RecoveryStateError("activation abort cause is unsupported")
        for field in ("expected_snapshot_digest", "observed_snapshot_digest"):
            _require_optional_hex(abort[field], f"activation abort {field}")
        if abort["error"] is not None:
            _require_string(abort["error"], "activation abort error")
    if "containment_failure" in lease:
        _require_string(lease["containment_failure"], "containment failure")
    if "teardown_proof" in lease:
        proof = _require_exact_object(
            lease["teardown_proof"],
            "fallback teardown proof",
            {"tree_empty", "no_user_code"},
        )
        if proof["tree_empty"] is not True or proof["no_user_code"] is not True:
            raise RecoveryStateError("fallback teardown proof is not affirmative")
    if "terminal_receipt" in lease:
        _validate_terminal_receipt(lease["terminal_receipt"])
    if "zero_proof" in lease:
        _validate_zero_proof(lease["zero_proof"])
    if "semantic_disposition" in lease:
        _validate_semantic_disposition(lease["semantic_disposition"])
    if "guardian_close" in lease:
        close = _require_exact_object(
            lease["guardian_close"],
            "guardian close acknowledgement",
            {"closed", "guardian_id", "closed_at"},
        )
        if close["closed"] is not True:
            raise RecoveryStateError("guardian close acknowledgement is not affirmative")
        for field in ("guardian_id", "closed_at"):
            _require_string(close[field], f"guardian close {field}")
    _validate_terminal_identity_binding(lease)


def _validate_outbox(value: Any) -> None:
    outbox = _require_exact_object(
        value,
        "recovery handoff outbox",
        {"event_id", "payload", "digest", "state"},
    )
    _require_hex(outbox["event_id"], "recovery handoff event ID")
    payload = _require_exact_object(
        outbox["payload"],
        "recovery handoff payload",
        {
            "lease_id",
            "run_id",
            "receipt_digest",
            "checkpoint_digest",
            "allowed_set_digest",
            "root_verification_digest",
        },
    )
    _require_string(payload["lease_id"], "recovery handoff lease ID")
    _require_string(payload["run_id"], "recovery handoff run ID")
    for field in (
        "receipt_digest",
        "checkpoint_digest",
        "allowed_set_digest",
        "root_verification_digest",
    ):
        _require_hex(payload[field], f"recovery handoff {field}")
    _require_hex(outbox["digest"], "recovery handoff outbox digest")
    if outbox["digest"] != _domain_digest(
        _DOMAIN_CHECKPOINT, {"event_id": outbox["event_id"], "payload": payload}
    ):
        raise RecoveryStateError("recovery handoff outbox digest drifted")
    if outbox["state"] not in {"pending", "materialized", "archived"}:
        raise RecoveryStateError("recovery handoff outbox state is unsupported")


def _validate_history_event(value: Any) -> None:
    if not isinstance(value, dict):
        raise RecoveryStateError("recovery registry history event must be an object")
    event = value.get("event")
    schemas: dict[str, tuple[set[str], set[str]]] = {
        "unactivated-reservation-released": ({"event", "lease_id"}, set()),
        "reserved-source-snapshot-bound": (
            {"event", "lease_id", "source_state_id", "source_snapshot_digest"},
            set(),
        ),
        "recovery-target-start-failed": (
            {"event", "lease_id", "grant_id", "cause", "proof"},
            set(),
        ),
        "activation-provenance-drift": (
            {
                "event",
                "lease_id",
                "lease_kind",
                "expected_snapshot_digest",
                "observed_snapshot_digest",
            },
            set(),
        ),
        "containment-loss-quarantined": ({"event", "lease_id", "cause"}, set()),
        "containment-loss-reconciled": (
            {
                "event",
                "schema",
                "lease_id",
                "run_id",
                "proof_digest",
                "provider",
                "guardian_id",
                "guardian_pid",
                "guardian_identity",
                "guardian_state",
                "worker_pid",
                "worker_identity",
                "worker_state",
                "terminal_binding_digest",
                "zero_proof_digest",
                "reconciled_at",
            },
            set(),
        ),
        "fallback-launch-quarantined": ({"event", "lease_id", "cause"}, set()),
        "legacy-terminal-released": ({"event", "lease_id", "success"}, set()),
        "semantic-handoff-rejected": (
            {
                "event",
                "lease_id",
                "disposition",
                "evidence_digest",
                "checkpoint_allowed",
                "checkpoint_invalidation",
                "run_id",
                "source_state_id",
            },
            {"checkpoint_digest"},
        ),
        "source-checkpoint-invalidated": (
            {
                "event",
                "lease_id",
                "run_id",
                "source_state_id",
                "checkpoint_digest",
                "evidence_digest",
            },
            set(),
        ),
        "terminal-abandonment-recorded": (
            {
                "event",
                "disposition",
                "schema",
                "cause",
                "evidence_digest",
                "checkpoint_allowed",
                "checkpoint_invalidation",
                "run_id",
                "lease_id",
                "source_state_id",
                "source_checkpoint_digest",
                "allowed_set_digest",
                "terminal_binding_digest",
                "zero_proof_digest",
                "candidate_snapshot_digest",
            },
            set(),
        ),
        "terminal-abandonment-completed": (
            {
                "event",
                "lease_id",
                "run_id",
                "source_state_id",
                "checkpoint_digest",
                "evidence_digest",
            },
            set(),
        ),
        "terminal-root-completion-recorded": (
            {
                "event",
                "disposition",
                "schema",
                "run_id",
                "lease_id",
                "source_state_id",
                "source_checkpoint_digest",
                "allowed_set_digest",
                "remediation_scope_digest",
                "task_commit",
                "parent_commit",
                "root_verification_digest",
                "user_action_digest",
                "authorization_digest",
                "authorization_consumption",
                "terminal_binding_format",
                "terminal_binding_digest",
                "zero_proof_digest",
                "candidate_snapshot_digest",
                "git_provenance_digest",
                "checkpoint_invalidation",
            },
            set(),
        ),
        "terminal-root-completion-completed": (
            {
                "event",
                "lease_id",
                "run_id",
                "source_state_id",
                "checkpoint_digest",
                "authorization_digest",
            },
            set(),
        ),
        "authorization-retired": (
            {
                "event",
                "source_state_id",
                "grant_id",
                "prompt_snapshot_id",
                "prompt_sha256",
            },
            set(),
        ),
    }
    if event == "contained-terminal-released":
        _validate_terminal_archive(value)
        return
    if event not in schemas:
        raise RecoveryStateError("recovery registry history event is unsupported")
    history = _require_exact_object(value, "recovery registry history event", *schemas[event])
    if event != "authorization-retired":
        _require_string(history["lease_id"], "recovery registry history lease ID")
    if event in {"reserved-source-snapshot-bound", "source-checkpoint-invalidated"}:
        _require_hex(history["source_state_id"], "recovery registry history source state ID")
    if event == "reserved-source-snapshot-bound":
        _require_hex(history["source_snapshot_digest"], "history source snapshot digest")
    elif event == "recovery-target-start-failed":
        _require_hex(history["grant_id"], "history recovery grant ID")
        _require_string(history["cause"], "history recovery start cause")
        proof = _require_exact_object(
            history["proof"], "history recovery start proof", {"tree_empty", "no_user_code"}
        )
        if proof["tree_empty"] is not True or proof["no_user_code"] is not True:
            raise RecoveryStateError("history recovery start proof is not affirmative")
    elif event == "activation-provenance-drift":
        if history["lease_kind"] not in {"normal-contained", "recovery-target"}:
            raise RecoveryStateError("history activation lease kind is unsupported")
        for field in ("expected_snapshot_digest", "observed_snapshot_digest"):
            _require_optional_hex(history[field], f"history activation {field}")
    elif event in {"containment-loss-quarantined", "fallback-launch-quarantined"}:
        _require_string(history["cause"], "history quarantine cause")
    elif event == "containment-loss-reconciled":
        if history["schema"] != "containment-loss-reconciliation-v1":
            raise RecoveryStateError("history containment reconciliation schema is unsupported")
        if history["provider"] not in {"windows-job", "linux-cgroup-v2"}:
            raise RecoveryStateError("history containment reconciliation provider is unsupported")
        for field in ("guardian_state", "worker_state"):
            if history[field] not in {"stopped", "reused"}:
                raise RecoveryStateError(
                    "history containment reconciliation original process is not stopped"
                )
        for field in ("guardian_pid", "worker_pid"):
            _require_integer(history[field], f"history containment reconciliation {field}", minimum=1)
        for field in ("guardian_id", "guardian_identity", "worker_identity"):
            _require_string(history[field], f"history containment reconciliation {field}")
        _require_string(history["run_id"], "history containment reconciliation run ID")
        _require_string(history["reconciled_at"], "history containment reconciliation time")
        for field in ("proof_digest", "terminal_binding_digest", "zero_proof_digest"):
            _require_hex(history[field], f"history containment reconciliation {field}")
        proof_basis = dict(history)
        proof_digest = proof_basis.pop("proof_digest")
        proof_basis.pop("event")
        if proof_digest != _domain_digest(
            _DOMAIN_CONTAINMENT_LOSS_RECONCILIATION, proof_basis
        ):
            raise RecoveryStateError("history containment reconciliation proof digest drifted")
    elif event == "legacy-terminal-released":
        _require_boolean(history["success"], "history legacy terminal success")
    elif event == "semantic-handoff-rejected":
        semantic = dict(history)
        semantic.pop("event")
        semantic.pop("lease_id")
        _validate_semantic_disposition(semantic)
    elif event == "source-checkpoint-invalidated":
        _require_string(history["run_id"], "history invalidation run ID")
        _require_hex(history["checkpoint_digest"], "history invalidated checkpoint digest")
        _require_hex(history["evidence_digest"], "history invalidation evidence digest")
    elif event == "terminal-abandonment-recorded":
        semantic = dict(history)
        semantic.pop("event")
        _validate_semantic_disposition(semantic)
        if semantic["checkpoint_invalidation"] != "pending":
            raise RecoveryStateError("terminal abandonment record must begin pending")
    elif event == "terminal-abandonment-completed":
        _require_string(history["run_id"], "terminal abandonment completion run ID")
        _require_hex(history["source_state_id"], "terminal abandonment completion source state ID")
        _require_hex(history["checkpoint_digest"], "terminal abandonment completion checkpoint digest")
        _require_hex(history["evidence_digest"], "terminal abandonment completion evidence digest")
    elif event == "terminal-root-completion-recorded":
        semantic = dict(history)
        semantic.pop("event")
        _validate_semantic_disposition(semantic)
        if semantic["checkpoint_invalidation"] != "pending":
            raise RecoveryStateError("terminal root completion record must begin pending")
    elif event == "terminal-root-completion-completed":
        _require_string(history["run_id"], "terminal root completion run ID")
        _require_hex(history["source_state_id"], "terminal root completion source state ID")
        _require_hex(history["checkpoint_digest"], "terminal root completion checkpoint digest")
        _require_hex(history["authorization_digest"], "terminal root completion authorization digest")
    elif event == "authorization-retired":
        for field in (
            "source_state_id",
            "grant_id",
            "prompt_snapshot_id",
            "prompt_sha256",
        ):
            _require_hex(history[field], f"retired recovery authorization {field}")


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise RecoveryStateError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _default_state_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "openbuild" / "recovery"


def _windows_current_user_sid() -> str:
    import ctypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise RecoveryStateError(f"cannot inspect the current Windows user token: {ctypes.WinError()}")
    try:
        required = ctypes.c_uint32()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise RecoveryStateError(f"cannot size the current Windows user token: {ctypes.WinError()}")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required.value, ctypes.byref(required)):
            raise RecoveryStateError(f"cannot read the current Windows user token: {ctypes.WinError()}")
        sid = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents.user.sid
        value = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(value)):
            raise RecoveryStateError(f"cannot serialize the current Windows user SID: {ctypes.WinError()}")
        try:
            if not value.value:
                raise RecoveryStateError("Windows returned an empty current-user SID")
            return value.value
        finally:
            kernel32.LocalFree(ctypes.cast(value, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _windows_directory_sddl(path: Path) -> str:
    import ctypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetFileSecurityW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    required = ctypes.c_uint32()
    information = 0x00000001 | 0x00000004
    advapi32.GetFileSecurityW(str(path), information, None, 0, ctypes.byref(required))
    if not required.value:
        raise RecoveryStateError(f"cannot size Windows state-directory security: {ctypes.WinError()}")
    descriptor = ctypes.create_string_buffer(required.value)
    if not advapi32.GetFileSecurityW(
        str(path), information, descriptor, required.value, ctypes.byref(required)
    ):
        raise RecoveryStateError(f"cannot read Windows state-directory security: {ctypes.WinError()}")
    value = ctypes.c_wchar_p()
    if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        descriptor, 1, information, ctypes.byref(value), None
    ):
        raise RecoveryStateError(f"cannot serialize Windows state-directory security: {ctypes.WinError()}")
    try:
        return value.value or ""
    finally:
        kernel32.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def _windows_directory_is_private(path: Path, user_sid: str) -> bool:
    sddl = _windows_directory_sddl(path)
    if f"O:{user_sid}" not in sddl or "D:P" not in sddl:
        return False
    dacl = sddl.split("D:", 1)[1]
    aces = set(re.findall(r"\([^)]*\)", dacl))
    return aces == {
        "(A;OICI;FA;;;SY)",
        f"(A;OICI;FA;;;{user_sid})",
    }


def _protect_windows_directory(path: Path, user_sid: str) -> None:
    import ctypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.SetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{user_sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise RecoveryStateError(f"cannot build a private Windows state DACL: {ctypes.WinError()}")
    try:
        if not advapi32.SetFileSecurityW(str(path), 0x00000004 | 0x80000000, descriptor):
            raise RecoveryStateError(f"cannot protect Windows state directory: {ctypes.WinError()}")
    finally:
        kernel32.LocalFree(descriptor)


def _ensure_private_directory(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    if not path.is_dir() or path.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise RecoveryStateError(f"private state directory must be a real directory: {path}")
    if os.name == "nt":
        user_sid = _windows_current_user_sid()
        if not existed:
            _protect_windows_directory(path, user_sid)
        if not _windows_directory_is_private(path, user_sid):
            raise RecoveryStateError(
                f"Windows private state directory must have a protected current-user-only DACL: {path}"
            )
    else:
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise RecoveryStateError(f"private state directory is not owned by the current user: {path}")
        os.chmod(path, 0o700)


def _object_identity(path: Path) -> dict[str, Any]:
    metadata = path.stat()
    return {
        "platform": "windows" if os.name == "nt" else sys.platform,
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
    }


def _reject_snapshot_reparse_point(metadata: Any) -> None:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if attributes & reparse_flag:
        raise RecoveryStateError(
            "Windows reparse point is unsupported in checkpoint inventory"
        )


def _snapshot_metadata_matches(left: Any, right: Any) -> bool:
    return (
        int(left.st_dev),
        int(left.st_ino),
        stat.S_IFMT(int(left.st_mode)),
    ) == (
        int(right.st_dev),
        int(right.st_ino),
        stat.S_IFMT(int(right.st_mode)),
    )


def _windows_open_snapshot_chain(
    workspace: Path,
    relative: str,
    expected_metadata: Any,
) -> list[int]:
    import ctypes

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
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    generic_read = 0x80000000
    share_read_write = 0x00000001 | 0x00000002
    open_existing = 3
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    invalid_handle = ctypes.c_void_p(-1).value
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    parts = relative.split("/")
    candidates = [workspace]
    current = workspace
    for part in parts:
        current = current / part
        candidates.append(current)
    handles: list[int] = []
    try:
        for index, candidate in enumerate(candidates):
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise RecoveryStateError(
                    "checkpoint path changed during snapshot handle acquisition"
                ) from exc
            _reject_snapshot_reparse_point(metadata)
            if index == len(candidates) - 1 and not _snapshot_metadata_matches(
                metadata, expected_metadata
            ):
                raise RecoveryStateError(
                    "checkpoint path changed during snapshot handle acquisition"
                )
            desired_access = (
                generic_read
                if index == len(candidates) - 1
                and stat.S_ISREG(expected_metadata.st_mode)
                else 0
            )
            handle = kernel32.CreateFileW(
                str(candidate),
                desired_access,
                share_read_write,
                None,
                open_existing,
                backup_semantics | open_reparse_point,
                None,
            )
            if handle in (None, invalid_handle):
                raise RecoveryStateError(
                    f"checkpoint path changed during snapshot handle acquisition: {ctypes.WinError(ctypes.get_last_error())}"
                )
            handle_value = int(handle)
            information = ByHandleFileInformation()
            if not kernel32.GetFileInformationByHandle(
                ctypes.c_void_p(handle_value), ctypes.byref(information)
            ):
                kernel32.CloseHandle(ctypes.c_void_p(handle_value))
                raise RecoveryStateError(
                    f"checkpoint handle metadata is unavailable: {ctypes.WinError(ctypes.get_last_error())}"
                )
            if information.attributes & reparse_flag:
                kernel32.CloseHandle(ctypes.c_void_p(handle_value))
                raise RecoveryStateError(
                    "Windows reparse point is unsupported in checkpoint inventory"
                )
            file_index = (
                int(information.file_index_high) << 32
            ) | int(information.file_index_low)
            if int(metadata.st_ino) != file_index:
                kernel32.CloseHandle(ctypes.c_void_p(handle_value))
                raise RecoveryStateError(
                    "checkpoint path changed during snapshot handle acquisition"
                )
            handles.append(handle_value)
        return handles
    except BaseException:
        for handle in reversed(handles):
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _windows_close_snapshot_handles(handles: Sequence[int]) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    for handle in reversed(handles):
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _windows_read_handle_chunks(handle: int) -> Iterator[bytes]:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReadFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(1024 * 1024)
    while True:
        read = ctypes.c_uint32()
        if not kernel32.ReadFile(
            ctypes.c_void_p(handle),
            buffer,
            len(buffer),
            ctypes.byref(read),
            None,
        ):
            raise RecoveryStateError(
                f"checkpoint file read failed: {ctypes.WinError(ctypes.get_last_error())}"
            )
        if read.value == 0:
            return
        yield buffer.raw[: read.value]


def _collation_tag() -> str:
    return "case-insensitive" if os.path.normcase("OpenBuild") == os.path.normcase("openbuild") else "case-sensitive"


def _normalize_relative(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or "\0" in normalized
        or any(part in {"", ".", ".."} for part in parts)
        or (len(parts[0]) >= 2 and parts[0][1] == ":")
    ):
        raise RecoveryStateError("paths must be normalized workspace-relative paths")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RecoveryStateError("paths must be valid UTF-8 after NFC normalization") from exc
    return normalized


def _decode_git_path(value: bytes) -> str:
    try:
        return _normalize_relative(value.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RecoveryStateError("Git returned a non-UTF-8 path; recovery capability is unavailable") from exc


def _decode_ignored_git_path(value: bytes) -> tuple[str, bool]:
    """Decode an ignored entry and preserve Git's trailing-slash directory marker."""
    directory_marker = value.endswith(b"/")
    if directory_marker:
        value = value[:-1]
    return _decode_git_path(value), directory_marker


def _windows_replace_write_through(source: Path, target: Path) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.MoveFileExW.restype = ctypes.c_int
    if not kernel32.MoveFileExW(str(source), str(target), 0x1 | 0x8):
        raise RecoveryStateError(f"write-through registry replace failed: {ctypes.WinError(ctypes.get_last_error())}")


def _replace_write_through(source: Path, target: Path) -> None:
    if os.name == "nt":
        _windows_replace_write_through(source, target)
    else:
        os.replace(source, target)


def _sync_parent_metadata(directory: Path) -> None:
    if os.name == "nt":
        # MoveFileExW(MOVEFILE_WRITE_THROUGH) is the Windows metadata barrier;
        # the resulting file is flushed separately before this point.
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_replace(path: Path, payload: bytes, *, fault: str | None = None) -> None:
    _ensure_private_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            if fault == "before-write":
                raise RecoveryStateError("injected failure before write")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if fault == "after-file-fsync":
            raise RecoveryStateError("injected failure after file fsync")
        _replace_write_through(temporary, path)
        if fault == "after-replace":
            raise RecoveryStateError("injected failure after registry replace")
        with open(path, "r+b") as handle:
            os.fsync(handle.fileno())
        if fault == "before-metadata-barrier":
            raise RecoveryStateError("injected failure before metadata barrier")
        _sync_parent_metadata(path.parent)
        if fault == "after-metadata-barrier":
            raise RecoveryStateError("injected failure after metadata barrier")
    finally:
        if temporary.exists():
            temporary.unlink()


def durable_write_private_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    fault: str | None = None,
) -> None:
    """Durably replace an owner-private JSON record before authority is exposed."""
    _durable_replace(path, _canonical(value) + b"\n", fault=fault)


def durable_write_private_bytes(
    path: Path,
    value: bytes,
    *,
    fault: str | None = None,
) -> None:
    """Durably replace owner-private bytes before a durable reference is written."""
    _durable_replace(path, value, fault=fault)


def _rebarrier(path: Path, expected_digest: str, *, fault: str | None = None) -> None:
    if fault == "reload-before-barrier":
        raise RecoveryStateError("injected failure before reload barrier")
    with open(path, "r+b") as handle:
        os.fsync(handle.fileno())
    _sync_parent_metadata(path.parent)
    if fault == "reload-after-barrier":
        raise RecoveryStateError("injected failure after reload barrier")
    try:
        reread = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryStateError("durable state changed during reload barrier") from exc
    if not isinstance(reread, dict) or reread.get("digest") != expected_digest or _digest(reread) != expected_digest:
        raise RecoveryStateError("durable state changed during reload barrier")


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Hold one owner-private byte lock; callers define a stable lock order."""
    _ensure_private_directory(path.parent)
    handle = open(path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _lease_run_id(lease: Mapping[str, Any]) -> str | None:
    plan = lease.get("plan")
    if lease.get("lease_kind") == "recovery-target" and isinstance(plan, Mapping):
        value = plan.get("run_id")
    else:
        value = lease.get("run_id")
    return value if isinstance(value, str) and value else None


class RecoveryRegistry:
    """One root-stable private registry and its non-authoritative source states."""

    def __init__(
        self,
        workspace: Path,
        *,
        state_root: Path | None = None,
        fault: str | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.workspace = workspace.expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise RecoveryStateError("workspace must resolve to a directory")
        self.root_identity = _object_identity(self.workspace)
        self.collation_tag = _collation_tag()
        self.workspace_key = hashlib.sha256(
            _DOMAIN_WORKSPACE
            + _canonical(
                {
                    "platform": self.root_identity["platform"],
                    "object_identity": self.root_identity,
                    "collation": self.collation_tag,
                }
            )
        ).hexdigest()
        self.state_root = (state_root or _default_state_root()).expanduser().resolve()
        self.directory = self.state_root / "workspaces" / self.workspace_key
        self.path = self.directory / "registry-v1.json"
        self.lock_path = self.directory / "registry-v1.lock"
        self.sources_directory = self.directory / "sources"
        self.fault = fault
        self.max_records = max_records
        self.max_bytes = max_bytes
        if max_records <= 0 or max_bytes <= 0:
            raise RecoveryStateError("checkpoint inventory limits must be positive")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        with _exclusive_file_lock(self.lock_path):
            yield

    def _git(self, *arguments: str, allow_failure: bool = False) -> bytes:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode and not allow_failure:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RecoveryStateError(f"Git provenance command failed: git {' '.join(arguments)}: {message}")
        return completed.stdout if completed.returncode == 0 else b""

    def _git_common_dir_identity(self) -> dict[str, Any] | None:
        raw = self._git("rev-parse", "--git-common-dir", allow_failure=True).strip()
        if not raw:
            return None
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RecoveryStateError("Git common directory is not UTF-8") from exc
        path = Path(value)
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve(strict=True)
        return {"path": str(resolved), "object_identity": _object_identity(resolved)}

    def _empty(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "schema_version": REGISTRY_SCHEMA,
            "identity_version": IDENTITY_VERSION,
            "reader_floor": READER_FLOOR,
            "workspace_key": self.workspace_key,
            "workspace_path": str(self.workspace),
            "root_identity": self.root_identity,
            "collation_tag": self.collation_tag,
            "git_common_dir_identity": self._git_common_dir_identity(),
            "generation": 0,
            "previous_generation_digest": None,
            "epoch": 0,
            "lease": None,
            "outbox": None,
            "history": [],
            "tombstones": [],
            "consumed_grants": [],
            "retired": False,
            "quarantine": None,
        }
        state["digest"] = _digest(state)
        return state

    def _validate_semantic_registry_binding(self, state: Mapping[str, Any]) -> None:
        lease = state.get("lease")
        semantic = lease.get("semantic_disposition") if isinstance(lease, Mapping) else None
        if not isinstance(lease, Mapping) or not isinstance(semantic, Mapping):
            return

        expected_run_id = _lease_run_id(lease)
        if semantic.get("run_id") != expected_run_id:
            raise RecoveryStateError("semantic disposition run binding drifted")
        if semantic.get("source_state_id") != lease.get("source_state_id"):
            raise RecoveryStateError("semantic disposition source binding drifted")

        if semantic.get("disposition") == "abandoned":
            if semantic.get("lease_id") != lease.get("lease_id"):
                raise RecoveryStateError("terminal abandonment lease binding drifted")
            if (
                semantic.get("schema") == "terminal-abandonment-v2"
                and lease.get("lease_kind") != "recovery-target"
            ):
                raise RecoveryStateError("terminal abandonment v2 requires a recovery target lease")
            if (
                semantic.get("schema")
                in {
                    "terminal-abandonment-v3",
                    "terminal-abandonment-v4",
                    "terminal-abandonment-v5",
                }
                and lease.get("lease_kind") != "normal-contained"
            ):
                raise RecoveryStateError(
                    "terminal abandonment v3/v4/v5 requires a normal contained lease"
                )
            recorded = [
                event
                for event in state.get("history", [])
                if event.get("event") == "terminal-abandonment-recorded"
                and event.get("lease_id") == lease.get("lease_id")
                and event.get("run_id") == expected_run_id
            ]
            if len(recorded) != 1:
                raise RecoveryStateError("terminal abandonment requires one recorded history event")
            immutable_recorded_fields = set(recorded[0]) - {
                "event",
                "checkpoint_invalidation",
            }
            if (
                recorded[0].get("checkpoint_invalidation") != "pending"
                or any(
                    recorded[0].get(field) != semantic.get(field)
                    for field in immutable_recorded_fields
                )
            ):
                raise RecoveryStateError("terminal abandonment history binding drifted")
            reconciled = [
                event
                for event in state.get("history", [])
                if event.get("event") == "containment-loss-reconciled"
                and event.get("lease_id") == lease.get("lease_id")
                and event.get("run_id") == expected_run_id
            ]
            if reconciled and (
                len(reconciled) != 1
                or state.get("quarantine") is not None
                or reconciled[0].get("provider")
                != lease.get("provider_receipt", {}).get("provider")
                or reconciled[0].get("guardian_id")
                != lease.get("provider_receipt", {}).get("guardian_id")
                or reconciled[0].get("guardian_pid")
                != lease.get("provider_receipt", {}).get("guardian_pid")
                or reconciled[0].get("guardian_identity")
                != lease.get("provider_receipt", {}).get("guardian_identity")
                or reconciled[0].get("worker_pid")
                != lease.get("process_receipt", {}).get("pid")
                or reconciled[0].get("worker_identity")
                != lease.get("process_receipt", {}).get("identity")
                or reconciled[0].get("terminal_binding_digest")
                != semantic.get("terminal_binding_digest")
                or reconciled[0].get("zero_proof_digest")
                != semantic.get("zero_proof_digest")
            ):
                raise RecoveryStateError("containment-loss reconciliation history binding drifted")
            source = self._read_source_locked(str(semantic["source_state_id"]), rebarrier=True)
            checkpoint = source.get("public_checkpoint")
            candidate = checkpoint.get("candidate_snapshot") if isinstance(checkpoint, Mapping) else None
            candidate_digest = semantic.get("candidate_snapshot_digest")
            if semantic.get("checkpoint_invalidation") == "completed":
                if (
                    not isinstance(candidate, Mapping)
                    or _domain_digest(_DOMAIN_CHECKPOINT, candidate) != candidate_digest
                ):
                    raise RecoveryStateError(
                        "terminal abandonment candidate snapshot binding drifted"
                    )
            expected_evidence = _domain_digest(
                _DOMAIN_TERMINAL_ABANDONMENT,
                {
                    "schema": semantic.get("schema"),
                    "cause": semantic.get("cause"),
                    "run_id": expected_run_id,
                    "lease_id": lease.get("lease_id"),
                    "source_state_id": lease.get("source_state_id"),
                    "source_checkpoint_digest": semantic.get("source_checkpoint_digest"),
                    "allowed_set_digest": lease.get("allowed_set_digest"),
                    "terminal_binding_digest": lease.get("terminal_receipt", {}).get("binding_digest"),
                    "zero_proof_digest": _terminal_part_digest("zero", lease.get("zero_proof", {})),
                    "candidate_snapshot_digest": candidate_digest,
                },
            )
            if semantic.get("evidence_digest") != expected_evidence:
                raise RecoveryStateError("terminal abandonment evidence digest drifted")
            if semantic.get("checkpoint_invalidation") == "completed":
                completed = [
                    event
                    for event in state.get("history", [])
                    if event.get("event") == "terminal-abandonment-completed"
                    and event.get("lease_id") == lease.get("lease_id")
                    and event.get("run_id") == expected_run_id
                ]
                if len(completed) != 1 or any(
                    completed[0].get(field) != semantic.get(field)
                    for field in ("source_state_id", "checkpoint_digest", "evidence_digest")
                ):
                    raise RecoveryStateError("terminal abandonment completion binding drifted")
                invalidation = source.get("checkpoint_invalidation")
                if (
                    not isinstance(checkpoint, Mapping)
                    or checkpoint.get("disposition") != "recovery-ineligible"
                    or checkpoint.get("checkpoint_digest") != semantic.get("checkpoint_digest")
                    or not isinstance(invalidation, Mapping)
                    or invalidation.get("reason")
                    != (
                        "terminal-abandoned-recovery-overlap"
                        if semantic.get("schema") == "terminal-abandonment-v2"
                        else (
                            "terminal-abandoned-legacy-normal-control-plane-overlap"
                            if semantic.get("schema") == "terminal-abandonment-v4"
                            else (
                                "terminal-abandoned-legacy-normal-dirty-overlap"
                                if semantic.get("schema") == "terminal-abandonment-v5"
                                else (
                                    "terminal-abandoned-legacy-normal-overlap"
                                    if semantic.get("schema")
                                    == "terminal-abandonment-v3"
                                    else "terminal-abandoned-outside-set-drift"
                                )
                            )
                        )
                    )
                    or invalidation.get("evidence_digest") != semantic.get("evidence_digest")
                ):
                    raise RecoveryStateError("terminal abandonment source invalidation is not authoritative")
            return

        if semantic.get("disposition") == "root-completed":
            if semantic.get("lease_id") != lease.get("lease_id"):
                raise RecoveryStateError("terminal root completion lease binding drifted")
            recorded = [
                event
                for event in state.get("history", [])
                if event.get("event") == "terminal-root-completion-recorded"
                and event.get("lease_id") == lease.get("lease_id")
                and event.get("run_id") == expected_run_id
            ]
            if len(recorded) != 1:
                raise RecoveryStateError("terminal root completion requires one recorded history event")
            immutable_recorded_fields = set(recorded[0]) - {"event", "checkpoint_invalidation"}
            if (
                recorded[0].get("checkpoint_invalidation") != "pending"
                or any(recorded[0].get(field) != semantic.get(field) for field in immutable_recorded_fields)
            ):
                raise RecoveryStateError("terminal root completion history binding drifted")
            source = self._read_source_locked(str(semantic["source_state_id"]), rebarrier=True)
            checkpoint = source.get("public_checkpoint")
            post = source.get("post_commit_root_completion")
            action = post.get("action") if isinstance(post, Mapping) else None
            authorization = post.get("authorization") if isinstance(post, Mapping) else None
            if (
                not isinstance(action, Mapping)
                or not isinstance(authorization, Mapping)
                or action.get("tuple_digest") != semantic.get("user_action_digest")
                or authorization.get("status") not in {"issued", "consumed"}
                or semantic.get("authorization_consumption") != "consumed"
                or semantic.get("terminal_binding_format") != "run-dir-v1"
                or lease.get("terminal_receipt", {}).get("binding_digest")
                != semantic.get("terminal_binding_digest")
                or _domain_digest(_DOMAIN_POST_COMMIT_AUTHORIZATION, {
                    "action_id": authorization.get("action_id"),
                    "authorization_handle": authorization.get("authorization_handle"),
                    "capability": authorization.get("capability"),
                    "tuple_digest": authorization.get("tuple_digest"),
                }) != semantic.get("authorization_digest")
            ):
                raise RecoveryStateError("terminal root completion authorization binding drifted")
            if semantic.get("checkpoint_invalidation") == "completed":
                completed = [
                    event
                    for event in state.get("history", [])
                    if event.get("event") == "terminal-root-completion-completed"
                    and event.get("lease_id") == lease.get("lease_id")
                    and event.get("run_id") == expected_run_id
                ]
                invalidation = source.get("checkpoint_invalidation")
                if (
                    len(completed) != 1
                    or completed[0].get("checkpoint_digest") != semantic.get("checkpoint_digest")
                    or completed[0].get("authorization_digest") != semantic.get("authorization_digest")
                    or not isinstance(checkpoint, Mapping)
                    or checkpoint.get("disposition") != "recovery-ineligible"
                    or checkpoint.get("checkpoint_digest") != semantic.get("checkpoint_digest")
                    or not isinstance(invalidation, Mapping)
                    or invalidation.get("reason") != "post-commit-root-completed"
                    or invalidation.get("evidence_digest") != semantic.get("authorization_digest")
                ):
                    raise RecoveryStateError("terminal root completion invalidation binding drifted")
            return

        lease_id = lease.get("lease_id")
        run_id = semantic.get("run_id")
        rejections = [
            event
            for event in state.get("history", [])
            if event.get("event") == "semantic-handoff-rejected"
            and event.get("lease_id") == lease_id
            and event.get("run_id") == run_id
        ]
        if len(rejections) != 1:
            raise RecoveryStateError("semantic disposition requires one lease-bound rejection history event")
        rejection = rejections[0]
        for field in (
            "disposition",
            "evidence_digest",
            "checkpoint_allowed",
            "source_state_id",
        ):
            if rejection.get(field) != semantic.get(field):
                raise RecoveryStateError("semantic rejection history binding drifted")
        expected_initial_invalidation = (
            "not-required" if semantic.get("disposition") == "blocked" else "pending"
        )
        if (
            rejection.get("checkpoint_invalidation") != expected_initial_invalidation
            or "checkpoint_digest" in rejection
        ):
            raise RecoveryStateError("semantic rejection history disposition drifted")

        invalidations = [
            event
            for event in state.get("history", [])
            if event.get("event") == "source-checkpoint-invalidated"
            and event.get("lease_id") == lease_id
            and event.get("run_id") == run_id
        ]
        invalidation_state = semantic.get("checkpoint_invalidation")
        if invalidation_state != "completed":
            if invalidations:
                raise RecoveryStateError("checkpoint invalidation history preceded completion")
        elif len(invalidations) != 1:
            raise RecoveryStateError("completed checkpoint invalidation requires one history event")
        elif any(
            invalidations[0].get(field) != semantic.get(field)
            for field in ("source_state_id", "checkpoint_digest", "evidence_digest")
        ):
            raise RecoveryStateError("checkpoint invalidation history binding drifted")

        source = self._read_source_locked(str(semantic["source_state_id"]), rebarrier=True)
        checkpoint = source.get("public_checkpoint")
        source_invalidation = source.get("checkpoint_invalidation")
        if semantic.get("disposition") == "blocked":
            if (
                not isinstance(checkpoint, Mapping)
                or checkpoint.get("disposition") != "recovery-eligible"
                or source_invalidation is not None
            ):
                raise RecoveryStateError("blocked semantic disposition did not retain its checkpoint")
        elif invalidation_state == "completed" and (
            not isinstance(checkpoint, Mapping)
            or checkpoint.get("disposition") != "recovery-ineligible"
            or checkpoint.get("checkpoint_digest") != semantic.get("checkpoint_digest")
            or not isinstance(source_invalidation, Mapping)
            or source_invalidation.get("reason") != "semantic-needs-escalation"
            or source_invalidation.get("evidence_digest") != semantic.get("evidence_digest")
        ):
            raise RecoveryStateError("semantic checkpoint invalidation is not source-authoritative")

    def _validate_registry(self, value: Any) -> dict[str, Any]:
        state = dict(
            _require_exact_object(
                value,
                "recovery registry",
                {
                    "schema_version",
                    "identity_version",
                    "reader_floor",
                    "workspace_key",
                    "workspace_path",
                    "root_identity",
                    "collation_tag",
                    "git_common_dir_identity",
                    "generation",
                    "previous_generation_digest",
                    "epoch",
                    "lease",
                    "outbox",
                    "history",
                    "tombstones",
                    "consumed_grants",
                    "retired",
                    "quarantine",
                    "digest",
                },
            )
        )
        if state.get("schema_version") != REGISTRY_SCHEMA or state.get("identity_version") != IDENTITY_VERSION:
            raise RecoveryStateError("unsupported recovery registry schema or identity version")
        if state.get("reader_floor") not in _LEGACY_READER_FLOORS | {READER_FLOOR}:
            raise RecoveryStateError("recovery registry reader floor is incompatible")
        if state.get("workspace_key") != self.workspace_key:
            raise RecoveryStateError("workspace key collision or root identity drift")
        if state.get("workspace_path") != str(self.workspace):
            raise RecoveryStateError("workspace path binding drifted")
        if state.get("root_identity") != self.root_identity or state.get("collation_tag") != self.collation_tag:
            raise RecoveryStateError("workspace object identity or collation drifted")
        _require_integer(state.get("generation"), "recovery registry generation", minimum=1)
        _require_hex(
            state.get("previous_generation_digest"),
            "recovery registry previous generation digest",
        )
        _require_integer(state.get("epoch"), "recovery registry epoch")
        if state.get("digest") != _digest(state):
            raise RecoveryStateError("recovery registry digest drifted")
        if state["lease"] is not None:
            _validate_lease(state["lease"])
        if state["outbox"] is not None:
            _validate_outbox(state["outbox"])
            lease = state.get("lease")
            payload = state["outbox"]["payload"]
            if (
                not isinstance(lease, dict)
                or lease.get("state") != "handoff-committed"
                or lease.get("handoff_digest") != state["outbox"].get("digest")
                or payload.get("lease_id") != lease.get("lease_id")
                or payload.get("allowed_set_digest") != lease.get("allowed_set_digest")
                or (
                    lease.get("run_id") is not None
                    and payload.get("run_id") != lease.get("run_id")
                )
            ):
                raise RecoveryStateError("recovery handoff outbox is not lease-bound")
        if state["lease"] is None and state["outbox"] is not None:
            raise RecoveryStateError("recovery handoff outbox outlived its lease")
        if not isinstance(state.get("history"), list):
            raise RecoveryStateError("recovery registry history must be a list")
        for event in state["history"]:
            _validate_history_event(event)
        self._validate_semantic_registry_binding(state)
        if not isinstance(state["tombstones"], list):
            raise RecoveryStateError("recovery registry tombstones must be a list")
        for tombstone in state["tombstones"]:
            if tombstone.get("event") == "registry-retired":
                item = _require_exact_object(
                    tombstone,
                    "recovery registry tombstone",
                    {"event", "target_version"},
                )
                _version_tuple(_require_string(item["target_version"], "registry retirement target"))
            elif tombstone.get("event") == "prompt-snapshot-released":
                item = _require_exact_object(
                    tombstone,
                    "prompt snapshot release tombstone",
                    {"event", "prompt_snapshot_id", "prompt_sha256"},
                )
                _require_hex(item["prompt_snapshot_id"], "released prompt snapshot ID")
                _require_hex(item["prompt_sha256"], "released prompt SHA-256")
            else:
                raise RecoveryStateError("recovery registry tombstone event is unsupported")
        if not isinstance(state["consumed_grants"], list):
            raise RecoveryStateError("recovery registry consumed grants must be a list")
        seen_grants: set[str] = set()
        for consumed in state["consumed_grants"]:
            item = _require_exact_object(
                consumed,
                "consumed recovery grant",
                {
                    "grant_id",
                    "authorization_nonce_digest",
                    "authorization_epoch",
                    "checkpoint_digest",
                    "allowed_set_digest",
                },
                {"prompt_snapshot_id", "prompt_sha256"},
            )
            for field in (
                "grant_id",
                "authorization_nonce_digest",
                "checkpoint_digest",
                "allowed_set_digest",
            ):
                _require_hex(item[field], f"consumed recovery grant {field}")
            _require_integer(item["authorization_epoch"], "consumed recovery grant epoch")
            if ("prompt_snapshot_id" in item) != ("prompt_sha256" in item):
                raise RecoveryStateError("consumed recovery grant prompt binding is incomplete")
            for field in ("prompt_snapshot_id", "prompt_sha256"):
                if field in item:
                    _require_hex(item[field], f"consumed recovery grant {field}")
            if item["grant_id"] in seen_grants:
                raise RecoveryStateError("consumed recovery grant is duplicated")
            seen_grants.add(item["grant_id"])
        lease = state.get("lease")
        if isinstance(lease, Mapping) and lease.get("lease_kind") == "recovery-target":
            plan = lease.get("plan")
            if isinstance(plan, Mapping) and "prompt_snapshot_id" in plan:
                source = self._read_source_locked(str(lease.get("source_state_id")), rebarrier=True)
                authorization = source.get("authorization")
                consumed = next(
                    (item for item in state["consumed_grants"] if item.get("grant_id") == lease.get("grant_id")),
                    None,
                )
                retired_authorization = next(
                    (
                        event
                        for event in state["history"]
                        if event.get("event") == "authorization-retired"
                        and event.get("source_state_id") == lease.get("source_state_id")
                        and event.get("grant_id") == lease.get("grant_id")
                    ),
                    None,
                )
                authority = (
                    authorization
                    if isinstance(authorization, Mapping)
                    else (
                        retired_authorization
                        if isinstance(retired_authorization, Mapping)
                        else consumed
                    )
                )
                if not isinstance(authority, Mapping) or not isinstance(consumed, Mapping):
                    raise RecoveryStateError("recovery prompt binding lacks authorization evidence")
                if any(
                    authority.get(field) != plan.get(field) or consumed.get(field) != plan.get(field)
                    for field in ("prompt_snapshot_id", "prompt_sha256")
                ):
                    raise RecoveryStateError("recovery prompt binding drifted")
        _require_boolean(state["retired"], "recovery registry retirement state")
        if state["retired"] and (
            state["lease"] is not None
            or state["outbox"] is not None
            or not state["tombstones"]
        ):
            raise RecoveryStateError("retired recovery registry is not exactly vacant")
        allowed_quarantines = {
            "git-common-dir-drift",
            "containment-loss-after-boundary",
            "fallback-launch-ambiguous",
            "handoff-trace-unreadable",
            "handoff-trace-mismatch",
        }
        if state["quarantine"] is not None:
            if (
                not isinstance(state["quarantine"], str)
                or state["quarantine"] not in allowed_quarantines
            ):
                raise RecoveryStateError("recovery registry quarantine state is unsupported")
        return state

    def _read_registry_locked(self, *, rebarrier: bool = False, allow_quarantine: bool = False) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            state = self._validate_registry(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryStateError("recovery registry is unreadable") from exc
        current_git = self._git_common_dir_identity()
        if state.get("git_common_dir_identity") != current_git:
            if state.get("quarantine") is None:
                state["quarantine"] = "git-common-dir-drift"
                self._commit_registry_locked(state)
            raise RecoveryStateError("Git common-directory identity drifted; registry is quarantined")
        if state.get("quarantine") is not None and not allow_quarantine:
            raise RecoveryStateError(f"recovery registry is quarantined: {state['quarantine']}")
        if rebarrier:
            _rebarrier(self.path, state["digest"], fault=self.fault)
            state = self._validate_registry(json.loads(self.path.read_text(encoding="utf-8")))
        return state

    def _read_registry_for_write_locked(
        self,
        *,
        rebarrier: bool = True,
        allow_quarantine: bool = False,
    ) -> dict[str, Any]:
        """Make the current reader floor durable before any owner-state write."""
        existed = self.path.exists()
        state = self._read_registry_locked(
            rebarrier=rebarrier and existed,
            allow_quarantine=allow_quarantine,
        )
        if not existed or state.get("reader_floor") != READER_FLOOR:
            state = self._commit_registry_locked(state, resolve_visible_commit=True)
        return state

    def _commit_registry_locked(
        self,
        state: dict[str, Any],
        *,
        rotate_epoch: bool = False,
        resolve_visible_commit: bool = False,
    ) -> dict[str, Any]:
        previous = state.get("digest")
        state = dict(state)
        # Reading an explicitly supported legacy generation never rewrites it.
        # Any durable transition made by this reader raises the floor atomically.
        state["reader_floor"] = READER_FLOOR
        state["previous_generation_digest"] = previous
        state["generation"] = int(state.get("generation", 0)) + 1
        if rotate_epoch:
            state["epoch"] = int(state.get("epoch", 0)) + 1
        state["digest"] = _digest(state)
        self._validate_registry(state)
        try:
            _durable_replace(self.path, _canonical(state) + b"\n", fault=self.fault)
        except (OSError, RecoveryStateError):
            if not resolve_visible_commit:
                raise
            try:
                visible = self._validate_registry(
                    json.loads(self.path.read_text(encoding="utf-8"))
                )
                if visible["digest"] != state["digest"]:
                    raise RecoveryStateError(
                        "registry replacement did not expose the expected generation"
                    )
                _rebarrier(self.path, state["digest"])
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecoveryStateError):
                raise
        reread = self._validate_registry(json.loads(self.path.read_text(encoding="utf-8")))
        if reread["digest"] != state["digest"]:
            raise RecoveryStateError("registry generation changed during durable replacement")
        return reread

    def initialize(self) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=self.path.exists())
            if not self.path.exists():
                state = self._commit_registry_locked(state)
            return state

    def state(self) -> dict[str, Any]:
        with self._lock():
            return self._read_registry_locked(allow_quarantine=True)

    def state_for_activation(self) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            if state.get("retired"):
                raise RecoveryStateError("recovery registry is retired")
            return state

    @staticmethod
    def _is_vacant(state: Mapping[str, Any]) -> bool:
        return state.get("lease") is None and state.get("outbox") is None

    def assert_reader_compatible(self, version: str) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=self.path.exists(), allow_quarantine=True)
            if _version_tuple(version) < _version_tuple(READER_FLOOR) and not state.get("retired"):
                raise RecoveryStateError(
                    f"reader floor {READER_FLOOR} blocks downgrade to {version} before explicit retirement"
                )
            return state

    def retire_for_downgrade(self, target_version: str) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            if _version_tuple(target_version) >= _version_tuple(READER_FLOOR):
                raise RecoveryStateError("registry retirement is only valid below the reader floor")
            if not self._is_vacant(state):
                raise RecoveryStateError("registry must be exactly vacant before retirement")
            state["retired"] = True
            state["tombstones"].append({"event": "registry-retired", "target_version": target_version})
            return self._commit_registry_locked(state, rotate_epoch=True)

    def mark_prompt_snapshot_released(
        self,
        prompt_snapshot_id: str,
        prompt_sha256: str,
    ) -> dict[str, Any]:
        """Mark a snapshot collectable after the private run copy is durable."""
        _require_hex(prompt_snapshot_id, "released prompt snapshot ID")
        _require_hex(prompt_sha256, "released prompt SHA-256")
        tombstone = {
            "event": "prompt-snapshot-released",
            "prompt_snapshot_id": prompt_snapshot_id,
            "prompt_sha256": prompt_sha256,
        }
        with self._lock():
            state = self._read_registry_locked(rebarrier=self.path.exists())
            for existing in state["tombstones"]:
                if (
                    existing.get("event") == "prompt-snapshot-released"
                    and existing.get("prompt_snapshot_id") == prompt_snapshot_id
                ):
                    if existing != tombstone:
                        raise RecoveryStateError("released prompt snapshot binding drifted")
                    return state
            state["tombstones"].append(tombstone)
            return self._commit_registry_locked(state, resolve_visible_commit=True)

    def reserve_normal(
        self,
        lease_id: str,
        *,
        allowed_set_digest: str,
        recovery_capable: bool,
        source_state_id: str | None = None,
        run_id: str | None = None,
        prompt_snapshot_id: str | None = None,
        prompt_sha256: str | None = None,
        containment_plan: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=self.path.exists())
            if state.get("retired") or not self._is_vacant(state):
                raise RecoveryStateError("workspace is not vacant")
            if allowed_set_digest:
                _require_hex(allowed_set_digest, "allowed_set_digest")
            if recovery_capable and not allowed_set_digest:
                raise RecoveryStateError("a recovery-capable normal lease requires an allowed-set digest")
            if prompt_snapshot_id is not None:
                _require_hex(prompt_snapshot_id, "normal prompt snapshot ID")
                if prompt_sha256 is None:
                    raise RecoveryStateError("normal prompt snapshot binding is incomplete")
                _require_hex(prompt_sha256, "normal prompt SHA-256")
            state["lease"] = {
                "lease_id": lease_id,
                "lease_kind": "normal-contained" if recovery_capable else "normal-legacy",
                "recovery_capable": bool(recovery_capable),
                "state": "normal-preflight-reserved" if recovery_capable else "reserved",
                "allowed_set_digest": allowed_set_digest,
                "source_state_id": source_state_id,
                "run_id": run_id,
                "prompt_snapshot_id": prompt_snapshot_id,
                "prompt_sha256": prompt_sha256,
                "containment_plan": dict(containment_plan or {}),
            }
            return self._commit_registry_locked(state, rotate_epoch=True)

    def release_unactivated_reservation(self, lease_id: str) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state")
                not in {"reserved", "normal-preflight-reserved", "normal-snapshot-bound"}
            ):
                raise RecoveryStateError("cannot release a non-reserved implementation lease")
            state["history"].append({"event": "unactivated-reservation-released", "lease_id": lease_id})
            state["lease"] = None
            return self._commit_registry_locked(state, rotate_epoch=True)

    def bind_reserved_source_snapshot(
        self,
        lease_id: str,
        preflight: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Re-capture and bind the source baseline after the normal lease is durable."""
        source_state_id = preflight.get("source_state_id")
        if not isinstance(source_state_id, str):
            raise RecoveryStateError("source preflight state ID is missing")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") != "normal-contained"
                or lease.get("state") != "normal-preflight-reserved"
                or lease.get("source_state_id") != source_state_id
            ):
                raise RecoveryStateError("reserved source lease binding drifted")
            source = self._read_source_locked(source_state_id)
            stored_preflight = source.get("public_preflight")
            if (
                not isinstance(stored_preflight, dict)
                or preflight.get("preflight_digest") != stored_preflight.get("preflight_digest")
                or lease.get("allowed_set_digest") != source.get("pre_snapshot", {}).get(
                    "allowed_set_digest"
                )
                or source.get("source_binding", {}).get("source_lease_id") != lease_id
            ):
                raise RecoveryStateError("reserved source preflight binding drifted")
            key = bytes.fromhex(source["checkpoint_key"])
            current = self._capture_snapshot(
                key=key,
                allowed_paths=source["pre_snapshot"]["allowed_paths"],
            )
            if current != source["pre_snapshot"]:
                raise RecoveryStateError(
                    "workspace changed before the reserved source boundary"
                )
            lease["source_snapshot_digest"] = _digest(current)
            lease["source_state_digest"] = source["digest"]
            lease["state"] = "normal-snapshot-bound"
            state["history"].append(
                {
                    "event": "reserved-source-snapshot-bound",
                    "lease_id": lease_id,
                    "source_state_id": source_state_id,
                    "source_snapshot_digest": lease["source_snapshot_digest"],
                }
            )
            return self._commit_registry_locked(state)

    def rotate_epoch_for_test(self) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            return self._commit_registry_locked(state, rotate_epoch=True)

    def source_path(self, source_state_id: str) -> Path:
        _require_hex(source_state_id, "source_state_id")
        return self.sources_directory / f"{source_state_id}.json"

    def public_checkpoint_for_source(self, source_state_id: str) -> dict[str, Any]:
        with self._lock():
            self._read_registry_locked(rebarrier=True)
            source = self._read_source_locked(source_state_id)
            checkpoint = source.get("public_checkpoint")
            if not isinstance(checkpoint, dict):
                raise RecoveryStateError("source checkpoint is not terminally bound")
            return dict(checkpoint)

    def assert_checkpoint_allowed_paths(
        self,
        checkpoint: Mapping[str, Any],
        allowed_paths: Sequence[str],
    ) -> None:
        stored_paths = self.checkpoint_allowed_paths(checkpoint)
        normalized = sorted({_normalize_relative(value) for value in allowed_paths})
        if normalized != stored_paths:
            raise RecoveryStateError("recovery target allowed paths drifted")

    def checkpoint_allowed_paths(
        self,
        checkpoint: Mapping[str, Any],
    ) -> list[str]:
        source_state_id = checkpoint.get("source_state_id")
        if not isinstance(source_state_id, str):
            raise RecoveryStateError("checkpoint source state ID is missing")
        with self._lock():
            self._read_registry_locked(rebarrier=True)
            source = self._read_source_locked(source_state_id)
            stored = source.get("public_checkpoint")
            if not isinstance(stored, dict) or checkpoint.get("checkpoint_digest") != stored.get(
                "checkpoint_digest"
            ):
                raise RecoveryStateError("checkpoint digest drifted")
            allowed = source.get("pre_snapshot", {}).get("allowed_paths")
            if not isinstance(allowed, list) or not all(
                isinstance(path, str) for path in allowed
            ):
                raise RecoveryStateError("recovery target allowed paths are invalid")
            return list(allowed)

    def _validate_source(self, value: Any, source_state_id: str) -> dict[str, Any]:
        state = dict(
            _require_exact_object(
                value,
                "private recovery source state",
                {
                    "schema_version",
                    "workspace_key",
                    "source_state_id",
                    "generation",
                    "previous_generation_digest",
                    "checkpoint_key",
                    "checkpoint_key_id",
                    "source_binding",
                    "pre_snapshot",
                    "candidate_snapshot",
                    "public_preflight",
                    "public_checkpoint",
                    "authorization",
                    "digest",
                },
                {"checkpoint_invalidation", "post_commit_root_completion"},
            )
        )
        if state.get("schema_version") != 1 or state.get("workspace_key") != self.workspace_key:
            raise RecoveryStateError("private recovery source state binding drifted")
        if state.get("source_state_id") != source_state_id or state.get("digest") != _digest(state):
            raise RecoveryStateError("private recovery source digest drifted")
        _require_hex(state["source_state_id"], "private recovery source state ID")
        _require_integer(state["generation"], "private recovery source generation", minimum=1)
        _require_hex(
            state["previous_generation_digest"],
            "private recovery source previous generation digest",
        )
        key = bytes.fromhex(_require_hex(state["checkpoint_key"], "private checkpoint key"))
        checkpoint_key_id = hashlib.sha256(_DOMAIN_KEY_ID + key).hexdigest()
        if state["checkpoint_key_id"] != checkpoint_key_id:
            raise RecoveryStateError("private checkpoint key ID drifted")
        binding = _validate_source_binding(state["source_binding"])
        initial_binding = dict(binding)
        initial_binding["source_receipt_digest"] = None
        expected_source_state_id = _keyed_id(key, _DOMAIN_SOURCE, initial_binding)
        if expected_source_state_id != source_state_id:
            raise RecoveryStateError("private source state ID drifted from its binding")

        _validate_private_snapshot(state["pre_snapshot"], "private source pre-snapshot")
        if state["candidate_snapshot"] is not None:
            _validate_private_snapshot(
                state["candidate_snapshot"], "private source candidate snapshot"
            )
        _validate_public_preflight(state["public_preflight"])
        preflight = state["public_preflight"]
        if (
            preflight["source_state_id"] != source_state_id
            or preflight["source_binding_id"] != expected_source_state_id
            or preflight["checkpoint_key_id"] != checkpoint_key_id
            or preflight["allowed_set_digest"] != state["pre_snapshot"]["allowed_set_digest"]
            or preflight["pre_snapshot"] != state["pre_snapshot"]["public"]
        ):
            raise RecoveryStateError("public recovery preflight binding drifted")

        checkpoint = state["public_checkpoint"]
        if checkpoint is not None:
            _validate_public_checkpoint(checkpoint)
            current_binding_id = _keyed_id(key, _DOMAIN_SOURCE, binding)
            projected_candidate = checkpoint["candidate_snapshot"]
            private_candidate_public = (
                state["candidate_snapshot"]["public"]
                if state["candidate_snapshot"] is not None
                else None
            )
            if projected_candidate is not None:
                projected_candidate = dict(projected_candidate)
                projected_candidate["outside_set_delta"] = []
            if (
                binding["source_receipt_digest"] is None
                or checkpoint["source_state_id"] != source_state_id
                or checkpoint["source_binding_id"] != current_binding_id
                or checkpoint["checkpoint_key_id"] != checkpoint_key_id
                or checkpoint["allowed_set_digest"]
                != state["pre_snapshot"]["allowed_set_digest"]
                or checkpoint["pre_snapshot"] != state["pre_snapshot"]["public"]
                or (
                    state["candidate_snapshot"] is None
                    and checkpoint["candidate_snapshot"] is not None
                )
                or (
                    state["candidate_snapshot"] is not None
                    and projected_candidate != private_candidate_public
                )
            ):
                raise RecoveryStateError("public recovery checkpoint binding drifted")
        elif binding["source_receipt_digest"] is not None:
            raise RecoveryStateError("terminal source binding lacks a public checkpoint")

        authorization = state["authorization"]
        if authorization is not None:
            _validate_private_authorization(authorization)
            if (
                checkpoint is None
                or authorization["source_receipt_digest"] != binding["source_receipt_digest"]
                or authorization["checkpoint_digest"] != checkpoint["checkpoint_digest"]
                or authorization["allowed_set_digest"] != checkpoint["allowed_set_digest"]
                or authorization["target_milestone"] != checkpoint["target_milestone"]
                or authorization["specification_revision"]
                != binding["specification_revision"]
            ):
                raise RecoveryStateError("private recovery authorization binding drifted")
        if "checkpoint_invalidation" in state:
            invalidation = _require_exact_object(
                state["checkpoint_invalidation"],
                "private checkpoint invalidation",
                {"reason", "evidence_digest"},
            )
            if invalidation["reason"] not in {
                "semantic-needs-escalation",
                "terminal-abandoned-outside-set-drift",
                "terminal-abandoned-recovery-overlap",
                "terminal-abandoned-legacy-normal-overlap",
                "terminal-abandoned-legacy-normal-dirty-overlap",
                "terminal-abandoned-legacy-normal-control-plane-overlap",
                "post-commit-root-completed",
            }:
                raise RecoveryStateError("private checkpoint invalidation reason is unsupported")
            _require_hex(invalidation["evidence_digest"], "checkpoint invalidation evidence")
            if (
                checkpoint is None
                or checkpoint["disposition"] != "recovery-ineligible"
                or checkpoint["reasons"] != [invalidation["reason"]]
            ):
                raise RecoveryStateError("private checkpoint invalidation binding drifted")
        post_commit = state.get("post_commit_root_completion")
        if post_commit is not None:
            post_commit = _require_exact_object(
                post_commit,
                "private post-commit root completion state",
                {"action", "authorization"},
            )
            action = post_commit["action"]
            authorization = post_commit["authorization"]
            action_value = _require_exact_object(
                action,
                "private post-commit root completion action",
                {
                    "schema",
                    "status",
                    "action_id",
                    "session_action_id",
                    "normalized_intent",
                    "workspace_identity_digest",
                    "action_snapshot_id",
                    "action_snapshot_sha256",
                    "tuple_digest",
                    "run_id",
                    "task_commit",
                    "root_verification_digest",
                    "source_checkpoint_digest",
                    "producer_allowed_set_digest",
                    "remediation_scope_digest",
                    "specification_revision",
                    "milestone",
                },
            )
            if (
                action_value["schema"] != "post-commit-root-completion-user-action-v1"
                or action_value["status"] not in {"confirmed", "issued"}
                or action_value["normalized_intent"]
                != "authorize-post-commit-root-completion"
                or action_value["workspace_identity_digest"] != self.workspace_key
                or checkpoint is None
                or (
                    action_value["source_checkpoint_digest"] != checkpoint["checkpoint_digest"]
                    and (
                        not isinstance(state.get("checkpoint_invalidation"), Mapping)
                        or state["checkpoint_invalidation"].get("reason")
                        != "post-commit-root-completed"
                    )
                )
                or action_value["producer_allowed_set_digest"]
                != checkpoint["allowed_set_digest"]
                or action_value["specification_revision"] != binding["specification_revision"]
                or action_value["milestone"] != binding["source_milestone"]
                or (authorization is None) != (action_value["status"] == "confirmed")
            ):
                raise RecoveryStateError("private post-commit root completion action binding drifted")
            for field in (
                "action_id",
                "session_action_id",
                "workspace_identity_digest",
                "action_snapshot_id",
                "action_snapshot_sha256",
                "tuple_digest",
                "root_verification_digest",
                "source_checkpoint_digest",
                "producer_allowed_set_digest",
                "remediation_scope_digest",
            ):
                _require_hex(action_value[field], f"post-commit root completion action {field}")
            _require_string(action_value["run_id"], "post-commit root completion action run ID")
            _require_git_sha(action_value["task_commit"], "post-commit root completion action task commit")
            if authorization is not None:
                authorization_value = _require_exact_object(
                    authorization,
                    "private post-commit root completion authorization",
                    {
                        "schema",
                        "status",
                        "action_id",
                        "authorization_handle",
                        "capability",
                        "tuple_digest",
                        "issued_at_ns",
                        "expires_at_ns",
                    },
                )
                if (
                    authorization_value["schema"] != "post-commit-root-completion-authorization-v1"
                    or authorization_value["status"] not in {"issued", "consumed"}
                    or authorization_value["action_id"] != action_value["action_id"]
                    or authorization_value["tuple_digest"] != action_value["tuple_digest"]
                    or authorization_value["expires_at_ns"] < authorization_value["issued_at_ns"]
                ):
                    raise RecoveryStateError("private post-commit root completion authorization binding drifted")
                for field in ("authorization_handle", "capability", "tuple_digest"):
                    _require_hex(authorization_value[field], f"post-commit root completion authorization {field}")
                _require_integer(authorization_value["issued_at_ns"], "post-commit root completion issued time")
                _require_integer(authorization_value["expires_at_ns"], "post-commit root completion expiry")
        return state

    def _read_source_locked(self, source_state_id: str, *, rebarrier: bool = True) -> dict[str, Any]:
        path = self.source_path(source_state_id)
        try:
            state = self._validate_source(json.loads(path.read_text(encoding="utf-8")), source_state_id)
        except FileNotFoundError as exc:
            raise RecoveryStateError("private recovery source state is missing") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryStateError("private recovery source state is unreadable") from exc
        if rebarrier:
            _rebarrier(path, state["digest"])
            state = self._validate_source(json.loads(path.read_text(encoding="utf-8")), source_state_id)
        return state

    def _commit_source_locked(self, state: dict[str, Any]) -> dict[str, Any]:
        registry = self._read_registry_locked(rebarrier=False)
        if not self.path.exists() or registry.get("reader_floor") != READER_FLOOR:
            raise RecoveryStateError(
                "private source write requires a durable current reader floor"
            )
        state = dict(state)
        state["previous_generation_digest"] = state.get("digest")
        state["generation"] = int(state.get("generation", 0)) + 1
        state["digest"] = _digest(state)
        self._validate_source(state, state["source_state_id"])
        path = self.source_path(state["source_state_id"])
        _durable_replace(path, _canonical(state) + b"\n", fault=self.fault)
        return self._validate_source(json.loads(path.read_text(encoding="utf-8")), state["source_state_id"])

    def read_private_source(self, source_state_id: str) -> dict[str, Any]:
        with self._lock():
            return self._read_source_locked(source_state_id)

    def _parse_index(self, raw: bytes) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for item in raw.split(b"\0"):
            if not item:
                continue
            try:
                tag, tagged_item = item.split(b" ", 1)
                metadata, raw_path = tagged_item.split(b"\t", 1)
                mode, object_id, stage = metadata.decode("ascii").split(" ")
            except (ValueError, UnicodeDecodeError) as exc:
                raise RecoveryStateError("Git full-index inventory is malformed") from exc
            if tag != b"H":
                raise RecoveryStateError(
                    "Git index contains a status-suppressing index flag; recovery capability is unavailable"
                )
            entries.append(
                {
                    "tag": tag.decode("ascii"),
                    "mode": mode,
                    "object_id": object_id,
                    "stage": stage,
                    "path": _decode_git_path(raw_path),
                }
            )
        return entries

    def _parse_status(self, raw: bytes) -> list[dict[str, Any]]:
        items = raw.split(b"\0")
        entries: list[dict[str, Any]] = []
        index = 0
        while index < len(items):
            item = items[index]
            index += 1
            if not item:
                continue
            if item.startswith((b"? ", b"! ")):
                entries.append({"kind": item[:1].decode("ascii"), "path": _decode_git_path(item[2:])})
                continue
            if item.startswith(b"1 "):
                parts = item.split(b" ", 8)
                if len(parts) != 9:
                    raise RecoveryStateError("Git porcelain-v2 ordinary record is malformed")
                entries.append({"kind": "1", "metadata": b" ".join(parts[:8]).decode("ascii"), "path": _decode_git_path(parts[8])})
                continue
            if item.startswith(b"2 "):
                parts = item.split(b" ", 9)
                if len(parts) != 10 or index >= len(items):
                    raise RecoveryStateError("Git porcelain-v2 rename record is malformed")
                original = items[index]
                index += 1
                entries.append(
                    {
                        "kind": "2",
                        "metadata": b" ".join(parts[:9]).decode("ascii"),
                        "path": _decode_git_path(parts[9]),
                        "original_path": _decode_git_path(original),
                    }
                )
                continue
            if item.startswith(b"u "):
                parts = item.split(b" ", 10)
                if len(parts) != 11:
                    raise RecoveryStateError("Git porcelain-v2 unmerged record is malformed")
                entries.append({"kind": "u", "metadata": b" ".join(parts[:10]).decode("ascii"), "path": _decode_git_path(parts[10])})
                continue
            raise RecoveryStateError("Git porcelain-v2 returned an unknown record")
        return entries

    @contextmanager
    def _hold_snapshot_object(
        self,
        relative: str,
        expected_metadata: Any,
        *,
        parent_fd: int | None = None,
        leaf_name: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        relative = _normalize_relative(relative)
        if os.name == "nt":
            handles = _windows_open_snapshot_chain(
                self.workspace, relative, expected_metadata
            )
            try:
                yield {
                    "windows_handle": handles[-1],
                    "fd": None,
                    "parent_fd": None,
                    "leaf": relative.rsplit("/", 1)[-1],
                }
                _, current_metadata, _ = self._lstat_snapshot_path(relative)
                if current_metadata is None or not _snapshot_metadata_matches(
                    current_metadata, expected_metadata
                ):
                    raise RecoveryStateError(
                        "checkpoint path changed during snapshot"
                    )
            finally:
                _windows_close_snapshot_handles(handles)
            return

        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        owned_fds: list[int] = []
        try:
            if parent_fd is None:
                current_fd = os.open(
                    self.workspace,
                    os.O_RDONLY | directory | nofollow | cloexec,
                )
                owned_fds.append(current_fd)
                parts = relative.split("/")
                for part in parts[:-1]:
                    current_fd = os.open(
                        part,
                        os.O_RDONLY | directory | nofollow | cloexec,
                        dir_fd=current_fd,
                    )
                    owned_fds.append(current_fd)
                final_parent_fd = current_fd
                final_leaf = parts[-1]
            else:
                if leaf_name is None:
                    raise RecoveryStateError(
                        "checkpoint relative handle is missing its leaf"
                    )
                final_parent_fd = parent_fd
                final_leaf = leaf_name

            final_fd: int | None = None
            if not stat.S_ISLNK(expected_metadata.st_mode):
                flags = os.O_RDONLY | nofollow | cloexec
                if stat.S_ISDIR(expected_metadata.st_mode):
                    flags |= directory
                final_fd = os.open(final_leaf, flags, dir_fd=final_parent_fd)
                owned_fds.append(final_fd)
                if not _snapshot_metadata_matches(
                    os.fstat(final_fd), expected_metadata
                ):
                    raise RecoveryStateError(
                        "checkpoint path changed during snapshot handle acquisition"
                    )

            yield {
                "windows_handle": None,
                "fd": final_fd,
                "parent_fd": final_parent_fd,
                "leaf": final_leaf,
            }
            current_metadata = os.stat(
                final_leaf,
                dir_fd=final_parent_fd,
                follow_symlinks=False,
            )
            if not _snapshot_metadata_matches(current_metadata, expected_metadata):
                raise RecoveryStateError("checkpoint path changed during snapshot")
            if parent_fd is None:
                _, visible_metadata, _ = self._lstat_snapshot_path(relative)
                if visible_metadata is None or not _snapshot_metadata_matches(
                    visible_metadata, expected_metadata
                ):
                    raise RecoveryStateError(
                        "checkpoint path changed during snapshot"
                    )
        except RecoveryStateError:
            raise
        except OSError as exc:
            raise RecoveryStateError(
                "checkpoint path changed during snapshot handle acquisition"
            ) from exc
        finally:
            for descriptor in reversed(owned_fds):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _hash_file(
        self,
        path: Path,
        key: bytes,
        budget: dict[str, int],
        *,
        relative: str,
        expected_metadata: Any,
        parent_fd: int | None = None,
        leaf_name: str | None = None,
    ) -> tuple[str, str]:
        raw_hash = hashlib.sha256()
        keyed_hash = hmac.new(key, _DOMAIN_CONTENT, hashlib.sha256)
        with self._hold_snapshot_object(
            relative,
            expected_metadata,
            parent_fd=parent_fd,
            leaf_name=leaf_name,
        ) as held:
            if os.name == "nt":
                chunks = _windows_read_handle_chunks(held["windows_handle"])
            else:
                descriptor = held["fd"]
                if descriptor is None:
                    raise RecoveryStateError(
                        "checkpoint file handle is unavailable"
                    )

                def read_chunks() -> Iterator[bytes]:
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            return
                        yield chunk

                chunks = read_chunks()
            for chunk in chunks:
                budget["bytes"] += len(chunk)
                if budget["bytes"] > self.max_bytes:
                    raise RecoveryStateError("checkpoint byte limit exceeded")
                raw_hash.update(chunk)
                keyed_hash.update(chunk)
        return raw_hash.hexdigest(), keyed_hash.hexdigest()

    def _record_path(
        self,
        relative: str,
        *,
        key: bytes,
        records: dict[str, dict[str, Any]],
        aliases: dict[tuple[Any, ...], str],
        budget: dict[str, int],
        recurse: bool,
        _parent_fd: int | None = None,
        _leaf_name: str | None = None,
    ) -> None:
        relative = _normalize_relative(relative)
        if relative in records:
            return
        path = self.workspace / relative
        if os.name != "nt" and _parent_fd is not None:
            if _leaf_name is None:
                raise RecoveryStateError(
                    "checkpoint relative metadata is missing its leaf"
                )
            parent_metadata = os.fstat(_parent_fd)
            try:
                metadata = os.stat(
                    _leaf_name,
                    dir_fd=_parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                metadata = None
            except OSError as exc:
                raise RecoveryStateError(
                    "checkpoint path metadata is unavailable"
                ) from exc
            if metadata is not None:
                _reject_snapshot_reparse_point(metadata)
        else:
            path, metadata, parent_metadata = self._lstat_snapshot_path(relative)
        if metadata is None:
            parent_identity = {
                "platform": "windows" if os.name == "nt" else sys.platform,
                "device": int(parent_metadata.st_dev),
                "inode": int(parent_metadata.st_ino),
            }
            collation_key = os.path.normcase(relative)
            identity_key = (
                "missing",
                parent_identity["device"],
                parent_identity["inode"],
                collation_key,
            )
            previous = aliases.get(identity_key)
            if previous is not None and previous != relative:
                raise RecoveryStateError(f"filesystem alias collision between {previous} and {relative}")
            aliases[identity_key] = relative
            record = {
                "kind": "missing",
                "parent_identity": parent_identity,
                "collation_key": collation_key,
            }
            records[relative] = record
            budget["records"] += 1
            if budget["records"] > self.max_records:
                raise RecoveryStateError("checkpoint record limit exceeded")
            return

        budget["records"] += 1
        if budget["records"] > self.max_records:
            raise RecoveryStateError("checkpoint record limit exceeded")
        mode = metadata.st_mode
        if stat.S_ISREG(mode):
            kind = "file"
        elif stat.S_ISDIR(mode):
            kind = "directory"
        elif stat.S_ISLNK(mode):
            kind = "symlink"
        else:
            raise RecoveryStateError("unsupported filesystem object in checkpoint inventory")
        identity_key = (
            "symlink" if kind == "symlink" else "object",
            int(metadata.st_dev),
            int(metadata.st_ino),
        )
        previous = aliases.get(identity_key)
        if previous is not None and previous != relative:
            raise RecoveryStateError(f"filesystem alias collision between {previous} and {relative}")
        aliases[identity_key] = relative
        record: dict[str, Any] = {
            "kind": kind,
            "mode": stat.S_IMODE(mode),
            "size": int(metadata.st_size),
            "mtime_ns": int(metadata.st_mtime_ns),
            "identity": {"device": int(metadata.st_dev), "inode": int(metadata.st_ino)},
        }
        if kind == "file":
            record["sha256"], record["content_id"] = self._hash_file(
                path,
                key,
                budget,
                relative=relative,
                expected_metadata=metadata,
                parent_fd=_parent_fd,
                leaf_name=_leaf_name,
            )
        elif kind == "symlink":
            with self._hold_snapshot_object(
                relative,
                metadata,
                parent_fd=_parent_fd,
                leaf_name=_leaf_name,
            ) as held:
                if held["parent_fd"] is None:
                    raise RecoveryStateError(
                        "symlink handle-relative parent is unavailable"
                    )
                target = os.readlink(
                    held["leaf"], dir_fd=held["parent_fd"]
                )
                record["symlink_target"] = target
                record["symlink_id"] = _keyed_id(key, _DOMAIN_SYMLINK, target)
                target_path = Path(target)
                if not target_path.is_absolute():
                    target_path = path.parent / target_path
                target_path = Path(os.path.abspath(target_path))
                try:
                    target_relative = target_path.relative_to(self.workspace).as_posix()
                except ValueError as exc:
                    raise RecoveryStateError(
                        "symlink target escapes the workspace"
                    ) from exc
                target_relative = _normalize_relative(target_relative)
                _, resolved_metadata, _ = self._lstat_snapshot_path(target_relative)
                if resolved_metadata is None or stat.S_ISLNK(
                    resolved_metadata.st_mode
                ):
                    raise RecoveryStateError(
                        "symlink target cannot be resolved safely"
                    )
                with self._hold_snapshot_object(
                    target_relative, resolved_metadata
                ):
                    resolved_key = (
                        "object",
                        int(resolved_metadata.st_dev),
                        int(resolved_metadata.st_ino),
                    )
                    previous = aliases.get(resolved_key)
                    if previous is not None and previous != relative:
                        raise RecoveryStateError(
                            f"filesystem alias collision between {previous} and {relative}"
                        )
                    aliases[resolved_key] = relative
                    record["resolved_identity"] = {
                        "device": int(resolved_metadata.st_dev),
                        "inode": int(resolved_metadata.st_ino),
                    }
        records[relative] = record
        if kind == "directory" and recurse:
            with self._hold_snapshot_object(
                relative,
                metadata,
                parent_fd=_parent_fd,
                leaf_name=_leaf_name,
            ) as held:
                scan_target: int | Path = (
                    held["fd"] if os.name != "nt" else path
                )
                if scan_target is None:
                    raise RecoveryStateError(
                        "checkpoint directory handle is unavailable"
                    )
                try:
                    children = sorted(
                        os.scandir(scan_target),
                        key=lambda entry: unicodedata.normalize("NFC", entry.name),
                    )
                except OSError as exc:
                    raise RecoveryStateError(
                        "checkpoint directory enumeration failed"
                    ) from exc
                for child in children:
                    child_relative = f"{relative}/{child.name}"
                    self._record_path(
                        child_relative,
                        key=key,
                        records=records,
                        aliases=aliases,
                        budget=budget,
                        recurse=True,
                        _parent_fd=(
                            held["fd"] if os.name != "nt" else None
                        ),
                        _leaf_name=(child.name if os.name != "nt" else None),
                    )

    def _lstat_snapshot_path(self, relative: str) -> tuple[Path, Any | None, Any]:
        """Walk components without following an ancestor alias or reparse point."""
        parts = relative.split("/")
        current = self.workspace
        try:
            parent_metadata = current.lstat()
        except OSError as exc:
            raise RecoveryStateError("workspace root metadata is unavailable") from exc
        _reject_snapshot_reparse_point(parent_metadata)
        for index, part in enumerate(parts):
            candidate = current / part
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                return self.workspace.joinpath(*parts), None, parent_metadata
            except OSError as exc:
                raise RecoveryStateError("checkpoint path metadata is unavailable") from exc
            _reject_snapshot_reparse_point(metadata)
            if index < len(parts) - 1:
                if stat.S_ISLNK(metadata.st_mode):
                    raise RecoveryStateError(
                        "symlink path component is unsupported in checkpoint inventory"
                    )
                if not stat.S_ISDIR(metadata.st_mode):
                    raise RecoveryStateError(
                        "checkpoint path component is not a directory"
                    )
                current = candidate
                parent_metadata = metadata
                continue
            return candidate, metadata, parent_metadata
        raise RecoveryStateError("checkpoint path has no components")

    def _public_records(self, records: Mapping[str, Mapping[str, Any]], key: bytes) -> list[dict[str, Any]]:
        projected: list[dict[str, Any]] = []
        for path, record in records.items():
            item: dict[str, Any] = {
                "path_id": _keyed_id(key, _DOMAIN_PATH, path),
                "kind": record["kind"],
                "mode": record.get("mode"),
                "size": record.get("size"),
                "mtime_ns": record.get("mtime_ns"),
            }
            if record.get("identity") is not None:
                item["object_id"] = _keyed_id(key, _DOMAIN_OBJECT, record["identity"])
            if record.get("content_id") is not None:
                item["content_id"] = record["content_id"]
            if record.get("symlink_id") is not None:
                item["symlink_id"] = record["symlink_id"]
            projected.append(item)
        return sorted(projected, key=lambda item: item["path_id"])

    def _capture_snapshot(self, *, key: bytes, allowed_paths: Sequence[str]) -> dict[str, Any]:
        allowed = sorted({_normalize_relative(path) for path in allowed_paths})
        if len(allowed) != len(allowed_paths):
            raise RecoveryStateError("allowed paths contain a normalized collision")
        if not allowed:
            raise RecoveryStateError("recovery checkpoint requires a non-empty allowed manifest")
        head = self._git("rev-parse", "--verify", "HEAD").strip().decode("ascii")
        ref_raw = self._git("symbolic-ref", "-q", "HEAD", allow_failure=True).strip()
        ref = ref_raw.decode("utf-8") if ref_raw else None
        index_entries = self._parse_index(
            self._git("ls-files", "--stage", "-v", "-z")
        )
        status_entries = self._parse_status(
            self._git("status", "--porcelain=v2", "-z", "--untracked-files=all")
        )
        ignored_entries: dict[str, bool] = {}
        ignored_raw = self._git("ls-files", "--others", "--ignored", "--exclude-standard", "-z")
        for item in ignored_raw.split(b"\0"):
            if not item:
                continue
            path, directory_marker = _decode_ignored_git_path(item)
            ignored_entries[path] = ignored_entries.get(path, False) or directory_marker
        ignored_paths = sorted(ignored_entries)
        records: dict[str, dict[str, Any]] = {}
        aliases: dict[tuple[Any, ...], str] = {}
        budget = {"records": 0, "bytes": 0}
        for path in allowed:
            self._record_path(path, key=key, records=records, aliases=aliases, budget=budget, recurse=True)
        for path in ignored_paths:
            self._record_path(
                path,
                key=key,
                records=records,
                aliases=aliases,
                budget=budget,
                recurse=ignored_entries[path],
            )
        status_paths: set[str] = set()
        for entry in status_entries:
            status_paths.add(entry["path"])
            if entry.get("original_path"):
                status_paths.add(entry["original_path"])
        for path in sorted(status_paths):
            self._record_path(path, key=key, records=records, aliases=aliases, budget=budget, recurse=False)

        path_ids = [_keyed_id(key, _DOMAIN_PATH, path) for path in allowed]
        allowed_set_digest = _domain_digest(_DOMAIN_ALLOWED, sorted(path_ids))
        public_records = self._public_records(records, key)
        allowed_record_ids = {
            _keyed_id(key, _DOMAIN_PATH, path)
            for path in records
            if self._path_is_allowed(path, allowed, records)
        }
        ignored_record_ids = {
            _keyed_id(key, _DOMAIN_PATH, path)
            for path in records
            if self._path_is_allowed(path, ignored_paths, records)
        }
        allowed_public_records = [item for item in public_records if item["path_id"] in allowed_record_ids]
        ignored_public_records = [item for item in public_records if item["path_id"] in ignored_record_ids]
        public = {
            "head_id": _keyed_id(key, _DOMAIN_REF, head),
            "ref_id": _keyed_id(key, _DOMAIN_REF, ref or "DETACHED"),
            "full_index_digest": _keyed_id(key, _DOMAIN_INDEX, index_entries),
            "status_digest": _keyed_id(key, _DOMAIN_STATUS, status_entries),
            "allowed_inventory_digest": _domain_digest(_DOMAIN_INVENTORY, allowed_public_records),
            "ignored_inventory_digest": _domain_digest(_DOMAIN_INVENTORY, ignored_public_records),
            "records_digest": _domain_digest(_DOMAIN_INVENTORY, public_records),
            "records": public_records,
            "record_count": budget["records"],
            "hashed_bytes": budget["bytes"],
            "outside_set_delta": [],
        }
        return {
            "head": head,
            "ref": ref,
            "full_index": index_entries,
            "status": status_entries,
            "status_paths": sorted(status_paths),
            "ignored_paths": sorted(ignored_paths),
            "allowed_paths": allowed,
            "records": records,
            "public": public,
            "allowed_set_digest": allowed_set_digest,
        }

    @staticmethod
    def _path_is_allowed(path: str, allowed: Sequence[str], records: Mapping[str, Mapping[str, Any]]) -> bool:
        for root in allowed:
            root_record = records.get(root)
            if path == root:
                return True
            if root_record and root_record.get("kind") == "directory" and path.startswith(root + "/"):
                return True
        return False

    @staticmethod
    def _checkpoint_digest(checkpoint: Mapping[str, Any]) -> str:
        value = dict(checkpoint)
        value.pop("checkpoint_digest", None)
        return _domain_digest(_DOMAIN_CHECKPOINT, value)

    def prepare_source_checkpoint(
        self,
        *,
        source_id: str,
        source_lease_id: str,
        source_milestone: str,
        target_milestone: str,
        allowed_paths: list[str],
        specification_revision: str,
    ) -> dict[str, Any]:
        key = secrets.token_bytes(32)
        with self._lock():
            self._read_registry_for_write_locked(rebarrier=self.path.exists())
            pre = self._capture_snapshot(key=key, allowed_paths=allowed_paths)
            source_binding = {
                "source_id": source_id,
                "source_lease_id": source_lease_id,
                "source_receipt_digest": None,
                "source_milestone": source_milestone,
                "target_milestone": target_milestone,
                "specification_revision": specification_revision,
            }
            source_state_id = _keyed_id(key, _DOMAIN_SOURCE, source_binding)
            checkpoint_key_id = hashlib.sha256(_DOMAIN_KEY_ID + key).hexdigest()
            preflight: dict[str, Any] = {
                "schema_version": 1,
                "source_state_id": source_state_id,
                "source_binding_id": _keyed_id(key, _DOMAIN_SOURCE, source_binding),
                "checkpoint_key_id": checkpoint_key_id,
                "allowed_set_digest": pre["allowed_set_digest"],
                "source_milestone": source_milestone,
                "target_milestone": target_milestone,
                "specification_revision": specification_revision,
                "pre_snapshot": pre["public"],
                "disposition": "recovery-capability-available",
            }
            preflight["preflight_digest"] = _domain_digest(_DOMAIN_SOURCE, preflight)
            private: dict[str, Any] = {
                "schema_version": 1,
                "workspace_key": self.workspace_key,
                "source_state_id": source_state_id,
                "generation": 0,
                "previous_generation_digest": None,
                "checkpoint_key": key.hex(),
                "checkpoint_key_id": checkpoint_key_id,
                "source_binding": source_binding,
                "pre_snapshot": pre,
                "candidate_snapshot": None,
                "public_preflight": preflight,
                "public_checkpoint": None,
                "authorization": None,
            }
            private["digest"] = _digest(private)
            self._commit_source_locked(private)
            return preflight

    def finalize_prepared_checkpoint(
        self,
        preflight: Mapping[str, Any],
        *,
        source_receipt_digest: str,
    ) -> dict[str, Any]:
        _require_hex(source_receipt_digest, "source_receipt_digest")
        source_state_id = preflight.get("source_state_id")
        if not isinstance(source_state_id, str):
            raise RecoveryStateError("source preflight state ID is missing")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            source = self._read_source_locked(source_state_id)
            stored_preflight = source.get("public_preflight")
            if not isinstance(stored_preflight, dict) or preflight.get("preflight_digest") != stored_preflight.get("preflight_digest"):
                raise RecoveryStateError("source preflight binding drifted")
            if source.get("public_checkpoint") is not None:
                if source.get("source_binding", {}).get("source_receipt_digest") != source_receipt_digest:
                    raise RecoveryStateError("source terminal receipt binding drifted")
                return dict(source["public_checkpoint"])
            source["source_binding"]["source_receipt_digest"] = source_receipt_digest
            key = bytes.fromhex(source["checkpoint_key"])
            binding = source["source_binding"]
            public: dict[str, Any] = {
                "schema_version": 1,
                "source_state_id": source_state_id,
                "source_binding_id": _keyed_id(key, _DOMAIN_SOURCE, binding),
                "checkpoint_key_id": source["checkpoint_key_id"],
                "allowed_set_digest": source["pre_snapshot"]["allowed_set_digest"],
                "source_milestone": binding["source_milestone"],
                "target_milestone": binding["target_milestone"],
                "specification_revision": binding["specification_revision"],
                "authorization_epoch": registry["epoch"],
                "pre_snapshot": source["pre_snapshot"]["public"],
                "candidate_snapshot": None,
                "disposition": "recovery-eligible",
                "reasons": [],
            }
            public["checkpoint_digest"] = self._checkpoint_digest(public)
            source["public_checkpoint"] = public
            self._commit_source_locked(source)
            return public

    def capture_checkpoint(
        self,
        *,
        source_id: str,
        source_lease_id: str,
        source_receipt_digest: str,
        source_milestone: str,
        target_milestone: str,
        allowed_paths: list[str],
        specification_revision: str,
    ) -> dict[str, Any]:
        preflight = self.prepare_source_checkpoint(
            source_id=source_id,
            source_lease_id=source_lease_id,
            source_milestone=source_milestone,
            target_milestone=target_milestone,
            allowed_paths=allowed_paths,
            specification_revision=specification_revision,
        )
        return self.finalize_prepared_checkpoint(
            preflight,
            source_receipt_digest=source_receipt_digest,
        )

    def _revalidate_source_locked(
        self,
        source: dict[str, Any],
        checkpoint: Mapping[str, Any],
        *,
        persist: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        key = bytes.fromhex(source["checkpoint_key"])
        if len(key) != 32 or hashlib.sha256(_DOMAIN_KEY_ID + key).hexdigest() != source.get("checkpoint_key_id"):
            raise RecoveryStateError("checkpoint key or key ID drifted")
        if checkpoint.get("source_state_id") != source["source_state_id"]:
            raise RecoveryStateError("checkpoint source binding drifted")
        stored = source["public_checkpoint"]
        if checkpoint.get("checkpoint_digest") != stored.get("checkpoint_digest"):
            raise RecoveryStateError("checkpoint digest drifted")
        pre = source["pre_snapshot"]
        candidate = self._capture_snapshot(key=key, allowed_paths=pre["allowed_paths"])
        reasons: list[str] = []
        if (
            candidate["head"] != pre["head"]
            or candidate["ref"] != pre["ref"]
            or candidate["full_index"] != pre["full_index"]
        ):
            reasons.append("git-control-plane-drift")
        all_paths = set(pre["records"]) | set(candidate["records"])
        changed_paths = {
            path for path in all_paths if pre["records"].get(path) != candidate["records"].get(path)
        }
        if candidate["head"] != pre["head"]:
            committed_paths = {
                _normalize_relative(_decode_git_path(item))
                for item in self._git(
                    "diff", "--name-only", "-z", f"{pre['head']}..{candidate['head']}"
                ).split(b"\0")
                if item
            }
            changed_paths |= committed_paths
        outside = sorted(
            path
            for path in changed_paths
            if not self._path_is_allowed(path, pre["allowed_paths"], pre["records"])
        )
        if outside:
            reasons.append("outside-set-drift")
        pre_dirty = set(pre["status_paths"])
        if any(
            path in pre_dirty
            and path in changed_paths
            and self._path_is_allowed(path, pre["allowed_paths"], pre["records"])
            for path in changed_paths
        ):
            reasons.append("preexisting-dirty-overlap")
        public = dict(stored)
        candidate_public = dict(candidate["public"])
        candidate_public["outside_set_delta"] = [
            _keyed_id(key, _DOMAIN_PATH, path) for path in outside
        ]
        public["candidate_snapshot"] = candidate_public
        public["disposition"] = "recovery-ineligible" if reasons else "recovery-eligible"
        public["reasons"] = sorted(set(reasons))
        public["checkpoint_digest"] = self._checkpoint_digest(public)
        source["candidate_snapshot"] = candidate
        source["public_checkpoint"] = public
        if persist:
            source = self._commit_source_locked(source)
        return source, public

    def _require_zero_write_source_locked(self, source_state_id: str) -> None:
        source = self._read_source_locked(source_state_id)
        key = bytes.fromhex(source["checkpoint_key"])
        pre = source["pre_snapshot"]
        current = self._capture_snapshot(key=key, allowed_paths=pre["allowed_paths"])
        if current != pre:
            raise RecoveryStateError(
                "semantic escalation requires an authoritative zero-write snapshot"
            )

    def revalidate_checkpoint(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        source_state_id = checkpoint.get("source_state_id")
        if not isinstance(source_state_id, str):
            raise RecoveryStateError("checkpoint source state ID is missing")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            if any(
                event.get("event") == "semantic-handoff-rejected"
                and event.get("source_state_id") == source_state_id
                and event.get("checkpoint_allowed") is False
                for event in registry.get("history", [])
            ):
                raise RecoveryStateError("semantic escalation made this checkpoint recovery-ineligible")
            source = self._read_source_locked(source_state_id)
            _, public = self._revalidate_source_locked(source, checkpoint, persist=True)
            return public

    def grant_authorization(
        self,
        checkpoint: Mapping[str, Any],
        *,
        user_action_digest: str,
        specification_revision: str,
        prompt_snapshot_id: str | None = None,
        prompt_sha256: str | None = None,
    ) -> dict[str, Any]:
        _require_hex(user_action_digest, "user_action_digest")
        if (prompt_snapshot_id is None) != (prompt_sha256 is None):
            raise RecoveryStateError("recovery authorization prompt binding is incomplete")
        if prompt_snapshot_id is not None:
            _require_hex(prompt_snapshot_id, "prompt_snapshot_id")
            _require_hex(prompt_sha256, "prompt_sha256")
        source_state_id = checkpoint.get("source_state_id")
        if not isinstance(source_state_id, str):
            raise RecoveryStateError("checkpoint source state ID is missing")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            source = self._read_source_locked(source_state_id)
            stored = source["public_checkpoint"]
            if checkpoint.get("checkpoint_digest") != stored.get("checkpoint_digest"):
                raise RecoveryStateError("checkpoint digest drifted before authorization")
            if checkpoint.get("disposition") != "recovery-eligible" or checkpoint.get("candidate_snapshot") is None:
                raise RecoveryStateError("recovery authorization requires an eligible candidate checkpoint")
            if specification_revision != source["source_binding"]["specification_revision"]:
                raise RecoveryStateError("specification revision drifted before authorization")
            existing = source.get("authorization")
            if isinstance(existing, dict):
                if ("prompt_snapshot_id" in existing) != (prompt_snapshot_id is not None):
                    raise RecoveryStateError(
                        "an immutable recovery authorization already exists with different prompt bindings"
                    )
                expected_existing = {
                    "authorization_epoch": registry["epoch"],
                    "user_action_digest": user_action_digest,
                    "specification_revision": specification_revision,
                    "source_receipt_digest": source["source_binding"]["source_receipt_digest"],
                    "checkpoint_digest": checkpoint["checkpoint_digest"],
                    "allowed_set_digest": checkpoint["allowed_set_digest"],
                    "target_milestone": checkpoint["target_milestone"],
                }
                if prompt_snapshot_id is not None:
                    expected_existing |= {
                        "prompt_snapshot_id": prompt_snapshot_id,
                        "prompt_sha256": prompt_sha256,
                    }
                if any(existing.get(key) != value for key, value in expected_existing.items()):
                    raise RecoveryStateError("an immutable recovery authorization already exists with different bindings")
                return {
                    "event": "recovery-authorization-granted",
                    "grant_id": existing["grant_id"],
                    "authorization_epoch": existing["authorization_epoch"],
                    "checkpoint_digest": existing["checkpoint_digest"],
                    "allowed_set_digest": existing["allowed_set_digest"],
                    "target_milestone": existing["target_milestone"],
                    "specification_revision": specification_revision,
                }
            nonce = secrets.token_bytes(32)
            private_grant = {
                "grant_id": _keyed_id(nonce, _DOMAIN_GRANT, checkpoint["checkpoint_digest"]),
                "authorization_nonce": nonce.hex(),
                "authorization_epoch": registry["epoch"],
                "user_action_digest": user_action_digest,
                "specification_revision": specification_revision,
                "source_receipt_digest": source["source_binding"]["source_receipt_digest"],
                "checkpoint_digest": checkpoint["checkpoint_digest"],
                "allowed_set_digest": checkpoint["allowed_set_digest"],
                "target_milestone": checkpoint["target_milestone"],
            }
            if prompt_snapshot_id is not None:
                private_grant["prompt_snapshot_id"] = prompt_snapshot_id
                private_grant["prompt_sha256"] = prompt_sha256
            source["authorization"] = private_grant
            self._commit_source_locked(source)
            return {
                "event": "recovery-authorization-granted",
                "grant_id": private_grant["grant_id"],
                "authorization_epoch": private_grant["authorization_epoch"],
                "checkpoint_digest": private_grant["checkpoint_digest"],
                "allowed_set_digest": private_grant["allowed_set_digest"],
                "target_milestone": private_grant["target_milestone"],
                "specification_revision": specification_revision,
            }

    def retire_authorization(
        self,
        *,
        source_state_id: str,
        grant_id: str,
    ) -> dict[str, Any]:
        """Retire one non-consumable prompt-bound grant while exactly vacant."""
        _require_hex(source_state_id, "authorization retirement source state ID")
        _require_hex(grant_id, "authorization retirement grant ID")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            if not self._is_vacant(registry):
                raise RecoveryStateError(
                    "authorization retirement requires an exactly vacant registry"
                )
            prior = next(
                (
                    event
                    for event in registry["history"]
                    if event.get("event") == "authorization-retired"
                    and event.get("source_state_id") == source_state_id
                    and event.get("grant_id") == grant_id
                ),
                None,
            )
            source = self._read_source_locked(source_state_id)
            authorization = source.get("authorization")
            if authorization is None and isinstance(prior, Mapping):
                return registry
            if (
                not isinstance(authorization, Mapping)
                or authorization.get("grant_id") != grant_id
                or not isinstance(authorization.get("prompt_snapshot_id"), str)
                or not isinstance(authorization.get("prompt_sha256"), str)
            ):
                raise RecoveryStateError(
                    "authorization retirement requires a prompt-bound grant"
                )
            checkpoint = source.get("public_checkpoint")
            consumed = any(
                item.get("grant_id") == grant_id
                for item in registry["consumed_grants"]
            )
            stale = authorization.get("authorization_epoch") != registry.get("epoch")
            ineligible = (
                isinstance(checkpoint, Mapping)
                and checkpoint.get("disposition") == "recovery-ineligible"
            )
            if not (consumed or stale or ineligible):
                raise RecoveryStateError(
                    "an eligible current authorization cannot be retired"
                )
            source["authorization"] = None
            self._commit_source_locked(source)
            registry["history"].append(
                {
                    "event": "authorization-retired",
                    "source_state_id": source_state_id,
                    "grant_id": grant_id,
                    "prompt_snapshot_id": authorization["prompt_snapshot_id"],
                    "prompt_sha256": authorization["prompt_sha256"],
                }
            )
            return self._commit_registry_locked(registry)

    def consume_grant_and_reserve(
        self,
        *,
        grant_id: str,
        checkpoint: Mapping[str, Any],
        target_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        source_state_id = checkpoint.get("source_state_id")
        if not isinstance(source_state_id, str):
            raise RecoveryStateError("checkpoint source state ID is missing")
        required_plan = {
            "lease_id",
            "run_id",
            "prompt_sha256",
            "launch_token",
            "provider_plan_id",
            "ipc_plan_id",
            "allowed_set_digest",
        }
        plan_fields = set(target_plan)
        if plan_fields != required_plan and plan_fields != required_plan | {"prompt_snapshot_id"}:
            raise RecoveryStateError("target reservation plan fields are incomplete or unknown")
        _require_hex(target_plan["prompt_sha256"], "prompt_sha256")
        if "prompt_snapshot_id" in target_plan:
            _require_hex(target_plan["prompt_snapshot_id"], "prompt_snapshot_id")
        _require_hex(target_plan["launch_token"], "launch_token")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            if not self._is_vacant(registry):
                raise RecoveryStateError("workspace is not vacant")
            if any(item.get("grant_id") == grant_id for item in registry["consumed_grants"]):
                raise RecoveryStateError("authorization grant is already consumed")
            source = self._read_source_locked(source_state_id)
            private_grant = source.get("authorization")
            if not isinstance(private_grant, dict) or private_grant.get("grant_id") != grant_id:
                raise RecoveryStateError("authorization grant is missing or mismatched")
            if private_grant.get("authorization_epoch") != registry["epoch"]:
                raise RecoveryStateError("authorization epoch is stale")
            for field in ("checkpoint_digest", "allowed_set_digest", "target_milestone"):
                if private_grant.get(field) != checkpoint.get(field):
                    raise RecoveryStateError(f"authorization {field} binding drifted")
            grant_has_prompt = "prompt_snapshot_id" in private_grant
            plan_has_prompt = "prompt_snapshot_id" in target_plan
            if grant_has_prompt != plan_has_prompt:
                raise RecoveryStateError("authorization prompt binding drifted")
            if grant_has_prompt and any(
                private_grant.get(field) != target_plan.get(field)
                for field in ("prompt_snapshot_id", "prompt_sha256")
            ):
                raise RecoveryStateError("authorization prompt binding drifted")
            if target_plan.get("allowed_set_digest") != checkpoint.get("allowed_set_digest"):
                raise RecoveryStateError("target allowed-set binding drifted")
            source, current = self._revalidate_source_locked(source, checkpoint, persist=False)
            if current.get("checkpoint_digest") != checkpoint.get("checkpoint_digest"):
                raise RecoveryStateError("checkpoint changed before authorization consumption")
            nonce = bytes.fromhex(private_grant["authorization_nonce"])
            consumed = {
                "grant_id": grant_id,
                "authorization_nonce_digest": hashlib.sha256(_DOMAIN_NONCE + nonce).hexdigest(),
                "authorization_epoch": private_grant["authorization_epoch"],
                "checkpoint_digest": checkpoint["checkpoint_digest"],
                "allowed_set_digest": checkpoint["allowed_set_digest"],
            }
            if grant_has_prompt:
                consumed["prompt_snapshot_id"] = private_grant["prompt_snapshot_id"]
                consumed["prompt_sha256"] = private_grant["prompt_sha256"]
            registry["consumed_grants"].append(consumed)
            registry["lease"] = {
                "lease_id": target_plan["lease_id"],
                "lease_kind": "recovery-target",
                "recovery_capable": True,
                "state": "reserved",
                "source_state_id": source_state_id,
                "grant_id": grant_id,
                "authorization_epoch": private_grant["authorization_epoch"],
                "checkpoint_digest": checkpoint["checkpoint_digest"],
                "allowed_set_digest": checkpoint["allowed_set_digest"],
                "target_milestone": checkpoint["target_milestone"],
                "plan": dict(target_plan),
            }
            return self._commit_registry_locked(registry)

    def claim_launch(self, lease_id: str, launch_token: str) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") != "reserved":
                raise RecoveryStateError("target lease is not reserved for launch")
            if lease.get("plan", {}).get("launch_token") != launch_token:
                raise RecoveryStateError("target launch token drifted")
            lease["state"] = "launch-claimed"
            lease["launch_claim_id"] = _domain_digest(_DOMAIN_GRANT, {"lease_id": lease_id, "token": launch_token})
            return self._commit_registry_locked(state)

    def fail_recovery_target_before_boundary(
        self,
        lease_id: str,
        cause: str,
        proof: Mapping[str, Any],
    ) -> dict[str, Any]:
        if proof.get("tree_empty") is not True or proof.get("no_user_code") is not True:
            raise RecoveryStateError("recovery target failed-start requires empty-tree and no-user-code proof")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") != "recovery-target"
                or lease.get("state") != "launch-claimed"
            ):
                raise RecoveryStateError("recovery target is not in a pre-boundary launch state")
            state["history"].append(
                {
                    "event": "recovery-target-start-failed",
                    "lease_id": lease_id,
                    "grant_id": lease.get("grant_id"),
                    "cause": cause,
                    "proof": dict(proof),
                }
            )
            state["lease"] = None
            return self._commit_registry_locked(state, rotate_epoch=True)

    def claim_contained_launch(self, lease_id: str, launch_token: str) -> dict[str, Any]:
        """Durably consume the one contained normal-source launch attempt."""
        if not isinstance(launch_token, str) or not launch_token:
            raise RecoveryStateError("contained launch token is required")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") != "normal-contained"
                or lease.get("state") != "normal-snapshot-bound"
            ):
                raise RecoveryStateError("normal contained lease lacks a reserved source boundary")
            planned_token = lease.get("containment_plan", {}).get("contained_launch_token")
            if planned_token is not None and planned_token != launch_token:
                raise RecoveryStateError("contained launch token drifted")
            lease["contained_launch_token_digest"] = _domain_digest(
                _DOMAIN_GRANT, {"lease_id": lease_id, "token": launch_token}
            )
            lease["state"] = "normal-preflight-launch-claimed"
            return self._commit_registry_locked(state)

    def bind_process_unactivated(
        self,
        lease_id: str,
        *,
        allowed_set_digest: str,
        provider_receipt: Mapping[str, Any],
        process_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
                raise RecoveryStateError("contained launch is not claim-bound")
            expected_state = (
                "launch-claimed"
                if lease.get("lease_kind") == "recovery-target"
                else "normal-preflight-launch-claimed"
            )
            if lease.get("state") != expected_state:
                raise RecoveryStateError("contained launch is not claim-bound")
            if lease.get("allowed_set_digest") != allowed_set_digest:
                raise RecoveryStateError("process-bound allowed-set binding drifted")
            if not provider_receipt or not process_receipt:
                raise RecoveryStateError("actual provider and process receipts are required")
            lease["provider_receipt"] = dict(provider_receipt)
            lease["process_receipt"] = dict(process_receipt)
            lease["state"] = "process-bound-unactivated"
            return self._commit_registry_locked(state, resolve_visible_commit=True)

    def commit_activation(self, lease_id: str, allowed_set_digest: str) -> dict[str, Any]:
        _require_hex(allowed_set_digest, "activation allowed-set digest")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
                raise RecoveryStateError("activation lease is missing")
            allowed_states = {
                "process-bound-unactivated",
                "ordinary-process-bound-unactivated",
                "running",
                "active",
                "legacy-running",
            }
            if lease.get("state") not in allowed_states or lease.get("allowed_set_digest") != allowed_set_digest:
                raise RecoveryStateError("activation binding drifted")
            if lease.get("activation_abort") is not None:
                raise RecoveryStateError("activation provenance drift was already retained")
            if lease.get("lease_kind") in {"normal-contained", "recovery-target"}:
                source = self._read_source_locked(lease.get("source_state_id"))
                key = bytes.fromhex(source["checkpoint_key"])
                if (
                    len(key) != 32
                    or hashlib.sha256(_DOMAIN_KEY_ID + key).hexdigest()
                    != source.get("checkpoint_key_id")
                ):
                    raise RecoveryStateError("activation provenance drifted at checkpoint key")
                if lease.get("lease_kind") == "normal-contained":
                    expected = source.get("pre_snapshot")
                    expected_digest = lease.get("source_snapshot_digest")
                    source_binding_valid = (
                        lease.get("source_state_digest") == source.get("digest")
                        and isinstance(expected, dict)
                        and expected_digest == _digest(expected)
                    )
                else:
                    expected = source.get("candidate_snapshot")
                    expected_digest = _digest(expected) if isinstance(expected, dict) else None
                    source_binding_valid = (
                        isinstance(expected, dict)
                        and source.get("public_checkpoint", {}).get("checkpoint_digest")
                        == lease.get("checkpoint_digest")
                    )
                try:
                    current = self._capture_snapshot(
                        key=key,
                        allowed_paths=source["pre_snapshot"]["allowed_paths"],
                    )
                    current_digest = _digest(current)
                except (KeyError, TypeError, RecoveryStateError) as exc:
                    current = None
                    current_digest = None
                    provenance_error = str(exc) or type(exc).__name__
                else:
                    provenance_error = None
                if (
                    not source_binding_valid
                    or current is None
                    or current != expected
                    or current_digest != expected_digest
                ):
                    lease["state"] = "process-bound-unactivated"
                    lease["activation_abort"] = {
                        "cause": "provenance-drift",
                        "expected_snapshot_digest": expected_digest,
                        "observed_snapshot_digest": current_digest,
                        "error": provenance_error,
                    }
                    state["history"].append(
                        {
                            "event": "activation-provenance-drift",
                            "lease_id": lease_id,
                            "lease_kind": lease.get("lease_kind"),
                            "expected_snapshot_digest": expected_digest,
                            "observed_snapshot_digest": current_digest,
                        }
                    )
                    self._commit_registry_locked(state)
                    raise RecoveryStateError(
                        "activation provenance drift retained the unactivated contained lease"
                    )
            if lease.get("state") in {"running", "active", "legacy-running"}:
                if lease.get("activation_allowed_set_digest") != allowed_set_digest:
                    raise RecoveryStateError("persisted activation binding drifted")
                return state
            lease["activation_allowed_set_digest"] = allowed_set_digest
            if lease.get("lease_kind") in {"normal-legacy", "normal-fallback"}:
                lease["state"] = "legacy-running"
            else:
                lease["state"] = "running" if lease.get("lease_kind") == "normal-contained" else "active"
            return self._commit_registry_locked(state)

    def containment_failed_before_boundary(self, lease_id: str, cause: str) -> dict[str, Any]:
        """Enter the only normal-source path that can later use ordinary fallback."""
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
                raise RecoveryStateError("containment lease is missing")
            if lease.get("state") == "process-bound-unactivated":
                state["quarantine"] = "containment-loss-after-boundary"
                self._commit_registry_locked(state)
                raise RecoveryStateError("committed containment loss is quarantined")
            if lease.get("lease_kind") != "normal-contained" or lease.get("state") != "normal-preflight-launch-claimed":
                raise RecoveryStateError("containment failure is not eligible for normal fallback")
            lease["state"] = "fallback-teardown-pending"
            lease["containment_failure"] = cause
            return self._commit_registry_locked(state)

    def quarantine_containment_loss(self, lease_id: str, cause: str) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
                raise RecoveryStateError("containment lease is missing")
            if lease.get("state") not in {
                "process-bound-unactivated",
                "running",
                "active",
                "terminal-pending-stop",
                "stopped-terminal",
                "handoff-committed",
            }:
                raise RecoveryStateError("containment loss preceded the durable process boundary")
            state["quarantine"] = "containment-loss-after-boundary"
            state["history"].append(
                {"event": "containment-loss-quarantined", "lease_id": lease_id, "cause": cause}
            )
            return self._commit_registry_locked(state)

    def prove_fallback_teardown(self, lease_id: str, proof: Mapping[str, Any]) -> dict[str, Any]:
        if proof.get("tree_empty") is not True or proof.get("no_user_code") is not True:
            raise RecoveryStateError("fallback teardown requires empty-tree and no-user-code proof")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") != "fallback-teardown-pending":
                raise RecoveryStateError("fallback teardown is not pending")
            lease["teardown_proof"] = dict(proof)
            lease["state"] = "fallback-teardown-complete"
            return self._commit_registry_locked(state)

    def claim_normal_fallback(self, lease_id: str, fallback_token: str) -> dict[str, Any]:
        if not isinstance(fallback_token, str) or not fallback_token:
            raise RecoveryStateError("ordinary fallback token is required")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") != "fallback-teardown-complete":
                raise RecoveryStateError("ordinary fallback is not teardown-proved")
            planned_token = lease.get("containment_plan", {}).get("fallback_token")
            if planned_token is not None and planned_token != fallback_token:
                raise RecoveryStateError("ordinary fallback token drifted")
            lease["lease_kind"] = "normal-fallback"
            lease["recovery_capable"] = False
            lease["fallback_token_digest"] = _domain_digest(_DOMAIN_GRANT, {"lease_id": lease_id, "token": fallback_token})
            lease["state"] = "ordinary-fallback-claimed"
            return self._commit_registry_locked(state)

    def quarantine_fallback_launch(self, lease_id: str, cause: str) -> dict[str, Any]:
        """Retain an ambiguous one-shot fallback launch for manual reconciliation."""
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") != "normal-fallback"
                or lease.get("state")
                not in {"ordinary-fallback-claimed", "ordinary-process-bound-unactivated"}
            ):
                raise RecoveryStateError("ordinary fallback launch is not ambiguity-quarantinable")
            state["quarantine"] = "fallback-launch-ambiguous"
            state["history"].append(
                {
                    "event": "fallback-launch-quarantined",
                    "lease_id": lease_id,
                    "cause": cause,
                }
            )
            return self._commit_registry_locked(state, resolve_visible_commit=True)

    def bind_fallback_process_unactivated(
        self,
        lease_id: str,
        *,
        process_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not process_receipt:
            raise RecoveryStateError("ordinary fallback process receipt is required")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") != "normal-fallback"
                or lease.get("recovery_capable") is not False
                or lease.get("state") != "ordinary-fallback-claimed"
            ):
                raise RecoveryStateError("ordinary fallback launch is not claim-bound")
            lease["process_receipt"] = dict(process_receipt)
            lease["state"] = "ordinary-process-bound-unactivated"
            return self._commit_registry_locked(state, resolve_visible_commit=True)

    def bind_legacy_process_unactivated(
        self,
        lease_id: str,
        *,
        process_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not process_receipt:
            raise RecoveryStateError("legacy process receipt is required")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") != "normal-legacy"
                or lease.get("state") != "reserved"
            ):
                raise RecoveryStateError("legacy launch is not reserved")
            lease["process_receipt"] = dict(process_receipt)
            lease["state"] = "ordinary-process-bound-unactivated"
            return self._commit_registry_locked(state)

    def release_legacy_terminal(
        self,
        lease_id: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        if receipt.get("process_tree_stopped") is not True:
            raise RecoveryStateError("legacy terminal release requires stopped process-tree proof")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("lease_kind") not in {"normal-legacy", "normal-fallback"}
                or lease.get("recovery_capable") is not False
                or lease.get("state") not in {"legacy-running", "ordinary-process-bound-unactivated"}
            ):
                raise RecoveryStateError("legacy terminal lease is not releasable")
            state["history"].append(
                {
                    "event": "legacy-terminal-released",
                    "lease_id": lease_id,
                    "success": receipt.get("success") is True,
                }
            )
            state["lease"] = None
            return self._commit_registry_locked(state, rotate_epoch=True)

    def record_terminal_evidence(self, lease_id: str, receipt: Mapping[str, Any], allowed_set_digest: str) -> dict[str, Any]:
        if not receipt:
            raise RecoveryStateError("terminal receipt is required")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or not lease.get("recovery_capable"):
                raise RecoveryStateError("contained terminal lease is missing")
            if lease.get("state") not in {"running", "active"} or lease.get("allowed_set_digest") != allowed_set_digest:
                raise RecoveryStateError("terminal allowed-set binding drifted")
            lease["terminal_receipt"] = dict(receipt)
            lease["state"] = "terminal-pending-stop"
            return self._commit_registry_locked(state)

    def prove_contained_tree_empty(self, lease_id: str, proof: Mapping[str, Any], allowed_set_digest: str) -> dict[str, Any]:
        if proof.get("populated") is not False or proof.get("identity_verified") is not True:
            raise RecoveryStateError("contained terminalization requires authenticated zero proof")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") != "terminal-pending-stop":
                raise RecoveryStateError("contained terminal receipt is missing")
            if lease.get("allowed_set_digest") != allowed_set_digest:
                raise RecoveryStateError("zero proof allowed-set binding drifted")
            lease["zero_proof"] = dict(proof)
            lease["state"] = "stopped-terminal"
            return self._commit_registry_locked(state)

    def remediation_scope_manifest(
        self,
        *,
        task_commit: str,
        parent_commit: str,
        source_checkpoint_digest: str,
        specification_revision: str,
        milestone: str,
        producer_allowed_set_digest: str,
        root_verification_digest: str,
        entries: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Return the private, exact task-commit manifest used by remediation."""
        _require_git_sha(task_commit, "remediation task commit")
        _require_git_sha(parent_commit, "remediation parent commit")
        for value, label in (
            (source_checkpoint_digest, "remediation source checkpoint"),
            (producer_allowed_set_digest, "remediation producer allowed set"),
            (root_verification_digest, "remediation root verification"),
        ):
            _require_hex(value, label)
        _require_string(specification_revision, "remediation specification revision")
        _require_string(milestone, "remediation milestone")
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {"path", "role"}:
                raise RecoveryStateError("remediation scope entry is malformed")
            path = _normalize_relative(_require_string(entry.get("path"), "remediation scope path"))
            role = entry.get("role")
            if role not in {"producer", "root-completion"} or path in seen:
                raise RecoveryStateError("remediation scope paths must be unique with a supported role")
            seen.add(path)
            normalized.append({"path": path, "role": role})
        if not normalized:
            raise RecoveryStateError("remediation scope requires at least one task path")
        manifest: dict[str, Any] = {
            "schema": "remediation-scope-v1",
            "task_commit": task_commit,
            "parent_commit": parent_commit,
            "source_checkpoint_digest": source_checkpoint_digest,
            "specification_revision": specification_revision,
            "milestone": milestone,
            "producer_allowed_set_digest": producer_allowed_set_digest,
            "root_verification_digest": root_verification_digest,
            "entries": sorted(normalized, key=lambda value: value["path"]),
        }
        manifest["digest"] = _domain_digest(_DOMAIN_REMEDIATION_SCOPE, manifest)
        return manifest

    @staticmethod
    def _post_commit_authorization_digest(authorization: Mapping[str, Any]) -> str:
        return _domain_digest(
            _DOMAIN_POST_COMMIT_AUTHORIZATION,
            {
                "action_id": authorization.get("action_id"),
                "authorization_handle": authorization.get("authorization_handle"),
                "capability": authorization.get("capability"),
                "tuple_digest": authorization.get("tuple_digest"),
            },
        )

    def _validated_remediation_scope(
        self,
        manifest: Mapping[str, Any],
        *,
        source_checkpoint_digest: str,
        specification_revision: str,
        milestone: str,
        producer_allowed_set_digest: str,
        root_verification_digest: str,
    ) -> dict[str, Any]:
        required = {
            "schema",
            "task_commit",
            "parent_commit",
            "source_checkpoint_digest",
            "specification_revision",
            "milestone",
            "producer_allowed_set_digest",
            "root_verification_digest",
            "entries",
            "digest",
        }
        if not isinstance(manifest, Mapping) or set(manifest) != required:
            raise RecoveryStateError("remediation scope manifest fields are incomplete")
        rebuilt = self.remediation_scope_manifest(
            task_commit=manifest["task_commit"],
            parent_commit=manifest["parent_commit"],
            source_checkpoint_digest=manifest["source_checkpoint_digest"],
            specification_revision=manifest["specification_revision"],
            milestone=manifest["milestone"],
            producer_allowed_set_digest=manifest["producer_allowed_set_digest"],
            root_verification_digest=manifest["root_verification_digest"],
            entries=manifest["entries"],
        )
        if rebuilt != dict(manifest):
            raise RecoveryStateError("remediation scope manifest digest drifted")
        if any(
            rebuilt[field] != value
            for field, value in (
                ("source_checkpoint_digest", source_checkpoint_digest),
                ("specification_revision", specification_revision),
                ("milestone", milestone),
                ("producer_allowed_set_digest", producer_allowed_set_digest),
                ("root_verification_digest", root_verification_digest),
            )
        ):
            raise RecoveryStateError("remediation scope manifest tuple drifted")
        return rebuilt

    def _post_commit_action_context_locked(
        self,
        registry: Mapping[str, Any],
        *,
        run_id: str,
        task_commit: str,
        root_verification_digest: str,
        source_checkpoint_digest: str,
        remediation_scope: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        _require_string(run_id, "post-commit action run ID")
        _require_git_sha(task_commit, "post-commit action task commit")
        _require_hex(root_verification_digest, "post-commit action root verification")
        _require_hex(source_checkpoint_digest, "post-commit action source checkpoint")
        lease = registry.get("lease")
        if (
            not isinstance(lease, dict)
            or lease.get("state") != "stopped-terminal"
            or _lease_run_id(lease) != run_id
            or not isinstance(lease.get("source_state_id"), str)
            or lease.get("terminal_receipt", {}).get("success") is not True
            or lease.get("terminal_receipt", {}).get("terminal_event") != "turn.completed"
            or not isinstance(lease.get("zero_proof"), Mapping)
            or registry.get("outbox") is not None
            or registry.get("quarantine") is not None
        ):
            raise RecoveryStateError("post-commit action requires stopped no-handoff containment")
        source = self._read_source_locked(lease["source_state_id"])
        checkpoint = source.get("public_checkpoint")
        binding = source.get("source_binding")
        if not isinstance(checkpoint, Mapping) or not isinstance(binding, Mapping):
            raise RecoveryStateError("post-commit action source checkpoint is unavailable")
        manifest = self._validated_remediation_scope(
            remediation_scope,
            source_checkpoint_digest=source_checkpoint_digest,
            specification_revision=str(binding.get("specification_revision") or ""),
            milestone=str(binding.get("source_milestone") or ""),
            producer_allowed_set_digest=str(lease.get("allowed_set_digest") or ""),
            root_verification_digest=root_verification_digest,
        )
        if checkpoint.get("checkpoint_digest") != source_checkpoint_digest:
            raise RecoveryStateError("post-commit action checkpoint drifted")
        tuple_basis = {
            "run_id": run_id,
            "task_commit": task_commit,
            "root_verification_digest": root_verification_digest,
            "source_checkpoint_digest": source_checkpoint_digest,
            "producer_allowed_set_digest": lease["allowed_set_digest"],
            "remediation_scope_digest": manifest["digest"],
            "specification_revision": binding["specification_revision"],
            "milestone": binding["source_milestone"],
        }
        return lease, source, manifest, tuple_basis

    def build_post_commit_root_completion_action_snapshot(
        self,
        *,
        run_id: str,
        task_commit: str,
        root_verification_digest: str,
        source_checkpoint_digest: str,
        remediation_scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build one canonical same-account confirmation snapshot without issuing it."""
        with self._lock():
            registry = self._read_registry_locked(rebarrier=True)
            _lease, _source, _manifest, tuple_basis = self._post_commit_action_context_locked(
                registry,
                run_id=run_id,
                task_commit=task_commit,
                root_verification_digest=root_verification_digest,
                source_checkpoint_digest=source_checkpoint_digest,
                remediation_scope=remediation_scope,
            )
            return {
                "schema": "post-commit-root-completion-user-action-v1",
                "status": "confirmed",
                "session_action_id": secrets.token_hex(32),
                "normalized_intent": "authorize-post-commit-root-completion",
                "workspace_identity_digest": self.workspace_key,
                **tuple_basis,
            }

    def stage_post_commit_root_completion_action(
        self,
        *,
        run_id: str,
        task_commit: str,
        root_verification_digest: str,
        source_checkpoint_digest: str,
        remediation_scope: Mapping[str, Any],
        action_snapshot: Mapping[str, Any],
        action_snapshot_id: str,
        action_snapshot_sha256: str,
    ) -> dict[str, Any]:
        """Bind one pre-existing confirmed action snapshot to the private source."""
        _require_hex(action_snapshot_id, "post-commit action snapshot ID")
        _require_hex(action_snapshot_sha256, "post-commit action snapshot SHA-256")
        snapshot = _require_exact_object(
            action_snapshot,
            "post-commit root completion action snapshot",
            {
                "schema",
                "status",
                "session_action_id",
                "normalized_intent",
                "workspace_identity_digest",
                "run_id",
                "task_commit",
                "root_verification_digest",
                "source_checkpoint_digest",
                "producer_allowed_set_digest",
                "remediation_scope_digest",
                "specification_revision",
                "milestone",
            },
        )
        _require_hex(snapshot["session_action_id"], "post-commit session action ID")
        if hashlib.sha256(_canonical(snapshot)).hexdigest() != action_snapshot_sha256:
            raise RecoveryStateError("post-commit action snapshot digest drifted")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            _lease, source, _manifest, tuple_basis = self._post_commit_action_context_locked(
                registry,
                run_id=run_id,
                task_commit=task_commit,
                root_verification_digest=root_verification_digest,
                source_checkpoint_digest=source_checkpoint_digest,
                remediation_scope=remediation_scope,
            )
            expected_snapshot = {
                "schema": "post-commit-root-completion-user-action-v1",
                "status": "confirmed",
                "session_action_id": snapshot["session_action_id"],
                "normalized_intent": "authorize-post-commit-root-completion",
                "workspace_identity_digest": self.workspace_key,
                **tuple_basis,
            }
            if snapshot != expected_snapshot:
                raise RecoveryStateError("post-commit action snapshot tuple drifted")
            action = {
                **expected_snapshot,
                "action_id": snapshot["session_action_id"],
                "action_snapshot_id": action_snapshot_id,
                "action_snapshot_sha256": action_snapshot_sha256,
                "tuple_digest": _domain_digest(
                    _DOMAIN_POST_COMMIT_ACTION,
                    {
                        "action_snapshot_id": action_snapshot_id,
                        "action_snapshot_sha256": action_snapshot_sha256,
                        "snapshot": snapshot,
                    },
                ),
            }
            existing = source.get("post_commit_root_completion")
            if isinstance(existing, Mapping):
                if existing.get("action") == action and existing.get("authorization") is None:
                    if registry.get("reader_floor") != READER_FLOOR:
                        self._commit_registry_locked(registry)
                    return {
                        "action_handle": action["action_id"],
                        "action_digest": action["tuple_digest"],
                    }
                existing_action = existing.get("action")
                existing_authorization = existing.get("authorization")
                semantic = registry.get("lease", {}).get("semantic_disposition")
                replacement_allowed = (
                    isinstance(existing_action, Mapping)
                    and isinstance(existing_authorization, Mapping)
                    and existing_action.get("status") == "issued"
                    and existing_authorization.get("status") == "issued"
                    and semantic is None
                    and existing_action.get("action_snapshot_id") != action_snapshot_id
                    and all(
                        existing_action.get(field) == value
                        for field, value in tuple_basis.items()
                    )
                )
                if not replacement_allowed:
                    raise RecoveryStateError(
                        "post-commit action snapshot was already issued or replaced"
                    )
            source["post_commit_root_completion"] = {"action": action, "authorization": None}
            self._commit_source_locked(source)
            # The write preflight made the current reader floor durable before
            # the source shape became visible; retain the existing registry event.
            self._commit_registry_locked(registry)
            return {
                "action_handle": action["action_id"],
                "action_digest": action["tuple_digest"],
            }

    def issue_post_commit_root_completion_authorization(
        self, action: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Issue one short-lived opaque capability for a staged exact tuple."""
        action_handle = action.get("action_handle") if isinstance(action, Mapping) else None
        action_digest = action.get("action_digest") if isinstance(action, Mapping) else None
        _require_hex(action_handle, "post-commit action handle")
        _require_hex(action_digest, "post-commit action digest")
        with self._lock():
            registry = self._read_registry_for_write_locked(rebarrier=True)
            lease = registry.get("lease")
            if not isinstance(lease, Mapping) or not isinstance(lease.get("source_state_id"), str):
                raise RecoveryStateError("post-commit authorization requires an active source")
            source = self._read_source_locked(lease["source_state_id"])
            post = source.get("post_commit_root_completion")
            if not isinstance(post, Mapping) or not isinstance(post.get("action"), Mapping):
                raise RecoveryStateError("post-commit authorization action is missing")
            staged = post["action"]
            existing = post.get("authorization")
            if isinstance(existing, Mapping):
                raise RecoveryStateError("post-commit action snapshot was already issued")
            if (
                staged.get("status") != "confirmed"
                or staged.get("action_id") != action_handle
                or staged.get("tuple_digest") != action_digest
            ):
                raise RecoveryStateError("post-commit authorization action binding drifted")
            issued_at_ns = time.time_ns()
            authorization = {
                "schema": "post-commit-root-completion-authorization-v1",
                "status": "issued",
                "action_id": staged["action_id"],
                "authorization_handle": secrets.token_hex(32),
                "capability": secrets.token_hex(32),
                "tuple_digest": staged["tuple_digest"],
                "issued_at_ns": issued_at_ns,
                "expires_at_ns": issued_at_ns + 300_000_000_000,
            }
            issued_action = dict(staged)
            issued_action["status"] = "issued"
            source["post_commit_root_completion"] = {
                "action": issued_action,
                "authorization": authorization,
            }
            self._commit_source_locked(source)
            return {
                "authorization_handle": authorization["authorization_handle"],
                "authorization_digest": self._post_commit_authorization_digest(authorization),
            }

    def _task_commit_paths(self, task_commit: str) -> list[str]:
        raw = self._git(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            task_commit,
        )
        paths = [_normalize_relative(_decode_git_path(value)) for value in raw.split(b"\0") if value]
        if len(set(paths)) != len(paths):
            raise RecoveryStateError("task commit contains duplicate normalized paths")
        return sorted(paths)

    def _verified_intervening_root_commits(
        self,
        checkpoint_head: str,
        task_parent: str,
        allowed_paths: Sequence[str],
        records: Mapping[str, Mapping[str, Any]],
    ) -> list[str]:
        """Return a linear checkpoint-to-parent chain, rejecting merges and unrelated history."""
        _require_git_sha(checkpoint_head, "post-commit checkpoint head")
        _require_git_sha(task_parent, "post-commit task parent")
        if checkpoint_head == task_parent:
            return []
        merge_base = self._git(
            "merge-base", checkpoint_head, task_parent, allow_failure=True
        ).strip().decode("ascii")
        if merge_base != checkpoint_head:
            raise RecoveryStateError("post-commit task parent does not descend from checkpoint")
        raw = self._git(
            "rev-list", "--reverse", "--parents", f"{checkpoint_head}..{task_parent}"
        )
        previous = checkpoint_head
        commits: list[str] = []
        for raw_line in raw.splitlines():
            fields = raw_line.decode("ascii").split()
            if len(fields) != 2 or fields[1] != previous:
                raise RecoveryStateError("post-commit intervening history is not linear")
            commit = fields[0]
            _require_git_sha(commit, "post-commit intervening commit")
            commits.append(commit)
            previous = commit
        if not commits or previous != task_parent:
            raise RecoveryStateError("post-commit intervening history is incomplete")
        intervening_paths = {
            path for commit in commits for path in self._task_commit_paths(commit)
        }
        if any(
            self._path_is_allowed(path, allowed_paths, records)
            for path in intervening_paths
        ):
            raise RecoveryStateError(
                "post-commit intervening history overlaps immutable producer scope"
            )
        return commits

    def finalize_post_commit_root_completion(
        self,
        lease_id: str,
        *,
        run_id: str,
        task_commit: str,
        root_verification_digest: str,
        authorization_handle: str,
        remediation_scope: Mapping[str, Any],
        terminal_binding_format: str,
    ) -> dict[str, Any]:
        """Atomically bind capability consumption to the first root-completion intent."""
        _require_string(run_id, "post-commit finalization run ID")
        _require_git_sha(task_commit, "post-commit finalization task commit")
        _require_hex(root_verification_digest, "post-commit finalization root verification")
        _require_hex(authorization_handle, "post-commit authorization handle")
        if terminal_binding_format != "run-dir-v1":
            raise RecoveryStateError("post-commit finalization requires exact legacy terminal binding")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id:
                raise RecoveryStateError("post-commit finalization lease is missing")
            semantic = lease.get("semantic_disposition")
            source_state_id = lease.get("source_state_id")
            if not isinstance(source_state_id, str):
                raise RecoveryStateError("post-commit finalization source is missing")
            source = self._read_source_locked(source_state_id)
            post = source.get("post_commit_root_completion")
            action = post.get("action") if isinstance(post, Mapping) else None
            authorization = post.get("authorization") if isinstance(post, Mapping) else None
            if not isinstance(action, Mapping) or not isinstance(authorization, Mapping):
                raise RecoveryStateError("post-commit finalization authorization is missing")
            authorization_digest = self._post_commit_authorization_digest(authorization)
            binding = source.get("source_binding")
            if not isinstance(binding, Mapping):
                raise RecoveryStateError("post-commit finalization source binding is unavailable")
            manifest = self._validated_remediation_scope(
                remediation_scope,
                source_checkpoint_digest=action["source_checkpoint_digest"],
                specification_revision=binding["specification_revision"],
                milestone=binding["source_milestone"],
                producer_allowed_set_digest=lease["allowed_set_digest"],
                root_verification_digest=root_verification_digest,
            )
            if manifest["digest"] != action.get("remediation_scope_digest"):
                raise RecoveryStateError("post-commit finalization remediation scope drifted")
            if isinstance(semantic, Mapping):
                if (
                    semantic.get("disposition") == "root-completed"
                    and semantic.get("run_id") == run_id
                    and semantic.get("task_commit") == task_commit
                    and semantic.get("root_verification_digest") == root_verification_digest
                    and semantic.get("authorization_digest") == authorization_digest
                    and semantic.get("authorization_consumption") == "consumed"
                    and semantic.get("terminal_binding_format") == terminal_binding_format
                    and semantic.get("remediation_scope_digest") == manifest["digest"]
                    and authorization.get("authorization_handle") == authorization_handle
                ):
                    if authorization.get("status") == "issued":
                        consumed = dict(authorization)
                        consumed["status"] = "consumed"
                        source["post_commit_root_completion"] = {
                            "action": dict(action),
                            "authorization": consumed,
                        }
                        self._commit_source_locked(source)
                    elif authorization.get("status") != "consumed":
                        raise RecoveryStateError(
                            "post-commit finalization authorization consumption drifted"
                        )
                    return state
                raise RecoveryStateError("terminal lease already has a different semantic disposition")
            if (
                lease.get("state") != "stopped-terminal"
                or lease.get("terminal_receipt", {}).get("success") is not True
                or lease.get("terminal_receipt", {}).get("terminal_event") != "turn.completed"
                or lease.get("terminal_receipt", {}).get("binding_format") not in {None, "run-dir-v1"}
                or not isinstance(lease.get("zero_proof"), Mapping)
                or state.get("outbox") is not None
                or state.get("quarantine") is not None
                or _lease_run_id(lease) != run_id
                or authorization.get("status") != "issued"
                or authorization.get("authorization_handle") != authorization_handle
                or authorization.get("expires_at_ns", 0) <= time.time_ns()
                or action.get("run_id") != run_id
                or action.get("task_commit") != task_commit
                or action.get("root_verification_digest") != root_verification_digest
            ):
                raise RecoveryStateError("post-commit finalization safety proof is incomplete")
            checkpoint = source.get("public_checkpoint")
            if not isinstance(checkpoint, Mapping):
                raise RecoveryStateError("post-commit finalization checkpoint is unavailable")
            if checkpoint.get("checkpoint_digest") != action.get("source_checkpoint_digest"):
                raise RecoveryStateError("post-commit finalization checkpoint drifted")
            parent = self._git("rev-parse", "--verify", f"{task_commit}^").strip().decode("ascii")
            if parent != manifest["parent_commit"]:
                raise RecoveryStateError("post-commit task parent provenance drifted")
            checkpoint_head = source["pre_snapshot"]["head"]
            allowed_paths = source["pre_snapshot"]["allowed_paths"]
            records = source["pre_snapshot"]["records"]
            intervening_commits = self._verified_intervening_root_commits(
                checkpoint_head, parent, allowed_paths, records
            )
            merge_base = self._git("merge-base", task_commit, "HEAD").strip().decode("ascii")
            if merge_base != task_commit:
                raise RecoveryStateError("post-commit task commit is not an ancestor of HEAD")
            commit_paths = self._task_commit_paths(task_commit)
            entries = {entry["path"]: entry["role"] for entry in manifest["entries"]}
            if set(commit_paths) != set(entries):
                raise RecoveryStateError("post-commit task paths do not exactly match remediation scope")
            if any(
                (role == "producer" and not self._path_is_allowed(path, allowed_paths, records))
                or role not in {"producer", "root-completion"}
                for path, role in entries.items()
            ):
                raise RecoveryStateError("post-commit remediation role is outside its immutable scope")
            proof_source, candidate_checkpoint = self._revalidate_source_locked(
                copy.deepcopy(source), checkpoint, persist=False
            )
            if candidate_checkpoint.get("reasons") != ["git-control-plane-drift", "outside-set-drift"]:
                raise RecoveryStateError("post-commit finalization requires exact mixed drift")
            candidate_snapshot = candidate_checkpoint.get("candidate_snapshot")
            if not isinstance(candidate_snapshot, Mapping):
                raise RecoveryStateError("post-commit finalization candidate snapshot is missing")
            provenance = {
                "head": proof_source["candidate_snapshot"]["head"],
                "ref": proof_source["candidate_snapshot"]["ref"],
                "full_index": proof_source["candidate_snapshot"]["full_index"],
                "status": proof_source["candidate_snapshot"]["status"],
                "records": proof_source["candidate_snapshot"]["records"],
                "task_commit": task_commit,
                "checkpoint_head": checkpoint_head,
                "parent_commit": parent,
                "intervening_commits": intervening_commits,
                "commit_paths": commit_paths,
            }
            # Re-capture immediately before intent; any race remains a no-mutation failure.
            _, barrier_checkpoint = self._revalidate_source_locked(
                proof_source, candidate_checkpoint, persist=False
            )
            if barrier_checkpoint != candidate_checkpoint:
                raise RecoveryStateError("post-commit Git provenance drifted before durable intent")
            terminal_binding = lease["terminal_receipt"].get("binding_digest")
            if not isinstance(terminal_binding, str):
                raise RecoveryStateError("post-commit terminal binding is missing")
            semantic = {
                "disposition": "root-completed",
                "schema": "terminal-root-completion-v1",
                "run_id": run_id,
                "lease_id": lease_id,
                "source_state_id": source_state_id,
                "source_checkpoint_digest": action["source_checkpoint_digest"],
                "allowed_set_digest": lease["allowed_set_digest"],
                "remediation_scope_digest": manifest["digest"],
                "task_commit": task_commit,
                "parent_commit": parent,
                "root_verification_digest": root_verification_digest,
                "user_action_digest": action["tuple_digest"],
                "authorization_digest": authorization_digest,
                "authorization_consumption": "consumed",
                "terminal_binding_format": terminal_binding_format,
                "terminal_binding_digest": terminal_binding,
                "zero_proof_digest": _terminal_part_digest("zero", lease["zero_proof"]),
                "candidate_snapshot_digest": _domain_digest(_DOMAIN_CHECKPOINT, candidate_snapshot),
                "git_provenance_digest": _domain_digest(_DOMAIN_CHECKPOINT, provenance),
                "checkpoint_invalidation": "pending",
            }
            lease["semantic_disposition"] = semantic
            lease["terminal_receipt"]["success"] = False
            lease["terminal_receipt"]["semantic_rejected"] = True
            lease["terminal_receipt"]["semantic_evidence_digest"] = authorization_digest
            state["history"].append({"event": "terminal-root-completion-recorded", **semantic})
            committed = self._commit_registry_locked(state)
            # The intent is now durable.  A reload treats it as the authority
            # if a source write crashes, so a capability cannot be reused.
            authorization = dict(authorization)
            authorization["status"] = "consumed"
            source["post_commit_root_completion"] = {"action": dict(action), "authorization": authorization}
            self._commit_source_locked(source)
            return committed

    def complete_post_commit_root_completion(self, lease_id: str) -> dict[str, Any]:
        """Invalidate the exact source checkpoint after a durable root intent."""
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            semantic = lease.get("semantic_disposition") if isinstance(lease, Mapping) else None
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "stopped-terminal"
                or not isinstance(semantic, dict)
                or semantic.get("disposition") != "root-completed"
            ):
                raise RecoveryStateError("post-commit root completion is not bound to the stopped lease")
            if semantic.get("checkpoint_invalidation") == "completed":
                return state
            if semantic.get("checkpoint_invalidation") != "pending":
                raise RecoveryStateError("post-commit root completion invalidation is not pending")
            source = self._read_source_locked(semantic["source_state_id"])
            checkpoint = source.get("public_checkpoint")
            if not isinstance(checkpoint, Mapping):
                raise RecoveryStateError("post-commit root completion source checkpoint drifted")
            invalidation = source.get("checkpoint_invalidation")
            if checkpoint.get("checkpoint_digest") == semantic.get("source_checkpoint_digest"):
                source, candidate = self._revalidate_source_locked(source, checkpoint, persist=False)
                if (
                    candidate.get("reasons") != ["git-control-plane-drift", "outside-set-drift"]
                    or _domain_digest(_DOMAIN_CHECKPOINT, candidate.get("candidate_snapshot"))
                    != semantic.get("candidate_snapshot_digest")
                ):
                    raise RecoveryStateError("post-commit root completion source evidence drifted")
                invalidated = dict(candidate)
                invalidated["disposition"] = "recovery-ineligible"
                invalidated["reasons"] = ["post-commit-root-completed"]
                invalidated["checkpoint_digest"] = self._checkpoint_digest(invalidated)
                source["public_checkpoint"] = invalidated
                source["checkpoint_invalidation"] = {
                    "reason": "post-commit-root-completed",
                    "evidence_digest": semantic["authorization_digest"],
                }
                post = source.get("post_commit_root_completion")
                if not isinstance(post, Mapping) or not isinstance(
                    post.get("authorization"), Mapping
                ):
                    raise RecoveryStateError("post-commit root completion authorization is missing")
                if post["authorization"].get("status") == "issued":
                    post = dict(post)
                    authorization = dict(post["authorization"])
                    authorization["status"] = "consumed"
                    post["authorization"] = authorization
                    source["post_commit_root_completion"] = post
                self._commit_source_locked(source)
            elif (
                checkpoint.get("disposition") == "recovery-ineligible"
                and checkpoint.get("reasons") == ["post-commit-root-completed"]
                and isinstance(invalidation, Mapping)
                and invalidation.get("reason") == "post-commit-root-completed"
                and invalidation.get("evidence_digest") == semantic.get("authorization_digest")
                and _domain_digest(_DOMAIN_CHECKPOINT, checkpoint.get("candidate_snapshot"))
                == semantic.get("candidate_snapshot_digest")
            ):
                invalidated = dict(checkpoint)
            else:
                raise RecoveryStateError("post-commit root completion source checkpoint drifted")
            if any(
                event.get("event") == "terminal-root-completion-completed"
                and event.get("lease_id") == lease_id
                for event in state["history"]
            ):
                raise RecoveryStateError("post-commit root completion event preceded registry phase")
            semantic["checkpoint_invalidation"] = "completed"
            semantic["checkpoint_digest"] = invalidated["checkpoint_digest"]
            state["history"].append(
                {
                    "event": "terminal-root-completion-completed",
                    "lease_id": lease_id,
                    "run_id": semantic["run_id"],
                    "source_state_id": semantic["source_state_id"],
                    "checkpoint_digest": semantic["checkpoint_digest"],
                    "authorization_digest": semantic["authorization_digest"],
                }
            )
            return self._commit_registry_locked(state)

    def post_commit_root_completion_replay_binding(
        self,
        *,
        lease_id: str,
        run_id: str,
        task_commit: str,
        root_verification_digest: str,
        authorization_handle: str,
        remediation_scope_digest: str,
    ) -> dict[str, Any]:
        """Rebuild the exact released tuple before returning completed replay."""
        _require_string(lease_id, "post-commit replay lease ID")
        _require_string(run_id, "post-commit replay run ID")
        _require_git_sha(task_commit, "post-commit replay task commit")
        _require_hex(root_verification_digest, "post-commit replay root verification")
        _require_hex(authorization_handle, "post-commit replay authorization handle")
        _require_hex(remediation_scope_digest, "post-commit replay remediation scope")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            recorded = [
                event
                for event in state["history"]
                if event.get("event") == "terminal-root-completion-recorded"
                and event.get("lease_id") == lease_id
                and event.get("run_id") == run_id
            ]
            completed = [
                event
                for event in state["history"]
                if event.get("event") == "terminal-root-completion-completed"
                and event.get("lease_id") == lease_id
                and event.get("run_id") == run_id
            ]
            released = [
                event
                for event in state["history"]
                if event.get("event") == "contained-terminal-released"
                and event.get("lease_id") == lease_id
                and event.get("semantic_disposition") == "root-completed"
            ]
            if (
                state.get("lease") is not None
                or state.get("outbox") is not None
                or len(recorded) != 1
                or len(completed) != 1
                or len(released) != 1
            ):
                raise RecoveryStateError("post-commit completed replay binding drifted")
            semantic = dict(recorded[0])
            semantic.pop("event")
            semantic["checkpoint_invalidation"] = "completed"
            semantic["checkpoint_digest"] = completed[0]["checkpoint_digest"]
            _validate_semantic_disposition(semantic)
            source = self._read_source_locked(semantic["source_state_id"])
            post = source.get("post_commit_root_completion")
            action = post.get("action") if isinstance(post, Mapping) else None
            authorization = post.get("authorization") if isinstance(post, Mapping) else None
            if not isinstance(action, Mapping) or not isinstance(authorization, Mapping):
                raise RecoveryStateError("post-commit completed replay binding drifted")
            authorization_digest = self._post_commit_authorization_digest(authorization)
            if (
                semantic.get("task_commit") != task_commit
                or semantic.get("root_verification_digest") != root_verification_digest
                or semantic.get("remediation_scope_digest") != remediation_scope_digest
                or semantic.get("authorization_consumption") != "consumed"
                or semantic.get("terminal_binding_format") != "run-dir-v1"
                or semantic.get("authorization_digest") != authorization_digest
                or action.get("run_id") != run_id
                or action.get("task_commit") != task_commit
                or action.get("root_verification_digest") != root_verification_digest
                or action.get("remediation_scope_digest") != remediation_scope_digest
                or action.get("tuple_digest") != semantic.get("user_action_digest")
                or action.get("source_checkpoint_digest")
                != semantic.get("source_checkpoint_digest")
                or action.get("producer_allowed_set_digest")
                != semantic.get("allowed_set_digest")
                or authorization.get("status") != "consumed"
                or authorization.get("authorization_handle") != authorization_handle
                or authorization.get("tuple_digest") != action.get("tuple_digest")
                or completed[0].get("source_state_id") != semantic.get("source_state_id")
                or completed[0].get("authorization_digest") != authorization_digest
                or released[0].get("semantic_disposition_digest")
                != _terminal_part_digest("semantic", semantic)
            ):
                raise RecoveryStateError("post-commit completed replay binding drifted")
            return {
                "schema": "terminal-root-completion-artifact-v1",
                "lease_id": lease_id,
                "run_id": run_id,
                "source_state_id": semantic["source_state_id"],
                "task_commit": task_commit,
                "parent_commit": semantic["parent_commit"],
                "root_verification_digest": root_verification_digest,
                "producer_allowed_set_digest": action["producer_allowed_set_digest"],
                "remediation_scope_digest": remediation_scope_digest,
                "action_snapshot_id": action["action_snapshot_id"],
                "action_snapshot_sha256": action["action_snapshot_sha256"],
                "user_action_digest": action["tuple_digest"],
                "authorization_digest": authorization_digest,
                "authorization_consumption": "consumed",
                "terminal_binding_format": semantic["terminal_binding_format"],
                "terminal_binding_digest": semantic["terminal_binding_digest"],
                "checkpoint_digest": semantic["checkpoint_digest"],
                "archive_digest": released[0]["archive_digest"],
            }

    def record_terminal_abandonment(
        self,
        lease_id: str,
        *,
        _containment_loss_reconciliation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one exact supported no-handoff terminal abandonment outcome.

        The caller has no cause, digest, checkpoint, or force input.  This is
        deliberately a continuation of the contained producer lifecycle, not
        a replacement-writer or generic unlock API.
        """
        with self._lock():
            state = self._read_registry_locked(
                rebarrier=True,
                allow_quarantine=_containment_loss_reconciliation is not None,
            )
            lease = state.get("lease")
            semantic = lease.get("semantic_disposition") if isinstance(lease, dict) else None
            if isinstance(semantic, dict):
                if semantic.get("disposition") != "abandoned":
                    raise RecoveryStateError("terminal lease already has a different semantic disposition")
                if _containment_loss_reconciliation is not None:
                    run_id = _lease_run_id(lease)
                    reconciled = [
                        event
                        for event in state["history"]
                        if event.get("event") == "containment-loss-reconciled"
                        and event.get("lease_id") == lease_id
                        and event.get("run_id") == run_id
                    ]
                    if state.get("quarantine") is not None or len(reconciled) != 1:
                        raise RecoveryStateError(
                            "containment-loss reconciliation replay is not authoritative"
                        )
                return state
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "stopped-terminal"
                or lease.get("terminal_receipt", {}).get("success") is not True
                or lease.get("terminal_receipt", {}).get("terminal_event") != "turn.completed"
                or not isinstance(lease.get("zero_proof"), Mapping)
                or state.get("outbox") is not None
            ):
                raise RecoveryStateError("terminal abandonment requires stopped transport-success containment")
            source_state_id = lease.get("source_state_id")
            run_id = _lease_run_id(lease)
            if not isinstance(source_state_id, str) or not isinstance(run_id, str):
                raise RecoveryStateError("terminal abandonment lacks exact source or run binding")
            source = self._read_source_locked(source_state_id)
            checkpoint = source.get("public_checkpoint")
            if not isinstance(checkpoint, Mapping):
                raise RecoveryStateError("terminal abandonment lacks a materialized source checkpoint")
            source_checkpoint_digest = checkpoint.get("checkpoint_digest")
            if not isinstance(source_checkpoint_digest, str):
                raise RecoveryStateError("terminal abandonment source checkpoint is malformed")
            source, candidate_checkpoint = self._revalidate_source_locked(
                source, checkpoint, persist=False
            )
            reasons = candidate_checkpoint.get("reasons")
            if reasons == ["outside-set-drift"]:
                schema = "terminal-abandonment-v1"
                cause = "outside-set-drift"
            elif (
                lease.get("lease_kind") == "recovery-target"
                and reasons == ["outside-set-drift", "preexisting-dirty-overlap"]
            ):
                schema = "terminal-abandonment-v2"
                cause = "outside-set-drift-with-preexisting-dirty-overlap"
            elif (
                lease.get("lease_kind") == "normal-contained"
                and reasons == ["outside-set-drift", "preexisting-dirty-overlap"]
            ):
                schema = "terminal-abandonment-v3"
                cause = "legacy-normal-outside-set-drift-with-preexisting-dirty-overlap"
            elif (
                lease.get("lease_kind") == "normal-contained"
                and reasons == ["preexisting-dirty-overlap"]
            ):
                schema = "terminal-abandonment-v5"
                cause = "legacy-normal-preexisting-dirty-overlap"
            elif (
                _containment_loss_reconciliation is not None
                and lease.get("lease_kind") == "normal-contained"
                and reasons
                == [
                    "git-control-plane-drift",
                    "outside-set-drift",
                    "preexisting-dirty-overlap",
                ]
            ):
                schema = "terminal-abandonment-v4"
                cause = (
                    "legacy-normal-control-plane-and-outside-set-drift-with-"
                    "preexisting-dirty-overlap"
                )
            else:
                raise RecoveryStateError(
                    "terminal abandonment requires an exact supported drift shape"
                )
            candidate_snapshot = candidate_checkpoint.get("candidate_snapshot")
            if not isinstance(candidate_snapshot, Mapping):
                raise RecoveryStateError("terminal abandonment lacks a candidate snapshot")
            terminal_binding = lease["terminal_receipt"].get("binding_digest")
            if not isinstance(terminal_binding, str):
                raise RecoveryStateError("terminal abandonment terminal binding is missing")
            zero_digest = _terminal_part_digest("zero", lease["zero_proof"])
            reconciliation_event: dict[str, Any] | None = None
            if _containment_loss_reconciliation is not None:
                proof = _require_exact_object(
                    _containment_loss_reconciliation,
                    "containment-loss reconciliation proof",
                    {
                        "schema",
                        "guardian_pid",
                        "guardian_identity",
                        "guardian_state",
                        "worker_pid",
                        "worker_identity",
                        "worker_state",
                        "reconciled_at",
                    },
                )
                provider = lease.get("provider_receipt")
                process = lease.get("process_receipt")
                zero = lease.get("zero_proof")
                if (
                    state.get("quarantine") != "containment-loss-after-boundary"
                    or not isinstance(provider, Mapping)
                    or not isinstance(process, Mapping)
                    or not isinstance(zero, Mapping)
                    or proof["schema"] != "containment-loss-reconciliation-v1"
                    or proof["guardian_pid"] != provider.get("guardian_pid")
                    or proof["guardian_identity"] != provider.get("guardian_identity")
                    or proof["worker_pid"] != process.get("pid")
                    or proof["worker_identity"] != process.get("identity")
                ):
                    raise RecoveryStateError(
                        "containment-loss reconciliation identity binding drifted"
                    )
                if proof["guardian_state"] not in {"stopped", "reused"} or proof[
                    "worker_state"
                ] not in {"stopped", "reused"}:
                    raise RecoveryStateError(
                        "containment-loss reconciliation original processes must be stopped"
                    )
                _require_string(proof["reconciled_at"], "containment-loss reconciliation time")
                loss_events = [
                    event
                    for event in state["history"]
                    if event.get("event") == "containment-loss-quarantined"
                    and event.get("lease_id") == lease_id
                ]
                if len(loss_events) != 1:
                    raise RecoveryStateError(
                        "containment-loss reconciliation requires one quarantine event"
                    )
                proof_basis = {
                    **dict(proof),
                    "run_id": run_id,
                    "lease_id": lease_id,
                    "provider": provider.get("provider"),
                    "guardian_id": provider.get("guardian_id"),
                    "terminal_binding_digest": terminal_binding,
                    "zero_proof_digest": zero_digest,
                }
                reconciliation_event = {
                    "event": "containment-loss-reconciled",
                    **proof_basis,
                    "proof_digest": _domain_digest(
                        _DOMAIN_CONTAINMENT_LOSS_RECONCILIATION, proof_basis
                    ),
                }
                state["quarantine"] = None
            candidate_digest = _domain_digest(_DOMAIN_CHECKPOINT, candidate_snapshot)
            evidence_basis = {
                "schema": schema,
                "cause": cause,
                "run_id": run_id,
                "lease_id": lease_id,
                "source_state_id": source_state_id,
                "source_checkpoint_digest": source_checkpoint_digest,
                "allowed_set_digest": lease.get("allowed_set_digest"),
                "terminal_binding_digest": terminal_binding,
                "zero_proof_digest": zero_digest,
                "candidate_snapshot_digest": candidate_digest,
            }
            evidence_digest = _domain_digest(_DOMAIN_TERMINAL_ABANDONMENT, evidence_basis)
            semantic = {
                "disposition": "abandoned",
                **evidence_basis,
                "evidence_digest": evidence_digest,
                "checkpoint_allowed": False,
                "checkpoint_invalidation": "pending",
            }
            lease["semantic_disposition"] = semantic
            lease["terminal_receipt"]["success"] = False
            lease["terminal_receipt"]["semantic_rejected"] = True
            lease["terminal_receipt"]["semantic_evidence_digest"] = evidence_digest
            if reconciliation_event is not None:
                state["history"].append(reconciliation_event)
            state["history"].append({"event": "terminal-abandonment-recorded", **semantic})
            return self._commit_registry_locked(state)

    def record_containment_loss_abandonment(
        self,
        lease_id: str,
        reconciliation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Turn exact post-zero guardian loss into the existing no-handoff abandonment."""
        return self.record_terminal_abandonment(
            lease_id,
            _containment_loss_reconciliation=reconciliation,
        )

    def complete_terminal_abandonment(self, lease_id: str) -> dict[str, Any]:
        """Complete the source invalidation bound by a recorded abandonment."""
        with self._lock():
            state = self._read_registry_for_write_locked(rebarrier=True)
            lease = state.get("lease")
            semantic = lease.get("semantic_disposition") if isinstance(lease, dict) else None
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "stopped-terminal"
                or not isinstance(semantic, dict)
                or semantic.get("disposition") != "abandoned"
            ):
                raise RecoveryStateError("terminal abandonment is not bound to the stopped lease")
            if semantic.get("checkpoint_invalidation") == "completed":
                return state
            if semantic.get("checkpoint_invalidation") != "pending":
                raise RecoveryStateError("terminal abandonment invalidation is not pending")
            source_state_id = semantic.get("source_state_id")
            evidence_digest = semantic.get("evidence_digest")
            if not isinstance(source_state_id, str) or not isinstance(evidence_digest, str):
                raise RecoveryStateError("terminal abandonment binding is incomplete")
            source = self._read_source_locked(source_state_id)
            checkpoint = source.get("public_checkpoint")
            if not isinstance(checkpoint, Mapping):
                raise RecoveryStateError("terminal abandonment source checkpoint drifted")
            retirement_event = None
            if lease.get("lease_kind") == "recovery-target":
                plan = lease.get("plan")
                grant_id = lease.get("grant_id")
                if (
                    not isinstance(plan, Mapping)
                    or not isinstance(grant_id, str)
                    or not isinstance(plan.get("prompt_snapshot_id"), str)
                    or not isinstance(plan.get("prompt_sha256"), str)
                ):
                    raise RecoveryStateError(
                        "terminal abandonment recovery authorization binding is incomplete"
                    )
                retirement_event = {
                    "event": "authorization-retired",
                    "source_state_id": source_state_id,
                    "grant_id": grant_id,
                    "prompt_snapshot_id": plan["prompt_snapshot_id"],
                    "prompt_sha256": plan["prompt_sha256"],
                }
                authorization = source.get("authorization")
                if authorization is not None and (
                    not isinstance(authorization, Mapping)
                    or authorization.get("grant_id") != grant_id
                    or authorization.get("prompt_snapshot_id")
                    != plan["prompt_snapshot_id"]
                    or authorization.get("prompt_sha256") != plan["prompt_sha256"]
                ):
                    raise RecoveryStateError(
                        "terminal abandonment recovery authorization binding drifted"
                    )
            invalidation = source.get("checkpoint_invalidation")
            invalidation_reason = (
                "terminal-abandoned-recovery-overlap"
                if semantic.get("schema") == "terminal-abandonment-v2"
                else (
                    "terminal-abandoned-legacy-normal-control-plane-overlap"
                    if semantic.get("schema") == "terminal-abandonment-v4"
                    else (
                        "terminal-abandoned-legacy-normal-dirty-overlap"
                        if semantic.get("schema") == "terminal-abandonment-v5"
                        else (
                            "terminal-abandoned-legacy-normal-overlap"
                            if semantic.get("schema") == "terminal-abandonment-v3"
                            else "terminal-abandoned-outside-set-drift"
                        )
                    )
                )
            )
            if (
                checkpoint.get("reasons") == [invalidation_reason]
                and invalidation
                == {
                    "reason": invalidation_reason,
                    "evidence_digest": evidence_digest,
                }
            ):
                candidate_snapshot = checkpoint.get("candidate_snapshot")
                if (
                    not isinstance(candidate_snapshot, Mapping)
                    or _domain_digest(_DOMAIN_CHECKPOINT, candidate_snapshot)
                    != semantic.get("candidate_snapshot_digest")
                ):
                    raise RecoveryStateError("terminal abandonment invalidated checkpoint drifted")
                invalidated = dict(checkpoint)
                if retirement_event is not None and source.get("authorization") is not None:
                    source["authorization"] = None
                    self._commit_source_locked(source)
            else:
                if checkpoint.get("checkpoint_digest") != semantic.get(
                    "source_checkpoint_digest"
                ):
                    raise RecoveryStateError("terminal abandonment source checkpoint drifted")
                source, candidate_checkpoint = self._revalidate_source_locked(
                    source, checkpoint, persist=False
                )
                candidate_snapshot = candidate_checkpoint.get("candidate_snapshot")
                if (
                    candidate_checkpoint.get("reasons")
                    != (
                        [
                            "git-control-plane-drift",
                            "outside-set-drift",
                            "preexisting-dirty-overlap",
                        ]
                        if semantic.get("schema") == "terminal-abandonment-v4"
                        else (
                            ["preexisting-dirty-overlap"]
                            if semantic.get("schema") == "terminal-abandonment-v5"
                            else (
                                ["outside-set-drift", "preexisting-dirty-overlap"]
                                if semantic.get("schema")
                                in {"terminal-abandonment-v2", "terminal-abandonment-v3"}
                                else ["outside-set-drift"]
                            )
                        )
                    )
                    or not isinstance(candidate_snapshot, Mapping)
                    or _domain_digest(_DOMAIN_CHECKPOINT, candidate_snapshot)
                    != semantic.get("candidate_snapshot_digest")
                ):
                    raise RecoveryStateError("terminal abandonment source checkpoint drifted")
                invalidated = dict(candidate_checkpoint)
                invalidated["disposition"] = "recovery-ineligible"
                invalidated["reasons"] = [invalidation_reason]
                invalidated["checkpoint_digest"] = self._checkpoint_digest(invalidated)
                source["public_checkpoint"] = invalidated
                source["checkpoint_invalidation"] = {
                    "reason": invalidation_reason,
                    "evidence_digest": evidence_digest,
                }
                if retirement_event is not None:
                    source["authorization"] = None
                self._commit_source_locked(source)
            semantic["checkpoint_invalidation"] = "completed"
            semantic["checkpoint_digest"] = invalidated["checkpoint_digest"]
            if retirement_event is not None and retirement_event not in state["history"]:
                state["history"].append(retirement_event)
            state["history"].append(
                {
                    "event": "terminal-abandonment-completed",
                    "lease_id": lease_id,
                    "run_id": semantic["run_id"],
                    "source_state_id": source_state_id,
                    "checkpoint_digest": semantic["checkpoint_digest"],
                    "evidence_digest": evidence_digest,
                }
            )
            return self._commit_registry_locked(state)

    def reject_semantic_handoff(
        self,
        lease_id: str,
        *,
        run_id: str,
        disposition: str,
        evidence_digest: str,
        checkpoint_allowed: bool,
    ) -> dict[str, Any]:
        """Bind root semantic rejection without manufacturing a successful handoff."""
        if disposition not in {"blocked", "needs-escalation"}:
            raise RecoveryStateError("semantic rejection disposition is unsupported")
        _require_hex(evidence_digest, "semantic rejection evidence digest")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            if any(
                event.get("event") == "semantic-handoff-rejected"
                and event.get("run_id") == run_id
                for event in state.get("history", [])
            ):
                raise RecoveryStateError("semantic rejection was already consumed for this run")
            lease = state.get("lease")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "stopped-terminal"
                or lease.get("terminal_receipt", {}).get("success") is not True
                or state.get("outbox") is not None
            ):
                raise RecoveryStateError("semantic rejection requires stopped transport-success containment")
            expected_run_id = _lease_run_id(lease)
            if run_id != expected_run_id:
                raise RecoveryStateError("semantic rejection run binding drifted")
            if checkpoint_allowed is not (disposition == "blocked"):
                raise RecoveryStateError("semantic rejection checkpoint disposition is inconsistent")
            if disposition == "needs-escalation":
                self._require_zero_write_source_locked(str(lease.get("source_state_id")))
            semantic = {
                "disposition": disposition,
                "evidence_digest": evidence_digest,
                "checkpoint_allowed": checkpoint_allowed,
                "checkpoint_invalidation": (
                    "not-required" if checkpoint_allowed else "pending"
                ),
                "run_id": run_id,
                "source_state_id": lease.get("source_state_id"),
            }
            lease["semantic_disposition"] = semantic
            lease["terminal_receipt"]["success"] = False
            lease["terminal_receipt"]["semantic_rejected"] = True
            lease["terminal_receipt"]["semantic_evidence_digest"] = evidence_digest
            state["history"].append(
                {
                    "event": "semantic-handoff-rejected",
                    "lease_id": lease_id,
                    **semantic,
                }
            )
            return self._commit_registry_locked(state)

    def invalidate_source_checkpoint(
        self,
        source_state_id: str,
        *,
        reason: str,
        evidence_digest: str,
    ) -> dict[str, Any]:
        """Invalidate a previously materialized checkpoint after zero-write escalation."""
        if reason not in {
            "semantic-needs-escalation",
            "terminal-abandoned-outside-set-drift",
            "terminal-abandoned-recovery-overlap",
            "terminal-abandoned-legacy-normal-overlap",
            "terminal-abandoned-legacy-normal-dirty-overlap",
            "terminal-abandoned-legacy-normal-control-plane-overlap",
            "post-commit-root-completed",
        }:
            raise RecoveryStateError("checkpoint invalidation reason is unsupported")
        _require_hex(evidence_digest, "checkpoint invalidation evidence digest")
        with self._lock():
            self._read_registry_for_write_locked(rebarrier=True)
            source = self._read_source_locked(source_state_id)
            checkpoint = source.get("public_checkpoint")
            if not isinstance(checkpoint, dict):
                raise RecoveryStateError("source checkpoint is unavailable for invalidation")
            prior = source.get("checkpoint_invalidation")
            if isinstance(prior, dict):
                if (
                    prior.get("reason") != reason
                    or prior.get("evidence_digest") != evidence_digest
                    or checkpoint.get("disposition") != "recovery-ineligible"
                    or checkpoint.get("reasons") != [reason]
                ):
                    raise RecoveryStateError("source checkpoint invalidation binding drifted")
                return dict(checkpoint)
            checkpoint = dict(checkpoint)
            checkpoint["disposition"] = "recovery-ineligible"
            checkpoint["reasons"] = [reason]
            checkpoint["checkpoint_digest"] = self._checkpoint_digest(checkpoint)
            source["public_checkpoint"] = checkpoint
            source["checkpoint_invalidation"] = {
                "reason": reason,
                "evidence_digest": evidence_digest,
            }
            self._commit_source_locked(source)
            return checkpoint

    def complete_source_checkpoint_invalidation(
        self,
        lease_id: str,
        *,
        source_state_id: str,
        checkpoint_digest: str,
        evidence_digest: str,
    ) -> dict[str, Any]:
        """Bind a completed source invalidation before containment may close."""
        _require_hex(checkpoint_digest, "invalidated checkpoint digest")
        _require_hex(evidence_digest, "checkpoint invalidation evidence digest")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            semantic = lease.get("semantic_disposition") if isinstance(lease, dict) else None
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "stopped-terminal"
                or not isinstance(semantic, dict)
                or semantic.get("disposition") != "needs-escalation"
                or semantic.get("source_state_id") != source_state_id
                or semantic.get("evidence_digest") != evidence_digest
            ):
                raise RecoveryStateError("checkpoint invalidation is not bound to the escalation lease")
            if semantic.get("checkpoint_invalidation") == "completed":
                if semantic.get("checkpoint_digest") != checkpoint_digest:
                    raise RecoveryStateError("completed checkpoint invalidation digest drifted")
                return state
            if semantic.get("checkpoint_invalidation") != "pending":
                raise RecoveryStateError("checkpoint invalidation is not pending")

            source = self._read_source_locked(source_state_id)
            checkpoint = source.get("public_checkpoint")
            invalidation = source.get("checkpoint_invalidation")
            if (
                not isinstance(checkpoint, dict)
                or checkpoint.get("disposition") != "recovery-ineligible"
                or checkpoint.get("checkpoint_digest") != checkpoint_digest
                or not isinstance(invalidation, dict)
                or invalidation.get("reason") != "semantic-needs-escalation"
                or invalidation.get("evidence_digest") != evidence_digest
            ):
                raise RecoveryStateError("source checkpoint invalidation is not durably complete")

            semantic["checkpoint_invalidation"] = "completed"
            semantic["checkpoint_digest"] = checkpoint_digest
            state["history"].append(
                {
                    "event": "source-checkpoint-invalidated",
                    "lease_id": lease_id,
                    "run_id": semantic.get("run_id"),
                    "source_state_id": source_state_id,
                    "checkpoint_digest": checkpoint_digest,
                    "evidence_digest": evidence_digest,
                }
            )
            return self._commit_registry_locked(state)

    def commit_handoff(self, lease_id: str, event: Mapping[str, Any], allowed_set_digest: str) -> dict[str, Any]:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or not isinstance(event.get("payload"), Mapping):
            raise RecoveryStateError("canonical handoff event is malformed")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") != "stopped-terminal":
                raise RecoveryStateError("handoff requires stopped terminal containment")
            if lease.get("allowed_set_digest") != allowed_set_digest or not lease.get("terminal_receipt", {}).get("success"):
                raise RecoveryStateError("handoff is not an accepted successful terminal result")
            payload = event["payload"]
            if (
                payload.get("lease_id") != lease_id
                or payload.get("allowed_set_digest") != allowed_set_digest
            ):
                raise RecoveryStateError("canonical handoff payload binding drifted")
            digest = _domain_digest(_DOMAIN_CHECKPOINT, {"event_id": event_id, "payload": event["payload"]})
            if state.get("outbox") is not None:
                raise RecoveryStateError("handoff outbox is already occupied")
            state["outbox"] = {"event_id": event_id, "payload": dict(event["payload"]), "digest": digest, "state": "pending"}
            lease["handoff_digest"] = digest
            lease["state"] = "handoff-committed"
            return self._commit_registry_locked(state)

    def materialize_handoff(self, lease_id: str, trace_path: Path | None = None) -> dict[str, Any]:
        """Idempotently materialize the authoritative outbox under registry+event locks."""
        target = (trace_path or (self.directory / "handoff-events.jsonl")).expanduser().resolve()
        event_lock = target.with_name(f"{target.name}.lock")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            outbox = state.get("outbox")
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "handoff-committed"
                or not isinstance(outbox, dict)
                or outbox.get("state") not in {"pending", "materialized"}
            ):
                raise RecoveryStateError("handoff outbox is not materializable")
            with _exclusive_file_lock(event_lock):
                events: list[dict[str, Any]] = []
                if target.is_file():
                    try:
                        for line in target.read_text(encoding="utf-8").splitlines():
                            value = json.loads(line)
                            if not isinstance(value, dict):
                                raise ValueError("event is not an object")
                            events.append(value)
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                        state["quarantine"] = "handoff-trace-unreadable"
                        self._commit_registry_locked(state)
                        raise RecoveryStateError("handoff trace is unreadable; registry is quarantined")
                matches = [event for event in events if event.get("event_id") == outbox.get("event_id")]
                canonical_event = {
                    "event_id": outbox["event_id"],
                    "payload": outbox["payload"],
                    "digest": outbox["digest"],
                }
                if len(matches) > 1 or (matches and matches[0] != canonical_event):
                    state["quarantine"] = "handoff-trace-mismatch"
                    self._commit_registry_locked(state)
                    raise RecoveryStateError("handoff trace mismatch; registry is quarantined")
                if not matches:
                    events.append(canonical_event)
                    payload = b"".join(_canonical(event) + b"\n" for event in events)
                    _durable_replace(target, payload)
                outbox["state"] = "materialized"
                return self._commit_registry_locked(state)

    def acknowledge_containment_loss_close(self, lease_id: str) -> dict[str, Any]:
        """Close a lost guardian only after its authenticated zero was abandoned."""
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            semantic = lease.get("semantic_disposition") if isinstance(lease, dict) else None
            run_id = _lease_run_id(lease) if isinstance(lease, Mapping) else None
            reconciled = [
                event
                for event in state["history"]
                if event.get("event") == "containment-loss-reconciled"
                and event.get("lease_id") == lease_id
                and event.get("run_id") == run_id
            ]
            if (
                not isinstance(lease, dict)
                or lease.get("lease_id") != lease_id
                or lease.get("state") != "stopped-terminal"
                or not isinstance(semantic, Mapping)
                or semantic.get("disposition") != "abandoned"
                or semantic.get("checkpoint_invalidation") != "completed"
                or len(reconciled) != 1
                or state.get("outbox") is not None
            ):
                raise RecoveryStateError(
                    "containment-loss close requires completed post-zero abandonment"
                )
            if lease.get("guardian_close") is not None:
                expected = {
                    "closed": True,
                    "guardian_id": lease.get("provider_receipt", {}).get("guardian_id"),
                    "closed_at": f"reconciled:{reconciled[0]['reconciled_at']}",
                }
                if lease["guardian_close"] != expected:
                    raise RecoveryStateError("containment-loss close acknowledgement drifted")
                return state
            lease["guardian_close"] = {
                "closed": True,
                "guardian_id": lease["provider_receipt"]["guardian_id"],
                "closed_at": f"reconciled:{reconciled[0]['reconciled_at']}",
            }
            return self._commit_registry_locked(state)

    def acknowledge_guardian_close(self, lease_id: str, acknowledgement: Mapping[str, Any]) -> dict[str, Any]:
        if acknowledgement.get("closed") is not True:
            raise RecoveryStateError("guardian close acknowledgement is required")
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") not in {"stopped-terminal", "handoff-committed"}:
                raise RecoveryStateError("guardian close is not terminal")
            semantic = lease.get("semantic_disposition")
            if (
                isinstance(semantic, dict)
                and semantic.get("disposition") in {"needs-escalation", "abandoned", "root-completed"}
                and semantic.get("checkpoint_invalidation") != "completed"
            ):
                raise RecoveryStateError("guardian close requires completed checkpoint invalidation")
            if lease.get("terminal_receipt", {}).get("success") and state.get("outbox", {}).get("state") != "materialized":
                raise RecoveryStateError("successful guardian close requires a materialized handoff")
            lease["guardian_close"] = dict(acknowledgement)
            if state.get("outbox") is not None:
                state["outbox"]["state"] = "archived"
            return self._commit_registry_locked(state)

    def release_contained_terminal(self, lease_id: str) -> dict[str, Any]:
        with self._lock():
            state = self._read_registry_locked(rebarrier=True)
            lease = state.get("lease")
            if not isinstance(lease, dict) or lease.get("lease_id") != lease_id or lease.get("state") not in {"stopped-terminal", "handoff-committed"}:
                raise RecoveryStateError("contained terminal release is not ready")
            semantic = lease.get("semantic_disposition")
            if (
                isinstance(semantic, dict)
                and semantic.get("disposition") in {"needs-escalation", "abandoned", "root-completed"}
                and semantic.get("checkpoint_invalidation") != "completed"
            ):
                raise RecoveryStateError("contained release requires completed checkpoint invalidation")
            if not lease.get("zero_proof") or not lease.get("guardian_close"):
                raise RecoveryStateError("zero proof and guardian close acknowledgement are required")
            if lease.get("terminal_receipt", {}).get("success") and (not isinstance(state.get("outbox"), dict) or state["outbox"].get("state") != "archived"):
                raise RecoveryStateError("successful terminal release requires archived handoff")
            terminal_receipt = lease["terminal_receipt"]
            zero_proof = lease["zero_proof"]
            guardian_close = lease["guardian_close"]
            provider_receipt = lease.get("provider_receipt")
            process_receipt = lease.get("process_receipt")
            if not isinstance(provider_receipt, dict) or not isinstance(process_receipt, dict):
                raise RecoveryStateError("contained terminal archive requires provider and process receipts")
            semantic_digest = (
                _terminal_part_digest("semantic", semantic)
                if isinstance(semantic, dict)
                else None
            )
            outbox = state.get("outbox")
            archive = {
                "event": "contained-terminal-released",
                "lease_id": lease_id,
                "lease_kind": lease.get("lease_kind"),
                "final_state": lease.get("state"),
                "allowed_set_digest": lease.get("allowed_set_digest"),
                "terminal_success": terminal_receipt.get("success") is True,
                "terminal_receipt_digest": _terminal_part_digest("terminal", terminal_receipt),
                "zero_proof_digest": _terminal_part_digest("zero", zero_proof),
                "guardian_close_digest": _terminal_part_digest("close", guardian_close),
                "provider_receipt_digest": _terminal_part_digest("provider", provider_receipt),
                "process_receipt_digest": _terminal_part_digest("process", process_receipt),
                "semantic_disposition": semantic.get("disposition") if isinstance(semantic, dict) else None,
                "semantic_disposition_digest": semantic_digest,
                "handoff_digest": lease.get("handoff_digest"),
                "outbox_digest": (
                    _terminal_part_digest("outbox", outbox)
                    if isinstance(outbox, dict)
                    else None
                ),
            }
            archive["archive_digest"] = _domain_digest(_DOMAIN_TERMINAL_ARCHIVE, archive)
            _validate_terminal_archive(archive)
            if lease.get("lease_kind") == "recovery-target":
                source_state_id = lease.get("source_state_id")
                grant_id = lease.get("grant_id")
                plan = lease.get("plan")
                if not isinstance(plan, Mapping):
                    raise RecoveryStateError(
                        "recovery terminal release lacks its target plan"
                    )
                prompt_snapshot_id = plan.get("prompt_snapshot_id")
                prompt_sha256 = plan.get("prompt_sha256")
                if isinstance(prompt_snapshot_id, str):
                    if (
                        not isinstance(source_state_id, str)
                        or not isinstance(grant_id, str)
                        or not isinstance(prompt_sha256, str)
                    ):
                        raise RecoveryStateError(
                            "recovery terminal release authorization binding is incomplete"
                        )
                    consumed = next(
                        (
                            item
                            for item in state["consumed_grants"]
                            if item.get("grant_id") == grant_id
                        ),
                        None,
                    )
                    if not isinstance(consumed, Mapping) or any(
                        consumed.get(field) != plan.get(field)
                        for field in ("prompt_snapshot_id", "prompt_sha256")
                    ):
                        raise RecoveryStateError(
                            "recovery terminal release consumed binding drifted"
                        )
                    source = self._read_source_locked(source_state_id)
                    authorization = source.get("authorization")
                    if authorization is not None and (
                        not isinstance(authorization, Mapping)
                        or authorization.get("grant_id") != grant_id
                        or any(
                            authorization.get(field) != plan.get(field)
                            for field in ("prompt_snapshot_id", "prompt_sha256")
                        )
                    ):
                        raise RecoveryStateError(
                            "recovery terminal release authorization binding drifted"
                        )
                    retirement = {
                        "event": "authorization-retired",
                        "source_state_id": source_state_id,
                        "grant_id": grant_id,
                        "prompt_snapshot_id": prompt_snapshot_id,
                        "prompt_sha256": prompt_sha256,
                    }
                    if authorization is not None:
                        source["authorization"] = None
                        self._commit_source_locked(source)
                    if retirement not in state["history"]:
                        state["history"].append(retirement)
            state["history"].append(archive)
            prompt_snapshot_id = (
                lease.get("plan", {}).get("prompt_snapshot_id")
                if lease.get("lease_kind") == "recovery-target"
                else lease.get("prompt_snapshot_id")
            )
            prompt_sha256 = (
                lease.get("plan", {}).get("prompt_sha256")
                if lease.get("lease_kind") == "recovery-target"
                else lease.get("prompt_sha256")
            )
            if isinstance(prompt_snapshot_id, str) and isinstance(prompt_sha256, str):
                tombstone = {
                    "event": "prompt-snapshot-released",
                    "prompt_snapshot_id": prompt_snapshot_id,
                    "prompt_sha256": prompt_sha256,
                }
                if tombstone not in state["tombstones"]:
                    state["tombstones"].append(tombstone)
            state["lease"] = None
            state["outbox"] = None
            return self._commit_registry_locked(state, rotate_epoch=True)
