#!/usr/bin/env python3
"""Validate and resolve OpenBuild's project, user, or packaged model map."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, NamedTuple

if sys.version_info < (3, 11):
    raise SystemExit("OpenBuild model_map.py requires Python 3.11 or newer")

import tomllib


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_runner import SUPPORTED_AGENTS, RunnerError, load_agent_profile  # noqa: E402


PACKAGED_MODEL_MAP = Path(__file__).resolve().parents[1] / "profiles" / "openbuild_model_map.toml"
RISKS = ("low", "medium", "high", "critical")
USE_CASES = ("discovery", "critic", "implementation", "review")
REQUIRED_ROUTES = {
    ("discovery", "default"),
    *((use_case, risk) for use_case in ("critic", "implementation", "review") for risk in RISKS),
}
TOP_LEVEL_FIELDS = {"schema_version", "name", "writer_policy", "failure_policy", *USE_CASES}
ROUTE_FIELDS = {
    "agents",
    "max_steps",
    "escalation_mode",
    "escalation_triggers",
    "stop_on_success",
    "transport_failure",
    "fallback",
    "critical_confirmed",
}
AGENT_PREFIX = {
    "discovery": "openbuild_search_",
    "critic": "openbuild_review_",
    "implementation": "openbuild_implementation_",
    "review": "openbuild_review_",
}
ESCALATION_MODE = {
    "discovery": "after-evidence",
    "critic": "after-evidence",
    "implementation": "semantic-before-edit",
    "review": "after-evidence",
}
ALLOWED_TRIGGERS = {
    "discovery": {"insufficient-evidence", "ambiguous-ownership", "cross-file-gap"},
    "critic": {"coverage-gap", "unresolved-contradiction", "low-confidence", "material-uncertainty"},
    "implementation": {
        "task-complexity-above-tier",
        "unresolved-cross-layer-reasoning",
        "validation-strategy-uncertain",
        "capability-gap",
    },
    "review": {"actionable-finding", "coverage-gap", "low-confidence", "material-dispute"},
}


class ModelMapError(RuntimeError):
    """A safe, actionable model-map validation failure."""


class ModelRoute(NamedTuple):
    agents: tuple[str, ...]
    max_steps: int
    escalation_mode: str
    escalation_triggers: tuple[str, ...]
    stop_on_success: bool
    transport_failure: str
    fallback: str
    critical_confirmed: bool


class ModelMap(NamedTuple):
    name: str
    writer_policy: str
    failure_policy: str
    routes: dict[tuple[str, str], ModelRoute]
    source: Path
    source_scope: str
    sha256: str


def _required_string(data: Mapping[str, Any], field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ModelMapError(f"{path}: required non-empty field {field!r} is missing")
    return value.strip()


def _string_list(value: Any, *, field: str, path: Path, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ModelMapError(f"{path}: {field} must be a{' possibly empty' if allow_empty else ' non-empty'} string array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ModelMapError(f"{path}: {field} must contain only non-empty strings")
    return tuple(item.strip() for item in value)


def _route_from_data(
    data: Mapping[str, Any],
    *,
    use_case: str,
    risk: str,
    path: Path,
) -> ModelRoute:
    route_name = f"{use_case}.{risk}"
    unknown = set(data) - ROUTE_FIELDS
    missing = ROUTE_FIELDS - set(data)
    if unknown:
        raise ModelMapError(f"{path}: route {route_name} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ModelMapError(f"{path}: route {route_name} is missing fields: {', '.join(sorted(missing))}")

    agents = _string_list(data.get("agents"), field=f"{route_name}.agents", path=path)
    if len(agents) != len(set(agents)):
        raise ModelMapError(f"{path}: route {route_name} repeats an agent")
    for agent in agents:
        if agent not in SUPPORTED_AGENTS or not agent.startswith(AGENT_PREFIX[use_case]):
            article = "an" if use_case == "implementation" else "a"
            raise ModelMapError(f"{path}: route {route_name} requires {article} {use_case} agent, got {agent!r}")

    max_steps = data.get("max_steps")
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps != len(agents):
        raise ModelMapError(
            f"{path}: route {route_name} max_steps must equal its explicit agent sequence length {len(agents)}"
        )
    if not 1 <= max_steps <= 4:
        raise ModelMapError(f"{path}: route {route_name} max_steps must be between 1 and 4")

    escalation_mode = _required_string(data, "escalation_mode", path)
    required_mode = ESCALATION_MODE[use_case]
    if escalation_mode != required_mode:
        raise ModelMapError(f"{path}: route {route_name} escalation_mode must be {required_mode!r}")

    triggers = _string_list(
        data.get("escalation_triggers"),
        field=f"{route_name}.escalation_triggers",
        path=path,
        allow_empty=max_steps == 1,
    )
    unsupported = set(triggers) - ALLOWED_TRIGGERS[use_case]
    if unsupported:
        raise ModelMapError(
            f"{path}: route {route_name} has unsupported escalation triggers: {', '.join(sorted(unsupported))}"
        )
    if max_steps > 1 and not triggers:
        raise ModelMapError(f"{path}: route {route_name} needs an evidence trigger for multiple steps")

    stop_on_success = data.get("stop_on_success")
    if stop_on_success is not True:
        raise ModelMapError(f"{path}: route {route_name} stop_on_success must be true")
    transport_failure = _required_string(data, "transport_failure", path)
    if transport_failure != "block":
        raise ModelMapError(f"{path}: route {route_name} transport_failure must remain 'block'")
    fallback = _required_string(data, "fallback", path)
    required_fallback = "targeted-root" if use_case == "discovery" else "block"
    if fallback != required_fallback:
        raise ModelMapError(f"{path}: route {route_name} fallback must be {required_fallback!r}")

    critical_confirmed = data.get("critical_confirmed")
    if not isinstance(critical_confirmed, bool):
        raise ModelMapError(f"{path}: route {route_name} critical_confirmed must be a boolean")
    if risk == "critical" and not critical_confirmed:
        raise ModelMapError(f"{path}: route {route_name} requires critical_confirmed = true")
    if risk != "critical" and critical_confirmed:
        raise ModelMapError(f"{path}: route {route_name} cannot set critical_confirmed = true")

    return ModelRoute(
        agents=agents,
        max_steps=max_steps,
        escalation_mode=escalation_mode,
        escalation_triggers=triggers,
        stop_on_success=stop_on_success,
        transport_failure=transport_failure,
        fallback=fallback,
        critical_confirmed=critical_confirmed,
    )


def load_model_map_file(path: Path, *, source_scope: str | None = None) -> ModelMap:
    resolved = path.resolve()
    try:
        raw_bytes = resolved.read_bytes()
        data = tomllib.loads(raw_bytes.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ModelMapError(f"model map is missing: {resolved}") from exc
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ModelMapError(f"cannot read model map {resolved}: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelMapError(f"{resolved}: model map must be a TOML table")

    unknown = set(data) - TOP_LEVEL_FIELDS
    missing = {"schema_version", "name", "writer_policy", "failure_policy"} - set(data)
    if unknown:
        raise ModelMapError(f"{resolved}: unknown top-level fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ModelMapError(f"{resolved}: missing top-level fields: {', '.join(sorted(missing))}")
    if data.get("schema_version") != 1:
        raise ModelMapError(f"{resolved}: schema_version must be 1")
    name = _required_string(data, "name", resolved)
    writer_policy = _required_string(data, "writer_policy", resolved)
    failure_policy = _required_string(data, "failure_policy", resolved)
    if writer_policy != "single":
        raise ModelMapError(f"{resolved}: writer_policy must remain 'single'")
    if failure_policy != "block":
        raise ModelMapError(f"{resolved}: failure_policy must remain 'block'")

    routes: dict[tuple[str, str], ModelRoute] = {}
    for use_case, risk in sorted(REQUIRED_ROUTES):
        use_case_data = data.get(use_case)
        if not isinstance(use_case_data, dict) or not isinstance(use_case_data.get(risk), dict):
            raise ModelMapError(f"{resolved}: missing route [{use_case}.{risk}]")
        routes[(use_case, risk)] = _route_from_data(
            use_case_data[risk],
            use_case=use_case,
            risk=risk,
            path=resolved,
        )
    for use_case in USE_CASES:
        expected_risks = {risk for candidate, risk in REQUIRED_ROUTES if candidate == use_case}
        actual = data[use_case]
        extra = set(actual) - expected_risks
        if extra:
            raise ModelMapError(f"{resolved}: unknown routes in [{use_case}]: {', '.join(sorted(extra))}")

    if source_scope is None:
        source_scope = "packaged" if resolved == PACKAGED_MODEL_MAP.resolve() else "explicit"
    return ModelMap(
        name=name,
        writer_policy=writer_policy,
        failure_policy=failure_policy,
        routes=routes,
        source=resolved,
        source_scope=source_scope,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def load_model_map(*, repo: Path, codex_home: Path) -> ModelMap:
    candidates = [
        (repo.resolve() / ".codex" / "openbuild" / "model-map.toml", "project"),
        (codex_home.resolve() / "openbuild" / "model-map.toml", "user"),
        (PACKAGED_MODEL_MAP, "packaged"),
    ]
    for path, scope in candidates:
        if path.is_file():
            return load_model_map_file(path, source_scope=scope)
    raise ModelMapError("packaged OpenBuild model map is missing; reinstall OpenBuild")


def resolve_model_route(
    *,
    repo: Path,
    codex_home: Path,
    use_case: str,
    risk: str,
) -> dict[str, Any]:
    key = (use_case, risk)
    if key not in REQUIRED_ROUTES:
        raise ModelMapError(f"unsupported model-map route {use_case}.{risk}")
    configured = load_model_map(repo=repo, codex_home=codex_home)
    route = configured.routes[key]
    agents: list[dict[str, str]] = []
    for agent_name in route.agents:
        try:
            profile = load_agent_profile(agent_name, repo=repo, codex_home=codex_home)
        except RunnerError as exc:
            raise ModelMapError(str(exc)) from exc
        agents.append(
            {
                "name": profile.name,
                "model": profile.model,
                "reasoning_effort": profile.reasoning_effort,
                "sandbox": profile.sandbox,
                "profile_source": str(profile.source),
            }
        )
    return {
        "schema_version": 1,
        "map_name": configured.name,
        "map_source": str(configured.source),
        "map_scope": configured.source_scope,
        "map_sha256": configured.sha256,
        "use_case": use_case,
        "risk": risk,
        "max_steps": route.max_steps,
        "escalation_mode": route.escalation_mode,
        "escalation_triggers": list(route.escalation_triggers),
        "stop_on_success": route.stop_on_success,
        "transport_failure": route.transport_failure,
        "fallback": route.fallback,
        "critical_confirmed": route.critical_confirmed,
        "agents": agents,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="resolve one effective route and its exact profiles")
    resolve.add_argument("--repo", type=Path, default=Path.cwd())
    resolve.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    )
    resolve.add_argument("--use-case", choices=USE_CASES, required=True)
    resolve.add_argument("--risk", choices=("default", *RISKS), required=True)

    validate = subparsers.add_parser("validate", help="validate one complete model map")
    validate.add_argument("--path", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            result = resolve_model_route(
                repo=args.repo,
                codex_home=args.codex_home,
                use_case=args.use_case,
                risk=args.risk,
            )
        else:
            configured = load_model_map_file(args.path)
            result = {
                "valid": True,
                "name": configured.name,
                "source": str(configured.source),
                "sha256": configured.sha256,
                "routes": len(configured.routes),
            }
    except ModelMapError as exc:
        parser.exit(2, f"model-map error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
