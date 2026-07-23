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
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence


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


def _validate_lane_session(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "common",
        "integration_ref",
        "reader_floor",
    }:
        raise ProjectStateError("lane session binding is invalid")
    integration_ref = value.get("integration_ref")
    if (
        not isinstance(integration_ref, str)
        or not _GIT_REF.fullmatch(integration_ref)
        or integration_ref.endswith(("/", "."))
        or ".." in integration_ref.split("/")
        or value.get("reader_floor") != "2.3.6"
    ):
        raise ProjectStateError("lane session integration binding is invalid")
    return {
        "common": _validate_common_identity(value.get("common")),
        "integration_ref": integration_ref,
        "reader_floor": "2.3.6",
    }


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
            }
            _write_exclusive_json(state_path, state)
            return self._read_state_strict(anchor_id)

    def _read_state_strict(self, anchor_id: str) -> dict[str, Any]:
        self._manifest(anchor_id)
        state = _read_json(self._state_path(anchor_id))
        required = {"schema", "generation", "epoch", "state", "registry", "incident_id", "lane_session", "lanes", "milestones", "scopes", "digest"}
        legacy_required = required - {"lane_session"}
        legacy = set(state) == legacy_required
        if legacy:
            if (
                state.get("generation") != 0
                or any(state.get(key) != [] for key in ("lanes", "milestones", "scopes"))
            ):
                raise ProjectStateError("legacy project state schema is invalid")
            state = dict(state)
            state["lane_session"] = None
        if set(state) != required or state.get("schema") != SCHEMA_VERSION or not isinstance(state.get("generation"), int) or state["generation"] < 0 or state.get("epoch") != 0 or state.get("state") not in {"clean", "breach"}:
            raise ProjectStateError("project state schema is invalid")
        if (state["state"] == "clean") != (state["registry"] == "B0") or (state["state"] == "breach") != (isinstance(state["incident_id"], str) and state["registry"] is None):
            raise ProjectStateError("clean/breach state split is invalid")
        if not all(isinstance(state[key], list) for key in ("lanes", "milestones", "scopes")):
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
        return {key: value for key, value in state.items() if key != "digest"}

    def bind_lane_session(
        self,
        anchor_id: str,
        *,
        expected_generation: int,
        common: Mapping[str, Any],
        integration_ref: str,
    ) -> dict[str, Any]:
        if not isinstance(expected_generation, int) or expected_generation < 0:
            raise ProjectStateError("expected project generation is invalid")
        binding = _validate_lane_session(
            {
                "common": dict(common),
                "integration_ref": integration_ref,
                "reader_floor": "2.3.6",
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
                    if state["lane_session"] != binding:
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

        This deliberately has no policy: lifecycle validation remains in the lane
        owner, while this M1 owner retains the sole generationed state sink.
        """
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
