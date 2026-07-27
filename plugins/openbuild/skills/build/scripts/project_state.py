"""Private, durable R-031 M1 coordinator state.

This owner creates only the I0/BA0/B0 bootstrap boundary.  It does not invoke
recovery, runners, worktrees, or scheduling.  POSIX durability is file plus
parent-directory ``fsync``.  On Windows files are flushed before publication
and every create, replace, or directory publish uses
``MoveFileExW(MOVEFILE_WRITE_THROUGH)`` as the metadata barrier.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from recovery_state import RecoveryRegistry, RecoveryStateError


SCHEMA_VERSION = 1
MAX_JSON_BYTES = 256 * 1024
WINDOWS_REPLACE_RETRY_SECONDS = 2.0
_HEX_64 = frozenset("0123456789abcdef")
_MILESTONE_ID = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_MILESTONE_STATES = frozenset({"ready", "waiting", "completed"})
_RUNTIME_JOB_ID = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_RUNTIME_NAMESPACE = re.compile(r"ob-[a-z0-9-]{1,80}\Z")
_RUNTIME_NAMESPACE_KINDS = (
    "port",
    "test-db",
    "compose",
    "temp",
    "build",
)
_SPECIFICATION_REVISION = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
_VERSION_TARGET = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_VERSION_SURFACES = (
    "CHANGELOG.md",
    "README.md",
    "README.ru.md",
    "plugins/openbuild/.codex-plugin/plugin.json",
)


def _version_order(value: str) -> tuple[int, int, int, int, tuple[tuple[int, Any], ...]]:
    """Return a SemVer precedence key for one already syntax-checked target."""

    match = _VERSION_TARGET.fullmatch(value)
    if match is None:
        raise ProjectStateError("version finalization target is invalid")
    core, separator, prerelease = value.partition("-")
    major, minor, patch = (int(item) for item in core.split("."))
    if not separator:
        return major, minor, patch, 1, ()
    identifiers: list[tuple[int, Any]] = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            identifiers.append((0, int(identifier)))
        else:
            identifiers.append((1, identifier))
    return major, minor, patch, 0, tuple(identifiers)


def _version_at_integration_ref(
    project: Path,
    integration_ref: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "show",
            f"{integration_ref}:plugins/openbuild/.codex-plugin/plugin.json",
        ],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ProjectStateError(
            "current integration version surface is unavailable"
        )
    try:
        text = result.stdout.decode("utf-8").strip()
        decoded = json.loads(text)
        version = (
            decoded.get("version")
            if isinstance(decoded, Mapping)
            else decoded
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        version = result.stdout.decode("utf-8", "strict").strip()
    if not isinstance(version, str) or not _VERSION_TARGET.fullmatch(version):
        raise ProjectStateError(
            "current integration version surface is invalid"
        )
    return version

# This is intentionally literal data: package validation parses it with
# ast.literal_eval and therefore never imports this owner while checking it.
TRANSITION_REGISTRY_DATA = (
    {"short_id": "I0", "id": "R-031.M1.I0.coordinator.setup", "class": "coordinator-setup", "family": "bootstrap", "incident_safe": False, "test_only": False},
    {"short_id": "BA0", "id": "R-031.M1.BA0.anchor.publish", "class": "anchor-no-replace-publish", "family": "bootstrap", "incident_safe": False, "test_only": False},
    {"short_id": "B0", "id": "R-031.M1.B0.bootstrap.clean", "class": "bootstrap-clean-or-breach", "family": "bootstrap", "incident_safe": False, "test_only": False},
    {"short_id": "O1", "id": "R-031.M1.O1.session-routing.stage", "class": "session-routing", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O2", "id": "R-031.M1.O2.lane-authorization.stage", "class": "lane-authorization", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O3", "id": "R-031.M1.O3.scope-validation.stage", "class": "scope-validation", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O4", "id": "R-031.M1.O4.prompt-snapshot.stage", "class": "prompt-snapshot", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O5", "id": "R-031.M1.O5.writer-dispatch.stage", "class": "writer-dispatch", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O6", "id": "R-031.M1.O6.commit-attribution.stage", "class": "commit-attribution", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O7", "id": "R-031.M1.O7.publication-gate.stage", "class": "publication-gate", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "O8", "id": "R-031.M1.O8.terminal-cleanup.stage", "class": "terminal-cleanup", "family": "ordinary", "incident_safe": False, "test_only": False},
    {"short_id": "S", "id": "R-031.M1.S.incident-status.observe", "class": "incident-status", "family": "incident", "incident_safe": True, "test_only": False},
    {"short_id": "BS", "id": "R-031.M1.BS.incident-breach.materialize", "class": "incident-breach", "family": "incident", "incident_safe": True, "test_only": False},
    {"short_id": "R", "id": "R-031.M1.R.state.observe", "class": "state-observer", "family": "observer", "incident_safe": True, "test_only": False},
    {"short_id": "TST", "id": "R-031.M1.TST.test.observe", "class": "test-observer", "family": "test", "incident_safe": True, "test_only": True},
)
TRANSITION_REGISTRY = tuple(MappingProxyType(dict(entry)) for entry in TRANSITION_REGISTRY_DATA)
TRANSITION_IDS = MappingProxyType({entry["short_id"]: entry["id"] for entry in TRANSITION_REGISTRY})
TRANSITION_CLASS_MEMBERSHIP = MappingProxyType(
    {
        "bootstrap": frozenset({"I0", "BA0", "B0"}),
        "ordinary": frozenset({f"O{number}" for number in range(1, 9)}),
        "incident": frozenset({"S", "BS"}),
        "observer": frozenset({"R"}),
        "test": frozenset({"TST"}),
    }
)

# Data-only cross-owner references.  The mapped owners remain untouched in M1.
ENTRY_POINT_TRANSITIONS = MappingProxyType(
    {
        "RecoveryRegistry.read_private_source": TRANSITION_IDS["R"],
        "RecoveryRegistry.mark_prompt_snapshot_released": TRANSITION_IDS["O" + "4"],
        "agent_runner.read_owner_prompt_snapshot": TRANSITION_IDS["R"],
        "agent_runner.stage_owner_prompt_snapshot": TRANSITION_IDS["O" + "4"],
        "agent_runner.dispatch_run": TRANSITION_IDS["O" + "5"],
    }
)
PROMPT_READ_REFERENCE_MAP = MappingProxyType(
    {
        "read_prompt": "agent_runner.read_owner_prompt_snapshot",
        "read_prompt_references": "agent_runner.collect_owner_prompt_snapshot_references",
    }
)
LOCK_ORDER = ("coordinator", "anchor", "registry", "lane", "scope")
NAMED_READS = (
    "read_status",
    "read_setup",
    "read_anchor",
    "read_state",
    "read_lanes",
    "read_milestones",
    "read_scopes",
    "read_private_source",
)


class ProjectStateError(RuntimeError):
    """Project coordinator state is absent, insecure, or violates its schema."""


def validate_transition_registry(registry: Sequence[Mapping[str, Any]]) -> list[str]:
    """Validate the immutable R-031 table without consulting another owner."""
    errors: list[str] = []
    expected = {member for members in TRANSITION_CLASS_MEMBERSHIP.values() for member in members}
    identifiers = [entry.get("short_id") for entry in registry]
    full_ids = [entry.get("id") for entry in registry]
    classes = [entry.get("class") for entry in registry]
    if set(identifiers) != expected or len(identifiers) != len(set(identifiers)):
        errors.append("transition short IDs are incomplete or non-unique")
    if len(full_ids) != len(set(full_ids)) or not all(isinstance(value, str) for value in full_ids):
        errors.append("transition full IDs are non-unique or malformed")
    if len(classes) != len(set(classes)) or not all(isinstance(value, str) and value for value in classes):
        errors.append("transition concrete classes are non-unique or malformed")
    for entry in registry:
        short_id = entry.get("short_id")
        family = entry.get("family")
        full_id = entry.get("id")
        if family not in TRANSITION_CLASS_MEMBERSHIP or short_id not in TRANSITION_CLASS_MEMBERSHIP.get(family, frozenset()):
            errors.append("transition class membership is invalid")
        if not isinstance(short_id, str) or not isinstance(full_id, str) or not full_id.startswith(f"R-031.M1.{short_id}."):
            errors.append("transition full ID is not an exact R-031 mapping")
        if entry.get("test_only") is not (short_id == "TST"):
            errors.append("test-only transition separation is invalid")
        if short_id in {"S", "BS", "R", "TST"} and entry.get("incident_safe") is not True:
            errors.append("incident-safe observer transition is invalid")
        if short_id not in {"S", "BS", "R", "TST"} and entry.get("incident_safe") is not False:
            errors.append("ordinary bootstrap transition is incorrectly incident-safe")
    if set(ENTRY_POINT_TRANSITIONS.values()) - set(full_ids):
        errors.append("entry point transition mapping is not registered")
    if set(PROMPT_READ_REFERENCE_MAP) != {"read_prompt", "read_prompt_references"}:
        errors.append("prompt read reference mapping is incomplete")
    return sorted(set(errors))


if _registry_errors := validate_transition_registry(TRANSITION_REGISTRY):
    raise RuntimeError("invalid R-031 transition registry: " + "; ".join(_registry_errors))


def _canonical(value: Any) -> bytes:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise ProjectStateError("project record exceeds bounded JSON size")
    return encoded


def _digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("digest", None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(isinstance(attributes, int) and attributes & reparse_flag)


def _absolute_no_follow(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _assert_no_link_or_reparse_ancestors(path: Path) -> None:
    """Walk lexical existing components; never resolve through a substituted one."""
    absolute = _absolute_no_follow(path)
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    for part in parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ProjectStateError("private coordinator ancestor is unreadable") from exc
        if _is_link_or_reparse(metadata):
            raise ProjectStateError("private coordinator path contains a link or reparse point")


def _windows_security_apis() -> tuple[Any, Any]:
    import ctypes

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
    advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    advapi32.GetTokenInformation.restype = ctypes.c_int
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
    advapi32.GetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    advapi32.GetFileSecurityW.restype = ctypes.c_int
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(ctypes.c_uint32)]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = ctypes.c_int
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int
    advapi32.SetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    advapi32.SetFileSecurityW.restype = ctypes.c_int
    advapi32.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
    advapi32.GetSecurityDescriptorDacl.restype = ctypes.c_int
    advapi32.SetNamedSecurityInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = ctypes.c_uint32
    return kernel32, advapi32


def _windows_current_user_sid() -> str:
    import ctypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    kernel32, advapi32 = _windows_security_apis()
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ProjectStateError(f"cannot open the current Windows token: {ctypes.WinError()}")
    try:
        required = ctypes.c_uint32()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise ProjectStateError(f"cannot size the current Windows token: {ctypes.WinError()}")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required.value, ctypes.byref(required)):
            raise ProjectStateError(f"cannot read the current Windows token: {ctypes.WinError()}")
        sid = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents.user.sid
        value = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(value)):
            raise ProjectStateError(f"cannot serialize the current Windows SID: {ctypes.WinError()}")
        try:
            return value.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(value, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _windows_object_sddl(path: Path) -> str:
    import ctypes

    kernel32, advapi32 = _windows_security_apis()
    required = ctypes.c_uint32()
    information = 0x00000001 | 0x00000004
    advapi32.GetFileSecurityW(str(path), information, None, 0, ctypes.byref(required))
    if not required.value:
        raise ProjectStateError(f"cannot size Windows private-object security: {ctypes.WinError()}")
    descriptor = ctypes.create_string_buffer(required.value)
    if not advapi32.GetFileSecurityW(str(path), information, descriptor, required.value, ctypes.byref(required)):
        raise ProjectStateError(f"cannot read Windows private-object security: {ctypes.WinError()}")
    value = ctypes.c_wchar_p()
    if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, information, ctypes.byref(value), None):
        raise ProjectStateError(f"cannot serialize Windows private-object security: {ctypes.WinError()}")
    try:
        return value.value or ""
    finally:
        kernel32.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def _windows_object_is_private(path: Path, user_sid: str, *, directory: bool) -> bool:
    sddl = _windows_object_sddl(path)
    inheritance = "OICI" if directory else ""
    expected = {
        f"(A;{inheritance};FA;;;SY)",
        f"(A;{inheritance};FA;;;{user_sid})",
    }
    if f"O:{user_sid}" not in sddl or "D:P" not in sddl:
        return False
    dacl = sddl.split("D:", 1)[1]
    import re
    return set(re.findall(r"\([^)]*\)", dacl)) == expected


def _protect_windows_private_object(path: Path, user_sid: str, *, directory: bool) -> None:
    import ctypes

    kernel32, advapi32 = _windows_security_apis()
    inheritance = "OICI" if directory else ""
    descriptor = ctypes.c_void_p()
    # The creator's owner SID is already the current user.  Setting OWNER on a
    # normal user token can require SeRestorePrivilege, so protect the DACL and
    # then verify both owner and DACL independently.
    sddl = f"D:P(A;{inheritance};FA;;;SY)(A;{inheritance};FA;;;{user_sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ProjectStateError(f"cannot build a private Windows DACL: {ctypes.WinError()}")
    try:
        present = ctypes.c_int()
        defaulted = ctypes.c_int()
        dacl = ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present.value or not dacl:
            raise ProjectStateError(f"cannot inspect a private Windows DACL: {ctypes.WinError()}")
        error = advapi32.SetNamedSecurityInfoW(
            str(path), 1, 0x00000004 | 0x80000000, None, None, dacl, None
        )
        if error:
            raise ProjectStateError(f"cannot protect private Windows state: {ctypes.WinError(error)}")
    finally:
        kernel32.LocalFree(descriptor)


def _windows_move_write_through(source: Path, target: Path, *, replace: bool) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.MoveFileExW.restype = ctypes.c_int
    flags = 0x00000008 | (0x00000001 if replace else 0)
    if kernel32.MoveFileExW(str(source), str(target), flags):
        return
    error = ctypes.get_last_error()
    if not replace and error in {80, 183}:
        raise FileExistsError(error, "private target already exists", str(target))
    failure = ProjectStateError(
        f"write-through private-object publish failed: {ctypes.WinError(error)}"
    )
    failure.winerror = error  # type: ignore[attr-defined]
    raise failure


def _windows_replace_error_code(error: BaseException) -> int | None:
    current: BaseException | None = error
    while current is not None:
        value = getattr(current, "winerror", None)
        if isinstance(value, int):
            return value
        current = current.__cause__
    return None


def _create_windows_private_directory(path: Path, user_sid: str) -> None:
    import ctypes

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint32),
            ("security_descriptor", ctypes.c_void_p),
            ("inherit_handle", ctypes.c_int),
        ]

    kernel32, advapi32 = _windows_security_apis()
    descriptor = ctypes.c_void_p()
    sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{user_sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ProjectStateError(f"cannot build a private Windows directory DACL: {ctypes.WinError()}")
    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
    try:
        if not kernel32.CreateDirectoryW(str(temporary), ctypes.byref(attributes)):
            error = ctypes.get_last_error()
            raise ProjectStateError(
                f"cannot create a private Windows directory: {ctypes.WinError(error)}"
            )
        _validate_private_directory(temporary, protect=False)
        try:
            _windows_move_write_through(temporary, path, replace=False)
        except FileExistsError:
            pass
    finally:
        kernel32.LocalFree(descriptor)
        try:
            temporary.rmdir()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ProjectStateError(
                "private Windows directory staging cleanup failed"
            ) from exc


def _validate_private_directory(path: Path, *, protect: bool) -> os.stat_result:
    _assert_no_link_or_reparse_ancestors(path)
    try:
        before = path.lstat()
    except OSError as exc:
        raise ProjectStateError("private coordinator directory is unreadable") from exc
    if _is_link_or_reparse(before) or not stat.S_ISDIR(before.st_mode):
        raise ProjectStateError("private coordinator directory is not a regular directory")
    if os.name == "nt":
        user_sid = _windows_current_user_sid()
        if not _windows_object_is_private(path, user_sid, directory=True):
            raise ProjectStateError("Windows private directory must have a current-user-only DACL")
    else:
        if hasattr(os, "geteuid") and before.st_uid != os.geteuid():
            raise ProjectStateError("private coordinator directory is not owned by the current user")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _is_link_or_reparse(opened) or not stat.S_ISDIR(opened.st_mode) or _identity(before) != _identity(opened):
                raise ProjectStateError("private coordinator directory identity changed")
            if protect:
                os.fchmod(descriptor, 0o700)
            if stat.S_IMODE(opened.st_mode) != 0o700 and not protect:
                raise ProjectStateError("private coordinator directory mode is not 0700")
        finally:
            os.close(descriptor)
        after = path.lstat()
        if _is_link_or_reparse(after) or _identity(before) != _identity(after):
            raise ProjectStateError("private coordinator directory identity changed")
        if stat.S_IMODE(after.st_mode) != 0o700:
            raise ProjectStateError("private coordinator directory mode is not 0700")
    return before


def _ensure_private_directory(path: Path) -> None:
    _assert_no_link_or_reparse_ancestors(path)
    missing: list[Path] = []
    current = path
    while True:
        try:
            current.lstat()
            break
        except FileNotFoundError:
            missing.append(current)
            if current.parent == current:
                raise ProjectStateError("private coordinator directory has no existing parent")
            current = current.parent
    user_sid = _windows_current_user_sid() if os.name == "nt" else None
    for directory in reversed(missing):
        _assert_no_link_or_reparse_ancestors(directory.parent)
        if os.name == "nt":
            assert user_sid is not None
            _create_windows_private_directory(directory, user_sid)
        else:
            try:
                os.mkdir(directory, 0o700)
            except FileExistsError:
                pass
        _validate_private_directory(directory, protect=os.name != "nt")
    _validate_private_directory(path, protect=os.name != "nt")


def _validate_private_regular(path: Path, *, protect: bool) -> os.stat_result:
    _assert_no_link_or_reparse_ancestors(path)
    try:
        before = path.lstat()
    except OSError as exc:
        raise ProjectStateError("private coordinator object is unreadable") from exc
    if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise ProjectStateError("private coordinator object is not a regular no-follow file")
    if os.name == "nt":
        user_sid = _windows_current_user_sid()
        if protect:
            _protect_windows_private_object(path, user_sid, directory=False)
        if not _windows_object_is_private(path, user_sid, directory=False):
            raise ProjectStateError("Windows private file must have a current-user-only DACL")
    else:
        if hasattr(os, "geteuid") and before.st_uid != os.geteuid():
            raise ProjectStateError("private coordinator file is not owned by the current user")
        if stat.S_IMODE(before.st_mode) != 0o600:
            raise ProjectStateError("private coordinator file mode is not 0600")
    return before


def _sync_parent_metadata(directory: Path) -> None:
    if os.name == "nt":
        # Every Windows caller publishes its already-flushed object through
        # MoveFileExW(MOVEFILE_WRITE_THROUGH), which is the metadata barrier.
        return
    descriptor = os.open(
        directory,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> dict[str, Any]:
    """Read one stable private record.  This function is deliberately sink-free."""
    _validate_private_directory(path.parent, protect=False)
    before = _validate_private_regular(path, protect=False)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened_before = os.fstat(descriptor)
        if _is_link_or_reparse(opened_before) or not stat.S_ISREG(opened_before.st_mode) or _identity(before) != _identity(opened_before):
            raise ProjectStateError("private coordinator object identity changed")
        if opened_before.st_size > MAX_JSON_BYTES:
            raise ProjectStateError("project record exceeds bounded JSON size")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_JSON_BYTES + 1))
            if not chunk:
                break
            chunks.append(chunk)
            if sum(len(value) for value in chunks) > MAX_JSON_BYTES:
                raise ProjectStateError("project record exceeds bounded JSON size")
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise ProjectStateError("private coordinator object disappeared while reading") from exc
    if _is_link_or_reparse(opened_after) or _is_link_or_reparse(after) or _identity(before) != _identity(opened_after) or _identity(opened_after) != _identity(after):
        raise ProjectStateError("private coordinator object identity changed")
    raw = b"".join(chunks)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectStateError("project record is malformed") from exc
    if not isinstance(value, dict) or value.get("digest") != _digest(value):
        raise ProjectStateError("project record digest is invalid")
    return value


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    payload = dict(value)
    payload["digest"] = _digest(payload)
    encoded = _canonical(payload) + b"\n"
    if len(encoded) > MAX_JSON_BYTES:
        raise ProjectStateError("project record exceeds bounded JSON size")
    published_path = path
    temporary: Path | None = None
    if os.name == "nt":
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
        published_path = temporary
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(published_path, flags, 0o600)
    except FileExistsError:
        raise
    except OSError as exc:
        raise ProjectStateError("private coordinator file could not be created") from exc
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _validate_private_regular(published_path, protect=os.name == "nt")
    if temporary is not None:
        try:
            _windows_move_write_through(temporary, path, replace=False)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    _validate_private_regular(path, protect=False)
    _sync_parent_metadata(path.parent)


def _write_exclusive_bytes(path: Path, value: bytes) -> None:
    """Publish one immutable owner-private archive without replacement."""

    if not isinstance(value, bytes):
        raise ProjectStateError("immutable archive is invalid")
    _assert_no_link_or_reparse_ancestors(path.parent)
    try:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ProjectStateError("immutable archive is unreadable") from exc
        if existing != value:
            raise ProjectStateError("immutable archive binding changed")
        return
    except OSError as exc:
        raise ProjectStateError("immutable archive publication failed") from exc
    _sync_parent_metadata(path.parent)


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    """Durably replace mutable state only; immutable anchor locks never use this."""
    _ensure_private_directory(path.parent)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
    _write_exclusive_json(temp, value)
    try:
        deadline = time.monotonic() + WINDOWS_REPLACE_RETRY_SECONDS
        delay = 0.01
        while True:
            try:
                if os.name == "nt":
                    _windows_move_write_through(temp, path, replace=True)
                else:
                    os.replace(temp, path)
                break
            except (OSError, ProjectStateError) as exc:
                if (
                    os.name != "nt"
                    or _windows_replace_error_code(exc) not in {5, 32, 33}
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.1)
    except (OSError, ProjectStateError) as exc:
        raise ProjectStateError(
            "mutable coordinator state could not be replaced"
        ) from exc
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    _validate_private_regular(path, protect=os.name == "nt")
    _sync_parent_metadata(path.parent)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold one stable private lock identity before, during, and after use."""
    _ensure_private_directory(path.parent)
    if not path.exists():
        try:
            _write_exclusive_json(path, {"schema": SCHEMA_VERSION, "kind": "coordinator-lock", "lock_id": secrets.token_hex(32)})
        except FileExistsError:
            pass
    before = _validate_private_regular(path, protect=False)
    try:
        descriptor = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ProjectStateError("private coordinator lock could not be opened") from exc
    try:
        opened = os.fstat(descriptor)
        if _identity(before) != _identity(opened):
            raise ProjectStateError("coordinator lock identity changed before acquisition")
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = path.lstat()
        if _is_link_or_reparse(current) or _identity(opened) != _identity(current):
            raise ProjectStateError("coordinator lock identity changed during acquisition")
        try:
            yield
        finally:
            final = path.lstat()
            if _is_link_or_reparse(final) or _identity(opened) != _identity(final):
                raise ProjectStateError("coordinator lock identity changed while held")
            if os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _publish_directory_no_replace(source: Path, target: Path) -> None:
    """Atomically publish an already durable directory without replacement."""
    if os.name == "nt":
        _windows_move_write_through(source, target, replace=False)
        return
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise ProjectStateError("atomic no-replace directory publish is unavailable on this platform") from exc
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        error = ctypes.get_errno()
        if error == 17:
            raise FileExistsError(error, "anchor target already exists", os.fspath(target))
        raise ProjectStateError(f"anchor directory publish failed: {os.strerror(error)}")


def _is_hex_identifier(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX_64


def _require_binding(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ProjectStateError(f"{name} binding is invalid")
    return value


def validate_scope_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"kind", "path", "mode"}:
        raise ProjectStateError("scope fields are incomplete or unknown")
    if value["kind"] not in {"file", "directory", "contract", "resource"} or value["mode"] not in {"hard", "soft"}:
        raise ProjectStateError("scope kind or mode is invalid")
    path = value["path"]
    if (
        not isinstance(path, str)
        or not path
        or len(path) > 4096
        or path != unicodedata.normalize("NFC", path)
        or any(
            unicodedata.category(character) == "Cc"
            for character in path
        )
        or "\\" in path
        or path.startswith("/")
        or path.endswith("/")
        or "//" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ProjectStateError("scope path is not normalized")
    try:
        from project_scopes import (
            ProjectScopeError,
            ProjectScopeManager,
            _WINDOWS_RESERVED,
        )

        canonical = ProjectScopeManager._path(path)
    except (ImportError, ProjectScopeError) as exc:
        raise ProjectStateError("scope path is not normalized") from exc
    if canonical != path:
        raise ProjectStateError("scope path is not normalized")
    for part in path.split("/"):
        stem = part.split(".", 1)[0].upper()
        if part.endswith((" ", ".")) or stem in _WINDOWS_RESERVED:
            raise ProjectStateError("scope path has a Windows alias")
    return dict(value)


def scope_requests_overlap(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    left_kind = left["kind"]
    right_kind = right["kind"]
    left_path = str(left["path"]).casefold()
    right_path = str(right["path"]).casefold()
    if (
        left_kind in {"file", "directory"}
        and right_kind in {"file", "directory"}
    ):
        return (
            left_path == right_path
            or left_path.startswith(right_path + "/")
            or right_path.startswith(left_path + "/")
        )
    return left_kind == right_kind and left_path == right_path


def _validate_hard_scope_overlaps(
    scopes: Sequence[Mapping[str, Any]],
) -> None:
    for index, left in enumerate(scopes):
        if any(
            scope_requests_overlap(left, right)
            for right in scopes[index + 1 :]
        ):
            raise ProjectStateError(
                "scope set contains an ancestor collision",
            )


_LANE_ID = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_GIT_OBJECT = re.compile(r"[0-9a-f]{40,64}\Z")
_GIT_REF = re.compile(r"refs/[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_LANE_STATES = frozenset(
    {
        "waiting-for-scope",
        "creating",
        "ready",
        "running",
        "recovery-ready",
        "waiting-for-integration",
        "cancelled",
        "quarantined",
        "closed",
    }
)
_TERMINAL_REASONS = frozenset({"cancelled", "crashed", "timeout", "pid-lost"})


def _is_normalized_relative_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == unicodedata.normalize("NFC", value)
        and len(value) <= 4096
        and "\\" not in value
        and not value.startswith("/")
        and not value.endswith("/")
        and "//" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _validate_common_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"path", "identity"}:
        raise ProjectStateError("lane common-directory identity is invalid")
    path = value.get("path")
    identity = value.get("identity")
    if (
        not isinstance(path, str)
        or not Path(path).is_absolute()
        or len(path) > 4096
        or not isinstance(identity, list)
        or len(identity) != 2
        or not all(isinstance(part, int) and part >= 0 for part in identity)
    ):
        raise ProjectStateError("lane common-directory identity is invalid")
    return {"path": path, "identity": list(identity)}


def _validate_writer(value: Any) -> dict[str, Any]:
    required = {"lease_id", "run_id", "allowed_set_digest", "lease_kind"}
    if not isinstance(value, dict) or set(value) != required:
        raise ProjectStateError("lane writer binding is invalid")
    if (
        not isinstance(value["lease_id"], str)
        or not value["lease_id"]
        or len(value["lease_id"]) > 512
        or not isinstance(value["run_id"], str)
        or not value["run_id"]
        or len(value["run_id"]) > 512
        or not _is_hex_identifier(value["allowed_set_digest"])
        or value["lease_kind"] not in {"normal-contained", "recovery-target"}
    ):
        raise ProjectStateError("lane writer binding is invalid")
    return dict(value)


_SCOPE_KIND_ORDER = {"file": 0, "directory": 1, "contract": 2, "resource": 3}


def _scope_reservation_projection(value: Any) -> dict[str, Any]:
    required = {"kind", "path", "mode", "sequence", "reservation", "phase"}
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("kind") not in _SCOPE_KIND_ORDER
        or value.get("mode") not in {"hard", "soft"}
        or not _is_normalized_relative_path(value.get("path"))
        or not isinstance(value.get("sequence"), int)
        or value["sequence"] < 1
        or not isinstance(value.get("reservation"), str)
        or not value["reservation"]
        or len(value["reservation"]) > 256
        or value.get("phase") not in {"planned", "expansion"}
    ):
        raise ProjectStateError("scope reservation binding is invalid")
    return dict(value)


def _scope_reservation_order(value: Mapping[str, Any]) -> tuple[int, str, str, str, int, str, str]:
    return (
        _SCOPE_KIND_ORDER[str(value["kind"])],
        str(value["path"]).casefold(),
        str(value["path"]),
        str(value["mode"]),
        int(value["sequence"]),
        str(value["reservation"]),
        str(value["phase"]),
    )


def _safe_stop_intent_id(value: Mapping[str, Any]) -> str:
    stable = {
        key: value[key]
        for key in (
            "schema",
            "anchor_id",
            "lane_id",
            "intent_generation",
            "session",
            "writer",
            "old_hard_grants",
            "requested_scopes",
            "reservation",
            "reason",
        )
    }
    return hashlib.sha256(_canonical(stable)).hexdigest()


def _validate_safe_stop(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "intent_id",
        "status",
        "anchor_id",
        "lane_id",
        "intent_generation",
        "session",
        "writer",
        "old_hard_grants",
        "requested_scopes",
        "reservation",
        "reason",
    }
    status = value.get("status") if isinstance(value, dict) else None
    if status in {"stopping", "completed"}:
        required.add("consumed_generation")
    if status == "completed":
        required.update(
            {
                "completed_generation",
                "completed_state",
                "terminal_archive",
                "recovery_checkpoint_digest",
                "preserved_changes",
            }
        )
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-lane-safe-stop-v1"
        or not _is_hex_identifier(value.get("intent_id"))
        or value.get("status") not in {"requested", "stopping", "completed"}
        or not _is_hex_identifier(value.get("anchor_id"))
        or not isinstance(value.get("lane_id"), str)
        or not _LANE_ID.fullmatch(value["lane_id"])
        or not isinstance(value.get("intent_generation"), int)
        or value["intent_generation"] < 1
        or not isinstance(value.get("reservation"), str)
        or not value["reservation"]
        or len(value["reservation"]) > 256
        or value.get("reason") not in {"scope-wait-cycle", "scope-expansion-wait"}
        or not isinstance(value.get("session"), dict)
        or frozenset(value["session"])
        not in {
            frozenset({"common", "integration_ref", "reader_floor"}),
            frozenset(
                {
                    "common",
                    "integration_ref",
                    "reader_floor",
                    "recovery_root",
                }
            ),
        }
        or not isinstance(value.get("old_hard_grants"), list)
        or not value["old_hard_grants"]
        or not isinstance(value.get("requested_scopes"), list)
        or not value["requested_scopes"]
    ):
        raise ProjectStateError("lane safe-stop binding is invalid")
    _validate_lane_session(value["session"])
    _validate_writer(value["writer"])
    grants = [_scope_reservation_projection(item) for item in value["old_hard_grants"]]
    requests = [validate_scope_state(item) for item in value["requested_scopes"]]
    if (
        any(item["mode"] != "hard" for item in grants)
        or any(item["mode"] != "hard" for item in requests)
        or grants != sorted(grants, key=_scope_reservation_order)
        or requests
        != sorted(
            requests,
            key=lambda item: (
                _SCOPE_KIND_ORDER[item["kind"]],
                item["path"].casefold(),
                item["path"],
                item["mode"],
            ),
        )
        or len({(item["kind"], item["path"].casefold(), item["mode"]) for item in grants})
        != len(grants)
        or len({(item["kind"], item["path"].casefold(), item["mode"]) for item in requests})
        != len(requests)
        or value["intent_id"] != _safe_stop_intent_id(value)
    ):
        raise ProjectStateError("lane safe-stop binding is invalid")
    if value["status"] == "stopping" and (
        not isinstance(value.get("consumed_generation"), int)
        or value["consumed_generation"] < value["intent_generation"]
    ):
        raise ProjectStateError("lane safe-stop consumption is invalid")
    if value["status"] == "completed":
        checkpoint_digest = value.get("recovery_checkpoint_digest")
        if (
            not isinstance(value.get("consumed_generation"), int)
            or value["consumed_generation"] < value["intent_generation"]
            or not isinstance(value.get("completed_generation"), int)
            or value["completed_generation"] <= value["consumed_generation"]
            or value.get("completed_state") not in {"ready", "recovery-ready"}
            or not _is_hex_identifier(value.get("terminal_archive"))
            or not isinstance(value.get("preserved_changes"), bool)
            or (
                value["completed_state"] == "ready"
                and checkpoint_digest is not None
            )
            or (
                value["completed_state"] == "recovery-ready"
                and not _is_hex_identifier(checkpoint_digest)
            )
        ):
            raise ProjectStateError("lane safe-stop completion is invalid")
    return dict(value)


