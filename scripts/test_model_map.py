"""Contract tests for OpenBuild's user-configurable model map."""

from __future__ import annotations

import importlib.util
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "openbuild" / "skills" / "build" / "scripts" / "model_map.py"
SPEC = importlib.util.spec_from_file_location("openbuild_model_map", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load model-map resolver from {SCRIPT}")
model_map = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_map)


class ModelMapContractTests(unittest.TestCase):
    def copy_map(self, target: Path, *, name: str) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        text = model_map.PACKAGED_MODEL_MAP.read_text(encoding="utf-8")
        text = text.replace('name = "OpenBuild defaults"', f'name = "{name}"', 1)
        target.write_text(text, encoding="utf-8", newline="\n")
        return target

    def write_profile_override(
        self,
        target: Path,
        *,
        name: str,
        model: str,
        effort: str,
        rung: str,
        sandbox: str = "read-only",
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(
                [
                    f'name = "{name}"',
                    'description = "Explicit test override."',
                    f'model = "{model}"',
                    f'model_reasoning_effort = "{effort}"',
                    f'sandbox_mode = "{sandbox}"',
                    f'routing_rung = "{rung}"',
                    "routing_tuple_confirmed = true",
                    'developer_instructions = "Perform only the bounded role."',
                ]
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def test_packaged_map_covers_every_use_case_and_risk(self) -> None:
        configured = model_map.load_model_map_file(model_map.PACKAGED_MODEL_MAP)

        self.assertEqual(
            set(configured.routes),
            {
                ("discovery", "default"),
                *( (use_case, risk)
                   for use_case in ("critic", "implementation", "review")
                   for risk in ("low", "medium", "high", "critical") ),
            },
        )
        self.assertEqual(
            configured.routes[("discovery", "default")].agents,
            ("openbuild_search_separate",),
        )
        discovery = configured.routes[("discovery", "default")]
        self.assertEqual(discovery.transport_failure, "availability-fallback")
        self.assertEqual(discovery.availability_fallback_agent, "openbuild_search_balanced")
        self.assertEqual(
            discovery.availability_fallback_triggers,
            ("model-unavailable", "quota-exhausted"),
        )
        self.assertEqual(
            configured.routes[("implementation", "high")].agents,
            (
                "openbuild_implementation_balanced",
                "openbuild_implementation_strong",
                "openbuild_implementation_sol_high",
            ),
        )
        self.assertEqual(
            configured.routes[("review", "high")].agents,
            (
                "openbuild_review_balanced",
                "openbuild_review_strong",
                "openbuild_review_sol_high",
            ),
        )
        self.assertEqual(
            configured.routes[("implementation", "low")].agents,
            (
                "openbuild_implementation_fast",
                "openbuild_implementation_luna_xhigh",
                "openbuild_implementation_balanced",
                "openbuild_implementation_strong",
                "openbuild_implementation_sol_high",
            ),
        )
        self.assertEqual(
            configured.routes[("critic", "low")].agents,
            (
                "openbuild_review_fast",
                "openbuild_review_luna_xhigh",
                "openbuild_review_balanced",
                "openbuild_review_strong",
                "openbuild_review_sol_high",
            ),
        )
        for use_case in ("critic", "implementation", "review"):
            with self.subTest(use_case=use_case):
                route = configured.routes[(use_case, "critical")]
                self.assertTrue(route.critical_confirmed)
                self.assertEqual(route.max_steps, len(route.agents))

    def test_project_map_wins_over_user_then_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            codex_home = root / "codex-home"
            user = self.copy_map(
                codex_home / "openbuild" / "model-map.toml",
                name="User map",
            )

            configured = model_map.load_model_map(repo=repo, codex_home=codex_home)
            self.assertEqual(configured.name, "User map")
            self.assertEqual(configured.source, user.resolve())
            self.assertEqual(configured.source_scope, "user")

            project = self.copy_map(
                repo / ".codex" / "openbuild" / "model-map.toml",
                name="Project map",
            )
            configured = model_map.load_model_map(repo=repo, codex_home=codex_home)
            self.assertEqual(configured.name, "Project map")
            self.assertEqual(configured.source, project.resolve())
            self.assertEqual(configured.source_scope, "project")

    def test_incomplete_map_fails_closed_instead_of_merging_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model-map.toml"
            path.write_text(
                'schema_version = 1\nname = "Incomplete"\nwriter_policy = "single"\n'
                'failure_policy = "block"\n',
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(model_map.ModelMapError, "missing route"):
                model_map.load_model_map_file(path)

    def test_invalid_project_map_does_not_fall_through_to_a_valid_user_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            codex_home = root / "codex-home"
            self.copy_map(
                codex_home / "openbuild" / "model-map.toml",
                name="Valid user map",
            )
            project = repo / ".codex" / "openbuild" / "model-map.toml"
            project.parent.mkdir(parents=True)
            project.write_text(
                'schema_version = 1\nname = "Broken project map"\n',
                encoding="utf-8",
                newline="\n",
            )

            with self.assertRaisesRegex(model_map.ModelMapError, "missing top-level fields"):
                model_map.load_model_map(repo=repo, codex_home=codex_home)

    def test_max_steps_must_match_the_explicit_agent_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Broken steps")
            text = path.read_text(encoding="utf-8").replace(
                "[implementation.high]\nagents = [\"openbuild_implementation_balanced\", \"openbuild_implementation_strong\", \"openbuild_implementation_sol_high\"]\nmax_steps = 3",
                "[implementation.high]\nagents = [\"openbuild_implementation_balanced\", \"openbuild_implementation_strong\", \"openbuild_implementation_sol_high\"]\nmax_steps = 1",
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "max_steps"):
                model_map.load_model_map_file(path)

    def test_route_cannot_cross_role_or_sandbox_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Wrong family")
            text = path.read_text(encoding="utf-8").replace(
                'agents = ["openbuild_implementation_fast", "openbuild_implementation_luna_xhigh", "openbuild_implementation_balanced", "openbuild_implementation_strong", "openbuild_implementation_sol_high"]',
                'agents = ["openbuild_review_fast", "openbuild_implementation_luna_xhigh", "openbuild_implementation_balanced", "openbuild_implementation_strong", "openbuild_implementation_sol_high"]',
                1,
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "implementation agent"):
                model_map.load_model_map_file(path)

    def test_unknown_escalation_trigger_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Unknown trigger")
            text = path.read_text(encoding="utf-8").replace(
                '"task-complexity-above-tier"',
                '"model-looked-weak"',
                1,
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "unsupported escalation triggers"):
                model_map.load_model_map_file(path)

    def test_transport_failure_and_writer_escalation_mode_are_non_negotiable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Unsafe fallback")
            text = path.read_text(encoding="utf-8").replace(
                'transport_failure = "block"',
                'transport_failure = "next-agent"',
                1,
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "transport_failure"):
                model_map.load_model_map_file(path)

            path = self.copy_map(Path(temp) / "writer-map.toml", name="Unsafe writer")
            text = path.read_text(encoding="utf-8").replace(
                '[implementation.medium]\nagents = ["openbuild_implementation_balanced", "openbuild_implementation_strong", "openbuild_implementation_sol_high"]\nmax_steps = 3\nescalation_mode = "semantic-before-edit"',
                '[implementation.medium]\nagents = ["openbuild_implementation_balanced", "openbuild_implementation_strong", "openbuild_implementation_sol_high"]\nmax_steps = 3\nescalation_mode = "after-evidence"',
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "semantic-before-edit"):
                model_map.load_model_map_file(path)

    def test_legacy_complete_map_keeps_blocked_targeted_root_discovery(self) -> None:
        data = tomllib.loads(model_map.PACKAGED_MODEL_MAP.read_text(encoding="utf-8"))
        discovery = data["discovery"]["default"]
        discovery["transport_failure"] = "block"
        discovery.pop("availability_fallback_agent")
        discovery.pop("availability_fallback_triggers")

        route = model_map._route_from_data(
            discovery,
            use_case="discovery",
            risk="default",
            path=model_map.PACKAGED_MODEL_MAP,
        )
        self.assertEqual(route.transport_failure, "block")
        self.assertIsNone(route.availability_fallback_agent)
        self.assertEqual(route.availability_fallback_triggers, ())
        self.assertEqual(route.fallback, "targeted-root")

    def test_availability_fallback_requires_the_exact_discovery_pair(self) -> None:
        cases = (
            ("missing triggers", lambda route: route.pop("availability_fallback_triggers"), "paired"),
            ("missing agent", lambda route: route.pop("availability_fallback_agent"), "paired"),
            ("wrong agent", lambda route: route.__setitem__("availability_fallback_agent", "openbuild_search_separate"), "canonical"),
            ("wrong source", lambda route: route.__setitem__("agents", ["openbuild_search_strong"]), "source"),
            ("unknown trigger", lambda route: route.__setitem__("availability_fallback_triggers", ["network-error"]), "unsupported availability"),
            ("block with pair", lambda route: route.__setitem__("transport_failure", "block"), "availability-fallback"),
        )
        for label, mutate, error in cases:
            with self.subTest(case=label):
                data = tomllib.loads(model_map.PACKAGED_MODEL_MAP.read_text(encoding="utf-8"))
                route = data["discovery"]["default"]
                mutate(route)
                with self.assertRaisesRegex(model_map.ModelMapError, error):
                    model_map._route_from_data(
                        route,
                        use_case="discovery",
                        risk="default",
                        path=model_map.PACKAGED_MODEL_MAP,
                    )

    def test_availability_fallback_is_discovery_only(self) -> None:
        data = tomllib.loads(model_map.PACKAGED_MODEL_MAP.read_text(encoding="utf-8"))
        route = data["implementation"]["low"]
        route["transport_failure"] = "availability-fallback"
        route["availability_fallback_agent"] = "openbuild_search_balanced"
        route["availability_fallback_triggers"] = ["model-unavailable"]
        with self.assertRaisesRegex(model_map.ModelMapError, "unknown fields"):
            model_map._route_from_data(
                route,
                use_case="implementation",
                risk="low",
                path=model_map.PACKAGED_MODEL_MAP,
            )

    def test_critical_routes_require_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Unconfirmed critical")
            text = path.read_text(encoding="utf-8").replace(
                "critical_confirmed = true",
                "critical_confirmed = false",
                1,
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "critical_confirmed"):
                model_map.load_model_map_file(path)

    def test_noncritical_override_cannot_use_a_critical_only_profile(self) -> None:
        cases = (
            (
                "implementation.low",
                '[implementation.low]\nagents = ["openbuild_implementation_fast", "openbuild_implementation_luna_xhigh", "openbuild_implementation_balanced", "openbuild_implementation_strong", "openbuild_implementation_sol_high"]\nmax_steps = 5',
                '[implementation.low]\nagents = ["openbuild_implementation_strongest"]\nmax_steps = 1',
            ),
            (
                "review.high",
                '[review.high]\nagents = ["openbuild_review_balanced", "openbuild_review_strong", "openbuild_review_sol_high"]\nmax_steps = 3',
                '[review.high]\nagents = ["openbuild_review_strongest"]\nmax_steps = 1',
            ),
        )
        for route_name, source, replacement in cases:
            with self.subTest(route=route_name), tempfile.TemporaryDirectory() as temp:
                path = self.copy_map(Path(temp) / "model-map.toml", name="Unsafe override")
                text = path.read_text(encoding="utf-8").replace(source, replacement)
                path.write_text(text, encoding="utf-8", newline="\n")

                with self.assertRaisesRegex(model_map.ModelMapError, "critical-only"):
                    model_map.load_model_map_file(path, source_scope="project")

    def test_noncritical_override_cannot_start_on_sol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Sol-first override")
            text = path.read_text(encoding="utf-8").replace(
                '[review.high]\nagents = ["openbuild_review_balanced", "openbuild_review_strong", "openbuild_review_sol_high"]\nmax_steps = 3',
                '[review.high]\nagents = ["openbuild_review_sol_high"]\nmax_steps = 1',
            )
            path.write_text(text, encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(model_map.ModelMapError, "cannot start on Sol"):
                model_map.load_model_map_file(path, source_scope="user")

    def test_critical_override_requires_the_direct_strongest_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Weak critical override")
            text = path.read_text(encoding="utf-8").replace(
                '[implementation.critical]\nagents = ["openbuild_implementation_strongest"]\nmax_steps = 1',
                '[implementation.critical]\nagents = ["openbuild_implementation_strong"]\nmax_steps = 1',
            )
            path.write_text(text, encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(model_map.ModelMapError, "direct strongest"):
                model_map.load_model_map_file(path, source_scope="project")

    def test_override_route_cannot_skip_a_reasoning_rung(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Skipped rung override")
            text = path.read_text(encoding="utf-8").replace(
                '[implementation.low]\nagents = ["openbuild_implementation_fast", "openbuild_implementation_luna_xhigh", "openbuild_implementation_balanced", "openbuild_implementation_strong", "openbuild_implementation_sol_high"]\nmax_steps = 5',
                '[implementation.low]\nagents = ["openbuild_implementation_fast", "openbuild_implementation_balanced"]\nmax_steps = 2',
            )
            path.write_text(text, encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(model_map.ModelMapError, "contiguous reasoning-first"):
                model_map.load_model_map_file(path, source_scope="user")

    def test_effective_profile_override_cannot_bypass_its_routing_rung(self) -> None:
        cases = (
            (
                "project-sol-first",
                "review",
                "low",
                "openbuild_review_fast",
                "gpt-5.6-sol",
                "high",
                "luna-medium",
                "known model/effort tuple",
            ),
            (
                "user-weakened-critical",
                "review",
                "critical",
                "openbuild_review_strongest",
                "gpt-5.6-luna",
                "medium",
                "sol-xhigh",
                "known model/effort tuple",
            ),
            (
                "project-skipped-xhigh",
                "review",
                "low",
                "openbuild_review_luna_xhigh",
                "gpt-5.6-luna",
                "medium",
                "luna-xhigh",
                "known model/effort tuple",
            ),
        )
        for label, use_case, risk, agent, model, effort, rung, error in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo = root / "repo"
                repo.mkdir()
                codex_home = root / "codex-home"
                target_root = repo if label.startswith("project") else codex_home
                self.write_profile_override(
                    target_root / ".codex" / "agents" / "override.toml"
                    if target_root == repo
                    else target_root / "agents" / "override.toml",
                    name=agent,
                    model=model,
                    effort=effort,
                    rung=rung,
                )

                with self.assertRaisesRegex(model_map.ModelMapError, error):
                    model_map.resolve_model_route(
                        repo=repo,
                        codex_home=codex_home,
                        use_case=use_case,
                        risk=risk,
                    )

    def test_resolver_returns_exact_profile_evidence_and_map_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            codex_home = root / "codex-home"

            result = model_map.resolve_model_route(
                repo=repo,
                codex_home=codex_home,
                use_case="implementation",
                risk="high",
            )

            self.assertEqual(result["map_scope"], "packaged")
            self.assertEqual(len(result["map_sha256"]), 64)
            self.assertEqual(result["max_steps"], 3)
            self.assertEqual(
                [agent["name"] for agent in result["agents"]],
                [
                    "openbuild_implementation_balanced",
                    "openbuild_implementation_strong",
                    "openbuild_implementation_sol_high",
                ],
            )
            self.assertEqual(
                [(agent["model"], agent["reasoning_effort"], agent["sandbox"]) for agent in result["agents"]],
                [
                    ("gpt-5.6-terra", "medium", "workspace-write"),
                    ("gpt-5.6-terra", "xhigh", "workspace-write"),
                    ("gpt-5.6-sol", "high", "workspace-write"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
