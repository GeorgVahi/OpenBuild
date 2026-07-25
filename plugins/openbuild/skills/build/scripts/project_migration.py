"""Pre-repository coordinator and project migration owner.

This module owns the R-032 M7a boundary.  It deliberately does not discover a
repository, invoke Git while setting up the coordinator, dispatch a worker, or
edit a lane-local recovery registry.  The first explicit Build entry verifies
or initializes one fixed owner-private coordinator.  Project state becomes
reachable only after that succeeds and a caller supplies a canonical Git
common-directory identity.
"""

from __future__ import annotations

import argparse
import getpass
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
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Sequence

from project_state import (
    ProjectStateError as _PrimitiveError,
    _absolute_no_follow,
    _assert_no_link_or_reparse_ancestors,
    _canonical,
    _digest,
    _ensure_private_directory,
    _identity,
    _is_link_or_reparse,
    _locked,
    _publish_directory_no_replace,
    _read_json,
    _replace_json,
    _sync_parent_metadata,
    _validate_private_directory,
    _validate_private_regular,
    _windows_current_user_sid,
    _windows_move_write_through,
    _windows_object_sddl,
    _windows_security_apis,
    _write_exclusive_json,
)


SCHEMA_VERSION = 2
CURRENT_CLIENT_VERSION = "2.4.0"
BUILD_MODES = (
    "auto",
    "new",
    "refine",
    "run",
    "full",
    "configure-models",
    "setup-models",
)
DEFAULT_CODEX_HOME = Path.home() / ".codex"
COORDINATOR_ROOT_RELATIVE = Path("openbuild") / "coordinator-v1"
DEFAULT_COORDINATOR_ROOT = DEFAULT_CODEX_HOME / COORDINATOR_ROOT_RELATIVE
MAX_RECORD_BYTES = 256 * 1024
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_BINDING = re.compile(r"[A-Za-z0-9_.:/+-]{1,512}\Z")
_CHANNELS = ("C1", "C2", "C3", "C4", "C5")
_VERDICTS = frozenset({"clean", "breach", "indeterminate"})
_LEGACY_MAX = (2, 3, 6)


class ProjectMigrationError(RuntimeError):
    """The coordinator or project migration boundary rejected an operation."""


def _raise_migration(message: str, exc: BaseException | None = None) -> None:
    if exc is None:
        raise ProjectMigrationError(message)
    raise ProjectMigrationError(message) from exc


def _record(
    transition_id: str,
    family: str,
    *,
    transition_class: str | None = None,
    test_only: bool = False,
) -> dict[str, Any]:
    return {
        "id": transition_id,
        "family": family,
        "class": transition_class or transition_id.split(".", 1)[0],
        "test_only": test_only,
        "incident_safe": family in {"incident", "bootstrap-incident", "observation", "test"},
    }


def _expanded(prefix: str, middle: str, actions: Sequence[str], family: str) -> list[dict[str, Any]]:
    return [_record(f"{prefix}.{middle}.{action}", family) for action in actions]


# Literal, data-only, immutable transition registry.  Runtime receipt issuance,
# alias validation, package validation, and tests all consume this same table.
_TRANSITION_DATA: list[dict[str, Any]] = [
    _record("I0.coordinator-root.initialize", "setup"),
    _record("I0.coordinator-key.initialize", "setup"),
    _record("I0.bootstrap-capability.issue", "setup"),
    _record("I0.bootstrap-temp.gc", "setup"),
    _record("BA0.anchor.publish", "bootstrap"),
    _record("BA0.receipt.stage", "bootstrap"),
    _record("BA0.clean-intent", "bootstrap"),
    _record("BA0.incident-intent", "bootstrap"),
    _record("BA0.handoff.complete", "bootstrap"),
    _record("B0.project.initialize", "bootstrap"),
]
_TRANSITION_DATA += _expanded(
    "O1",
    "session",
    ("attach", "resume", "retire"),
    "ordinary",
)
_TRANSITION_DATA += [
    _record("O1.epoch.activate", "ordinary"),
    _record("O1.covenant.activate", "ordinary"),
    _record("O1.floor.promote", "ordinary"),
    _record("O1.floor.lower", "ordinary"),
    _record("O1.schema.promote", "ordinary"),
    _record("O1.registry.retire-downgrade", "ordinary"),
    _record("O1.downgrade.admit", "ordinary"),
    _record("O1.rollback.admit", "ordinary"),
]
_TRANSITION_DATA += _expanded(
    "O2",
    "lane",
    ("create", "register", "resume", "activate", "cancel", "terminal", "close", "transfer"),
    "ordinary",
)
_TRANSITION_DATA += _expanded(
    "O2", "worktree", ("create", "register", "move", "remove"), "ordinary"
)
_TRANSITION_DATA += _expanded(
    "O2", "task-ref", ("create", "move", "remove"), "ordinary"
)
_TRANSITION_DATA += _expanded(
    "O3", "milestone", ("ready", "activate", "complete"), "ordinary"
)
_TRANSITION_DATA += _expanded(
    "O3", "soft-intent", ("create", "update", "expire"), "ordinary"
)
_TRANSITION_DATA += _expanded(
    "O3", "scope", ("reserve", "grant", "expand", "release"), "ordinary"
)
_TRANSITION_DATA += _expanded(
    "O3", "protected", ("adoption-intent", "finalize", "rollback"), "ordinary"
)
_TRANSITION_DATA += [
    _record("O3.queue-ticket.grant", "ordinary"),
    _record("O3.capacity.grant", "ordinary"),
    _record("O3.capacity.release", "ordinary"),
    _record("O3.runtime-resource.grant", "ordinary"),
    _record("O3.runtime-resource.release", "ordinary"),
]
_O4_IDS = (
    "O4.lane-registry.initialize",
    "O4.process.dispatch",
    "O4.write-gate.open",
    "O4.retry.approve",
    "O4.escalation.approve",
    "O4.recovery-target.authorize",
    "O4.recovery-target.activate",
    "O4.prompt-snapshot.stage",
    "O4.lease.normal.reserve",
    "O4.lease.unactivated.release",
    "O4.source-snapshot.bind",
    "O4.checkpoint.prepare",
    "O4.checkpoint.finalize",
    "O4.checkpoint.capture",
    "O4.checkpoint.revalidate-persist",
    "O4.authorization.grant",
    "O4.authorization.retire",
    "O4.authorization.consume-reserve",
    "O4.recovery-launch.claim",
    "O4.recovery-launch.fail-preboundary",
    "O4.contained-launch.claim",
    "O4.process.bind-unactivated",
    "O4.process.activate",
    "O4.containment.fail-preboundary",
    "O4.quarantine.containment-loss",
    "O4.fallback.teardown-prove",
    "O4.fallback.claim",
    "O4.quarantine.fallback-launch",
    "O4.fallback-process.bind",
    "O4.legacy-process.bind",
    "O4.legacy-terminal.release",
    "O4.terminal.record",
    "O4.tree-zero.prove",
    "O4.post-commit-action.stage",
    "O4.post-commit-authorization.issue",
    "O4.post-commit-root-completion.finalize",
    "O4.post-commit-root-completion.complete",
    "O4.terminal-abandonment.record",
    "O4.containment-abandonment.record",
    "O4.terminal-abandonment.complete",
    "O4.semantic-handoff.reject",
    "O4.source-checkpoint.invalidate",
    "O4.source-checkpoint-invalidation.complete",
    "O4.handoff.commit",
    "O4.handoff.materialize",
    "O4.guardian.containment-loss-close",
    "O4.guardian.close",
    "O4.contained-terminal.release",
)
_TRANSITION_DATA += [_record(value, "ordinary") for value in _O4_IDS]
_TRANSITION_DATA += _expanded(
    "O5",
    "integration",
    ("intent", "enqueue", "dequeue", "apply", "conflict", "reject", "stale", "accept", "validate"),
    "ordinary",
)
_TRANSITION_DATA += [
    _record("O5.integration-ref.cas", "ordinary"),
    _record("O5.baseline.promote", "ordinary"),
    _record("O5.ownership.transfer", "ordinary"),
]
_TRANSITION_DATA += _expanded(
    "O6", "version-ticket", ("allocate", "consume", "supersede"), "ordinary"
)
_TRANSITION_DATA += [
    _record("O6.version-metadata.mutate", "ordinary"),
    _record("O6.package-metadata.mutate", "ordinary"),
]
for _commit_kind in ("task", "integration", "release"):
    _TRANSITION_DATA += _expanded(
        "O6", f"commit.{_commit_kind}", ("create", "finalize"), "ordinary"
    )
_TRANSITION_DATA += [
    _record("O6.stable-candidate.finalize", "ordinary"),
    _record("O6.success.declare", "ordinary"),
    _record("O7.git.push", "ordinary"),
    _record("O7.tag.create", "ordinary"),
    _record("O7.tag.push", "ordinary"),
]
_TRANSITION_DATA += _expanded(
    "O7", "github-release", ("create", "update", "publish"), "ordinary"
)
_TRANSITION_DATA += [
    _record("O7.public-version.audit", "ordinary"),
    _record("O7.remote-install.start", "ordinary"),
    _record("O7.remote-install.complete", "ordinary"),
    _record("O7.remote-smoke.start", "ordinary"),
    _record("O7.remote-smoke.complete", "ordinary"),
]
_O8_IDS = (
    "O8.worktree.cleanup",
    "O8.branch.delete",
    "O8.ref.delete",
    "O8.lane.retire",
    "O8.registry.retire",
    "O8.tombstone.gc",
    "O8.source.gc",
    "O8.checkpoint.gc",
    "O8.prompt-snapshot.release",
    "O8.prompt-snapshot.gc",
    "O8.bootstrap-record.gc",
    "O8.archive.gc",
    "O8.receipt.gc",
    "O8.evidence.delete",
    "O8.cleanup.success",
)
_TRANSITION_DATA += [_record(value, "ordinary") for value in _O8_IDS]
for _stage, _ids in {
    "S1": (
        "incident.materialize",
        "incident.fence",
        "registry-drift.materialize",
        "preservation.capture",
        "drain.start",
    ),
    "S2": (
        "process.safe-stop",
        "terminal.record",
        "tree-zero.prove",
        "quarantine.record",
    ),
    "S3": (
        "owner.reconcile",
        "semantic-disposition.record",
        "checkpoint.invalidate",
        "authorization.retire",
        "guardian.close",
        "terminal.archive",
        "E1.finalize",
        "E2.finalize",
        "E3.finalize",
        "E4.finalize",
    ),
    "S4": (
        "drain.complete",
        "floor.verify",
        "covenant-candidate.renew",
        "incident.clear",
    ),
}.items():
    _TRANSITION_DATA += [_record(f"{_stage}.{item}", "incident") for item in _ids]
for _stage, _ids in {
    "BS1": ("incident.materialize", "preservation.capture", "drain.start"),
    "BS2": (
        "process.safe-stop",
        "terminal.record",
        "tree-zero.prove",
        "quarantine.record",
    ),
    "BS3": (
        "owner.reconcile",
        "semantic-disposition.record",
        "checkpoint.invalidate",
        "authorization.retire",
        "guardian.close",
        "terminal.archive",
        "E1.finalize",
        "E2.finalize",
        "E3.finalize",
        "E4.finalize",
    ),
    "BS4": (
        "drain.complete",
        "clear-intent",
        "project-registry.visible",
        "complete",
    ),
}.items():
    _TRANSITION_DATA += [
        _record(f"{_stage}.{item}", "bootstrap-incident") for item in _ids
    ]
_TRANSITION_DATA += [
    _record("R.C1.git-topology.scan", "observation"),
    _record("R.C3.process.scan", "observation"),
    _record("R.C4.workspace-index-status.scan", "observation"),
    _record("R.C5.refs.scan", "observation"),
    _record("TST.registry.rotate-epoch", "test", test_only=True),
]

