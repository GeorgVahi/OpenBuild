"""R-031 M3 fail-closed project-wide scope and resource lease policy.

The state store remains the only durable sink.  This owner only derives a
validated next projection and uses its generation CAS; it never infers a
release from liveness, a heartbeat, or a PID observation.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from project_state import (
    ProjectStateError,
    ProjectStateStore,
    _is_link_or_reparse,
    _safe_stop_intent_id,
)


class ProjectScopeError(RuntimeError):
    pass


class _LiveCycleSafeStop(RuntimeError):
    def __init__(self, lane_id: str, reservation: str) -> None:
        super().__init__(lane_id, reservation)
        self.lane_id = lane_id
        self.reservation = reservation


_LANE = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_KINDS = frozenset({"file", "directory", "contract", "resource"})
_KIND_ORDER = {"file": 0, "directory": 1, "contract": 2, "resource": 3}


class ProjectScopeManager:
    """Own hard scopes across lanes, with durable wait and cycle handling."""

    def __init__(
        self,
        store: ProjectStateStore,
        anchor_id: str,
        *,
        checkout: Path,
    ) -> None:
        self.store = store
        self.anchor_id = anchor_id
        self.checkout = Path(os.path.abspath(os.fspath(checkout)))
        try:
            metadata = self.checkout.lstat()
        except OSError as exc:
            raise ProjectScopeError("scope checkout is unreadable") from exc
        if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ProjectScopeError("scope checkout is not a real directory")

    @staticmethod
    def _path(value: Any) -> str:
        if not isinstance(value, str):
            raise ProjectScopeError("scope path is not text")
        normalized = unicodedata.normalize("NFC", value)
        parts = normalized.split("/")
        if (
            normalized != value
            or not normalized
            or normalized.startswith("/")
            or "\\" in normalized
            or "\0" in normalized
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
            or (len(parts[0]) >= 2 and parts[0][1] == ":")
        ):
            raise ProjectScopeError("scope is not a canonical repository path")
        if os.path.normcase("A") == os.path.normcase("a"):
            for part in parts:
                stem = part.split(".", 1)[0].upper()
                if part.endswith((" ", ".")) or stem in _WINDOWS_RESERVED:
                    raise ProjectScopeError("scope has a Windows path alias")
        return normalized

    def _assert_real_path(self, path: str, kind: str) -> None:
        current = self.checkout
        parts = path.split("/")
        for part in parts[:-1]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                return
            except OSError as exc:
                raise ProjectScopeError("scope ancestor is unreadable") from exc
            if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise ProjectScopeError("scope has a link or non-directory ancestor")
        target = current / parts[-1]
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ProjectScopeError("scope target is unreadable") from exc
        if _is_link_or_reparse(metadata):
            raise ProjectScopeError("scope target is a link or reparse point")
        if kind == "file" and not stat.S_ISREG(metadata.st_mode):
            raise ProjectScopeError("file scope target is not a regular file")
        if kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
            raise ProjectScopeError("directory scope target is not a directory")

    @classmethod
    def _order(cls, claim: Mapping[str, Any]) -> tuple[int, str, str, str]:
        return (
            _KIND_ORDER[str(claim["kind"])],
            str(claim["path"]).casefold(),
            str(claim["path"]),
            str(claim["mode"]),
        )

    def normalize(self, scopes: Sequence[object]) -> list[dict[str, str]]:
        if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)) or not scopes:
            raise ProjectScopeError("scope set is invalid")
        normalized: list[dict[str, str]] = []
        for raw in scopes:
            legacy_path_scope = isinstance(raw, str)
            if legacy_path_scope:
                candidate: dict[str, Any] = {
                    "kind": "directory",
                    "path": raw,
                    "mode": "hard",
                }
            elif isinstance(raw, Mapping):
                candidate = dict(raw)
            else:
                raise ProjectScopeError("scope request is invalid")
            if set(candidate) != {"kind", "path", "mode"}:
                raise ProjectScopeError("scope fields are incomplete or unknown")
            kind = candidate.get("kind")
            mode = candidate.get("mode")
            if kind not in _KINDS or mode not in {"hard", "soft"}:
                raise ProjectScopeError("scope kind or mode is invalid")
            path = self._path(candidate.get("path"))
            if kind in {"file", "directory"}:
                self._assert_real_path(
                    path,
                    "legacy-path" if legacy_path_scope else str(kind),
                )
            normalized.append({"kind": str(kind), "path": path, "mode": str(mode)})
        normalized.sort(key=self._order)
        keys = [(item["kind"], item["path"].casefold(), item["mode"]) for item in normalized]
        if len(keys) != len(set(keys)):
            raise ProjectScopeError("scope set contains case or path aliases")
        hard = [item for item in normalized if item["mode"] == "hard"]
        for index, left in enumerate(hard):
            if any(self._overlaps(left, right) for right in hard[index + 1 :]):
                raise ProjectScopeError("scope set contains an ancestor collision")
        return normalized

    @staticmethod
    def _overlaps(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        left_kind, right_kind = left["kind"], right["kind"]
        left_path = str(left["path"]).casefold()
        right_path = str(right["path"]).casefold()
        if left_kind in {"file", "directory"} and right_kind in {"file", "directory"}:
            return (
                left_path == right_path
                or left_path.startswith(right_path + "/")
                or right_path.startswith(left_path + "/")
            )
        return left_kind == right_kind and left_path == right_path

    def _state(self) -> dict[str, Any]:
        for attempt in range(32):
            result = self.store.read_state(self.anchor_id)
            if result.get("status") == "present":
                return dict(result["state"])
            if attempt < 31:
                time.sleep(0.005)
        raise ProjectScopeError("project scope state is unavailable")

    def _publish(
        self,
        state: Mapping[str, Any],
        lanes: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        try:
            return self.store.replace_lane_state(
                self.anchor_id,
                expected_generation=int(state["generation"]),
                lanes=lanes,
                scopes=scopes,
            )
        except ProjectStateError as exc:
            raise ProjectScopeError(str(exc)) from exc

    def _integration_tip(self, state: Mapping[str, Any]) -> str:
        session = state.get("lane_session")
        if not isinstance(session, Mapping):
            raise ProjectScopeError("lane session binding is unavailable")
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--verify",
                f"{session['integration_ref']}^{{commit}}",
            ],
            cwd=self.checkout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        try:
            value = result.stdout.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ProjectScopeError(
                "integration ref identity is invalid"
            ) from exc
        if result.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", value):
            raise ProjectScopeError("integration ref identity is invalid")
        return value

    @staticmethod
    def _claims(scopes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in scopes
            if item.get("kind") in _KINDS
        ]

    @staticmethod
    def _groups(scopes: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for scope in scopes:
            if scope.get("kind") in _KINDS and scope.get("mode") == "hard":
                groups.setdefault(str(scope["reservation"]), []).append(scope)
        return groups

    def _group_is_eligible(
        self,
        group: Sequence[Mapping[str, Any]],
        scopes: Sequence[Mapping[str, Any]],
    ) -> bool:
        sequence = min(int(item["sequence"]) for item in group)
        reservation = str(group[0]["reservation"])
        for requested in group:
            for existing in scopes:
                if existing.get("kind") == "protected-user-work":
                    if (
                        existing.get("adoption") != "adopted"
                        and requested.get("kind") in {"file", "directory"}
                        and self._overlaps(
                            requested,
                            {"kind": "file", "path": str(existing["path"])},
                        )
                    ):
                        return False
                    continue
                if existing.get("kind") not in _KINDS or existing.get("mode") != "hard":
                    continue
                if str(existing.get("reservation")) == reservation:
                    continue
                if existing.get("status") not in {"active", "waiting"}:
                    continue
                if not self._overlaps(requested, existing):
                    continue
                if existing["status"] == "active":
                    return False
                existing_sequence = int(existing["sequence"])
                if existing_sequence < sequence or (
                    existing_sequence == sequence
                    and str(existing["reservation"]) < reservation
                ):
                    return False
        return True

    def _promote(
        self,
        lanes: list[dict[str, Any]],
        scopes: list[dict[str, Any]],
        *,
        accepted_tip: str,
    ) -> bool:
        changed = False
        groups = self._groups(scopes)
        waiting = sorted(
            (
                (min(int(item["sequence"]) for item in group), reservation, group)
                for reservation, group in groups.items()
                if all(item["status"] == "waiting" for item in group)
            ),
            key=lambda value: (value[0], value[1]),
        )
        for _, _, group in waiting:
            if not self._group_is_eligible(group, scopes):
                continue
            owner = str(group[0]["owner"])
            lane = next(
                (item for item in lanes if item.get("lane_id") == owner),
                None,
            )
            if (
                isinstance(lane, dict)
                and (
                    lane.get("integration_stale") is not None
                    or lane.get("base") != accepted_tip
                    or lane.get("dependency_binding", {}).get(
                        "accepted_base"
                    )
                    not in {None, accepted_tip}
                )
            ):
                continue
            for item in group:
                item["status"] = "active"
            if isinstance(lane, dict) and lane.get("state") == "waiting-for-scope":
                if group[0]["phase"] == "planned":
                    lane["state"] = "creating"
                elif group[0]["phase"] == "expansion":
                    lane["state"] = lane.pop("scope_wait_from", "ready")
            changed = True
        return changed

    def _wait_edges(self, scopes: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
        edges: dict[str, set[str]] = {}
        for requested in scopes:
            if requested.get("kind") not in _KINDS or requested.get("status") != "waiting":
                continue
            owner = str(requested["owner"])
            for held in scopes:
                if (
                    held.get("kind") in _KINDS
                    and held.get("mode") == "hard"
                    and held.get("status") == "active"
                    and held.get("owner") != owner
                    and self._overlaps(requested, held)
                ):
                    edges.setdefault(owner, set()).add(str(held["owner"]))
        return edges

    @staticmethod
    def _cycle_nodes(edges: Mapping[str, set[str]]) -> list[set[str]]:
        index = 0
        stack: list[str] = []
        indices: dict[str, int] = {}
        low: dict[str, int] = {}
        active: set[str] = set()
        components: list[set[str]] = []

        def visit(node: str) -> None:
            nonlocal index
            indices[node] = index
            low[node] = index
            index += 1
            stack.append(node)
            active.add(node)
            for target in sorted(edges.get(node, set())):
                if target not in indices:
                    visit(target)
                    low[node] = min(low[node], low[target])
                elif target in active:
                    low[node] = min(low[node], indices[target])
            if low[node] != indices[node]:
                return
            component: set[str] = set()
            while stack:
                target = stack.pop()
                active.remove(target)
                component.add(target)
                if target == node:
                    break
            if len(component) > 1 or node in edges.get(node, set()):
                components.append(component)

        for node in sorted(edges):
            if node not in indices:
                visit(node)
        return components

    def _cancel_cycles(
        self,
        lanes: list[dict[str, Any]],
        scopes: list[dict[str, Any]],
    ) -> list[str]:
        cancelled: list[str] = []
        while True:
            components = self._cycle_nodes(self._wait_edges(scopes))
            if not components:
                return cancelled
            changed = False
            for component in components:
                cycle_reservations = {
                    str(requested["reservation"])
                    for requested in scopes
                    if requested.get("kind") in _KINDS
                    and requested.get("mode") == "hard"
                    and requested.get("status") == "waiting"
                    and requested.get("owner") in component
                    and any(
                        held.get("kind") in _KINDS
                        and held.get("mode") == "hard"
                        and held.get("status") == "active"
                        and held.get("owner") in component
                        and held.get("owner") != requested.get("owner")
                        and self._overlaps(requested, held)
                        for held in scopes
                    )
                }
                candidates = [
                    item
                    for item in scopes
                    if item.get("kind") in _KINDS
                    and item.get("mode") == "hard"
                    and item.get("status") == "waiting"
                    and item.get("owner") in component
                    and item.get("reservation") in cycle_reservations
                ]
                if not candidates:
                    continue
                victim = max(
                    candidates,
                    key=lambda item: (int(item["sequence"]), str(item["reservation"])),
                )
                reservation = str(victim["reservation"])
                owner = str(victim["owner"])
                lane = next((item for item in lanes if item.get("lane_id") == owner), None)
                if (
                    isinstance(lane, dict)
                    and lane.get("state") in {"running", "quarantined"}
                    and lane.get("writer") is not None
                ):
                    if lane.get("state") != "running":
                        raise ProjectScopeError(
                            "quarantined live scope cycle cannot be rebound"
                        )
                    raise _LiveCycleSafeStop(owner, reservation)
                for item in scopes:
                    if item.get("reservation") == reservation and item.get("status") == "waiting":
                        item["status"] = "cancelled"
                if (
                    isinstance(lane, dict)
                    and lane.get("state") == "waiting-for-scope"
                    and victim.get("phase") == "expansion"
                ):
                    lane["state"] = lane.pop("scope_wait_from", "ready")
                cancelled.append(reservation)
                changed = True
            if not changed:
                return cancelled

    def _request_live_cycle_rebind(
        self,
        state: Mapping[str, Any],
        lanes: list[dict[str, Any]],
        scopes: list[dict[str, Any]],
        live_cycle: _LiveCycleSafeStop,
    ) -> dict[str, Any]:
        lane = next(
            (
                item
                for item in lanes
                if item.get("lane_id") == live_cycle.lane_id
            ),
            None,
        )
        if (
            not isinstance(lane, dict)
            or lane.get("state") != "running"
            or not isinstance(lane.get("writer"), dict)
        ):
            raise ProjectScopeError("live cycle safe-stop owner is not running")
        requested = [
            item
            for item in scopes
            if item.get("owner") == live_cycle.lane_id
            and item.get("reservation") == live_cycle.reservation
            and item.get("phase") == "expansion"
            and item.get("kind") in _KINDS
        ]
        requested_shape = [
            {key: item[key] for key in ("kind", "path", "mode")}
            for item in sorted(requested, key=self._order)
        ]
        if not requested_shape or any(
            item.get("mode") != "hard" for item in requested
        ):
            raise ProjectScopeError("live cycle safe-stop reservation is invalid")
        existing_intent = lane.get("safe_stop")
        if existing_intent is not None:
            if (
                isinstance(existing_intent, dict)
                and existing_intent.get("lane_id") == live_cycle.lane_id
                and existing_intent.get("reservation")
                == live_cycle.reservation
                and existing_intent.get("requested_scopes")
                == requested_shape
            ):
                return {
                    "status": "safe-stop-requested",
                    "reservation": live_cycle.reservation,
                    "intent_id": existing_intent["intent_id"],
                    "cancelled": [],
                    "replayed": True,
                }
            raise ProjectScopeError("live cycle safe-stop binding changed")
        grants = [
            {
                key: item[key]
                for key in (
                    "kind",
                    "path",
                    "mode",
                    "sequence",
                    "reservation",
                    "phase",
                )
            }
            for item in scopes
            if item.get("owner") == live_cycle.lane_id
            and item.get("kind") in _KINDS
            and item.get("mode") == "hard"
            and item.get("status") == "active"
        ]
        grants.sort(key=self._order)
        session = state.get("lane_session")
        if not isinstance(session, dict):
            raise ProjectScopeError("live cycle lane session is unavailable")
        intent = {
            "schema": "project-lane-safe-stop-v1",
            "status": "requested",
            "anchor_id": self.anchor_id,
            "lane_id": live_cycle.lane_id,
            "intent_generation": int(state["generation"]) + 1,
            "session": session,
            "writer": dict(lane["writer"]),
            "old_hard_grants": grants,
            "requested_scopes": requested_shape,
            "reservation": live_cycle.reservation,
            "reason": "scope-wait-cycle",
        }
        intent["intent_id"] = _safe_stop_intent_id(intent)
        lane["safe_stop"] = intent
        try:
            self.store.request_safe_stop_rebind(
                self.anchor_id,
                expected_generation=int(state["generation"]),
                lanes=lanes,
                scopes=scopes,
                intent_id=intent["intent_id"],
            )
        except ProjectStateError as exc:
            raise ProjectScopeError(str(exc)) from exc
        return {
            "status": "safe-stop-requested",
            "reservation": live_cycle.reservation,
            "intent_id": intent["intent_id"],
            "cancelled": [],
            "replayed": False,
        }

    def migrate_legacy_claims(self) -> dict[str, Any]:
        """Turn claimless alpha.2 lane prefixes into explicit hard leases."""

        mandatory_states = {
            "running",
            "recovery-ready",
            "waiting-for-integration",
            "cancelled",
            "quarantined",
            "closed",
        }
        for _ in range(8):
            state = self._state()
            if state.get("integration_fence") is not None:
                raise ProjectScopeError(
                    "integration ref is fenced pending acceptance"
                )
            lanes = [dict(item) for item in state["lanes"]]
            scopes = [dict(item) for item in state["scopes"]]
            claimed_owners = {
                str(item["owner"])
                for item in scopes
                if item.get("kind") in _KINDS and "owner" in item
            }
            protected = [
                item
                for item in scopes
                if item.get("kind") == "protected-user-work"
                and item.get("adoption") != "adopted"
            ]
            candidates: list[tuple[bool, int, dict[str, Any], bool]] = []
            for index, lane in enumerate(lanes):
                lane_id = str(lane["lane_id"])
                if (
                    lane.get("scope_schema") == "project-scopes-v1"
                    or lane_id in claimed_owners
                ):
                    continue
                requested = []
                for raw_path in lane["scopes"]:
                    path = self._path(raw_path)
                    self._assert_real_path(path, "legacy-path")
                    requested.append(
                        {
                            "kind": "directory",
                            "path": path,
                            "mode": "hard",
                        }
                    )
                blocked_by_protected = any(
                    self._overlaps(
                        claim,
                        {
                            "kind": "file",
                            "path": str(item["path"]),
                        },
                    )
                    for claim in requested
                    for item in protected
                )
                candidates.append(
                    (
                        lane.get("state") in mandatory_states,
                        index,
                        lane,
                        blocked_by_protected,
                    )
                )
            if not candidates:
                return {"migrated": []}
            active = [
                item
                for item in scopes
                if item.get("kind") in _KINDS
                and item.get("mode") == "hard"
                and item.get("status") == "active"
            ]
            migrated: list[str] = []
            for ordinal, (mandatory, _, lane, blocked_by_protected) in enumerate(
                sorted(candidates, key=lambda item: (not item[0], item[1])),
                start=1,
            ):
                lane_id = str(lane["lane_id"])
                ticket = int(state["generation"]) + 1
                reservation = (
                    f"legacy:{ticket:020d}:{ordinal:020d}:{lane_id}"
                )
                claims = [
                    {
                        "kind": "directory",
                        "path": str(path),
                        "mode": "hard",
                        "owner": lane_id,
                        "status": "waiting",
                        "sequence": ticket,
                        "reservation": reservation,
                        "phase": "planned",
                    }
                    for path in lane["scopes"]
                ]
                conflict = blocked_by_protected or any(
                    self._overlaps(claim, held)
                    for claim in claims
                    for held in active
                    if held.get("owner") != lane_id
                )
                if mandatory and conflict:
                    reason = (
                        "live legacy lane overlaps protected user work"
                        if blocked_by_protected
                        else "overlapping live legacy lanes require the runner safe-stop bridge"
                    )
                    raise ProjectScopeError(reason)
                if not conflict:
                    for claim in claims:
                        claim["status"] = "active"
                    active.extend(claims)
                    if lane.get("state") == "waiting-for-scope":
                        lane["state"] = "creating"
                elif lane.get("state") in {"creating", "ready"}:
                    lane["state"] = "waiting-for-scope"
                scopes.extend(sorted(claims, key=self._order))
                migrated.append(lane_id)
            try:
                self._publish(state, lanes, scopes)
            except ProjectScopeError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return {"migrated": migrated}
        raise ProjectScopeError(
            "legacy project scopes could not win the project generation CAS"
        )

    def preflight_legacy_claims(
        self,
        projected_scopes: Sequence[Mapping[str, Any]],
    ) -> None:
        """Reject unsafe live alpha.2 migration before lane admission mutates."""

        state = self._state()
        claimed_owners = {
            str(item["owner"])
            for item in projected_scopes
            if item.get("kind") in _KINDS and "owner" in item
        }
        protected = [
            item
            for item in projected_scopes
            if item.get("kind") == "protected-user-work"
            and item.get("adoption") != "adopted"
        ]
        active = [
            item
            for item in projected_scopes
            if item.get("kind") in _KINDS
            and item.get("mode") == "hard"
            and item.get("status") == "active"
        ]
        for lane in state["lanes"]:
            lane_id = str(lane["lane_id"])
            if (
                lane.get("scope_schema") == "project-scopes-v1"
                or lane_id in claimed_owners
            ):
                continue
            claims = []
            for raw_path in lane["scopes"]:
                path = self._path(raw_path)
                self._assert_real_path(path, "legacy-path")
                claims.append(
                    {"kind": "directory", "path": path, "mode": "hard"}
                )
            mandatory = lane.get("state") in {
                "running",
                "recovery-ready",
                "waiting-for-integration",
                "cancelled",
                "quarantined",
                "closed",
            }
            if not mandatory:
                continue
            blocked_by_protected = any(
                self._overlaps(
                    claim,
                    {"kind": "file", "path": str(item["path"])},
                )
                for claim in claims
                for item in protected
            )
            blocked_by_claim = any(
                self._overlaps(claim, held)
                for claim in claims
                for held in active
                if held.get("owner") != lane_id
            )
            if blocked_by_protected:
                raise ProjectScopeError(
                    "live legacy lane overlaps protected user work"
                )
            if blocked_by_claim:
                raise ProjectScopeError(
                    "overlapping live legacy lanes require the runner safe-stop bridge"
                )
            active.extend({**claim, "owner": lane_id} for claim in claims)

    def _reserve(
        self,
        lane_id: str,
        requested: Sequence[object],
        *,
        phase: str,
    ) -> dict[str, Any]:
        if not _LANE.fullmatch(lane_id) or phase not in {"planned", "expansion"}:
            raise ProjectScopeError("scope reservation is invalid")
        normalized = self.normalize(requested)
        self.migrate_legacy_claims()
        for _ in range(8):
            state = self._state()
            if state.get("integration_fence") is not None:
                raise ProjectScopeError(
                    "integration ref is fenced pending acceptance"
                )
            accepted_tip = self._integration_tip(state)
            lanes = [dict(item) for item in state["lanes"]]
            lane = next((item for item in lanes if item.get("lane_id") == lane_id), None)
            if not isinstance(lane, dict):
                raise ProjectScopeError("scope owner lane does not exist")
            scopes = [dict(item) for item in state["scopes"]]
            existing = [
                item
                for item in scopes
                if item.get("owner") == lane_id
                and item.get("phase") == phase
                and item.get("kind") in _KINDS
            ]
            existing_shape = [
                {key: item[key] for key in ("kind", "path", "mode")}
                for item in sorted(existing, key=self._order)
            ]
            if phase == "planned" and existing:
                if existing_shape != normalized:
                    raise ProjectScopeError("planned scope reservation binding changed")
                changed = self._promote(
                    lanes,
                    scopes,
                    accepted_tip=accepted_tip,
                )
                try:
                    cancelled = self._cancel_cycles(lanes, scopes)
                except _LiveCycleSafeStop as live_cycle:
                    try:
                        return self._request_live_cycle_rebind(
                            state,
                            lanes,
                            scopes,
                            live_cycle,
                        )
                    except ProjectScopeError as exc:
                        if str(exc) == "project generation changed":
                            continue
                        raise
                if changed or cancelled:
                    try:
                        self._publish(state, lanes, scopes)
                    except ProjectScopeError as exc:
                        if str(exc) == "project generation changed":
                            continue
                        raise
                hard = [item for item in existing if item["mode"] == "hard"]
                return {
                    "status": "active" if all(item["status"] == "active" for item in hard) else "waiting-for-scope",
                    "reservation": existing[0]["reservation"],
                    "cancelled": cancelled,
                }
            if phase == "expansion":
                by_reservation: dict[str, list[dict[str, Any]]] = {}
                for item in existing:
                    by_reservation.setdefault(str(item["reservation"]), []).append(item)
                matching = [
                    group
                    for group in by_reservation.values()
                    if [
                        {key: item[key] for key in ("kind", "path", "mode")}
                        for item in sorted(group, key=self._order)
                    ]
                    == normalized
                ]
                if len(matching) == 1:
                    group = matching[0]
                    changed = self._promote(
                        lanes,
                        scopes,
                        accepted_tip=accepted_tip,
                    )
                    try:
                        cancelled = self._cancel_cycles(lanes, scopes)
                    except _LiveCycleSafeStop as live_cycle:
                        try:
                            return self._request_live_cycle_rebind(
                                state,
                                lanes,
                                scopes,
                                live_cycle,
                            )
                        except ProjectScopeError as exc:
                            if str(exc) == "project generation changed":
                                continue
                            raise
                    hard = [item for item in group if item["mode"] == "hard"]
                    status = (
                        "active"
                        if all(item["status"] == "active" for item in hard)
                        else (
                            "cancelled"
                            if hard
                            and all(item["status"] == "cancelled" for item in hard)
                            else "waiting-for-scope"
                        )
                    )
                    if changed or cancelled:
                        try:
                            self._publish(state, lanes, scopes)
                        except ProjectScopeError as exc:
                            if str(exc) == "project generation changed":
                                continue
                            raise
                    return {
                        "status": status,
                        "reservation": group[0]["reservation"],
                        "cancelled": cancelled,
                    }
            if phase == "planned" and lane.get("scope_schema") == "project-scopes-v1":
                sequence = lane.get("scope_enqueue_sequence")
                if not isinstance(sequence, int) or sequence < 1:
                    raise ProjectScopeError(
                        "lane scope enqueue sequence is invalid"
                    )
            else:
                sequence = int(state["generation"]) + 1
            reservation = f"{lane_id}:{phase}:{sequence}"
            claims = [
                {
                    **item,
                    "owner": lane_id,
                    "status": "waiting" if item["mode"] == "hard" else "intent",
                    "sequence": sequence,
                    "reservation": reservation,
                    "phase": phase,
                }
                for item in normalized
            ]
            scopes.extend(claims)
            self._promote(
                lanes,
                scopes,
                accepted_tip=accepted_tip,
            )
            try:
                cancelled = self._cancel_cycles(lanes, scopes)
            except _LiveCycleSafeStop as live_cycle:
                try:
                    return self._request_live_cycle_rebind(
                        state,
                        lanes,
                        scopes,
                        live_cycle,
                    )
                except ProjectScopeError as exc:
                    if str(exc) == "project generation changed":
                        continue
                    raise
            hard = [item for item in claims if item["mode"] == "hard"]
            status = (
                "active"
                if all(item["status"] == "active" for item in hard)
                else (
                    "cancelled"
                    if hard and all(item["status"] == "cancelled" for item in hard)
                    else "waiting-for-scope"
                )
            )
            if phase == "planned" and status == "waiting-for-scope" and lane.get("state") == "creating":
                lane["state"] = "waiting-for-scope"
            if (
                phase == "expansion"
                and status == "waiting-for-scope"
                and lane.get("state") in {"creating", "ready"}
            ):
                lane["scope_wait_from"] = lane["state"]
                lane["state"] = "waiting-for-scope"
            try:
                self._publish(state, lanes, scopes)
            except ProjectScopeError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return {"status": status, "reservation": reservation, "cancelled": cancelled}
        raise ProjectScopeError("scope reservation could not win the project generation CAS")

    def reserve_planned(self, lane_id: str, requested: Sequence[object]) -> dict[str, Any]:
        return self._reserve(lane_id, requested, phase="planned")

    def _request_live_rebind(
        self,
        lane_id: str,
        requested: Sequence[object],
    ) -> dict[str, Any]:
        normalized = self.normalize(requested)
        if any(item["mode"] != "hard" for item in normalized):
            raise ProjectScopeError("live scope expansion requires hard typed scopes")
        for _ in range(8):
            state = self._state()
            lanes = [dict(item) for item in state["lanes"]]
            lane = next((item for item in lanes if item.get("lane_id") == lane_id), None)
            if (
                not isinstance(lane, dict)
                or lane.get("state") != "running"
                or not isinstance(lane.get("writer"), dict)
            ):
                raise ProjectScopeError("live scope expansion owner is not running")
            existing_intent = lane.get("safe_stop")
            if (
                existing_intent is not None
                and (
                    not isinstance(existing_intent, Mapping)
                    or existing_intent.get("status") != "completed"
                )
            ):
                if (
                    isinstance(existing_intent, dict)
                    and existing_intent.get("requested_scopes") == normalized
                    and existing_intent.get("lane_id") == lane_id
                ):
                    return {
                        "status": "safe-stop-requested",
                        "reservation": existing_intent["reservation"],
                        "intent_id": existing_intent["intent_id"],
                        "replayed": True,
                    }
                raise ProjectScopeError("live safe-stop rebind binding changed")
            scopes = [dict(item) for item in state["scopes"]]
            reservation = f"{lane_id}:expansion:{int(state['generation']) + 1}"
            claims = [
                {
                    **item,
                    "owner": lane_id,
                    "status": "waiting",
                    "sequence": int(state["generation"]) + 1,
                    "reservation": reservation,
                    "phase": "expansion",
                }
                for item in normalized
            ]
            scopes.extend(claims)
            grants = [
                {
                    key: item[key]
                    for key in (
                        "kind",
                        "path",
                        "mode",
                        "sequence",
                        "reservation",
                        "phase",
                    )
                }
                for item in scopes
                if item.get("owner") == lane_id
                and item.get("kind") in _KINDS
                and item.get("mode") == "hard"
                and item.get("status") == "active"
            ]
            grants.sort(key=self._order)
            session = state.get("lane_session")
            if not isinstance(session, dict):
                raise ProjectScopeError("live safe-stop lane session is unavailable")
            intent = {
                "schema": "project-lane-safe-stop-v1",
                "status": "requested",
                "anchor_id": self.anchor_id,
                "lane_id": lane_id,
                "intent_generation": int(state["generation"]) + 1,
                "session": session,
                "writer": dict(lane["writer"]),
                "old_hard_grants": grants,
                "requested_scopes": normalized,
                "reservation": reservation,
                "reason": "scope-expansion-wait",
            }
            intent["intent_id"] = _safe_stop_intent_id(intent)
            lane["safe_stop"] = intent
            try:
                self.store.request_safe_stop_rebind(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    lanes=lanes,
                    scopes=scopes,
                    intent_id=intent["intent_id"],
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectScopeError(str(exc)) from exc
            return {
                "status": "safe-stop-requested",
                "reservation": reservation,
                "intent_id": intent["intent_id"],
                "replayed": False,
            }
        raise ProjectScopeError("live safe-stop rebind could not win the project generation CAS")

    def expand(
        self,
        lane_id: str,
        requested: Sequence[object],
        *,
        pre_write: bool,
    ) -> dict[str, Any]:
        if pre_write is not True:
            raise ProjectScopeError("post-write scope expansion is rejected")
        state = self._state()
        lane = next((item for item in state["lanes"] if item.get("lane_id") == lane_id), None)
        if not isinstance(lane, dict):
            raise ProjectScopeError("scope owner lane does not exist")
        if lane.get("state") == "running" and lane.get("writer") is not None:
            return self._request_live_rebind(lane_id, requested)
        if (
            lane.get("state") in {"quarantined", "waiting-for-integration"}
            or lane.get("writer") is not None
        ):
            raise ProjectScopeError("post-write scope expansion is rejected")
        return self._reserve(lane_id, requested, phase="expansion")

    def resolve_wait_cycles(self) -> dict[str, Any]:
        for _ in range(8):
            state = self._state()
            lanes = [dict(item) for item in state["lanes"]]
            scopes = [dict(item) for item in state["scopes"]]
            try:
                cancelled = self._cancel_cycles(lanes, scopes)
            except _LiveCycleSafeStop as live_cycle:
                try:
                    return self._request_live_cycle_rebind(
                        state,
                        lanes,
                        scopes,
                        live_cycle,
                    )
                except ProjectScopeError as exc:
                    if str(exc) == "project generation changed":
                        continue
                    raise
            if not cancelled:
                return {"cancelled": []}
            try:
                self._publish(state, lanes, scopes)
            except ProjectScopeError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise
            return {"cancelled": cancelled}
        raise ProjectScopeError("scope cycle resolution could not win the project generation CAS")

    def release(
        self,
        lane_id: str,
        *,
        acceptance: str,
        executor_lease_id: str | None = None,
    ) -> dict[str, Any]:
        if not _LANE.fullmatch(lane_id) or not isinstance(acceptance, str):
            raise ProjectScopeError(
                "scope release requires registry-resident integration-owner acceptance"
            )
        for _ in range(8):
            state = self._state()
            if not any(
                item.get("acceptance_id") == acceptance
                and item.get("lane_id") == lane_id
                for item in state.get("integration_acceptances", [])
            ):
                raise ProjectScopeError(
                    "scope release requires registry-resident integration-owner acceptance"
                )
            lanes = [dict(item) for item in state["lanes"]]
            scopes = [dict(item) for item in state["scopes"]]
            accepted = next(
                (
                    item
                    for item in state["integration_acceptances"]
                    if item.get("acceptance_id") == acceptance
                    and item.get("lane_id") == lane_id
                ),
                None,
            )
            if not isinstance(accepted, dict):
                raise ProjectScopeError(
                    "scope release requires registry-resident integration-owner acceptance"
                )
            intent = next(
                (
                    item
                    for item in state.get("integration_queue", [])
                    if item.get("acceptance_id") == acceptance
                    or (
                        item.get("result", {}).get("lane_id") == lane_id
                        and item.get("candidate_commit")
                        == accepted.get("accepted_commit")
                    )
                ),
                None,
            )
            producer_result = (
                intent.get("result")
                if isinstance(intent, Mapping)
                else None
            )
            producer_result_digest = (
                str(producer_result.get("digest"))
                if isinstance(producer_result, Mapping)
                else acceptance
            )
            producer_dependencies = (
                producer_result.get("dependency_binding", {})
                if isinstance(producer_result, Mapping)
                else {}
            )
            producer_scopes = [
                {
                    "kind": item["kind"],
                    "path": item["path"],
                    "mode": item["mode"],
                }
                for item in accepted.get("reservations", [])
                if accepted.get("kind") != "abandoned-no-change"
                if item.get("kind") in _KINDS
                and item.get("mode") == "hard"
                and item.get("status") in {"active", "released"}
            ]
            for scope in scopes:
                if (
                    scope.get("owner") == lane_id
                    and scope.get("kind") in _KINDS
                    and scope.get("mode") == "hard"
                ):
                    if scope.get("status") == "active":
                        scope["status"] = "released"
                        scope["release"] = {
                            "acceptance_id": acceptance,
                            "released_generation": int(state["generation"]) + 1,
                        }
                    elif scope.get("status") == "waiting":
                        scope["status"] = "cancelled"
            # A released scope does not authorize a waiter on its old admitted
            # base.  The lane owner must first consume this stale marker,
            # refresh the common base and rebind its scheduler/spec/allowed-set
            # contract, then call reserve_planned again.
            producer_scheduler = next(
                (
                    item.get("scheduler_binding")
                    for item in state["lanes"]
                    if item.get("lane_id") == lane_id
                ),
                None,
            )
            for lane in lanes:
                if (
                    lane.get("lane_id") == lane_id
                    and isinstance(producer_result, Mapping)
                    and isinstance(
                        producer_result.get("dependency_stale"),
                        Mapping,
                    )
                    and lane.get("integration_stale")
                    == producer_result["dependency_stale"]
                ):
                    lane.pop("integration_stale", None)
                    break
            for lane in lanes:
                consumer_binding = lane.get("dependency_binding")
                read_dependencies = (
                    consumer_binding.get("read_dependencies", [])
                    if isinstance(consumer_binding, Mapping)
                    else [
                        item
                        for item in lane.get("scope_requests", [])
                        if isinstance(item, Mapping)
                        and (
                            item.get("mode") == "soft"
                            or item.get("kind") == "contract"
                        )
                    ]
                )
                hard_dependencies = [
                    item
                    for item in lane.get("scope_requests", [])
                    if isinstance(item, Mapping)
                    and item.get("mode") == "hard"
                ]
                dependency_overlap = any(
                    self._overlaps(read, changed)
                    for read in [*read_dependencies, *hard_dependencies]
                    for changed in producer_scopes
                )
                scheduler_dependency = False
                consumer_scheduler = lane.get("scheduler_binding")
                if (
                    isinstance(producer_scheduler, Mapping)
                    and isinstance(consumer_scheduler, Mapping)
                    and producer_scheduler.get("task_id")
                    == consumer_scheduler.get("task_id")
                ):
                    consumer_record = next(
                        (
                            item
                            for item in state.get("milestones", [])
                            if item.get("task_id")
                            == consumer_scheduler.get("task_id")
                            and item.get("milestone_id")
                            == consumer_scheduler.get("milestone_id")
                        ),
                        None,
                    )
                    scheduler_dependency = (
                        isinstance(consumer_record, Mapping)
                        and producer_scheduler.get("milestone_id")
                        in consumer_record.get("depends_on", [])
                    )
                if (
                    lane.get("lane_id") != lane_id
                    and (
                        dependency_overlap
                        or scheduler_dependency
                    )
                ):
                    lane["integration_stale"] = {
                        "accepted_commit": accepted["accepted_commit"],
                        "acceptance_id": acceptance,
                        "generation": int(state["generation"]) + 1,
                        "dependency_digest": str(
                            producer_dependencies.get(
                                "dependency_digest"
                            )
                            or producer_result_digest
                        ),
                        "producer_result_digest": producer_result_digest,
                    }
            try:
                result = self.store.release_scope_integration_acceptance(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    lane_id=lane_id,
                    acceptance_id=acceptance,
                    lanes=lanes,
                    scopes=scopes,
                    executor_lease_id=executor_lease_id,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectScopeError(str(exc)) from exc
            return {"released": True, "replayed": bool(result["replayed"])}
        raise ProjectScopeError("scope release could not win the project generation CAS")

    def assert_lane_authority(self, lane_id: str) -> None:
        state = self._state()
        if state.get("integration_fence") is not None:
            raise ProjectScopeError(
                "integration ref is fenced pending acceptance"
            )
        lane = next(
            (item for item in state["lanes"] if item.get("lane_id") == lane_id),
            None,
        )
        if not isinstance(lane, dict):
            raise ProjectScopeError("scope owner lane does not exist")
        dependency_binding = lane.get("dependency_binding")
        if (
            lane.get("integration_stale") is not None
            or (
                isinstance(dependency_binding, Mapping)
                and dependency_binding.get("accepted_base")
                != lane.get("base")
            )
        ):
            raise ProjectScopeError(
                "lane dependencies require a fresh accepted-base rebind"
            )
        claims = [
            item
            for item in state["scopes"]
            if item.get("kind") in _KINDS and item.get("owner") == lane_id
        ]
        hard = [
            item
            for item in claims
            if item.get("mode") == "hard" and item.get("status") != "cancelled"
        ]
        if not hard:
            raise ProjectScopeError(
                "legacy lane scopes require project claim migration"
            )
        if any(item.get("status") != "active" for item in hard):
            raise ProjectScopeError("lane hard scopes are not active")

    def assert_write_authority(
        self,
        lane_id: str,
        allowed_paths: Sequence[str],
        *,
        allow_waiting: bool = False,
    ) -> None:
        state = self._state()
        lane = next(
            (item for item in state["lanes"] if item.get("lane_id") == lane_id),
            None,
        )
        safe_stop = lane.get("safe_stop") if isinstance(lane, dict) else None
        if (
            isinstance(safe_stop, Mapping)
            and safe_stop.get("status") in {"requested", "stopping"}
        ):
            raise ProjectScopeError("safe-stop lane has no continuing write authority")
        claims = [
            item
            for item in state["scopes"]
            if item.get("kind") in _KINDS and item.get("owner") == lane_id
        ]
        if not claims:
            raise ProjectScopeError(
                "legacy lane scopes require project claim migration"
            )
        hard = [
            item
            for item in claims
            if item.get("mode") == "hard" and item.get("status") != "cancelled"
        ]
        active_hard = [
            item for item in hard if item.get("status") == "active"
        ]
        if (
            not active_hard
            or (
                not allow_waiting
                and any(item.get("status") != "active" for item in hard)
            )
        ):
            raise ProjectScopeError("lane hard scopes are not active")
        for path in allowed_paths:
            allowed = {"kind": "file", "path": path}
            if not any(
                item.get("kind") in {"file", "directory"}
                and self._overlaps(allowed, item)
                and (
                    item["kind"] == "directory"
                    or item["path"].casefold() == path.casefold()
                )
                for item in active_hard
            ):
                raise ProjectScopeError(
                    "runner allowed path escapes active file or directory scopes"
                )
