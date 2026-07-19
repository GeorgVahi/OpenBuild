from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "plugins" / "openbuild" / "skills" / "build" / "scripts" / "discovery_contract.py"
)
SPEC = importlib.util.spec_from_file_location("openbuild_discovery_contract", MODULE_PATH)
assert SPEC and SPEC.loader
discovery_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery_contract)


class DiscoveryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.external = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "src").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "plugins" / "openbuild" / "skills" / "build").mkdir(parents=True)
        (self.repo / "artifacts").mkdir()
        (self.repo / ".pytest_cache").mkdir()
        (self.repo / "target").mkdir()
        (self.repo / "src" / "owner.py").write_text("def owner():\n    return 1\n", encoding="utf-8")
        (self.repo / "tests" / "test_owner.py").write_text(
            "def test_owner():\n    assert True\n", encoding="utf-8"
        )
        (self.repo / "plugins" / "openbuild" / "skills" / "build" / "owner.py").write_text(
            "def build_owner():\n    return 1\n", encoding="utf-8"
        )
        for relative in ("artifacts/report.py", ".pytest_cache/report.py", "target/report.py"):
            (self.repo / relative).write_text("generated = True\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "add",
                "src/owner.py",
                "tests/test_owner.py",
                "plugins/openbuild/skills/build/owner.py",
                "artifacts/report.py",
                ".pytest_cache/report.py",
                "target/report.py",
            ],
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.external.cleanup()

    def valid_result(self, fingerprint: dict[str, object]) -> dict[str, object]:
        return {
            "schema": "openbuild.discovery.v1",
            "worktree_fingerprint": fingerprint,
            "summary": "Owner and focused validation map.",
            "owners": [
                {
                    "path": "src/owner.py",
                    "line_start": 1,
                    "line_end": 2,
                    "symbol": "owner",
                    "reason": "owns the behavior",
                }
            ],
            "couplings": [],
            "tests": [
                {
                    "path": "tests/test_owner.py",
                    "line_start": 1,
                    "line_end": 2,
                    "symbol": "test_owner",
                    "reason": "focused validation",
                }
            ],
            "flows": [],
            "constraints": ["read-only"],
            "uncertainties": [],
        }

    def add_local_submodule(self) -> Path:
        source = Path(self.external.name) / "submodule-source"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "tests@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Tests"],
            check=True,
        )
        (source / "tracked.txt").write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "commit", "-q", "-m", "seed"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "-q",
                str(source),
                "deps/submodule",
            ],
            check=True,
        )
        return self.repo / "deps" / "submodule"

    def test_fingerprint_is_content_sensitive_and_includes_untracked(self) -> None:
        first = discovery_contract.compute_worktree_fingerprint(self.repo)
        self.assertIn("src/owner.py", first.paths)
        (self.repo / "notes.txt").write_text("untracked\n", encoding="utf-8")
        second = discovery_contract.compute_worktree_fingerprint(self.repo)
        self.assertIn("notes.txt", second.paths)
        self.assertNotEqual(first.public["digest"], second.public["digest"])

    def test_fingerprint_fails_closed_on_file_and_byte_limits(self) -> None:
        with self.assertRaisesRegex(discovery_contract.DiscoveryContractError, "file limit"):
            discovery_contract.compute_worktree_fingerprint(self.repo, max_files=1)
        with self.assertRaisesRegex(discovery_contract.DiscoveryContractError, "byte limit"):
            discovery_contract.compute_worktree_fingerprint(self.repo, max_bytes=1)

    def test_valid_result_requires_exact_owner_fingerprint(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        with tempfile.TemporaryDirectory() as output:
            result = Path(output) / "result.json"
            result.write_text(
                json.dumps(self.valid_result(snapshot.public), ensure_ascii=False), encoding="utf-8"
            )
            post = discovery_contract.validate_discovery_result(
                result,
                repo=self.repo,
                expected_public=snapshot.public,
            )
            self.assertEqual(post.public, snapshot.public)

    def test_result_rejects_regular_file_replacement_between_check_and_open(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        with tempfile.TemporaryDirectory() as output:
            result = Path(output) / "result.json"
            replacement = Path(output) / "replacement.json"
            original = Path(output) / "original.json"
            payload = json.dumps(
                self.valid_result(snapshot.public),
                ensure_ascii=False,
            )
            result.write_text(payload, encoding="utf-8")
            replacement.write_text(payload, encoding="utf-8")
            real_open = discovery_contract.os.open
            swapped = False

            def swap_before_open(path: object, flags: int, *args: object) -> int:
                nonlocal swapped
                if not swapped and Path(path) == result:
                    swapped = True
                    result.replace(original)
                    replacement.replace(result)
                return real_open(path, flags, *args)

            with mock.patch.object(
                discovery_contract.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    discovery_contract.DiscoveryContractError,
                    "missing or unreadable",
                ):
                    discovery_contract.validate_discovery_result(
                        result,
                        repo=self.repo,
                        expected_public=snapshot.public,
                    )

            self.assertTrue(swapped)

    def test_legitimate_source_directory_named_build_is_allowed(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        value = self.valid_result(snapshot.public)
        value["owners"][0]["path"] = "plugins/openbuild/skills/build/owner.py"  # type: ignore[index]
        discovery_contract.validate_discovery_object(value, repo=self.repo, expected=snapshot)

    def test_canonical_artifact_cache_and_output_segments_are_rejected(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        for relative in ("artifacts/report.py", ".pytest_cache/report.py", "target/report.py"):
            with self.subTest(relative=relative):
                value = self.valid_result(snapshot.public)
                value["owners"][0]["path"] = relative  # type: ignore[index]
                with self.assertRaisesRegex(
                    discovery_contract.DiscoveryContractError,
                    "unsafe or outside inventory",
                ):
                    discovery_contract.validate_discovery_object(
                        value,
                        repo=self.repo,
                        expected=snapshot,
                    )

    def test_literal_backslash_paths_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            discovery_contract.DiscoveryContractError,
            "literal backslash",
        ):
            discovery_contract._normalize_git_path(b"tracked\\name.py")

        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        value = self.valid_result(snapshot.public)
        value["owners"][0]["path"] = "src\\owner.py"  # type: ignore[index]
        with self.assertRaisesRegex(
            discovery_contract.DiscoveryContractError,
            "literal backslash",
        ):
            discovery_contract.validate_discovery_object(
                value,
                repo=self.repo,
                expected=snapshot,
            )

        if os.name != "nt":
            tracked = self.repo / "tracked\\name.py"
            tracked.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(self.repo), "add", "--", "tracked\\name.py"],
                check=True,
            )
            with self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "literal backslash",
            ):
                discovery_contract.compute_worktree_fingerprint(self.repo)

    def test_result_rejects_unknown_fields_unsafe_paths_and_loose_ranges(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        cases: list[tuple[str, object, str]] = []
        unknown = self.valid_result(snapshot.public)
        unknown["extra"] = True
        cases.append(("unknown", unknown, "unknown or missing"))
        unsafe = self.valid_result(snapshot.public)
        unsafe["owners"][0]["path"] = "../owner.py"  # type: ignore[index]
        cases.append(("unsafe", unsafe, "unsafe or outside"))
        loose = self.valid_result(snapshot.public)
        loose["owners"][0]["line_end"] = 201  # type: ignore[index]
        cases.append(("loose", loose, "invalid line range"))
        for label, value, error in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(discovery_contract.DiscoveryContractError, error):
                    discovery_contract.validate_discovery_object(
                        value,
                        repo=self.repo,
                        expected=snapshot,
                    )

    def test_result_rejects_symlink_to_file_outside_repository(self) -> None:
        external = Path(self.external.name) / "outside.py"
        external.write_text("secret = True\n", encoding="utf-8")
        link = self.repo / "src" / "outside_link.py"
        try:
            link.symlink_to(external)
        except OSError:
            snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
            value = self.valid_result(snapshot.public)
            with mock.patch.object(
                discovery_contract,
                "_is_link_or_reparse",
                return_value=True,
            ), self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "symlink or junction",
            ):
                discovery_contract.validate_discovery_object(
                    value,
                    repo=self.repo,
                    expected=snapshot,
                )
            return
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        value = self.valid_result(snapshot.public)
        value["owners"][0]["path"] = "src/outside_link.py"  # type: ignore[index]
        with self.assertRaisesRegex(
            discovery_contract.DiscoveryContractError,
            "symlink or junction",
        ):
            discovery_contract.validate_discovery_object(
                value,
                repo=self.repo,
                expected=snapshot,
            )

    def test_windows_reparse_attribute_is_rejected_without_path_is_junction(self) -> None:
        info = mock.Mock(
            st_mode=stat.S_IFREG,
            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        )
        self.assertTrue(discovery_contract._is_link_or_reparse(info))

    def test_regular_file_swap_is_rejected_before_any_content_read(self) -> None:
        owner = self.repo / "src" / "owner.py"
        info = owner.lstat()
        with mock.patch.object(
            discovery_contract,
            "_fingerprint_regular_path",
            side_effect=[
                (owner, info),
                discovery_contract.DiscoveryContractError(
                    "fingerprint-unavailable: regular-file path contains a link or reparse point"
                ),
            ],
        ), mock.patch.object(discovery_contract.os, "read") as read:
            with self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "link or reparse point",
            ):
                discovery_contract._hash_regular_file(
                    owner,
                    repo=self.repo,
                    relative="src/owner.py",
                    deadline=time.monotonic() + 5,
                    byte_budget=1024,
                )
            read.assert_not_called()

    def test_symlink_swap_is_rejected_after_readlink(self) -> None:
        path = self.repo / "src" / "owner.py"
        before = path.lstat()
        after = mock.Mock(
            st_dev=before.st_dev,
            st_ino=before.st_ino + 1,
            st_size=before.st_size,
            st_mtime_ns=before.st_mtime_ns,
        )
        with mock.patch.object(
            discovery_contract,
            "_fingerprint_symlink_path",
            side_effect=[(path, before), (path, after)],
        ), mock.patch.object(discovery_contract.os, "readlink", return_value="target.py"):
            with self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "symlink changed",
            ):
                discovery_contract._hash_symlink(
                    path,
                    repo=self.repo,
                    relative="src/owner.py",
                )

    def test_gitlink_ancestor_reparse_is_rejected_before_submodule_read(self) -> None:
        path = self.repo / "src"
        with mock.patch.object(
            discovery_contract,
            "_fingerprint_gitlink_path",
            side_effect=discovery_contract.DiscoveryContractError(
                "fingerprint-unavailable: gitlink path contains a link or reparse point"
            ),
        ), mock.patch.object(discovery_contract, "_submodule_marker") as marker:
            with self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "link or reparse point",
            ):
                discovery_contract._hash_gitlink(
                    path,
                    repo=self.repo,
                    relative="src",
                    oid="a" * 40,
                    deadline=time.monotonic() + 5,
                    max_files=100,
                    byte_budget=1024 * 1024,
                    depth=1,
                )
            marker.assert_not_called()

    def test_submodule_tracked_and_untracked_dirty_state_changes_fingerprint(self) -> None:
        submodule = self.add_local_submodule()
        clean = discovery_contract.compute_worktree_fingerprint(self.repo)
        (submodule / "tracked.txt").write_text("modified\n", encoding="utf-8")
        tracked_dirty = discovery_contract.compute_worktree_fingerprint(self.repo)
        self.assertNotEqual(clean.public["digest"], tracked_dirty.public["digest"])

        subprocess.run(
            ["git", "-C", str(submodule), "checkout", "--", "tracked.txt"],
            check=True,
        )
        (submodule / "untracked.txt").write_text("new\n", encoding="utf-8")
        untracked_dirty = discovery_contract.compute_worktree_fingerprint(self.repo)
        self.assertNotEqual(clean.public["digest"], untracked_dirty.public["digest"])

    def test_submodule_marker_drift_during_capture_is_rejected(self) -> None:
        submodule = self.add_local_submodule()
        with mock.patch.object(
            discovery_contract,
            "_submodule_marker",
            side_effect=[b"clean", b"dirty"],
        ):
            with self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "submodule changed during snapshot",
            ):
                discovery_contract._hash_gitlink(
                    submodule,
                    repo=self.repo,
                    relative="deps/submodule",
                    oid="a" * 40,
                    deadline=time.monotonic() + 5,
                    max_files=100,
                    byte_budget=1024 * 1024,
                    depth=1,
                )

    def test_gitlink_becoming_dirty_during_snapshot_is_rejected(self) -> None:
        path = self.repo / "src"
        info = path.lstat()
        marker = b" " + (b"a" * 40) + b" src"
        with mock.patch.object(
            discovery_contract,
            "_fingerprint_gitlink_path",
            return_value=(path, info),
        ), mock.patch.object(
            discovery_contract,
            "_submodule_marker",
            return_value=marker,
        ), mock.patch.object(
            discovery_contract,
            "_checked_out_gitlink_state",
            side_effect=[
                (b"first", 1, 6),
                (b"second", 1, 6),
            ],
        ):
            with self.assertRaisesRegex(
                discovery_contract.DiscoveryContractError,
                "submodule changed during snapshot",
            ):
                discovery_contract._hash_gitlink(
                    path,
                    repo=self.repo,
                    relative="src",
                    oid="a" * 40,
                    deadline=time.monotonic() + 5,
                    max_files=100,
                    byte_budget=1024 * 1024,
                    depth=1,
                )

    def test_result_rejects_missing_owner_or_test_evidence(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        for field in ("owners", "tests"):
            with self.subTest(field=field):
                value = self.valid_result(snapshot.public)
                value[field] = []
                with self.assertRaisesRegex(discovery_contract.DiscoveryContractError, "item count"):
                    discovery_contract.validate_discovery_object(
                        value,
                        repo=self.repo,
                        expected=snapshot,
                    )

    def test_result_rejects_worktree_drift(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        with tempfile.TemporaryDirectory() as output:
            result = Path(output) / "result.json"
            result.write_text(json.dumps(self.valid_result(snapshot.public)), encoding="utf-8")
            (self.repo / "src" / "owner.py").write_text(
                "def changed():\n    return 2\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(discovery_contract.DiscoveryContractError, "drifted"):
                discovery_contract.validate_discovery_result(
                    result,
                    repo=self.repo,
                    expected_public=snapshot.public,
                )

    def test_result_rejects_invalid_fingerprint_field_types_and_constants(self) -> None:
        snapshot = discovery_contract.compute_worktree_fingerprint(self.repo)
        mutations: tuple[tuple[str, object], ...] = (
            ("algorithm", "SHA256"),
            ("digest", "A" * 64),
            ("digest", "a" * 63),
            ("files", True),
            ("files", -1),
            ("bytes", False),
            ("bytes", -1),
            ("inventory", "other"),
        )
        for field, replacement in mutations:
            with self.subTest(field=field, replacement=replacement):
                public = {**snapshot.public, field: replacement}
                invalid_expected = discovery_contract.FingerprintSnapshot(
                    public,
                    snapshot.paths,
                    snapshot.line_counts,
                )
                value = self.valid_result(public)
                with self.assertRaisesRegex(
                    discovery_contract.DiscoveryContractError,
                    "fingerprint",
                ):
                    discovery_contract.validate_discovery_object(
                        value,
                        repo=self.repo,
                        expected=invalid_expected,
                    )


if __name__ == "__main__":
    unittest.main()
