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
from typing import Any, Mapping, NamedTuple

if sys.version_info < (3, 11):
    raise SystemExit("OpenBuild agent_runner.py requires Python 3.11 or newer")

import tomllib

# The control plane is intentionally private and separate from the public
# receipt schema.  The script is also loaded directly by focused unit tests.
_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)
from recovery_state import RecoveryRegistry, RecoveryStateError


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
SCHEMA_VERSION = 1
OBSERVATION_BUDGET_SECONDS = 900
PACKAGED_PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
SEARCH_DEVELOPER_INSTRUCTIONS = (
    "You are the already-delegated read-only Explorer. Do not spawn or delegate to another agent.\n\n"
    "When code discovery, broad rg, route or symbol lookup, owner mapping, or cross-file evidence gathering is needed:\n"
    "- perform repository search, rg, rg --files, Get-Content, and local file reading yourself;\n"
    "- do not edit files, write configuration, make product or architecture decisions, commit, push, or answer the user;\n"
    "- return only a compact evidence map with path:line, symbol or route, a short snippet/signature, and why it matters;\n"
    "- include relevant negative results, confidence, and the search stop condition;\n"
    "- keep raw logs and large file dumps out of the result.\n\n"
    "The main process will do targeted reads only after your result, for verification before edits."
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


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(value)
    os.replace(temporary, path)


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


def windows_directory_is_private(path: Path, user_sid: str) -> bool:
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
        allowed_sids = {user_sid, "S-1-5-18"}
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
            if ace_sid not in allowed_sids:
                return False
            if ace_sid == user_sid:
                user_has_full_access = (
                    mask & 0x001F01FF == 0x001F01FF and ace_flags & 0x03 == 0x03
                )
        return user_has_full_access
    finally:
        kernel32.LocalFree(descriptor)


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
    """Force the child to reuse saved ChatGPT authentication, never an ambient API key."""

    blocked = API_CREDENTIALS | PROVIDER_ENVIRONMENT_OVERRIDES
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


def read_event_evidence(path: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "completed": False,
        "event_error": None,
        "failure_message": None,
        "terminal_event_count": 0,
        "terminal_event": None,
        "thread_id": None,
        "usage": None,
    }
    if not path.is_file():
        return evidence

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
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
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            evidence["thread_id"] = event["thread_id"]
        if event_type in TERMINAL_EVENTS:
            evidence["terminal_event_count"] += 1
            evidence["terminal_event"] = event_type
            if event_type == "turn.completed":
                evidence["usage"] = event.get("usage")
            else:
                error = event.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    evidence["failure_message"] = error["message"]
        elif event_type == "error" and not evidence["failure_message"]:
            message = event.get("message")
            if isinstance(message, str):
                evidence["failure_message"] = message

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
    if not path.is_file():
        return "missing final result artifact"
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
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


def default_run_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.gettempdir()) / "openbuild-agent-runs" / f"{stamp}-{uuid.uuid4().hex[:10]}"


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
    registry = recovery_registry_for_agent(agent_name, Path(repo_value))
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
            if cancel_path.is_file() and not cancellation_applied:
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