def _validate_lane_session(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    legacy_fields = {
        "common",
        "integration_ref",
        "reader_floor",
    }
    current_fields = legacy_fields | {"recovery_root"}
    if (
        not isinstance(value, dict)
        or frozenset(value)
        not in {frozenset(legacy_fields), frozenset(current_fields)}
    ):
        raise ProjectStateError("lane session binding is invalid")
    integration_ref = value.get("integration_ref")
    recovery_root = value.get("recovery_root")
    if (
        not isinstance(integration_ref, str)
        or not _GIT_REF.fullmatch(integration_ref)
        or integration_ref.endswith(("/", "."))
        or ".." in integration_ref.split("/")
        or value.get("reader_floor") != "2.3.6"
        or (
            recovery_root is not None
            and (
                not isinstance(recovery_root, str)
                or not Path(recovery_root).is_absolute()
                or "\0" in recovery_root
                or len(recovery_root) > 4096
            )
        )
    ):
        raise ProjectStateError("lane session integration binding is invalid")
    result = {
        "common": _validate_common_identity(value.get("common")),
        "integration_ref": integration_ref,
        "reader_floor": "2.3.6",
    }
    if recovery_root is not None:
        result["recovery_root"] = recovery_root
    return result


def _validate_milestone_projection(value: Any) -> dict[str, Any]:
    """Validate the intentionally writer-free R-032 M4 scheduler record."""
    required = {
        "task_id", "milestone_id", "depends_on", "hard_scopes", "soft_intents",
        "primary_signal", "red_signal", "integration_output", "hotspot", "state",
    }
    if not isinstance(value, dict) or not required <= set(value):
        raise ProjectStateError("milestone fields are incomplete")
    completed = value.get("state") == "completed"
    expected = required | ({"validation"} if completed else set())
    if set(value) != expected:
        raise ProjectStateError("milestone fields are incomplete or unknown")
    text_fields = (
        "task_id",
        "milestone_id",
        "primary_signal",
        "red_signal",
        "integration_output",
    )
    if (
        not _MILESTONE_ID.fullmatch(value.get("task_id", ""))
        or not _MILESTONE_ID.fullmatch(value.get("milestone_id", ""))
        or value.get("state") not in _MILESTONE_STATES
        or not isinstance(value.get("hotspot"), bool)
        or any(
            not isinstance(value.get(key), str)
            or not value[key]
            or len(value[key]) > 4096
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value[key]
            )
            for key in text_fields
        )
    ):
        raise ProjectStateError("milestone identity or state is invalid")
    dependencies = value.get("depends_on")
    if (
        not isinstance(dependencies, list)
        or any(
            not isinstance(item, str)
            or not _MILESTONE_ID.fullmatch(item)
            for item in dependencies
        )
        or dependencies != sorted(dependencies)
        or len(dependencies) != len(set(dependencies))
        or value["milestone_id"] in dependencies
    ):
        raise ProjectStateError("milestone dependency contract is invalid")
    normalized_scopes: dict[str, list[dict[str, Any]]] = {}
    for key, mode in (("hard_scopes", "hard"), ("soft_intents", "soft")):
        items = value.get(key)
        if not isinstance(items, list):
            raise ProjectStateError("milestone decomposition contract is invalid")
        parsed = [validate_scope_state(item) for item in items]
        if any(item["mode"] != mode for item in parsed):
            raise ProjectStateError("milestone scope mode is invalid")
        ordered = sorted(
            parsed,
            key=lambda item: (
                _SCOPE_KIND_ORDER[item["kind"]],
                item["path"].casefold(),
                item["path"],
                item["mode"],
            ),
        )
        identities = [
            (item["kind"], item["path"].casefold(), item["mode"])
            for item in ordered
        ]
        if parsed != ordered or len(identities) != len(set(identities)):
            raise ProjectStateError("milestone scope ordering is invalid")
        normalized_scopes[key] = ordered
    if not normalized_scopes["hard_scopes"]:
        raise ProjectStateError("milestone scope contract is invalid")
    _validate_hard_scope_overlaps(
        normalized_scopes["hard_scopes"],
    )
    hard_keys = {
        (item["kind"], item["path"].casefold())
        for item in normalized_scopes["hard_scopes"]
    }
    soft_keys = {
        (item["kind"], item["path"].casefold())
        for item in normalized_scopes["soft_intents"]
    }
    if hard_keys & soft_keys:
        raise ProjectStateError("milestone hard scope and soft intent overlap")
    if completed and value.get("validation") != {"focused_green": True, "intermediate_valid": True}:
        raise ProjectStateError("milestone completion validation is invalid")
    result = dict(value)
    result["depends_on"] = list(dependencies)
    result.update(normalized_scopes)
    return result


def _validate_milestone_dag(milestones: Sequence[Mapping[str, Any]]) -> None:
    ordered = sorted(
        milestones,
        key=lambda item: (str(item["task_id"]), str(item["milestone_id"])),
    )
    if list(milestones) != ordered:
        raise ProjectStateError("milestone project ordering is invalid")
    by_identity = {
        (item["task_id"], item["milestone_id"]): item
        for item in milestones
    }
    if len(by_identity) != len(milestones):
        raise ProjectStateError("milestone identities are not unique")
    task_ids = sorted({str(item["task_id"]) for item in milestones})
    for task_id in task_ids:
        by_id = {
            str(item["milestone_id"]): item
            for item in milestones
            if item["task_id"] == task_id
        }
        if any(
            dependency not in by_id
            for item in by_id.values()
            for dependency in item["depends_on"]
        ):
            raise ProjectStateError("milestone dependency is unknown")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(milestone_id: str) -> None:
            if milestone_id in visiting:
                raise ProjectStateError("milestone dependency cycle is invalid")
            if milestone_id not in visited:
                visiting.add(milestone_id)
                for dependency in by_id[milestone_id]["depends_on"]:
                    visit(dependency)
                visiting.remove(milestone_id)
                visited.add(milestone_id)

        for milestone_id in sorted(by_id):
            visit(milestone_id)
        for item in by_id.values():
            if item["state"] == "completed":
                if any(
                    by_id[dependency]["state"] != "completed"
                    for dependency in item["depends_on"]
                ):
                    raise ProjectStateError(
                        "milestone completed before dependencies"
                    )
                continue
            expected = (
                "ready"
                if all(
                    by_id[dependency]["state"] == "completed"
                    for dependency in item["depends_on"]
                )
                else "waiting"
            )
            if item["state"] != expected:
                raise ProjectStateError("milestone readiness is not dependency-derived")


def _validate_milestone_transition(current: Sequence[Mapping[str, Any]], proposed: Sequence[Mapping[str, Any]]) -> None:
    before = {
        (item["task_id"], item["milestone_id"]): item
        for item in current
    }
    after = {
        (item["task_id"], item["milestone_id"]): item
        for item in proposed
    }
    if not set(before) <= set(after):
        raise ProjectStateError("milestone plan identity changed")
    for task_id in {identity[0] for identity in before}:
        old_ids = {
            identity for identity in before if identity[0] == task_id
        }
        new_ids = {
            identity for identity in after if identity[0] == task_id
        }
        if old_ids != new_ids:
            raise ProjectStateError("milestone plan identity changed")
    completed_now: list[tuple[str, str]] = []
    for identity, old in before.items():
        new = after[identity]
        for key in old:
            if key not in {"state", "validation"} and new.get(key) != old.get(key):
                raise ProjectStateError("milestone decomposition contract changed")
        if old["state"] == "completed" and new["state"] != "completed":
            raise ProjectStateError("milestone state cannot regress")
        if old["state"] == "ready" and new["state"] not in {"ready", "completed"}:
            raise ProjectStateError("milestone state cannot regress")
        if old["state"] == "waiting" and new["state"] not in {"waiting", "ready"}:
            raise ProjectStateError("milestone state cannot regress")
        if old["state"] != "completed" and new["state"] == "completed":
            if old["state"] != "ready":
                raise ProjectStateError("milestone completed before dependencies")
            old_task = {
                item["milestone_id"]: item
                for item in current
                if item["task_id"] == identity[0]
            }
            if any(
                old_task[dependency]["state"] != "completed"
                for dependency in new["depends_on"]
            ):
                raise ProjectStateError("milestone completed before dependencies")
            completed_now.append(identity)
    if len(completed_now) > 1:
        raise ProjectStateError("only one milestone may complete per project CAS")
    if any(
        item["state"] == "completed"
        for identity, item in after.items()
        if identity not in before
    ):
        raise ProjectStateError("new milestone plan cannot begin completed")


def _milestone_lane_binding(task_id: str, milestone_id: str) -> str:
    return f"{task_id}:{milestone_id}"


def _validate_scheduler_lane_binding(value: Any) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "task_id", "milestone_id"}
        or value.get("schema") != "project-scheduler-lane-v1"
        or not _MILESTONE_ID.fullmatch(str(value.get("task_id", "")))
        or not _MILESTONE_ID.fullmatch(
            str(value.get("milestone_id", "")),
        )
    ):
        raise ProjectStateError(
            "scheduler lane binding is invalid",
        )
    return {
        "schema": "project-scheduler-lane-v1",
        "task_id": str(value["task_id"]),
        "milestone_id": str(value["milestone_id"]),
    }


def _validate_milestone_lane_projection(
    milestones: Sequence[Mapping[str, Any]],
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]] = (),
) -> None:
    by_lane_binding = {
        _milestone_lane_binding(
            str(item["task_id"]),
            str(item["milestone_id"]),
        ): item
        for item in milestones
    }
    binding_counts: dict[str, int] = {}
    for lane in lanes:
        scheduler_binding = lane.get("scheduler_binding")
        if scheduler_binding is None:
            continue
        parsed_binding = _validate_scheduler_lane_binding(
            scheduler_binding,
        )
        lane_binding = _milestone_lane_binding(
            parsed_binding["task_id"],
            parsed_binding["milestone_id"],
        )
        if lane.get("milestone") != lane_binding:
            raise ProjectStateError(
                "scheduler lane milestone identity drifted",
            )
        milestone = by_lane_binding.get(lane_binding)
        if milestone is None:
            raise ProjectStateError(
                "lane milestone is not bound to a project DAG record"
            )
        binding_counts[lane_binding] = binding_counts.get(lane_binding, 0) + 1
        if binding_counts[lane_binding] > 1:
            raise ProjectStateError(
                "milestone is bound to more than one lane"
            )
        expected_hard = {
            (item["kind"], item["path"].casefold(), item["mode"])
            for item in milestone["hard_scopes"]
        }
        lane_hard = {
            (item["kind"], item["path"].casefold(), item["mode"])
            for item in lane.get("scope_requests", [])
            if isinstance(item, Mapping) and item.get("mode") == "hard"
        }
        if lane_hard != expected_hard:
            raise ProjectStateError(
                "lane hard scopes differ from the milestone plan"
            )
        if milestone["state"] == "waiting":
            raise ProjectStateError(
                "waiting milestone cannot admit a scheduler lane"
            )
        if (
            milestone["state"] == "completed"
            and lane.get("state") == "running"
        ):
            raise ProjectStateError(
                "completed milestone retains a running lane writer"
            )


def _validate_lane_projection(value: Any) -> dict[str, Any]:
    base_fields = {
        "lane_id",
        "milestone",
        "reader_floor",
        "common",
        "base",
        "branch",
        "worktree",
        "scopes",
        "state",
        "writer",
    }
    if not isinstance(value, dict) or not base_fields <= set(value):
        raise ProjectStateError("lane fields are incomplete")
    lane_id = value.get("lane_id")
    state = value.get("state")
    if (
        not isinstance(lane_id, str)
        or not _LANE_ID.fullmatch(lane_id)
        or state not in _LANE_STATES
        or not isinstance(value.get("milestone"), str)
        or not value["milestone"]
        or len(value["milestone"]) > 256
        or value.get("reader_floor") != "2.3.6"
        or not isinstance(value.get("base"), str)
        or not _GIT_OBJECT.fullmatch(value["base"])
        or value.get("branch") != f"refs/heads/openbuild/lanes/{lane_id}"
        or not isinstance(value.get("worktree"), str)
        or not Path(value["worktree"]).is_absolute()
        or len(value["worktree"]) > 4096
    ):
        raise ProjectStateError("lane identity or state is invalid")
    _validate_common_identity(value.get("common"))
    scopes = value.get("scopes")
    if (
        not isinstance(scopes, list)
        or not scopes
        or not all(_is_normalized_relative_path(scope) for scope in scopes)
        or len({scope.casefold() for scope in scopes}) != len(scopes)
    ):
        raise ProjectStateError("lane scopes are invalid")
    writer = value.get("writer")
    if state in {"running", "waiting-for-integration", "quarantined"}:
        _validate_writer(writer)
    elif state != "closed" and writer is not None:
        raise ProjectStateError("lane writer/state split is invalid")
    elif state == "closed" and writer is not None:
        _validate_writer(writer)
    expected_fields = set(base_fields)
    scheduler_binding = value.get("scheduler_binding")
    if scheduler_binding is not None:
        parsed_scheduler_binding = _validate_scheduler_lane_binding(
            scheduler_binding,
        )
        if value["milestone"] != _milestone_lane_binding(
            parsed_scheduler_binding["task_id"],
            parsed_scheduler_binding["milestone_id"],
        ):
            raise ProjectStateError(
                "scheduler lane milestone identity drifted",
            )
        expected_fields.add("scheduler_binding")
    if state in {"recovery-ready", "cancelled", "quarantined", "closed"}:
        expected_fields.update({"reason", "terminal_from"})
        terminal_from = value.get("terminal_from")
        if (
            value.get("reason") not in _TERMINAL_REASONS
            or terminal_from not in {"waiting-for-scope", "creating", "ready", "running"}
            or (state == "quarantined" and terminal_from not in {"creating", "ready", "running"})
            or (state == "recovery-ready" and terminal_from != "running")
        ):
            raise ProjectStateError("lane terminal binding is invalid")
    if state == "recovery-ready":
        expected_fields.update(
            {"terminal_evidence", "recovery_checkpoint_digest"}
        )
        if (
            not _is_hex_identifier(value.get("terminal_evidence"))
            or not _is_hex_identifier(value.get("recovery_checkpoint_digest"))
        ):
            raise ProjectStateError("lane recovery evidence is invalid")
    if state == "closed":
        expected_fields.add("terminal_evidence")
        if not _is_hex_identifier(value.get("terminal_evidence")):
            raise ProjectStateError("lane terminal evidence is invalid")
    if state == "waiting-for-integration":
        expected_fields.add("terminal_evidence")
        if not _is_hex_identifier(value.get("terminal_evidence")):
            raise ProjectStateError("lane terminal evidence is invalid")
    safe_stop = value.get("safe_stop")
    if safe_stop is not None:
        parsed_safe_stop = _validate_safe_stop(safe_stop)
        if (
            parsed_safe_stop["lane_id"] != lane_id
            or parsed_safe_stop["session"]["common"] != value.get("common")
        ):
            raise ProjectStateError("lane safe-stop binding is invalid")
        if parsed_safe_stop["status"] in {"requested", "stopping"} and (
            state != "running"
            or not isinstance(writer, dict)
            or parsed_safe_stop["writer"] != writer
        ):
            raise ProjectStateError("lane safe-stop binding is invalid")
        if (
            parsed_safe_stop["status"] == "completed"
            and state in {"creating", "waiting-for-scope"}
        ):
            raise ProjectStateError("lane safe-stop completion state is invalid")
        expected_fields.add("safe_stop")
    dependency_binding = value.get("dependency_binding")
    if dependency_binding is not None:
        parsed_dependency_binding = _validate_dependency_binding(
            dependency_binding
        )
        if (
            parsed_dependency_binding["accepted_base"] != value["base"]
            or (
                isinstance(writer, Mapping)
                and parsed_dependency_binding["allowed_set_digest"]
                != writer["allowed_set_digest"]
            )
        ):
            raise ProjectStateError("lane dependency binding drifted")
        expected_fields.add("dependency_binding")
    integration_stale = value.get("integration_stale")
    if integration_stale is not None:
        if (
            not isinstance(integration_stale, dict)
            or set(integration_stale) != {
                "accepted_commit",
                "acceptance_id",
                "generation",
                "dependency_digest",
                "producer_result_digest",
            }
            or not _GIT_OBJECT.fullmatch(
                str(integration_stale.get("accepted_commit")),
            )
            or not _is_hex_identifier(integration_stale.get("acceptance_id"))
            or not isinstance(integration_stale.get("generation"), int)
            or integration_stale["generation"] < 1
            or not _is_hex_identifier(
                integration_stale.get("dependency_digest")
            )
            or not _is_hex_identifier(
                integration_stale.get("producer_result_digest")
            )
        ):
            raise ProjectStateError("lane integration stale marker is invalid")
        expected_fields.add("integration_stale")
    scope_wait_from = value.get("scope_wait_from")
    if scope_wait_from is not None:
        if (
            state != "waiting-for-scope"
            or scope_wait_from not in {"creating", "ready"}
        ):
            raise ProjectStateError("lane scope-wait origin is invalid")
        expected_fields.add("scope_wait_from")
    scope_schema = value.get("scope_schema")
    if scope_schema is not None:
        if scope_schema != "project-scopes-v1":
            raise ProjectStateError("lane scope schema is invalid")
        scope_enqueue_sequence = value.get("scope_enqueue_sequence")
        if (
            not isinstance(scope_enqueue_sequence, int)
            or scope_enqueue_sequence < 1
        ):
            raise ProjectStateError("lane scope enqueue sequence is invalid")
        scope_requests = value.get("scope_requests")
        if not isinstance(scope_requests, list) or not scope_requests:
            raise ProjectStateError("lane scope requests are invalid")
        kind_order = {
            "file": 0,
            "directory": 1,
            "contract": 2,
            "resource": 3,
        }
        normalized_requests: list[dict[str, str]] = []
        for request in scope_requests:
            if (
                not isinstance(request, dict)
                or set(request) != {"kind", "path", "mode"}
                or request.get("kind") not in kind_order
                or request.get("mode") not in {"hard", "soft"}
                or not _is_normalized_relative_path(request.get("path"))
            ):
                raise ProjectStateError("lane scope request is invalid")
            normalized_requests.append(dict(request))
        ordered_requests = sorted(
            normalized_requests,
            key=lambda request: (
                kind_order[request["kind"]],
                request["path"].casefold(),
                request["path"],
                request["mode"],
            ),
        )
        request_keys = [
            (request["kind"], request["path"].casefold(), request["mode"])
            for request in ordered_requests
        ]
        flattened: list[str] = []
        seen_paths: set[str] = set()
        for request in ordered_requests:
            key = request["path"].casefold()
            if key not in seen_paths:
                flattened.append(request["path"])
                seen_paths.add(key)
        flattened.sort(key=lambda path: (path.casefold(), path))
        if (
            normalized_requests != ordered_requests
            or len(request_keys) != len(set(request_keys))
            or scopes != flattened
        ):
            raise ProjectStateError("lane scope request binding is invalid")
        _validate_hard_scope_overlaps(
            [
                request
                for request in ordered_requests
                if request["mode"] == "hard"
            ],
        )
        expected_fields.update(
            {"scope_schema", "scope_requests", "scope_enqueue_sequence"}
        )
    if set(value) != expected_fields:
        raise ProjectStateError("lane fields are incomplete or unknown")
    return dict(value)


def _validate_protected_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") not in {"missing", "file", "link"}:
        raise ProjectStateError("protected scope content is invalid")
    if value["kind"] == "missing":
        if set(value) != {"kind", "digest"} or value.get("digest") is not None:
            raise ProjectStateError("protected scope deletion evidence is invalid")
    elif (
        set(value) != {"kind", "digest", "git_blob_id", "git_mode"}
        or not _is_hex_identifier(value.get("digest"))
        or not isinstance(value.get("git_blob_id"), str)
        or not _GIT_OBJECT.fullmatch(value["git_blob_id"])
        or value.get("git_mode") not in {"100644", "100755", "120000"}
        or (value["kind"] == "link") != (value["git_mode"] == "120000")
    ):
        raise ProjectStateError("protected scope content evidence is invalid")
    return dict(value)


