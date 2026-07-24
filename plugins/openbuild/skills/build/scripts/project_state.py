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
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from recovery_state import RecoveryRegistry, RecoveryStateError


SCHEMA_VERSION = 1
MAX_JSON_BYTES = 256 * 1024
_HEX_64 = frozenset("0123456789abcdef")

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
    raise ProjectStateError(
        f"write-through private-object publish failed: {ctypes.WinError(error)}"
    )


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


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    """Durably replace mutable state only; immutable anchor locks never use this."""
    _ensure_private_directory(path.parent)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
    _write_exclusive_json(temp, value)
    try:
        if os.name == "nt":
            _windows_move_write_through(temp, path, replace=True)
        else:
            os.replace(temp, path)
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
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/") or ".." in path.split("/"):
        raise ProjectStateError("scope path is not normalized")
    return dict(value)


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
                existing.get("state") != "waiting-for-scope"
                or lane.get("state") != "waiting-for-scope"
                or existing.get("writer") is not None
                or lane.get("writer") is not None
            )
        ):
            raise ProjectStateError("lane admitted base changed")
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
            }
            _write_exclusive_json(state_path, state)
            return self._read_state_strict(anchor_id)

    def _read_state_strict(self, anchor_id: str) -> dict[str, Any]:
        self._manifest(anchor_id)
        state = _read_json(self._state_path(anchor_id))
        required = {"schema", "generation", "epoch", "state", "registry", "incident_id", "lane_session", "lanes", "milestones", "scopes", "integration_acceptances", "digest"}
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
        if set(state) != required or state.get("schema") != SCHEMA_VERSION or not isinstance(state.get("generation"), int) or state["generation"] < 0 or state.get("epoch") != 0 or state.get("state") not in {"clean", "breach"}:
            raise ProjectStateError("project state schema is invalid")
        if (state["state"] == "clean") != (state["registry"] == "B0") or (state["state"] == "breach") != (isinstance(state["incident_id"], str) and state["registry"] is None):
            raise ProjectStateError("clean/breach state split is invalid")
        if not all(isinstance(state[key], list) for key in ("lanes", "milestones", "scopes", "integration_acceptances")):
            raise ProjectStateError("project state collections are invalid")
        lane_session = _validate_lane_session(state["lane_session"])
        validated_lanes = [_validate_lane_projection(value) for value in state["lanes"]]
        validated_scopes = [
            _validate_project_scope(value, lane_session)
            for value in state["scopes"]
        ]
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
            lane_head != accepted_commit
            or integration_tip != accepted_commit
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
                or tree_before != lane_tree
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
                if (
                    not isinstance(current_lane, dict)
                    or current_lane.get("state") != "waiting-for-integration"
                    or current_lane.get("writer") != acceptance.get("writer")
                    or current_lane.get("terminal_evidence") != acceptance.get("terminal_archive")
                    or current_lane.get("base") != acceptance.get("admitted_commit")
                ):
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
                _validate_lane_projection_transition(state["lanes"], validated_lanes)
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
                lane_session = _validate_lane_session(state["lane_session"])
                if lane_session is None:
                    raise ProjectStateError("lane session binding is absent")
                validated_scopes = [
                    _validate_project_scope(value, lane_session)
                    for value in scopes
                ]
                _validate_lane_scope_uniqueness(validated_lanes, validated_scopes)
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
