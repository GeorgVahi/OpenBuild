#!/usr/bin/env python3
"""Strict, bounded evidence and worktree fingerprint contract for OpenBuild discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NamedTuple


SCHEMA = "openbuild.discovery.v1"
INVENTORY = "git-tracked-untracked-nonignored-v1"
MAX_RESULT_BYTES = 64 * 1024
MAX_RESULT_STRING_BYTES = 32 * 1024
MAX_ITEMS = 64
MAX_FILES = 100_000
MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_SECONDS = 30.0
MAX_LINE_SPAN = 200
MAX_GITLINK_DEPTH = 16
IGNORED_EVIDENCE_SEGMENTS = {
    ".git",
    ".venv",
    ".cache",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "artifacts",
    "coverage",
    "dist",
    "generated",
    "node_modules",
    "out",
    "target",
    "vendor",
}
RESULT_FIELDS = {
    "schema",
    "worktree_fingerprint",
    "summary",
    "owners",
    "couplings",
    "tests",
    "flows",
    "constraints",
    "uncertainties",
}
FINGERPRINT_FIELDS = {"algorithm", "digest", "files", "bytes", "inventory"}
EVIDENCE_REQUIRED_FIELDS = {"path", "line_start", "line_end", "symbol", "reason"}
EVIDENCE_OPTIONAL_FIELDS = {"kind", "related_path"}


class DiscoveryContractError(RuntimeError):
    """The discovery proof is incomplete, stale, unsafe, or malformed."""


class FingerprintSnapshot(NamedTuple):
    public: dict[str, Any]
    paths: frozenset[str]
    line_counts: Mapping[str, int]


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _run_git(repo: Path, arguments: list[str], deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DiscoveryContractError("fingerprint-unavailable: time limit exceeded")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=False,
            capture_output=True,
            timeout=remaining,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DiscoveryContractError(f"fingerprint-unavailable: Git failed: {exc}") from exc
    if result.returncode != 0:
        raise DiscoveryContractError("fingerprint-unavailable: Git inventory failed")
    return result.stdout


def _normalize_git_path(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DiscoveryContractError("fingerprint-unavailable: Git path is not UTF-8") from exc
    if "\\" in value:
        raise DiscoveryContractError(
            "fingerprint-unavailable: Git path contains a literal backslash"
        )
    normalized = value
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or normalized != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise DiscoveryContractError("fingerprint-unavailable: unsafe Git path")
    return normalized


def _git_inventory(repo: Path, deadline: float) -> tuple[bytes, list[tuple[str, str, str]]]:
    staged = _run_git(repo, ["ls-files", "--stage", "-z"], deadline)
    untracked = _run_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"], deadline)
    entries: dict[str, tuple[str, str, str]] = {}
    for record in staged.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split(" ")
        except (ValueError, UnicodeDecodeError) as exc:
            raise DiscoveryContractError("fingerprint-unavailable: malformed Git index entry") from exc
        if stage != "0":
            raise DiscoveryContractError("fingerprint-unavailable: unmerged Git index entry")
        path = _normalize_git_path(raw_path)
        if path in entries:
            raise DiscoveryContractError("fingerprint-unavailable: duplicate Git path")
        entries[path] = (mode, oid, "tracked")
    for raw_path in untracked.split(b"\0"):
        if not raw_path:
            continue
        path = _normalize_git_path(raw_path)
        if path in entries:
            raise DiscoveryContractError("fingerprint-unavailable: duplicate Git path")
        entries[path] = ("000000", "0" * 40, "untracked")
    ordered = [entries[path] for path in sorted(entries)]
    ordered_with_paths = [
        (path, entries[path][0], entries[path][1]) for path in sorted(entries)
    ]
    if len(ordered) > MAX_FILES:
        raise DiscoveryContractError("fingerprint-unavailable: file limit exceeded")
    folded: dict[str, str] = {}
    for path in entries:
        key = path.casefold()
        if key in folded and folded[key] != path:
            raise DiscoveryContractError("fingerprint-unavailable: case-colliding Git paths")
        folded[key] = path
    return staged + b"\0--untracked--\0" + untracked, ordered_with_paths


def _is_link_or_reparse(info: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(info, "st_file_attributes", 0)
    if not isinstance(attributes, int):
        attributes = 0
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _fingerprint_contained_path(
    repo: Path,
    relative: str,
    *,
    allow_final_symlink: bool,
    field: str,
) -> tuple[Path, os.stat_result]:
    root = repo.resolve()
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = current.lstat()
        except OSError as exc:
            raise DiscoveryContractError(
                f"fingerprint-unavailable: unreadable {field} path"
            ) from exc
        if _is_link_or_reparse(info):
            if (
                allow_final_symlink
                and index == len(parts) - 1
                and stat.S_ISLNK(info.st_mode)
            ):
                continue
            raise DiscoveryContractError(
                f"fingerprint-unavailable: {field} path contains a link or reparse point"
            )
    containment_target = current.parent if allow_final_symlink else current
    try:
        containment_target.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise DiscoveryContractError(
            f"fingerprint-unavailable: {field} path resolves outside repository"
        ) from exc
    return current, info


def _fingerprint_regular_path(repo: Path, relative: str) -> tuple[Path, os.stat_result]:
    return _fingerprint_contained_path(
        repo,
        relative,
        allow_final_symlink=False,
        field="regular-file",
    )


def _fingerprint_symlink_path(repo: Path, relative: str) -> tuple[Path, os.stat_result]:
    path, info = _fingerprint_contained_path(
        repo,
        relative,
        allow_final_symlink=True,
        field="symlink",
    )
    if not stat.S_ISLNK(info.st_mode):
        raise DiscoveryContractError("fingerprint-unavailable: symlink path changed type")
    return path, info


def _fingerprint_gitlink_path(repo: Path, relative: str) -> tuple[Path, os.stat_result]:
    path, info = _fingerprint_contained_path(
        repo,
        relative,
        allow_final_symlink=False,
        field="gitlink",
    )
    if not stat.S_ISDIR(info.st_mode):
        raise DiscoveryContractError("fingerprint-unavailable: gitlink is not a directory")
    return path, info


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def read_regular_file_no_follow(
    path: Path,
    *,
    maximum_bytes: int | None = None,
) -> bytes | None:
    """Read one stable regular file through its verified descriptor, or return missing."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DiscoveryContractError("artifact is unreadable") from exc
    if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise DiscoveryContractError("artifact is not a regular file")
    if maximum_bytes is not None and before.st_size > maximum_bytes:
        raise DiscoveryContractError("artifact exceeds the byte limit")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DiscoveryContractError("artifact is unreadable or changed before open") from exc
    try:
        opened_before = os.fstat(descriptor)
        after_open = path.lstat()
        if (
            _is_link_or_reparse(opened_before)
            or _is_link_or_reparse(after_open)
            or not stat.S_ISREG(opened_before.st_mode)
            or not stat.S_ISREG(after_open.st_mode)
            or _file_identity(before) != _file_identity(opened_before)
            or _file_identity(opened_before) != _file_identity(after_open)
        ):
            raise DiscoveryContractError("artifact identity changed before read")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if maximum_bytes is not None and total > maximum_bytes:
                raise DiscoveryContractError("artifact exceeds the byte limit")
            chunks.append(chunk)

        opened_after = os.fstat(descriptor)
        after = path.lstat()
        if (
            _is_link_or_reparse(opened_after)
            or _is_link_or_reparse(after)
            or not stat.S_ISREG(opened_after.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or _file_identity(opened_before) != _file_identity(opened_after)
            or _file_identity(opened_after) != _file_identity(after)
            or total != opened_before.st_size
        ):
            raise DiscoveryContractError("artifact identity changed during read")
        return b"".join(chunks)
    except OSError as exc:
        raise DiscoveryContractError("artifact is unreadable or changed during read") from exc
    finally:
        os.close(descriptor)


def _hash_regular_file(
    path: Path,
    *,
    repo: Path,
    relative: str,
    deadline: float,
    byte_budget: int,
) -> tuple[int, str, int]:
    checked_path, before = _fingerprint_regular_path(repo, relative)
    if checked_path != path:
        raise DiscoveryContractError("fingerprint-unavailable: regular-file path drifted")
    if not stat.S_ISREG(before.st_mode):
        raise DiscoveryContractError("fingerprint-unavailable: unsupported special file")
    if before.st_size > byte_budget:
        raise DiscoveryContractError("fingerprint-unavailable: byte limit exceeded")
    digest = hashlib.sha256()
    total = 0
    line_breaks = 0
    last_byte = b""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DiscoveryContractError("fingerprint-unavailable: unreadable file") from exc
    try:
        opened_before = os.fstat(descriptor)
        checked_path, after_open = _fingerprint_regular_path(repo, relative)
        if (
            checked_path != path
            or not stat.S_ISREG(opened_before.st_mode)
            or _file_identity(opened_before) != _file_identity(after_open)
            or _file_identity(before) != _file_identity(after_open)
        ):
            raise DiscoveryContractError(
                "fingerprint-unavailable: file identity changed before snapshot read"
            )
        while True:
            if time.monotonic() > deadline:
                raise DiscoveryContractError("fingerprint-unavailable: time limit exceeded")
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > byte_budget:
                raise DiscoveryContractError("fingerprint-unavailable: byte limit exceeded")
            digest.update(chunk)
            line_breaks += chunk.count(b"\n")
            last_byte = chunk[-1:]
        opened_after = os.fstat(descriptor)
        checked_path, after = _fingerprint_regular_path(repo, relative)
        if (
            checked_path != path
            or _file_identity(opened_before) != _file_identity(opened_after)
            or _file_identity(opened_after) != _file_identity(after)
            or total != opened_before.st_size
        ):
            raise DiscoveryContractError("fingerprint-unavailable: file changed during snapshot")
    except OSError as exc:
        raise DiscoveryContractError("fingerprint-unavailable: unreadable file") from exc
    finally:
        os.close(descriptor)
    line_count = line_breaks + (1 if total and last_byte != b"\n" else 0)
    return total, digest.hexdigest(), line_count


def _submodule_marker(repo: Path, relative: str, oid: str, deadline: float) -> bytes:
    output = _run_git(repo, ["submodule", "status", "--", relative], deadline).rstrip(
        b"\r\n"
    )
    if not output:
        output = f"-{oid} {relative}".encode("utf-8")
    return output


def _checked_out_gitlink_state(
    path: Path,
    deadline: float,
    *,
    max_files: int,
    max_bytes: int,
    depth: int,
) -> tuple[bytes, int, int]:
    top_level = _run_git(path, ["rev-parse", "--show-toplevel"], deadline).strip()
    try:
        nested_root = Path(top_level.decode("utf-8")).resolve(strict=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise DiscoveryContractError(
            "fingerprint-unavailable: unreadable checked-out gitlink root"
        ) from exc
    if nested_root != path.resolve(strict=True):
        raise DiscoveryContractError(
            "fingerprint-unavailable: checked-out gitlink resolves to another repository"
        )
    head = _run_git(path, ["rev-parse", "--verify", "HEAD"], deadline).strip()
    try:
        head.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DiscoveryContractError(
            "fingerprint-unavailable: malformed checked-out gitlink HEAD"
        ) from exc
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DiscoveryContractError("fingerprint-unavailable: time limit exceeded")
    nested = compute_worktree_fingerprint(
        path,
        max_files=max_files,
        max_bytes=max_bytes,
        max_seconds=remaining,
        _depth=depth,
    )
    state = _canonical_json_bytes(
        {
            "head": head.decode("ascii"),
            "worktree_fingerprint": nested.public,
        }
    )
    return state, int(nested.public["files"]), int(nested.public["bytes"])


def _hash_symlink(path: Path, *, repo: Path, relative: str) -> bytes:
    checked_path, before = _fingerprint_symlink_path(repo, relative)
    if checked_path != path:
        raise DiscoveryContractError("fingerprint-unavailable: symlink path drifted")
    try:
        target = os.readlink(path).encode("utf-8")
    except (OSError, UnicodeEncodeError) as exc:
        raise DiscoveryContractError("fingerprint-unavailable: unreadable symlink") from exc
    checked_path, after = _fingerprint_symlink_path(repo, relative)
    if checked_path != path or _file_identity(before) != _file_identity(after):
        raise DiscoveryContractError("fingerprint-unavailable: symlink changed during snapshot")
    return target


def _hash_gitlink(
    path: Path,
    *,
    repo: Path,
    relative: str,
    oid: str,
    deadline: float,
    max_files: int,
    byte_budget: int,
    depth: int,
) -> tuple[bytes, int, int]:
    checked_path, before = _fingerprint_gitlink_path(repo, relative)
    if checked_path != path:
        raise DiscoveryContractError("fingerprint-unavailable: gitlink path drifted")
    marker_before = _submodule_marker(repo, relative, oid, deadline)
    if marker_before.startswith(b"-"):
        state_before, nested_files_before, nested_bytes_before = (
            b"uninitialized\0" + oid.encode("ascii"),
            0,
            0,
        )
    else:
        state_before, nested_files_before, nested_bytes_before = (
            _checked_out_gitlink_state(
                path,
                deadline,
                max_files=max_files,
                max_bytes=byte_budget,
                depth=depth,
            )
        )
    marker_after = _submodule_marker(repo, relative, oid, deadline)
    if marker_after.startswith(b"-"):
        state_after, nested_files_after, nested_bytes_after = (
            b"uninitialized\0" + oid.encode("ascii"),
            0,
            0,
        )
    else:
        state_after, nested_files_after, nested_bytes_after = (
            _checked_out_gitlink_state(
                path,
                deadline,
                max_files=max_files,
                max_bytes=byte_budget,
                depth=depth,
            )
        )
    checked_path, after = _fingerprint_gitlink_path(repo, relative)
    if (
        checked_path != path
        or _file_identity(before) != _file_identity(after)
        or marker_before != marker_after
        or state_before != state_after
        or nested_files_before != nested_files_after
        or nested_bytes_before != nested_bytes_after
    ):
        raise DiscoveryContractError("fingerprint-unavailable: submodule changed during snapshot")
    return (
        marker_after + b"\0" + state_after,
        nested_files_after,
        nested_bytes_after,
    )


def compute_worktree_fingerprint(
    repo: Path,
    *,
    max_files: int = MAX_FILES,
    max_bytes: int = MAX_BYTES,
    max_seconds: float = MAX_SECONDS,
    _depth: int = 0,
) -> FingerprintSnapshot:
    repo = repo.resolve()
    if max_files <= 0 or max_bytes < 0 or max_seconds <= 0:
        raise DiscoveryContractError("fingerprint-unavailable: invalid bounds")
    if _depth > MAX_GITLINK_DEPTH:
        raise DiscoveryContractError("fingerprint-unavailable: gitlink depth limit exceeded")
    deadline = time.monotonic() + max_seconds
    first_raw, entries = _git_inventory(repo, deadline)
    if len(entries) > max_files:
        raise DiscoveryContractError("fingerprint-unavailable: file limit exceeded")
    digest = hashlib.sha256()
    total_bytes = 0
    total_files = len(entries)
    paths: list[str] = []
    line_counts: dict[str, int] = {}
    for relative, mode, oid in entries:
        if time.monotonic() > deadline:
            raise DiscoveryContractError("fingerprint-unavailable: time limit exceeded")
        path = repo / Path(*PurePosixPath(relative).parts)
        paths.append(relative)
        kind = "missing"
        size = 0
        content_digest = hashlib.sha256(b"").hexdigest()
        try:
            info = path.lstat()
        except FileNotFoundError:
            if mode == "000000":
                raise DiscoveryContractError("fingerprint-unavailable: inventory entry disappeared")
        except OSError as exc:
            raise DiscoveryContractError("fingerprint-unavailable: unreadable inventory entry") from exc
        else:
            if mode == "160000":
                remaining_files = max_files - total_files
                if remaining_files <= 0:
                    raise DiscoveryContractError("fingerprint-unavailable: file limit exceeded")
                marker, nested_files, nested_bytes = _hash_gitlink(
                    path,
                    repo=repo,
                    relative=relative,
                    oid=oid,
                    deadline=deadline,
                    max_files=remaining_files,
                    byte_budget=max_bytes - total_bytes,
                    depth=_depth + 1,
                )
                kind = "gitlink"
                size = nested_bytes
                total_files += nested_files
                if total_files > max_files:
                    raise DiscoveryContractError("fingerprint-unavailable: file limit exceeded")
                content_digest = hashlib.sha256(marker).hexdigest()
            elif stat.S_ISLNK(info.st_mode):
                target = _hash_symlink(path, repo=repo, relative=relative)
                kind = "symlink"
                size = len(target)
                content_digest = hashlib.sha256(target).hexdigest()
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
                size, content_digest, line_count = _hash_regular_file(
                    path,
                    repo=repo,
                    relative=relative,
                    deadline=deadline,
                    byte_budget=max_bytes - total_bytes,
                )
                line_counts[relative] = line_count
            else:
                raise DiscoveryContractError("fingerprint-unavailable: unsupported special file")
        total_bytes += size
        if total_bytes > max_bytes:
            raise DiscoveryContractError("fingerprint-unavailable: byte limit exceeded")
        digest.update(
            _canonical_json_bytes(
                {
                    "path": relative,
                    "mode": mode,
                    "oid": oid,
                    "type": kind,
                    "bytes": size,
                    "sha256": content_digest,
                }
            )
        )
        digest.update(b"\n")
    second_raw, _second_entries = _git_inventory(repo, deadline)
    if first_raw != second_raw:
        raise DiscoveryContractError("fingerprint-unavailable: Git inventory changed during snapshot")
    public = {
        "algorithm": "sha256",
        "digest": digest.hexdigest(),
        "files": total_files,
        "bytes": total_bytes,
        "inventory": INVENTORY,
    }
    return FingerprintSnapshot(
        public=public,
        paths=frozenset(paths),
        line_counts=line_counts,
    )


def _bounded_string(value: Any, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise DiscoveryContractError(f"discovery result {field} must be a non-empty string")
    if len(value.encode("utf-8")) > maximum:
        raise DiscoveryContractError(f"discovery result {field} is too large")
    return value


def _reject_link_escape(repo: Path, relative: str, *, field: str) -> None:
    root = repo.resolve()
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        try:
            info = current.lstat()
        except OSError as exc:
            raise DiscoveryContractError(
                f"discovery result {field} is unreadable"
            ) from exc
        if _is_link_or_reparse(info):
            raise DiscoveryContractError(
                f"discovery result {field} is a symlink or junction"
            )
    try:
        current.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise DiscoveryContractError(
            f"discovery result {field} resolves outside repository"
        ) from exc


def _safe_evidence_path(
    value: Any,
    snapshot: FingerprintSnapshot,
    *,
    repo: Path,
    field: str,
) -> str:
    path = _bounded_string(value, field=field, maximum=1024)
    if "\\" in path:
        raise DiscoveryContractError(
            f"discovery result {field} contains a literal backslash"
        )
    normalized = path
    pure = PurePosixPath(normalized)
    if (
        pure.is_absolute()
        or normalized != pure.as_posix()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(part.casefold() in IGNORED_EVIDENCE_SEGMENTS for part in pure.parts)
        or normalized not in snapshot.paths
    ):
        raise DiscoveryContractError(f"discovery result {field} is unsafe or outside inventory")
    _reject_link_escape(repo, normalized, field=field)
    return normalized


def _validate_evidence_items(
    name: str,
    value: Any,
    *,
    repo: Path,
    snapshot: FingerprintSnapshot,
    require_nonempty: bool,
) -> int:
    if not isinstance(value, list) or len(value) > MAX_ITEMS or (require_nonempty and not value):
        raise DiscoveryContractError(f"discovery result {name} has invalid item count")
    string_bytes = 0
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DiscoveryContractError(f"discovery result {name}[{index}] must be an object")
        fields = set(item)
        if not EVIDENCE_REQUIRED_FIELDS <= fields or fields - (
            EVIDENCE_REQUIRED_FIELDS | EVIDENCE_OPTIONAL_FIELDS
        ):
            raise DiscoveryContractError(f"discovery result {name}[{index}] has invalid fields")
        relative = _safe_evidence_path(
            item["path"],
            snapshot,
            repo=repo,
            field=f"{name}[{index}].path",
        )
        start, end = item["line_start"], item["line_end"]
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start <= 0
            or end < start
            or end - start + 1 > MAX_LINE_SPAN
        ):
            raise DiscoveryContractError(f"discovery result {name}[{index}] has invalid line range")
        line_count = snapshot.line_counts.get(relative)
        if line_count is None or end > line_count:
            raise DiscoveryContractError(f"discovery result {name}[{index}] line range is outside file")
        for key, maximum in (("symbol", 256), ("reason", 512), ("kind", 128)):
            if key in item:
                string_bytes += len(
                    _bounded_string(
                        item[key],
                        field=f"{name}[{index}].{key}",
                        maximum=maximum,
                    ).encode("utf-8")
                )
        if "related_path" in item:
            related = _safe_evidence_path(
                item["related_path"],
                snapshot,
                repo=repo,
                field=f"{name}[{index}].related_path",
            )
            string_bytes += len(related.encode("utf-8"))
        string_bytes += len(relative.encode("utf-8"))
    return string_bytes


def _validate_public_fingerprint(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != FINGERPRINT_FIELDS:
        raise DiscoveryContractError("discovery result fingerprint has invalid fields")
    digest = value.get("digest")
    files = value.get("files")
    byte_count = value.get("bytes")
    if (
        value.get("algorithm") != "sha256"
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or isinstance(files, bool)
        or not isinstance(files, int)
        or files < 0
        or isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
        or value.get("inventory") != INVENTORY
    ):
        raise DiscoveryContractError("discovery result fingerprint is malformed")


def validate_discovery_object(
    value: Any,
    *,
    repo: Path,
    expected: FingerprintSnapshot,
) -> None:
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise DiscoveryContractError("discovery result has unknown or missing top-level fields")
    if value.get("schema") != SCHEMA:
        raise DiscoveryContractError("discovery result schema is not openbuild.discovery.v1")
    fingerprint = value.get("worktree_fingerprint")
    _validate_public_fingerprint(fingerprint)
    _validate_public_fingerprint(expected.public)
    if fingerprint != expected.public:
        raise DiscoveryContractError("discovery result fingerprint does not match owner snapshot")
    string_bytes = len(
        _bounded_string(value.get("summary"), field="summary", maximum=2048).encode("utf-8")
    )
    for name in ("owners", "couplings", "tests", "flows"):
        string_bytes += _validate_evidence_items(
            name,
            value.get(name),
            repo=repo,
            snapshot=expected,
            require_nonempty=name in {"owners", "tests"},
        )
    for name in ("constraints", "uncertainties"):
        items = value.get(name)
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise DiscoveryContractError(f"discovery result {name} has invalid item count")
        for index, item in enumerate(items):
            string_bytes += len(
                _bounded_string(
                    item,
                    field=f"{name}[{index}]",
                    maximum=512,
                ).encode("utf-8")
            )
    if string_bytes > MAX_RESULT_STRING_BYTES:
        raise DiscoveryContractError("discovery result string budget exceeded")


def validate_discovery_result(
    result_path: Path,
    *,
    repo: Path,
    expected_public: Mapping[str, Any],
) -> FingerprintSnapshot:
    try:
        raw = read_regular_file_no_follow(
            result_path,
            maximum_bytes=MAX_RESULT_BYTES,
        )
    except DiscoveryContractError as exc:
        raise DiscoveryContractError("discovery result artifact is missing or unreadable") from exc
    if raw is None:
        raise DiscoveryContractError("discovery result artifact is missing or unreadable")
    if not raw:
        raise DiscoveryContractError("discovery result artifact is empty or too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryContractError("discovery result artifact is not strict UTF-8 JSON") from exc
    post = compute_worktree_fingerprint(repo)
    if dict(expected_public) != post.public:
        raise DiscoveryContractError("discovery worktree fingerprint drifted")
    validate_discovery_object(value, repo=repo.resolve(), expected=post)
    return post


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("--repo", required=True)
    args = parser.parse_args()
    if args.command == "fingerprint":
        snapshot = compute_worktree_fingerprint(Path(args.repo))
        print(json.dumps(snapshot.public, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except DiscoveryContractError as exc:
        print(str(exc), file=os.sys.stderr)
        raise SystemExit(2)