def _terminal_binding(receipt: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "run_dir",
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
    return {field: receipt.get(field) for field in fields}


def audit_guardian_health(run_dir: Path) -> None:
    ready_path = run_dir / "guardian-ready.json"
    failure_path = run_dir / "guardian-failure.json"
    if not ready_path.is_file() and not failure_path.is_file():
        return
    request = read_json(run_dir / "request.json")
    registry = recovery_registry_for_agent(request["profile"]["name"], Path(request["repo"]))
    lease_id = request.get("lease_id")
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
    raise RunnerError(
        "contained guardian failed after the durable process boundary; "
        "the writer lease is quarantined for manual reconciliation"
    )


def reconcile_implementation_registry(
    run_dir: Path,
    receipt: Mapping[str, Any],
    *,
    success_verification_digest: str | None = None,
) -> None:
    """Drive a terminal implementation receipt through one durable owner lifecycle."""
    if receipt.get("status") not in {"completed", "failed"} or receipt.get("process_tree_stopped") is not True:
        return
    request = read_json(run_dir / "request.json")
    agent_name = request["profile"]["name"]
    registry = recovery_registry_for_agent(agent_name, Path(request["repo"]))
    lease_id = request.get("lease_id")
    if registry is None or not isinstance(lease_id, str):
        return
    state = registry.state()
    lease = state.get("lease")
    if lease is None:
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
        except RecoveryStateError as exc:
            raise RunnerError(f"legacy implementation lease could not be released: {exc}") from exc
        return

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
        binding = _terminal_binding(receipt)
        binding_digest = sha256_bytes(_canonical_json_bytes(binding))
        state_name = lease.get("state")
        if state_name in {"running", "active"}:
            state = registry.record_terminal_evidence(
                lease_id,
                {
                    "success": receipt.get("status") == "completed",
                    "binding_digest": binding_digest,
                    "terminal_event": receipt.get("terminal_event"),
                },
                allowed_set_digest,
            )
            lease = state["lease"]
            state_name = lease["state"]
        elif lease.get("terminal_receipt", {}).get("binding_digest") != binding_digest:
            raise RecoveryStateError("terminal receipt binding drifted during reload")
        if state_name == "terminal-pending-stop":
            state = registry.prove_contained_tree_empty(
                lease_id,
                zero,
                allowed_set_digest,
            )
            lease = state["lease"]
            state_name = lease["state"]

        semantic_disposition = lease.get("semantic_disposition")
        if isinstance(semantic_disposition, dict):
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
            if semantic_disposition.get("checkpoint_invalidation") != "completed":
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
            verification_checkpoint = registry.revalidate_checkpoint(parent_checkpoint)
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
    except (OSError, RecoveryStateError) as exc:
        raise RunnerError(f"contained implementation terminalization failed closed: {exc}") from exc


def finalize_success_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    if (run_dir / "semantic-rejection.json").is_file():
        raise RunnerError("root success finalization is forbidden after semantic handoff rejection")
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt.get("status") != "completed":
        raise RunnerError("root success finalization requires an accepted completed runner receipt")
    request = read_json(run_dir / "request.json")
    registry = recovery_registry_for_agent(request["profile"]["name"], Path(request["repo"]))
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
    run_dir = Path(args.run_dir).expanduser().resolve()
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
    registry = recovery_registry_for_agent(request["profile"]["name"], Path(request["repo"]))
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


def authorize_recovery_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    checkpoint_path = Path(args.checkpoint_file).expanduser().resolve()
    prompt_path = Path(args.prompt_file).expanduser().resolve()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not repo.is_dir() or not checkpoint_path.is_file() or not prompt_path.is_file():
        raise RunnerError("recovery authorization requires an existing repo, checkpoint and prompt")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RunnerError("reserved recovery run directory must be absent or empty")
    lease_id = validate_lease_id("openbuild_implementation_fast", args.lease_id)
    if lease_id is None:
        raise RunnerError("recovery target lease ID is required")
    try:
        prompt_bytes = prompt_path.read_bytes()
        prompt_bytes.decode("utf-8")
        checkpoint = read_json(checkpoint_path)
        registry = recovery_registry_for_agent("openbuild_implementation_fast", repo)
        if registry is None:
            raise RecoveryStateError("implementation recovery registry is unavailable")
        state = registry.initialize()
        existing = state.get("lease")
        if isinstance(existing, dict):
            plan = existing.get("plan", {})
            if (
                existing.get("lease_id") != lease_id
                or existing.get("lease_kind") != "recovery-target"
                or plan.get("run_id") != run_dir.name
                or plan.get("prompt_sha256") != sha256_bytes(prompt_bytes)
                or existing.get("source_state_id") != checkpoint.get("source_state_id")
            ):
                raise RecoveryStateError("workspace is occupied by another recovery lifecycle")
            output = {
                "event": "recovery-target-reserved",
                "lease_id": lease_id,
                "grant_id": existing.get("grant_id"),
                "target_milestone": existing.get("target_milestone"),
                "allowed_set_digest": existing.get("allowed_set_digest"),
                "reconstructed": True,
            }
        else:
            checkpoint = registry.revalidate_checkpoint(checkpoint)
            grant = registry.grant_authorization(
                checkpoint,
                user_action_digest=args.user_action_digest,
                specification_revision=args.specification_revision,
            )
            registry.consume_grant_and_reserve(
                grant_id=grant["grant_id"],
                checkpoint=checkpoint,
                target_plan={
                    "lease_id": lease_id,
                    "run_id": run_dir.name,
                    "prompt_sha256": sha256_bytes(prompt_bytes),
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
    codex_exit_code, codex_exit_status = codex_exit_evidence_status(
        run_dir,
        expected_pid=codex_process.get("pid"),
        expected_identity=codex_process.get("identity"),
    )
    result_status = result_evidence_status(run_dir / "result.md")

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

    return {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(run_dir.resolve()),
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
        "configured_model": profile["model"],
        "model_reasoning_effort": profile["reasoning_effort"],
        "observed_agent": profile["name"] if status == "completed" else None,
        "observed_model": profile["model"] if status == "completed" else None,
        "sandbox": profile["sandbox"],
        "auth_mode": request["auth_mode"],
        "profile_source": request["profile_source"],
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
        "failure_message": (
            evidence["failure_message"]
            or evidence["event_error"]
            or (result_error if status == "failed" else None)
            or (exit_record or {}).get("failure_message")
            or (
                f"Codex exit evidence is {codex_exit_status}"
                if status == "failed" and evidence["completed"] and codex_exit_status != "valid"
                else None
            )
            or ("runner process exited without a terminal record" if status == "failed" else None)
        ),
        "usage": evidence["usage"],
        "artifacts": {
            "events": str((run_dir / "events.jsonl").resolve()),
            "stderr": str((run_dir / "stderr.log").resolve()),
            "result": str((run_dir / "result.md").resolve()),
            "codex_exit": str((run_dir / "codex-exit.json").resolve()),
            "codex_spawn": str((run_dir / "codex-spawn.json").resolve()),
        },
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


def start_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    prompt_file = Path(args.prompt_file).expanduser().resolve()
    if not repo.is_dir():
        raise RunnerError(f"repository/workspace directory does not exist: {repo}")
    if not prompt_file.is_file():
        raise RunnerError(f"prompt file does not exist: {prompt_file}")
    lease_id = validate_lease_id(args.agent, args.lease_id)
    allowed_files, specification_revision, recovery_target_milestone = validate_recovery_start_options(
        args.agent,
        getattr(args, "allowed_file", None),
        getattr(args, "specification_revision", None),
        getattr(args, "recovery_target_milestone", None),
    )
    try:
        source_prompt = prompt_file.read_bytes()
        task_prompt = source_prompt.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RunnerError(f"cannot read UTF-8 delegated prompt {prompt_file}: {exc}") from exc

    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else default_run_dir().resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RunnerError(f"run directory must be absent or empty: {run_dir}")
    ensure_private_run_dir(run_dir)

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()
    validate_subscription_configuration(codex_home, repo)
    profile = load_agent_profile(args.agent, repo=repo, codex_home=codex_home)
    codex_bin = resolve_codex_binary(args.codex_bin)
    environment = scrub_api_credentials(os.environ)
    auth_mode = require_chatgpt_login(codex_bin, environment)
    result_file = run_dir / "result.md"
    command = build_codex_command(
        codex_bin=codex_bin,
        profile=profile,
        repo=repo,
        result_file=result_file,
        is_git_repo=is_git_repository(repo),
    )
    effective_prompt(profile, args.task_name, task_prompt)
    prompt_snapshot = run_dir / "prompt.md"
    atomic_write_bytes(prompt_snapshot, source_prompt)
    request = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "agent_name": profile.name,
        "task_name": args.task_name.strip(),
        "lease_id": lease_id,
        "repo": str(repo),
        "codex_home": str(codex_home),
        "prompt_source": str(prompt_file),
        "prompt_file": str(prompt_snapshot),
        "prompt_sha256": sha256_bytes(source_prompt),
        "profile_source": str(profile.source),
        "profile": {
            "name": profile.name,
            "description": profile.description,
            "model": profile.model,
            "reasoning_effort": profile.reasoning_effort,
            "sandbox": profile.sandbox,
            "developer_instructions": profile.developer_instructions,
        },
        "auth_mode": auth_mode,
        "activation_timeout": args.activation_timeout,
        "command": command,
        "recovery_preflight": None,
        "recovery_parent_checkpoint": None,
        "recovery_capability_unavailable": None,
        "lifecycle_allowed_set_digest": "",
        "recovery_target": False,
        "containment_plan": None,
    }

    registry = recovery_registry_for_agent(args.agent, repo)
    registry_lease_id = lease_id
    recovery_target_lease: dict[str, Any] | None = None
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
    atomic_write_json(run_dir / "request.json", request)

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
                allowed_set_digest=(preflight or {}).get("allowed_set_digest", ""),
                recovery_capable=preflight is not None,
                source_state_id=(preflight or {}).get("source_state_id"),
                run_id=run_dir.name,
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

    worker: Any | None = None
    worker_record: dict[str, Any] = {}
    launch_mode = "unstarted"
    fallback_bind_attempted = False
    fallback_bind_verified = False
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
        raise RunnerError(f"{exc}; startup process tree stopped; artifacts: {run_dir}") from exc


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
    run_dir = Path(args.run_dir).expanduser().resolve()
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    reconcile_implementation_registry(run_dir, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 1 if receipt["status"] == "failed" else 0


def activate_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    audit_guardian_health(run_dir)
    receipt = public_receipt(run_dir)
    if receipt["status"] != "running":
        reconcile_implementation_registry(run_dir, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt["status"] == "completed" else 1
    if not receipt.get("codex_pid") or not receipt.get("codex_process_identity"):
        raise RunnerError("Codex process is not ready for activation")
    activation_path = run_dir / "activate.json"
    if activation_path.is_file():
        activation = read_json(activation_path)
        if (
            activation.get("codex_pid") != receipt["codex_pid"]
            or activation.get("codex_process_identity") != receipt["codex_process_identity"]
        ):
            raise RunnerError("existing activation does not match the live creation-bound Codex process")
    else:
        request_path = run_dir / "request.json"
        if request_path.is_file():
            request = read_json(request_path)
            registry = recovery_registry_for_agent(request["profile"]["name"], Path(request["repo"]))
            lease_id = request.get("lease_id")
            if registry is not None and isinstance(lease_id, str):
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
        atomic_write_json(
            activation_path,
            {
                **activation_window(),
                "codex_pid": receipt["codex_pid"],
                "codex_process_identity": receipt["codex_process_identity"],
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
    run_dir = Path(args.run_dir).expanduser().resolve()
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
    run_dir = Path(args.run_dir).expanduser().resolve()
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="start one explicit-model Codex agent asynchronously")
    start.add_argument("--agent", required=True, choices=sorted(SUPPORTED_AGENTS))
    start.add_argument("--task-name", required=True)
    start.add_argument("--repo", required=True)
    start.add_argument("--prompt-file", required=True)
    start.add_argument("--run-dir")
    start.add_argument("--lease-id")
    start.add_argument("--allowed-file", action="append", default=[])
    start.add_argument("--specification-revision")
    start.add_argument("--recovery-target-milestone")
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
    dispatch.add_argument("--prompt-file", required=True)
    dispatch.add_argument("--run-dir")
    dispatch.add_argument("--lease-id")
    dispatch.add_argument("--allowed-file", action="append", default=[])
    dispatch.add_argument("--specification-revision")
    dispatch.add_argument("--recovery-target-milestone")
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
    authorize = subparsers.add_parser("_authorize-recovery", help=argparse.SUPPRESS)
    authorize.add_argument("--repo", required=True)
    authorize.add_argument("--checkpoint-file", required=True)
    authorize.add_argument("--prompt-file", required=True)
    authorize.add_argument("--run-dir", required=True)
    authorize.add_argument("--lease-id", required=True)
    authorize.add_argument("--user-action-digest", required=True)
    authorize.add_argument("--specification-revision", required=True)
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