TRANSITION_REGISTRY = tuple(
    MappingProxyType(dict(entry)) for entry in _TRANSITION_DATA
)
TRANSITION_IDS = MappingProxyType(
    {str(entry["id"]): str(entry["id"]) for entry in TRANSITION_REGISTRY}
)

_ORDINARY_ALIASES: dict[str, tuple[str, ...]] = {
    "initialize": ("O4.lane-registry.initialize",),
    "retire_for_downgrade": ("O1.registry.retire-downgrade",),
    "mark_prompt_snapshot_released": ("O8.prompt-snapshot.release",),
    "reserve_normal": ("O4.lease.normal.reserve",),
    "release_unactivated_reservation": (
        "O4.lease.unactivated.release",
        "S3.E1.finalize",
        "BS3.E1.finalize",
    ),
    "bind_reserved_source_snapshot": ("O4.source-snapshot.bind",),
    "prepare_source_checkpoint": ("O4.checkpoint.prepare",),
    "finalize_prepared_checkpoint": ("O4.checkpoint.finalize",),
    "capture_checkpoint": ("O4.checkpoint.capture",),
    "revalidate_checkpoint": ("O4.checkpoint.revalidate-persist",),
    "grant_authorization": ("O4.authorization.grant",),
    "retire_authorization": (
        "O4.authorization.retire",
        "S3.authorization.retire",
        "BS3.authorization.retire",
    ),
    "consume_grant_and_reserve": ("O4.authorization.consume-reserve",),
    "claim_launch": ("O4.recovery-launch.claim",),
    "fail_recovery_target_before_boundary": (
        "O4.recovery-launch.fail-preboundary",
        "S3.owner.reconcile",
        "BS3.owner.reconcile",
    ),
    "claim_contained_launch": ("O4.contained-launch.claim",),
    "bind_process_unactivated": ("O4.process.bind-unactivated",),
    "commit_activation": ("O4.process.activate",),
    "containment_failed_before_boundary": (
        "O4.containment.fail-preboundary",
        "S3.owner.reconcile",
        "BS3.owner.reconcile",
    ),
    "quarantine_containment_loss": (
        "O4.quarantine.containment-loss",
        "S2.quarantine.record",
        "BS2.quarantine.record",
    ),
    "prove_fallback_teardown": (
        "O4.fallback.teardown-prove",
        "S3.owner.reconcile",
        "BS3.owner.reconcile",
    ),
    "claim_normal_fallback": ("O4.fallback.claim",),
    "quarantine_fallback_launch": (
        "O4.quarantine.fallback-launch",
        "S2.quarantine.record",
        "BS2.quarantine.record",
    ),
    "bind_fallback_process_unactivated": ("O4.fallback-process.bind",),
    "bind_legacy_process_unactivated": ("O4.legacy-process.bind",),
    "release_legacy_terminal": (
        "O4.legacy-terminal.release",
        "S3.E2.finalize",
        "BS3.E2.finalize",
    ),
    "record_terminal_evidence": (
        "O4.terminal.record",
        "S2.terminal.record",
        "BS2.terminal.record",
    ),
    "prove_contained_tree_empty": (
        "O4.tree-zero.prove",
        "S2.tree-zero.prove",
        "BS2.tree-zero.prove",
    ),
    "record_terminal_abandonment": (
        "O4.terminal-abandonment.record",
        "S3.semantic-disposition.record",
        "BS3.semantic-disposition.record",
    ),
    "record_containment_loss_abandonment": (
        "O4.containment-abandonment.record",
        "S3.owner.reconcile",
        "BS3.owner.reconcile",
    ),
    "complete_terminal_abandonment": (
        "O4.terminal-abandonment.complete",
        "S3.owner.reconcile",
        "BS3.owner.reconcile",
    ),
    "reject_semantic_handoff": (
        "O4.semantic-handoff.reject",
        "S3.semantic-disposition.record",
        "BS3.semantic-disposition.record",
    ),
    "invalidate_source_checkpoint": (
        "O4.source-checkpoint.invalidate",
        "S3.checkpoint.invalidate",
        "BS3.checkpoint.invalidate",
    ),
    "complete_source_checkpoint_invalidation": (
        "O4.source-checkpoint-invalidation.complete",
        "S3.checkpoint.invalidate",
        "BS3.checkpoint.invalidate",
    ),
    "commit_handoff": ("O4.handoff.commit",),
    "materialize_handoff": ("O4.handoff.materialize",),
    "acknowledge_containment_loss_close": (
        "O4.guardian.containment-loss-close",
        "S3.guardian.close",
        "BS3.guardian.close",
    ),
    "acknowledge_guardian_close": (
        "O4.guardian.close",
        "S3.guardian.close",
        "BS3.guardian.close",
    ),
    "release_contained_terminal": (
        "O4.contained-terminal.release",
        "S3.E3.finalize",
        "S3.E4.finalize",
        "BS3.E3.finalize",
        "BS3.E4.finalize",
    ),
}
TRANSITION_ALIASES = MappingProxyType(
    {key: tuple(value) for key, value in _ORDINARY_ALIASES.items()}
)


def validate_transition_registry(
    registry: Sequence[Mapping[str, Any]],
) -> list[str]:
    errors: list[str] = []
    ids = [entry.get("id") for entry in registry]
    if len(ids) != len(set(ids)) or not all(
        isinstance(value, str) and value for value in ids
    ):
        errors.append("transition IDs are malformed or non-unique")
    allowed_families = {
        "setup",
        "bootstrap",
        "ordinary",
        "incident",
        "bootstrap-incident",
        "observation",
        "test",
    }
    for entry in registry:
        identifier = entry.get("id")
        family = entry.get("family")
        if family not in allowed_families:
            errors.append("transition family is unknown")
        if not isinstance(identifier, str):
            continue
        expected_prefixes = {
            "setup": ("I0.",),
            "bootstrap": ("BA0.", "B0."),
            "ordinary": tuple(f"O{number}." for number in range(1, 9)),
            "incident": ("S1.", "S2.", "S3.", "S4."),
            "bootstrap-incident": ("BS1.", "BS2.", "BS3.", "BS4."),
            "observation": ("R.",),
            "test": ("TST.",),
        }
        if family in expected_prefixes and not identifier.startswith(
            expected_prefixes[family]
        ):
            errors.append("transition class does not match its family")
        if entry.get("test_only") is not (family == "test"):
            errors.append("test-only transition classification is invalid")
        if entry.get("incident_safe") is not (
            family
            in {"incident", "bootstrap-incident", "observation", "test"}
        ):
            errors.append("incident-safe transition classification is invalid")
    registered = set(ids)
    for method, aliases in TRANSITION_ALIASES.items():
        if not aliases or set(aliases) - registered:
            errors.append(f"transition alias {method} is incomplete")
        if method in {"commit_handoff", "materialize_handoff"} and any(
            value.startswith("BS") for value in aliases
        ):
            errors.append("bootstrap incident handoff alias is forbidden")
    required = {
        "I0.coordinator-root.initialize",
        "I0.coordinator-key.initialize",
        "I0.bootstrap-capability.issue",
        "I0.bootstrap-temp.gc",
        "BA0.anchor.publish",
        "B0.project.initialize",
        "BS4.project-registry.visible",
        "R.C1.git-topology.scan",
        "TST.registry.rotate-epoch",
    }
    if required - registered:
        errors.append("required stable transitions are missing")
    return sorted(set(errors))


if _transition_errors := validate_transition_registry(TRANSITION_REGISTRY):
    raise RuntimeError(
        "invalid R-032 transition registry: " + "; ".join(_transition_errors)
    )


