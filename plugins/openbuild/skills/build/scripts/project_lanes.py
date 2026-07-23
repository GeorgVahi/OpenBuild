"""Fail-closed R-031 M2 task-lane lifecycle owner.

It intentionally stops before scheduling and integration.  The
only mutable project record is ProjectStateStore's generationed lane projection.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from project_state import ProjectStateError, ProjectStateStore, _assert_no_link_or_reparse_ancestors, _identity, _is_link_or_reparse
from recovery_state import RecoveryRegistry, RecoveryStateError


class ProjectLaneError(RuntimeError):
    pass


_LANE = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_GIT_REF = re.compile(r"refs/[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}
)
PROJECT_LANE_READER_FLOOR = "2.3.6"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _safe_dir(path: Path) -> Path:
    path = Path(os.path.abspath(os.fspath(path)))
    _assert_no_link_or_reparse_ancestors(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProjectLaneError("Git path is unreadable") from exc
    if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ProjectLaneError("Git path is not a real directory")
    return path


class ProjectLaneCoordinator:
    """Coordinates independent Git worktree lanes bound to one common directory."""

    def __init__(
        self,
        checkout: Path,
        store: ProjectStateStore,
        anchor_id: str,
        *,
        recovery_root: Path,
        lane_root: Path,
        integration_ref: str,
        fault: str | None = None,
    ) -> None:
        self.checkout = _safe_dir(checkout)
        self.store = store
        self.anchor_id = anchor_id
        self.recovery_root = Path(recovery_root)
        self.lane_root = _safe_dir(lane_root)
        if (
            not isinstance(integration_ref, str)
            or not _GIT_REF.fullmatch(integration_ref)
            or integration_ref.endswith(("/", "."))
            or ".." in integration_ref.split("/")
        ):
            raise ProjectLaneError("integration ref is invalid")
        self.integration_ref = integration_ref
        self.fault = fault
        self.common = self._common_identity()
        self.base = self._git("rev-parse", "--verify", "HEAD").decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.base):
            raise ProjectLaneError("admitted Git base is invalid")
        self.integration_ref = self._bind_session(integration_ref)

    def _trip(self, stage: str) -> None:
        if self.fault == stage:
            raise ProjectLaneError(f"injected fault at {stage}")

    def _git(self, *args: str, cwd: Path | None = None, allow_failure: bool = False) -> bytes:
        result = subprocess.run(["git", *args], cwd=cwd or self.checkout, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode and not allow_failure:
            raise ProjectLaneError("Git lifecycle command failed")
        return result.stdout if result.returncode == 0 else b""

    def _git_checked_result(
        self,
        *args: str,
        cwd: Path | None = None,
        input_data: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.checkout,
            input=input_data,
            stdin=subprocess.DEVNULL if input_data is None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _common_identity(self, checkout: Path | None = None) -> dict[str, Any]:
        checkout = checkout or self.checkout
        raw = self._git("rev-parse", "--git-common-dir", cwd=checkout).strip()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectLaneError("Git common directory is not UTF-8") from exc
        path = Path(text)
        if not path.is_absolute():
            path = checkout / path
        path = _safe_dir(path)
        return {"path": str(path), "identity": list(_identity(path.lstat()))}

    def _state(self) -> dict[str, Any]:
        result = self.store.read_state(self.anchor_id)
        if result.get("status") != "present":
            raise ProjectLaneError("project state is unavailable")
        state = dict(result["state"])
        session = state.get("lane_session")
        if not isinstance(session, dict) or session.get("common") != self.common:
            raise ProjectLaneError("Git common-directory identity drifted")
        if (
            session.get("integration_ref") != self.integration_ref
            or session.get("reader_floor") != PROJECT_LANE_READER_FLOOR
        ):
            raise ProjectLaneError("lane session integration binding changed")
        return state

    def _bind_session(self, integration_ref: str) -> str:
        expected = {
            "common": self.common,
            "integration_ref": integration_ref,
            "reader_floor": PROJECT_LANE_READER_FLOOR,
        }
        for _ in range(8):
            result = self.store.read_state(self.anchor_id)
            if result.get("status") != "present":
                raise ProjectLaneError("project state is unavailable")
            state = dict(result["state"])
            session = state.get("lane_session")
            if session is not None:
                if session != expected:
                    raise ProjectLaneError("lane session integration binding changed")
                return str(session["integration_ref"])
            try:
                bound = self.store.bind_lane_session(
                    self.anchor_id,
                    expected_generation=state["generation"],
                    common=self.common,
                    integration_ref=integration_ref,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectLaneError(str(exc)) from exc
            if bound.get("lane_session") != expected:
                raise ProjectLaneError("lane session integration binding changed")
            return integration_ref
        raise ProjectLaneError("lane session binding could not win the project generation CAS")

    @staticmethod
    def _canonical_scope(value: str) -> str:
        if not isinstance(value, str):
            raise ProjectLaneError("lane scope is not text")
        normalized = unicodedata.normalize("NFC", value)
        parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or "\\" in normalized
            or "\0" in normalized
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
            or (len(parts[0]) >= 2 and parts[0][1] == ":")
        ):
            raise ProjectLaneError("lane scope is not a canonical repository path")
        if os.path.normcase("A") == os.path.normcase("a"):
            for part in parts:
                stem = part.split(".", 1)[0].upper()
                if part.endswith((" ", ".")) or stem in _WINDOWS_RESERVED:
                    raise ProjectLaneError("lane scope has a Windows path alias")
        return normalized

    @staticmethod
    def _scope_key(value: str) -> str:
        return value.casefold()

    def _assert_scope_ancestors(self, value: str) -> None:
        current = self.checkout
        for part in value.split("/")[:-1]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                return
            except OSError as exc:
                raise ProjectLaneError("lane scope ancestor is unreadable") from exc
            if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise ProjectLaneError("lane scope has a link or non-directory ancestor")

    def _assert_binding(self, state: Mapping[str, Any]) -> None:
        current = self._common_identity()
        if self.common != current:
            raise ProjectLaneError("Git common-directory identity drifted")
        for lane in state["lanes"]:
            lane_id = lane.get("lane_id")
            worktree = Path(str(lane.get("worktree")))
            try:
                relative = worktree.relative_to(self.lane_root)
            except ValueError as exc:
                raise ProjectLaneError("registered lane escapes the managed lane root") from exc
            if (
                lane.get("common") != current
                or lane.get("base") != self.base
                or lane.get("branch") != f"refs/heads/openbuild/lanes/{lane_id}"
                or relative == Path(".")
            ):
                raise ProjectLaneError("Git common-directory identity drifted")

    def _publish(self, state: Mapping[str, Any], lanes: Sequence[Mapping[str, Any]], scopes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        try:
            return self.store.replace_lane_state(self.anchor_id, expected_generation=state["generation"], lanes=lanes, scopes=scopes)
        except ProjectStateError as exc:
            raise ProjectLaneError(str(exc)) from exc

    @staticmethod
    def _decode_paths(raw: bytes) -> set[str]:
        paths: set[str] = set()
        for value in raw.split(b"\0"):
            if not value:
                continue
            try:
                name = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProjectLaneError("dirty checkout path is not UTF-8") from exc
            paths.add(ProjectLaneCoordinator._canonical_scope(name))
        return paths

    def _dirty_scopes(self) -> list[dict[str, Any]]:
        paths: set[str] = set()
        for command in (
            ("diff", "--no-renames", "--name-only", "-z"),
            ("diff", "--cached", "--no-renames", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            paths.update(self._decode_paths(self._git(*command)))
        output: list[dict[str, Any]] = []
        for path in sorted(paths):
            absolute = self.checkout / Path(path)
            try:
                metadata = absolute.lstat()
            except FileNotFoundError:
                content = {"kind": "missing", "digest": None}
            except OSError as exc:
                raise ProjectLaneError("protected-user-work is unreadable") from exc
            else:
                if _is_link_or_reparse(metadata):
                    try:
                        target = os.readlink(absolute)
                    except OSError as exc:
                        raise ProjectLaneError("protected-user-work link is unreadable") from exc
                    content = {
                        "kind": "link",
                        "digest": hashlib.sha256(os.fsencode(target)).hexdigest(),
                    }
                    blob = self._git_checked_result(
                        "hash-object",
                        "--stdin",
                        input_data=os.fsencode(target),
                    )
                elif stat.S_ISREG(metadata.st_mode):
                    try:
                        content_digest = hashlib.sha256(absolute.read_bytes()).hexdigest()
                    except OSError as exc:
                        raise ProjectLaneError("protected-user-work is unreadable") from exc
                    content = {"kind": "file", "digest": content_digest}
                    blob = self._git_checked_result(
                        "hash-object",
                        f"--path={path}",
                        "--",
                        path,
                    )
                else:
                    raise ProjectLaneError("protected-user-work type is unsupported")
                blob_id = blob.stdout.decode("ascii").strip() if blob.returncode == 0 else ""
                if not re.fullmatch(r"[0-9a-f]{40,64}", blob_id):
                    raise ProjectLaneError("protected-user-work Git blob identity is unavailable")
                content["git_blob_id"] = blob_id
            index = self._git("ls-files", "--stage", "-z", "--", path)
            index_fields = index.split(b"\t", 1)[0].split() if index else []
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
            if content["kind"] == "link":
                content["git_mode"] = "120000"
            elif content["kind"] == "file":
                executable = bool(metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                content["git_mode"] = (
                    index_mode
                    if os.name == "nt" and index_mode in {"100644", "100755"}
                    else ("100755" if executable else "100644")
                )
            evidence = {
                "common": self.common,
                "path": path,
                "content": content,
                "index_digest": hashlib.sha256(index).hexdigest(),
                "index_blob_id": index_blob_id,
            }
            output.append(
                {
                    "kind": "protected-user-work",
                    "path": path,
                    "owner": None,
                    "adoption": "protected",
                    "evidence": evidence,
                    "provenance": hashlib.sha256(_canonical(evidence)).hexdigest(),
                }
            )
        return output

    @staticmethod
    def _merge_protected(
        existing: Sequence[Mapping[str, Any]],
        observed: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = [dict(value) for value in existing]
        by_path = {
            value.get("path"): value
            for value in merged
            if value.get("kind") == "protected-user-work"
        }
        for value in observed:
            previous = by_path.get(value["path"])
            if previous is None:
                merged.append(dict(value))
                by_path[value["path"]] = merged[-1]
            elif previous.get("provenance") != value.get("provenance"):
                raise ProjectLaneError("protected-user-work provenance changed")
        return merged

    @staticmethod
    def _overlaps(left: str, right: str) -> bool:
        left_key = ProjectLaneCoordinator._scope_key(left)
        right_key = ProjectLaneCoordinator._scope_key(right)
        return left_key == right_key or left_key.startswith(right_key + "/") or right_key.startswith(left_key + "/")

    def _assert_legacy_vacancy(self) -> None:
        state = RecoveryRegistry(self.checkout, state_root=self.recovery_root).state()
        if (
            state.get("lease") is not None
            or state.get("outbox") is not None
            or state.get("quarantine") is not None
        ):
            raise ProjectLaneError("originating checkout recovery registry is not vacant")

    @staticmethod
    def _writer_binding(
        registry_state: Mapping[str, Any],
        *,
        states: set[str],
    ) -> dict[str, str] | None:
        lease = registry_state.get("lease")
        if lease is None:
            return None
        if not isinstance(lease, dict):
            raise ProjectLaneError("lane-local contained writer is not active")
        lease_kind = lease.get("lease_kind")
        run_id = (
            lease.get("plan", {}).get("run_id")
            if lease_kind == "recovery-target"
            else lease.get("run_id")
        )
        if (
            not isinstance(lease.get("lease_id"), str)
            or not lease["lease_id"]
            or not isinstance(run_id, str)
            or not run_id
            or not re.fullmatch(r"[0-9a-f]{64}", str(lease.get("allowed_set_digest")))
            or lease_kind not in {"normal-contained", "recovery-target"}
            or lease.get("recovery_capable") is not True
            or lease.get("state") not in states
        ):
            raise ProjectLaneError("lane-local contained writer is not active")
        return {
            "lease_id": lease["lease_id"],
            "run_id": run_id,
            "allowed_set_digest": lease["allowed_set_digest"],
            "lease_kind": lease_kind,
        }

    @staticmethod
    def _active_writer_binding(
        registry_state: Mapping[str, Any],
    ) -> dict[str, str] | None:
        return ProjectLaneCoordinator._writer_binding(
            registry_state,
            states={"running", "active"},
        )

    def _lane_registry_state(self, lane: Mapping[str, Any]) -> dict[str, Any]:
        worktree = _safe_dir(Path(str(lane["worktree"])))
        try:
            return RecoveryRegistry(
                worktree,
                state_root=self.recovery_root,
            ).state()
        except RecoveryStateError as exc:
            raise ProjectLaneError("lane-local recovery registry is invalid") from exc

    def _require_active_writer(
        self,
        lane: Mapping[str, Any],
        expected: Mapping[str, Any],
    ) -> dict[str, Any]:
        writer = self._active_writer_binding(self._lane_registry_state(lane))
        if writer is None or writer != dict(expected):
            raise ProjectLaneError("lane-local contained writer is not active")
        return writer

    def create(self, lane_id: str, milestone: str, worktree: Path, scopes: Sequence[str]) -> dict[str, Any]:
        if not _LANE.fullmatch(lane_id) or not isinstance(milestone, str) or not milestone or len(milestone) > 256:
            raise ProjectLaneError("lane identifier or milestone is invalid")
        if not scopes:
            raise ProjectLaneError("lane scopes are invalid")
        canonical_scopes = [self._canonical_scope(item) for item in scopes]
        scope_keys = [self._scope_key(item) for item in canonical_scopes]
        if len(set(scope_keys)) != len(scope_keys):
            raise ProjectLaneError("lane scopes contain aliases")
        canonical_scopes = sorted(canonical_scopes, key=self._scope_key)
        for scope in canonical_scopes:
            self._assert_scope_ancestors(scope)
        worktree = Path(os.path.abspath(os.fspath(worktree)))
        try:
            worktree.relative_to(self.lane_root)
        except ValueError as exc:
            raise ProjectLaneError("target worktree escapes the managed lane root") from exc
        if worktree == self.lane_root or not worktree.parent.is_dir():
            raise ProjectLaneError("target worktree must be beneath an existing managed directory")
        _assert_no_link_or_reparse_ancestors(worktree.parent)
        state = self._state()
        self._assert_binding(state)
        lanes = list(state["lanes"])
        branch = f"refs/heads/openbuild/lanes/{lane_id}"
        existing_lane = next((lane for lane in lanes if lane.get("lane_id") == lane_id), None)
        if isinstance(existing_lane, dict):
            if (
                existing_lane.get("milestone") != milestone
                or existing_lane.get("branch") != branch
                or existing_lane.get("worktree") != str(worktree)
                or existing_lane.get("scopes") != canonical_scopes
                or existing_lane.get("base") != self.base
                or existing_lane.get("common") != self.common
            ):
                raise ProjectLaneError("lane replay binding changed")
            if existing_lane.get("state") == "waiting-for-scope":
                return existing_lane
            if existing_lane.get("state") in {"creating", "ready", "running"}:
                return self._materialize(existing_lane)
            raise ProjectLaneError("lane already reached a terminal state")
        if worktree.exists():
            raise ProjectLaneError("target worktree must be absent")
        if any(lane.get("branch") == branch or lane.get("worktree") == str(worktree) for lane in lanes):
            raise ProjectLaneError("lane Git identity is already registered")
        if self._git("rev-parse", "--verify", "--quiet", branch, allow_failure=True):
            raise ProjectLaneError("managed lane ref already exists")
        self._assert_legacy_vacancy()
        inventory = self._dirty_scopes()
        merged_scopes = self._merge_protected(state["scopes"], inventory)
        external = [
            scope
            for scope in merged_scopes
            if scope.get("kind") == "protected-user-work"
            and scope.get("adoption") != "adopted"
        ]
        waiting = any(self._overlaps(scope, protected["path"]) for scope in canonical_scopes for protected in external)
        lane = {"lane_id": lane_id, "milestone": milestone, "reader_floor": PROJECT_LANE_READER_FLOOR, "common": self.common, "base": self.base, "branch": branch, "worktree": str(worktree), "scopes": canonical_scopes, "state": "waiting-for-scope" if waiting else "creating", "writer": None}
        self._trip("before-lane-state")
        self._publish(state, [*lanes, lane], merged_scopes)
        self._trip("after-lane-state")
        if waiting:
            return lane
        return self._materialize(lane)

    def _materialize(self, lane: Mapping[str, Any]) -> dict[str, Any]:
        worktree = Path(str(lane["worktree"]))
        branch = str(lane["branch"])
        self._assert_legacy_vacancy()
        if not worktree.exists():
            branch_tip = self._git(
                "rev-parse",
                "--verify",
                "--quiet",
                branch,
                allow_failure=True,
            ).decode("ascii").strip()
            if branch_tip and branch_tip != lane["base"]:
                raise ProjectLaneError("managed lane ref moved before worktree creation")
            self._trip("before-worktree-add")
            try:
                if branch_tip:
                    self._git("worktree", "add", str(worktree), branch)
                else:
                    self._git(
                        "worktree",
                        "add",
                        "-b",
                        branch.removeprefix("refs/heads/"),
                        str(worktree),
                        str(lane["base"]),
                    )
            except ProjectLaneError:
                if not worktree.is_dir():
                    raise
            self._trip("after-worktree-add")
        return self.resume(str(lane["lane_id"]))

    def resume(self, lane_id: str) -> dict[str, Any]:
        for _ in range(8):
            self._assert_legacy_vacancy()
            state = self._state()
            self._assert_binding(state)
            lanes = list(state["lanes"])
            lane = next((item for item in lanes if item.get("lane_id") == lane_id), None)
            if not isinstance(lane, dict) or lane.get("state") not in {"creating", "ready", "running"}:
                raise ProjectLaneError("lane cannot be resumed")
            worktree = _safe_dir(Path(lane["worktree"]))
            if self._common_identity(worktree) != self.common:
                raise ProjectLaneError("lane Git common-directory identity drifted")
            if self._git("rev-parse", "--verify", "HEAD", cwd=worktree).decode("ascii").strip() != lane["base"]:
                raise ProjectLaneError("lane admitted base drifted")
            expected_branch = lane["branch"].removeprefix("refs/heads/")
            if self._git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=worktree, allow_failure=True).decode("utf-8").strip() != expected_branch:
                raise ProjectLaneError("lane branch identity drifted")
            if lane["state"] == "running":
                self._require_active_writer(lane, lane["writer"])
                return lane
            if self._git("status", "--porcelain=v1", "-z", cwd=worktree):
                raise ProjectLaneError("lane worktree is dirty")
            if lane["state"] == "ready":
                return lane
            lane["state"] = "ready"
            try:
                self._publish(state, lanes, state["scopes"])
            except ProjectLaneError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return lane
        raise ProjectLaneError("lane resume could not win the project generation CAS")

    def runner_writer_binding(
        self,
        lane_id: str,
        worktree: Path,
        allowed_paths: Sequence[str],
        *,
        require_ready: bool,
        lease_kind: str = "normal-contained",
    ) -> dict[str, Any]:
        """Bind one already-resolved lane worktree to its lane-local runner."""
        if (
            not _LANE.fullmatch(lane_id)
            or not allowed_paths
            or lease_kind not in {"normal-contained", "recovery-target"}
        ):
            raise ProjectLaneError("runner lane binding is invalid")
        canonical_allowed = [
            self._canonical_scope(path)
            for path in allowed_paths
        ]
        allowed_keys = [self._scope_key(path) for path in canonical_allowed]
        if len(set(allowed_keys)) != len(allowed_keys):
            raise ProjectLaneError("runner allowed paths contain aliases")
        canonical_allowed = sorted(canonical_allowed, key=self._scope_key)
        expected_worktree = _safe_dir(Path(worktree))
        self._assert_legacy_vacancy()
        state = self._state()
        self._assert_binding(state)
        lane = next(
            (item for item in state["lanes"] if item.get("lane_id") == lane_id),
            None,
        )
        if not isinstance(lane, dict):
            raise ProjectLaneError("runner lane does not exist")
        if require_ready:
            expected_state = (
                "recovery-ready"
                if lease_kind == "recovery-target"
                else "ready"
            )
            if lane.get("state") != expected_state or lane.get("writer") is not None:
                raise ProjectLaneError("runner lane is not ready for activation")
            if lease_kind == "recovery-target":
                registry_state = self._lane_registry_state(lane)
                reserved = registry_state.get("lease")
                if (
                    not isinstance(reserved, dict)
                    or reserved.get("lease_kind") != "recovery-target"
                    or reserved.get("state") != "reserved"
                    or reserved.get("checkpoint_digest")
                    != lane.get("recovery_checkpoint_digest")
                ):
                    raise ProjectLaneError(
                        "runner recovery target is not reserved for this lane checkpoint"
                    )
        elif lane.get("state") not in {
            "ready",
            "running",
            "recovery-ready",
            "waiting-for-integration",
            "cancelled",
            "quarantined",
            "closed",
        }:
            raise ProjectLaneError("runner lane lifecycle is not attachable")
        writer = lane.get("writer")
        if (
            isinstance(writer, dict)
            and writer.get("lease_kind") != lease_kind
        ):
            raise ProjectLaneError("runner lane writer kind changed")
        registered_worktree = _safe_dir(Path(str(lane["worktree"])))
        if expected_worktree != registered_worktree:
            raise ProjectLaneError("runner repository is not the registered lane worktree")
        if self._common_identity(registered_worktree) != self.common:
            raise ProjectLaneError("runner lane Git common-directory identity drifted")
        if (
            self._git(
                "rev-parse",
                "--verify",
                "HEAD",
                cwd=registered_worktree,
            ).decode("ascii").strip()
            != lane["base"]
        ):
            raise ProjectLaneError("runner lane admitted base drifted")
        expected_branch = str(lane["branch"]).removeprefix("refs/heads/")
        if (
            self._git(
                "symbolic-ref",
                "--quiet",
                "--short",
                "HEAD",
                cwd=registered_worktree,
                allow_failure=True,
            ).decode("utf-8").strip()
            != expected_branch
        ):
            raise ProjectLaneError("runner lane branch identity drifted")
        if require_ready and lease_kind == "normal-contained" and self._git(
            "status",
            "--porcelain=v1",
            "-z",
            cwd=registered_worktree,
        ):
            raise ProjectLaneError("runner lane worktree is dirty before activation")
        scope_keys = [self._scope_key(path) for path in lane["scopes"]]
        for allowed in allowed_keys:
            if not any(
                allowed == scope or allowed.startswith(scope + "/")
                for scope in scope_keys
            ):
                raise ProjectLaneError("runner allowed path escapes the lane hard scopes")
        binding = {
            "schema": "project-lane-runner-v1",
            "anchor_id": self.anchor_id,
            "lane_id": lane_id,
            "milestone": lane["milestone"],
            "reader_floor": lane["reader_floor"],
            "common": lane["common"],
            "base": lane["base"],
            "branch": lane["branch"],
            "worktree": lane["worktree"],
            "scopes": list(lane["scopes"]),
            "allowed_paths": canonical_allowed,
            "integration_ref": self.integration_ref,
            "lease_kind": lease_kind,
        }
        binding["digest"] = hashlib.sha256(_canonical(binding)).hexdigest()
        return binding

    def lane_projection(self, lane_id: str) -> dict[str, Any]:
        if not _LANE.fullmatch(lane_id):
            raise ProjectLaneError("lane identifier is invalid")
        state = self._state()
        self._assert_binding(state)
        lane = next(
            (item for item in state["lanes"] if item.get("lane_id") == lane_id),
            None,
        )
        if not isinstance(lane, dict):
            raise ProjectLaneError("lane does not exist")
        return dict(lane)

    def verify_runner_writer_binding(
        self,
        expected: Mapping[str, Any],
        worktree: Path,
    ) -> dict[str, Any]:
        if (
            not isinstance(expected, Mapping)
            or expected.get("schema") != "project-lane-runner-v1"
            or not isinstance(expected.get("lane_id"), str)
            or not isinstance(expected.get("allowed_paths"), list)
        ):
            raise ProjectLaneError("runner lane binding is invalid")
        current = self.runner_writer_binding(
            str(expected["lane_id"]),
            worktree,
            expected["allowed_paths"],
            require_ready=False,
            lease_kind=str(expected.get("lease_kind")),
        )
        if current != dict(expected):
            raise ProjectLaneError("runner lane binding changed")
        return current

    def attach_contained_writer(
        self,
        lane_id: str,
        *,
        lease_id: str,
        run_id: str,
        allowed_set_digest: str,
        lease_kind: str = "normal-contained",
        recovery_checkpoint_digest: str | None = None,
    ) -> dict[str, Any]:
        if (
            not lease_id
            or not run_id
            or not re.fullmatch(r"[0-9a-f]{64}", allowed_set_digest)
            or lease_kind not in {"normal-contained", "recovery-target"}
            or (
                lease_kind == "recovery-target"
                and not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(recovery_checkpoint_digest),
                )
            )
            or (
                lease_kind == "normal-contained"
                and recovery_checkpoint_digest is not None
            )
        ):
            raise ProjectLaneError("contained writer binding is invalid")
        for _ in range(8):
            self._assert_legacy_vacancy()
            state = self._state()
            self._assert_binding(state)
            lanes = list(state["lanes"])
            lane = next((item for item in lanes if item.get("lane_id") == lane_id), None)
            if not isinstance(lane, dict) or lane.get("state") not in {
                "ready",
                "running",
                "recovery-ready",
                "cancelled",
                "quarantined",
            }:
                raise ProjectLaneError("lane is not ready for a contained writer")
            writer = {
                "lease_id": lease_id,
                "run_id": run_id,
                "allowed_set_digest": allowed_set_digest,
                "lease_kind": lease_kind,
            }
            if lane.get("state") in {"running", "quarantined"}:
                if lane.get("writer") != writer:
                    raise ProjectLaneError("contained writer replay binding changed")
                self._require_active_writer(lane, writer)
                return lane
            if lane["state"] == "ready" and lease_kind != "normal-contained":
                raise ProjectLaneError(
                    "ordinary ready lane cannot attach a recovery target"
                )
            if lane["state"] == "recovery-ready":
                if (
                    lease_kind != "recovery-target"
                    or lane.get("recovery_checkpoint_digest")
                    != recovery_checkpoint_digest
                ):
                    raise ProjectLaneError(
                        "recovery target does not match the lane checkpoint"
                    )
            self._require_active_writer(lane, writer)
            lane["state"] = (
                "quarantined"
                if lane["state"] == "cancelled"
                else "running"
            )
            lane["writer"] = writer
            if lane["state"] == "running":
                for field in (
                    "reason",
                    "terminal_from",
                    "terminal_evidence",
                    "recovery_checkpoint_digest",
                ):
                    lane.pop(field, None)
            try:
                self._publish(state, lanes, state["scopes"])
            except ProjectLaneError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return lane
        raise ProjectLaneError("contained writer attach could not win the project generation CAS")

    def record_recovery_ready(
        self,
        lane_id: str,
        checkpoint_digest: str,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", checkpoint_digest):
            raise ProjectLaneError("lane recovery checkpoint digest is invalid")
        for _ in range(8):
            state = self._state()
            self._assert_binding(state)
            lanes = list(state["lanes"])
            lane = next(
                (item for item in lanes if item.get("lane_id") == lane_id),
                None,
            )
            if (
                isinstance(lane, dict)
                and lane.get("state") == "recovery-ready"
            ):
                if lane.get("recovery_checkpoint_digest") != checkpoint_digest:
                    raise ProjectLaneError(
                        "lane recovery checkpoint replay binding changed"
                    )
                return lane
            if not isinstance(lane, dict) or lane.get("state") != "quarantined":
                raise ProjectLaneError("lane is not quarantined for recovery")
            writer = lane.get("writer")
            if not isinstance(writer, dict):
                raise ProjectLaneError("lane recovery source writer is missing")
            registry_state = self._lane_registry_state(lane)
            if (
                registry_state.get("lease") is not None
                or registry_state.get("outbox") is not None
                or registry_state.get("quarantine") is not None
            ):
                raise ProjectLaneError("recoverable lane registry is not vacant")
            releases = [
                event
                for event in registry_state.get("history", [])
                if event.get("event") == "contained-terminal-released"
                and event.get("lease_id") == writer.get("lease_id")
                and event.get("lease_kind") == writer.get("lease_kind")
                and event.get("allowed_set_digest")
                == writer.get("allowed_set_digest")
                and event.get("terminal_success") is False
                and event.get("handoff_digest") is None
                and event.get("outbox_digest") is None
            ]
            if len(releases) != 1:
                raise ProjectLaneError(
                    "recoverable contained terminal archive is missing or ambiguous"
                )
            terminal_evidence = releases[0].get("archive_digest")
            if not re.fullmatch(r"[0-9a-f]{64}", str(terminal_evidence)):
                raise ProjectLaneError(
                    "recoverable contained terminal archive digest is invalid"
                )
            lane["state"] = "recovery-ready"
            lane["writer"] = None
            lane["terminal_evidence"] = terminal_evidence
            lane["recovery_checkpoint_digest"] = checkpoint_digest
            try:
                self._publish(state, lanes, state["scopes"])
            except ProjectLaneError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return lane
        raise ProjectLaneError(
            "lane recovery transition could not win the project generation CAS"
        )

    def record_successful_terminal(self, lane_id: str) -> dict[str, Any]:
        for _ in range(8):
            state = self._state()
            self._assert_binding(state)
            lanes = list(state["lanes"])
            lane = next(
                (item for item in lanes if item.get("lane_id") == lane_id),
                None,
            )
            if (
                isinstance(lane, dict)
                and lane.get("state") == "waiting-for-integration"
            ):
                return lane
            if not isinstance(lane, dict) or lane.get("state") != "running":
                raise ProjectLaneError("lane is not running toward integration")
            writer = lane.get("writer")
            if not isinstance(writer, dict):
                raise ProjectLaneError("lane terminal writer binding is missing")
            registry_state = self._lane_registry_state(lane)
            if (
                registry_state.get("lease") is not None
                or registry_state.get("outbox") is not None
                or registry_state.get("quarantine") is not None
            ):
                raise ProjectLaneError("successful lane registry is not vacant")
            releases = [
                event
                for event in registry_state.get("history", [])
                if event.get("event") == "contained-terminal-released"
                and event.get("lease_id") == writer.get("lease_id")
                and event.get("lease_kind") == writer.get("lease_kind")
                and event.get("allowed_set_digest")
                == writer.get("allowed_set_digest")
                and event.get("terminal_success") is True
                and event.get("semantic_disposition") is None
                and event.get("final_state") == "handoff-committed"
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(event.get("handoff_digest")),
                )
            ]
            if len(releases) != 1:
                raise ProjectLaneError(
                    "successful contained terminal archive is missing or ambiguous"
                )
            terminal_evidence = releases[0].get("archive_digest")
            if not re.fullmatch(r"[0-9a-f]{64}", str(terminal_evidence)):
                raise ProjectLaneError(
                    "successful contained terminal archive digest is invalid"
                )
            lane["state"] = "waiting-for-integration"
            lane["terminal_evidence"] = terminal_evidence
            try:
                self._publish(state, lanes, state["scopes"])
            except ProjectLaneError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return lane
        raise ProjectLaneError(
            "successful lane terminal transition could not win the project generation CAS"
        )

    def cancel_or_crash(self, lane_id: str, reason: str) -> dict[str, Any]:
        if reason not in {"cancelled", "crashed", "timeout", "pid-lost"}:
            raise ProjectLaneError("lane terminal reason is invalid")
        for _ in range(8):
            state = self._state()
            self._assert_binding(state)
            lanes = list(state["lanes"])
            lane = next((item for item in lanes if item.get("lane_id") == lane_id), None)
            if not isinstance(lane, dict):
                raise ProjectLaneError("lane does not exist")
            lane_state = lane.get("state")
            if lane_state == "closed":
                raise ProjectLaneError("closed lane cannot be cancelled")
            if lane_state in {"cancelled", "quarantined"} and lane.get("reason") != reason:
                raise ProjectLaneError("lane terminal replay binding changed")
            writer = lane.get("writer")
            worktree = Path(str(lane["worktree"]))
            if worktree.exists():
                active_writer = self._writer_binding(
                    self._lane_registry_state(lane),
                    states={
                        "running",
                        "active",
                        "terminal-pending-stop",
                        "stopped-terminal",
                        "handoff-committed",
                    },
                )
                if active_writer is not None:
                    if writer is not None and writer != active_writer:
                        raise ProjectLaneError("contained writer terminal binding changed")
                    writer = active_writer
            if lane_state in {"cancelled", "quarantined"}:
                if lane_state == "quarantined" or writer is None:
                    return lane
                lane["state"] = "quarantined"
                lane["writer"] = writer
            else:
                if lane_state not in {
                    "waiting-for-scope",
                    "creating",
                    "ready",
                    "running",
                }:
                    raise ProjectLaneError("lane cannot enter a terminal state")
                lane["terminal_from"] = lane_state
                lane["reason"] = reason
                lane["writer"] = writer
                lane["state"] = "quarantined" if writer is not None else "cancelled"
            try:
                self._publish(state, lanes, state["scopes"])
            except ProjectLaneError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return lane
        raise ProjectLaneError("lane terminal transition could not win the project generation CAS")

    def close_terminal(self, lane_id: str) -> dict[str, Any]:
        for _ in range(8):
            state = self._state()
            self._assert_binding(state)
            lanes = list(state["lanes"])
            lane = next((item for item in lanes if item.get("lane_id") == lane_id), None)
            if isinstance(lane, dict) and lane.get("state") == "closed":
                return lane
            if not isinstance(lane, dict) or lane.get("state") not in {"quarantined", "cancelled"}:
                raise ProjectLaneError("lane is not terminally closable")
            worktree = Path(str(lane["worktree"]))
            writer = lane.get("writer")
            if not worktree.exists():
                if (
                    lane.get("terminal_from") not in {"waiting-for-scope", "creating"}
                    or writer is not None
                    or self._git(
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        str(lane["branch"]),
                        allow_failure=True,
                    )
                ):
                    raise ProjectLaneError("unmaterialized lane Git identity is not absent")
                terminal_evidence = hashlib.sha256(
                    _canonical(
                        {
                            "lane_id": lane_id,
                            "outcome": "unmaterialized-close",
                            "terminal_from": lane["terminal_from"],
                        }
                    )
                ).hexdigest()
            else:
                registry_state = self._lane_registry_state(lane)
                if (
                    registry_state.get("lease") is not None
                    or registry_state.get("outbox") is not None
                    or registry_state.get("quarantine") is not None
                ):
                    raise ProjectLaneError("lane-local recovery registry is not vacant")
                if writer is None:
                    if self._git("status", "--porcelain=v1", "-z", cwd=_safe_dir(worktree)):
                        raise ProjectLaneError("unactivated lane worktree is not clean")
                    terminal_evidence = hashlib.sha256(
                        _canonical({"lane_id": lane_id, "outcome": "unactivated-clean-close"})
                    ).hexdigest()
                else:
                    releases = [
                        event
                        for event in registry_state.get("history", [])
                        if event.get("event") == "contained-terminal-released"
                        and event.get("lease_id") == writer.get("lease_id")
                        and event.get("lease_kind") == writer.get("lease_kind")
                        and event.get("allowed_set_digest") == writer.get("allowed_set_digest")
                    ]
                    if len(releases) != 1:
                        raise ProjectLaneError("contained terminal archive is missing or ambiguous")
                    terminal_evidence = releases[0].get("archive_digest")
                    if not re.fullmatch(r"[0-9a-f]{64}", str(terminal_evidence)):
                        raise ProjectLaneError("contained terminal archive digest is invalid")
            lane["state"] = "closed"
            lane["terminal_evidence"] = terminal_evidence
            try:
                self._publish(state, lanes, state["scopes"])
            except ProjectLaneError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return lane
        raise ProjectLaneError("lane close could not win the project generation CAS")

    @staticmethod
    def _adoption_bindings(
        paths: Sequence[str],
        user_action_digest: str,
        plan_digest: str,
    ) -> tuple[list[str], str, str]:
        normalized = [
            ProjectLaneCoordinator._canonical_scope(path)
            for path in paths
        ]
        keys = [
            ProjectLaneCoordinator._scope_key(path)
            for path in normalized
        ]
        if (
            not normalized
            or len(set(keys)) != len(keys)
            or not re.fullmatch(r"[0-9a-f]{64}", user_action_digest)
            or not re.fullmatch(r"[0-9a-f]{64}", plan_digest)
        ):
            raise ProjectLaneError("protected adoption binding is invalid")
        return sorted(normalized, key=ProjectLaneCoordinator._scope_key), user_action_digest, plan_digest

    def begin_protected_user_work_adoption(
        self,
        paths: Sequence[str],
        *,
        user_action_digest: str,
        plan_digest: str,
    ) -> list[dict[str, Any]]:
        paths, user_action_digest, plan_digest = self._adoption_bindings(
            paths, user_action_digest, plan_digest
        )
        state = self._state()
        self._assert_binding(state)
        observed = {value["path"]: value for value in self._dirty_scopes()}
        scopes = [dict(value) for value in state["scopes"]]
        selected: list[dict[str, Any]] = []
        for scope in scopes:
            if scope.get("kind") != "protected-user-work" or scope.get("path") not in paths:
                continue
            if observed.get(str(scope["path"]), {}).get("provenance") != scope.get("provenance"):
                raise ProjectLaneError("protected adoption provenance changed")
            evidence = scope.get("evidence")
            content = evidence.get("content") if isinstance(evidence, dict) else None
            if (
                isinstance(content, dict)
                and evidence.get("index_blob_id") is not None
                and evidence.get("index_blob_id") != content.get("git_blob_id")
            ):
                raise ProjectLaneError("protected adoption index/content identity is split")
            intent = {
                "user_action_digest": user_action_digest,
                "plan_digest": plan_digest,
                "provenance": scope["provenance"],
                "intent_generation": state["generation"] + 1,
            }
            if scope.get("adoption") == "adoption-intent":
                existing_intent = scope.get("adoption_intent")
                if (
                    not isinstance(existing_intent, dict)
                    or {
                        key: existing_intent.get(key)
                        for key in ("user_action_digest", "plan_digest", "provenance")
                    }
                    != {
                        key: intent[key]
                        for key in ("user_action_digest", "plan_digest", "provenance")
                    }
                ):
                    raise ProjectLaneError("protected adoption replay binding changed")
            elif scope.get("adoption") == "protected":
                scope["adoption"] = "adoption-intent"
                scope["adoption_intent"] = intent
            else:
                raise ProjectLaneError("protected scope is not adoptable")
            selected.append(scope)
        if {scope["path"] for scope in selected} != set(paths):
            raise ProjectLaneError("protected adoption scope is incomplete")
        if all(
            original == updated
            for original, updated in zip(state["scopes"], scopes, strict=True)
        ):
            return selected
        self._trip("before-adoption-intent")
        self._publish(state, state["lanes"], scopes)
        self._trip("after-adoption-intent")
        return selected

    def rollback_protected_user_work_adoption(
        self,
        paths: Sequence[str],
        *,
        user_action_digest: str,
        plan_digest: str,
    ) -> list[dict[str, Any]]:
        paths, user_action_digest, plan_digest = self._adoption_bindings(
            paths, user_action_digest, plan_digest
        )
        state = self._state()
        scopes = [dict(value) for value in state["scopes"]]
        selected: list[dict[str, Any]] = []
        for scope in scopes:
            if scope.get("kind") != "protected-user-work" or scope.get("path") not in paths:
                continue
            intent = scope.get("adoption_intent")
            if (
                scope.get("adoption") != "adoption-intent"
                or not isinstance(intent, dict)
                or intent.get("user_action_digest") != user_action_digest
                or intent.get("plan_digest") != plan_digest
            ):
                raise ProjectLaneError("protected adoption rollback binding changed")
            scope["adoption"] = "protected"
            scope.pop("adoption_intent", None)
            selected.append(scope)
        if {scope["path"] for scope in selected} != set(paths):
            raise ProjectLaneError("protected adoption rollback scope is incomplete")
        self._publish(state, state["lanes"], scopes)
        return selected

    def _adoption_acceptance_receipt(
        self,
        selected: Sequence[Mapping[str, Any]],
        *,
        user_action_digest: str,
        plan_digest: str,
        integrated_commit: str,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{40,64}", integrated_commit):
            raise ProjectLaneError("protected adoption commit is invalid")
        commit_result = self._git_checked_result(
            "rev-parse",
            "--verify",
            f"{integrated_commit}^{{commit}}",
        )
        ref_result = self._git_checked_result(
            "rev-parse",
            "--verify",
            f"{self.integration_ref}^{{commit}}",
        )
        if (
            commit_result.returncode != 0
            or ref_result.returncode != 0
            or commit_result.stdout.decode("ascii").strip() != integrated_commit
            or ref_result.stdout.decode("ascii").strip() != integrated_commit
        ):
            raise ProjectLaneError("adoption commit is not the accepted integration ref tip")
        receipt = {
            "kind": "accepted-protected-work-integration",
            "project_common_digest": hashlib.sha256(_canonical(self.common)).hexdigest(),
            "integration_ref": self.integration_ref,
            "user_action_digest": user_action_digest,
            "plan_digest": plan_digest,
            "paths": [
                {
                    "path": scope["path"],
                    "provenance": scope["provenance"],
                    "intent_generation": scope["adoption_intent"]["intent_generation"],
                }
                for scope in sorted(selected, key=lambda value: self._scope_key(str(value["path"])))
            ],
            "integrated_commit": integrated_commit,
        }
        receipt["digest"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        return receipt

    def build_protected_user_work_acceptance_receipt(
        self,
        paths: Sequence[str],
        *,
        user_action_digest: str,
        plan_digest: str,
        integrated_commit: str,
    ) -> dict[str, Any]:
        paths, user_action_digest, plan_digest = self._adoption_bindings(
            paths, user_action_digest, plan_digest
        )
        state = self._state()
        selected = [
            scope
            for scope in state["scopes"]
            if scope.get("kind") == "protected-user-work"
            and scope.get("path") in paths
            and scope.get("adoption") == "adoption-intent"
        ]
        if {scope["path"] for scope in selected} != set(paths):
            raise ProjectLaneError("protected adoption acceptance scope is incomplete")
        for scope in selected:
            intent = scope.get("adoption_intent")
            if (
                not isinstance(intent, dict)
                or intent.get("user_action_digest") != user_action_digest
                or intent.get("plan_digest") != plan_digest
            ):
                raise ProjectLaneError("protected adoption acceptance binding changed")
        return self._adoption_acceptance_receipt(
            selected,
            user_action_digest=user_action_digest,
            plan_digest=plan_digest,
            integrated_commit=integrated_commit,
        )

    def finalize_protected_user_work_adoption(
        self,
        paths: Sequence[str],
        *,
        user_action_digest: str,
        plan_digest: str,
        integration_receipt: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        paths, user_action_digest, plan_digest = self._adoption_bindings(
            paths, user_action_digest, plan_digest
        )
        if not isinstance(integration_receipt, Mapping):
            raise ProjectLaneError("protected adoption acceptance is invalid")
        integrated_commit = integration_receipt.get("integrated_commit")
        if not isinstance(integrated_commit, str):
            raise ProjectLaneError("protected adoption acceptance is invalid")
        state = self._state()
        self._assert_binding(state)
        observed = {value["path"]: value for value in self._dirty_scopes()}
        scopes = [dict(value) for value in state["scopes"]]
        selected: list[dict[str, Any]] = []
        for scope in scopes:
            if scope.get("kind") != "protected-user-work" or scope.get("path") not in paths:
                continue
            accepted = {
                "user_action_digest": user_action_digest,
                "plan_digest": plan_digest,
                "integrated_commit": integrated_commit,
                "integration_receipt_digest": integration_receipt.get("digest"),
            }
            if scope.get("adoption") == "adopted":
                existing_acceptance = scope.get("adoption_acceptance")
                if (
                    not isinstance(existing_acceptance, dict)
                    or {
                        key: existing_acceptance.get(key)
                        for key in accepted
                    }
                    != accepted
                    or existing_acceptance.get("receipt") != dict(integration_receipt)
                ):
                    raise ProjectLaneError("protected adoption acceptance replay changed")
                selected.append(scope)
                continue
            intent = scope.get("adoption_intent")
            if (
                scope.get("adoption") != "adoption-intent"
                or not isinstance(intent, dict)
                or intent.get("user_action_digest") != user_action_digest
                or intent.get("plan_digest") != plan_digest
                or observed.get(str(scope["path"]), {}).get("provenance") != scope.get("provenance")
            ):
                raise ProjectLaneError("protected adoption intent is stale")
            selected.append(scope)
        if {scope["path"] for scope in selected} != set(paths):
            raise ProjectLaneError("protected adoption acceptance scope is incomplete")
        adoption_states = {scope.get("adoption") for scope in selected}
        if adoption_states == {"adopted"}:
            return selected
        if adoption_states != {"adoption-intent"}:
            raise ProjectLaneError("protected adoption acceptance state split")
        expected_receipt = self._adoption_acceptance_receipt(
            selected,
            user_action_digest=user_action_digest,
            plan_digest=plan_digest,
            integrated_commit=integrated_commit,
        )
        if dict(integration_receipt) != expected_receipt:
            raise ProjectLaneError("protected adoption receipt binding changed")
        self._trip("before-adoption-verify")
        for scope in selected:
            if scope.get("adoption") == "adopted":
                continue
            evidence = scope.get("evidence")
            if not isinstance(evidence, dict) or not isinstance(evidence.get("content"), dict):
                raise ProjectLaneError("protected adoption evidence is invalid")
            content = evidence["content"]
            tree_entry = self._git_checked_result(
                "ls-tree",
                "-z",
                integrated_commit,
                "--",
                str(scope["path"]),
            )
            if tree_entry.returncode != 0:
                raise ProjectLaneError("integrated commit tree could not be inspected")
            if content.get("kind") == "missing":
                if tree_entry.stdout:
                    raise ProjectLaneError("integrated commit retained a protected deletion")
            else:
                try:
                    tree_fields = tree_entry.stdout.split(b"\t", 1)[0].split()
                    committed_mode = tree_fields[0].decode("ascii")
                    committed_blob = tree_fields[2].decode("ascii")
                except (IndexError, UnicodeDecodeError) as exc:
                    raise ProjectLaneError("integrated commit tree entry is malformed") from exc
                if (
                    committed_mode != content.get("git_mode")
                    or committed_blob != content.get("git_blob_id")
                ):
                    raise ProjectLaneError("integrated commit does not match protected content")
        self._trip("after-adoption-verify")
        for scope in selected:
            if scope.get("adoption") == "adopted":
                continue
            accepted = {
                "user_action_digest": user_action_digest,
                "plan_digest": plan_digest,
                "integrated_commit": integrated_commit,
                "integration_receipt_digest": expected_receipt["digest"],
                "receipt": expected_receipt,
            }
            scope["adoption"] = "adopted"
            scope["owner"] = "integration"
            scope["adoption_acceptance"] = accepted
            scope.pop("adoption_intent", None)
        if all(
            original == updated
            for original, updated in zip(state["scopes"], scopes, strict=True)
        ):
            return selected
        self._trip("before-adoption-accept")
        self._publish(state, state["lanes"], scopes)
        self._trip("after-adoption-accept")
        return selected

    def recover_protected_user_work_adoption(
        self,
        paths: Sequence[str],
        *,
        user_action_digest: str,
        plan_digest: str,
        integration_receipt: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        paths, user_action_digest, plan_digest = self._adoption_bindings(
            paths, user_action_digest, plan_digest
        )
        state = self._state()
        selected = [
            scope
            for scope in state["scopes"]
            if scope.get("kind") == "protected-user-work"
            and scope.get("path") in paths
        ]
        if {scope["path"] for scope in selected} != set(paths):
            raise ProjectLaneError("protected adoption recovery scope is incomplete")
        states = {scope.get("adoption") for scope in selected}
        if states == {"adopted"}:
            if integration_receipt is None:
                raise ProjectLaneError("adopted recovery requires its acceptance receipt")
            return self.finalize_protected_user_work_adoption(
                paths,
                user_action_digest=user_action_digest,
                plan_digest=plan_digest,
                integration_receipt=integration_receipt,
            )
        if states != {"adoption-intent"}:
            raise ProjectLaneError("protected adoption is not recoverable")
        if integration_receipt is not None:
            return self.finalize_protected_user_work_adoption(
                paths,
                user_action_digest=user_action_digest,
                plan_digest=plan_digest,
                integration_receipt=integration_receipt,
            )
        return self.rollback_protected_user_work_adoption(
            paths,
            user_action_digest=user_action_digest,
            plan_digest=plan_digest,
        )