def _protected_scope_snapshot(
    project: Path,
    common: Mapping[str, Any],
    path: str,
) -> dict[str, Any]:
    """Capture one protected path with the same content/index provenance owner."""

    if not _is_normalized_relative_path(path):
        raise ProjectStateError("protected scope path is invalid")
    absolute = project / Path(path)
    try:
        metadata = absolute.lstat()
    except FileNotFoundError:
        content: dict[str, Any] = {"kind": "missing", "digest": None}
    except OSError as exc:
        raise ProjectStateError("protected-user-work is unreadable") from exc
    else:
        if _is_link_or_reparse(metadata):
            try:
                target = os.readlink(absolute)
            except OSError as exc:
                raise ProjectStateError(
                    "protected-user-work link is unreadable"
                ) from exc
            content = {
                "kind": "link",
                "digest": hashlib.sha256(os.fsencode(target)).hexdigest(),
            }
            blob = subprocess.run(
                ["git", "hash-object", "--stdin"],
                cwd=project,
                input=os.fsencode(target),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        elif stat.S_ISREG(metadata.st_mode):
            try:
                content_digest = hashlib.sha256(absolute.read_bytes()).hexdigest()
            except OSError as exc:
                raise ProjectStateError(
                    "protected-user-work is unreadable"
                ) from exc
            content = {"kind": "file", "digest": content_digest}
            blob = subprocess.run(
                ["git", "hash-object", f"--path={path}", "--", path],
                cwd=project,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        else:
            raise ProjectStateError("protected-user-work type is unsupported")
        try:
            blob_id = blob.stdout.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ProjectStateError(
                "protected-user-work Git blob identity is unavailable"
            ) from exc
        if blob.returncode != 0 or not _GIT_OBJECT.fullmatch(blob_id):
            raise ProjectStateError(
                "protected-user-work Git blob identity is unavailable"
            )
        content["git_blob_id"] = blob_id

    index = subprocess.run(
        ["git", "ls-files", "--stage", "-z", "--", path],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if index.returncode != 0:
        raise ProjectStateError("protected-user-work index is unavailable")
    index_fields = index.stdout.split(b"\t", 1)[0].split() if index.stdout else []
    try:
        index_mode = (
            index_fields[0].decode("ascii")
            if len(index_fields) >= 3
            else None
        )
        index_blob_id = (
            index_fields[1].decode("ascii")
            if len(index_fields) >= 3
            else None
        )
    except UnicodeDecodeError as exc:
        raise ProjectStateError("protected-user-work index is invalid") from exc
    if content["kind"] == "link":
        content["git_mode"] = "120000"
    elif content["kind"] == "file":
        executable = bool(
            metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )
        content["git_mode"] = (
            index_mode
            if os.name == "nt" and index_mode in {"100644", "100755"}
            else ("100755" if executable else "100644")
        )
    evidence = {
        "common": dict(common),
        "path": path,
        "content": content,
        "index_digest": hashlib.sha256(index.stdout).hexdigest(),
        "index_blob_id": index_blob_id,
    }
    return {
        "kind": "protected-user-work",
        "path": path,
        "owner": None,
        "adoption": "protected",
        "evidence": evidence,
        "provenance": hashlib.sha256(_canonical(evidence)).hexdigest(),
    }


def _validate_adoption_receipt(value: Any) -> dict[str, Any]:
    required = {
        "kind",
        "project_common_digest",
        "integration_ref",
        "user_action_digest",
        "plan_digest",
        "paths",
        "integrated_commit",
        "digest",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ProjectStateError("protected scope adoption receipt is invalid")
    paths = value.get("paths")
    if (
        value.get("kind") != "accepted-protected-work-integration"
        or not all(
            _is_hex_identifier(value.get(field))
            for field in (
                "project_common_digest",
                "user_action_digest",
                "plan_digest",
                "digest",
            )
        )
        or not isinstance(value.get("integration_ref"), str)
        or not value["integration_ref"].startswith("refs/")
        or not isinstance(value.get("integrated_commit"), str)
        or not _GIT_OBJECT.fullmatch(value["integrated_commit"])
        or not isinstance(paths, list)
        or not paths
    ):
        raise ProjectStateError("protected scope adoption receipt is invalid")
    for entry in paths:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "provenance", "intent_generation"}
            or not _is_normalized_relative_path(entry.get("path"))
            or not _is_hex_identifier(entry.get("provenance"))
            or not isinstance(entry.get("intent_generation"), int)
            or entry["intent_generation"] < 1
        ):
            raise ProjectStateError("protected scope adoption receipt path is invalid")
    if value["digest"] != _digest(value):
        raise ProjectStateError("protected scope adoption receipt digest is invalid")
    return dict(value)


def _validate_project_scope(
    value: Any,
    lane_session: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectStateError("project scope is invalid")
    if value.get("kind") in {"file", "directory", "contract", "resource"} and "owner" in value:
        required = {
            "kind",
            "path",
            "mode",
            "owner",
            "status",
            "sequence",
            "reservation",
            "phase",
        }
        if value.get("status") == "released":
            required.add("release")
        if set(value) != required:
            raise ProjectStateError("project scope lease fields are incomplete or unknown")
        if (
            value.get("kind") not in {"file", "directory", "contract", "resource"}
            or value.get("mode") not in {"hard", "soft"}
            or not _is_normalized_relative_path(value.get("path"))
            or not isinstance(value.get("owner"), str)
            or not _LANE_ID.fullmatch(value["owner"])
            or not isinstance(value.get("sequence"), int)
            or value["sequence"] < 1
            or not isinstance(value.get("reservation"), str)
            or not value["reservation"]
            or len(value["reservation"]) > 256
            or value.get("phase") not in {"planned", "expansion"}
        ):
            raise ProjectStateError("project scope lease is invalid")
        if value["mode"] == "hard":
            if value.get("status") not in {"active", "waiting", "cancelled", "released"}:
                raise ProjectStateError("hard scope lease state is invalid")
            if value["status"] == "released":
                release = value.get("release")
                if (
                    not isinstance(release, dict)
                    or set(release) != {"acceptance_id", "released_generation"}
                    or not _is_hex_identifier(release.get("acceptance_id"))
                    or not isinstance(release.get("released_generation"), int)
                    or release["released_generation"] < 1
                ):
                    raise ProjectStateError("project scope release binding is invalid")
            elif "release" in value:
                raise ProjectStateError("unreleased project scope has release authority")
        elif value.get("status") != "intent":
            raise ProjectStateError("soft scope intent has write authority")
        return dict(value)
    if value.get("kind") != "protected-user-work":
        return validate_scope_state(value)
    base_fields = {"kind", "path", "owner", "adoption", "evidence", "provenance"}
    adoption = value.get("adoption")
    expected_fields = set(base_fields)
    if adoption == "adoption-intent":
        expected_fields.add("adoption_intent")
    elif adoption == "adopted":
        expected_fields.add("adoption_acceptance")
    elif adoption != "protected":
        raise ProjectStateError("protected scope adoption state is invalid")
    if set(value) != expected_fields or not _is_normalized_relative_path(value.get("path")):
        raise ProjectStateError("protected scope fields are incomplete or unknown")
    evidence = value.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
        "common",
        "path",
        "content",
        "index_digest",
        "index_blob_id",
    }:
        raise ProjectStateError("protected scope evidence is invalid")
    _validate_common_identity(evidence.get("common"))
    _validate_protected_content(evidence.get("content"))
    index_blob_id = evidence.get("index_blob_id")
    if (
        evidence.get("path") != value["path"]
        or not _is_hex_identifier(evidence.get("index_digest"))
        or (
            index_blob_id is not None
            and (
                not isinstance(index_blob_id, str)
                or not _GIT_OBJECT.fullmatch(index_blob_id)
            )
        )
        or not _is_hex_identifier(value.get("provenance"))
        or value["provenance"] != hashlib.sha256(_canonical(evidence)).hexdigest()
    ):
        raise ProjectStateError("protected scope evidence binding is invalid")
    if (
        lane_session is None
        or evidence["common"] != lane_session.get("common")
    ):
        raise ProjectStateError("protected scope session binding is invalid")
    if adoption in {"protected", "adoption-intent"} and value.get("owner") is not None:
        raise ProjectStateError("protected scope owner is invalid")
    if adoption == "adoption-intent":
        intent = value.get("adoption_intent")
        if (
            not isinstance(intent, dict)
            or set(intent)
            != {
                "user_action_digest",
                "plan_digest",
                "provenance",
                "intent_generation",
            }
            or not _is_hex_identifier(intent.get("user_action_digest"))
            or not _is_hex_identifier(intent.get("plan_digest"))
            or intent.get("provenance") != value["provenance"]
            or not isinstance(intent.get("intent_generation"), int)
            or intent["intent_generation"] < 1
        ):
            raise ProjectStateError("protected scope adoption intent is invalid")
    if adoption == "adopted":
        acceptance = value.get("adoption_acceptance")
        if (
            value.get("owner") != "integration"
            or not isinstance(acceptance, dict)
            or set(acceptance)
            != {
                "user_action_digest",
                "plan_digest",
                "integrated_commit",
                "integration_receipt_digest",
                "receipt",
            }
            or not _is_hex_identifier(acceptance.get("user_action_digest"))
            or not _is_hex_identifier(acceptance.get("plan_digest"))
            or not isinstance(acceptance.get("integrated_commit"), str)
            or not _GIT_OBJECT.fullmatch(acceptance["integrated_commit"])
            or not _is_hex_identifier(acceptance.get("integration_receipt_digest"))
        ):
            raise ProjectStateError("protected scope adoption acceptance is invalid")
        receipt = _validate_adoption_receipt(acceptance.get("receipt"))
        matching_paths = [
            entry
            for entry in receipt["paths"]
            if entry.get("path") == value["path"]
            and entry.get("provenance") == value["provenance"]
        ]
        if (
            acceptance["integration_receipt_digest"] != receipt["digest"]
            or acceptance["integrated_commit"] != receipt["integrated_commit"]
            or acceptance["user_action_digest"] != receipt["user_action_digest"]
            or acceptance["plan_digest"] != receipt["plan_digest"]
            or len(matching_paths) != 1
            or len({entry["path"].casefold() for entry in receipt["paths"]})
            != len(receipt["paths"])
            or receipt["project_common_digest"]
            != hashlib.sha256(_canonical(evidence["common"])).hexdigest()
            or receipt["integration_ref"] != lane_session.get("integration_ref")
        ):
            raise ProjectStateError("protected scope adoption acceptance binding is invalid")
    return dict(value)


def _validate_lane_scope_uniqueness(
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
) -> None:
    lane_ids = [value["lane_id"] for value in lanes]
    lane_branches = [value["branch"] for value in lanes]
    lane_worktrees = [value["worktree"].casefold() for value in lanes]
    scope_paths = [
        value["path"].casefold()
        for value in scopes
        if value.get("kind") == "protected-user-work"
    ]
    if (
        len(lane_ids) != len(set(lane_ids))
        or len(lane_branches) != len(set(lane_branches))
        or len(lane_worktrees) != len(set(lane_worktrees))
        or len(scope_paths) != len(set(scope_paths))
    ):
        raise ProjectStateError("project lane or scope identities are not unique")
    lane_id_set = set(lane_ids)
    leases = [
        value
        for value in scopes
        if value.get("kind") in {"file", "directory", "contract", "resource"}
        and "owner" in value
    ]
    if any(value["owner"] not in lane_id_set for value in leases):
        raise ProjectStateError("project scope owner lane is absent")
    reservations: dict[str, list[Mapping[str, Any]]] = {}
    for value in leases:
        reservations.setdefault(str(value["reservation"]), []).append(value)
    for reservation in reservations.values():
        ordered = sorted(
            reservation,
            key=lambda item: (
                {"file": 0, "directory": 1, "contract": 2, "resource": 3}[item["kind"]],
                item["path"].casefold(),
                item["path"],
                item["mode"],
            ),
        )
        if list(reservation) != ordered:
            raise ProjectStateError("project scope reservation ordering is invalid")
        keys = [(item["kind"], item["path"].casefold(), item["mode"]) for item in reservation]
        if len(keys) != len(set(keys)):
            raise ProjectStateError("project scope reservation aliases are invalid")
    active = [value for value in leases if value.get("mode") == "hard" and value.get("status") == "active"]
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            if left["owner"] == right["owner"]:
                continue
            left_path, right_path = left["path"].casefold(), right["path"].casefold()
            path_overlap = (
                left_path == right_path
                or left_path.startswith(right_path + "/")
                or right_path.startswith(left_path + "/")
            )
            file_overlap = (
                left["kind"] in {"file", "directory"}
                and right["kind"] in {"file", "directory"}
                and path_overlap
            )
            named_overlap = left["kind"] == right["kind"] and left_path == right_path
            if file_overlap or named_overlap:
                raise ProjectStateError("project active hard scopes overlap")


def _validate_scope_integration_acceptance(
    value: Any,
    *,
    anchor_id: str,
    lane_session: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema") == "project-scope-integration-acceptance-v2":
        return _validate_abandoned_no_change_acceptance(
            value,
            anchor_id=anchor_id,
            lane_session=lane_session,
            lanes=lanes,
            scopes=scopes,
        )
    required = {
        "schema",
        "acceptance_id",
        "anchor_id",
        "lane_id",
        "session",
        "writer",
        "terminal_archive",
        "terminal_release",
        "admitted_commit",
        "accepted_commit",
        "validation",
        "reservations",
        "generation",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-scope-integration-acceptance-v1"
        or not _is_hex_identifier(value.get("acceptance_id"))
        or value.get("anchor_id") != anchor_id
        or not isinstance(value.get("lane_id"), str)
        or not _LANE_ID.fullmatch(value["lane_id"])
        or value.get("session") != lane_session
        or not _is_hex_identifier(value.get("terminal_archive"))
        or not isinstance(value.get("terminal_release"), dict)
        or set(value["terminal_release"])
        != {
            "run_id",
            "archive_digest",
            "handoff_digest",
            "outbox_digest",
            "final_state",
        }
        or value["terminal_release"].get("archive_digest")
        != value.get("terminal_archive")
        or not _is_hex_identifier(
            value["terminal_release"].get("handoff_digest")
        )
        or not _is_hex_identifier(
            value["terminal_release"].get("outbox_digest")
        )
        or value["terminal_release"].get("final_state")
        != "handoff-committed"
        or not _GIT_OBJECT.fullmatch(str(value.get("admitted_commit")))
        or not _GIT_OBJECT.fullmatch(str(value.get("accepted_commit")))
        or not isinstance(value.get("generation"), int)
        or value["generation"] < 1
        or not isinstance(value.get("validation"), dict)
        or set(value["validation"])
        != {
            "result",
            "command",
            "accepted_commit",
            "head_before",
            "tree_before",
            "status_before_digest",
            "head_after",
            "tree_after",
            "status_after_digest",
            "exit_code",
            "stdout_digest",
            "stderr_digest",
            "digest",
        }
        or value["validation"].get("result") != "passed"
        or not isinstance(value["validation"].get("command"), list)
        or not value["validation"]["command"]
        or len(value["validation"]["command"]) > 64
        or any(
            not isinstance(argument, str)
            or not argument
            or "\0" in argument
            or len(argument) > 4096
            for argument in value["validation"]["command"]
        )
        or value["validation"].get("accepted_commit")
        != value.get("accepted_commit")
        or value["validation"].get("head_before")
        != value.get("accepted_commit")
        or value["validation"].get("head_after")
        != value.get("accepted_commit")
        or not _GIT_OBJECT.fullmatch(
            str(value["validation"].get("tree_before"))
        )
        or value["validation"].get("tree_after")
        != value["validation"].get("tree_before")
        or not _is_hex_identifier(
            value["validation"].get("status_before_digest")
        )
        or value["validation"].get("status_after_digest")
        != value["validation"].get("status_before_digest")
        or value["validation"].get("exit_code") != 0
        or not _is_hex_identifier(value["validation"].get("stdout_digest"))
        or not _is_hex_identifier(value["validation"].get("stderr_digest"))
        or not _is_hex_identifier(value["validation"].get("digest"))
        or not isinstance(value.get("reservations"), list)
        or not value["reservations"]
    ):
        raise ProjectStateError("integration acceptance binding is invalid")
    validation = dict(value["validation"])
    validation_digest = validation.pop("digest")
    if validation_digest != hashlib.sha256(_canonical(validation)).hexdigest():
        raise ProjectStateError("integration acceptance validation digest is invalid")
    writer = _validate_writer(value["writer"])
    if value["terminal_release"].get("run_id") != writer["run_id"]:
        raise ProjectStateError("integration acceptance writer binding is invalid")
    reservations: list[dict[str, Any]] = []
    for raw in value["reservations"]:
        if not isinstance(raw, dict) or set(raw) != {
            "kind", "path", "mode", "sequence", "reservation", "phase", "status"
        }:
            raise ProjectStateError("integration acceptance reservation is invalid")
        projected = _scope_reservation_projection(
            {key: raw[key] for key in raw if key != "status"}
        )
        if raw.get("mode") != "hard" or raw.get("status") not in {
            "active",
            "waiting",
            "cancelled",
        }:
            raise ProjectStateError("integration acceptance reservation is invalid")
        reservations.append({**projected, "status": raw["status"]})
    if reservations != sorted(reservations, key=_scope_reservation_order):
        raise ProjectStateError("integration acceptance reservation ordering is invalid")
    if len({(item["kind"], item["path"].casefold(), item["mode"], item["sequence"], item["reservation"], item["phase"]) for item in reservations}) != len(reservations):
        raise ProjectStateError("integration acceptance reservations are ambiguous")
    lane = next((item for item in lanes if item.get("lane_id") == value["lane_id"]), None)
    if (
        not isinstance(lane, Mapping)
        or lane.get("state") != "waiting-for-integration"
        or lane.get("writer") != writer
        or lane.get("terminal_evidence") != value["terminal_archive"]
        or lane.get("base") != value["admitted_commit"]
    ):
        raise ProjectStateError("integration acceptance lane binding is invalid")
    current = [
        {
            key: scope[key]
            for key in ("kind", "path", "mode", "sequence", "reservation", "phase", "status")
        }
        for scope in scopes
        if scope.get("owner") == value["lane_id"]
        and scope.get("kind") in _SCOPE_KIND_ORDER
        and scope.get("mode") == "hard"
        and scope.get("status") in {
            "active",
            "waiting",
            "cancelled",
            "released",
        }
    ]
    current.sort(key=_scope_reservation_order)
    released_current = [
        {
            **item,
            "status": (
                "released"
                if item["status"] == "active"
                else "cancelled"
            ),
        }
        if item["status"] in {"active", "waiting"}
        else item
        for item in reservations
    ]
    if current != reservations and current != released_current:
        raise ProjectStateError("integration acceptance scope binding is stale")
    stable = {key: value[key] for key in value if key != "acceptance_id"}
    if value["acceptance_id"] != hashlib.sha256(_canonical(stable)).hexdigest():
        raise ProjectStateError("integration acceptance digest is invalid")
    return dict(value)


def _validate_abandoned_no_change_acceptance(
    value: Any,
    *,
    anchor_id: str,
    lane_session: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    required = {
        "schema", "kind", "acceptance_id", "anchor_id", "lane_id", "session",
        "writer", "terminal_archive", "admitted_commit", "accepted_commit",
        "validation", "reservations", "no_op_archive", "generation",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-scope-integration-acceptance-v2"
        or value.get("kind") != "abandoned-no-change"
        or not _is_hex_identifier(value.get("acceptance_id"))
        or value.get("anchor_id") != anchor_id
        or not isinstance(value.get("lane_id"), str)
        or not _LANE_ID.fullmatch(value["lane_id"])
        or value.get("session") != lane_session
        or not _is_hex_identifier(value.get("terminal_archive"))
        or not _is_hex_identifier(value.get("no_op_archive"))
        or not _GIT_OBJECT.fullmatch(str(value.get("admitted_commit")))
        or value.get("accepted_commit") != value.get("admitted_commit")
        or not isinstance(value.get("generation"), int)
        or value["generation"] < 1
    ):
        raise ProjectStateError("abandoned no-change acceptance is invalid")
    writer = _validate_writer(value["writer"])
    validation = value.get("validation")
    if (
        not isinstance(validation, dict)
        or set(validation)
        != {
            "result", "command", "accepted_commit", "head_before", "tree_before",
            "status_before_digest", "head_after", "tree_after", "status_after_digest",
            "exit_code", "stdout_digest", "stderr_digest", "digest",
        }
        or validation.get("result") != "passed"
        or validation.get("accepted_commit") != value["accepted_commit"]
        or validation.get("head_before") != value["accepted_commit"]
        or validation.get("head_after") != value["accepted_commit"]
        or validation.get("tree_after") != validation.get("tree_before")
        or validation.get("status_after_digest") != validation.get("status_before_digest")
        or validation.get("exit_code") != 0
        or not _GIT_OBJECT.fullmatch(str(validation.get("tree_before")))
        or not _is_hex_identifier(validation.get("status_before_digest"))
        or not _is_hex_identifier(validation.get("stdout_digest"))
        or not _is_hex_identifier(validation.get("stderr_digest"))
        or not _is_hex_identifier(validation.get("digest"))
    ):
        raise ProjectStateError("abandoned no-change validation is invalid")
    command = _validate_integration_validation_argv(validation.get("command"))
    hashed = {key: item for key, item in validation.items() if key != "digest"}
    if validation["digest"] != hashlib.sha256(_canonical(hashed)).hexdigest():
        raise ProjectStateError("abandoned no-change validation digest is invalid")
    reservations: list[dict[str, Any]] = []
    if not isinstance(value.get("reservations"), list) or not value["reservations"]:
        raise ProjectStateError("abandoned no-change reservations are invalid")
    for raw in value["reservations"]:
        if not isinstance(raw, dict) or set(raw) != {
            "kind", "path", "mode", "sequence", "reservation", "phase", "status"
        }:
            raise ProjectStateError("abandoned no-change reservation is invalid")
        projected = _scope_reservation_projection(
            {key: raw[key] for key in raw if key != "status"},
        )
        if raw.get("mode") != "hard" or raw.get("status") not in {
            "active", "waiting", "cancelled"
        }:
            raise ProjectStateError("abandoned no-change reservation is invalid")
        reservations.append({**projected, "status": raw["status"]})
    if reservations != sorted(reservations, key=_scope_reservation_order):
        raise ProjectStateError("abandoned no-change reservation ordering is invalid")
    lane = next((item for item in lanes if item.get("lane_id") == value["lane_id"]), None)
    safe_stop = lane.get("safe_stop") if isinstance(lane, Mapping) else None
    if (
        not isinstance(lane, Mapping)
        or lane.get("state") != "ready"
        or lane.get("writer") is not None
        or lane.get("base") != value["admitted_commit"]
        or not isinstance(safe_stop, Mapping)
        or safe_stop.get("status") != "completed"
        or safe_stop.get("writer") != writer
        or safe_stop.get("terminal_archive") != value["terminal_archive"]
        or safe_stop.get("completed_state") != "ready"
        or safe_stop.get("preserved_changes") is not False
        or safe_stop.get("recovery_checkpoint_digest") is not None
    ):
        raise ProjectStateError("abandoned no-change lane binding is invalid")
    current = [
        {
            key: scope[key]
            for key in (
                "kind", "path", "mode", "sequence", "reservation", "phase", "status"
            )
        }
        for scope in scopes
        if scope.get("owner") == value["lane_id"]
        and scope.get("kind") in _SCOPE_KIND_ORDER
        and scope.get("mode") == "hard"
        and scope.get("status") in {"active", "waiting", "cancelled", "released"}
    ]
    current.sort(key=_scope_reservation_order)
    released = [
        {
            **item,
            "status": "released" if item["status"] == "active" else (
                "cancelled" if item["status"] == "waiting" else item["status"]
            ),
        }
        for item in reservations
    ]
    if current != reservations and current != released:
        raise ProjectStateError("abandoned no-change reservation binding is stale")
    stable = {key: item for key, item in value.items() if key != "acceptance_id"}
    if value["acceptance_id"] != hashlib.sha256(_canonical(stable)).hexdigest():
        raise ProjectStateError("abandoned no-change acceptance digest is invalid")
    return {
        **value,
        "writer": writer,
        "validation": {**validation, "command": command},
        "reservations": reservations,
    }


_INTEGRATION_INTENT_STATES = frozenset(
    {
        "queued",
        "integrating",
        "candidate",
        "validated",
        "cas-applied",
        "accepted",
        "released",
        "blocked",
        "stale",
        "no-op",
    }
)
_INTEGRATION_QUEUE_CLASSES = frozenset({"ordinary", "dependency-unblocking"})
_INTEGRATION_DIAGNOSTICS = frozenset(
    {
        "cas-race",
        "merge-conflict",
        "validation-failed",
        "identity-drift",
        "integration-blocked",
        "acceptance-failed",
        "ref-ambiguous",
    }
)


def _process_creation_identity(pid: int) -> str | None:
    """Return a kernel creation identity, not a reusable PID-only assertion."""

    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = process.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not process.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            value = (int(creation.dwHighDateTime) << 32) | int(
                creation.dwLowDateTime
            )
            return f"windows-filetime:{value}"
        finally:
            process.CloseHandle(handle)
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError):
        return None
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split() if closing >= 0 else []
    if len(fields) < 20 or not fields[19].isdigit():
        return None
    return f"linux-proc-start:{fields[19]}"


def _current_process_identity() -> str:
    identity = _process_creation_identity(os.getpid())
    if identity is None:
        raise ProjectStateError("integration executor process identity is unavailable")
    return identity


def _process_identity_state(pid: int, expected_identity: str) -> str:
    """Return running/stopped/unknown for one creation-bound process."""

    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid < 1
        or not isinstance(expected_identity, str)
        or not expected_identity
    ):
        return "unknown"
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process = ctypes.WinDLL("kernel32", use_last_error=True)
        process.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        process.OpenProcess.restype = wintypes.HANDLE
        process.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        process.GetProcessTimes.restype = wintypes.BOOL
        process.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        process.GetExitCodeProcess.restype = wintypes.BOOL
        process.CloseHandle.argtypes = [wintypes.HANDLE]
        process.CloseHandle.restype = wintypes.BOOL
        handle = process.OpenProcess(0x1000, False, pid)
        if not handle:
            return (
                "stopped"
                if ctypes.get_last_error() in {87, 1168}
                else "unknown"
            )
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            exit_code = wintypes.DWORD()
            if not process.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ) or not process.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            ):
                return "unknown"
            value = (int(creation.dwHighDateTime) << 32) | int(
                creation.dwLowDateTime
            )
            if f"windows-filetime:{value}" != expected_identity:
                return "stopped"
            return "running" if int(exit_code.value) == 259 else "stopped"
        finally:
            process.CloseHandle(handle)
    observed = _process_creation_identity(pid)
    if observed is None:
        return "stopped" if not Path(f"/proc/{pid}").exists() else "unknown"
    if observed != expected_identity:
        return "stopped"
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return "stopped"
    except (OSError, UnicodeError):
        return "unknown"
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split() if closing >= 0 else []
    if not fields:
        return "unknown"
    return "stopped" if fields[0] in {"X", "Z"} else "running"