def _binding(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _BINDING.fullmatch(value):
        raise ProjectMigrationError(f"{label} binding is invalid")
    return value


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise ProjectMigrationError(f"{label} is invalid")
    return value


def _account_identity() -> str:
    uid = str(os.geteuid()) if hasattr(os, "geteuid") else "windows"
    return hashlib.sha256(
        f"{uid}:{getpass.getuser()}".encode("utf-8", "strict")
    ).hexdigest()


def _version(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ProjectMigrationError("registry version is invalid")
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value)
    if match is None:
        raise ProjectMigrationError("registry version is invalid")
    return tuple(int(match.group(index)) for index in range(1, 4))  # type: ignore[return-value]


def _stable_plain_json(path: Path) -> dict[str, Any]:
    _assert_no_link_or_reparse_ancestors(path)
    try:
        before = path.lstat()
    except OSError as exc:
        _raise_migration("registry is unreadable", exc)
    if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise ProjectMigrationError("registry is not a no-follow regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _raise_migration("registry is unreadable", exc)
    try:
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(before) or opened.st_size > MAX_RECORD_BYTES:
            raise ProjectMigrationError("registry identity or size changed")
        raw = b""
        while len(raw) <= MAX_RECORD_BYTES:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            raw += chunk
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        _raise_migration("registry disappeared while reading", exc)
    if (
        len(raw) > MAX_RECORD_BYTES
        or _identity(before) != _identity(after_open)
        or _identity(after_open) != _identity(after)
    ):
        raise ProjectMigrationError("registry identity or size changed")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _raise_migration("registry is malformed", exc)
    if not isinstance(decoded, dict):
        raise ProjectMigrationError("registry is malformed")
    return decoded


if os.name == "nt":
    # A Codex workspace process uses a Windows restricted token.  A DACL that
    # grants only TOKEN_USER is inaccessible to that same process because a
    # restricted-token access check must also be allowed by its restricting
    # SID set.  These primitives therefore grant exactly SYSTEM, TOKEN_USER,
    # and the current token's restricting SIDs; no broad Users/AuthUsers ACE is
    # inherited.
    def _windows_restricted_sids() -> tuple[str, ...]:
        import ctypes

        class SidAndAttributes(ctypes.Structure):
            _fields_ = [
                ("sid", ctypes.c_void_p),
                ("attributes", ctypes.c_uint32),
            ]

        class TokenGroupsOne(ctypes.Structure):
            _fields_ = [
                ("count", ctypes.c_uint32),
                ("groups", SidAndAttributes * 1),
            ]

        kernel32, advapi32 = _windows_security_apis()
        token = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            raise ProjectMigrationError(
                f"cannot open the current Windows token: {ctypes.WinError()}"
            )
        try:
            required = ctypes.c_uint32()
            advapi32.GetTokenInformation(
                token, 11, None, 0, ctypes.byref(required)
            )
            if not required.value:
                return ()
            buffer = ctypes.create_string_buffer(required.value)
            if not advapi32.GetTokenInformation(
                token,
                11,
                buffer,
                required.value,
                ctypes.byref(required),
            ):
                raise ProjectMigrationError(
                    f"cannot read restricted Windows token SIDs: {ctypes.WinError()}"
                )
            header = ctypes.cast(
                buffer, ctypes.POINTER(TokenGroupsOne)
            ).contents
            result: list[str] = []
            base = (
                ctypes.addressof(buffer)
                + TokenGroupsOne.groups.offset
            )
            for index in range(header.count):
                entry = SidAndAttributes.from_address(
                    base + index * ctypes.sizeof(SidAndAttributes)
                )
                value = ctypes.c_wchar_p()
                if not advapi32.ConvertSidToStringSidW(
                    entry.sid, ctypes.byref(value)
                ):
                    raise ProjectMigrationError(
                        f"cannot serialize restricted Windows SID: {ctypes.WinError()}"
                    )
                try:
                    if value.value:
                        result.append(value.value)
                finally:
                    kernel32.LocalFree(
                        ctypes.cast(value, ctypes.c_void_p)
                    )
            return tuple(sorted(set(result)))
        finally:
            kernel32.CloseHandle(token)


    def _windows_private_sddl(*, directory: bool) -> str:
        inheritance = "OICI" if directory else ""
        trustees = (
            "SY",
            _windows_current_user_sid(),
            *_windows_restricted_sids(),
        )
        return "D:P" + "".join(
            f"(A;{inheritance};FA;;;{trustee})"
            for trustee in trustees
        )


    def _windows_private_object(path: Path, *, directory: bool) -> bool:
        sddl = _windows_object_sddl(path)
        user = _windows_current_user_sid()
        if f"O:{user}" not in sddl or (
            directory and "D:P" not in sddl
        ):
            return False
        import re as _re

        actual = set(
            _re.findall(r"\([^)]*\)", sddl.split("D:", 1)[1])
        )
        inheritance = "OICI" if directory else ""
        expected = {
            f"(A;{inheritance};FA;;;SY)",
            f"(A;{inheritance};FA;;;{user})",
            *{
                f"(A;{inheritance};FA;;;{'WD' if sid == 'S-1-1-0' else sid})"
                for sid in _windows_restricted_sids()
            },
        }
        return actual == expected


    def _validate_private_directory(
        path: Path, *, protect: bool
    ) -> os.stat_result:
        del protect
        _assert_no_link_or_reparse_ancestors(path)
        try:
            metadata = path.lstat()
        except OSError as exc:
            _raise_migration(
                "private coordinator directory is unreadable", exc
            )
        if _is_link_or_reparse(metadata) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            raise ProjectMigrationError(
                "private coordinator directory is not a regular directory"
            )
        if not _windows_private_object(path, directory=True):
            raise ProjectMigrationError(
                "Windows private directory DACL is not token-private"
            )
        return metadata


    def _validate_private_regular(
        path: Path, *, protect: bool
    ) -> os.stat_result:
        del protect
        _assert_no_link_or_reparse_ancestors(path)
        try:
            metadata = path.lstat()
        except OSError as exc:
            _raise_migration(
                "private coordinator object is unreadable", exc
            )
        if _is_link_or_reparse(metadata) or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise ProjectMigrationError(
                "private coordinator object is not a regular no-follow file"
            )
        if not _windows_private_object(path, directory=False):
            raise ProjectMigrationError(
                "Windows private file DACL is not token-private"
            )
        return metadata


    def _create_windows_private_directory(path: Path) -> None:
        import ctypes

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_uint32),
                ("security_descriptor", ctypes.c_void_p),
                ("inherit_handle", ctypes.c_int),
            ]

        kernel32, advapi32 = _windows_security_apis()
        descriptor = ctypes.c_void_p()
        sddl = _windows_private_sddl(directory=True)
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ProjectMigrationError(
                f"cannot build private Windows directory DACL: {ctypes.WinError()}"
            )
        attributes = SecurityAttributes(
            ctypes.sizeof(SecurityAttributes), descriptor, False
        )
        try:
            if not kernel32.CreateDirectoryW(
                str(path), ctypes.byref(attributes)
            ):
                error = ctypes.get_last_error()
                if error not in {80, 183}:
                    raise ProjectMigrationError(
                        f"cannot create private Windows directory: {ctypes.WinError(error)}"
                    )
        finally:
            kernel32.LocalFree(descriptor)


    def _ensure_private_directory(path: Path) -> None:
        _assert_no_link_or_reparse_ancestors(path)
        missing: list[Path] = []
        current = path
        while not current.exists():
            missing.append(current)
            if current.parent == current:
                raise ProjectMigrationError(
                    "private coordinator directory has no existing parent"
                )
            current = current.parent
        for directory in reversed(missing):
            _create_windows_private_directory(directory)
            _validate_private_directory(directory, protect=False)
        _validate_private_directory(path, protect=False)


    def _read_json(path: Path) -> dict[str, Any]:
        before = _validate_private_regular(path, protect=False)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened):
                raise ProjectMigrationError(
                    "private coordinator object identity changed"
                )
            raw = b""
            while len(raw) <= MAX_RECORD_BYTES:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                raw += chunk
            after_open = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
        if (
            len(raw) > MAX_RECORD_BYTES
            or _identity(before) != _identity(after_open)
            or _identity(after_open) != _identity(after)
        ):
            raise ProjectMigrationError(
                "private coordinator object identity changed"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _raise_migration(
                "private coordinator object is malformed", exc
            )
        if not isinstance(value, dict) or value.get("digest") != _digest(
            value
        ):
            raise ProjectMigrationError(
                "private coordinator record digest is invalid"
            )
        return value


    def _write_exclusive_json(
        path: Path, value: Mapping[str, Any]
    ) -> None:
        _ensure_private_directory(path.parent)
        payload = dict(value)
        payload["digest"] = _digest(payload)
        encoded = _canonical(payload) + b"\n"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags, 0o600)
        try:
            offset = 0
            while offset < len(encoded):
                offset += os.write(descriptor, encoded[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _validate_private_regular(path, protect=False)


    def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
        _ensure_private_directory(path.parent)
        temp = path.with_name(
            f".{path.name}.{secrets.token_hex(16)}.tmp"
        )
        _write_exclusive_json(temp, value)
        try:
            _windows_move_write_through(temp, path, replace=True)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        _validate_private_regular(path, protect=False)


    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        _ensure_private_directory(path.parent)
        if not path.exists():
            try:
                _write_exclusive_json(
                    path,
                    {
                        "schema": 1,
                        "kind": "coordinator-lock",
                        "lock_id": secrets.token_hex(32),
                    },
                )
            except FileExistsError:
                pass
        before = _validate_private_regular(path, protect=False)
        descriptor = os.open(
            path,
            os.O_RDWR
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened):
                raise ProjectMigrationError(
                    "private lock identity changed before acquisition"
                )
            import msvcrt

            lock_offset = MAX_RECORD_BYTES + 1
            os.lseek(descriptor, lock_offset, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            try:
                current = path.lstat()
                if _identity(opened) != _identity(current):
                    raise ProjectMigrationError(
                        "private lock identity changed during acquisition"
                    )
                yield
                final = path.lstat()
                if _identity(opened) != _identity(final):
                    raise ProjectMigrationError(
                        "private lock identity changed while held"
                    )
            finally:
                os.lseek(descriptor, lock_offset, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)


def _write_record(path: Path, value: Mapping[str, Any], *, no_replace: bool = False) -> None:
    try:
        if no_replace:
            _write_exclusive_json(path, value)
        elif path.exists():
            _replace_json(path, value)
        else:
            _write_exclusive_json(path, value)
    except (_PrimitiveError, OSError) as exc:
        _raise_migration("durable migration record write failed", exc)


def _read_record(path: Path, label: str) -> dict[str, Any]:
    try:
        return _read_json(path)
    except (_PrimitiveError, OSError) as exc:
        _raise_migration(f"{label} is missing or tampered", exc)


class ObservationContext:
    """One bounded read observer with no durable or process-control authority."""

    __slots__ = ("transition_id", "argv", "cwd")

    def __init__(
        self, transition_id: str, argv: tuple[str, ...], cwd: Path | None
    ) -> None:
        self.transition_id = transition_id
        self.argv = argv
        self.cwd = cwd

    def observe(self) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            list(self.argv),
            cwd=self.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            },
        )


class TransitionContext:
    """One-use ordered mutation context bound to an immutable receipt."""

    def __init__(
        self,
        coordinator: "ProjectMigrationCoordinator",
        token: str,
        path: Path,
        receipt: Mapping[str, Any],
        *,
        resumed: bool,
    ) -> None:
        self._coordinator = coordinator
        self._token = token
        self._path = path
        self._receipt_id = str(receipt["receipt_id"])
        self.anchor_id = str(receipt["anchor_id"])
        self.transition_id = str(receipt["transition_id"])
        self._executing_sink: str | None = None
        self._resumed = resumed

    def _reload(self) -> dict[str, Any]:
        receipt = self._coordinator._transition_receipt(
            self._token, expected_path=self._path
        )
        if receipt["receipt_id"] != self._receipt_id:
            raise ProjectMigrationError("transition receipt identity changed")
        return receipt

    def run_sink(
        self,
        sink: str,
        action: Callable[[], Any],
        *,
        visible: Callable[[], bool] | None = None,
    ) -> Any:
        _binding(sink, "ordered sink")
        with self._coordinator._anchor_lock(self.anchor_id):
            receipt = self._reload()
            plan = receipt["sink_plan"]
            cursor = int(receipt["cursor"])
            if receipt["status"] not in {"issued", "active"}:
                raise ProjectMigrationError("transition receipt was already used")
            if cursor >= len(plan) or plan[cursor] != sink:
                raise ProjectMigrationError("ordered sink was skipped or reordered")
            inflight = receipt.get("inflight")
            if inflight is not None and inflight != sink:
                raise ProjectMigrationError("transition receipt inflight sink changed")
            if inflight == sink and visible is not None and visible():
                receipt["inflight"] = None
                receipt["cursor"] = cursor + 1
                receipt["status"] = "active"
                _write_record(self._path, receipt)
                return {"status": "replayed-visible", "sink": sink}
            if receipt["status"] == "issued":
                receipt["status"] = "active"
                intent = {
                    "schema": SCHEMA_VERSION,
                    "kind": "transition-intent",
                    "receipt_id": receipt["receipt_id"],
                    "transition_id": receipt["transition_id"],
                    "project_id": receipt["project_id"],
                    "anchor_id": receipt["anchor_id"],
                    "epoch": receipt["epoch"],
                    "generation": receipt["generation"],
                    "attempt_id": receipt["attempt_id"],
                    "sink_plan_digest": receipt["sink_plan_digest"],
                    "cursor": cursor,
                }
                intent_path = (
                    self._coordinator.anchor_path(self.anchor_id)
                    / "records"
                    / "transition-intents"
                    / f"{self._receipt_id}.json"
                )
                try:
                    _write_record(intent_path, intent, no_replace=True)
                except ProjectMigrationError:
                    existing = _read_record(intent_path, "transition intent")
                    if {
                        key: value for key, value in existing.items() if key != "digest"
                    } != intent:
                        raise
            receipt["inflight"] = sink
            _write_record(self._path, receipt)
        self._executing_sink = sink
        try:
            result = action()
        finally:
            self._executing_sink = None
        with self._coordinator._anchor_lock(self.anchor_id):
            receipt = self._reload()
            if (
                receipt["status"] != "active"
                or receipt.get("inflight") != sink
                or int(receipt["cursor"]) != cursor
            ):
                raise ProjectMigrationError("transition cursor changed during sink")
            receipt["inflight"] = None
            receipt["cursor"] = cursor + 1
            _write_record(self._path, receipt)
        return result

    def complete(self) -> dict[str, Any]:
        with self._coordinator._anchor_lock(self.anchor_id):
            receipt = self._reload()
            if receipt.get("inflight") is not None:
                raise ProjectMigrationError("transition has an incomplete sink")
            if int(receipt["cursor"]) != len(receipt["sink_plan"]):
                raise ProjectMigrationError("transition sink plan is incomplete")
            if receipt["status"] == "complete":
                return receipt
            if receipt["status"] != "active":
                raise ProjectMigrationError("transition receipt was not consumed")
            receipt["status"] = "complete"
            receipt["completed_ns"] = time.time_ns()
            _write_record(self._path, receipt)
            return receipt


class ProjectMigrationCoordinator:
    """Permanent coordinator plus per-common-directory migration anchors."""

    def __init__(
        self,
        *,
        coordinator_root: Path | None = None,
        codex_home: Path | None = None,
        fault: str | None = None,
    ) -> None:
        if coordinator_root is not None and codex_home is not None:
            raise ProjectMigrationError(
                "coordinator root and Codex home are mutually exclusive"
            )
        base = Path(
            codex_home
            or os.environ.get("CODEX_HOME")
            or DEFAULT_CODEX_HOME
        )
        self.root = _absolute_no_follow(
            coordinator_root or (base / COORDINATOR_ROOT_RELATIVE)
        )
        self.lock_path = self.root / "coordinator.lock"
        self.key_path = self.root / "coordinator.key"
        self.identity_path = self.root / "identity.json"
        self.fault = fault

    def _fault(self, point: str) -> None:
        if self.fault == point:
            raise ProjectMigrationError(f"injected fault at {point}")

    def _setup_components(self) -> dict[str, Any]:
        try:
            root_metadata = _validate_private_directory(
                self.root, protect=False
            )
            lock_metadata = _validate_private_regular(
                self.lock_path, protect=False
            )
            lock = _read_json(self.lock_path)
            key = _read_json(self.key_path)
            identity = _read_json(self.identity_path)
        except (_PrimitiveError, OSError) as exc:
            _raise_migration("coordinator setup is missing or tampered", exc)
        if (
            lock.get("schema") != 1
            or lock.get("kind") != "coordinator-lock"
            or not isinstance(lock.get("lock_id"), str)
        ):
            raise ProjectMigrationError("coordinator identity lock is tampered")
        if (
            key.get("schema") != SCHEMA_VERSION
            or key.get("kind") != "coordinator-key"
            or not _HEX_64.fullmatch(str(key.get("key", "")))
        ):
            raise ProjectMigrationError("coordinator key is tampered")
        key_bytes = bytes.fromhex(str(key["key"]))
        key_id = hashlib.sha256(key_bytes).hexdigest()
        if key.get("key_id") != key_id:
            raise ProjectMigrationError("coordinator key is tampered")
        expected_identity = {
            "schema": SCHEMA_VERSION,
            "kind": "coordinator-identity",
            "root_device": int(root_metadata.st_dev),
            "root_inode": int(root_metadata.st_ino),
            "lock_device": int(lock_metadata.st_dev),
            "lock_inode": int(lock_metadata.st_ino),
            "lock_id": lock["lock_id"],
            "key_id": key_id,
            "account_id": _account_identity(),
        }
        if {
            name: value
            for name, value in identity.items()
            if name != "digest"
        } != expected_identity:
            raise ProjectMigrationError(
                "coordinator root, lock, key, or account identity changed"
            )
        return {
            "root": root_metadata,
            "lock": lock,
            "key": key,
            "identity": identity,
            "key_bytes": key_bytes,
            "key_id": key_id,
        }

    def _initialize_setup(self, mode: str) -> dict[str, Any]:
        try:
            _ensure_private_directory(self.root)
            with _locked(self.lock_path):
                if self.identity_path.exists():
                    setup = self._setup_components()
                    return {
                        "status": "setup-verified",
                        "requested_mode": mode,
                        "continue": True,
                        "key_id": setup["key_id"],
                        "setup_receipt": hashlib.sha256(
                            _canonical(
                                {
                                    "kind": "setup-verification",
                                    "requested_mode": mode,
                                    "key_id": setup["key_id"],
                                }
                            )
                        ).hexdigest(),
                    }
                allowed = {
                    "coordinator.lock",
                    "coordinator.key",
                }
                actual = {item.name for item in self.root.iterdir()}
                if actual - allowed:
                    raise ProjectMigrationError(
                        "partial coordinator setup contains unknown objects"
                    )
                if self.key_path.exists():
                    key = _read_record(self.key_path, "coordinator key")
                else:
                    key_hex = secrets.token_hex(32)
                    key = {
                        "schema": SCHEMA_VERSION,
                        "kind": "coordinator-key",
                        "key": key_hex,
                        "key_id": hashlib.sha256(
                            bytes.fromhex(key_hex)
                        ).hexdigest(),
                    }
                    _write_record(self.key_path, key, no_replace=True)
                self._fault("after-key-publish")
                root_metadata = _validate_private_directory(
                    self.root, protect=False
                )
                lock_metadata = _validate_private_regular(
                    self.lock_path, protect=False
                )
                lock = _read_record(
                    self.lock_path, "coordinator identity lock"
                )
                identity = {
                    "schema": SCHEMA_VERSION,
                    "kind": "coordinator-identity",
                    "root_device": int(root_metadata.st_dev),
                    "root_inode": int(root_metadata.st_ino),
                    "lock_device": int(lock_metadata.st_dev),
                    "lock_inode": int(lock_metadata.st_ino),
                    "lock_id": lock["lock_id"],
                    "key_id": key["key_id"],
                    "account_id": _account_identity(),
                }
                _write_record(self.identity_path, identity, no_replace=True)
                self._fault("after-identity-publish")
                receipt_id = secrets.token_hex(32)
                receipt_path = (
                    self.root / "setup-receipts" / f"{receipt_id}.json"
                )
                receipt = {
                    "schema": SCHEMA_VERSION,
                    "kind": "first-use-setup-receipt",
                    "receipt_id": receipt_id,
                    "transition_id": "I0.coordinator-root.initialize",
                    "key_transition_id": "I0.coordinator-key.initialize",
                    "key_id": key["key_id"],
                    "requested_mode": mode,
                    "continue": True,
                }
                _write_record(receipt_path, receipt, no_replace=True)
                return {
                    "status": "setup-initialized",
                    "requested_mode": mode,
                    "continue": True,
                    "key_id": key["key_id"],
                    "setup_receipt": receipt_id,
                }
        except ProjectMigrationError:
            raise
        except (_PrimitiveError, OSError, KeyError, ValueError) as exc:
            _raise_migration("coordinator setup failed closed", exc)

    def pre_repository_setup(self, requested_mode: str) -> dict[str, Any]:
        """Verify or initialize I0 without reading a project or invoking Git."""
        if requested_mode not in BUILD_MODES:
            raise ProjectMigrationError("requested Build mode is invalid")
        try:
            setup = self._setup_components()
        except ProjectMigrationError as exc:
            if self.identity_path.exists():
                return {
                    "status": "setup-required",
                    "requested_mode": requested_mode,
                    "continue": False,
                    "reason": str(exc),
                }
            try:
                return self._initialize_setup(requested_mode)
            except ProjectMigrationError as initialize_error:
                return {
                    "status": "setup-required",
                    "requested_mode": requested_mode,
                    "continue": False,
                    "reason": str(initialize_error),
                }
        verification = {
            "kind": "setup-verification",
            "requested_mode": requested_mode,
            "key_id": setup["key_id"],
            "continue": True,
        }
        return {
            "status": "setup-verified",
            "requested_mode": requested_mode,
            "continue": True,
            "key_id": setup["key_id"],
            "setup_receipt": hashlib.sha256(
                _canonical(verification)
            ).hexdigest(),
        }

    def coordinate_build_entry(
        self,
        requested_mode: str,
        continue_requested_mode: Callable[[str], Any],
    ) -> dict[str, Any]:
        result = self.pre_repository_setup(requested_mode)
        if result["status"] == "setup-required":
            return result
        continuation = continue_requested_mode(requested_mode)
        return {**result, "continuation": continuation}

    def _setup_or_raise(self) -> dict[str, Any]:
        return self._setup_components()

    def project_identity(self, common_directory: Path) -> dict[str, Any]:
        self._setup_or_raise()
        path = _absolute_no_follow(common_directory)
        try:
            _assert_no_link_or_reparse_ancestors(path)
            metadata = path.lstat()
        except (_PrimitiveError, OSError) as exc:
            _raise_migration(
                "project common-directory identity is unreadable", exc
            )
        if _is_link_or_reparse(metadata):
            raise ProjectMigrationError(
                "project common-directory path contains a link or reparse point"
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise ProjectMigrationError(
                "project common-directory is not a real directory"
            )
        identity = {
            "schema": "project-common-directory-v1",
            "canonical_path": os.path.normcase(str(path)),
            "device": int(metadata.st_dev),
            "inode": int(metadata.st_ino),
            "account_id": _account_identity(),
        }
        identity["identity_digest"] = hashlib.sha256(
            _canonical(identity)
        ).hexdigest()
        return identity

    def _validate_project_identity(
        self, identity: Mapping[str, Any]
    ) -> dict[str, Any]:
        required = {
            "schema",
            "canonical_path",
            "device",
            "inode",
            "account_id",
            "identity_digest",
        }
        if set(identity) != required:
            raise ProjectMigrationError(
                "project common-directory identity is invalid"
            )
        value = dict(identity)
        digest = value.pop("identity_digest")
        if (
            value.get("schema") != "project-common-directory-v1"
            or value.get("account_id") != _account_identity()
            or digest != hashlib.sha256(_canonical(value)).hexdigest()
        ):
            raise ProjectMigrationError(
                "project common-directory identity is invalid"
            )
        current = self.project_identity(Path(str(value["canonical_path"])))
        if current != dict(identity):
            raise ProjectMigrationError(
                "project common-directory identity changed"
            )
        return dict(identity)

    def _anchor_slot(
        self,
        setup: Mapping[str, Any],
        identity: Mapping[str, Any],
    ) -> str:
        key = setup["key_bytes"]
        assert isinstance(key, bytes)
        return hmac.new(
            key,
            _canonical(
                {
                    "identity_digest": identity["identity_digest"],
                    "account_id": identity["account_id"],
                }
            ),
            hashlib.sha256,
        ).hexdigest()

    @property
    def _capabilities_directory(self) -> Path:
        return self.root / "capabilities"

    @property
    def _capability_index_directory(self) -> Path:
        return self.root / "capability-index"

    @property
    def _anchors_directory(self) -> Path:
        return self.root / "anchors"

    def _capability_index(
        self, project_id: str, plan_id: str, attempt_id: str
    ) -> Path:
        digest = hashlib.sha256(
            _canonical(
                {
                    "project_id": project_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                }
            )
        ).hexdigest()
        return self._capability_index_directory / f"{digest}.json"

    def _capability_path(self, capability_id: str) -> Path:
        _hex(capability_id, "bootstrap capability ID")
        return self._capabilities_directory / f"{capability_id}.json"

    def issue_bootstrap_capability(
        self,
        project_identity: Mapping[str, Any],
        plan_id: str,
        attempt_id: str,
        *,
        expected_absence: bool = True,
    ) -> dict[str, Any]:
        if expected_absence is not True:
            raise ProjectMigrationError(
                "bootstrap capability requires expected absence"
            )
        identity = self._validate_project_identity(project_identity)
        plan_id = _binding(plan_id, "plan")
        attempt_id = _binding(attempt_id, "attempt")
        setup = self._setup_or_raise()
        project_id = str(identity["identity_digest"])
        anchor_id = self._anchor_slot(setup, identity)
        sink_plan = (
            "BA0.temp.create",
            "BA0.anchor.publish",
            "BA0.winner.verify",
            "BA0.capability.cursor",
        )
        sink_plan_digest = hashlib.sha256(
            _canonical(
                {
                    "project_id": project_id,
                    "anchor_id": anchor_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "expected_anchor": "absent",
                    "expected_project_registry": "absent",
                    "expected_bs": "absent",
                    "sink_plan": sink_plan,
                }
            )
        ).hexdigest()
        try:
            with _locked(self.lock_path):
                index_path = self._capability_index(
                    project_id, plan_id, attempt_id
                )
                if index_path.exists():
                    index = _read_record(
                        index_path, "bootstrap capability index"
                    )
                    record = _read_record(
                        self._capability_path(str(index["capability_id"])),
                        "bootstrap capability",
                    )
                    if record.get("cursor") != "issued":
                        raise ProjectMigrationError(
                            "bootstrap capability was already consumed"
                        )
                    return {
                        "status": "issued",
                        "bootstrap_capability": (
                            f"{record['capability_id']}.{record['token']}"
                        ),
                        "anchor_id": anchor_id,
                        "sink_plan_digest": sink_plan_digest,
                    }
                capability_id = secrets.token_hex(32)
                token = secrets.token_hex(32)
                record = {
                    "schema": SCHEMA_VERSION,
                    "kind": "bootstrap-capability",
                    "transition_id": "I0.bootstrap-capability.issue",
                    "capability_id": capability_id,
                    "token": token,
                    "token_digest": hashlib.sha256(
                        token.encode("ascii")
                    ).hexdigest(),
                    "project_id": project_id,
                    "project_identity": identity,
                    "anchor_id": anchor_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "expected_absence": True,
                    "key_id": setup["key_id"],
                    "sink_plan": list(sink_plan),
                    "sink_plan_digest": sink_plan_digest,
                    "cursor": "issued",
                    "created_ns": time.time_ns(),
                    "anchor_manifest": None,
                }
                _write_record(
                    self._capability_path(capability_id),
                    record,
                    no_replace=True,
                )
                _write_record(
                    index_path,
                    {
                        "schema": SCHEMA_VERSION,
                        "kind": "bootstrap-capability-index",
                        "project_id": project_id,
                        "plan_id": plan_id,
                        "attempt_id": attempt_id,
                        "capability_id": capability_id,
                    },
                    no_replace=True,
                )
                return {
                    "status": "issued",
                    "bootstrap_capability": f"{capability_id}.{token}",
                    "anchor_id": anchor_id,
                    "sink_plan_digest": sink_plan_digest,
                }
        except (_PrimitiveError, OSError) as exc:
            _raise_migration("bootstrap capability issue failed", exc)

    def _parse_capability(self, capability: str) -> tuple[str, str]:
        if not isinstance(capability, str) or capability.count(".") != 1:
            raise ProjectMigrationError("bootstrap capability is malformed")
        capability_id, token = capability.split(".", 1)
        return _hex(capability_id, "bootstrap capability ID"), _hex(
            token, "bootstrap capability token"
        )

    def _capability(
        self,
        capability: str,
        identity: Mapping[str, Any],
        plan_id: str,
        attempt_id: str,
    ) -> tuple[Path, dict[str, Any]]:
        capability_id, token = self._parse_capability(capability)
        path = self._capability_path(capability_id)
        record = _read_record(path, "bootstrap capability")
        project = self._validate_project_identity(identity)
        if (
            record.get("schema") != SCHEMA_VERSION
            or record.get("kind") != "bootstrap-capability"
            or record.get("capability_id") != capability_id
            or record.get("project_id") != project["identity_digest"]
            or record.get("project_identity") != project
            or record.get("plan_id") != plan_id
            or record.get("attempt_id") != attempt_id
            or record.get("expected_absence") is not True
            or record.get("token") != token
            or not hmac.compare_digest(
                str(record.get("token_digest")),
                hashlib.sha256(token.encode("ascii")).hexdigest(),
            )
        ):
            raise ProjectMigrationError(
                "bootstrap capability is not bound to this project, plan, and attempt"
            )
        setup = self._setup_or_raise()
        if (
            record.get("key_id") != setup["key_id"]
            or record.get("anchor_id") != self._anchor_slot(setup, project)
        ):
            raise ProjectMigrationError(
                "bootstrap capability anchor binding changed"
            )
        return path, record

    def anchor_path(self, anchor_id: str) -> Path:
        return self._anchors_directory / _hex(anchor_id, "anchor ID")

    def _anchor_manifest_for(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        chosen = record.get("anchor_manifest")
        if isinstance(chosen, Mapping):
            return dict(chosen)
        return {
            "schema": SCHEMA_VERSION,
            "kind": "BA0-anchor",
            "project_id": record["project_id"],
            "project_identity_digest": record["project_id"],
            "anchor_id": record["anchor_id"],
            "key_id": record["key_id"],
            "epoch": 0,
            "lock_id": secrets.token_hex(32),
            "winning_plan_id": record["plan_id"],
            "winning_attempt_id": record["attempt_id"],
        }

    def _build_anchor_temp(
        self, record: Mapping[str, Any]
    ) -> tuple[Path, dict[str, Any]]:
        _ensure_private_directory(self._anchors_directory)
        manifest = self._anchor_manifest_for(record)
        temp = self._anchors_directory / (
            f".ba0-{record['capability_id']}-{secrets.token_hex(8)}"
        )
        _ensure_private_directory(temp)
        _write_record(temp / "manifest.json", manifest, no_replace=True)
        _write_record(
            temp / "anchor.lock",
            {
                "schema": SCHEMA_VERSION,
                "kind": "BA0-lock",
                "anchor_id": manifest["anchor_id"],
                "lock_id": manifest["lock_id"],
                "manifest_digest": _digest(manifest),
            },
            no_replace=True,
        )
        _ensure_private_directory(temp / "records")
        _sync_parent_metadata(temp)
        return temp, manifest

    def _validate_anchor(
        self, anchor_id: str, project_id: str | None = None
    ) -> dict[str, Any]:
        path = self.anchor_path(anchor_id)
        try:
            directory = _validate_private_directory(path, protect=False)
            manifest = _read_json(path / "manifest.json")
            lock_before = _validate_private_regular(
                path / "anchor.lock", protect=False
            )
            lock = _read_json(path / "anchor.lock")
            lock_after = (path / "anchor.lock").lstat()
        except (_PrimitiveError, OSError) as exc:
            _raise_migration("anchor is missing or tampered", exc)
        required_manifest = {
            "schema",
            "kind",
            "project_id",
            "project_identity_digest",
            "anchor_id",
            "key_id",
            "epoch",
            "lock_id",
            "winning_plan_id",
            "winning_attempt_id",
            "digest",
        }
        if (
            set(manifest) != required_manifest
            or manifest.get("schema") != SCHEMA_VERSION
            or manifest.get("kind") != "BA0-anchor"
            or manifest.get("anchor_id") != anchor_id
            or manifest.get("project_identity_digest")
            != manifest.get("project_id")
            or (project_id is not None and manifest.get("project_id") != project_id)
        ):
            raise ProjectMigrationError("anchor manifest is invalid")
        required_lock = {
            "schema",
            "kind",
            "anchor_id",
            "lock_id",
            "manifest_digest",
            "digest",
        }
        if (
            set(lock) != required_lock
            or lock.get("schema") != SCHEMA_VERSION
            or lock.get("kind") != "BA0-lock"
            or lock.get("anchor_id") != anchor_id
            or lock.get("lock_id") != manifest.get("lock_id")
            or lock.get("manifest_digest") != _digest(manifest)
            or _identity(lock_before) != _identity(lock_after)
        ):
            raise ProjectMigrationError("anchor lock identity changed")
        return {
            "anchor_id": anchor_id,
            "project_id": manifest["project_id"],
            "lock_id": manifest["lock_id"],
            "epoch": manifest["epoch"],
            "manifest_digest": _digest(manifest),
            "directory_identity": _identity(directory),
            "lock_identity": _identity(lock_before),
        }

    def _matching_temp(
        self, record: Mapping[str, Any]
    ) -> Path | None:
        if not self._anchors_directory.exists():
            return None
        prefix = f".ba0-{record['capability_id']}-"
        matches = [
            item
            for item in self._anchors_directory.iterdir()
            if item.name.startswith(prefix)
        ]
        if len(matches) > 1:
            raise ProjectMigrationError(
                "bootstrap capability has ambiguous temporary anchors"
            )
        return matches[0] if matches else None

    def _publish_capability_locked(
        self, path: Path, record: dict[str, Any]
    ) -> dict[str, Any]:
        anchor_id = str(record["anchor_id"])
        target = self.anchor_path(anchor_id)
        if target.exists():
            result = self._validate_anchor(anchor_id, str(record["project_id"]))
            record["anchor_manifest"] = {
                key: value
                for key, value in _read_record(
                    target / "manifest.json", "anchor manifest"
                ).items()
                if key != "digest"
            }
        else:
            temp = self._matching_temp(record)
            if temp is None:
                temp, manifest = self._build_anchor_temp(record)
                record["anchor_manifest"] = manifest
                _write_record(path, record)
            self._fault("after-anchor-temp")
            try:
                _publish_directory_no_replace(temp, target)
            except FileExistsError:
                pass
            except (_PrimitiveError, OSError) as exc:
                _raise_migration("atomic anchor publication failed", exc)
            self._fault("after-anchor-publish")
            result = self._validate_anchor(anchor_id, str(record["project_id"]))
        record["cursor"] = "published"
        record["published_lock_id"] = result["lock_id"]
        _write_record(path, record)
        return {"status": "anchor-ready", **result}

    def consume_bootstrap_capability(
        self,
        capability: str,
        project_identity: Mapping[str, Any],
        plan_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        plan_id = _binding(plan_id, "plan")
        attempt_id = _binding(attempt_id, "attempt")
        try:
            with _locked(self.lock_path):
                path, record = self._capability(
                    capability, project_identity, plan_id, attempt_id
                )
                if record.get("cursor") != "issued":
                    raise ProjectMigrationError(
                        "bootstrap capability was already consumed"
                    )
                record["cursor"] = "consumed"
                record["consumed_ns"] = time.time_ns()
                _write_record(path, record)
                self._fault("after-capability-consume")
                return self._publish_capability_locked(path, record)
        except (_PrimitiveError, OSError) as exc:
            _raise_migration("bootstrap capability consume failed", exc)

    def resume_bootstrap_capability(
        self,
        capability: str,
        project_identity: Mapping[str, Any],
        plan_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        plan_id = _binding(plan_id, "plan")
        attempt_id = _binding(attempt_id, "attempt")
        try:
            with _locked(self.lock_path):
                path, record = self._capability(
                    capability, project_identity, plan_id, attempt_id
                )
                if record.get("cursor") == "issued":
                    raise ProjectMigrationError(
                        "bootstrap capability has not been consumed"
                    )
                if record.get("cursor") == "abandoned":
                    raise ProjectMigrationError(
                        "bootstrap capability was abandoned"
                    )
                if record.get("cursor") == "published":
                    return {
                        "status": "anchor-ready",
                        **self._validate_anchor(
                            str(record["anchor_id"]),
                            str(record["project_id"]),
                        ),
                    }
                return self._publish_capability_locked(path, record)
        except (_PrimitiveError, OSError) as exc:
            _raise_migration("bootstrap capability resume failed", exc)

    def create_bootstrap_temp_for_test(
        self,
        capability: str,
        project_identity: Mapping[str, Any],
        plan_id: str,
        attempt_id: str,
    ) -> Path:
        with _locked(self.lock_path):
            path, record = self._capability(
                capability, project_identity, plan_id, attempt_id
            )
            if record["cursor"] != "issued":
                raise ProjectMigrationError(
                    "bootstrap capability was already consumed"
                )
            temp, manifest = self._build_anchor_temp(record)
            record["anchor_manifest"] = manifest
            _write_record(path, record)
            return temp

    def abandon_bootstrap_capability(
        self,
        capability: str,
        project_identity: Mapping[str, Any],
        plan_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        with _locked(self.lock_path):
            path, record = self._capability(
                capability, project_identity, plan_id, attempt_id
            )
            if record["cursor"] == "published":
                raise ProjectMigrationError(
                    "published bootstrap capability cannot be abandoned"
                )
            if record["cursor"] != "abandoned":
                record["cursor"] = "abandoned"
                record["abandoned_ns"] = time.time_ns()
                _write_record(path, record)
            return record

    def issue_retention_proof(self, before_ns: int) -> dict[str, Any]:
        if not isinstance(before_ns, int) or before_ns < 0:
            raise ProjectMigrationError("retention boundary is invalid")
        setup = self._setup_or_raise()
        payload = {
            "kind": "bootstrap-temp-retention",
            "before_ns": before_ns,
            "key_id": setup["key_id"],
        }
        key = setup["key_bytes"]
        assert isinstance(key, bytes)
        return {
            **payload,
            "mac": hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest(),
        }

    def gc_bootstrap_temps(
        self, retention_proof: Mapping[str, Any]
    ) -> dict[str, Any]:
        setup = self._setup_or_raise()
        required = {"kind", "before_ns", "key_id", "mac"}
        if set(retention_proof) != required:
            raise ProjectMigrationError("retention proof is invalid")
        payload = {
            key: retention_proof[key]
            for key in ("kind", "before_ns", "key_id")
        }
        key_bytes = setup["key_bytes"]
        assert isinstance(key_bytes, bytes)
        expected = hmac.new(
            key_bytes, _canonical(payload), hashlib.sha256
        ).hexdigest()
        if (
            payload["kind"] != "bootstrap-temp-retention"
            or payload["key_id"] != setup["key_id"]
            or not isinstance(payload["before_ns"], int)
            or not hmac.compare_digest(str(retention_proof["mac"]), expected)
        ):
            raise ProjectMigrationError("retention proof is invalid")
        removed: list[str] = []
        with _locked(self.lock_path):
            if not self._anchors_directory.exists():
                return {"status": "complete", "removed": removed}
            for temp in self._anchors_directory.iterdir():
                match = re.fullmatch(r"\.ba0-([0-9a-f]{64})-[0-9a-f]{16}", temp.name)
                if match is None:
                    continue
                try:
                    metadata = temp.lstat()
                    capability = _read_record(
                        self._capability_path(match.group(1)),
                        "bootstrap capability",
                    )
                except (OSError, ProjectMigrationError):
                    continue
                if (
                    _is_link_or_reparse(metadata)
                    or not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_mtime_ns > int(payload["before_ns"])
                    or capability.get("cursor") not in {"abandoned", "published"}
                ):
                    continue
                allowed = {"manifest.json", "anchor.lock", "records"}
                if {item.name for item in temp.iterdir()} - allowed:
                    continue
                records = temp / "records"
                if records.exists() and any(records.iterdir()):
                    continue
                for item in (temp / "manifest.json", temp / "anchor.lock"):
                    item.unlink()
                if records.exists():
                    records.rmdir()
                temp.rmdir()
                removed.append(str(temp))
            _sync_parent_metadata(self._anchors_directory)
        return {"status": "complete", "removed": removed}

    @contextmanager
    def _anchor_lock(self, anchor_id: str) -> Iterator[None]:
        anchor = self._validate_anchor(anchor_id)
        lock_path = self.anchor_path(anchor_id) / "anchor.lock"
        before = lock_path.lstat()
        with _locked(lock_path):
            current = lock_path.lstat()
            if _identity(before) != _identity(current):
                raise ProjectMigrationError(
                    "anchor lock identity changed during acquisition"
                )
            yield
            final = self._validate_anchor(anchor_id)
            if final["lock_identity"] != anchor["lock_identity"]:
                raise ProjectMigrationError(
                    "anchor lock identity changed while held"
                )

    def _records(self, anchor_id: str) -> Path:
        return self.anchor_path(anchor_id) / "records"

    def registry_path(self, anchor_id: str) -> Path:
        return self._records(anchor_id) / "project-registry.json"

    def bs_path(self, anchor_id: str) -> Path:
        return self._records(anchor_id) / "bootstrap-incident.json"

    def _evidence(
        self, requested_verdict: str, evidence: Mapping[str, Any]
    ) -> dict[str, str]:
        if set(evidence) != set(_CHANNELS) or not all(
            evidence.get(channel) in _VERDICTS for channel in _CHANNELS
        ):
            raise ProjectMigrationError(
                "bootstrap evidence must contain exact C1-C5 verdicts"
            )
        observed = [str(evidence[channel]) for channel in _CHANNELS]
        verdict = (
            "breach"
            if "breach" in observed
            else "indeterminate"
            if "indeterminate" in observed
            else "clean"
        )
        if requested_verdict != verdict:
            raise ProjectMigrationError(
                "bootstrap verdict does not match C1-C5 evidence"
            )
        return {channel: str(evidence[channel]) for channel in _CHANNELS}

    def _protected_work(
        self, protected_work: Sequence[Mapping[str, Any]] | None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in protected_work or ():
            if set(item) != {"actor_id", "state", "source", "scopes"}:
                raise ProjectMigrationError("protected work entry is invalid")
            actor_id = _binding(item["actor_id"], "protected actor")
            state = item["state"]
            source = item["source"]
            scopes = item["scopes"]
            if (
                state not in {"active", "vacant"}
                or source not in {"legacy", "external"}
                or not isinstance(scopes, list)
                or not scopes
                or not all(
                    isinstance(scope, str) and 0 < len(scope) <= 1024
                    for scope in scopes
                )
            ):
                raise ProjectMigrationError("protected work entry is invalid")
            result.append(
                {
                    "actor_id": actor_id,
                    "state": state,
                    "source": source,
                    "scopes": list(scopes),
                }
            )
        if len({item["actor_id"] for item in result}) != len(result):
            raise ProjectMigrationError("protected actor identities are not unique")
        return result

    def _registry_candidate(
        self,
        anchor: Mapping[str, Any],
        *,
        protected_work: Sequence[Mapping[str, Any]],
        incident_history: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        return {
            "schema": "openbuild-project-registry-v2",
            "reader_floor": CURRENT_CLIENT_VERSION,
            "writer_floor": CURRENT_CLIENT_VERSION,
            "client_version": CURRENT_CLIENT_VERSION,
            "generation": 0,
            "epoch": anchor["epoch"],
            "state": "active",
            "fence": None,
            "project_id": anchor["project_id"],
            "anchor_id": anchor["anchor_id"],
            "anchor_lock_id": anchor["lock_id"],
            "anchor_manifest_digest": anchor["manifest_digest"],
            "session": {
                "state": "active",
                "generation": 0,
                "epoch": anchor["epoch"],
            },
            "protected_work": [dict(item) for item in protected_work],
            "active_work": [],
            "incident_history": [dict(item) for item in incident_history],
            "previous_generation_digest": None,
        }

    def _validate_registry(
        self,
        value: Mapping[str, Any],
        anchor: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "schema",
            "reader_floor",
            "writer_floor",
            "client_version",
            "generation",
            "epoch",
            "state",
            "fence",
            "project_id",
            "anchor_id",
            "anchor_lock_id",
            "anchor_manifest_digest",
            "session",
            "protected_work",
            "active_work",
            "incident_history",
            "previous_generation_digest",
            "digest",
        }
        if set(value) != required:
            raise ProjectMigrationError("project registry schema is invalid")
        state = dict(value)
        if (
            state["schema"] != "openbuild-project-registry-v2"
            or not isinstance(state["generation"], int)
            or state["generation"] < 0
            or state["state"] not in {"active", "fenced", "retired"}
            or state["project_id"] != anchor["project_id"]
            or state["anchor_id"] != anchor["anchor_id"]
            or state["anchor_lock_id"] != anchor["lock_id"]
            or state["anchor_manifest_digest"]
            != anchor["manifest_digest"]
            or state["epoch"] != anchor["epoch"]
            or not isinstance(state["protected_work"], list)
            or not isinstance(state["active_work"], list)
            or not isinstance(state["incident_history"], list)
        ):
            raise ProjectMigrationError("project registry schema is invalid")
        self._assert_compatible(state)
        protected = self._protected_work(state["protected_work"])
        state["protected_work"] = protected
        if state["state"] == "fenced" and not isinstance(state["fence"], dict):
            raise ProjectMigrationError("fenced project registry has no fence")
        if state["state"] != "fenced" and state["fence"] is not None:
            raise ProjectMigrationError("project registry fence is invalid")
        return state

    def _assert_compatible(self, state: Mapping[str, Any]) -> None:
        reader = _version(state.get("reader_floor"))
        writer = _version(state.get("writer_floor"))
        client = _version(CURRENT_CLIENT_VERSION)
        if not (
            reader == client
            or (reader[0] == 2 and reader <= _LEGACY_MAX)
        ):
            raise ProjectMigrationError(
                "project registry reader floor is unknown"
            )
        if writer > client:
            raise ProjectMigrationError(
                "current client is below the project registry writer floor"
            )
        _version(state.get("client_version"))

    def read_registry(self, anchor_id: str) -> dict[str, Any]:
        anchor = self._validate_anchor(anchor_id)
        state = _read_record(
            self.registry_path(anchor_id), "project registry"
        )
        return self._validate_registry(state, anchor)

    def bootstrap_project(
        self,
        anchor_id: str,
        verdict: str,
        *,
        attempt_id: str,
        evidence: Mapping[str, Any],
        protected_work: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if verdict not in _VERDICTS:
            raise ProjectMigrationError("bootstrap verdict is invalid")
        attempt_id = _binding(attempt_id, "attempt")
        evidence_value = self._evidence(verdict, evidence)
        protected = self._protected_work(protected_work)
        with self._anchor_lock(anchor_id):
            anchor = self._validate_anchor(anchor_id)
            records = self._records(anchor_id)
            receipt = {
                "schema": SCHEMA_VERSION,
                "kind": "BA0-bootstrap-receipt",
                "transition_id": "BA0.receipt.stage",
                "binding_class": "bootstrap",
                "project_id": anchor["project_id"],
                "anchor_id": anchor_id,
                "anchor_lock_id": anchor["lock_id"],
                "anchor_manifest_digest": anchor["manifest_digest"],
                "epoch": anchor["epoch"],
                "attempt_id": attempt_id,
                "expected_project_registry": "absent",
                "expected_bs": "absent",
                "evidence": evidence_value,
                "verdict": verdict,
            }
            receipt["receipt_id"] = hashlib.sha256(
                _canonical(receipt)
            ).hexdigest()
            receipt_path = records / "bootstrap-receipt.json"

            def replay_record(path: Path, expected: Mapping[str, Any], label: str) -> bool:
                """Accept only the exact immutable BA0 artifact for this call."""
                if not path.exists():
                    return False
                actual = _read_record(path, label)
                actual.pop("digest", None)
                if actual != dict(expected):
                    raise ProjectMigrationError(f"{label} does not match bootstrap replay")
                return True

            if not replay_record(receipt_path, receipt, "bootstrap receipt"):
                _write_record(receipt_path, receipt, no_replace=True)
            self._fault("after-record-write")
            handoff_base = {
                "schema": SCHEMA_VERSION,
                "project_id": anchor["project_id"],
                "anchor_id": anchor_id,
                "epoch": anchor["epoch"],
                "attempt_id": attempt_id,
                "receipt_id": receipt["receipt_id"],
            }
            if verdict == "clean":
                intent = {
                    **handoff_base,
                    "kind": "BA0-clean-intent",
                    "transition_id": "BA0.clean-intent",
                    "registry_generation": 0,
                }
                candidate = self._registry_candidate(
                    anchor, protected_work=protected
                )
                handoff = {
                    **handoff_base,
                    "kind": "BA0-handoff",
                    "transition_id": "BA0.handoff.complete",
                    "outcome": "clean",
                    "registry_digest": _digest(candidate),
                }
                if (records / "incident-intent.json").exists() or self.bs_path(anchor_id).exists():
                    raise ProjectMigrationError("bootstrap clean replay has mixed incident state")
                if not replay_record(records / "clean-intent.json", intent, "bootstrap clean intent"):
                    _write_record(records / "clean-intent.json", intent, no_replace=True)
                self._fault("after-clean-intent")
                if self.registry_path(anchor_id).exists():
                    visible = self.read_registry(anchor_id)
                    visible.pop("digest", None)
                    if visible != candidate:
                        raise ProjectMigrationError("visible bootstrap registry does not match replay")
                else:
                    _write_record(self.registry_path(anchor_id), candidate, no_replace=True)
                self._fault("after-registry-visibility")
                if not replay_record(records / "handoff.json", handoff, "bootstrap handoff"):
                    _write_record(records / "handoff.json", handoff, no_replace=True)
                self._fault("after-handoff")
                return self.read_registry(anchor_id)
            incident_id = hashlib.sha256(
                f"BA0-incident:{receipt['receipt_id']}".encode("ascii")
            ).hexdigest()
            intent = {
                **handoff_base,
                "kind": "BA0-incident-intent",
                "transition_id": "BA0.incident-intent",
                "incident_id": incident_id,
            }
            incident = {
                "schema": SCHEMA_VERSION,
                "kind": "bootstrap-incident",
                "transition_id": "BS1.incident.materialize",
                "project_id": anchor["project_id"],
                "anchor_id": anchor_id,
                "anchor_lock_id": anchor["lock_id"],
                "anchor_manifest_digest": anchor["manifest_digest"],
                "epoch": anchor["epoch"],
                "attempt_id": attempt_id,
                "incident_id": incident_id,
                "generation": 0,
                "state": "incident-active",
                "verdict": verdict,
                "evidence": evidence_value,
                "protected_work": protected,
                "target_registries": [],
                "target_results": [],
                "preservation": {
                    "transition_id": "BS1.preservation.capture",
                    "authority_usable": False,
                    "protected_work_digest": hashlib.sha256(
                        _canonical(protected)
                    ).hexdigest(),
                },
                "clear_candidate_digest": None,
            }
            handoff = {
                **handoff_base,
                "kind": "BA0-handoff",
                "transition_id": "BA0.handoff.complete",
                "outcome": "incident",
                "incident_id": incident_id,
            }
            if (records / "clean-intent.json").exists() or self.registry_path(anchor_id).exists():
                raise ProjectMigrationError("bootstrap incident replay has mixed clean state")
            if not replay_record(records / "incident-intent.json", intent, "bootstrap incident intent"):
                _write_record(records / "incident-intent.json", intent, no_replace=True)
            self._fault("after-incident-intent")
            if self.bs_path(anchor_id).exists():
                visible = self.read_bootstrap_incident(anchor_id)
                visible.pop("digest", None)
                if visible != incident:
                    raise ProjectMigrationError("visible bootstrap incident does not match replay")
            else:
                _write_record(self.bs_path(anchor_id), incident, no_replace=True)
            self._fault("after-incident-visibility")
            if not replay_record(records / "handoff.json", handoff, "bootstrap handoff"):
                _write_record(records / "handoff.json", handoff, no_replace=True)
            self._fault("after-handoff")
            return self.read_bootstrap_incident(anchor_id)

    def read_bootstrap_incident(self, anchor_id: str) -> dict[str, Any]:
        anchor = self._validate_anchor(anchor_id)
        incident = _read_record(
            self.bs_path(anchor_id), "bootstrap incident"
        )
        required = {
            "schema",
            "kind",
            "transition_id",
            "project_id",
            "anchor_id",
            "anchor_lock_id",
            "anchor_manifest_digest",
            "epoch",
            "attempt_id",
            "incident_id",
            "generation",
            "state",
            "verdict",
            "evidence",
            "protected_work",
            "target_registries",
            "target_results",
            "preservation",
            "clear_candidate_digest",
            "digest",
        }
        if (
            set(incident) != required
            or incident.get("schema") != SCHEMA_VERSION
            or incident.get("kind") != "bootstrap-incident"
            or incident.get("anchor_id") != anchor_id
            or incident.get("project_id") != anchor["project_id"]
            or incident.get("anchor_lock_id") != anchor["lock_id"]
            or incident.get("anchor_manifest_digest")
            != anchor["manifest_digest"]
            or incident.get("epoch") != anchor["epoch"]
            or incident.get("state")
            not in {"incident-active", "drain-complete", "complete"}
            or not isinstance(incident.get("generation"), int)
        ):
            raise ProjectMigrationError("bootstrap incident schema is invalid")
        incident["protected_work"] = self._protected_work(
            incident["protected_work"]
        )
        return incident

    def drain_bootstrap_incident(
        self, anchor_id: str, *, expected_generation: int
    ) -> dict[str, Any]:
        with self._anchor_lock(anchor_id):
            incident = self.read_bootstrap_incident(anchor_id)
            if incident["state"] == "drain-complete":
                return incident
            if incident["state"] == "complete":
                return incident
            if incident["generation"] != expected_generation:
                raise ProjectMigrationError(
                    "bootstrap incident generation changed"
                )
            if any(
                item.get("state") != "vacant"
                for item in incident["protected_work"]
            ) or any(
                result.get("state") != "vacant"
                for result in incident["target_results"]
            ):
                raise ProjectMigrationError(
                    "bootstrap incident targets are not proven vacant"
                )
            incident["generation"] += 1
            incident["state"] = "drain-complete"
            incident["transition_id"] = "BS4.drain.complete"
            _write_record(self.bs_path(anchor_id), incident)
            self._fault("after-drain")
            return self.read_bootstrap_incident(anchor_id)

    def clear_bootstrap_incident(
        self, anchor_id: str, *, expected_generation: int
    ) -> dict[str, Any]:
        with self._anchor_lock(anchor_id):
            anchor = self._validate_anchor(anchor_id)
            incident = self.read_bootstrap_incident(anchor_id)
            if incident["state"] == "complete":
                return self.read_registry(anchor_id)
            if (
                incident["state"] != "drain-complete"
                or incident["generation"] != expected_generation
            ):
                raise ProjectMigrationError(
                    "bootstrap incident is not clearable at this generation"
                )
            history = [
                {
                    "incident_id": incident["incident_id"],
                    "incident_generation": incident["generation"],
                    "verdict": incident["verdict"],
                    "preservation_digest": incident["preservation"][
                        "protected_work_digest"
                    ],
                }
            ]
            candidate = self._registry_candidate(
                anchor,
                protected_work=incident["protected_work"],
                incident_history=history,
            )
            candidate_digest = _digest(candidate)
            intent_path = self._records(anchor_id) / "clear-intent.json"
            intent = {
                "schema": SCHEMA_VERSION,
                "kind": "BS4-clear-intent",
                "transition_id": "BS4.clear-intent",
                "project_id": anchor["project_id"],
                "anchor_id": anchor_id,
                "incident_id": incident["incident_id"],
                "incident_generation": incident["generation"],
                "candidate_digest": candidate_digest,
            }
            if intent_path.exists():
                existing_intent = _read_record(
                    intent_path, "bootstrap clear intent"
                )
                if {
                    key: value
                    for key, value in existing_intent.items()
                    if key != "digest"
                } != intent:
                    raise ProjectMigrationError(
                        "bootstrap clear intent changed"
                    )
            else:
                _write_record(intent_path, intent, no_replace=True)
            registry_path = self.registry_path(anchor_id)
            if registry_path.exists():
                visible = self.read_registry(anchor_id)
                if _digest(visible) != candidate_digest:
                    # _digest ignores the stored digest and works on the
                    # validated projection returned by read_registry.
                    raise ProjectMigrationError(
                        "visible clear registry does not match clear intent"
                    )
            else:
                _write_record(registry_path, candidate, no_replace=True)
            self._fault("after-registry-visibility")
            incident["state"] = "complete"
            incident["generation"] += 1
            incident["transition_id"] = "BS4.complete"
            incident["clear_candidate_digest"] = candidate_digest
            _write_record(self.bs_path(anchor_id), incident)
            self._fault("after-clear-complete")
            return self.read_registry(anchor_id)

    def load_legacy_registry(self, path: Path) -> dict[str, Any]:
        value = _stable_plain_json(_absolute_no_follow(path))
        floor = value.get("reader_floor")
        parsed = _version(floor)
        if parsed[0] != 2 or parsed > _LEGACY_MAX:
            raise ProjectMigrationError(
                "legacy registry reader floor is unknown"
            )
        required = {
            "schema_version",
            "reader_floor",
            "generation",
            "epoch",
            "lease",
            "outbox",
            "protected_work",
        }
        if not required <= set(value):
            raise ProjectMigrationError("legacy registry shape is invalid")
        if (
            not isinstance(value["generation"], int)
            or not isinstance(value["epoch"], int)
            or not isinstance(value["protected_work"], list)
        ):
            raise ProjectMigrationError("legacy registry shape is invalid")
        return value

    def update_registry(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "state",
            "fence",
            "protected_work",
            "active_work",
            "incident_history",
            "reader_floor",
            "writer_floor",
        }
        if set(changes) - allowed:
            raise ProjectMigrationError("project registry update is invalid")
        with self._anchor_lock(anchor_id):
            state = self.read_registry(anchor_id)
            if state["generation"] != expected_generation:
                raise ProjectMigrationError(
                    "project registry generation changed"
                )
            candidate = {
                key: value for key, value in state.items() if key != "digest"
            }
            candidate.update(
                {
                    key: (
                        self._protected_work(value)
                        if key == "protected_work"
                        else value
                    )
                    for key, value in changes.items()
                }
            )
            if (
                "reader_floor" in changes
                and _version(changes["reader_floor"])
                < _version(state["reader_floor"])
            ) or (
                "writer_floor" in changes
                and _version(changes["writer_floor"])
                < _version(state["writer_floor"])
            ):
                raise ProjectMigrationError(
                    "registry floor downgrade is forbidden"
                )
            self._assert_compatible(candidate)
            if (
                candidate["state"] == "fenced"
                and not isinstance(candidate["fence"], dict)
            ) or (
                candidate["state"] != "fenced"
                and candidate["fence"] is not None
            ):
                raise ProjectMigrationError("project registry fence is invalid")
            path = self.registry_path(anchor_id)
            current_floor = _version(CURRENT_CLIENT_VERSION)
            if (
                _version(state["reader_floor"]) < current_floor
                or _version(state["writer_floor"]) < current_floor
                or state["client_version"] != CURRENT_CLIENT_VERSION
            ):
                promoted = {
                    key: value
                    for key, value in state.items()
                    if key != "digest"
                }
                promoted["generation"] += 1
                promoted["previous_generation_digest"] = _digest(state)
                promoted["reader_floor"] = CURRENT_CLIENT_VERSION
                promoted["writer_floor"] = CURRENT_CLIENT_VERSION
                promoted["client_version"] = CURRENT_CLIENT_VERSION
                _write_record(path, promoted)
                self._fault("after-floor-promotion")
                state = self.read_registry(anchor_id)
                candidate["reader_floor"] = CURRENT_CLIENT_VERSION
                candidate["writer_floor"] = CURRENT_CLIENT_VERSION
                candidate["client_version"] = CURRENT_CLIENT_VERSION
            candidate["generation"] = int(state["generation"]) + 1
            candidate["previous_generation_digest"] = _digest(state)
            _write_record(path, candidate)
            return self.read_registry(anchor_id)

    def _replace_registry_for_test(
        self, anchor_id: str, value: Mapping[str, Any]
    ) -> None:
        with self._anchor_lock(anchor_id):
            payload = {
                key: item for key, item in value.items() if key != "digest"
            }
            _write_record(self.registry_path(anchor_id), payload)

    # Kept as a compatibility test hook for the focused fixture.  It is not
    # reachable from the CLI and is intentionally absent from __all__.
    replace_registry_for_test = _replace_registry_for_test

    def retire_registry(
        self, anchor_id: str, *, expected_generation: int
    ) -> dict[str, Any]:
        with self._anchor_lock(anchor_id):
            state = self.read_registry(anchor_id)
            if state["state"] == "retired":
                return state
            if state["generation"] != expected_generation:
                raise ProjectMigrationError(
                    "project registry generation changed"
                )
            if (
                state["fence"] is not None
                or state["active_work"]
                or any(
                    item["state"] == "active"
                    for item in state["protected_work"]
                )
            ):
                raise ProjectMigrationError(
                    "project registry is not proven vacant"
                )
            candidate = {
                key: value for key, value in state.items() if key != "digest"
            }
            candidate["generation"] += 1
            candidate["previous_generation_digest"] = _digest(state)
            candidate["state"] = "retired"
            candidate["session"] = {
                **candidate["session"],
                "state": "retired",
                "generation": candidate["generation"],
            }
            _write_record(self.registry_path(anchor_id), candidate)
            return self.read_registry(anchor_id)

    @staticmethod
    def _scopes_overlap(left: str, right: str) -> bool:
        if left == right:
            return True
        left_kind, _, left_value = left.partition(":")
        right_kind, _, right_value = right.partition(":")
        if left_kind not in {"file", "directory"} or right_kind not in {
            "file",
            "directory",
        }:
            return False
        left_path = PurePosixPath(left_value)
        right_path = PurePosixPath(right_value)
        if left_kind == "directory" and (
            left_path == right_path or left_path in right_path.parents
        ):
            return True
        if right_kind == "directory" and (
            right_path == left_path or right_path in left_path.parents
        ):
            return True
        return False

    def admit_scope(self, anchor_id: str, scope: str) -> dict[str, Any]:
        if not isinstance(scope, str) or not scope:
            raise ProjectMigrationError("scope is invalid")
        state = self.read_registry(anchor_id)
        if state["state"] != "active":
            return {"status": "waiting-for-fence", "scope": scope}
        conflicts = [
            item["actor_id"]
            for item in state["protected_work"]
            if item["state"] == "active"
            and any(
                self._scopes_overlap(scope, protected)
                for protected in item["scopes"]
            )
        ]
        return {
            "status": "waiting-for-scope" if conflicts else "ready",
            "scope": scope,
            "protected_actors": conflicts,
        }

    def issue_transition_receipt(
        self,
        transition_id: str,
        *,
        anchor_id: str,
        generation: int,
        attempt_id: str,
        sink_plan: Sequence[str],
    ) -> dict[str, Any]:
        if transition_id not in TRANSITION_IDS:
            raise ProjectMigrationError("transition ID is unknown")
        entry = next(
            item
            for item in TRANSITION_REGISTRY
            if item["id"] == transition_id
        )
        if entry["family"] in {"observation", "test"}:
            raise ProjectMigrationError(
                "transition class cannot issue a mutation receipt"
            )
        if (
            not isinstance(generation, int)
            or generation < 0
            or not isinstance(sink_plan, Sequence)
            or isinstance(sink_plan, (str, bytes))
            or not sink_plan
        ):
            raise ProjectMigrationError("transition receipt binding is invalid")
        plan = [_binding(value, "ordered sink") for value in sink_plan]
        if len(plan) != len(set(plan)):
            raise ProjectMigrationError("ordered sink plan contains duplicates")
        attempt_id = _binding(attempt_id, "attempt")
        anchor = self._validate_anchor(anchor_id)
        if self.registry_path(anchor_id).exists():
            registry = self.read_registry(anchor_id)
            if registry["generation"] != generation:
                raise ProjectMigrationError(
                    "transition registry generation changed"
                )
        receipt_id = secrets.token_hex(32)
        token = secrets.token_hex(32)
        plan_digest = hashlib.sha256(_canonical(plan)).hexdigest()
        receipt = {
            "schema": SCHEMA_VERSION,
            "kind": "transition-receipt",
            "receipt_id": receipt_id,
            "token_digest": hashlib.sha256(
                token.encode("ascii")
            ).hexdigest(),
            "transition_id": transition_id,
            "transition_family": entry["family"],
            "project_id": anchor["project_id"],
            "anchor_id": anchor_id,
            "anchor_lock_id": anchor["lock_id"],
            "epoch": anchor["epoch"],
            "generation": generation,
            "attempt_id": attempt_id,
            "sink_plan": plan,
            "sink_plan_digest": plan_digest,
            "cursor": 0,
            "inflight": None,
            "status": "issued",
            "completed_ns": None,
        }
        path = (
            self._records(anchor_id)
            / "transition-receipts"
            / f"{receipt_id}.json"
        )
        with self._anchor_lock(anchor_id):
            _write_record(path, receipt, no_replace=True)
        return {
            "status": "issued",
            "transition_receipt": f"{receipt_id}.{token}",
            "sink_plan_digest": plan_digest,
        }

    def _transition_receipt(
        self, token: str, *, expected_path: Path | None = None
    ) -> dict[str, Any]:
        if not isinstance(token, str) or token.count(".") != 1:
            raise ProjectMigrationError("transition receipt is malformed")
        receipt_id, secret = token.split(".", 1)
        _hex(receipt_id, "transition receipt ID")
        _hex(secret, "transition receipt token")
        if expected_path is None:
            matches = list(
                self._anchors_directory.glob(
                    f"*/records/transition-receipts/{receipt_id}.json"
                )
            )
            if len(matches) != 1:
                raise ProjectMigrationError(
                    "transition receipt is missing or ambiguous"
                )
            path = matches[0]
        else:
            path = expected_path
        receipt = _read_record(path, "transition receipt")
        if (
            receipt.get("schema") != SCHEMA_VERSION
            or receipt.get("kind") != "transition-receipt"
            or receipt.get("receipt_id") != receipt_id
            or receipt.get("transition_id") not in TRANSITION_IDS
            or not hmac.compare_digest(
                str(receipt.get("token_digest")),
                hashlib.sha256(secret.encode("ascii")).hexdigest(),
            )
            or receipt.get("sink_plan_digest")
            != hashlib.sha256(
                _canonical(receipt.get("sink_plan"))
            ).hexdigest()
        ):
            raise ProjectMigrationError(
                "transition receipt is invalid or misbound"
            )
        anchor = self._validate_anchor(str(receipt["anchor_id"]))
        if (
            receipt.get("project_id") != anchor["project_id"]
            or receipt.get("anchor_lock_id") != anchor["lock_id"]
            or receipt.get("epoch") != anchor["epoch"]
        ):
            raise ProjectMigrationError(
                "transition receipt project or anchor binding changed"
            )
        return receipt

    def open_transition_context(self, token: str) -> TransitionContext:
        receipt = self._transition_receipt(token)
        if receipt["status"] != "issued":
            raise ProjectMigrationError("transition receipt was already used")
        path = (
            self._records(str(receipt["anchor_id"]))
            / "transition-receipts"
            / f"{receipt['receipt_id']}.json"
        )
        return TransitionContext(self, token, path, receipt, resumed=False)

    def resume_transition_context(self, token: str) -> TransitionContext:
        receipt = self._transition_receipt(token)
        if receipt["status"] != "active":
            raise ProjectMigrationError(
                "transition receipt has no resumable context"
            )
        path = (
            self._records(str(receipt["anchor_id"]))
            / "transition-receipts"
            / f"{receipt['receipt_id']}.json"
        )
        return TransitionContext(self, token, path, receipt, resumed=True)

    def write_mutable_record(
        self,
        context: TransitionContext | ObservationContext | None,
        anchor_id: str,
        relative_path: str,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(context, TransitionContext):
            if isinstance(context, ObservationContext):
                raise ProjectMigrationError(
                    "observation context cannot reach a durable sink"
                )
            raise ProjectMigrationError(
                "durable sink requires a guarded transition context"
            )
        relative = PurePosixPath(relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
        ):
            raise ProjectMigrationError("mutable record path is invalid")
        expected_sink = f"records/{relative.as_posix()}"
        if (
            context.anchor_id != anchor_id
            or context._executing_sink != expected_sink
        ):
            raise ProjectMigrationError(
                "durable sink is outside its guarded ordered plan"
            )
        path = self._records(anchor_id).joinpath(*relative.parts)
        _write_record(path, value)
        return _read_record(path, "mutable transition record")

    def compact_bootstrap_records(
        self, anchor_id: str, *, retain_after_ns: int
    ) -> dict[str, Any]:
        if not isinstance(retain_after_ns, int) or retain_after_ns < 0:
            raise ProjectMigrationError("record retention boundary is invalid")
        removed: list[str] = []
        with self._anchor_lock(anchor_id):
            anchor = self._validate_anchor(anchor_id)
            if self.registry_path(anchor_id).exists():
                registry = self.read_registry(anchor_id)
                if (
                    registry["anchor_lock_id"] != anchor["lock_id"]
                    or registry["anchor_manifest_digest"]
                    != anchor["manifest_digest"]
                ):
                    raise ProjectMigrationError(
                        "registry backlink changed before compaction"
                    )
            elif self.bs_path(anchor_id).exists():
                self.read_bootstrap_incident(anchor_id)
            else:
                raise ProjectMigrationError(
                    "bootstrap records have no retained backlink"
                )
            records = self._records(anchor_id)
            for directory_name in ("receipts", "transition-receipts"):
                directory = records / directory_name
                if not directory.exists():
                    continue
                for path in directory.iterdir():
                    if path.suffix != ".json":
                        continue
                    value = _read_record(path, "compactable record")
                    completed_ns = value.get("completed_ns")
                    completed = value.get("completed") is True or value.get(
                        "status"
                    ) == "complete"
                    if (
                        completed
                        and isinstance(completed_ns, int)
                        and completed_ns < retain_after_ns
                    ):
                        path.unlink()
                        removed.append(str(path))
                if not any(directory.iterdir()):
                    directory.rmdir()
            _sync_parent_metadata(records)
        return {"status": "complete", "removed": removed}

    def open_observation_context(
        self,
        transition_id: str,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
    ) -> ObservationContext:
        allowed_ids = {
            "R.C1.git-topology.scan",
            "R.C3.process.scan",
            "R.C4.workspace-index-status.scan",
            "R.C5.refs.scan",
        }
        if transition_id not in allowed_ids:
            raise ProjectMigrationError(
                "observation transition ID is unknown"
            )
        values = tuple(str(item) for item in argv)
        allowed_git = {
            ("git", "rev-parse", "--git-common-dir"),
            ("git", "worktree", "list", "--porcelain"),
            ("git", "status", "--porcelain=v2", "-z"),
            ("git", "show-ref", "--head"),
            ("git", "for-each-ref", "--format=%(refname)%00%(objectname)"),
        }
        allowed_process = {
            ("tasklist", "/fo", "csv", "/nh"),
            ("ps", "-eo", "pid=,ppid=,lstart=,args="),
        }
        if values not in allowed_git | allowed_process:
            raise ProjectMigrationError(
                "observation argv is outside the closed allowlist"
            )
        if transition_id == "R.C3.process.scan":
            if values not in allowed_process:
                raise ProjectMigrationError(
                    "process observation argv is outside the closed allowlist"
                )
        elif values not in allowed_git:
            raise ProjectMigrationError(
                "Git observation argv is outside the closed allowlist"
            )
        cwd_value = None
        if cwd is not None:
            cwd_value = _absolute_no_follow(cwd)
            _assert_no_link_or_reparse_ancestors(cwd_value)
            metadata = cwd_value.lstat()
            if _is_link_or_reparse(metadata) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise ProjectMigrationError(
                    "observation cwd is not a real directory"
                )
        return ObservationContext(transition_id, values, cwd_value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenBuild pre-repository coordinator setup/verification"
    )
    parser.add_argument(
        "mode",
        choices=BUILD_MODES,
        help="explicit Build mode to continue after setup",
    )
    parser.add_argument(
        "--coordinator-root",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    coordinator = ProjectMigrationCoordinator(
        coordinator_root=arguments.coordinator_root,
        codex_home=arguments.codex_home,
    )
    result = coordinator.pre_repository_setup(arguments.mode)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] != "setup-required" else 2


__all__ = (
    "BUILD_MODES",
    "CURRENT_CLIENT_VERSION",
    "DEFAULT_COORDINATOR_ROOT",
    "ProjectMigrationCoordinator",
    "ProjectMigrationError",
    "TRANSITION_ALIASES",
    "TRANSITION_IDS",
    "TRANSITION_REGISTRY",
    "validate_transition_registry",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
