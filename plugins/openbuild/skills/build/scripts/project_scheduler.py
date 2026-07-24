"""Fail-closed R-032 M4 durable milestone DAG scheduler.

Milestones are project-state records, never process ownership records.  The
lane bridge gates runner activation and makes ``waiting`` valid only while the
matching lane has no writer lifecycle.  Lanes continue to own worktrees,
scope leases, contained writers, and terminal evidence.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from project_state import (
    ProjectStateError,
    ProjectStateStore,
    _validate_hard_scope_overlaps,
    validate_scope_state,
)


class ProjectSchedulerError(RuntimeError):
    pass


_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_KIND_ORDER = {"file": 0, "directory": 1, "contract": 2, "resource": 3}
_LANE_WAIT_STATES = frozenset({"waiting-for-scope", "recovery-ready"})


class ProjectScheduler:
    def __init__(
        self,
        store: ProjectStateStore,
        anchor_id: str,
        task_id: str,
    ) -> None:
        if not isinstance(task_id, str) or not _IDENTIFIER.fullmatch(task_id):
            raise ProjectSchedulerError("scheduler task identifier is invalid")
        self.store = store
        self.anchor_id = anchor_id
        self.task_id = task_id

    def lane_milestone(self, milestone_id: str) -> dict[str, str]:
        if not isinstance(milestone_id, str) or not _IDENTIFIER.fullmatch(
            milestone_id
        ):
            raise ProjectSchedulerError("milestone identifier is invalid")
        return {
            "schema": "project-scheduler-lane-v1",
            "task_id": self.task_id,
            "milestone_id": milestone_id,
        }

    def _lane_binding(self, milestone_id: str) -> dict[str, str]:
        return self.lane_milestone(milestone_id)

    def _state(self) -> dict[str, Any]:
        result = self.store.read_state(self.anchor_id)
        if result.get("status") != "present":
            raise ProjectSchedulerError("project state is unavailable")
        return dict(result["state"])

    def _task_records(
        self,
        state: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in state["milestones"]
            if item.get("task_id") == self.task_id
        ]

    @staticmethod
    def _derive(
        milestones: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        by_id = {str(item["milestone_id"]): item for item in milestones}
        result: list[dict[str, Any]] = []
        for source in milestones:
            item = dict(source)
            if item.get("state") != "completed":
                item.pop("validation", None)
                item["state"] = (
                    "ready"
                    if all(
                        by_id[dependency].get("state") == "completed"
                        for dependency in item["depends_on"]
                    )
                    else "waiting"
                )
            result.append(item)
        return sorted(result, key=lambda item: item["milestone_id"])

    def _matching_lanes(
        self,
        state: Mapping[str, Any],
        milestone_id: str,
    ) -> list[dict[str, Any]]:
        binding = self._lane_binding(milestone_id)
        return [
            dict(lane)
            for lane in state.get("lanes", [])
            if lane.get("scheduler_binding") == binding
        ]

    def _public(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, list[str]]:
        milestones = self._task_records(state)
        ready: list[str] = []
        waiting: list[str] = []
        completed: list[dict[str, Any]] = []
        for item in milestones:
            if item["state"] == "completed":
                completed.append(item)
                continue
            lane_wait = any(
                lane.get("state") in _LANE_WAIT_STATES
                for lane in self._matching_lanes(
                    state,
                    str(item["milestone_id"]),
                )
            )
            target = waiting if item["state"] == "waiting" or lane_wait else ready
            target.append(str(item["milestone_id"]))
        candidates = sorted(
            completed,
            key=lambda item: (not item["hotspot"], item["milestone_id"]),
        )
        hotspot = {
            str(item["milestone_id"]): bool(item["hotspot"])
            for item in milestones
        }
        return {
            "ready": sorted(
                ready,
                key=lambda milestone_id: (
                    not hotspot[milestone_id],
                    milestone_id,
                ),
            ),
            "waiting": sorted(waiting),
            "completed": sorted(
                str(item["milestone_id"]) for item in completed
            ),
            "integration_candidates": [
                str(item["milestone_id"]) for item in candidates
            ],
        }

    @staticmethod
    def _canonical_scopes(
        value: Any,
        *,
        mode: str,
        required: bool,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list) or (required and not value):
            raise ProjectSchedulerError("milestone scope contract is invalid")
        try:
            parsed = [
                validate_scope_state(dict(item))
                if isinstance(item, Mapping)
                else validate_scope_state(item)
                for item in value
            ]
        except (ProjectStateError, TypeError, ValueError) as exc:
            raise ProjectSchedulerError("milestone scope contract is invalid") from exc
        if any(item["mode"] != mode for item in parsed):
            raise ProjectSchedulerError("milestone scope mode is invalid")
        ordered = sorted(
            parsed,
            key=lambda item: (
                _KIND_ORDER[item["kind"]],
                item["path"].casefold(),
                item["path"],
                item["mode"],
            ),
        )
        identities = [
            (item["kind"], item["path"].casefold(), item["mode"])
            for item in ordered
        ]
        if len(identities) != len(set(identities)):
            raise ProjectSchedulerError("milestone scope aliases are invalid")
        if mode == "hard":
            try:
                _validate_hard_scope_overlaps(ordered)
            except ProjectStateError as exc:
                raise ProjectSchedulerError(
                    "milestone scope aliases are invalid",
                ) from exc
        return ordered

    def _plan_item(self, source: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "milestone_id",
            "depends_on",
            "hard_scopes",
            "soft_intents",
            "primary_signal",
            "red_signal",
            "integration_output",
            "hotspot",
        }
        if not isinstance(source, Mapping) or set(source) != required:
            raise ProjectSchedulerError(
                "milestone decomposition contract is invalid"
            )
        milestone_id = source.get("milestone_id")
        dependencies = source.get("depends_on")
        if (
            not isinstance(milestone_id, str)
            or not _IDENTIFIER.fullmatch(milestone_id)
            or not isinstance(dependencies, list)
            or any(
                not isinstance(item, str) or not _IDENTIFIER.fullmatch(item)
                for item in dependencies
            )
        ):
            raise ProjectSchedulerError(
                "milestone decomposition contract is invalid"
            )
        hard_scopes = self._canonical_scopes(
            source["hard_scopes"],
            mode="hard",
            required=True,
        )
        soft_intents = self._canonical_scopes(
            source["soft_intents"],
            mode="soft",
            required=False,
        )
        hard_keys = {
            (item["kind"], item["path"].casefold())
            for item in hard_scopes
        }
        if hard_keys & {
            (item["kind"], item["path"].casefold())
            for item in soft_intents
        }:
            raise ProjectSchedulerError(
                "milestone hard scope and soft intent overlap"
            )
        return {
            "task_id": self.task_id,
            "milestone_id": milestone_id,
            "depends_on": sorted(dependencies),
            "hard_scopes": hard_scopes,
            "soft_intents": soft_intents,
            "primary_signal": source["primary_signal"],
            "red_signal": source["red_signal"],
            "integration_output": source["integration_output"],
            "hotspot": source["hotspot"],
            "state": "waiting",
        }

    @staticmethod
    def _contract(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key not in {"state", "validation"}
        }

    def publish_plan(
        self,
        plan: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[str]]:
        if (
            not isinstance(plan, Sequence)
            or isinstance(plan, (str, bytes))
            or not plan
        ):
            raise ProjectSchedulerError("milestone plan is invalid")
        proposed = self._derive(
            sorted(
                [self._plan_item(item) for item in plan],
                key=lambda item: item["milestone_id"],
            )
        )
        for _ in range(8):
            state = self._state()
            existing = self._task_records(state)
            if existing:
                if [
                    self._contract(item) for item in existing
                ] != [
                    self._contract(item) for item in proposed
                ]:
                    raise ProjectSchedulerError("milestone plan replay changed")
                return self._public(state)
            combined = sorted(
                [
                    *[dict(item) for item in state["milestones"]],
                    *proposed,
                ],
                key=lambda item: (item["task_id"], item["milestone_id"]),
            )
            try:
                published = self.store.replace_milestone_state(
                    self.anchor_id,
                    expected_generation=state["generation"],
                    milestones=combined,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectSchedulerError(str(exc)) from exc
            return self._public(published)
        raise ProjectSchedulerError(
            "milestone plan could not win the project generation CAS"
        )

    def complete(
        self,
        milestone_id: str,
        *,
        focused_green: bool,
        intermediate_valid: bool,
    ) -> dict[str, list[str]]:
        if focused_green is not True:
            raise ProjectSchedulerError(
                "milestone lacks focused green validation"
            )
        if intermediate_valid is not True:
            raise ProjectSchedulerError(
                "milestone intermediate state is invalid"
            )
        for _ in range(8):
            state = self._state()
            task_records = self._task_records(state)
            item = next(
                (
                    entry
                    for entry in task_records
                    if entry["milestone_id"] == milestone_id
                ),
                None,
            )
            if item is None:
                raise ProjectSchedulerError("milestone is unknown")
            if item["state"] == "completed":
                return self._public(state)
            if item["state"] != "ready":
                raise ProjectSchedulerError(
                    "milestone dependencies are not complete"
                )
            lanes = self._matching_lanes(state, milestone_id)
            if lanes and any(
                lane.get("state") != "waiting-for-integration"
                or not isinstance(lane.get("writer"), dict)
                or not isinstance(lane.get("terminal_evidence"), str)
                for lane in lanes
            ):
                raise ProjectSchedulerError(
                    "milestone lane has not reached accepted terminal validation"
                )
            proposed_task = [dict(entry) for entry in task_records]
            proposed_item = next(
                entry
                for entry in proposed_task
                if entry["milestone_id"] == milestone_id
            )
            proposed_item["state"] = "completed"
            proposed_item["validation"] = {
                "focused_green": True,
                "intermediate_valid": True,
            }
            proposed_task = self._derive(proposed_task)
            others = [
                dict(entry)
                for entry in state["milestones"]
                if entry.get("task_id") != self.task_id
            ]
            combined = sorted(
                [*others, *proposed_task],
                key=lambda entry: (
                    entry["task_id"],
                    entry["milestone_id"],
                ),
            )
            try:
                published = self.store.replace_milestone_state(
                    self.anchor_id,
                    expected_generation=state["generation"],
                    milestones=combined,
                )
            except ProjectStateError as exc:
                if str(exc) == "project generation changed":
                    continue
                raise ProjectSchedulerError(str(exc)) from exc
            return self._public(published)
        raise ProjectSchedulerError(
            "milestone completion could not win the project generation CAS"
        )

    def wait(self, milestone_id: str) -> dict[str, list[str]]:
        state = self._state()
        item = next(
            (
                entry
                for entry in self._task_records(state)
                if entry["milestone_id"] == milestone_id
            ),
            None,
        )
        if item is None:
            raise ProjectSchedulerError("milestone is unknown")
        if item["state"] == "completed":
            raise ProjectSchedulerError("milestone state cannot regress")
        status = self._public(state)
        if milestone_id not in status["waiting"]:
            raise ProjectSchedulerError("milestone is not waiting")
        if any(
            lane.get("writer") is not None
            or lane.get("state")
            in {"running", "quarantined", "waiting-for-integration"}
            for lane in self._matching_lanes(state, milestone_id)
        ):
            raise ProjectSchedulerError(
                "waiting milestone lacks a completed zero-writer lane transition"
            )
        return status

    def status(self) -> dict[str, list[str]]:
        return self._public(self._state())
