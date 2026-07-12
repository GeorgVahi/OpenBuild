"""Contract tests for the OpenBuild package validator."""

from __future__ import annotations

import unittest

from validate_package import VERSION_SYNC_PATHS, commit_requires_version_bump


class PerCommitVersionGateTests(unittest.TestCase):
    def test_every_nonempty_commit_requires_a_version_bump(self) -> None:
        examples = [
            {"plugins/openbuild/skills/build/SKILL.md"},
            {"README.md"},
            {"CONTRIBUTING.md"},
            {"scripts/validate_package.py"},
            {"LICENSE"},
        ]

        for changed_paths in examples:
            with self.subTest(changed_paths=changed_paths):
                self.assertTrue(commit_requires_version_bump(changed_paths))

    def test_no_pending_commit_does_not_require_a_version_bump(self) -> None:
        self.assertFalse(commit_requires_version_bump(set()))

    def test_even_an_empty_created_commit_requires_a_version_bump(self) -> None:
        self.assertTrue(commit_requires_version_bump(set(), commit_exists=True))

    def test_every_versioned_commit_synchronizes_public_version_metadata(self) -> None:
        self.assertEqual(
            VERSION_SYNC_PATHS,
            {
                "plugins/openbuild/.codex-plugin/plugin.json",
                "CHANGELOG.md",
                "README.md",
                "README.ru.md",
            },
        )


if __name__ == "__main__":
    unittest.main()
