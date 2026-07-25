"""Fail-closed R-032 M5 single-writer integration owner.

Task lanes never move the common integration ref.  This owner admits an exact
terminal lane result into a generation-bound queue, prepares a candidate only
inside its dedicated detached checkout, validates it, then performs one
compare-and-swap ref update before delegating durable acceptance and scope
release to the existing project-state and scope owners.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from project_scopes import ProjectScopeError, ProjectScopeManager
from project_state import (
    ProjectStateError,
    ProjectStateStore,
    _assert_no_link_or_reparse_ancestors,
    _identity,
    _is_link_or_reparse,
    _current_process_identity,
)
from recovery_state import RecoveryRegistry, RecoveryStateError


class ProjectIntegratorError(RuntimeError):
    """The integration queue cannot prove a safe owner transition."""


_GIT_OBJECT = re.compile(r"[0-9a-f]{40,64}\Z")
_GIT_REF = re.compile(r"refs/[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_LANE = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")


def _safe_directory(path: Path) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    _assert_no_link_or_reparse_ancestors(candidate)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise ProjectIntegratorError("integration checkout is unreadable") from exc
    if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ProjectIntegratorError("integration checkout is not a real directory")
    return candidate


class ProjectIntegrator:
    """The only owner permitted to advance a project's integration ref."""

    def __init__(
        self,
        checkout: Path,
        store: ProjectStateStore,
        anchor_id: str,
        *,
        recovery_root: Path,
        integration_checkout: Path,
        integration_ref: str,
        integration_owner: str = "root",
        fault: str | None = None,
    ) -> None:
        self.checkout = _safe_directory(checkout)
        self.store = store
        self.anchor_id = anchor_id
        self.recovery_root = Path(os.path.abspath(os.fspath(recovery_root)))
        self.integration_checkout = Path(
            os.path.abspath(os.fspath(integration_checkout)),
        )
        if self.integration_checkout == self.checkout:
            raise ProjectIntegratorError("integration checkout cannot be a user checkout")
        if (
            not isinstance(integration_ref, str)
            or not _GIT_REF.fullmatch(integration_ref)
            or integration_ref.endswith(("/", "."))
            or ".." in integration_ref.split("/")
        ):
            raise ProjectIntegratorError("integration ref is invalid")
        if not (
            integration_ref == "refs/openbuild/integration"
            or integration_ref.startswith("refs/openbuild/integration/")
        ):
            raise ProjectIntegratorError(
                "integration ref is not a dedicated OpenBuild ref"
            )
        if (
            not isinstance(integration_owner, str)
            or not integration_owner
            or len(integration_owner) > 128
        ):
            raise ProjectIntegratorError("integration owner is invalid")
        self.integration_ref = integration_ref
        self.integration_owner = integration_owner
        self.owner_token = secrets.token_hex(32)
        self.process_identity = _current_process_identity()
        self.fault = fault
        self.common = self._common_identity(self.checkout)
        self.checkout_binding: dict[str, Any] | None = None
        self.executor_lease_id: str | None = None
        self.executor_intent_id: str | None = None
        self.invocation_lock = threading.Lock()

    def _trip(self, stage: str) -> None:
        if self.fault == stage:
            raise ProjectIntegratorError(f"injected fault at {stage}")

    def _git_result(
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

    def _git(self, *args: str, cwd: Path | None = None) -> bytes:
        result = self._git_result(*args, cwd=cwd)
        if result.returncode:
            raise ProjectIntegratorError("integration Git command failed")
        return result.stdout

    def _commit(self, value: bytes, *, message: str) -> str:
        try:
            result = value.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ProjectIntegratorError(message) from exc
        if not _GIT_OBJECT.fullmatch(result):
            raise ProjectIntegratorError(message)
        return result

    def _common_identity(self, checkout: Path) -> dict[str, Any]:
        raw = self._git("rev-parse", "--git-common-dir", cwd=checkout)
        try:
            text = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ProjectIntegratorError("Git common directory is not UTF-8") from exc
        path = Path(text)
        if not path.is_absolute():
            path = checkout / path
        path = _safe_directory(path)
        return {"path": str(path), "identity": list(_identity(path.lstat()))}

    def _worktrees(self) -> list[dict[str, Any]]:
        result = self._git_result("worktree", "list", "--porcelain", "-z")
        if result.returncode:
            raise ProjectIntegratorError("Git worktree inventory is ambiguous")
        records: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        try:
            tokens = result.stdout.decode("utf-8").split("\0")
        except UnicodeDecodeError as exc:
            raise ProjectIntegratorError(
                "Git worktree inventory is not UTF-8"
            ) from exc
        for token in tokens:
            if not token:
                continue
            key, separator, value = token.partition(" ")
            if key == "worktree":
                if not separator or not value:
                    raise ProjectIntegratorError(
                        "Git worktree inventory is ambiguous"
                    )
                worktree_path = Path(value)
                if not worktree_path.is_absolute():
                    raise ProjectIntegratorError(
                        "Git worktree inventory is ambiguous"
                    )
                if current is not None:
                    records.append(current)
                current = {"worktree": str(worktree_path)}
                continue
            if current is None:
                raise ProjectIntegratorError(
                    "Git worktree inventory is ambiguous"
                )
            if key in current:
                raise ProjectIntegratorError(
                    "Git worktree inventory is ambiguous"
                )
            current[key] = value if separator else True
        if current is not None:
            records.append(current)
        if not records or len(
            {str(item["worktree"]).casefold() for item in records}
        ) != len(records):
            raise ProjectIntegratorError("Git worktree inventory is ambiguous")
        return records

    def _assert_dedicated_ref_not_checked_out(self) -> None:
        for record in self._worktrees():
            if record.get("branch") == self.integration_ref:
                raise ProjectIntegratorError(
                    "integration ref is checked out in an ordinary worktree"
                )

    def _checkout_identity(self, checkout: Path) -> dict[str, Any]:
        checkout = _safe_directory(checkout)
        raw = self._git("rev-parse", "--git-dir", cwd=checkout)
        try:
            value = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ProjectIntegratorError(
                "integration checkout Git directory is not UTF-8"
            ) from exc
        git_dir = Path(value)
        if not git_dir.is_absolute():
            git_dir = checkout / git_dir
        git_dir = _safe_directory(git_dir)
        return {
            "path": str(checkout),
            "identity": list(_identity(checkout.lstat())),
            "git_dir": str(git_dir),
            "git_dir_identity": list(_identity(git_dir.lstat())),
            "common": self.common,
        }

    def _state(self) -> dict[str, Any]:
        observed = self.store.read_state(self.anchor_id)
        if observed.get("status") != "present":
            raise ProjectIntegratorError("project state is unavailable")
        state = dict(observed["state"])
        session = state.get("lane_session")
        if (
            not isinstance(session, dict)
            or session.get("common") != self.common
            or session.get("integration_ref") != self.integration_ref
            or session.get("recovery_root") != str(self.recovery_root)
            or (
                self.checkout_binding is not None
                and state.get("integration_checkout")
                != self.checkout_binding
            )
        ):
            raise ProjectIntegratorError("integration session binding changed")
        if self._common_identity(self.checkout) != self.common:
            raise ProjectIntegratorError("Git common-directory identity drifted")
        fence = state.get("integration_fence")
        if isinstance(fence, Mapping):
            tip = self._commit(
                self._git(
                    "rev-parse",
                    "--verify",
                    f"{self.integration_ref}^{{commit}}",
                ),
                message="integration ref is invalid",
            )
            if (
                fence.get("state") != "prepared"
                and tip != str(fence["candidate_commit"])
            ):
                raise ProjectIntegratorError(
                    "fenced integration ref identity is ambiguous"
                )
        return state

    def _integration_tip(self) -> str:
        return self._commit(
            self._git("rev-parse", "--verify", f"{self.integration_ref}^{{commit}}"),
            message="integration ref is invalid",
        )

    def _assert_terminal_registry(self, lane: Mapping[str, Any]) -> None:
        try:
            registry = RecoveryRegistry(
                Path(str(lane["worktree"])),
                state_root=self.recovery_root,
            ).state()
        except (OSError, RecoveryStateError) as exc:
            raise ProjectIntegratorError("integration recovery registry is invalid") from exc
        writer = lane.get("writer")
        matches = [
            event
            for event in registry.get("history", [])
            if isinstance(writer, Mapping)
            and event.get("event") == "contained-terminal-released"
            and event.get("lease_id") == writer.get("lease_id")
            and event.get("run_id") == writer.get("run_id")
            and event.get("lease_kind") == writer.get("lease_kind")
            and event.get("allowed_set_digest") == writer.get("allowed_set_digest")
            and event.get("terminal_success") is True
            and event.get("semantic_disposition") is None
            and event.get("final_state") == "handoff-committed"
            and event.get("archive_digest") == lane.get("terminal_evidence")
        ]
        if (
            registry.get("lease") is not None
            or registry.get("outbox") is not None
            or registry.get("quarantine") is not None
            or len(matches) != 1
        ):
            raise ProjectIntegratorError("integration terminal archive is missing or ambiguous")

    @staticmethod
    def _validation_argv(value: Sequence[str]) -> list[str]:
        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or not value
            or len(value) > 64
            or any(
                not isinstance(item, str)
                or not item
                or "\0" in item
                or len(item) > 4096
                for item in value
            )
        ):
            raise ProjectIntegratorError("integration validation command is invalid")
        return list(value)

    def _result_commit(self, lane: Mapping[str, Any]) -> str:
        worktree = _safe_directory(Path(str(lane["worktree"])))
        if self._common_identity(worktree) != self.common:
            raise ProjectIntegratorError("terminal lane common-directory identity drifted")
        if self._git("status", "--porcelain=v1", "-z", cwd=worktree):
            raise ProjectIntegratorError("terminal lane worktree is not committed")
        branch = self._git("symbolic-ref", "--quiet", "HEAD", cwd=worktree)
        try:
            branch_text = branch.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ProjectIntegratorError("terminal lane branch is invalid") from exc
        if branch_text != lane.get("branch"):
            raise ProjectIntegratorError("terminal lane branch binding changed")
        return self._commit(
            self._git("rev-parse", "--verify", "HEAD^{commit}", cwd=worktree),
            message="terminal lane result commit is invalid",
        )

    def enqueue(
        self,
        lane_id: str,
        *,
        validation_argv: Sequence[str],
        dependency_unblocking: bool = False,
    ) -> dict[str, Any]:
        """Admit exactly one terminal result tuple without releasing a scope."""

        if not isinstance(lane_id, str) or not _LANE.fullmatch(lane_id):
            raise ProjectIntegratorError("integration lane identifier is invalid")
        if not isinstance(dependency_unblocking, bool):
            raise ProjectIntegratorError("integration queue class is invalid")
        argv = self._validation_argv(validation_argv)
        self._ensure_integration_checkout()
        for _ in range(8):
            state = self._state()
            lane = next(
                (item for item in state["lanes"] if item.get("lane_id") == lane_id),
                None,
            )
            if (
                not isinstance(lane, dict)
                or lane.get("state") != "waiting-for-integration"
                or not isinstance(lane.get("writer"), dict)
                or not isinstance(lane.get("terminal_evidence"), str)
            ):
                raise ProjectIntegratorError("integration lane is not terminally admitted")
            result_commit = self._result_commit(lane)
            self._assert_terminal_registry(lane)
            try:
                intent = self.store.enqueue_integration_intent(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    lane_id=lane_id,
                    result_commit=result_commit,
                    admitted_tip=self._integration_tip(),
                    validation_argv=argv,
                    queue_class=(
                        "dependency-unblocking"
                        if dependency_unblocking
                        else "ordinary"
                    ),
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
            self._trip("after-enqueue")
            return intent
        raise ProjectIntegratorError("integration intent could not win the project generation CAS")

    def _ensure_integration_checkout(
        self,
        *,
        allow_dirty_recovery: bool = False,
    ) -> Path:
        self._assert_dedicated_ref_not_checked_out()
        parent = self.integration_checkout.parent
        _assert_no_link_or_reparse_ancestors(parent)
        dirty_checkout = False
        if self.integration_checkout.exists():
            worktree = _safe_directory(self.integration_checkout)
            if self._common_identity(worktree) != self.common:
                raise ProjectIntegratorError("integration checkout common-directory identity drifted")
            dirty_checkout = bool(
                self._git(
                    "status",
                    "--porcelain=v1",
                    "-z",
                    cwd=worktree,
                )
            )
            if dirty_checkout and not allow_dirty_recovery:
                raise ProjectIntegratorError("dedicated integration checkout is dirty")
            symbolic = self._git_result("symbolic-ref", "--quiet", "HEAD", cwd=worktree)
            if symbolic.returncode == 0:
                raise ProjectIntegratorError("dedicated integration checkout is not detached")
        else:
            if not parent.is_dir():
                raise ProjectIntegratorError("integration checkout parent is absent")
            added = self._git_result(
                "worktree",
                "add",
                "--detach",
                str(self.integration_checkout),
                self.integration_ref,
            )
            if added.returncode:
                raise ProjectIntegratorError("dedicated integration checkout creation failed")
            worktree = _safe_directory(self.integration_checkout)
        if self._common_identity(worktree) != self.common:
            raise ProjectIntegratorError("integration checkout common-directory identity drifted")
        if (
            self._git("status", "--porcelain=v1", "-z", cwd=worktree)
            and not allow_dirty_recovery
        ):
            raise ProjectIntegratorError("dedicated integration checkout is dirty")
        symbolic = self._git_result(
            "symbolic-ref",
            "--quiet",
            "HEAD",
            cwd=worktree,
        )
        if symbolic.returncode == 0:
            raise ProjectIntegratorError(
                "dedicated integration checkout is not detached"
            )
        records = [
            item
            for item in self._worktrees()
            if str(item["worktree"]).casefold()
            == str(worktree).casefold()
        ]
        if (
            len(records) != 1
            or records[0].get("detached") is not True
            or "branch" in records[0]
        ):
            raise ProjectIntegratorError(
                "dedicated integration checkout inventory is ambiguous"
            )
        binding = self._checkout_identity(worktree)
        for _ in range(8):
            state = self._state()
            existing = state.get("integration_checkout")
            if existing is not None:
                if existing != binding:
                    raise ProjectIntegratorError(
                        "integration checkout identity changed"
                    )
                self.checkout_binding = binding
                return worktree
            if dirty_checkout:
                raise ProjectIntegratorError(
                    "unbound integration checkout is dirty"
                )
            try:
                self.store.bind_integration_checkout(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    checkout=binding,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
            self.checkout_binding = binding
            return worktree
        raise ProjectIntegratorError(
            "integration checkout binding could not win the project generation CAS"
        )

    @staticmethod
    def _intent(state: Mapping[str, Any], intent_id: str) -> dict[str, Any]:
        value = next(
            (item for item in state.get("integration_queue", []) if item.get("intent_id") == intent_id),
            None,
        )
        if not isinstance(value, dict):
            raise ProjectIntegratorError("integration intent is absent")
        return dict(value)

    @staticmethod
    def _public_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(intent)
        if (
            result.get("status") in {"accepted", "released"}
            and isinstance(result.get("candidate_commit"), str)
        ):
            result["accepted_commit"] = result["candidate_commit"]
        return result

    def _lease(self, intent_id: str) -> str:
        if (
            self.executor_lease_id is None
            or self.executor_intent_id != intent_id
        ):
            raise ProjectIntegratorError(
                "integration executor lease is not held"
            )
        return self.executor_lease_id

    def _record_candidate(self, intent_id: str, candidate: str) -> dict[str, Any]:
        for _ in range(8):
            state = self._state()
            try:
                return self.store.record_integration_candidate(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    intent_id=intent_id,
                    candidate_commit=candidate,
                    executor_lease_id=self._lease(intent_id),
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
        raise ProjectIntegratorError("integration candidate could not win the project generation CAS")

    def _advance(self, intent_id: str, stage: str) -> dict[str, Any]:
        method = {
            "validated": self.store.mark_integration_validated,
            "cas-applied": self.store.mark_integration_cas_applied,
        }.get(stage)
        if method is None:
            raise ProjectIntegratorError("integration stage is invalid")
        for _ in range(8):
            state = self._state()
            try:
                return method(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    intent_id=intent_id,
                    executor_lease_id=self._lease(intent_id),
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
        raise ProjectIntegratorError("integration stage could not win the project generation CAS")

    def _blocked(
        self,
        intent_id: str,
        *,
        status: str,
        diagnostic: str,
    ) -> dict[str, Any]:
        for _ in range(8):
            observed = self.store.read_state(self.anchor_id)
            if observed.get("status") != "present":
                raise ProjectIntegratorError("project state is unavailable")
            state = dict(observed["state"])
            try:
                return self.store.mark_integration_blocked(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    intent_id=intent_id,
                    status=status,
                    diagnostic_code=diagnostic,
                    executor_lease_id=self._lease(intent_id),
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
        raise ProjectIntegratorError("integration failure could not win the project generation CAS")

    def _prepare_fence(self, intent_id: str) -> dict[str, Any]:
        for _ in range(8):
            state = self._state()
            try:
                return self.store.prepare_integration_ref_cas(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    intent_id=intent_id,
                    executor_lease_id=self._lease(intent_id),
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
        raise ProjectIntegratorError(
            "integration ref fence could not win the project generation CAS"
        )

    def _quarantine(
        self,
        intent_id: str,
        diagnostic: str,
    ) -> dict[str, Any]:
        for _ in range(8):
            state = self._state()
            try:
                return self.store.quarantine_integration_ref(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    intent_id=intent_id,
                    executor_lease_id=self._lease(intent_id),
                    diagnostic_code=diagnostic,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
        raise ProjectIntegratorError(
            "integration ref quarantine could not win the project generation CAS"
        )

    def _release_executor(self) -> None:
        lease_id = self.executor_lease_id
        intent_id = self.executor_intent_id
        if lease_id is None or intent_id is None:
            return
        try:
            for _ in range(16):
                observed = self.store.read_state(self.anchor_id)
                if observed.get("status") != "present":
                    raise ProjectIntegratorError(
                        "project state is unavailable"
                    )
                state = dict(observed["state"])
                executor = state.get("integration_executor")
                if executor is None:
                    return
                if (
                    executor.get("lease_id") != lease_id
                    or executor.get("intent_id") != intent_id
                ):
                    raise ProjectIntegratorError(
                        "integration executor release binding changed"
                    )
                try:
                    self.store.release_integration_executor(
                        self.anchor_id,
                        expected_generation=int(state["generation"]),
                        lease_id=lease_id,
                        intent_id=intent_id,
                    )
                    return
                except ProjectStateError as exc:
                    if str(exc) == "project generation changed":
                        continue
                    raise ProjectIntegratorError(str(exc)) from exc
            raise ProjectIntegratorError(
                "integration executor release could not converge"
            )
        finally:
            self.executor_lease_id = None
            self.executor_intent_id = None

    def _restore_candidate_checkout(
        self,
        worktree: Path,
        admitted_tip: str,
    ) -> None:
        status = self._git_result(
            "status",
            "--porcelain=v1",
            "-z",
            cwd=worktree,
        )
        head = self._git_result(
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
            cwd=worktree,
        )
        if (
            status.returncode == 0
            and not status.stdout
            and head.returncode == 0
            and head.stdout.decode("ascii", "ignore").strip()
            == admitted_tip
        ):
            return
        self._git_result("merge", "--abort", cwd=worktree)
        restored = self._git_result(
            "restore",
            f"--source={admitted_tip}",
            "--staged",
            "--worktree",
            "--",
            ".",
            cwd=worktree,
        )
        detached = self._git_result(
            "checkout",
            "--detach",
            admitted_tip,
            cwd=worktree,
        )
        status = self._git_result(
            "status",
            "--porcelain=v1",
            "-z",
            cwd=worktree,
        )
        head = self._git_result(
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
            cwd=worktree,
        )
        if (
            restored.returncode
            or detached.returncode
            or status.returncode
            or status.stdout
            or head.returncode
            or head.stdout.decode("ascii", "ignore").strip()
            != admitted_tip
        ):
            raise ProjectIntegratorError(
                "integration candidate cleanup failed"
            )

    def _candidate(self, intent: Mapping[str, Any], worktree: Path) -> str:
        admitted_tip = str(intent["admitted_tip"])
        result_commit = str(intent["result"]["result_commit"])
        if self._integration_tip() != admitted_tip:
            raise ProjectIntegratorError("integration ref changed before candidate preparation")
        self._git("checkout", "--detach", admitted_tip, cwd=worktree)
        merged = self._git_result(
            "merge",
            "--no-ff",
            "--no-commit",
            result_commit,
            cwd=worktree,
        )
        if merged.returncode:
            self._git_result("merge", "--abort", cwd=worktree)
            raise ProjectIntegratorError("integration merge conflict")
        try:
            self._trip("after-merge")
            version_request = intent.get("version_finalization")
            if version_request is not None:
                payload = self.store.read_version_finalization_payload(
                    self.anchor_id,
                    intent_id=str(intent["intent_id"]),
                    executor_lease_id=self._lease(
                        str(intent["intent_id"])
                    ),
                )
                if not isinstance(payload, dict):
                    raise ProjectIntegratorError(
                        "version finalization payload is absent"
                    )
                target = str(version_request["requested_target"]).encode(
                    "utf-8"
                )
                for relative, content in payload.items():
                    destination = worktree.joinpath(*relative.split("/"))
                    if (
                        not destination.is_file()
                        or target not in content
                    ):
                        raise ProjectIntegratorError(
                            "version finalization surface does not bind the requested target"
                        )
                    destination.write_bytes(content)
                added = self._git_result(
                    "add",
                    "--",
                    *sorted(payload),
                    cwd=worktree,
                )
                if added.returncode:
                    raise ProjectIntegratorError(
                        "version finalization staging failed"
                    )
            message = (
                "OpenBuild integrate "
                f"{intent['result']['lane_id']} prerelease ticket {intent['ticket']}"
            )
            committed = self._git_result(
                "commit",
                "-m",
                message,
                cwd=worktree,
            )
            if committed.returncode:
                raise ProjectIntegratorError(
                    "integration candidate commit failed"
                )
            return self._commit(
                self._git(
                    "rev-parse",
                    "--verify",
                    "HEAD^{commit}",
                    cwd=worktree,
                ),
                message="integration candidate commit is invalid",
            )
        except Exception as exc:
            try:
                self._restore_candidate_checkout(
                    worktree,
                    admitted_tip,
                )
            except ProjectIntegratorError as cleanup_exc:
                raise cleanup_exc from exc
            if isinstance(exc, ProjectIntegratorError):
                raise
            raise ProjectIntegratorError(
                "integration candidate preparation failed"
            ) from exc

    def _validate_candidate(
        self,
        candidate: str,
        argv: Sequence[str],
    ) -> bool:
        parent = self.integration_checkout.parent
        with tempfile.TemporaryDirectory(
            prefix="openbuild-integration-validation-",
            dir=parent,
        ) as directory:
            validation_checkout = Path(directory) / "checkout"
            added = self._git_result(
                "worktree",
                "add",
                "--detach",
                str(validation_checkout),
                candidate,
            )
            if added.returncode:
                raise ProjectIntegratorError("integration validation checkout creation failed")
            try:
                if self._common_identity(validation_checkout) != self.common:
                    raise ProjectIntegratorError("integration validation common-directory identity drifted")
                before = self._git("status", "--porcelain=v1", "-z", cwd=validation_checkout)
                if before:
                    raise ProjectIntegratorError("integration validation checkout is dirty")
                try:
                    completed = subprocess.run(
                        list(argv),
                        cwd=validation_checkout,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=300,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    return False
                if (
                    completed.returncode != 0
                    or len(completed.stdout) > 1024 * 1024
                    or len(completed.stderr) > 1024 * 1024
                    or self._git("status", "--porcelain=v1", "-z", cwd=validation_checkout) != before
                ):
                    return False
                return True
            finally:
                removed = self._git_result(
                    "worktree",
                    "remove",
                    "--force",
                    str(validation_checkout),
                )
                if removed.returncode:
                    raise ProjectIntegratorError("integration validation checkout cleanup failed")

    def _record_acceptance_and_release(self, intent: Mapping[str, Any]) -> dict[str, Any]:
        intent_id = str(intent["intent_id"])
        candidate = str(intent["candidate_commit"])
        result = intent["result"]
        if not isinstance(result, dict):
            raise ProjectIntegratorError("integration result tuple is invalid")
        for _ in range(8):
            state = self._state()
            current = self._intent(state, intent_id)
            if current["status"] == "cas-applied":
                try:
                    acceptance = self.store.record_scope_integration_acceptance(
                        self.anchor_id,
                        expected_generation=int(state["generation"]),
                        lane_id=str(result["lane_id"]),
                        admitted_commit=str(result["admitted_commit"]),
                        accepted_commit=candidate,
                        validation_argv=list(result["validation_argv"]),
                        executor_lease_id=self._lease(intent_id),
                    )
                except ProjectStateError as exc:
                    if str(exc) == "project generation changed":
                        continue
                    self._quarantine(
                        intent_id,
                        "acceptance-failed",
                    )
                    raise ProjectIntegratorError(
                        "post-CAS acceptance validation failed; integration ref remains fenced"
                    ) from exc
                self._trip("after-acceptance")
                state = self._state()
                try:
                    current = self.store.mark_integration_accepted(
                        self.anchor_id,
                        expected_generation=int(state["generation"]),
                        intent_id=intent_id,
                        acceptance_id=str(acceptance["acceptance_id"]),
                        executor_lease_id=self._lease(intent_id),
                    )
                except ProjectStateError as exc:
                    if str(exc) == "project generation changed":
                        continue
                    raise ProjectIntegratorError(str(exc)) from exc
            if current["status"] == "accepted":
                try:
                    ProjectScopeManager(
                        self.store,
                        self.anchor_id,
                        checkout=self.checkout,
                    ).release(
                        str(result["lane_id"]),
                        acceptance=str(current["acceptance_id"]),
                        executor_lease_id=self._lease(intent_id),
                    )
                except ProjectScopeError as exc:
                    raise ProjectIntegratorError(str(exc)) from exc
                self._trip("after-release")
                state = self._state()
                try:
                    released = self.store.mark_integration_released(
                        self.anchor_id,
                        expected_generation=int(state["generation"]),
                        intent_id=intent_id,
                        executor_lease_id=self._lease(intent_id),
                    )
                    return self._public_intent(released)
                except ProjectStateError as exc:
                    if str(exc) == "project generation changed":
                        continue
                    raise ProjectIntegratorError(str(exc)) from exc
            return current
        raise ProjectIntegratorError("integration acceptance could not converge")

    def integrate_next(
        self,
        *,
        requested_version_target: str | None = None,
        version_surfaces: Mapping[str, bytes] | None = None,
    ) -> dict[str, Any] | None:
        """Replay or finalize exactly one queue head without touching user work."""

        if not self.invocation_lock.acquire(blocking=False):
            raise ProjectIntegratorError(
                "integration invocation is already active"
            )
        try:
            return self._integrate_next(
                requested_version_target=requested_version_target,
                version_surfaces=version_surfaces,
            )
        finally:
            self.invocation_lock.release()

    def _integrate_next(
        self,
        *,
        requested_version_target: str | None,
        version_surfaces: Mapping[str, bytes] | None,
    ) -> dict[str, Any] | None:
        worktree = self._ensure_integration_checkout(
            allow_dirty_recovery=True,
        )
        if self.checkout_binding is None:
            raise ProjectIntegratorError(
                "integration checkout is not durably bound"
            )
        initial_state = self._state()
        recoverable = [
            item
            for item in initial_state["integration_queue"]
            if item.get("status") == "integrating"
            and item.get("candidate_commit") is None
            and item.get("admitted_tip") == self._integration_tip()
        ]
        checkout_dirty = bool(
            self._git(
                "status",
                "--porcelain=v1",
                "-z",
                cwd=worktree,
            )
        )
        if checkout_dirty and len(recoverable) != 1:
            raise ProjectIntegratorError(
                "dedicated integration checkout is dirty"
            )
        recoverable_intent_id = (
            str(recoverable[0]["intent_id"])
            if len(recoverable) == 1
            else None
        )
        claimed: dict[str, Any] | None = None
        for _ in range(16):
            state = self._state()
            try:
                claimed = self.store.claim_next_integration_intent(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    executor_owner=self.integration_owner,
                    owner_token=self.owner_token,
                    pid=os.getpid(),
                    process_identity=self.process_identity,
                    checkout=self.checkout_binding,
                    requested_version_target=requested_version_target,
                    version_surfaces=version_surfaces,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
            if claimed is None:
                return None
            lease_id = claimed.pop("executor_lease_id", None)
            if not isinstance(lease_id, str):
                raise ProjectIntegratorError(
                    "integration executor lease was not returned"
                )
            self.executor_lease_id = lease_id
            self.executor_intent_id = str(claimed["intent_id"])
            break
        if claimed is None:
            raise ProjectIntegratorError(
                "integration queue could not claim an executor"
            )
        intent_id = str(claimed["intent_id"])
        try:
            if recoverable_intent_id is not None:
                if intent_id != recoverable_intent_id:
                    raise ProjectIntegratorError(
                        "integration candidate recovery binding changed"
                    )
                self._restore_candidate_checkout(
                    worktree,
                    str(claimed["admitted_tip"]),
                )
            for _ in range(16):
                state = self._state()
                intent = self._intent(state, intent_id)
                executor = state.get("integration_executor")
                if (
                    not isinstance(executor, Mapping)
                    or executor.get("lease_id")
                    != self._lease(intent_id)
                ):
                    raise ProjectIntegratorError(
                        "integration executor lease changed"
                    )
                status = str(intent["status"])
                if status in {"released", "blocked", "stale", "no-op"}:
                    return self._public_intent(intent)
                if status == "integrating":
                    try:
                        candidate = self._candidate(intent, worktree)
                    except ProjectIntegratorError as exc:
                        if str(exc) == "integration merge conflict":
                            return self._blocked(
                                intent_id,
                                status="blocked",
                                diagnostic="merge-conflict",
                            )
                        if str(exc) == "integration ref changed before candidate preparation":
                            return self._blocked(
                                intent_id,
                                status="stale",
                                diagnostic="cas-race",
                            )
                        raise
                    intent = self._record_candidate(intent_id, candidate)
                    self._trip("after-candidate")
                    status = str(intent["status"])
                if status == "candidate":
                    candidate = str(intent["candidate_commit"])
                    if not self._validate_candidate(
                        candidate,
                        intent["result"]["validation_argv"],
                    ):
                        return self._blocked(
                            intent_id,
                            status="blocked",
                            diagnostic="validation-failed",
                        )
                    intent = self._advance(intent_id, "validated")
                    self._trip("after-validation")
                    status = str(intent["status"])
                if status == "validated":
                    candidate = str(intent["candidate_commit"])
                    fence = state.get("integration_fence")
                    if not (
                        isinstance(fence, Mapping)
                        and fence.get("intent_id") == intent_id
                    ):
                        self._prepare_fence(intent_id)
                    self._trip("before-cas")
                    tip = self._integration_tip()
                    if tip == candidate:
                        intent = self._advance(intent_id, "cas-applied")
                    elif tip != str(intent["admitted_tip"]):
                        try:
                            intent = (
                                self.store.mark_integration_pre_cas_stale(
                                    self.anchor_id,
                                    expected_generation=int(
                                        state["generation"]
                                    ),
                                    intent_id=intent_id,
                                    executor_lease_id=self._lease(
                                        intent_id
                                    ),
                                    observed_tip=tip,
                                )
                            )
                        except ProjectStateError as exc:
                            if str(exc) == "project generation changed":
                                continue
                            raise ProjectIntegratorError(
                                str(exc)
                            ) from exc
                        return self._public_intent(intent)
                    else:
                        cas = self._git_result(
                            "update-ref",
                            self.integration_ref,
                            candidate,
                            str(intent["admitted_tip"]),
                        )
                        if cas.returncode:
                            observed_tip = self._integration_tip()
                            if observed_tip != candidate:
                                self._quarantine(
                                    intent_id,
                                    "ref-ambiguous",
                                )
                                raise ProjectIntegratorError(
                                    "integration ref CAS failed while fenced"
                                )
                        self._trip("after-cas")
                        intent = self._advance(
                            intent_id,
                            "cas-applied",
                        )
                    status = str(intent["status"])
                if status in {"cas-applied", "accepted"}:
                    self._trip("before-acceptance")
                    return self._record_acceptance_and_release(intent)
                if status == "released":
                    return self._public_intent(intent)
                raise ProjectIntegratorError(
                    "integration intent state is invalid"
                )
            raise ProjectIntegratorError(
                "integration queue could not converge"
            )
        finally:
            self._release_executor()

    def abandon_no_change(
        self,
        lane_id: str,
        *,
        validation_argv: Sequence[str],
    ) -> dict[str, Any]:
        """Run the strictly no-change T-015 release transaction once.

        This does not reset, commit, or otherwise rewrite a task branch.  A
        lane that differs from its already accepted admitted base is ambiguous
        and remains closed to this escape hatch.
        """

        if not isinstance(lane_id, str) or not _LANE.fullmatch(lane_id):
            raise ProjectIntegratorError("integration lane identifier is invalid")
        argv = self._validation_argv(validation_argv)
        self._ensure_integration_checkout()
        for _ in range(8):
            state = self._state()
            lane = next(
                (item for item in state["lanes"] if item.get("lane_id") == lane_id),
                None,
            )
            safe_stop = lane.get("safe_stop") if isinstance(lane, Mapping) else None
            if (
                not isinstance(lane, dict)
                or lane.get("state") != "ready"
                or lane.get("writer") is not None
                or not isinstance(safe_stop, Mapping)
                or safe_stop.get("status") != "completed"
                or safe_stop.get("preserved_changes") is not False
                or safe_stop.get("completed_state") != "ready"
            ):
                raise ProjectIntegratorError("abandoned no-change lane is not eligible")
            worktree = _safe_directory(Path(str(lane["worktree"])))
            if self._common_identity(worktree) != self.common:
                raise ProjectIntegratorError("abandoned no-change common-directory identity drifted")
            base = str(lane.get("base"))
            existing = next(
                (
                    item
                    for item in state["integration_acceptances"]
                    if item.get("lane_id") == lane_id
                    and item.get("kind") == "abandoned-no-change"
                ),
                None,
            )
            if existing is None:
                if (
                    not _GIT_OBJECT.fullmatch(base)
                    or self._integration_tip() != base
                    or self._git("status", "--porcelain=v1", "-z", cwd=worktree)
                    or self._commit(
                        self._git("rev-parse", "--verify", "HEAD^{commit}", cwd=worktree),
                        message="abandoned no-change lane head is invalid",
                    )
                    != base
                ):
                    raise ProjectIntegratorError("abandoned no-change restore binding is invalid")
                diff_archive = self._git("diff", "--binary", base, cwd=worktree)
                if diff_archive:
                    raise ProjectIntegratorError("abandoned no-change lane has changes")
            else:
                diff_archive = b""
            try:
                acceptance = self.store.record_abandoned_no_change_acceptance(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    lane_id=lane_id,
                    diff_archive=diff_archive,
                    validation_argv=argv,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectIntegratorError(str(exc)) from exc
            self._trip("after-no-op-acceptance")
            try:
                released = ProjectScopeManager(
                    self.store,
                    self.anchor_id,
                    checkout=self.checkout,
                ).release(
                    lane_id,
                    acceptance=str(acceptance["acceptance_id"]),
                )
            except ProjectScopeError as exc:
                raise ProjectIntegratorError(str(exc)) from exc
            return {
                "status": "released" if released["released"] else "accepted",
                "acceptance_id": acceptance["acceptance_id"],
                "accepted_commit": acceptance["accepted_commit"],
                "no_op_archive": acceptance["no_op_archive"],
                "replayed": bool(released["replayed"]),
            }
        raise ProjectIntegratorError("abandoned no-change acceptance could not win the project generation CAS")
