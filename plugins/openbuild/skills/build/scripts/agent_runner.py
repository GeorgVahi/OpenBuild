#!/usr/bin/env python3
"""Run an OpenBuild custom-agent profile through an explicit Codex CLI model selection."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NamedTuple

if sys.version_info < (3, 11):
    raise SystemExit("OpenBuild agent_runner.py requires Python 3.11 or newer")

import tomllib


SUPPORTED_AGENTS = {
    "openbuild_search_separate",
    "openbuild_implementation_fast",
    "openbuild_implementation_balanced",
    "openbuild_implementation_strongest",
    "openbuild_review_fast",
    "openbuild_review_balanced",
    "openbuild_review_strong",
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
PACKAGED_PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
ACTIVE_WORKER_CHILD: Any | None = None
ACTIVE_WINDOWS_JOB: Any | None = None
ACTIVE_WORKER_FINALIZING = False


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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
    sandbox = _required_string(data, "sandbox_mode", path)
    required_sandbox = expected_sandbox(name)
    if sandbox != required_sandbox:
        raise RunnerError(
            f"{path}: {name} requires sandbox_mode={required_sandbox!r}, got {sandbox!r}"
        )

    return AgentProfile(
        name=name,
        description=_required_string(data, "description", path),
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox=sandbox,
        developer_instructions=_required_string(data, "developer_instructions", path),
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
    """Resolve immutable Spark or an exact project, user, then packaged role profile."""

    if agent_name not in SUPPORTED_AGENTS:
        raise RunnerError(f"unsupported OpenBuild agent: {agent_name}")
    if agent_name == "openbuild_search_separate":
        packaged = _matching_profiles(PACKAGED_PROFILE_DIR, agent_name)
        if len(packaged) != 1:
            raise RunnerError(
                "packaged openbuild_search_separate profile is missing or ambiguous; reinstall OpenBuild"
            )
        path, data = packaged[0]
        return _profile_from_data(data, path, agent_name)
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
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    return kernel32


def create_windows_kill_job() -> Any:
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
    ) or not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        error = ctypes.WinError()
        kernel32.CloseHandle(handle)
        raise RunnerError(f"cannot bind worker to Windows cleanup Job Object: {error}")
    return handle


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


def public_receipt(run_dir: Path) -> dict[str, Any]:
    request = read_json(run_dir / "request.json")
    profile = request["profile"]
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
    if exit_record:
        if exit_record.get("startup_process_stopped") is True:
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
        "activated": (run_dir / "activate.json").is_file(),
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


def start_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    prompt_file = Path(args.prompt_file).expanduser().resolve()
    if not repo.is_dir():
        raise RunnerError(f"repository/workspace directory does not exist: {repo}")
    if not prompt_file.is_file():
        raise RunnerError(f"prompt file does not exist: {prompt_file}")
    lease_id = validate_lease_id(args.agent, args.lease_id)
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
    }
    atomic_write_json(run_dir / "request.json", request)

    worker: Any | None = None
    worker_record: dict[str, Any] = {}
    runner_log = open_private_binary(run_dir / "runner.log", append=True)
    try:
        try:
            worker = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "_worker", "--run-dir", str(run_dir)],
                stdin=subprocess.DEVNULL,
                stdout=runner_log,
                stderr=runner_log,
                close_fds=True,
                **_background_options(),
            )
        finally:
            runner_log.close()
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
        if cleanup_errors:
            raise RunnerError(
                f"{exc}; startup cleanup was not confirmed for {run_dir}: {'; '.join(cleanup_errors)}"
            ) from exc
        if not startup_process_stopped:
            raise RunnerError(
                f"{exc}; startup cleanup is unconfirmed because creation-bound stopped-process "
                f"evidence is unavailable; artifacts: {run_dir}"
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
        if os.name == "nt" and ACTIVE_WINDOWS_JOB is None:
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
    receipt = public_receipt(Path(args.run_dir).expanduser().resolve())
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 1 if receipt["status"] == "failed" else 0


def activate_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    receipt = public_receipt(run_dir)
    if receipt["status"] != "running":
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
        atomic_write_json(
            activation_path,
            {
                "activated_at": utc_now(),
                "codex_pid": receipt["codex_pid"],
                "codex_process_identity": receipt["codex_process_identity"],
            },
        )
    receipt = public_receipt(run_dir)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 1 if receipt["status"] == "failed" else 0


def wait_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    deadline = time.monotonic() + args.timeout
    while True:
        receipt = public_receipt(run_dir)
        if receipt["status"] != "running":
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0 if receipt["status"] == "completed" else 1
        if time.monotonic() >= deadline:
            receipt["status"] = "timeout"
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 3
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
    receipt = public_receipt(run_dir)
    if receipt["status"] != "running":
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
    terminate_process_tree(worker_record, codex_record, args.grace_seconds)
    receipt = public_receipt(run_dir)
    if receipt["status"] == "completed":
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
    start.add_argument("--activation-timeout", type=float, default=300.0)
    start.add_argument("--codex-bin", default=os.environ.get("OPENBUILD_CODEX_BIN", "codex"))
    start.set_defaults(handler=start_run)

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
    wait.set_defaults(handler=wait_run)

    cancel = subparsers.add_parser("cancel", help="stop a running worker process tree")
    cancel.add_argument("--run-dir", required=True)
    cancel.add_argument("--grace-seconds", type=float, default=5.0)
    cancel.set_defaults(handler=cancel_run)

    worker = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--run-dir", required=True)
    worker.set_defaults(handler=lambda args: worker_run(Path(args.run_dir).resolve()))
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
