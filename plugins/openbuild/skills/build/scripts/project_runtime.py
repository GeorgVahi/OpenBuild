"""R-032 M6 owner for bounded heavy-job runtime allocation and status."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping

from project_state import ProjectStateError, ProjectStateStore


_CAS_RETRIES = 64
_PUBLIC_STATES = {
    "running",
    "waiting-for-scope",
    "waiting-for-integration",
    "stale",
    "blocked",
    "complete",
}


class ProjectRuntimeError(RuntimeError):
    """A durable runtime allocation or projection could not converge."""


def _opaque_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}-{digest}"


def _integration_order(item: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        0 if item.get("queue_class") == "dependency-unblocking" else 1,
        int(item["enqueue_generation"]),
        str(item["intent_id"]),
    )


class ProjectRuntimeCoordinator:
    """Own runtime tickets and derive a bounded, privacy-safe project trace."""

    def __init__(self, store: ProjectStateStore, anchor_id: str) -> None:
        self.store = store
        self.anchor_id = anchor_id

    def _state(self) -> Mapping[str, Any]:
        for _ in range(_CAS_RETRIES):
            try:
                observed = self.store.read_state(self.anchor_id)
            except PermissionError:
                time.sleep(0.005)
                continue
            if observed.get("status") == "present":
                return observed["state"]
            if observed.get("status") != "indeterminate":
                break
            time.sleep(0.005)
        raise ProjectRuntimeError("project state is unavailable")

    def configure_capacity(self, capacity: int) -> dict[str, Any]:
        for _ in range(_CAS_RETRIES):
            state = self._state()
            try:
                return self.store.configure_runtime_capacity(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    capacity=capacity,
                )
            except ProjectStateError as exc:
                if str(exc) != "project generation changed":
                    raise ProjectRuntimeError(str(exc)) from exc
        raise ProjectRuntimeError("runtime capacity update could not converge")

    def acquire(
        self,
        job_id: str,
        *,
        lane_id: str | None = None,
        port: int | None = None,
        owner_digest: str | None = None,
        claim_receipt: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        for _ in range(_CAS_RETRIES):
            state = self._state()
            try:
                result = self.store.request_runtime_slot(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    job_id=job_id,
                    lane_id=lane_id,
                    port=port,
                    owner_digest=owner_digest,
                )
                claim_acquired = result.pop("_claim_acquired", False)
                if claim_receipt is not None:
                    claim_receipt.clear()
                    claim_receipt["acquired"] = claim_acquired is True
                return result
            except ProjectStateError as exc:
                if str(exc) != "project generation changed":
                    raise ProjectRuntimeError(str(exc)) from exc
        raise ProjectRuntimeError("runtime allocation could not converge")

    def release(
        self,
        job_id: str,
        *,
        owner_digest: str | None = None,
    ) -> dict[str, Any]:
        for _ in range(_CAS_RETRIES):
            state = self._state()
            try:
                return self.store.release_runtime_slot(
                    self.anchor_id,
                    expected_generation=int(state["generation"]),
                    job_id=job_id,
                    owner_digest=owner_digest,
                )
            except ProjectStateError as exc:
                if str(exc) != "project generation changed":
                    raise ProjectRuntimeError(str(exc)) from exc
        raise ProjectRuntimeError("runtime release could not converge")

    def status(self, job_id: str) -> dict[str, Any]:
        runtime = self._state()["runtime"]
        job = next(
            (
                item
                for item in [*runtime["jobs"], *runtime["completed"]]
                if item["job_id"] == job_id
            ),
            None,
        )
        if job is None:
            raise ProjectRuntimeError("runtime job is absent")
        return {
            "job_id": job_id,
            "lane_id": job["lane_id"],
            "ticket": job["ticket"],
            "status": job["status"],
            "namespace": job["namespace"],
            "namespaces": dict(job["namespaces"]),
            "owner_digest": job.get("owner_digest"),
        }

    def public_status(self, lane_id: str) -> dict[str, Any]:
        """Project one authoritative lane/job without caller-supplied prose."""

        state = self._state()
        lane = next(
            (item for item in state["lanes"] if item["lane_id"] == lane_id),
            None,
        )
        runtime = state["runtime"]
        lane_jobs = [
            item
            for item in [*runtime["jobs"], *runtime["completed"]]
            if item["lane_id"] == lane_id
        ]
        job = next(
            (item for item in lane_jobs if item["status"] != "complete"),
            max(lane_jobs, key=lambda item: item["ticket"], default=None),
        )
        intents = [
            item
            for item in state["integration_queue"]
            if item["result"]["lane_id"] == lane_id
        ]
        if lane is None and job is None and not intents:
            raise ProjectRuntimeError("project lane is absent")

        scheduler = lane.get("scheduler_binding") if lane is not None else None
        task_id = (
            str(scheduler["task_id"])
            if isinstance(scheduler, Mapping)
            and isinstance(scheduler.get("task_id"), str)
            else _opaque_id("task", lane_id)
        )
        milestone_id = (
            str(scheduler["milestone_id"])
            if isinstance(scheduler, Mapping)
            and isinstance(scheduler.get("milestone_id"), str)
            else (
                str(lane["milestone"])
                if lane is not None and isinstance(lane.get("milestone"), str)
                else _opaque_id("milestone", lane_id)
            )
        )

        public_state = "running"
        reason_code = "lane-active"
        dependency: str | None = None
        position: int | None = None
        last_transition = "lane-active"
        next_action = "continue"

        latest_intent = max(
            intents,
            key=lambda item: (item["enqueue_generation"], item["intent_id"]),
            default=None,
        )
        failed_intent = (
            latest_intent
            if latest_intent is not None
            and latest_intent["status"] in {"blocked", "stale"}
            else None
        )
        lane_state = lane.get("state") if lane is not None else None
        if (
            lane is not None
            and lane.get("integration_stale") is not None
        ) or (
            failed_intent is not None and failed_intent["status"] == "stale"
        ):
            public_state = "stale"
            reason_code = "integration-stale"
            dependency = "integration-ref"
            last_transition = "integration-stale"
            next_action = "rebind-dependencies"
        elif failed_intent is not None and failed_intent["status"] == "blocked":
            public_state = "blocked"
            reason_code = "integration-blocked"
            dependency = "integration-validation"
            last_transition = "integration-blocked"
            next_action = "inspect-safe-diagnostic"
        elif lane_state in {"quarantined", "recovery-ready", "cancelled"}:
            public_state = "blocked"
            reason_code = f"lane-{lane_state}"
            dependency = "lane-recovery"
            last_transition = f"lane-{lane_state}"
            next_action = "resume-or-close-lane"
        elif lane_state == "waiting-for-scope":
            waiting_lanes = sorted(
                (
                    item
                    for item in state["lanes"]
                    if item.get("state") == "waiting-for-scope"
                ),
                key=lambda item: (
                    int(item.get("scope_enqueue_sequence") or 0),
                    str(item["lane_id"]),
                ),
            )
            public_state = "waiting-for-scope"
            reason_code = "scope-conflict"
            dependency = "scope-reservation"
            position = 1 + next(
                index
                for index, item in enumerate(waiting_lanes)
                if item["lane_id"] == lane_id
            )
            last_transition = "scope-wait"
            next_action = "wait-for-scope-release"
        elif latest_intent is not None and latest_intent["status"] in {
            "released",
            "no-op",
        }:
            public_state = "complete"
            reason_code = "integration-complete"
            last_transition = "integration-complete"
            next_action = "none"
        elif lane_state == "waiting-for-integration":
            queued = sorted(
                (
                    item
                    for item in state["integration_queue"]
                    if item["status"] == "queued"
                ),
                key=_integration_order,
            )
            public_state = "waiting-for-integration"
            reason_code = (
                "integration-priority"
                if latest_intent is not None
                and latest_intent.get("queue_class")
                == "dependency-unblocking"
                else "integration-queued"
            )
            dependency = "integration-order"
            matching = next(
                (
                    index
                    for index, item in enumerate(queued)
                    if item["result"]["lane_id"] == lane_id
                ),
                None,
            )
            position = matching + 1 if matching is not None else 1
            last_transition = "integration-wait"
            next_action = "wait-for-integration"
        elif job is not None and job["status"] == "waiting-for-capacity":
            waiting = sorted(
                (
                    item
                    for item in runtime["jobs"]
                    if item["status"] == "waiting-for-capacity"
                ),
                key=lambda item: item["ticket"],
            )
            public_state = "blocked"
            reason_code = "capacity-wait"
            dependency = "runtime-capacity"
            position = 1 + next(
                index
                for index, item in enumerate(waiting)
                if item["job_id"] == job["job_id"]
            )
            last_transition = "capacity-wait"
            next_action = "wait-for-runtime-capacity"
        elif lane_state == "closed" or (
            lane is None
            and job is not None
            and job["status"] == "complete"
        ):
            public_state = "complete"
            reason_code = "lane-complete"
            last_transition = "lane-complete"
            next_action = "none"
        elif job is not None and job["status"] == "running":
            reason_code = "runtime-active"
            last_transition = "runtime-active"
            next_action = "continue-runtime-job"
        elif lane_state in {"creating", "ready", "running"}:
            reason_code = f"lane-{lane_state}"
            last_transition = f"lane-{lane_state}"

        if public_state not in _PUBLIC_STATES:
            raise ProjectRuntimeError("public project status is invalid")
        return {
            "state": public_state,
            "task_id": task_id,
            "lane_id": lane_id,
            "milestone_id": milestone_id,
            "reason_code": reason_code,
            "queue_dependency": dependency,
            "position": position,
            "last_transition": last_transition,
            "next_action": next_action,
        }

    def public_trace(self) -> list[dict[str, Any]]:
        state = self._state()
        lane_ids = {
            str(item["lane_id"]) for item in state["lanes"]
        } | {
            str(item["lane_id"])
            for item in [
                *state["runtime"]["jobs"],
                *state["runtime"]["completed"],
            ]
        }
        return [self.public_status(lane_id) for lane_id in sorted(lane_ids)]
