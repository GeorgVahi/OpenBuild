"""Contract tests for OpenBuild's user-configurable model map."""

from __future__ import annotations

import importlib.util
import tempfile
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
        self.assertEqual(
            configured.routes[("implementation", "high")].agents,
            ("openbuild_implementation_balanced", "openbuild_implementation_strong"),
        )
        self.assertEqual(
            configured.routes[("review", "high")].agents,
            ("openbuild_review_balanced", "openbuild_review_strong"),
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
                "[implementation.high]\nagents = [\"openbuild_implementation_balanced\", \"openbuild_implementation_strong\"]\nmax_steps = 2",
                "[implementation.high]\nagents = [\"openbuild_implementation_balanced\", \"openbuild_implementation_strong\"]\nmax_steps = 1",
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "max_steps"):
                model_map.load_model_map_file(path)

    def test_route_cannot_cross_role_or_sandbox_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self.copy_map(Path(temp) / "model-map.toml", name="Wrong family")
            text = path.read_text(encoding="utf-8").replace(
                'agents = ["openbuild_implementation_fast", "openbuild_implementation_balanced"]',
                'agents = ["openbuild_review_fast", "openbuild_implementation_balanced"]',
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
                '[implementation.medium]\nagents = ["openbuild_implementation_balanced", "openbuild_implementation_strong"]\nmax_steps = 2\nescalation_mode = "semantic-before-edit"',
                '[implementation.medium]\nagents = ["openbuild_implementation_balanced", "openbuild_implementation_strong"]\nmax_steps = 2\nescalation_mode = "after-evidence"',
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(model_map.ModelMapError, "semantic-before-edit"):
                model_map.load_model_map_file(path)

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
            self.assertEqual(result["max_steps"], 2)
            self.assertEqual(
                [agent["name"] for agent in result["agents"]],
                ["openbuild_implementation_balanced", "openbuild_implementation_strong"],
            )
            self.assertEqual(
                [(agent["model"], agent["reasoning_effort"], agent["sandbox"]) for agent in result["agents"]],
                [
                    ("gpt-5.6-terra", "medium", "workspace-write"),
                    ("gpt-5.6-sol", "high", "workspace-write"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