def _validate_integration_checkout(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    required = {"path", "identity", "git_dir", "git_dir_identity", "common"}
    if (
        not isinstance(value, dict)
        or set(value) != required
        or not isinstance(value.get("path"), str)
        or not Path(value["path"]).is_absolute()
        or "\0" in value["path"]
        or len(value["path"]) > 4096
        or not isinstance(value.get("git_dir"), str)
        or not Path(value["git_dir"]).is_absolute()
        or "\0" in value["git_dir"]
        or len(value["git_dir"]) > 4096
        or not isinstance(value.get("identity"), list)
        or len(value["identity"]) != 2
        or not all(isinstance(item, int) and item >= 0 for item in value["identity"])
        or not isinstance(value.get("git_dir_identity"), list)
        or len(value["git_dir_identity"]) != 2
        or not all(
            isinstance(item, int) and item >= 0
            for item in value["git_dir_identity"]
        )
    ):
        raise ProjectStateError("integration checkout binding is invalid")
    return {
        **value,
        "common": _validate_common_identity(value.get("common")),
    }


def _validate_integration_executor(
    value: Any,
    *,
    checkout: Mapping[str, Any] | None,
    generation: int,
) -> dict[str, Any] | None:
    if value is None:
        return None
    required = {
        "schema",
        "lease_id",
        "owner",
        "owner_token",
        "pid",
        "process_identity",
        "intent_id",
        "checkout",
        "claimed_generation",
        "renewed_generation",
    }
    if (
        checkout is None
        or not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-integration-executor-v1"
        or not _is_hex_identifier(value.get("lease_id"))
        or not isinstance(value.get("owner"), str)
        or not value["owner"]
        or len(value["owner"]) > 128
        or not _is_hex_identifier(value.get("owner_token"))
        or not isinstance(value.get("pid"), int)
        or isinstance(value.get("pid"), bool)
        or value["pid"] < 1
        or not isinstance(value.get("process_identity"), str)
        or not value["process_identity"]
        or len(value["process_identity"]) > 256
        or not _is_hex_identifier(value.get("intent_id"))
        or value.get("checkout") != checkout
        or not isinstance(value.get("claimed_generation"), int)
        or value["claimed_generation"] < 1
        or not isinstance(value.get("renewed_generation"), int)
        or value["renewed_generation"] < value["claimed_generation"]
        or value["renewed_generation"] > generation
    ):
        raise ProjectStateError("integration executor lease is invalid")
    stable = {
        key: value[key]
        for key in (
            "owner",
            "owner_token",
            "pid",
            "process_identity",
            "intent_id",
            "checkout",
            "claimed_generation",
        )
    }
    if value["lease_id"] != hashlib.sha256(_canonical(stable)).hexdigest():
        raise ProjectStateError("integration executor lease digest is invalid")
    return dict(value)


def _validate_integration_fence(
    value: Any,
    *,
    queue: Sequence[Mapping[str, Any]],
    generation: int,
) -> dict[str, Any] | None:
    if value is None:
        return None
    required = {
        "schema",
        "intent_id",
        "executor_lease_id",
        "admitted_commit",
        "candidate_commit",
        "state",
        "diagnostic",
        "generation",
        "digest",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-integration-ref-fence-v1"
        or not _is_hex_identifier(value.get("intent_id"))
        or not _is_hex_identifier(value.get("executor_lease_id"))
        or not _GIT_OBJECT.fullmatch(str(value.get("admitted_commit")))
        or not _GIT_OBJECT.fullmatch(str(value.get("candidate_commit")))
        or value.get("state") not in {"prepared", "cas-applied", "quarantined"}
        or not isinstance(value.get("generation"), int)
        or value["generation"] < 1
        or value["generation"] > generation
        or not _is_hex_identifier(value.get("digest"))
    ):
        raise ProjectStateError("integration ref fence is invalid")
    diagnostic = value.get("diagnostic")
    if (value["state"] == "quarantined") != isinstance(diagnostic, dict):
        raise ProjectStateError("integration ref fence quarantine is invalid")
    if diagnostic is not None and (
        set(diagnostic) != {"code", "digest"}
        or diagnostic.get("code") not in _INTEGRATION_DIAGNOSTICS
        or not _is_hex_identifier(diagnostic.get("digest"))
    ):
        raise ProjectStateError("integration ref fence diagnostic is invalid")
    intent = next(
        (item for item in queue if item.get("intent_id") == value["intent_id"]),
        None,
    )
    if (
        not isinstance(intent, Mapping)
        or intent.get("candidate_commit") != value["candidate_commit"]
        or intent.get("admitted_tip") != value["admitted_commit"]
        or intent.get("status")
        not in {"validated", "cas-applied", "accepted", "released"}
        or (
            value["state"] in {"cas-applied", "quarantined"}
            and intent.get("status") == "validated"
        )
    ):
        raise ProjectStateError("integration ref fence intent binding is invalid")
    stable = {key: item for key, item in value.items() if key != "digest"}
    if value["digest"] != hashlib.sha256(_canonical(stable)).hexdigest():
        raise ProjectStateError("integration ref fence digest is invalid")
    return dict(value)


def _validate_dependency_binding(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "milestone_revision",
        "specification_revision",
        "allowed_set_digest",
        "read_dependencies",
        "dependency_digest",
        "accepted_base",
        "rebind_generation",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-lane-dependency-v1"
        or not _is_hex_identifier(value.get("milestone_revision"))
        or not isinstance(value.get("specification_revision"), str)
        or not _SPECIFICATION_REVISION.fullmatch(value["specification_revision"])
        or (
            value.get("allowed_set_digest") is not None
            and not _is_hex_identifier(value["allowed_set_digest"])
        )
        or not _GIT_OBJECT.fullmatch(str(value.get("accepted_base")))
        or not isinstance(value.get("rebind_generation"), int)
        or value["rebind_generation"] < 1
    ):
        raise ProjectStateError("lane dependency binding is invalid")
    dependencies = value.get("read_dependencies")
    if not isinstance(dependencies, list):
        raise ProjectStateError("lane dependency binding is invalid")
    parsed = [validate_scope_state(item) for item in dependencies]
    if any(
        item["mode"] != "soft" and item["kind"] != "contract"
        for item in parsed
    ):
        raise ProjectStateError("lane read dependency binding is invalid")
    ordered = sorted(
        parsed,
        key=lambda item: (
            _SCOPE_KIND_ORDER[item["kind"]],
            item["path"].casefold(),
            item["path"],
            item["mode"],
        ),
    )
    if parsed != ordered or len(
        {(item["kind"], item["path"].casefold(), item["mode"]) for item in parsed}
    ) != len(parsed):
        raise ProjectStateError("lane read dependency binding is invalid")
    stable = {
        key: value[key]
        for key in (
            "milestone_revision",
            "specification_revision",
            "read_dependencies",
        )
    }
    if value["dependency_digest"] != hashlib.sha256(
        _canonical(stable)
    ).hexdigest():
        raise ProjectStateError("lane dependency digest is invalid")
    return {**value, "read_dependencies": parsed}


def _validate_version_finalization(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    required = {
        "schema",
        "owner",
        "requested_target",
        "surfaces",
        "surface_digest",
        "payload_digest",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-version-finalization-v1"
        or value.get("owner") != "root"
        or not isinstance(value.get("requested_target"), str)
        or not _VERSION_TARGET.fullmatch(value["requested_target"])
        or not isinstance(value.get("surfaces"), list)
        or value["surfaces"] != list(_VERSION_SURFACES)
        or not _is_hex_identifier(value.get("surface_digest"))
        or not _is_hex_identifier(value.get("payload_digest"))
    ):
        raise ProjectStateError("version finalization binding is invalid")
    stable = {
        "requested_target": value["requested_target"],
        "surfaces": value["surfaces"],
        "payload_digest": value["payload_digest"],
    }
    if value["surface_digest"] != hashlib.sha256(_canonical(stable)).hexdigest():
        raise ProjectStateError("version finalization digest is invalid")
    return dict(value)


def _validate_integration_validation_argv(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 64
        or any(
            not isinstance(argument, str)
            or not argument
            or "\0" in argument
            or len(argument) > 4096
            for argument in value
        )
    ):
        raise ProjectStateError("integration validation command is invalid")
    return list(value)


def _validate_integration_result(
    value: Any,
    *,
    lane_session: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    required = {
        "schema",
        "lane_id",
        "session",
        "writer",
        "terminal_archive",
        "admitted_commit",
        "result_commit",
        "reservations",
        "validation_argv",
        "dependency_binding",
        "dependency_stale",
        "digest",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != "project-integration-result-v1"
        or not isinstance(value.get("lane_id"), str)
        or not _LANE_ID.fullmatch(value["lane_id"])
        or value.get("session") != lane_session
        or not _is_hex_identifier(value.get("terminal_archive"))
        or not _GIT_OBJECT.fullmatch(str(value.get("admitted_commit")))
        or not _GIT_OBJECT.fullmatch(str(value.get("result_commit")))
        or not isinstance(value.get("reservations"), list)
        or not value["reservations"]
        or not _is_hex_identifier(value.get("digest"))
    ):
        raise ProjectStateError("integration result tuple is invalid")
    writer = _validate_writer(value["writer"])
    dependency_binding = _validate_dependency_binding(
        value["dependency_binding"]
    )
    dependency_stale = value["dependency_stale"]
    if dependency_stale is not None and (
        not isinstance(dependency_stale, dict)
        or set(dependency_stale) != {
            "accepted_commit",
            "acceptance_id",
            "generation",
            "dependency_digest",
            "producer_result_digest",
        }
        or not _GIT_OBJECT.fullmatch(
            str(dependency_stale.get("accepted_commit")),
        )
        or not _is_hex_identifier(dependency_stale.get("acceptance_id"))
        or not isinstance(dependency_stale.get("generation"), int)
        or dependency_stale["generation"] < 1
        or not _is_hex_identifier(
            dependency_stale.get("dependency_digest"),
        )
        or not _is_hex_identifier(
            dependency_stale.get("producer_result_digest"),
        )
    ):
        raise ProjectStateError(
            "integration result stale dependency binding is invalid"
        )
    if (
        dependency_binding["allowed_set_digest"]
        != writer["allowed_set_digest"]
        or dependency_binding["accepted_base"] != value["admitted_commit"]
    ):
        raise ProjectStateError("integration result dependency binding is invalid")
    validation_argv = _validate_integration_validation_argv(
        value["validation_argv"],
    )
    reservations: list[dict[str, Any]] = []
    for raw in value["reservations"]:
        if not isinstance(raw, dict) or set(raw) != {
            "kind", "path", "mode", "sequence", "reservation", "phase", "status"
        }:
            raise ProjectStateError("integration result reservation is invalid")
        projected = _scope_reservation_projection(
            {key: raw[key] for key in raw if key != "status"},
        )
        if raw.get("mode") != "hard" or raw.get("status") not in {
            "active", "waiting", "cancelled"
        }:
            raise ProjectStateError("integration result reservation is invalid")
        reservations.append({**projected, "status": raw["status"]})
    if reservations != sorted(reservations, key=_scope_reservation_order):
        raise ProjectStateError("integration result reservation ordering is invalid")
    if len(
        {
            (
                item["kind"], item["path"].casefold(), item["mode"],
                item["sequence"], item["reservation"], item["phase"],
            )
            for item in reservations
        }
    ) != len(reservations):
        raise ProjectStateError("integration result reservations are ambiguous")
    lane = next((item for item in lanes if item.get("lane_id") == value["lane_id"]), None)
    if (
        not isinstance(lane, Mapping)
        or lane.get("state") != "waiting-for-integration"
        or lane.get("writer") != writer
        or lane.get("terminal_evidence") != value["terminal_archive"]
        or lane.get("base") != value["admitted_commit"]
    ):
        raise ProjectStateError("integration result lane binding is invalid")
    current = [
        {
            key: scope[key]
            for key in (
                "kind", "path", "mode", "sequence", "reservation", "phase", "status"
            )
        }
        for scope in scopes
        if scope.get("owner") == value["lane_id"]
        and scope.get("kind") in _SCOPE_KIND_ORDER
        and scope.get("mode") == "hard"
        and scope.get("status") in {"active", "waiting", "cancelled", "released"}
    ]
    current.sort(key=_scope_reservation_order)
    released = [
        {
            **item,
            "status": "released" if item["status"] == "active" else (
                "cancelled" if item["status"] == "waiting" else item["status"]
            ),
        }
        for item in reservations
    ]
    if current != reservations and current != released:
        raise ProjectStateError("integration result reservation binding is stale")
    stale_resolved = (
        isinstance(dependency_stale, Mapping)
        and lane.get("integration_stale") is None
        and current == released
    )
    if lane.get("integration_stale") != dependency_stale and not stale_resolved:
        raise ProjectStateError(
            "integration result stale dependency binding changed"
        )
    stable = {key: item for key, item in value.items() if key != "digest"}
    if value["digest"] != hashlib.sha256(_canonical(stable)).hexdigest():
        raise ProjectStateError("integration result digest is invalid")
    return {
        **value,
        "writer": writer,
        "reservations": reservations,
        "validation_argv": validation_argv,
        "dependency_binding": dependency_binding,
        "dependency_stale": (
            dict(dependency_stale)
            if isinstance(dependency_stale, Mapping)
            else None
        ),
    }


def _validate_integration_queue(
    value: Any,
    *,
    lane_session: Mapping[str, Any] | None,
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
    acceptances: Sequence[Mapping[str, Any]],
    generation: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ProjectStateError("integration queue is invalid")
    if lane_session is None and value:
        raise ProjectStateError("integration queue requires a lane session binding")
    parsed: list[dict[str, Any]] = []
    required = {
        "schema", "intent_id", "enqueue_generation", "status", "result",
        "admitted_tip", "ticket", "candidate_commit", "acceptance_id",
        "release_generation", "diagnostic", "version_finalization",
        "queue_class",
    }
    legacy_required = required - {"queue_class"}
    for raw in value:
        if (
            not isinstance(raw, dict)
            or (set(raw) != required and set(raw) != legacy_required)
            or raw.get("schema") != "project-integration-intent-v1"
            or not _is_hex_identifier(raw.get("intent_id"))
            or not isinstance(raw.get("enqueue_generation"), int)
            or raw["enqueue_generation"] < 1
            or raw["enqueue_generation"] > generation
            or raw.get("status") not in _INTEGRATION_INTENT_STATES
            or not _GIT_OBJECT.fullmatch(str(raw.get("admitted_tip")))
        ):
            raise ProjectStateError("integration intent is invalid")
        legacy = set(raw) == legacy_required
        normalized = {**raw, "queue_class": raw.get("queue_class", "ordinary")}
        if normalized["queue_class"] not in _INTEGRATION_QUEUE_CLASSES:
            raise ProjectStateError("integration intent queue class is invalid")
        assert lane_session is not None
        result = _validate_integration_result(
            normalized["result"],
            lane_session=lane_session,
            lanes=lanes,
            scopes=scopes,
        )
        if normalized["ticket"] is not None and (
            not isinstance(normalized["ticket"], int) or normalized["ticket"] < 1
        ):
            raise ProjectStateError("integration prerelease ticket is invalid")
        if normalized["candidate_commit"] is not None and not _GIT_OBJECT.fullmatch(
            str(normalized["candidate_commit"]),
        ):
            raise ProjectStateError("integration candidate binding is invalid")
        if normalized["acceptance_id"] is not None and not _is_hex_identifier(
            normalized["acceptance_id"],
        ):
            raise ProjectStateError("integration acceptance binding is invalid")
        if normalized["release_generation"] is not None and (
            not isinstance(normalized["release_generation"], int)
            or normalized["release_generation"] < 1
            or normalized["release_generation"] > generation
        ):
            raise ProjectStateError("integration release generation is invalid")
        diagnostic = normalized["diagnostic"]
        version_finalization = _validate_version_finalization(
            normalized["version_finalization"]
        )
        if diagnostic is not None and (
            not isinstance(diagnostic, dict)
            or set(diagnostic) != {"code", "digest"}
            or diagnostic.get("code") not in _INTEGRATION_DIAGNOSTICS
            or not _is_hex_identifier(diagnostic.get("digest"))
        ):
            raise ProjectStateError("integration diagnostic is invalid")
        status = normalized["status"]
        if status == "queued" and any(
            normalized[key] is not None
            for key in (
                "ticket", "candidate_commit", "acceptance_id",
                "release_generation", "diagnostic", "version_finalization",
            )
        ):
            raise ProjectStateError("queued integration intent is not immutable")
        if status in {"integrating", "candidate", "validated", "cas-applied", "accepted", "released"} and normalized["ticket"] is None:
            raise ProjectStateError("integration intent lacks a prerelease ticket")
        if status in {"candidate", "validated", "cas-applied", "accepted", "released"} and normalized["candidate_commit"] is None:
            raise ProjectStateError("integration intent lacks a candidate commit")
        if status in {"accepted", "released"} and normalized["acceptance_id"] is None:
            raise ProjectStateError("integration intent lacks acceptance")
        if status == "released" and normalized["release_generation"] is None:
            raise ProjectStateError("integration intent lacks release evidence")
        if status in {"blocked", "stale"} and diagnostic is None:
            raise ProjectStateError("failed integration intent lacks a diagnostic")
        if status not in {"blocked", "stale"} and diagnostic is not None:
            raise ProjectStateError("successful integration intent has a diagnostic")
        if version_finalization is not None and normalized["ticket"] is None:
            raise ProjectStateError(
                "version finalization lacks an integration-order ticket"
            )
        if normalized["acceptance_id"] is not None and not any(
            item.get("acceptance_id") == normalized["acceptance_id"]
            and item.get("lane_id") == result["lane_id"]
            and item.get("accepted_commit") == normalized["candidate_commit"]
            for item in acceptances
        ):
            raise ProjectStateError("integration intent acceptance is not resident")
        stable = {
            key: normalized[key]
            for key in ("schema", "enqueue_generation", "result", "admitted_tip")
        }
        legacy_digest = hashlib.sha256(_canonical(stable)).hexdigest()
        stable["queue_class"] = normalized["queue_class"]
        current_digest = hashlib.sha256(_canonical(stable)).hexdigest()
        accepted_digests = {current_digest}
        if legacy or normalized["queue_class"] == "ordinary":
            accepted_digests.add(legacy_digest)
        if normalized["intent_id"] not in accepted_digests:
            raise ProjectStateError("integration intent digest is invalid")
        parsed.append(
            {
                **normalized,
                "result": result,
                "version_finalization": version_finalization,
            }
        )
    if parsed != sorted(
        parsed,
        key=lambda item: (item["enqueue_generation"], item["intent_id"]),
    ):
        raise ProjectStateError("integration queue ordering is invalid")
    if len({item["intent_id"] for item in parsed}) != len(parsed):
        raise ProjectStateError("integration intent identities are not unique")
    tickets = [item["ticket"] for item in parsed if item["ticket"] is not None]
    if len(tickets) != len(set(tickets)):
        raise ProjectStateError("integration prerelease tickets are not unique")
    version_targets = [
        item["version_finalization"]["requested_target"]
        for item in parsed
        if isinstance(item.get("version_finalization"), Mapping)
    ]
    if len(version_targets) != len(set(version_targets)):
        raise ProjectStateError("version finalization targets are not unique")
    active = {
        item["result"]["lane_id"]
        for item in parsed
        if item["status"] not in {"released", "blocked", "stale", "no-op"}
    }
    if len(active) != sum(
        1
        for item in parsed
        if item["status"] not in {"released", "blocked", "stale", "no-op"}
    ):
        raise ProjectStateError("lane has more than one live integration intent")
    return parsed


def _runtime_namespace(
    anchor_id: str,
    job_id: str,
    ticket: int,
    kind: str | None = None,
) -> str:
    """Derive an opaque, deterministic namespace without leaking a job label."""

    binding: dict[str, Any] = {
        "anchor": anchor_id,
        "job": job_id,
        "ticket": ticket,
    }
    if kind is not None:
        binding["kind"] = kind
    digest = hashlib.sha256(_canonical(binding)).hexdigest()[:20]
    return f"ob-{kind}-{digest}" if kind is not None else f"ob-{digest}"


def _runtime_namespaces(anchor_id: str, job_id: str, ticket: int) -> dict[str, str]:
    return {
        kind: _runtime_namespace(anchor_id, job_id, ticket, kind)
        for kind in _RUNTIME_NAMESPACE_KINDS
    }


def _validate_runtime(value: Any, *, anchor_id: str) -> dict[str, Any]:
    """Validate the bounded runtime ledger, including completed ticket history."""

    required = {"schema", "capacity", "next_ticket", "jobs", "completed"}
    legacy_required = required - {"completed"}
    if (
        not isinstance(value, dict)
        or (set(value) != required and set(value) != legacy_required)
        or value.get("schema") != "project-runtime-v1"
    ):
        raise ProjectStateError("runtime state is invalid")
    capacity = value.get("capacity")
    next_ticket = value.get("next_ticket")
    jobs = value.get("jobs")
    legacy = set(value) == legacy_required
    if (
        not isinstance(capacity, int) or isinstance(capacity, bool)
        or not 1 <= capacity <= 10
        or not isinstance(next_ticket, int) or isinstance(next_ticket, bool)
        or next_ticket < 1 or not isinstance(jobs, list)
        or (not legacy and not isinstance(value.get("completed"), list))
    ):
        raise ProjectStateError("runtime capacity is invalid")
    raw_jobs = jobs if legacy else [*jobs, *value["completed"]]
    parsed: list[dict[str, Any]] = []
    for raw in raw_jobs:
        legacy_job = isinstance(raw, dict) and set(raw) == {
            "job_id", "ticket", "status", "namespace", "port"
        }
        pre_lane_job = isinstance(raw, dict) and set(raw) == {
            "job_id", "ticket", "status", "namespace", "namespaces", "port"
        }
        expected_fields = {
            "job_id", "lane_id", "ticket", "status", "namespace",
            "namespaces", "port",
        }
        claimed_fields = expected_fields | {"owner_digest"}
        if (
            not isinstance(raw, dict)
            or (
                not legacy_job
                and not pre_lane_job
                and frozenset(raw)
                not in {frozenset(expected_fields), frozenset(claimed_fields)}
            )
        ):
            raise ProjectStateError("runtime job is invalid")
        job_id = raw.get("job_id")
        lane_id = raw.get("lane_id", job_id)
        ticket = raw.get("ticket")
        status = raw.get("status")
        port = raw.get("port")
        owner_digest = raw.get("owner_digest")
        if (
            not isinstance(job_id, str)
            or not _RUNTIME_JOB_ID.fullmatch(job_id)
            or not isinstance(lane_id, str)
            or not _LANE_ID.fullmatch(lane_id)
            or not isinstance(ticket, int) or isinstance(ticket, bool)
            or ticket < 1 or ticket >= next_ticket
            or status not in (
                {"running", "waiting-for-capacity"}
                if legacy_job
                else {"running", "waiting-for-capacity", "complete"}
            )
            or (port is not None and (
                not isinstance(port, int) or isinstance(port, bool)
                or not 1 <= port <= 65535
            ))
            or (
                owner_digest is not None
                and re.fullmatch(r"[0-9a-f]{64}", str(owner_digest)) is None
            )
        ):
            raise ProjectStateError("runtime job is invalid")
        namespace = _runtime_namespace(anchor_id, job_id, ticket)
        namespaces = _runtime_namespaces(anchor_id, job_id, ticket)
        if (
            not _RUNTIME_NAMESPACE.fullmatch(namespace)
            or any(
                not _RUNTIME_NAMESPACE.fullmatch(value)
                for value in namespaces.values()
            )
            or raw.get("namespace") != namespace
            or (
                not legacy_job
                and raw.get("namespaces") != namespaces
            )
        ):
            raise ProjectStateError("runtime namespace binding is invalid")
        parsed.append(
            {
                "job_id": job_id,
                "lane_id": lane_id,
                "ticket": ticket,
                "status": status,
                "namespace": namespace,
                "namespaces": namespaces,
                "port": port,
                "owner_digest": owner_digest,
            }
        )
    if legacy:
        if parsed != sorted(parsed, key=lambda item: item["ticket"]):
            raise ProjectStateError("runtime tickets are not ordered")
    else:
        active_count = len(jobs)
        if (
            parsed[:active_count]
            != sorted(parsed[:active_count], key=lambda item: item["ticket"])
            or parsed[active_count:]
            != sorted(parsed[active_count:], key=lambda item: item["ticket"])
        ):
            raise ProjectStateError("runtime tickets are not ordered")
    ordered = sorted(parsed, key=lambda item: item["ticket"])
    tickets = [item["ticket"] for item in ordered]
    if tickets != list(range(1, next_ticket)):
        raise ProjectStateError("runtime ticket history is invalid")
    if len({item["job_id"] for item in parsed}) != len(parsed) or len(
        {item["namespace"] for item in parsed}
    ) != len(parsed) or len(
        {
            namespace
            for item in parsed
            for namespace in item["namespaces"].values()
        }
    ) != len(parsed) * len(_RUNTIME_NAMESPACE_KINDS):
        raise ProjectStateError("runtime ownership is not unique")
    active_lane_ids = [
        item["lane_id"] for item in ordered if item["status"] != "complete"
    ]
    if len(active_lane_ids) != len(set(active_lane_ids)):
        raise ProjectStateError("runtime lane has more than one active job")
    running = [item for item in ordered if item["status"] == "running"]
    if len(running) > capacity or len(
        [item for item in running if item["port"] is not None]
    ) != len({item["port"] for item in running if item["port"] is not None}):
        raise ProjectStateError("runtime capacity ownership is invalid")
    if not legacy:
        active = [item for item in ordered if item["status"] != "complete"]
        completed = [item for item in ordered if item["status"] == "complete"]
        if (
            any(item.get("status") == "complete" for item in value["jobs"])
            or any(
                item.get("status") != "complete"
                for item in value["completed"]
            )
            or len(value["jobs"]) != len(active)
            or len(value["completed"]) != len(completed)
        ):
            raise ProjectStateError("runtime completion partition is invalid")
    if len(running) < capacity:
        occupied_ports = {
            item["port"] for item in running if item["port"] is not None
        }
        if any(
            item["status"] == "waiting-for-capacity"
            and (item["port"] is None or item["port"] not in occupied_ports)
            for item in ordered
        ):
            raise ProjectStateError("runtime capacity fairness is invalid")
    active = [item for item in ordered if item["status"] != "complete"]
    completed = [item for item in ordered if item["status"] == "complete"]
    return {
        "schema": "project-runtime-v1",
        "capacity": capacity,
        "next_ticket": next_ticket,
        "jobs": active,
        "completed": completed,
    }


def _promote_runtime_jobs(runtime: dict[str, Any]) -> None:
    """Fill bounded capacity with the oldest port-ready durable waiter."""

    jobs = runtime["jobs"]
    while sum(item["status"] == "running" for item in jobs) < runtime["capacity"]:
        occupied_ports = {
            item["port"]
            for item in jobs
            if item["status"] == "running" and item["port"] is not None
        }
        waiter = next(
            (
                item
                for item in jobs
                if item["status"] == "waiting-for-capacity"
                and (item["port"] is None or item["port"] not in occupied_ports)
            ),
            None,
        )
        if waiter is None:
            return
        waiter["status"] = "running"


def _validate_safe_stop_projection(
    lanes: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
    *,
    anchor_id: str,
    lane_session: Mapping[str, Any],
    generation: int,
) -> None:
    for lane in lanes:
        safe_stop = lane.get("safe_stop")
        if safe_stop is None:
            continue
        parsed = _validate_safe_stop(safe_stop)
        if (
            parsed["anchor_id"] != anchor_id
            or parsed["lane_id"] != lane.get("lane_id")
            or parsed["session"] != lane_session
            or parsed["intent_generation"] > generation
            or (
                parsed["status"] in {"stopping", "completed"}
                and parsed["consumed_generation"] > generation
            )
            or (
                parsed["status"] == "completed"
                and parsed["completed_generation"] > generation
            )
        ):
            raise ProjectStateError("lane safe-stop projection is stale")
        current_grants = [
            {
                key: scope[key]
                for key in ("kind", "path", "mode", "sequence", "reservation", "phase")
            }
            for scope in scopes
            if scope.get("owner") == lane.get("lane_id")
            and scope.get("kind") in _SCOPE_KIND_ORDER
            and scope.get("mode") == "hard"
            and scope.get("status") == "active"
        ]
        current_grants.sort(key=_scope_reservation_order)
        if (
            parsed["status"] != "completed"
            and current_grants != parsed["old_hard_grants"]
        ):
            raise ProjectStateError("lane safe-stop hard grant binding changed")
        requested = [
            {"kind": scope["kind"], "path": scope["path"], "mode": scope["mode"]}
            for scope in scopes
            if scope.get("owner") == lane.get("lane_id")
            and scope.get("reservation") == parsed["reservation"]
            and scope.get("phase") == "expansion"
            and scope.get("kind") in _SCOPE_KIND_ORDER
        ]
        requested.sort(
            key=lambda item: (
                _SCOPE_KIND_ORDER[item["kind"]],
                item["path"].casefold(),
                item["path"],
                item["mode"],
            )
        )
        if requested != parsed["requested_scopes"]:
            raise ProjectStateError("lane safe-stop requested scope binding changed")


def _validate_scope_projection_transition(
    current: Sequence[Mapping[str, Any]],
    proposed: Sequence[Mapping[str, Any]],
    *,
    protected_transition: str | None = None,
    scope_release_acceptance_id: str | None = None,
) -> None:
    """Keep an admitted lease until its owning lifecycle can prove release."""

    def identity(value: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            value.get("kind"),
            str(value.get("path", "")).casefold(),
            value.get("mode"),
            value.get("owner"),
            value.get("sequence"),
            value.get("reservation"),
            value.get("phase"),
        )

    proposed_leases = {
        identity(value): value
        for value in proposed
        if value.get("kind") in {"file", "directory", "contract", "resource"}
        and "owner" in value
    }
    allowed_status_transitions = {
        "active": {"active"},
        "waiting": {"waiting", "active", "cancelled"},
        "cancelled": {"cancelled"},
        "intent": {"intent"},
        "released": {"released"},
    }
    if scope_release_acceptance_id is None and any(
        value.get("status") == "released"
        and not any(
            identity(existing) == identity(value)
            and dict(existing) == dict(value)
            and existing.get("status") == "released"
            for existing in current
        )
        for value in proposed
    ):
        raise ProjectStateError("project scope release requires its owning lifecycle")
    for existing in current:
        if existing.get("kind") == "protected-user-work":
            updated = next(
                (
                    value
                    for value in proposed
                    if value.get("kind") == "protected-user-work"
                    and str(value.get("path", "")).casefold()
                    == str(existing.get("path", "")).casefold()
                ),
                None,
            )
            if updated is None:
                raise ProjectStateError(
                    "protected user work requires its owning lifecycle"
                )
            if dict(updated) == dict(existing):
                continue
            stable_fields = ("kind", "path", "evidence", "provenance")
            if any(
                updated.get(field) != existing.get(field)
                for field in stable_fields
            ):
                raise ProjectStateError(
                    "protected user work requires its owning lifecycle"
                )
            transition = (
                existing.get("adoption"),
                updated.get("adoption"),
            )
            if (
                protected_transition == "intent"
                and transition == ("protected", "adoption-intent")
            ):
                if (
                    existing.get("owner") is not None
                    or updated.get("owner") is not None
                ):
                    raise ProjectStateError(
                        "protected user work requires its owning lifecycle"
                    )
                continue
            if (
                protected_transition == "rollback"
                and transition == ("adoption-intent", "protected")
            ):
                if (
                    existing.get("owner") is not None
                    or updated.get("owner") is not None
                ):
                    raise ProjectStateError(
                        "protected user work requires its owning lifecycle"
                    )
                continue
            if (
                protected_transition == "adopt"
                and transition == ("adoption-intent", "adopted")
            ):
                continue
            raise ProjectStateError(
                "purpose-specific protected adoption sink is required"
            )
        if (
            existing.get("kind")
            not in {"file", "directory", "contract", "resource"}
            or "owner" not in existing
        ):
            continue
        updated = proposed_leases.get(identity(existing))
        if updated is None:
            raise ProjectStateError(
                "project scope release requires its owning lifecycle"
            )
        if any(
            updated.get(field) != existing.get(field)
            for field in (
                "kind",
                "path",
                "mode",
                "owner",
                "sequence",
                "reservation",
                "phase",
            )
        ):
            raise ProjectStateError(
                "project scope release requires its owning lifecycle"
            )
        existing_status = existing.get("status")
        if existing_status == "released":
            if dict(updated) != dict(existing):
                raise ProjectStateError(
                    "project scope release requires its owning lifecycle"
                )
            continue
        permitted = allowed_status_transitions.get(
            str(existing_status),
            set(),
        )
        if (
            scope_release_acceptance_id is not None
            and existing_status == "active"
            and updated.get("status") == "released"
            and updated.get("release", {}).get("acceptance_id")
            == scope_release_acceptance_id
        ):
            continue
        if (
            scope_release_acceptance_id is not None
            and existing_status == "released"
            and dict(updated) == dict(existing)
            and updated.get("release", {}).get("acceptance_id")
            == scope_release_acceptance_id
        ):
            continue
        if updated.get("status") not in permitted:
            raise ProjectStateError(
                "project scope release requires its owning lifecycle"
            )


def _verify_protected_adoption_transition(
    project: Path,
    lane_session: Mapping[str, Any],
    current: Sequence[Mapping[str, Any]],
    proposed: Sequence[Mapping[str, Any]],
    integration_receipt: Mapping[str, Any],
) -> None:
    receipt = _validate_adoption_receipt(integration_receipt)
    if (
        receipt["project_common_digest"]
        != hashlib.sha256(_canonical(lane_session["common"])).hexdigest()
        or receipt["integration_ref"] != lane_session["integration_ref"]
    ):
        raise ProjectStateError("protected adoption receipt session drifted")
    integrated_commit = receipt["integrated_commit"]
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", f"{integrated_commit}^{{commit}}"],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    accepted_tip = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            f"{lane_session['integration_ref']}^{{commit}}",
        ],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        commit_id = commit.stdout.decode("ascii").strip()
        tip_id = accepted_tip.stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ProjectStateError("protected adoption Git identity is invalid") from exc
    if (
        commit.returncode != 0
        or accepted_tip.returncode != 0
        or commit_id != integrated_commit
        or tip_id != integrated_commit
    ):
        raise ProjectStateError(
            "adoption commit is not the accepted integration ref tip"
        )

    current_by_path = {
        str(scope["path"]).casefold(): scope
        for scope in current
        if scope.get("kind") == "protected-user-work"
    }
    proposed_by_path = {
        str(scope["path"]).casefold(): scope
        for scope in proposed
        if scope.get("kind") == "protected-user-work"
    }
    receipt_paths = {
        str(entry["path"]).casefold(): entry
        for entry in receipt["paths"]
    }
    changed_paths = {
        path
        for path, existing in current_by_path.items()
        if proposed_by_path.get(path) != existing
    }
    if changed_paths != set(receipt_paths):
        raise ProjectStateError("protected adoption path set changed")
    for path_key in sorted(changed_paths):
        existing = current_by_path[path_key]
        updated = proposed_by_path.get(path_key)
        entry = receipt_paths[path_key]
        intent = existing.get("adoption_intent")
        acceptance = (
            updated.get("adoption_acceptance")
            if isinstance(updated, Mapping)
            else None
        )
        if (
            existing.get("adoption") != "adoption-intent"
            or not isinstance(intent, Mapping)
            or not isinstance(updated, Mapping)
            or updated.get("adoption") != "adopted"
            or updated.get("owner") != "integration"
            or not isinstance(acceptance, Mapping)
            or entry.get("path") != existing.get("path")
            or entry.get("provenance") != existing.get("provenance")
            or entry.get("intent_generation") != intent.get(
                "intent_generation"
            )
            or receipt["user_action_digest"]
            != intent.get("user_action_digest")
            or receipt["plan_digest"] != intent.get("plan_digest")
            or acceptance.get("receipt") != receipt
            or acceptance.get("integration_receipt_digest")
            != receipt["digest"]
            or acceptance.get("integrated_commit") != integrated_commit
            or acceptance.get("user_action_digest")
            != receipt["user_action_digest"]
            or acceptance.get("plan_digest") != receipt["plan_digest"]
        ):
            raise ProjectStateError("protected adoption intent is stale")
        observed = _protected_scope_snapshot(
            project,
            lane_session["common"],
            str(existing["path"]),
        )
        if (
            observed["provenance"] != existing.get("provenance")
            or observed["evidence"] != existing.get("evidence")
        ):
            raise ProjectStateError("protected adoption provenance changed")
        content = existing.get("evidence", {}).get("content")
        if not isinstance(content, Mapping):
            raise ProjectStateError("protected adoption evidence is invalid")
        tree = subprocess.run(
            [
                "git",
                "ls-tree",
                "-z",
                integrated_commit,
                "--",
                str(existing["path"]),
            ],
            cwd=project,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if tree.returncode != 0:
            raise ProjectStateError(
                "integrated commit tree could not be inspected"
            )
        if content.get("kind") == "missing":
            if tree.stdout:
                raise ProjectStateError(
                    "integrated commit retained a protected deletion"
                )
            continue
        try:
            tree_fields = tree.stdout.split(b"\t", 1)[0].split()
            committed_mode = tree_fields[0].decode("ascii")
            committed_blob = tree_fields[2].decode("ascii")
        except (IndexError, UnicodeDecodeError) as exc:
            raise ProjectStateError(
                "integrated commit tree entry is malformed"
            ) from exc
        if (
            committed_mode != content.get("git_mode")
            or committed_blob != content.get("git_blob_id")
        ):
            raise ProjectStateError(
                "integrated commit does not match protected content"
            )
def _validate_lane_projection_transition(
    current: Sequence[Mapping[str, Any]],
    proposed: Sequence[Mapping[str, Any]],
    *,
    stale_acceptance_id: str | None = None,
    dependency_rebind_lane_id: str | None = None,
    stale_resolved_lane_id: str | None = None,
) -> None:
    current_by_id = {str(lane["lane_id"]): lane for lane in current}
    proposed_ids = {str(lane["lane_id"]) for lane in proposed}
    if set(current_by_id) - proposed_ids:
        raise ProjectStateError(
            "lane removal requires its owning lifecycle"
        )
    for lane in proposed:
        existing = current_by_id.get(str(lane["lane_id"]))
        if (
            existing is not None
            and existing.get("scope_schema") is None
            and lane.get("scope_schema") is not None
        ):
            raise ProjectStateError(
                "legacy lane scope migration requires explicit project claims"
            )
        if (
            existing is None
            and lane.get("scope_schema") == "project-scopes-v1"
            and (
                lane.get("state") not in {"creating", "waiting-for-scope"}
                or lane.get("writer") is not None
            )
        ):
            raise ProjectStateError("new typed lane state is invalid")
        if (
            existing is not None
            and existing.get("scope_schema") == "project-scopes-v1"
            and lane.get("scope_enqueue_sequence")
            != existing.get("scope_enqueue_sequence")
        ):
            raise ProjectStateError("lane scope enqueue sequence changed")
        if existing is None:
            continue
        for field in (
            "milestone",
            "scheduler_binding",
            "reader_floor",
            "common",
            "branch",
            "worktree",
        ):
            if lane.get(field) != existing.get(field):
                raise ProjectStateError("lane durable identity changed")
        if (
            lane.get("base") != existing.get("base")
            and (
                dependency_rebind_lane_id != lane.get("lane_id")
                and (
                    existing.get("state") != "waiting-for-scope"
                    or lane.get("state") != "waiting-for-scope"
                    or existing.get("writer") is not None
                    or lane.get("writer") is not None
                )
            )
        ):
            raise ProjectStateError("lane admitted base changed")
        old_dependency = existing.get("dependency_binding")
        new_dependency = lane.get("dependency_binding")
        if old_dependency != new_dependency:
            initial_writer_bind = (
                isinstance(old_dependency, Mapping)
                and isinstance(new_dependency, Mapping)
                and old_dependency.get("allowed_set_digest") is None
                and new_dependency
                == {
                    **old_dependency,
                    "allowed_set_digest": (lane.get("writer") or {}).get(
                        "allowed_set_digest"
                    ),
                }
                and existing.get("writer") is None
                and isinstance(lane.get("writer"), Mapping)
            )
            waiting_base_refresh = (
                isinstance(old_dependency, Mapping)
                and isinstance(new_dependency, Mapping)
                and existing.get("state") == "waiting-for-scope"
                and lane.get("state") == "waiting-for-scope"
                and existing.get("writer") is None
                and lane.get("writer") is None
                and existing.get("base") != lane.get("base")
                and new_dependency
                == {
                    **old_dependency,
                    "accepted_base": lane.get("base"),
                    "rebind_generation": new_dependency.get(
                        "rebind_generation"
                    ),
                }
                and new_dependency.get("rebind_generation", 0)
                > old_dependency.get("rebind_generation", 0)
            )
            completed_writer_detach = (
                isinstance(old_dependency, Mapping)
                and isinstance(new_dependency, Mapping)
                and isinstance(existing.get("writer"), Mapping)
                and lane.get("writer") is None
                and old_dependency.get("allowed_set_digest")
                == existing["writer"].get("allowed_set_digest")
                and new_dependency
                == {
                    **old_dependency,
                    "allowed_set_digest": None,
                }
                and isinstance(existing.get("safe_stop"), Mapping)
                and existing["safe_stop"].get("status") == "stopping"
                and isinstance(lane.get("safe_stop"), Mapping)
                and lane["safe_stop"].get("status") == "completed"
            )
            if (
                dependency_rebind_lane_id != lane.get("lane_id")
                and not initial_writer_bind
                and not waiting_base_refresh
                and not completed_writer_detach
            ):
                raise ProjectStateError(
                    "lane dependency binding requires its owning lifecycle"
                )
        old_stale = existing.get("integration_stale")
        new_stale = lane.get("integration_stale")
        if old_stale != new_stale:
            if (
                old_stale is None
                and isinstance(new_stale, Mapping)
                and stale_acceptance_id is not None
                and new_stale.get("acceptance_id")
                == stale_acceptance_id
            ):
                pass
            elif (
                isinstance(old_stale, Mapping)
                and isinstance(new_stale, Mapping)
                and stale_acceptance_id is not None
                and new_stale.get("acceptance_id")
                == stale_acceptance_id
            ):
                pass
            elif (
                isinstance(old_stale, Mapping)
                and new_stale is None
                and dependency_rebind_lane_id == lane.get("lane_id")
                and lane.get("base") != existing.get("base")
            ):
                pass
            elif (
                isinstance(old_stale, Mapping)
                and new_stale is None
                and stale_resolved_lane_id == lane.get("lane_id")
            ):
                pass
            else:
                raise ProjectStateError("lane integration stale marker changed")
        if (
            isinstance(existing.get("writer"), Mapping)
            and isinstance(lane.get("writer"), Mapping)
            and lane.get("writer") != existing.get("writer")
        ):
            raise ProjectStateError("lane writer binding changed")


def _validate_safe_stop_transition(
    current: Sequence[Mapping[str, Any]],
    proposed: Sequence[Mapping[str, Any]],
    *,
    transition: str | None,
    intent_id: str | None,
    expected_generation: int,
) -> None:
    current_by_id = {str(lane["lane_id"]): lane for lane in current}
    proposed_by_id = {str(lane["lane_id"]): lane for lane in proposed}
    changed = [
        lane_id
        for lane_id, before in current_by_id.items()
        if before.get("safe_stop") != proposed_by_id.get(lane_id, {}).get("safe_stop")
    ]
    if transition is None:
        if changed:
            raise ProjectStateError("lane safe-stop requires its owning lifecycle")
        return
    if len(changed) != 1 or intent_id is None:
        raise ProjectStateError("lane safe-stop transition is ambiguous")
    before = current_by_id[changed[0]]
    after = proposed_by_id[changed[0]]
    old = before.get("safe_stop")
    new = after.get("safe_stop")
    if transition == "request":
        if (
            (
                old is not None
                and (
                    not isinstance(old, Mapping)
                    or old.get("status") != "completed"
                )
            )
            or before.get("state") != "running"
            or before.get("writer") is None
            or not isinstance(new, Mapping)
            or new.get("status") != "requested"
            or new.get("intent_id") != intent_id
            or new.get("intent_generation") != expected_generation + 1
            or after.get("writer") != before.get("writer")
            or after.get("state") != "running"
        ):
            raise ProjectStateError("lane safe-stop request is invalid")
        return
    if transition == "consume":
        if (
            not isinstance(old, Mapping)
            or not isinstance(new, Mapping)
            or old.get("intent_id") != intent_id
            or new.get("intent_id") != intent_id
            or old.get("status") != "requested"
            or new.get("status") != "stopping"
            or new.get("consumed_generation") != expected_generation + 1
            or {key: value for key, value in new.items() if key not in {"status", "consumed_generation"}}
            != {key: value for key, value in old.items() if key != "status"}
            or after.get("writer") != before.get("writer")
            or after.get("state") != "running"
        ):
            raise ProjectStateError("lane safe-stop consumption is invalid")
        return
    if transition == "complete":
        if (
            not isinstance(old, Mapping)
            or not isinstance(new, Mapping)
            or old.get("intent_id") != intent_id
            or old.get("status") != "stopping"
            or new.get("intent_id") != intent_id
            or new.get("status") != "completed"
            or {
                key: value
                for key, value in new.items()
                if key
                not in {
                    "status",
                    "completed_generation",
                    "completed_state",
                    "terminal_archive",
                    "recovery_checkpoint_digest",
                    "preserved_changes",
                }
            }
            != {
                key: value
                for key, value in old.items()
                if key != "status"
            }
            or new.get("completed_generation") != expected_generation + 1
            or new.get("completed_state") != after.get("state")
            or before.get("state") != "running"
            or before.get("writer") is None
            or after.get("writer") is not None
            or after.get("state") not in {"ready", "recovery-ready"}
        ):
            raise ProjectStateError("lane safe-stop completion is invalid")
        return
    raise ProjectStateError("lane safe-stop transition is invalid")


def _verify_scope_integration_ref(
    project: Path,
    lane_session: Mapping[str, Any],
    *,
    admitted_commit: str,
    accepted_commit: str,
) -> None:
    commands = (
        ("rev-parse", "--verify", f"{admitted_commit}^{{commit}}"),
        ("rev-parse", "--verify", f"{accepted_commit}^{{commit}}"),
        ("rev-parse", "--verify", f"{lane_session['integration_ref']}^{{commit}}"),
    )
    observed: list[str] = []
    for command in commands:
        result = subprocess.run(
            ["git", *command],
            cwd=project,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        try:
            resolved = result.stdout.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ProjectStateError("integration acceptance Git identity is invalid") from exc
        if result.returncode != 0 or not _GIT_OBJECT.fullmatch(resolved):
            raise ProjectStateError("integration acceptance commit is unavailable")
        observed.append(resolved)
    if observed[0] != admitted_commit or observed[1] != accepted_commit or observed[2] != accepted_commit:
        raise ProjectStateError("integration acceptance ref binding is stale")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", admitted_commit, accepted_commit],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ProjectStateError("integration acceptance does not contain the admitted commit")


class ProjectStateStore:
    def __init__(self, project: Path, *, coordinator_root: Path | None = None, fault: str | None = None) -> None:
        self.project = _absolute_no_follow(project)
        _assert_no_link_or_reparse_ancestors(self.project)
        try:
            project_metadata = self.project.lstat()
        except OSError as exc:
            raise ProjectStateError("project must be a directory") from exc
        if _is_link_or_reparse(project_metadata) or not stat.S_ISDIR(project_metadata.st_mode):
            raise ProjectStateError("project must be a real directory")
        self.project_id = hashlib.sha256(str(self.project).encode("utf-8")).hexdigest()
        self.root = _absolute_no_follow(coordinator_root or (self.project.parent / ".openbuild-project-state"))
        _assert_no_link_or_reparse_ancestors(self.root)
        self.i0_path = self.root / "i0.json"
        self.lock_path = self.root / "coordinator.lock"
        self.fault = fault

    @property
    def _anchors_directory(self) -> Path:
        return self.root / "anchors"

    @property
    def _capabilities_directory(self) -> Path:
        return self.root / "capabilities"

    @property
    def _capability_index_directory(self) -> Path:
        return self.root / "capability-index"

    @property
    def _states_directory(self) -> Path:
        return self.root / "states"

    def _setup(self) -> dict[str, Any]:
        setup = _read_json(self.i0_path)
        required = {"schema", "kind", "key", "key_id", "digest"}
        if set(setup) != required or setup.get("schema") != SCHEMA_VERSION or setup.get("kind") != "I0":
            raise ProjectStateError("coordinator setup is tampered")
        key = setup.get("key")
        if not isinstance(key, str) or not _is_hex_identifier(key):
            raise ProjectStateError("coordinator key is tampered")
        try:
            expected_key_id = hashlib.sha256(bytes.fromhex(key)).hexdigest()
        except ValueError as exc:
            raise ProjectStateError("coordinator key is tampered") from exc
        if setup.get("key_id") != expected_key_id:
            raise ProjectStateError("coordinator key is tampered")
        return setup

    def _ensure_setup_locked(self) -> dict[str, Any]:
        if not self.i0_path.exists():
            key = secrets.token_hex(32)
            _write_exclusive_json(self.i0_path, {"schema": SCHEMA_VERSION, "kind": "I0", "key": key, "key_id": hashlib.sha256(bytes.fromhex(key)).hexdigest()})
        return self._setup()

    def ensure_setup(self) -> dict[str, str]:
        _ensure_private_directory(self.root)
        with _locked(self.lock_path):
            setup = self._ensure_setup_locked()
            return {"status": "setup-ready", "key_id": str(setup["key_id"])}

    def _capability_index_path(self, plan_id: str, attempt_id: str) -> Path:
        binding = _canonical({"project_id": self.project_id, "plan_id": plan_id, "attempt_id": attempt_id})
        return self._capability_index_directory / f"{hashlib.sha256(binding).hexdigest()}.json"

    def _capability_path(self, capability_id: str) -> Path:
        if not _is_hex_identifier(capability_id):
            raise ProjectStateError("bootstrap capability handle is invalid")
        return self._capabilities_directory / f"{capability_id}.json"

    def _sink_plan_digest(self, *, plan_id: str, attempt_id: str, anchor_id: str, lock_id: str, expected_absence: bool) -> str:
        return hashlib.sha256(
            _canonical(
                {
                    "project_id": self.project_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "anchor_id": anchor_id,
                    "lock_id": lock_id,
                    "expected_absence": expected_absence,
                    "immutable_sinks": ["anchor.lock", "manifest.json"],
                }
            )
        ).hexdigest()

    def issue_bootstrap_capability(self, plan_id: str, attempt_id: str, *, expected_absence: bool = True) -> dict[str, str]:
        """Issue exactly one opaque BA0 capability for a project/plan/attempt tuple."""
        plan_id = _require_binding(plan_id, "plan")
        attempt_id = _require_binding(attempt_id, "attempt")
        if expected_absence is not True:
            raise ProjectStateError("BA0 requires an expected-absence sink plan")
        _ensure_private_directory(self.root)
        with _locked(self.lock_path):
            setup = self._ensure_setup_locked()
            index_path = self._capability_index_path(plan_id, attempt_id)
            if index_path.exists():
                raise ProjectStateError("bootstrap capability was already issued for this plan and attempt")
            capability_id = secrets.token_hex(32)
            token = secrets.token_hex(32)
            anchor_id = hashlib.sha256(
                _canonical({"project_id": self.project_id, "plan_id": plan_id, "attempt_id": attempt_id})
            ).hexdigest()
            lock_id = secrets.token_hex(32)
            outcome = {"anchor_id": anchor_id, "lock_id": lock_id}
            sink_plan_digest = self._sink_plan_digest(
                plan_id=plan_id,
                attempt_id=attempt_id,
                anchor_id=anchor_id,
                lock_id=lock_id,
                expected_absence=True,
            )
            record = {
                "schema": SCHEMA_VERSION,
                "kind": "BA0-capability",
                "capability_id": capability_id,
                "token_digest": hashlib.sha256(token.encode("ascii")).hexdigest(),
                "project_id": self.project_id,
                "plan_id": plan_id,
                "attempt_id": attempt_id,
                "expected_absence": True,
                "sink_plan_digest": sink_plan_digest,
                "key_id": setup["key_id"],
                "outcome": outcome,
                "cursor": "issued",
            }
            _write_exclusive_json(self._capability_path(capability_id), record)
            _write_exclusive_json(
                index_path,
                {
                    "schema": SCHEMA_VERSION,
                    "kind": "BA0-capability-index",
                    "project_id": self.project_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "capability_id": capability_id,
                },
            )
            return {
                "status": "issued",
                "bootstrap_capability": f"{capability_id}.{token}",
                "sink_plan_digest": sink_plan_digest,
            }

    def _parse_capability(self, capability: str) -> tuple[str, str]:
        if not isinstance(capability, str) or capability.count(".") != 1:
            raise ProjectStateError("bootstrap capability is malformed")
        capability_id, token = capability.split(".", 1)
        if not _is_hex_identifier(capability_id) or not _is_hex_identifier(token):
            raise ProjectStateError("bootstrap capability is malformed")
        return capability_id, token

    def _capability_record(self, capability: str, plan_id: str, attempt_id: str) -> tuple[Path, dict[str, Any]]:
        capability_id, token = self._parse_capability(capability)
        record = _read_json(self._capability_path(capability_id))
        required = {
            "schema", "kind", "capability_id", "token_digest", "project_id", "plan_id", "attempt_id",
            "expected_absence", "sink_plan_digest", "key_id", "outcome", "cursor", "digest",
        }
        if set(record) != required or record.get("schema") != SCHEMA_VERSION or record.get("kind") != "BA0-capability":
            raise ProjectStateError("bootstrap capability record is tampered")
        if (
            record.get("capability_id") != capability_id
            or record.get("project_id") != self.project_id
            or record.get("plan_id") != plan_id
            or record.get("attempt_id") != attempt_id
            or record.get("expected_absence") is not True
            or not hmac.compare_digest(str(record.get("token_digest")), hashlib.sha256(token.encode("ascii")).hexdigest())
        ):
            raise ProjectStateError("bootstrap capability is not bound to this project, plan, and attempt")
        outcome = record.get("outcome")
        if not isinstance(outcome, dict) or set(outcome) != {"anchor_id", "lock_id"} or not all(_is_hex_identifier(outcome.get(field)) for field in outcome):
            raise ProjectStateError("bootstrap capability outcome is tampered")
        expected_digest = self._sink_plan_digest(
            plan_id=plan_id,
            attempt_id=attempt_id,
            anchor_id=outcome["anchor_id"],
            lock_id=outcome["lock_id"],
            expected_absence=True,
        )
        if record.get("sink_plan_digest") != expected_digest or record.get("cursor") not in {"issued", "consumed", "published"}:
            raise ProjectStateError("bootstrap capability sink plan is tampered")
        return self._capability_path(capability_id), record

    def anchor_path(self, anchor_id: str) -> Path:
        if not _is_hex_identifier(anchor_id):
            raise ProjectStateError("anchor ID is invalid")
        return self._anchors_directory / anchor_id

    def _state_path(self, anchor_id: str) -> Path:
        if not _is_hex_identifier(anchor_id):
            raise ProjectStateError("anchor ID is invalid")
        return self._states_directory / f"{anchor_id}.json"

    def _anchor_state_lock_path(self, anchor_id: str) -> Path:
        return self.anchor_path(anchor_id) / "state.lock"

    def _anchor_manifest(self, record: Mapping[str, Any]) -> dict[str, Any]:
        outcome = record["outcome"]
        assert isinstance(outcome, Mapping)
        return {
            "schema": SCHEMA_VERSION,
            "kind": "BA0",
            "project_id": self.project_id,
            "plan_id": record["plan_id"],
            "attempt_id": record["attempt_id"],
            "key_id": record["key_id"],
            "anchor_id": outcome["anchor_id"],
            "lock_id": outcome["lock_id"],
            "sink_plan_digest": record["sink_plan_digest"],
        }

    def _validate_anchor_directory(self, record: Mapping[str, Any], *, expected_identity: tuple[int, int] | None = None) -> dict[str, str]:
        outcome = record["outcome"]
        assert isinstance(outcome, Mapping)
        path = self.anchor_path(str(outcome["anchor_id"]))
        metadata = _validate_private_directory(path, protect=False)
        if expected_identity is not None and _identity(metadata) != expected_identity:
            raise ProjectStateError("published anchor directory identity changed")
        manifest = _read_json(path / "manifest.json")
        expected_manifest = self._anchor_manifest(record)
        if {key: value for key, value in manifest.items() if key != "digest"} != expected_manifest:
            raise ProjectStateError("anchor publication winner does not match the consumed sink plan")
        lock = _read_json(path / "anchor.lock")
        expected_lock = {
            "schema": SCHEMA_VERSION,
            "kind": "BA0-lock",
            "anchor_id": outcome["anchor_id"],
            "lock_id": outcome["lock_id"],
            "manifest_digest": _digest(manifest),
        }
        if {key: value for key, value in lock.items() if key != "digest"} != expected_lock:
            raise ProjectStateError("published anchor lock identity changed")
        return {"anchor_id": str(outcome["anchor_id"]), "lock_id": str(outcome["lock_id"])}

    def _build_anchor_temp(self, record: Mapping[str, Any]) -> tuple[Path, tuple[int, int]]:
        _ensure_private_directory(self._anchors_directory)
        capability_id = str(record["capability_id"])
        temp = self._anchors_directory / f".ba0-{capability_id[:16]}-{secrets.token_hex(8)}"
        _ensure_private_directory(temp)
        manifest = self._anchor_manifest(record)
        _write_exclusive_json(
            temp / "anchor.lock",
            {
                "schema": SCHEMA_VERSION,
                "kind": "BA0-lock",
                "anchor_id": manifest["anchor_id"],
                "lock_id": manifest["lock_id"],
                "manifest_digest": _digest(manifest),
            },
        )
        _write_exclusive_json(temp / "manifest.json", manifest)
        _sync_parent_metadata(temp)
        return temp, _identity(temp.lstat())

    def _materialize_anchor_locked(self, record: Mapping[str, Any]) -> dict[str, str]:
        outcome = record["outcome"]
        assert isinstance(outcome, Mapping)
        target = self.anchor_path(str(outcome["anchor_id"]))
        if target.exists():
            return self._validate_anchor_directory(record)
        temp, temp_identity = self._build_anchor_temp(record)
        if self.fault == "after-anchor-temp-sync":
            raise ProjectStateError("injected fault after anchor temp sync")
        try:
            _publish_directory_no_replace(temp, target)
        except FileExistsError:
            return self._validate_anchor_directory(record)
        _sync_parent_metadata(target.parent)
        result = self._validate_anchor_directory(record, expected_identity=temp_identity)
        if self.fault == "after-anchor-publish":
            raise ProjectStateError("injected fault after anchor publish")
        return result

    def _mark_published(self, path: Path, record: dict[str, Any]) -> None:
        if record["cursor"] != "published":
            record["cursor"] = "published"
            _replace_json(path, record)

    def create_anchor(self, capability: str, plan_id: str, attempt_id: str) -> dict[str, str]:
        """Consume a fresh capability.  A normal replay is rejected before BA0."""
        plan_id = _require_binding(plan_id, "plan")
        attempt_id = _require_binding(attempt_id, "attempt")
        with _locked(self.lock_path):
            path, record = self._capability_record(capability, plan_id, attempt_id)
            if record["cursor"] != "issued":
                raise ProjectStateError("bootstrap capability was already consumed")
            target = self.anchor_path(str(record["outcome"]["anchor_id"]))
            if target.exists():
                raise ProjectStateError("expected-absent BA0 anchor already exists")
            record["cursor"] = "consumed"
            _replace_json(path, record)
            if self.fault == "after-capability-consume":
                raise ProjectStateError("injected fault after capability consume")
            result = self._materialize_anchor_locked(record)
            self._mark_published(path, record)
            return result

    def resume_anchor(self, capability: str, plan_id: str, attempt_id: str) -> dict[str, str]:
        """Recover a consumed BA0 cursor without issuing or consuming another token."""
        plan_id = _require_binding(plan_id, "plan")
        attempt_id = _require_binding(attempt_id, "attempt")
        with _locked(self.lock_path):
            path, record = self._capability_record(capability, plan_id, attempt_id)
            if record["cursor"] == "issued":
                raise ProjectStateError("bootstrap capability has not been consumed")
            result = self._materialize_anchor_locked(record)
            self._mark_published(path, record)
            return result

    def _manifest(self, anchor_id: str) -> dict[str, Any]:
        path = self.anchor_path(anchor_id)
        # Anchor reads are tied to the durable capability record by its fixed outcome.
        manifest = _read_json(path / "manifest.json")
        required = {
            "schema", "kind", "project_id", "plan_id", "attempt_id", "key_id", "anchor_id", "lock_id", "sink_plan_digest", "digest",
        }
        if set(manifest) != required or manifest.get("schema") != SCHEMA_VERSION or manifest.get("kind") != "BA0" or manifest.get("project_id") != self.project_id or manifest.get("anchor_id") != anchor_id:
            raise ProjectStateError("anchor manifest is invalid")
        lock = _read_json(path / "anchor.lock")
        required_lock = {"schema", "kind", "anchor_id", "lock_id", "manifest_digest", "digest"}
        if set(lock) != required_lock or lock.get("schema") != SCHEMA_VERSION or lock.get("kind") != "BA0-lock" or lock.get("anchor_id") != anchor_id or lock.get("lock_id") != manifest.get("lock_id") or lock.get("manifest_digest") != _digest(manifest):
            raise ProjectStateError("anchor lock identity changed")
        return manifest

    def bootstrap(self, anchor_id: str, verdict: str) -> dict[str, Any]:
        if verdict not in {"clean", "breach", "indeterminate"}:
            raise ProjectStateError("bootstrap verdict is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            state_path = self._state_path(anchor_id)
            if state_path.exists():
                return self._read_state_strict(anchor_id)
            state = {
                "schema": SCHEMA_VERSION,
                "generation": 0,
                "epoch": 0,
                "state": "clean" if verdict == "clean" else "breach",
                "registry": "B0" if verdict == "clean" else None,
                "incident_id": None if verdict == "clean" else secrets.token_hex(32),
                "lane_session": None,
                "lanes": [],
                "milestones": [],
                "scopes": [],
                "integration_acceptances": [],
                "integration_queue": [],
                "integration_next_ticket": 1,
                "integration_checkout": None,
                "integration_executor": None,
                "integration_fence": None,
                "runtime": {
                    "schema": "project-runtime-v1",
                    "capacity": 2,
                    "next_ticket": 1,
                    "jobs": [],
                    "completed": [],
                },
            }
            _write_exclusive_json(state_path, state)
            return self._read_state_strict(anchor_id)

    def _read_state_strict(self, anchor_id: str) -> dict[str, Any]:
        self._manifest(anchor_id)
        state = _read_json(self._state_path(anchor_id))
        required = {"schema", "generation", "epoch", "state", "registry", "incident_id", "lane_session", "lanes", "milestones", "scopes", "integration_acceptances", "digest"}
        integration_required = required | {
            "integration_queue",
            "integration_next_ticket",
            "integration_checkout",
            "integration_executor",
            "integration_fence",
        }
        runtime_required = integration_required | {"runtime"}
        runtime_preintegration_required = required | {"runtime"}
        pre_executor_required = required | {
            "integration_queue",
            "integration_next_ticket",
        }
        legacy_required = required - {"lane_session", "integration_acceptances"}
        pre_acceptance_required = required - {"integration_acceptances"}
        legacy = set(state) == legacy_required
        if legacy:
            if (
                state.get("generation") != 0
                or any(state.get(key) != [] for key in ("lanes", "milestones", "scopes"))
            ):
                raise ProjectStateError("legacy project state schema is invalid")
            state = dict(state)
            state["lane_session"] = None
            state["integration_acceptances"] = []
        elif set(state) == pre_acceptance_required:
            state = dict(state)
            state["integration_acceptances"] = []
        if set(state) == required:
            state = dict(state)
            state["integration_queue"] = []
            state["integration_next_ticket"] = 1
            state["integration_checkout"] = None
            state["integration_executor"] = None
            state["integration_fence"] = None
        elif set(state) == runtime_preintegration_required:
            state = dict(state)
            state["integration_queue"] = []
            state["integration_next_ticket"] = 1
            state["integration_checkout"] = None
            state["integration_executor"] = None
            state["integration_fence"] = None
        elif set(state) == pre_executor_required:
            state = dict(state)
            state["integration_checkout"] = None
            state["integration_executor"] = None
            state["integration_fence"] = None
        if set(state) == integration_required:
            state = dict(state)
            state["runtime"] = {
                "schema": "project-runtime-v1",
                "capacity": 2,
                "next_ticket": 1,
                "jobs": [],
                "completed": [],
            }
        if set(state) != runtime_required or state.get("schema") != SCHEMA_VERSION or not isinstance(state.get("generation"), int) or state["generation"] < 0 or state.get("epoch") != 0 or state.get("state") not in {"clean", "breach"}:
            raise ProjectStateError("project state schema is invalid")
        if (state["state"] == "clean") != (state["registry"] == "B0") or (state["state"] == "breach") != (isinstance(state["incident_id"], str) and state["registry"] is None):
            raise ProjectStateError("clean/breach state split is invalid")
        if not all(isinstance(state[key], list) for key in ("lanes", "milestones", "scopes", "integration_acceptances")) or not isinstance(state.get("integration_next_ticket"), int) or state["integration_next_ticket"] < 1:
            raise ProjectStateError("project state collections are invalid")
        validated_milestones = [_validate_milestone_projection(value) for value in state["milestones"]]
        _validate_milestone_dag(validated_milestones)
        lane_session = _validate_lane_session(state["lane_session"])
        validated_lanes = [_validate_lane_projection(value) for value in state["lanes"]]
        validated_scopes = [
            _validate_project_scope(value, lane_session)
            for value in state["scopes"]
        ]
        _validate_milestone_lane_projection(
            validated_milestones,
            validated_lanes,
            validated_scopes,
        )
        if lane_session is None and validated_lanes:
            raise ProjectStateError("project lanes require a lane session binding")
        if lane_session is not None and any(
            lane["common"] != lane_session["common"]
            for lane in validated_lanes
        ):
            raise ProjectStateError("project lane session identity drifted")
        _validate_lane_scope_uniqueness(validated_lanes, validated_scopes)
        _validate_safe_stop_projection(
            validated_lanes,
            validated_scopes,
            anchor_id=anchor_id,
            lane_session=lane_session,
            generation=state["generation"],
        ) if lane_session is not None else None
        validated_acceptances = [
            _validate_scope_integration_acceptance(
                value,
                anchor_id=anchor_id,
                lane_session=lane_session,
                lanes=validated_lanes,
                scopes=validated_scopes,
            )
            for value in state["integration_acceptances"]
        ] if lane_session is not None else []
        if lane_session is None and state["integration_acceptances"]:
            raise ProjectStateError("integration acceptance requires a lane session binding")
        if len({item["acceptance_id"] for item in validated_acceptances}) != len(validated_acceptances):
            raise ProjectStateError("integration acceptance identities are not unique")
        state["integration_queue"] = _validate_integration_queue(
            state["integration_queue"],
            lane_session=lane_session,
            lanes=validated_lanes,
            scopes=validated_scopes,
            acceptances=validated_acceptances,
            generation=state["generation"],
        )
        integration_checkout = _validate_integration_checkout(
            state["integration_checkout"]
        )
        if (
            integration_checkout is not None
            and lane_session is not None
            and integration_checkout["common"] != lane_session["common"]
        ):
            raise ProjectStateError(
                "integration checkout common-directory binding drifted"
            )
        state["integration_checkout"] = integration_checkout
        state["integration_executor"] = _validate_integration_executor(
            state["integration_executor"],
            checkout=integration_checkout,
            generation=state["generation"],
        )
        state["integration_fence"] = _validate_integration_fence(
            state["integration_fence"],
            queue=state["integration_queue"],
            generation=state["generation"],
        )
        state["runtime"] = _validate_runtime(
            state["runtime"], anchor_id=anchor_id
        )
        if state["integration_fence"] is not None:
            fence_intent = state["integration_fence"]["intent_id"]
            executor = state["integration_executor"]
            if (
                executor is not None
                and executor["intent_id"] != fence_intent
            ):
                raise ProjectStateError(
                    "integration executor and ref fence disagree"
                )
        issued = [
            item["ticket"]
            for item in state["integration_queue"]
            if isinstance(item.get("ticket"), int)
        ]
        if len(issued) != len(set(issued)):
            raise ProjectStateError(
                "integration prerelease tickets are not unique"
            )
        if issued and state["integration_next_ticket"] <= max(issued):
            raise ProjectStateError("integration prerelease ticket regressed")
        state["milestones"] = validated_milestones
        return {key: value for key, value in state.items() if key != "digest"}

    def bind_lane_session(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        common: Mapping[str, Any],
        integration_ref: str,
        recovery_root: Path,
    ) -> dict[str, Any]:
        if not isinstance(expected_generation, int) or expected_generation < 0:
            raise ProjectStateError("expected project generation is invalid")
        recovery_root = _absolute_no_follow(Path(recovery_root))
        _assert_no_link_or_reparse_ancestors(recovery_root.parent)
        binding = _validate_lane_session(
            {
                "common": dict(common),
                "integration_ref": integration_ref,
                "reader_floor": "2.3.6",
                "recovery_root": str(recovery_root),
            }
        )
        assert binding is not None
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                if state["state"] != "clean":
                    raise ProjectStateError("breached project state cannot bind a lane session")
                if state["lane_session"] is not None:
                    existing = _validate_lane_session(
                        state["lane_session"]
                    )
                    assert existing is not None
                    legacy = {
                        key: binding[key]
                        for key in (
                            "common",
                            "integration_ref",
                            "reader_floor",
                        )
                    }
                    if (
                        existing == legacy
                        and not state["integration_acceptances"]
                    ):
                        state["generation"] += 1
                        state["lane_session"] = binding
                        _replace_json(
                            self._state_path(anchor_id),
                            state,
                        )
                        return self._read_state_strict(anchor_id)
                    if existing != binding:
                        raise ProjectStateError("lane session integration binding changed")
                    return state
                state["generation"] += 1
                state["lane_session"] = binding
                _replace_json(self._state_path(anchor_id), state)
                return self._read_state_strict(anchor_id)

    def bind_integration_checkout(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        checkout: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind the sole detached managed checkout before executor admission."""

        parsed = _validate_integration_checkout(dict(checkout))
        assert parsed is not None
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                session = _validate_lane_session(state["lane_session"])
                if (
                    state["state"] != "clean"
                    or session is None
                    or parsed["common"] != session["common"]
                ):
                    raise ProjectStateError(
                        "integration checkout session binding is invalid"
                    )
                existing = state["integration_checkout"]
                if existing is not None:
                    if existing != parsed:
                        raise ProjectStateError(
                            "integration checkout identity changed"
                        )
                    return state
                if (
                    state["integration_executor"] is not None
                    or state["integration_fence"] is not None
                    or state["integration_queue"]
                ):
                    raise ProjectStateError(
                        "integration checkout cannot be rebound after admission"
                    )
                state["integration_checkout"] = parsed
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return self._read_state_strict(anchor_id)

    def rebind_lane_dependencies(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lane_id: str,
        accepted_commit: str,
        dependency_binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Clear staleness only after Git, scheduler, spec and allowed-set rebind."""

        parsed = _validate_dependency_binding(dict(dependency_binding))
        if (
            not _LANE_ID.fullmatch(lane_id)
            or not _GIT_OBJECT.fullmatch(accepted_commit)
            or parsed["accepted_base"] != accepted_commit
            or parsed["allowed_set_digest"] is None
        ):
            raise ProjectStateError("lane dependency rebind input is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                if state["integration_fence"] is not None:
                    raise ProjectStateError(
                        "integration ref is fenced pending acceptance"
                    )
                lane = next(
                    (
                        item
                        for item in state["lanes"]
                        if item.get("lane_id") == lane_id
                    ),
                    None,
                )
                stale = (
                    lane.get("integration_stale")
                    if isinstance(lane, Mapping)
                    else None
                )
                if (
                    not isinstance(lane, dict)
                    or not isinstance(stale, Mapping)
                    or stale.get("accepted_commit") != accepted_commit
                    or lane.get("writer") is not None
                    or lane.get("state")
                    not in {"waiting-for-scope", "creating", "ready"}
                ):
                    raise ProjectStateError(
                        "lane dependency rebind is not eligible"
                    )
                session = _validate_lane_session(state["lane_session"])
                assert session is not None
                tip = subprocess.run(
                    [
                        "git",
                        "rev-parse",
                        "--verify",
                        f"{session['integration_ref']}^{{commit}}",
                    ],
                    cwd=self.project,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                head = subprocess.run(
                    ["git", "rev-parse", "--verify", "HEAD^{commit}"],
                    cwd=Path(str(lane["worktree"])),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                dirty = subprocess.run(
                    ["git", "status", "--porcelain=v1", "-z"],
                    cwd=Path(str(lane["worktree"])),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if (
                    tip.returncode
                    or head.returncode
                    or dirty.returncode
                    or tip.stdout.decode("ascii", "ignore").strip()
                    != accepted_commit
                    or head.stdout.decode("ascii", "ignore").strip()
                    != accepted_commit
                    or dirty.stdout
                ):
                    raise ProjectStateError(
                        "lane dependency rebind Git proof is stale"
                    )
                lanes = [dict(item) for item in state["lanes"]]
                updated = next(
                    item for item in lanes if item["lane_id"] == lane_id
                )
                updated["base"] = accepted_commit
                updated["dependency_binding"] = parsed
                updated.pop("integration_stale", None)
                validated = [
                    _validate_lane_projection(item) for item in lanes
                ]
                _validate_lane_projection_transition(
                    state["lanes"],
                    validated,
                    dependency_rebind_lane_id=lane_id,
                )
                state["generation"] += 1
                state["lanes"] = validated
                _replace_json(self._state_path(anchor_id), state)
                return next(
                    item
                    for item in self._read_state_strict(anchor_id)["lanes"]
                    if item["lane_id"] == lane_id
                )

    def replace_lane_state(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Atomically publish the M2 lane projection under the established locks.

        Lifecycle owners derive the projection. The sink still prevents an
        admitted lease from disappearing or being downgraded without the future
        integration-owner release transition.
        """
        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition=None,
            protected_adoption_receipt=None,
            safe_stop_transition=None,
            safe_stop_intent_id=None,
            scope_release_acceptance_id=None,
        )

    def cancel_unclaimed_runtime_with_lane_state(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        lane_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        """Atomically terminalize one lane and remove its unclaimed runtime job."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition=None,
            protected_adoption_receipt=None,
            safe_stop_transition=None,
            safe_stop_intent_id=None,
            scope_release_acceptance_id=None,
            runtime_cancellation={
                "lane_id": lane_id,
                "job_id": job_id,
            },
        )

    def replace_milestone_state(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        milestones: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Atomically publish the M4 scheduler's durable DAG projection."""
        if not isinstance(expected_generation, int) or expected_generation < 0:
            raise ProjectStateError("expected project generation is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                if state["state"] != "clean":
                    raise ProjectStateError("breached project state cannot publish milestones")
                if state["integration_fence"] is not None:
                    raise ProjectStateError(
                        "integration ref is fenced pending acceptance"
                    )
                validated = [_validate_milestone_projection(value) for value in milestones]
                _validate_milestone_dag(validated)
                _validate_milestone_transition(state["milestones"], validated)
                _validate_milestone_lane_projection(
                    validated,
                    state["lanes"],
                    state["scopes"],
                )
                self._validate_milestone_completion_lane(
                    state["milestones"],
                    validated,
                    state["lanes"],
                    state["lane_session"],
                    state["integration_acceptances"],
                    state["scopes"],
                )
                state["generation"] += 1
                state["milestones"] = validated
                _replace_json(self._state_path(anchor_id), state)
                return self._read_state_strict(anchor_id)

    def request_safe_stop_rebind(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        intent_id: str,
    ) -> dict[str, Any]:
        """Publish the project-owner half of a live writer safe-stop intent."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition=None,
            protected_adoption_receipt=None,
            safe_stop_transition="request",
            safe_stop_intent_id=intent_id,
            scope_release_acceptance_id=None,
        )

    def consume_safe_stop_rebind(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        intent_id: str,
    ) -> dict[str, Any]:
        """Record that the exact creation-bound guardian has started stopping."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition=None,
            protected_adoption_receipt=None,
            safe_stop_transition="consume",
            safe_stop_intent_id=intent_id,
            scope_release_acceptance_id=None,
        )

    def complete_safe_stop_rebind(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        intent_id: str,
    ) -> dict[str, Any]:
        """Publish the post-zero no-writer ready/wait projection exactly once."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition=None,
            protected_adoption_receipt=None,
            safe_stop_transition="complete",
            safe_stop_intent_id=intent_id,
            scope_release_acceptance_id=None,
        )

    def _scope_terminal_release(
        self,
        lane: Mapping[str, Any],
        recovery_root: Path,
    ) -> dict[str, Any]:
        try:
            registry_state = RecoveryRegistry(
                Path(str(lane["worktree"])),
                state_root=recovery_root,
            ).state()
        except (OSError, RecoveryStateError) as exc:
            raise ProjectStateError(
                "integration acceptance lane registry is invalid"
            ) from exc
        if (
            registry_state.get("lease") is not None
            or registry_state.get("outbox") is not None
            or registry_state.get("quarantine") is not None
        ):
            raise ProjectStateError(
                "integration acceptance lane registry is not vacant"
            )
        writer = lane.get("writer")
        releases = [
            event
            for event in registry_state.get("history", [])
            if isinstance(writer, Mapping)
            and event.get("event") == "contained-terminal-released"
            and event.get("lease_id") == writer.get("lease_id")
            and event.get("run_id") == writer.get("run_id")
            and event.get("lease_kind") == writer.get("lease_kind")
            and event.get("allowed_set_digest")
            == writer.get("allowed_set_digest")
            and event.get("terminal_success") is True
            and event.get("semantic_disposition") is None
            and event.get("final_state") == "handoff-committed"
            and event.get("archive_digest")
            == lane.get("terminal_evidence")
            and _is_hex_identifier(event.get("handoff_digest"))
            and _is_hex_identifier(event.get("outbox_digest"))
        ]
        if len(releases) != 1:
            raise ProjectStateError(
                "integration acceptance terminal archive is missing or ambiguous"
            )
        return {
            key: releases[0][key]
            for key in (
                "run_id",
                "archive_digest",
                "handoff_digest",
                "outbox_digest",
                "final_state",
            )
        }

    def _validate_milestone_completion_lane(
        self,
        current: Sequence[Mapping[str, Any]],
        proposed: Sequence[Mapping[str, Any]],
        lanes: Sequence[Mapping[str, Any]],
        lane_session: Mapping[str, Any] | None,
        integration_acceptances: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
    ) -> None:
        before = {
            (item["task_id"], item["milestone_id"]): item
            for item in current
        }
        completed = [
            identity
            for identity, item in {
                (value["task_id"], value["milestone_id"]): value
                for value in proposed
            }.items()
            if item["state"] == "completed"
            and identity in before
            and before[identity]["state"] != "completed"
        ]
        if not completed:
            return
        if len(completed) != 1 or not isinstance(lane_session, Mapping):
            raise ProjectStateError(
                "milestone completion lane binding is unavailable"
            )
        task_id, milestone_id = completed[0]
        matching = [
            lane
            for lane in lanes
            if lane.get("scheduler_binding")
            == {
                "schema": "project-scheduler-lane-v1",
                "task_id": str(task_id),
                "milestone_id": str(milestone_id),
            }
        ]
        if (
            len(matching) != 1
            or matching[0].get("state") != "waiting-for-integration"
            or not isinstance(matching[0].get("writer"), Mapping)
            or not _is_hex_identifier(
                matching[0].get("terminal_evidence")
            )
        ):
            raise ProjectStateError(
                "milestone completion requires one exact terminal lane"
            )
        lane = matching[0]
        acceptances = [
            acceptance
            for acceptance in integration_acceptances
            if acceptance.get("lane_id") == lane.get("lane_id")
        ]
        if (
            len(acceptances) != 1
            or acceptances[0].get("writer") != lane.get("writer")
            or acceptances[0].get("terminal_archive")
            != lane.get("terminal_evidence")
            or acceptances[0].get("admitted_commit") != lane.get("base")
            or not _is_hex_identifier(
                acceptances[0].get("acceptance_id")
            )
        ):
            raise ProjectStateError(
                "milestone completion requires exact integration acceptance"
            )
        acceptance_id = str(acceptances[0]["acceptance_id"])
        owned_hard = [
            scope
            for scope in scopes
            if scope.get("owner") == lane.get("lane_id")
            and scope.get("mode") == "hard"
            and scope.get("kind") in _SCOPE_KIND_ORDER
        ]
        if not owned_hard or any(
            scope.get("status") not in {"released", "cancelled"}
            or (
                scope.get("status") == "released"
                and (
                    not isinstance(scope.get("release"), Mapping)
                    or scope["release"].get("acceptance_id")
                    != acceptance_id
                )
            )
            for scope in owned_hard
        ):
            raise ProjectStateError(
                "milestone completion requires released hard scopes"
            )
        recovery_root_value = lane_session.get("recovery_root")
        if not isinstance(recovery_root_value, str):
            raise ProjectStateError(
                "milestone completion recovery binding is unavailable"
            )
        self._scope_terminal_release(
            lane,
            Path(recovery_root_value),
        )

    def _validate_lane_writer_transitions(
        self,
        current: Sequence[Mapping[str, Any]],
        proposed: Sequence[Mapping[str, Any]],
        lane_session: Mapping[str, Any],
        *,
        safe_stop_transition: str | None,
    ) -> None:
        recovery_root_value = lane_session.get("recovery_root")
        if not isinstance(recovery_root_value, str):
            raise ProjectStateError(
                "lane writer transition requires a bound recovery root"
            )
        recovery_root = Path(recovery_root_value)
        _assert_no_link_or_reparse_ancestors(recovery_root)
        current_by_id = {
            str(lane["lane_id"]): lane
            for lane in current
        }
        for after in proposed:
            before = current_by_id.get(str(after["lane_id"]))
            new_writer = after.get("writer")
            if not isinstance(before, Mapping) and new_writer is None:
                continue
            old_writer = (
                before.get("writer")
                if isinstance(before, Mapping)
                else None
            )
            entering_running = (
                (
                    before.get("state")
                    if isinstance(before, Mapping)
                    else None
                )
                != "running"
                and after.get("state") == "running"
            )
            if old_writer == new_writer and not entering_running:
                continue
            try:
                registry_state = RecoveryRegistry(
                    Path(str(after["worktree"])),
                    state_root=recovery_root,
                ).state()
            except (OSError, RecoveryStateError) as exc:
                raise ProjectStateError(
                    "lane writer transition registry is invalid"
                ) from exc
            if (
                isinstance(old_writer, Mapping)
                and new_writer is None
                and safe_stop_transition == "complete"
            ):
                safe_stop = after.get("safe_stop")
                terminal_archive = (
                    safe_stop.get("terminal_archive")
                    if isinstance(safe_stop, Mapping)
                    else None
                )
                releases = [
                    event
                    for event in registry_state.get("history", [])
                    if event.get("event") == "contained-terminal-released"
                    and event.get("lease_id") == old_writer.get("lease_id")
                    and event.get("run_id") == old_writer.get("run_id")
                    and event.get("lease_kind")
                    == old_writer.get("lease_kind")
                    and event.get("allowed_set_digest")
                    == old_writer.get("allowed_set_digest")
                    and event.get("terminal_success") is False
                    and event.get("handoff_digest") is None
                    and event.get("outbox_digest") is None
                    and event.get("archive_digest") == terminal_archive
                ]
                if (
                    registry_state.get("lease") is not None
                    or registry_state.get("outbox") is not None
                    or registry_state.get("quarantine") is not None
                    or len(releases) != 1
                    or (
                        after.get("state") == "recovery-ready"
                        and after.get("terminal_evidence") != terminal_archive
                    )
                ):
                    raise ProjectStateError(
                        "safe-stop detach lacks exact terminal registry authority"
                    )
                continue
            if (
                old_writer is None
                or entering_running
            ) and isinstance(new_writer, Mapping):
                lease = registry_state.get("lease")
                lease_kind = (
                    lease.get("lease_kind")
                    if isinstance(lease, Mapping)
                    else None
                )
                run_id = (
                    lease.get("plan", {}).get("run_id")
                    if lease_kind == "recovery-target"
                    and isinstance(lease, Mapping)
                    else lease.get("run_id")
                    if isinstance(lease, Mapping)
                    else None
                )
                observed_writer = (
                    {
                        "lease_id": lease.get("lease_id"),
                        "run_id": run_id,
                        "allowed_set_digest": lease.get(
                            "allowed_set_digest"
                        ),
                        "lease_kind": lease_kind,
                    }
                    if isinstance(lease, Mapping)
                    else None
                )
                if (
                    not isinstance(lease, Mapping)
                    or lease.get("state") not in {"running", "active"}
                    or observed_writer != new_writer
                    or after.get("state") not in {"running", "quarantined"}
                ):
                    raise ProjectStateError(
                        "lane writer attach lacks exact active registry authority"
                    )
                continue
            if (
                isinstance(old_writer, Mapping)
                and new_writer is None
                and before.get("state") == "quarantined"
                and after.get("state") == "recovery-ready"
            ):
                releases = [
                    event
                    for event in registry_state.get("history", [])
                    if event.get("event") == "contained-terminal-released"
                    and event.get("lease_id") == old_writer.get("lease_id")
                    and event.get("run_id") == old_writer.get("run_id")
                    and event.get("lease_kind")
                    == old_writer.get("lease_kind")
                    and event.get("allowed_set_digest")
                    == old_writer.get("allowed_set_digest")
                    and event.get("terminal_success") is False
                    and event.get("archive_digest")
                    == after.get("terminal_evidence")
                ]
                if (
                    registry_state.get("lease") is not None
                    or registry_state.get("outbox") is not None
                    or registry_state.get("quarantine") is not None
                    or len(releases) != 1
                ):
                    raise ProjectStateError(
                        "lane recovery detach lacks exact terminal registry authority"
                    )
                continue
            raise ProjectStateError(
                "lane writer transition requires its owning lifecycle"
            )

    def _scope_integration_proof(
        self,
        anchor_id: str,
        lane: Mapping[str, Any],
        lane_session: Mapping[str, Any],
        *,
        admitted_commit: str,
        accepted_commit: str,
        validation_argv: Sequence[str],
        executor_lease_id: str | None = None,
        recovery_root: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        terminal_release = self._scope_terminal_release(lane, recovery_root)
        lane_worktree = _absolute_no_follow(
            Path(str(lane["worktree"]))
        )
        _assert_no_link_or_reparse_ancestors(lane_worktree)

        def git(*arguments: str, cwd: Path) -> bytes:
            result = subprocess.run(
                ["git", *arguments],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode != 0:
                raise ProjectStateError(
                    "integration acceptance Git proof failed"
                )
            return result.stdout

        if git(
            "status",
            "--porcelain=v1",
            "-z",
            cwd=lane_worktree,
        ):
            raise ProjectStateError(
                "integration acceptance lane worktree is not committed"
            )
        try:
            lane_head = git(
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
                cwd=lane_worktree,
            ).decode("ascii").strip()
            lane_tree = git(
                "rev-parse",
                "--verify",
                "HEAD^{tree}",
                cwd=lane_worktree,
            ).decode("ascii").strip()
            admitted_tree = git(
                "rev-parse",
                "--verify",
                f"{admitted_commit}^{{tree}}",
                cwd=lane_worktree,
            ).decode("ascii").strip()
            integration_tip = git(
                "rev-parse",
                "--verify",
                f"{lane_session['integration_ref']}^{{commit}}",
                cwd=self.project,
            ).decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ProjectStateError(
                "integration acceptance Git identity is invalid"
            ) from exc
        if (
            integration_tip != accepted_commit
            or lane_tree == admitted_tree
            or git(
                "symbolic-ref",
                "--quiet",
                "HEAD",
                cwd=lane_worktree,
            ).decode(
                "utf-8"
            ).strip()
            != str(lane["branch"])
        ):
            raise ProjectStateError(
                "integration acceptance lane result is not a non-empty accepted commit"
            )
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", lane_head, accepted_commit],
            cwd=lane_worktree,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if ancestry.returncode != 0:
            raise ProjectStateError(
                "integration acceptance does not contain the terminal lane result"
            )
        _verify_scope_integration_ref(
            self.project,
            lane_session,
            admitted_commit=admitted_commit,
            accepted_commit=accepted_commit,
        )
        validation_parent = (
            self.anchor_path(anchor_id) / "integration-validation"
        )
        _ensure_private_directory(validation_parent)
        validation_worktree = (
            validation_parent / secrets.token_hex(16)
        )
        add_result = subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(validation_worktree),
                accepted_commit,
            ],
            cwd=self.project,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if add_result.returncode != 0:
            raise ProjectStateError(
                "integration validation checkout creation failed"
            )
        result: subprocess.CompletedProcess[bytes]
        try:
            status_before = git(
                "status",
                "--porcelain=v1",
                "-z",
                cwd=validation_worktree,
            )
            head_before = git(
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
                cwd=validation_worktree,
            ).decode("ascii").strip()
            tree_before = git(
                "rev-parse",
                "--verify",
                "HEAD^{tree}",
                cwd=validation_worktree,
            ).decode("ascii").strip()
            if (
                status_before
                or head_before != accepted_commit
                or validation_worktree == lane_worktree
            ):
                raise ProjectStateError(
                    "integration validation checkout binding is invalid"
                )
            try:
                result = subprocess.run(
                    list(validation_argv),
                    cwd=validation_worktree,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=300,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ProjectStateError(
                    "integration validation did not complete"
                ) from exc
            if (
                result.returncode != 0
                or len(result.stdout) > 1024 * 1024
                or len(result.stderr) > 1024 * 1024
            ):
                raise ProjectStateError(
                    "integration validation did not pass"
                )
            status_after = git(
                "status",
                "--porcelain=v1",
                "-z",
                cwd=validation_worktree,
            )
            head_after = git(
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
                cwd=validation_worktree,
            ).decode("ascii").strip()
            tree_after = git(
                "rev-parse",
                "--verify",
                "HEAD^{tree}",
                cwd=validation_worktree,
            ).decode("ascii").strip()
            if (
                status_after != status_before
                or head_after != head_before
                or tree_after != tree_before
            ):
                raise ProjectStateError(
                    "integration validation changed its accepted checkout"
                )
        except UnicodeDecodeError as exc:
            raise ProjectStateError(
                "integration validation checkout identity is invalid"
            ) from exc
        finally:
            remove_result = subprocess.run(
                [
                    "git",
                    "worktree",
                    "remove",
                    "--force",
                    str(validation_worktree),
                ],
                cwd=self.project,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if remove_result.returncode != 0:
                raise ProjectStateError(
                    "integration validation checkout cleanup failed"
                )
        validation = {
            "result": "passed",
            "command": list(validation_argv),
            "accepted_commit": accepted_commit,
            "head_before": head_before,
            "tree_before": tree_before,
            "status_before_digest": hashlib.sha256(
                status_before
            ).hexdigest(),
            "head_after": head_after,
            "tree_after": tree_after,
            "status_after_digest": hashlib.sha256(
                status_after
            ).hexdigest(),
            "exit_code": result.returncode,
            "stdout_digest": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_digest": hashlib.sha256(result.stderr).hexdigest(),
        }
        validation["digest"] = hashlib.sha256(
            _canonical(validation)
        ).hexdigest()
        return terminal_release, validation

    def record_scope_integration_acceptance(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lane_id: str,
        admitted_commit: str,
        accepted_commit: str,
        validation_argv: Sequence[str],
        executor_lease_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist the minimum M3 integration-owner acceptance record.

        This deliberately records acceptance only. It does not merge, queue, or
        move a ref; release remains a separate purpose-specific sink.
        """

        if (
            not _LANE_ID.fullmatch(lane_id)
            or not _GIT_OBJECT.fullmatch(admitted_commit)
            or not _GIT_OBJECT.fullmatch(accepted_commit)
            or not isinstance(validation_argv, Sequence)
            or isinstance(validation_argv, (str, bytes))
            or not validation_argv
            or len(validation_argv) > 64
            or any(
                not isinstance(argument, str)
                or not argument
                or "\0" in argument
                or len(argument) > 4096
                for argument in validation_argv
            )
        ):
            raise ProjectStateError("integration acceptance input is invalid")
        observed = self.read_state(anchor_id)
        if observed.get("status") != "present":
            raise ProjectStateError("project state is unavailable")
        observed_state = observed["state"]
        if observed_state.get("generation") != expected_generation:
            raise ProjectStateError("project generation changed")
        observed_session = _validate_lane_session(
            observed_state.get("lane_session")
        )
        observed_lane = next(
            (
                item
                for item in observed_state.get("lanes", [])
                if item.get("lane_id") == lane_id
            ),
            None,
        )
        if (
            observed_state.get("state") != "clean"
            or observed_session is None
            or not isinstance(observed_lane, dict)
            or observed_lane.get("state") != "waiting-for-integration"
            or not isinstance(observed_lane.get("writer"), dict)
            or not _is_hex_identifier(
                observed_lane.get("terminal_evidence")
            )
            or observed_lane.get("base") != admitted_commit
        ):
            raise ProjectStateError(
                "integration acceptance lane is not terminally admitted"
            )
        recovery_root_value = observed_session.get("recovery_root")
        if not isinstance(recovery_root_value, str):
            raise ProjectStateError(
                "integration acceptance recovery registry is not durably bound"
            )
        recovery_root = _absolute_no_follow(
            Path(recovery_root_value)
        )
        _assert_no_link_or_reparse_ancestors(recovery_root)
        terminal_release, validation = self._scope_integration_proof(
            anchor_id,
            observed_lane,
            observed_session,
            admitted_commit=admitted_commit,
            accepted_commit=accepted_commit,
            validation_argv=validation_argv,
            recovery_root=recovery_root,
        )
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                fence = state["integration_fence"]
                if fence is not None:
                    if (
                        not isinstance(executor_lease_id, str)
                        or fence.get("candidate_commit") != accepted_commit
                    ):
                        raise ProjectStateError(
                            "integration acceptance lacks the executor lease"
                        )
                    self._require_integration_executor(
                        state,
                        lease_id=executor_lease_id,
                        intent_id=str(fence["intent_id"]),
                    )
                lane_session = _validate_lane_session(state["lane_session"])
                if state["state"] != "clean" or lane_session is None:
                    raise ProjectStateError("integration acceptance lane session is unavailable")
                lane = next(
                    (item for item in state["lanes"] if item.get("lane_id") == lane_id),
                    None,
                )
                if (
                    not isinstance(lane, dict)
                    or lane.get("state") != "waiting-for-integration"
                    or not isinstance(lane.get("writer"), dict)
                    or not _is_hex_identifier(lane.get("terminal_evidence"))
                    or lane.get("base") != admitted_commit
                ):
                    raise ProjectStateError("integration acceptance lane is not terminally admitted")
                if lane != observed_lane:
                    raise ProjectStateError("integration acceptance lane binding changed")
                if self._scope_terminal_release(
                    lane,
                    recovery_root,
                ) != terminal_release:
                    raise ProjectStateError(
                        "integration acceptance terminal archive changed"
                    )
                _verify_scope_integration_ref(
                    self.project,
                    lane_session,
                    admitted_commit=admitted_commit,
                    accepted_commit=accepted_commit,
                )
                reservations = [
                    {
                        key: scope[key]
                        for key in (
                            "kind",
                            "path",
                            "mode",
                            "sequence",
                            "reservation",
                            "phase",
                            "status",
                        )
                    }
                    for scope in state["scopes"]
                    if scope.get("owner") == lane_id
                    and scope.get("kind") in _SCOPE_KIND_ORDER
                    and scope.get("mode") == "hard"
                    and scope.get("status") in {
                        "active",
                        "waiting",
                        "cancelled",
                    }
                ]
                reservations.sort(key=_scope_reservation_order)
                if not reservations:
                    raise ProjectStateError("integration acceptance has no exact hard reservations")
                candidate = {
                    "schema": "project-scope-integration-acceptance-v1",
                    "anchor_id": anchor_id,
                    "lane_id": lane_id,
                    "session": lane_session,
                    "writer": dict(lane["writer"]),
                    "terminal_archive": lane["terminal_evidence"],
                    "terminal_release": dict(terminal_release),
                    "admitted_commit": admitted_commit,
                    "accepted_commit": accepted_commit,
                    "validation": dict(validation),
                    "reservations": reservations,
                    "generation": state["generation"] + 1,
                }
                acceptance_id = hashlib.sha256(_canonical(candidate)).hexdigest()
                acceptance = {"acceptance_id": acceptance_id, **candidate}
                existing = [
                    item
                    for item in state["integration_acceptances"]
                    if item.get("lane_id") == lane_id
                ]
                if existing:
                    stored = dict(existing[0]) if len(existing) == 1 else {}
                    replay_candidate = {
                        **candidate,
                        "generation": stored.get("generation"),
                    }
                    replay_acceptance = {
                        "acceptance_id": hashlib.sha256(
                            _canonical(replay_candidate)
                        ).hexdigest(),
                        **replay_candidate,
                    }
                    if stored == replay_acceptance:
                        return stored
                    raise ProjectStateError("integration acceptance replay binding changed")
                state["integration_acceptances"].append(acceptance)
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(acceptance)

    def release_scope_integration_acceptance(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lane_id: str,
        acceptance_id: str,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        executor_lease_id: str | None = None,
    ) -> dict[str, Any]:
        if not _LANE_ID.fullmatch(lane_id) or not _is_hex_identifier(acceptance_id):
            raise ProjectStateError("integration acceptance input is invalid")
        validated_lanes = [_validate_lane_projection(value) for value in lanes]
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                fence = state["integration_fence"]
                if fence is not None:
                    if not isinstance(executor_lease_id, str):
                        raise ProjectStateError(
                            "integration scope release lacks the executor lease"
                        )
                    self._require_integration_executor(
                        state,
                        lease_id=executor_lease_id,
                        intent_id=str(fence["intent_id"]),
                    )
                lane_session = _validate_lane_session(state["lane_session"])
                if state["state"] != "clean" or lane_session is None:
                    raise ProjectStateError("integration acceptance lane session is unavailable")
                acceptance = next(
                    (
                        item
                        for item in state["integration_acceptances"]
                        if item.get("acceptance_id") == acceptance_id
                    ),
                    None,
                )
                if not isinstance(acceptance, dict) or acceptance.get("lane_id") != lane_id:
                    raise ProjectStateError("registry-resident integration-owner acceptance is absent")
                no_op = (
                    acceptance.get("schema")
                    == "project-scope-integration-acceptance-v2"
                )
                if not no_op:
                    _verify_scope_integration_ref(
                        self.project,
                        lane_session,
                        admitted_commit=acceptance["admitted_commit"],
                        accepted_commit=acceptance["accepted_commit"],
                    )
                current_lane = next(
                    (item for item in state["lanes"] if item.get("lane_id") == lane_id),
                    None,
                )
                if no_op:
                    safe_stop = current_lane.get("safe_stop") if isinstance(current_lane, dict) else None
                    valid_lane = (
                        isinstance(current_lane, dict)
                        and current_lane.get("state") == "ready"
                        and current_lane.get("writer") is None
                        and current_lane.get("base") == acceptance.get("admitted_commit")
                        and isinstance(safe_stop, Mapping)
                        and safe_stop.get("status") == "completed"
                        and safe_stop.get("writer") == acceptance.get("writer")
                        and safe_stop.get("terminal_archive") == acceptance.get("terminal_archive")
                        and safe_stop.get("preserved_changes") is False
                    )
                else:
                    valid_lane = (
                        isinstance(current_lane, dict)
                        and current_lane.get("state") == "waiting-for-integration"
                        and current_lane.get("writer") == acceptance.get("writer")
                        and current_lane.get("terminal_evidence") == acceptance.get("terminal_archive")
                        and current_lane.get("base") == acceptance.get("admitted_commit")
                    )
                if not valid_lane:
                    raise ProjectStateError("integration acceptance is stale")
                validated_scopes = [
                    _validate_project_scope(value, lane_session) for value in scopes
                ]
                _validate_lane_scope_uniqueness(validated_lanes, validated_scopes)
                def release_identity(
                    item: Mapping[str, Any],
                ) -> tuple[Any, ...]:
                    return (
                        item.get("kind"),
                        str(item.get("path", "")).casefold(),
                        item.get("mode"),
                        item.get("owner"),
                        item.get("sequence"),
                        item.get("reservation"),
                        item.get("phase"),
                    )

                current_other_scopes = {
                    release_identity(item): dict(item)
                    for item in state["scopes"]
                    if item.get("owner") != lane_id
                }
                proposed_other_scopes = {
                    release_identity(item): dict(item)
                    for item in validated_scopes
                    if item.get("owner") != lane_id
                }
                if set(proposed_other_scopes) != set(current_other_scopes):
                    raise ProjectStateError(
                        "integration acceptance cannot mutate another lane scope"
                    )
                for identity, current_other in current_other_scopes.items():
                    proposed_other = proposed_other_scopes[identity]
                    if proposed_other == current_other:
                        continue
                    promoted = dict(current_other)
                    promoted["status"] = "active"
                    if (
                        current_other.get("status") == "waiting"
                        and proposed_other == promoted
                    ):
                        continue
                    raise ProjectStateError(
                        "integration acceptance cannot mutate another lane scope"
                    )
                _validate_scope_projection_transition(
                    state["scopes"],
                    validated_scopes,
                    scope_release_acceptance_id=acceptance_id,
                )
                accepted_intent = next(
                    (
                        item
                        for item in state["integration_queue"]
                        if item.get("acceptance_id") == acceptance_id
                    ),
                    None,
                )
                accepted_stale = (
                    accepted_intent.get("result", {}).get(
                        "dependency_stale",
                    )
                    if isinstance(accepted_intent, Mapping)
                    else None
                )
                proposed_lane = next(
                    (
                        item
                        for item in validated_lanes
                        if item.get("lane_id") == lane_id
                    ),
                    None,
                )
                stale_resolved_lane_id = None
                if (
                    isinstance(current_lane, Mapping)
                    and isinstance(current_lane.get("integration_stale"), Mapping)
                    and accepted_stale == current_lane.get("integration_stale")
                    and isinstance(proposed_lane, Mapping)
                    and proposed_lane.get("integration_stale") is None
                ):
                    stale_resolved_lane_id = lane_id
                _validate_lane_projection_transition(
                    state["lanes"],
                    validated_lanes,
                    stale_acceptance_id=acceptance_id,
                    stale_resolved_lane_id=stale_resolved_lane_id,
                )
                _validate_safe_stop_transition(
                    state["lanes"],
                    validated_lanes,
                    transition=None,
                    intent_id=None,
                    expected_generation=state["generation"],
                )
                accepted_by_identity = {
                    (
                        item["kind"],
                        item["path"].casefold(),
                        item["mode"],
                        item["sequence"],
                        item["reservation"],
                        item["phase"],
                    ): item
                    for item in acceptance["reservations"]
                }
                proposed_by_identity = {
                    (
                        item["kind"],
                        item["path"].casefold(),
                        item["mode"],
                        item["sequence"],
                        item["reservation"],
                        item["phase"],
                    ): item
                    for item in validated_scopes
                    if item.get("owner") == lane_id
                    and item.get("kind") in _SCOPE_KIND_ORDER
                    and item.get("mode") == "hard"
                }
                if set(proposed_by_identity) != set(accepted_by_identity):
                    raise ProjectStateError("integration acceptance reservation binding changed")
                current_by_identity = {
                    (
                        item["kind"],
                        item["path"].casefold(),
                        item["mode"],
                        item["sequence"],
                        item["reservation"],
                        item["phase"],
                    ): item
                    for item in state["scopes"]
                    if item.get("owner") == lane_id
                    and item.get("kind") in _SCOPE_KIND_ORDER
                    and item.get("mode") == "hard"
                }
                replayed = True
                for identity, expected in accepted_by_identity.items():
                    proposed = proposed_by_identity[identity]
                    current = current_by_identity.get(identity)
                    if not isinstance(current, Mapping):
                        raise ProjectStateError("integration acceptance reservation is stale")
                    if expected["status"] == "cancelled":
                        if current.get("status") != "cancelled" or proposed.get("status") != "cancelled":
                            raise ProjectStateError("cancelled reservation cannot be released")
                        continue
                    if expected["status"] == "waiting":
                        if (
                            current.get("status") not in {"waiting", "cancelled"}
                            or proposed.get("status") != "cancelled"
                        ):
                            raise ProjectStateError(
                                "waiting reservation was not cancelled by integration"
                            )
                        if current.get("status") != "cancelled":
                            replayed = False
                        continue
                    release = proposed.get("release")
                    if proposed.get("status") == "released":
                        if (
                            not isinstance(release, dict)
                            or release.get("acceptance_id") != acceptance_id
                        ):
                            raise ProjectStateError("integration acceptance release binding changed")
                        if current.get("status") != "released":
                            replayed = False
                        continue
                    raise ProjectStateError("accepted active reservation was not released")
                if replayed:
                    return {"state": state, "replayed": True}
                if any(lane["common"] != lane_session["common"] for lane in validated_lanes):
                    raise ProjectStateError("project lane session identity drifted")
                state["generation"] += 1
                state["lanes"] = validated_lanes
                state["scopes"] = validated_scopes
                _replace_json(self._state_path(anchor_id), state)
                return {"state": self._read_state_strict(anchor_id), "replayed": False}

    def enqueue_integration_intent(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lane_id: str,
        result_commit: str,
        admitted_tip: str,
        validation_argv: Sequence[str],
        queue_class: str = "ordinary",
    ) -> dict[str, Any]:
        """Durably admit one exact terminal lane result to the M5 queue."""

        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _LANE_ID.fullmatch(lane_id)
            or not _GIT_OBJECT.fullmatch(result_commit)
            or not _GIT_OBJECT.fullmatch(admitted_tip)
            or queue_class not in _INTEGRATION_QUEUE_CLASSES
        ):
            raise ProjectStateError("integration intent input is invalid")
        argv = _validate_integration_validation_argv(list(validation_argv))
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                session = _validate_lane_session(state["lane_session"])
                lane = next(
                    (item for item in state["lanes"] if item.get("lane_id") == lane_id),
                    None,
                )
                if (
                    state["state"] != "clean"
                    or session is None
                    or state["integration_checkout"] is None
                    or state["integration_fence"] is not None
                    or not isinstance(lane, dict)
                    or lane.get("state") != "waiting-for-integration"
                    or not isinstance(lane.get("writer"), dict)
                    or not _is_hex_identifier(lane.get("terminal_evidence"))
                    or not _GIT_OBJECT.fullmatch(str(lane.get("base")))
                ):
                    raise ProjectStateError("integration intent lane is not terminally admitted")
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", f"{result_commit}^{{commit}}"],
                    cwd=Path(str(lane["worktree"])),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if result.returncode != 0 or result.stdout.decode("ascii", "ignore").strip() != result_commit:
                    raise ProjectStateError("integration result commit is unavailable")
                lane_head = subprocess.run(
                    ["git", "rev-parse", "--verify", "HEAD^{commit}"],
                    cwd=Path(str(lane["worktree"])),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if lane_head.returncode != 0 or lane_head.stdout.decode("ascii", "ignore").strip() != result_commit:
                    raise ProjectStateError("integration result is not the terminal lane commit")
                common_tip = subprocess.run(
                    ["git", "rev-parse", "--verify", f"{session['integration_ref']}^{{commit}}"],
                    cwd=self.project,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if common_tip.returncode != 0 or common_tip.stdout.decode("ascii", "ignore").strip() != admitted_tip:
                    raise ProjectStateError("integration ref changed before intent admission")
                changed = subprocess.run(
                    [
                        "git",
                        "diff",
                        "--name-only",
                        "-z",
                        str(lane["base"]),
                        result_commit,
                    ],
                    cwd=self.project,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if changed.returncode:
                    raise ProjectStateError(
                        "integration result changed-path proof failed"
                    )
                try:
                    changed_paths = {
                        item.decode("utf-8")
                        for item in changed.stdout.split(b"\0")
                        if item
                    }
                except UnicodeDecodeError as exc:
                    raise ProjectStateError(
                        "integration result changed path is not UTF-8"
                    ) from exc
                if changed_paths & set(_VERSION_SURFACES):
                    raise ProjectStateError(
                        "worker result changed root-only version surfaces"
                    )
                recovery_root_value = session.get("recovery_root")
                if not isinstance(recovery_root_value, str):
                    raise ProjectStateError("integration intent recovery binding is absent")
                self._scope_terminal_release(lane, Path(recovery_root_value))
                reservations = [
                    {
                        key: scope[key]
                        for key in (
                            "kind", "path", "mode", "sequence", "reservation", "phase", "status"
                        )
                    }
                    for scope in state["scopes"]
                    if scope.get("owner") == lane_id
                    and scope.get("kind") in _SCOPE_KIND_ORDER
                    and scope.get("mode") == "hard"
                    and scope.get("status") in {"active", "waiting", "cancelled"}
                ]
                reservations.sort(key=_scope_reservation_order)
                if not reservations:
                    raise ProjectStateError("integration intent has no exact hard reservations")
                raw_dependency = lane.get("dependency_binding")
                if raw_dependency is None:
                    read_dependencies = [
                        dict(item)
                        for item in lane.get("scope_requests", [])
                        if isinstance(item, Mapping)
                        and (
                            item.get("mode") == "soft"
                            or item.get("kind") == "contract"
                        )
                    ]
                    read_dependencies.sort(
                        key=lambda item: (
                            _SCOPE_KIND_ORDER[str(item["kind"])],
                            str(item["path"]).casefold(),
                            str(item["path"]),
                            str(item["mode"]),
                        )
                    )
                    dependency_stable = {
                        "milestone_revision": hashlib.sha256(
                            _canonical(
                                {
                                    "milestone": lane["milestone"],
                                    "scheduler_binding": lane.get(
                                        "scheduler_binding"
                                    ),
                                }
                            )
                        ).hexdigest(),
                        "specification_revision": "R-032",
                        "read_dependencies": read_dependencies,
                    }
                    dependency_binding = {
                        "schema": "project-lane-dependency-v1",
                        **dependency_stable,
                        "allowed_set_digest": lane["writer"][
                            "allowed_set_digest"
                        ],
                        "dependency_digest": hashlib.sha256(
                            _canonical(dependency_stable)
                        ).hexdigest(),
                        "accepted_base": lane["base"],
                        "rebind_generation": int(
                            lane.get("scope_enqueue_sequence")
                            or state["generation"]
                            or 1
                        ),
                    }
                else:
                    dependency_binding = _validate_dependency_binding(
                        raw_dependency
                    )
                    if dependency_binding["allowed_set_digest"] is None:
                        dependency_binding = {
                            **dependency_binding,
                            "allowed_set_digest": lane["writer"][
                                "allowed_set_digest"
                            ],
                        }
                    if (
                        dependency_binding["allowed_set_digest"]
                        != lane["writer"]["allowed_set_digest"]
                        or dependency_binding["accepted_base"] != lane["base"]
                    ):
                        raise ProjectStateError(
                            "integration result dependency binding is stale"
                        )
                live = [
                    item for item in state["integration_queue"]
                    if item["result"]["lane_id"] == lane_id
                    and item["status"] not in {"released", "blocked", "stale", "no-op"}
                ]
                if live:
                    if (
                        len(live) == 1
                        and live[0]["result"]["result_commit"] == result_commit
                        and live[0]["result"]["validation_argv"] == argv
                        and live[0]["queue_class"] == queue_class
                    ):
                        return dict(live[0])
                    raise ProjectStateError("lane already has a live integration intent")
                tuple_without_digest = {
                    "schema": "project-integration-result-v1",
                    "lane_id": lane_id,
                    "session": session,
                    "writer": dict(lane["writer"]),
                    "terminal_archive": lane["terminal_evidence"],
                    "admitted_commit": lane["base"],
                    "result_commit": result_commit,
                    "reservations": reservations,
                    "validation_argv": argv,
                    "dependency_binding": dependency_binding,
                    "dependency_stale": (
                        dict(lane["integration_stale"])
                        if isinstance(
                            lane.get("integration_stale"),
                            Mapping,
                        )
                        else None
                    ),
                }
                result_tuple = {
                    **tuple_without_digest,
                    "digest": hashlib.sha256(_canonical(tuple_without_digest)).hexdigest(),
                }
                enqueue_generation = state["generation"] + 1
                binding = {
                    "schema": "project-integration-intent-v1",
                    "enqueue_generation": enqueue_generation,
                    "result": result_tuple,
                    "admitted_tip": admitted_tip,
                    "queue_class": queue_class,
                }
                intent = {
                    "schema": "project-integration-intent-v1",
                    "intent_id": hashlib.sha256(_canonical(binding)).hexdigest(),
                    "enqueue_generation": enqueue_generation,
                    "status": "queued",
                    "result": result_tuple,
                    "admitted_tip": admitted_tip,
                    "ticket": None,
                    "candidate_commit": None,
                    "acceptance_id": None,
                    "release_generation": None,
                    "diagnostic": None,
                    "version_finalization": None,
                    "queue_class": queue_class,
                }
                state["integration_queue"].append(intent)
                state["integration_queue"].sort(
                    key=lambda item: (item["enqueue_generation"], item["intent_id"]),
                )
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def record_abandoned_no_change_acceptance(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lane_id: str,
        diff_archive: bytes,
        validation_argv: Sequence[str],
    ) -> dict[str, Any]:
        """Accept the sole T-015 no-change exit without creating a commit."""

        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _LANE_ID.fullmatch(lane_id)
            or not isinstance(diff_archive, bytes)
            or diff_archive != b""
        ):
            raise ProjectStateError("abandoned no-change input is invalid")
        argv = _validate_integration_validation_argv(list(validation_argv))
        archive_digest = hashlib.sha256(diff_archive).hexdigest()

        def release_no_op_scopes(
            current: dict[str, Any],
            acceptance: Mapping[str, Any],
        ) -> bool:
            def identity(value: Mapping[str, Any]) -> tuple[Any, ...]:
                return (
                    value.get("kind"),
                    str(value.get("path", "")).casefold(),
                    value.get("mode"),
                    value.get("sequence"),
                    value.get("reservation"),
                    value.get("phase"),
                )

            expected = {
                identity(item): item
                for item in acceptance["reservations"]
            }
            observed: set[tuple[Any, ...]] = set()
            changed = False
            for scope in current["scopes"]:
                if (
                    scope.get("owner") != lane_id
                    or scope.get("kind") not in _SCOPE_KIND_ORDER
                    or scope.get("mode") != "hard"
                ):
                    continue
                key = identity(scope)
                recorded = expected.get(key)
                if not isinstance(recorded, Mapping):
                    raise ProjectStateError(
                        "abandoned no-change reservation binding changed"
                    )
                observed.add(key)
                recorded_status = recorded.get("status")
                if recorded_status == "active":
                    if scope.get("status") == "active":
                        scope["status"] = "released"
                        scope["release"] = {
                            "acceptance_id": acceptance["acceptance_id"],
                            "released_generation": current["generation"] + 1,
                        }
                        changed = True
                    elif (
                        scope.get("status") != "released"
                        or scope.get("release", {}).get("acceptance_id")
                        != acceptance["acceptance_id"]
                    ):
                        raise ProjectStateError(
                            "abandoned no-change active reservation changed"
                        )
                elif recorded_status == "waiting":
                    if scope.get("status") == "waiting":
                        scope["status"] = "cancelled"
                        changed = True
                    elif scope.get("status") != "cancelled":
                        raise ProjectStateError(
                            "abandoned no-change waiting reservation changed"
                        )
                elif (
                    recorded_status != "cancelled"
                    or scope.get("status") != "cancelled"
                ):
                    raise ProjectStateError(
                        "abandoned no-change cancelled reservation changed"
                    )
            if observed != set(expected):
                raise ProjectStateError(
                    "abandoned no-change reservation binding changed"
                )
            return changed

        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                current = self._read_state_strict(anchor_id)
                if current["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                existing = [
                    item
                    for item in current["integration_acceptances"]
                    if item.get("lane_id") == lane_id
                ]
                if existing:
                    stored = existing[0] if len(existing) == 1 else None
                    if (
                        not isinstance(stored, Mapping)
                        or stored.get("schema")
                        != "project-scope-integration-acceptance-v2"
                        or stored.get("kind") != "abandoned-no-change"
                        or stored.get("no_op_archive") != archive_digest
                        or stored.get("validation", {}).get("command") != argv
                    ):
                        raise ProjectStateError(
                            "abandoned no-change acceptance replay changed"
                        )
                    if release_no_op_scopes(current, stored):
                        current["generation"] += 1
                        _replace_json(self._state_path(anchor_id), current)
                    return dict(stored)

        observed = self.read_state(anchor_id)
        if observed.get("status") != "present":
            raise ProjectStateError("project state is unavailable")
        state = observed["state"]
        if state.get("generation") != expected_generation:
            raise ProjectStateError("project generation changed")
        session = _validate_lane_session(state.get("lane_session"))
        lane = next(
            (item for item in state.get("lanes", []) if item.get("lane_id") == lane_id),
            None,
        )
        safe_stop = lane.get("safe_stop") if isinstance(lane, Mapping) else None
        if (
            state.get("state") != "clean"
            or session is None
            or state.get("integration_fence") is not None
            or state.get("integration_executor") is not None
            or not isinstance(lane, Mapping)
            or lane.get("state") != "ready"
            or lane.get("writer") is not None
            or not isinstance(safe_stop, Mapping)
            or safe_stop.get("status") != "completed"
            or safe_stop.get("completed_state") != "ready"
            or safe_stop.get("preserved_changes") is not False
            or safe_stop.get("recovery_checkpoint_digest") is not None
            or not _is_hex_identifier(safe_stop.get("terminal_archive"))
            or not _GIT_OBJECT.fullmatch(str(lane.get("base")))
        ):
            raise ProjectStateError("abandoned no-change lane is not eligible")
        writer = _validate_writer(safe_stop.get("writer"))
        worktree = _absolute_no_follow(Path(str(lane["worktree"])))
        _assert_no_link_or_reparse_ancestors(worktree)

        def git(*arguments: str, cwd: Path) -> bytes:
            result = subprocess.run(
                ["git", *arguments],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode:
                raise ProjectStateError("abandoned no-change Git proof failed")
            return result.stdout

        base = str(lane["base"])
        if (
            git("status", "--porcelain=v1", "-z", cwd=worktree)
            or git("diff", "--binary", base, cwd=worktree) != diff_archive
            or git("rev-parse", "--verify", "HEAD^{commit}", cwd=worktree).decode("ascii").strip() != base
            or git(
                "symbolic-ref", "--quiet", "HEAD", cwd=worktree,
            ).decode("utf-8").strip() != str(lane["branch"])
            or git(
                "rev-parse", "--verify", f"{session['integration_ref']}^{{commit}}", cwd=self.project,
            ).decode("ascii").strip() != base
        ):
            raise ProjectStateError("abandoned no-change restore binding is invalid")
        try:
            registry = RecoveryRegistry(worktree, state_root=Path(str(session["recovery_root"]))).state()
        except (OSError, RecoveryStateError) as exc:
            raise ProjectStateError("abandoned no-change recovery registry is invalid") from exc
        releases = [
            event
            for event in registry.get("history", [])
            if event.get("event") == "contained-terminal-released"
            and event.get("lease_id") == writer.get("lease_id")
            and event.get("run_id") == writer.get("run_id")
            and event.get("lease_kind") == writer.get("lease_kind")
            and event.get("allowed_set_digest") == writer.get("allowed_set_digest")
            and event.get("terminal_success") is False
            and event.get("handoff_digest") is None
            and event.get("outbox_digest") is None
            and event.get("archive_digest") == safe_stop.get("terminal_archive")
        ]
        if (
            registry.get("lease") is not None
            or registry.get("outbox") is not None
            or registry.get("quarantine") is not None
            or len(releases) != 1
        ):
            raise ProjectStateError("abandoned no-change full-tree-zero archive is missing")
        validation_parent = self.anchor_path(anchor_id) / "no-op-validation"
        _ensure_private_directory(validation_parent)
        validation_worktree = validation_parent / secrets.token_hex(16)
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(validation_worktree), base],
            cwd=self.project,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if add.returncode:
            raise ProjectStateError("abandoned no-change validation checkout creation failed")
        try:
            status_before = git("status", "--porcelain=v1", "-z", cwd=validation_worktree)
            head_before = git("rev-parse", "--verify", "HEAD^{commit}", cwd=validation_worktree).decode("ascii").strip()
            tree_before = git("rev-parse", "--verify", "HEAD^{tree}", cwd=validation_worktree).decode("ascii").strip()
            if status_before or head_before != base:
                raise ProjectStateError("abandoned no-change validation binding is invalid")
            try:
                executed = subprocess.run(
                    argv,
                    cwd=validation_worktree,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ProjectStateError("abandoned no-change validation did not complete") from exc
            status_after = git("status", "--porcelain=v1", "-z", cwd=validation_worktree)
            head_after = git("rev-parse", "--verify", "HEAD^{commit}", cwd=validation_worktree).decode("ascii").strip()
            tree_after = git("rev-parse", "--verify", "HEAD^{tree}", cwd=validation_worktree).decode("ascii").strip()
            if (
                executed.returncode != 0
                or len(executed.stdout) > 1024 * 1024
                or len(executed.stderr) > 1024 * 1024
                or status_after != status_before
                or head_after != head_before
                or tree_after != tree_before
            ):
                raise ProjectStateError("abandoned no-change validation did not pass")
        finally:
            removed = subprocess.run(
                ["git", "worktree", "remove", "--force", str(validation_worktree)],
                cwd=self.project,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if removed.returncode:
                raise ProjectStateError("abandoned no-change validation cleanup failed")
        validation = {
            "result": "passed",
            "command": argv,
            "accepted_commit": base,
            "head_before": head_before,
            "tree_before": tree_before,
            "status_before_digest": hashlib.sha256(status_before).hexdigest(),
            "head_after": head_after,
            "tree_after": tree_after,
            "status_after_digest": hashlib.sha256(status_after).hexdigest(),
            "exit_code": executed.returncode,
            "stdout_digest": hashlib.sha256(executed.stdout).hexdigest(),
            "stderr_digest": hashlib.sha256(executed.stderr).hexdigest(),
        }
        validation["digest"] = hashlib.sha256(_canonical(validation)).hexdigest()
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                current = self._read_state_strict(anchor_id)
                if current["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                current_lane = next(
                    (item for item in current["lanes"] if item.get("lane_id") == lane_id),
                    None,
                )
                if current_lane != lane:
                    raise ProjectStateError("abandoned no-change lane binding changed")
                reservations = [
                    {
                        key: scope[key]
                        for key in (
                            "kind", "path", "mode", "sequence", "reservation", "phase", "status"
                        )
                    }
                    for scope in current["scopes"]
                    if scope.get("owner") == lane_id
                    and scope.get("kind") in _SCOPE_KIND_ORDER
                    and scope.get("mode") == "hard"
                    and scope.get("status") in {"active", "waiting", "cancelled"}
                ]
                reservations.sort(key=_scope_reservation_order)
                if not reservations:
                    raise ProjectStateError("abandoned no-change has no exact hard reservations")
                archive_parent = self.anchor_path(anchor_id) / "no-op-archives"
                _ensure_private_directory(archive_parent)
                _write_exclusive_bytes(archive_parent / f"{archive_digest}.diff", diff_archive)
                candidate = {
                    "schema": "project-scope-integration-acceptance-v2",
                    "kind": "abandoned-no-change",
                    "anchor_id": anchor_id,
                    "lane_id": lane_id,
                    "session": session,
                    "writer": writer,
                    "terminal_archive": safe_stop["terminal_archive"],
                    "admitted_commit": base,
                    "accepted_commit": base,
                    "validation": validation,
                    "reservations": reservations,
                    "no_op_archive": archive_digest,
                    "generation": current["generation"] + 1,
                }
                candidate["acceptance_id"] = hashlib.sha256(_canonical(candidate)).hexdigest()
                current["integration_acceptances"].append(candidate)
                release_no_op_scopes(current, candidate)
                current["generation"] += 1
                _replace_json(self._state_path(anchor_id), current)
                return dict(candidate)

    def claim_next_integration_intent(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        executor_owner: str,
        owner_token: str,
        pid: int,
        process_identity: str,
        checkout: Mapping[str, Any],
        requested_version_target: str | None = None,
        version_surfaces: Mapping[str, bytes] | None = None,
    ) -> dict[str, Any] | None:
        """Claim the sole executor and allocate a never-reused queue ticket."""

        parsed_checkout = _validate_integration_checkout(dict(checkout))
        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not isinstance(executor_owner, str)
            or not executor_owner
            or len(executor_owner) > 128
            or not _is_hex_identifier(owner_token)
            or not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid < 1
            or not isinstance(process_identity, str)
            or not process_identity
            or len(process_identity) > 256
            or parsed_checkout is None
            or (requested_version_target is None)
            != (version_surfaces is None)
        ):
            raise ProjectStateError("expected project generation is invalid")
        version_request: dict[str, Any] | None = None
        version_payload: dict[str, str] | None = None
        if requested_version_target is not None:
            if (
                executor_owner != "root"
                or not _VERSION_TARGET.fullmatch(requested_version_target)
                or not isinstance(version_surfaces, Mapping)
                or set(version_surfaces) != set(_VERSION_SURFACES)
                or any(
                    not isinstance(version_surfaces[path], bytes)
                    or len(version_surfaces[path]) > 1024 * 1024
                    for path in _VERSION_SURFACES
                )
            ):
                raise ProjectStateError(
                    "root version finalization input is invalid"
                )
            version_payload = {
                path: version_surfaces[path].hex()
                for path in _VERSION_SURFACES
            }
            bounded_payload = dict(version_payload)
            bounded_payload["digest"] = _digest(bounded_payload)
            if len(_canonical(bounded_payload) + b"\n") > MAX_JSON_BYTES:
                raise ProjectStateError(
                    "root version finalization payload exceeds bounded JSON size"
                )
            payload_digest = hashlib.sha256(
                _canonical(version_payload)
            ).hexdigest()
            stable = {
                "requested_target": requested_version_target,
                "surfaces": list(_VERSION_SURFACES),
                "payload_digest": payload_digest,
            }
            version_request = {
                "schema": "project-version-finalization-v1",
                "owner": "root",
                **stable,
                "surface_digest": hashlib.sha256(
                    _canonical(stable)
                ).hexdigest(),
            }
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                if (
                    state["state"] != "clean"
                    or state["integration_checkout"] != parsed_checkout
                ):
                    raise ProjectStateError(
                        "integration executor checkout binding changed"
                    )
                in_progress = [
                    item for item in state["integration_queue"]
                    if item["status"] in {
                        "integrating", "candidate", "validated", "cas-applied", "accepted"
                    }
                ]
                if len(in_progress) > 1:
                    raise ProjectStateError("integration queue lost single-writer serialization")
                intent = in_progress[0] if in_progress else None
                if intent is None:
                    queued = [
                        item for item in state["integration_queue"]
                        if item["status"] == "queued"
                    ]
                    if not queued:
                        return None
                    intent = min(
                        queued,
                        key=lambda item: (
                            0
                            if item["queue_class"] == "dependency-unblocking"
                            else 1,
                            item["enqueue_generation"],
                            item["intent_id"],
                        ),
                    )
                if (
                    version_request is not None
                    and intent["version_finalization"] is None
                ):
                    lane_session = _validate_lane_session(
                        state["lane_session"],
                    )
                    if lane_session is None:
                        raise ProjectStateError(
                            "version finalization lane session is unavailable"
                        )
                    current_target = _version_at_integration_ref(
                        self.project,
                        str(lane_session["integration_ref"]),
                    )
                    requested_order = _version_order(
                        str(requested_version_target),
                    )
                    issued_targets = [
                        str(item["version_finalization"]["requested_target"])
                        for item in state["integration_queue"]
                        if item is not intent
                        and isinstance(
                            item.get("version_finalization"),
                            Mapping,
                        )
                    ]
                    if (
                        requested_order <= _version_order(current_target)
                        or any(
                            requested_order <= _version_order(target)
                            for target in issued_targets
                        )
                    ):
                        raise ProjectStateError(
                            "version finalization target would not advance integration order"
                        )
                executor = state["integration_executor"]
                if executor is not None:
                    same_owner = (
                        executor["owner"] == executor_owner
                        and executor["owner_token"] == owner_token
                        and executor["pid"] == pid
                        and executor["process_identity"]
                        == process_identity
                        and executor["intent_id"] == intent["intent_id"]
                        and executor["checkout"] == parsed_checkout
                    )
                    if same_owner:
                        if (
                            version_request is not None
                            and intent["version_finalization"]
                            != version_request
                        ):
                            raise ProjectStateError(
                                "version finalization replay binding changed"
                            )
                        result = dict(intent)
                        result["executor_lease_id"] = executor["lease_id"]
                        return result
                    owner_state = _process_identity_state(
                        int(executor["pid"]),
                        str(executor["process_identity"]),
                    )
                    if owner_state == "running":
                        raise ProjectStateError(
                            "integration executor lease is held by a live owner"
                        )
                    if owner_state != "stopped":
                        raise ProjectStateError(
                            "integration executor process state is unknown"
                        )
                if state["integration_fence"] is not None and (
                    state["integration_fence"]["intent_id"]
                    != intent["intent_id"]
                ):
                    raise ProjectStateError(
                        "integration ref is fenced for another intent"
                    )
                if intent["status"] == "queued":
                    intent["status"] = "integrating"
                    intent["ticket"] = state["integration_next_ticket"]
                    state["integration_next_ticket"] += 1
                if version_request is not None:
                    if intent["version_finalization"] is None:
                        if not any(
                            item.get("kind") == "contract"
                            and item.get("path") == "version-metadata"
                            and item.get("mode") == "hard"
                            and item.get("status") == "active"
                            for item in intent["result"]["reservations"]
                        ):
                            raise ProjectStateError(
                                "root finalizer lacks contract:version-metadata ownership"
                            )
                        if any(
                            item.get("version_finalization", {}).get(
                                "requested_target"
                            )
                            == requested_version_target
                            for item in state["integration_queue"]
                            if item is not intent
                        ):
                            raise ProjectStateError(
                                "version finalization target was already issued"
                            )
                        assert version_payload is not None
                        payload_parent = (
                            self.anchor_path(anchor_id)
                            / "version-finalizations"
                        )
                        _ensure_private_directory(payload_parent)
                        payload_path = (
                            payload_parent
                            / f"{version_request['payload_digest']}.json"
                        )
                        if payload_path.exists():
                            stored_payload = {
                                key: value
                                for key, value in _read_json(
                                    payload_path
                                ).items()
                                if key != "digest"
                            }
                            if stored_payload != version_payload:
                                raise ProjectStateError(
                                    "version finalization payload changed"
                                )
                        else:
                            _write_exclusive_json(
                                payload_path,
                                version_payload,
                            )
                        intent["version_finalization"] = version_request
                    elif intent["version_finalization"] != version_request:
                        raise ProjectStateError(
                            "version finalization replay binding changed"
                        )
                claimed_generation = state["generation"] + 1
                lease_stable = {
                    "owner": executor_owner,
                    "owner_token": owner_token,
                    "pid": pid,
                    "process_identity": process_identity,
                    "intent_id": intent["intent_id"],
                    "checkout": parsed_checkout,
                    "claimed_generation": claimed_generation,
                }
                state["integration_executor"] = {
                    "schema": "project-integration-executor-v1",
                    "lease_id": hashlib.sha256(
                        _canonical(lease_stable)
                    ).hexdigest(),
                    **lease_stable,
                    "renewed_generation": claimed_generation,
                }
                if state["integration_fence"] is not None:
                    rebound_fence = {
                        **state["integration_fence"],
                        "executor_lease_id": state[
                            "integration_executor"
                        ]["lease_id"],
                        "generation": claimed_generation,
                    }
                    rebound_fence["digest"] = hashlib.sha256(
                        _canonical(
                            {
                                key: value
                                for key, value in rebound_fence.items()
                                if key != "digest"
                            }
                        )
                    ).hexdigest()
                    state["integration_fence"] = rebound_fence
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                result = dict(intent)
                result["executor_lease_id"] = state[
                    "integration_executor"
                ]["lease_id"]
                return result

    @staticmethod
    def _require_integration_executor(
        state: Mapping[str, Any],
        *,
        lease_id: str,
        intent_id: str,
    ) -> dict[str, Any]:
        executor = state.get("integration_executor")
        if (
            not isinstance(executor, dict)
            or executor.get("lease_id") != lease_id
            or executor.get("intent_id") != intent_id
        ):
            raise ProjectStateError(
                "integration transition lacks the executor lease"
            )
        return executor

    def renew_integration_executor(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lease_id: str,
        intent_id: str,
    ) -> dict[str, Any]:
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                executor = self._require_integration_executor(
                    state,
                    lease_id=lease_id,
                    intent_id=intent_id,
                )
                if _process_identity_state(
                    int(executor["pid"]),
                    str(executor["process_identity"]),
                ) != "running":
                    raise ProjectStateError(
                        "integration executor process identity is vacant"
                    )
                state["generation"] += 1
                executor["renewed_generation"] = state["generation"]
                _replace_json(self._state_path(anchor_id), state)
                return dict(executor)

    def release_integration_executor(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lease_id: str,
        intent_id: str,
    ) -> dict[str, Any]:
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=lease_id,
                    intent_id=intent_id,
                )
                state["integration_executor"] = None
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return self._read_state_strict(anchor_id)

    def prepare_integration_ref_cas(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                intent = next(
                    (
                        item
                        for item in state["integration_queue"]
                        if item["intent_id"] == intent_id
                    ),
                    None,
                )
                if (
                    not isinstance(intent, dict)
                    or intent["status"] != "validated"
                    or not isinstance(intent["candidate_commit"], str)
                ):
                    raise ProjectStateError(
                        "integration ref fence transition is invalid"
                    )
                existing = state["integration_fence"]
                if existing is not None:
                    if (
                        existing["intent_id"] == intent_id
                        and existing["executor_lease_id"]
                        == executor_lease_id
                    ):
                        return dict(existing)
                    raise ProjectStateError(
                        "integration ref is already fenced"
                    )
                fence = {
                    "schema": "project-integration-ref-fence-v1",
                    "intent_id": intent_id,
                    "executor_lease_id": executor_lease_id,
                    "admitted_commit": intent["admitted_tip"],
                    "candidate_commit": intent["candidate_commit"],
                    "state": "prepared",
                    "diagnostic": None,
                    "generation": state["generation"] + 1,
                }
                fence["digest"] = hashlib.sha256(
                    _canonical(fence)
                ).hexdigest()
                state["integration_fence"] = fence
                state["generation"] += 1
                state["integration_executor"]["renewed_generation"] = state[
                    "generation"
                ]
                _replace_json(self._state_path(anchor_id), state)
                return dict(fence)

    def quarantine_integration_ref(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
        diagnostic_code: str,
    ) -> dict[str, Any]:
        if diagnostic_code not in _INTEGRATION_DIAGNOSTICS:
            raise ProjectStateError("integration ref quarantine is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                fence = state["integration_fence"]
                if (
                    not isinstance(fence, dict)
                    or fence["intent_id"] != intent_id
                ):
                    raise ProjectStateError(
                        "integration ref quarantine lacks a fence"
                    )
                diagnostic = {
                    "code": diagnostic_code,
                    "digest": hashlib.sha256(
                        _canonical(
                            {
                                "intent_id": intent_id,
                                "code": diagnostic_code,
                                "candidate_commit": fence[
                                    "candidate_commit"
                                ],
                            }
                        )
                    ).hexdigest(),
                }
                updated = {
                    **fence,
                    "state": "quarantined",
                    "diagnostic": diagnostic,
                    "generation": state["generation"] + 1,
                }
                updated["digest"] = hashlib.sha256(
                    _canonical(
                        {
                            key: value
                            for key, value in updated.items()
                            if key != "digest"
                        }
                    )
                ).hexdigest()
                state["integration_fence"] = updated
                state["generation"] += 1
                state["integration_executor"]["renewed_generation"] = state[
                    "generation"
                ]
                _replace_json(self._state_path(anchor_id), state)
                return dict(updated)

    def mark_integration_pre_cas_stale(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
        observed_tip: str,
    ) -> dict[str, Any]:
        """Consume a prepared-fence CAS race without accepting its candidate."""

        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _is_hex_identifier(intent_id)
            or not _GIT_OBJECT.fullmatch(observed_tip)
        ):
            raise ProjectStateError("integration pre-CAS stale input is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                fence = state["integration_fence"]
                intent = next(
                    (
                        item
                        for item in state["integration_queue"]
                        if item["intent_id"] == intent_id
                    ),
                    None,
                )
                session = _validate_lane_session(state["lane_session"])
                if (
                    not isinstance(fence, dict)
                    or fence.get("intent_id") != intent_id
                    or fence.get("executor_lease_id")
                    != executor_lease_id
                    or fence.get("state") != "prepared"
                    or not isinstance(intent, dict)
                    or intent.get("status") != "validated"
                    or session is None
                    or observed_tip
                    in {
                        fence.get("admitted_commit"),
                        fence.get("candidate_commit"),
                    }
                ):
                    raise ProjectStateError(
                        "integration pre-CAS stale transition is invalid"
                    )
                actual = subprocess.run(
                    [
                        "git",
                        "rev-parse",
                        "--verify",
                        f"{session['integration_ref']}^{{commit}}",
                    ],
                    cwd=self.project,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if (
                    actual.returncode
                    or actual.stdout.decode("ascii", "ignore").strip()
                    != observed_tip
                ):
                    raise ProjectStateError(
                        "integration pre-CAS stale Git proof changed"
                    )
                diagnostic = {
                    "code": "cas-race",
                    "digest": hashlib.sha256(
                        _canonical(
                            {
                                "intent_id": intent_id,
                                "code": "cas-race",
                            }
                        )
                    ).hexdigest(),
                }
                intent["status"] = "stale"
                intent["diagnostic"] = diagnostic
                state["integration_fence"] = None
                state["generation"] += 1
                state["integration_executor"]["renewed_generation"] = state[
                    "generation"
                ]
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def read_version_finalization_payload(
        self,
        anchor_id: str,
        *,
        intent_id: str,
        executor_lease_id: str,
    ) -> dict[str, bytes] | None:
        observed = self.read_state(anchor_id)
        if observed.get("status") != "present":
            raise ProjectStateError("project state is unavailable")
        state = observed["state"]
        self._require_integration_executor(
            state,
            lease_id=executor_lease_id,
            intent_id=intent_id,
        )
        intent = next(
            (
                item
                for item in state["integration_queue"]
                if item["intent_id"] == intent_id
            ),
            None,
        )
        request = (
            intent.get("version_finalization")
            if isinstance(intent, Mapping)
            else None
        )
        if request is None:
            return None
        parsed = _validate_version_finalization(request)
        assert parsed is not None
        payload_path = (
            self.anchor_path(anchor_id)
            / "version-finalizations"
            / f"{parsed['payload_digest']}.json"
        )
        payload = {
            key: value
            for key, value in _read_json(payload_path).items()
            if key != "digest"
        }
        if (
            set(payload) != set(_VERSION_SURFACES)
            or hashlib.sha256(_canonical(payload)).hexdigest()
            != parsed["payload_digest"]
        ):
            raise ProjectStateError(
                "version finalization payload is invalid"
            )
        try:
            return {
                path: bytes.fromhex(payload[path])
                for path in _VERSION_SURFACES
            }
        except (TypeError, ValueError) as exc:
            raise ProjectStateError(
                "version finalization payload is invalid"
            ) from exc

    def record_integration_candidate(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        candidate_commit: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _is_hex_identifier(intent_id)
            or not _GIT_OBJECT.fullmatch(candidate_commit)
        ):
            raise ProjectStateError("integration candidate input is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                intent = next(
                    (item for item in state["integration_queue"] if item["intent_id"] == intent_id),
                    None,
                )
                if not isinstance(intent, dict):
                    raise ProjectStateError("integration intent is absent")
                if intent["status"] == "candidate" and intent["candidate_commit"] == candidate_commit:
                    return dict(intent)
                if intent["status"] != "integrating" or intent["candidate_commit"] is not None:
                    raise ProjectStateError("integration candidate transition is invalid")
                intent["candidate_commit"] = candidate_commit
                intent["status"] = "candidate"
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def mark_integration_validated(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        return self._advance_integration_intent(
            anchor_id,
            expected_generation=expected_generation,
            intent_id=intent_id,
            executor_lease_id=executor_lease_id,
            current="candidate",
            target="validated",
        )

    def mark_integration_cas_applied(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        return self._advance_integration_intent(
            anchor_id,
            expected_generation=expected_generation,
            intent_id=intent_id,
            executor_lease_id=executor_lease_id,
            current="validated",
            target="cas-applied",
        )

    def _advance_integration_intent(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
        current: str,
        target: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _is_hex_identifier(intent_id)
        ):
            raise ProjectStateError("integration intent input is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                intent = next(
                    (item for item in state["integration_queue"] if item["intent_id"] == intent_id),
                    None,
                )
                if not isinstance(intent, dict):
                    raise ProjectStateError("integration intent is absent")
                if intent["status"] == target:
                    return dict(intent)
                if intent["status"] != current:
                    raise ProjectStateError("integration intent transition is invalid")
                if target == "cas-applied":
                    fence = state["integration_fence"]
                    if (
                        not isinstance(fence, dict)
                        or fence.get("intent_id") != intent_id
                        or fence.get("executor_lease_id")
                        != executor_lease_id
                        or fence.get("candidate_commit")
                        != intent.get("candidate_commit")
                    ):
                        raise ProjectStateError(
                            "integration CAS lacks a durable ref fence"
                        )
                intent["status"] = target
                if target == "cas-applied":
                    fence = {
                        **state["integration_fence"],
                        "state": "cas-applied",
                        "diagnostic": None,
                        "generation": state["generation"] + 1,
                    }
                    fence["digest"] = hashlib.sha256(
                        _canonical(
                            {
                                key: value
                                for key, value in fence.items()
                                if key != "digest"
                            }
                        )
                    ).hexdigest()
                    state["integration_fence"] = fence
                state["generation"] += 1
                state["integration_executor"]["renewed_generation"] = state[
                    "generation"
                ]
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def mark_integration_blocked(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        status: str,
        diagnostic_code: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _is_hex_identifier(intent_id)
            or status not in {"blocked", "stale"}
            or diagnostic_code not in _INTEGRATION_DIAGNOSTICS
        ):
            raise ProjectStateError("integration blocked input is invalid")
        diagnostic = {
            "code": diagnostic_code,
            "digest": hashlib.sha256(
                _canonical({"intent_id": intent_id, "code": diagnostic_code}),
            ).hexdigest(),
        }
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                if state["integration_fence"] is not None:
                    raise ProjectStateError(
                        "fenced integration intent cannot become ordinarily blocked"
                    )
                intent = next(
                    (item for item in state["integration_queue"] if item["intent_id"] == intent_id),
                    None,
                )
                if not isinstance(intent, dict):
                    raise ProjectStateError("integration intent is absent")
                if intent["status"] == status and intent["diagnostic"] == diagnostic:
                    return dict(intent)
                if intent["status"] in {"released", "accepted", "no-op"}:
                    raise ProjectStateError("accepted integration intent cannot be blocked")
                intent["status"] = status
                intent["diagnostic"] = diagnostic
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def mark_integration_accepted(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        acceptance_id: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _is_hex_identifier(intent_id)
            or not _is_hex_identifier(acceptance_id)
        ):
            raise ProjectStateError("integration acceptance input is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                intent = next(
                    (item for item in state["integration_queue"] if item["intent_id"] == intent_id),
                    None,
                )
                if not isinstance(intent, dict):
                    raise ProjectStateError("integration intent is absent")
                if intent["status"] == "accepted" and intent["acceptance_id"] == acceptance_id:
                    return dict(intent)
                if intent["status"] != "cas-applied":
                    raise ProjectStateError("integration acceptance transition is invalid")
                fence = state["integration_fence"]
                if (
                    not isinstance(fence, Mapping)
                    or fence.get("intent_id") != intent_id
                    or fence.get("candidate_commit")
                    != intent.get("candidate_commit")
                ):
                    raise ProjectStateError(
                        "integration acceptance lacks a ref fence"
                    )
                acceptance = next(
                    (
                        item for item in state["integration_acceptances"]
                        if item.get("acceptance_id") == acceptance_id
                    ),
                    None,
                )
                if (
                    not isinstance(acceptance, dict)
                    or acceptance.get("lane_id") != intent["result"]["lane_id"]
                    or acceptance.get("accepted_commit") != intent["candidate_commit"]
                    or acceptance.get("admitted_commit") != intent["result"]["admitted_commit"]
                    or acceptance.get("terminal_archive") != intent["result"]["terminal_archive"]
                    or acceptance.get("writer") != intent["result"]["writer"]
                ):
                    raise ProjectStateError("registry-resident integration acceptance is absent")
                intent["acceptance_id"] = acceptance_id
                intent["status"] = "accepted"
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def mark_integration_released(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        intent_id: str,
        executor_lease_id: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected_generation, int)
            or expected_generation < 0
            or not _is_hex_identifier(intent_id)
        ):
            raise ProjectStateError("integration release input is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                self._require_integration_executor(
                    state,
                    lease_id=executor_lease_id,
                    intent_id=intent_id,
                )
                intent = next(
                    (item for item in state["integration_queue"] if item["intent_id"] == intent_id),
                    None,
                )
                if not isinstance(intent, dict):
                    raise ProjectStateError("integration intent is absent")
                if intent["status"] == "released":
                    return dict(intent)
                if intent["status"] != "accepted" or not isinstance(intent.get("acceptance_id"), str):
                    raise ProjectStateError("integration release transition is invalid")
                expected = intent["acceptance_id"]
                owned = [
                    scope for scope in state["scopes"]
                    if scope.get("owner") == intent["result"]["lane_id"]
                    and scope.get("kind") in _SCOPE_KIND_ORDER
                    and scope.get("mode") == "hard"
                ]
                if not owned or any(
                    scope.get("status") not in {"released", "cancelled"}
                    or (
                        scope.get("status") == "released"
                        and scope.get("release", {}).get("acceptance_id") != expected
                    )
                    for scope in owned
                ):
                    raise ProjectStateError("integration scopes were not released")
                intent["status"] = "released"
                intent["release_generation"] = state["generation"] + 1
                fence = state["integration_fence"]
                if (
                    not isinstance(fence, Mapping)
                    or fence.get("intent_id") != intent_id
                    or fence.get("candidate_commit")
                    != intent.get("candidate_commit")
                ):
                    raise ProjectStateError(
                        "integration release lacks its ref fence"
                    )
                state["integration_fence"] = None
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(intent)

    def begin_protected_adoption(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Publish only structurally bound protected-to-intent transitions."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition="intent",
            protected_adoption_receipt=None,
            safe_stop_transition=None,
            safe_stop_intent_id=None,
            scope_release_acceptance_id=None,
        )

    def rollback_protected_adoption(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Publish only adoption-intent-to-protected rollback transitions."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition="rollback",
            protected_adoption_receipt=None,
            safe_stop_transition=None,
            safe_stop_intent_id=None,
            scope_release_acceptance_id=None,
        )

    def accept_protected_adoption(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        integration_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Publish only a Git/provenance-verified intent-to-adopted transition."""

        return self._replace_lane_state(
            anchor_id,
            expected_generation=expected_generation,
            lanes=lanes,
            scopes=scopes,
            protected_transition="adopt",
            protected_adoption_receipt=integration_receipt,
            safe_stop_transition=None,
            safe_stop_intent_id=None,
            scope_release_acceptance_id=None,
        )

    def _replace_lane_state(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
        protected_transition: str | None,
        protected_adoption_receipt: Mapping[str, Any] | None,
        safe_stop_transition: str | None,
        safe_stop_intent_id: str | None,
        scope_release_acceptance_id: str | None,
        runtime_cancellation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if protected_transition not in {None, "intent", "rollback", "adopt"}:
            raise ProjectStateError("protected transition is invalid")
        if (protected_transition == "adopt") != (
            protected_adoption_receipt is not None
        ):
            raise ProjectStateError("protected adoption receipt is invalid")
        if safe_stop_transition not in {None, "request", "consume", "complete"}:
            raise ProjectStateError("safe-stop transition is invalid")
        if (safe_stop_transition is None) != (safe_stop_intent_id is None):
            raise ProjectStateError("safe-stop intent binding is invalid")
        if safe_stop_intent_id is not None and not _is_hex_identifier(safe_stop_intent_id):
            raise ProjectStateError("safe-stop intent binding is invalid")
        if scope_release_acceptance_id is not None and not _is_hex_identifier(scope_release_acceptance_id):
            raise ProjectStateError("integration acceptance binding is invalid")
        if (
            runtime_cancellation is not None
            and (
                not isinstance(runtime_cancellation, Mapping)
                or set(runtime_cancellation) != {"lane_id", "job_id"}
                or not isinstance(runtime_cancellation.get("lane_id"), str)
                or not _LANE_ID.fullmatch(runtime_cancellation["lane_id"])
                or not isinstance(runtime_cancellation.get("job_id"), str)
                or not _RUNTIME_JOB_ID.fullmatch(
                    runtime_cancellation["job_id"]
                )
            )
        ):
            raise ProjectStateError("runtime cancellation binding is invalid")
        if not isinstance(expected_generation, int) or expected_generation < 0:
            raise ProjectStateError("expected project generation is invalid")
        validated_lanes = [_validate_lane_projection(value) for value in lanes]
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                if state["state"] != "clean":
                    raise ProjectStateError("breached project state cannot admit lanes")
                if (
                    state["integration_fence"] is not None
                    and scope_release_acceptance_id is None
                ):
                    raise ProjectStateError(
                        "integration ref is fenced pending acceptance"
                    )
                lane_session = _validate_lane_session(state["lane_session"])
                if lane_session is None:
                    raise ProjectStateError("lane session binding is absent")
                validated_scopes = [
                    _validate_project_scope(value, lane_session)
                    for value in scopes
                ]
                _validate_lane_scope_uniqueness(validated_lanes, validated_scopes)
                _validate_milestone_lane_projection(
                    state["milestones"],
                    validated_lanes,
                    validated_scopes,
                )
                if protected_adoption_receipt is not None:
                    _verify_protected_adoption_transition(
                        self.project,
                        lane_session,
                        state["scopes"],
                        validated_scopes,
                        protected_adoption_receipt,
                    )
                _validate_scope_projection_transition(
                    state["scopes"],
                    validated_scopes,
                    protected_transition=protected_transition,
                    scope_release_acceptance_id=scope_release_acceptance_id,
                )
                _validate_lane_projection_transition(
                    state["lanes"],
                    validated_lanes,
                    stale_acceptance_id=scope_release_acceptance_id,
                )
                claimed_runtime_lanes = {
                    str(job["lane_id"])
                    for job in state["runtime"]["jobs"]
                    if job.get("owner_digest") is not None
                }
                if any(
                    lane["lane_id"] in claimed_runtime_lanes
                    and lane.get("state") in {"cancelled", "closed"}
                    and lane.get("writer") is None
                    for lane in validated_lanes
                ):
                    raise ProjectStateError(
                        "active claimed runtime job blocks ordinary terminal transition"
                    )
                _validate_safe_stop_transition(
                    state["lanes"],
                    validated_lanes,
                    transition=safe_stop_transition,
                    intent_id=safe_stop_intent_id,
                    expected_generation=state["generation"],
                )
                self._validate_lane_writer_transitions(
                    state["lanes"],
                    validated_lanes,
                    lane_session,
                    safe_stop_transition=safe_stop_transition,
                )
                if any(
                    lane["common"] != lane_session["common"]
                    for lane in validated_lanes
                ):
                    raise ProjectStateError("project lane session identity drifted")
                if runtime_cancellation is not None:
                    lane_id = str(runtime_cancellation["lane_id"])
                    job_id = str(runtime_cancellation["job_id"])
                    old_lane = next(
                        (
                            item
                            for item in state["lanes"]
                            if item["lane_id"] == lane_id
                        ),
                        None,
                    )
                    new_lane = next(
                        (
                            item
                            for item in validated_lanes
                            if item["lane_id"] == lane_id
                        ),
                        None,
                    )
                    if (
                        not isinstance(old_lane, Mapping)
                        or not isinstance(new_lane, Mapping)
                        or new_lane.get("state")
                        not in {"cancelled", "closed"}
                        or new_lane.get("writer") is not None
                    ):
                        raise ProjectStateError(
                            "runtime cancellation lacks an unactivated terminal lane"
                        )
                    runtime = dict(state["runtime"])
                    jobs = [dict(job) for job in runtime["jobs"]]
                    completed = [
                        dict(job) for job in runtime["completed"]
                    ]
                    target = next(
                        (
                            job
                            for job in jobs
                            if job["job_id"] == job_id
                            and job["lane_id"] == lane_id
                        ),
                        None,
                    )
                    if (
                        target is None
                        or target.get("owner_digest") is not None
                        or target.get("status")
                        not in {"waiting-for-capacity", "running"}
                    ):
                        raise ProjectStateError(
                            "runtime cancellation target is not unclaimed"
                        )
                    jobs.remove(target)
                    target["status"] = "complete"
                    completed.append(target)
                    completed.sort(key=lambda item: item["ticket"])
                    runtime["jobs"] = jobs
                    runtime["completed"] = completed
                    _promote_runtime_jobs(runtime)
                    state["runtime"] = _validate_runtime(
                        runtime,
                        anchor_id=anchor_id,
                    )
                state["generation"] += 1
                state["lanes"] = validated_lanes
                state["scopes"] = validated_scopes
                _replace_json(self._state_path(anchor_id), state)
                return self._read_state_strict(anchor_id)

    # The methods below are named R-031 observers.  They only lstat/open/read
    # private records and deliberately never lock, mkdir, chmod, fsync, issue a
    # key, replace, unlink, start a subprocess, or repair state.
    def read_status(self, anchor_id: str | None = None) -> dict[str, Any]:
        del anchor_id
        try:
            self.i0_path.lstat()
        except FileNotFoundError:
            return {"status": "setup-required"}
        except OSError:
            return {"status": "indeterminate"}
        try:
            setup = self._setup()
        except ProjectStateError:
            return {"status": "indeterminate"}
        return {"status": "setup-ready", "key_id": setup["key_id"]}

    def read_setup(self, anchor_id: str | None = None) -> dict[str, Any]:
        del anchor_id
        return self.read_status()

    def read_anchor(self, anchor_id: str | None = None) -> dict[str, Any]:
        status = self.read_status()
        if status["status"] != "setup-ready":
            return status
        if anchor_id is None:
            return {"status": "absent"}
        try:
            self.anchor_path(anchor_id).lstat()
        except FileNotFoundError:
            return {"status": "absent"}
        except (OSError, ProjectStateError):
            return {"status": "indeterminate"}
        try:
            manifest = self._manifest(anchor_id)
        except ProjectStateError:
            return {"status": "indeterminate"}
        return {"status": "present", "anchor": {"anchor_id": anchor_id, "lock_id": manifest["lock_id"]}}

    def configure_runtime_capacity(
        self, anchor_id: str, *, expected_generation: int, capacity: int
    ) -> dict[str, Any]:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or not 1 <= capacity <= 10:
            raise ProjectStateError("runtime capacity must be from 1 through 10")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                runtime = dict(state["runtime"])
                if runtime["capacity"] == capacity:
                    return runtime
                if sum(job["status"] == "running" for job in runtime["jobs"]) > capacity:
                    raise ProjectStateError("runtime capacity cannot evict active jobs")
                runtime["capacity"] = capacity
                _promote_runtime_jobs(runtime)
                state["runtime"] = _validate_runtime(
                    runtime, anchor_id=anchor_id
                )
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(state["runtime"])

    def request_runtime_slot(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        job_id: str,
        lane_id: str | None = None,
        port: int | None = None,
        owner_digest: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(job_id, str) or not _RUNTIME_JOB_ID.fullmatch(job_id):
            raise ProjectStateError("runtime job identifier is invalid")
        lane_id = job_id if lane_id is None else lane_id
        if not isinstance(lane_id, str) or not _LANE_ID.fullmatch(lane_id):
            raise ProjectStateError("runtime lane identifier is invalid")
        if port is not None and (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535):
            raise ProjectStateError("runtime port is invalid")
        if owner_digest is not None and re.fullmatch(
            r"[0-9a-f]{64}",
            owner_digest,
        ) is None:
            raise ProjectStateError("runtime owner digest is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                runtime = dict(state["runtime"])
                jobs = [dict(job) for job in runtime["jobs"]]
                completed = [dict(job) for job in runtime["completed"]]
                existing = next(
                    (job for job in [*jobs, *completed] if job["job_id"] == job_id),
                    None,
                )
                if existing is not None:
                    if (
                        existing["lane_id"] != lane_id
                        or existing["port"] != port
                    ):
                        raise ProjectStateError("runtime job replay binding changed")
                    if (
                        owner_digest is not None
                        and existing["status"] == "running"
                    ):
                        current_owner = existing.get("owner_digest")
                        if current_owner is not None:
                            raise ProjectStateError(
                                "runtime job is owned by another dispatch"
                            )
                        if current_owner is None:
                            target = next(
                                job
                                for job in jobs
                                if job["job_id"] == job_id
                            )
                            target["owner_digest"] = owner_digest
                            runtime["jobs"] = jobs
                            runtime["completed"] = completed
                            state["runtime"] = _validate_runtime(
                                runtime,
                                anchor_id=anchor_id,
                            )
                            state["generation"] += 1
                            _replace_json(self._state_path(anchor_id), state)
                            result = dict(target)
                            result["_claim_acquired"] = True
                            return result
                    result = dict(existing)
                    result["_claim_acquired"] = False
                    return result
                ticket = runtime["next_ticket"]
                job = {
                    "job_id": job_id,
                    "lane_id": lane_id,
                    "ticket": ticket,
                    "status": "waiting-for-capacity",
                    "namespace": _runtime_namespace(anchor_id, job_id, ticket),
                    "namespaces": _runtime_namespaces(anchor_id, job_id, ticket),
                    "port": port,
                    "owner_digest": None,
                }
                jobs.append(job)
                runtime["next_ticket"] = ticket + 1
                runtime["jobs"] = jobs
                runtime["completed"] = completed
                _promote_runtime_jobs(runtime)
                if job["status"] == "running":
                    job["owner_digest"] = owner_digest
                state["runtime"] = _validate_runtime(
                    runtime, anchor_id=anchor_id
                )
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                result = dict(job)
                result["_claim_acquired"] = (
                    owner_digest is not None
                    and job["status"] == "running"
                )
                return result

    def release_runtime_slot(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        job_id: str,
        owner_digest: str | None = None,
    ) -> dict[str, Any]:
        if owner_digest is not None and re.fullmatch(
            r"[0-9a-f]{64}",
            owner_digest,
        ) is None:
            raise ProjectStateError("runtime owner digest is invalid")
        with _locked(self.lock_path):
            self._manifest(anchor_id)
            with _locked(self._anchor_state_lock_path(anchor_id)):
                state = self._read_state_strict(anchor_id)
                if state["generation"] != expected_generation:
                    raise ProjectStateError("project generation changed")
                runtime = dict(state["runtime"])
                jobs = [dict(job) for job in runtime["jobs"]]
                completed = [dict(job) for job in runtime["completed"]]
                target = next((job for job in jobs if job["job_id"] == job_id), None)
                already_completed = next(
                    (job for job in completed if job["job_id"] == job_id), None
                )
                if target is None:
                    if already_completed is not None:
                        if (
                            already_completed.get("owner_digest") is not None
                            and already_completed.get("owner_digest")
                            != owner_digest
                        ):
                            raise ProjectStateError(
                                "runtime job is owned by another dispatch"
                            )
                        return dict(already_completed)
                    raise ProjectStateError("runtime job is absent")
                if (
                    target.get("owner_digest") is not None
                    and target.get("owner_digest") != owner_digest
                ):
                    raise ProjectStateError(
                        "runtime job is owned by another dispatch"
                    )
                jobs.remove(target)
                target["status"] = "complete"
                completed.append(target)
                completed.sort(key=lambda item: item["ticket"])
                runtime["jobs"] = jobs
                runtime["completed"] = completed
                _promote_runtime_jobs(runtime)
                state["runtime"] = _validate_runtime(
                    runtime, anchor_id=anchor_id
                )
                state["generation"] += 1
                _replace_json(self._state_path(anchor_id), state)
                return dict(target)

    def read_state(self, anchor_id: str | None = None) -> dict[str, Any]:
        anchor = self.read_anchor(anchor_id)
        if anchor["status"] != "present":
            return anchor
        assert anchor_id is not None
        try:
            self._state_path(anchor_id).lstat()
        except FileNotFoundError:
            return {"status": "absent"}
        except (OSError, ProjectStateError):
            return {"status": "indeterminate"}
        try:
            state = self._read_state_strict(anchor_id)
        except ProjectStateError:
            return {"status": "indeterminate"}
        return {"status": "present", "state": state}

    def read_lanes(self, anchor_id: str | None = None) -> dict[str, Any]:
        state = self.read_state(anchor_id)
        return state if state["status"] != "present" else {"status": "present", "lanes": list(state["state"]["lanes"])}

    def read_milestones(self, anchor_id: str | None = None) -> dict[str, Any]:
        state = self.read_state(anchor_id)
        return state if state["status"] != "present" else {"status": "present", "milestones": list(state["state"]["milestones"])}

    def read_scopes(self, anchor_id: str | None = None) -> dict[str, Any]:
        state = self.read_state(anchor_id)
        return state if state["status"] != "present" else {"status": "present", "scopes": list(state["state"]["scopes"])}

    def read_private_source(self, anchor_id: str | None = None) -> dict[str, Any]:
        anchor = self.read_anchor(anchor_id)
        if anchor["status"] != "present":
            return anchor
        return {"status": "present", "private_source": {"anchor_id": anchor["anchor"]["anchor_id"]}}
