#!/usr/bin/env python3
"""Validate the public OpenBuild package without third-party dependencies."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "openbuild"
SKILL = PLUGIN / "skills" / "build"

REQUIRED = [
    ROOT / ".agents" / "plugins" / "marketplace.json",
    ROOT / ".gitattributes",
    ROOT / ".gitignore",
    ROOT / "README.md",
    ROOT / "README.ru.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "LICENSE",
    ROOT / "CHANGELOG.md",
    PLUGIN / ".codex-plugin" / "plugin.json",
    SKILL / "SKILL.md",
    SKILL / "agents" / "openai.yaml",
    SKILL / "references" / "spec-template.md",
    SKILL / "references" / "code-discovery.md",
    SKILL / "references" / "minimality-protocol.md",
    SKILL / "references" / "model-routing.md",
    SKILL / "references" / "review-protocol.md",
    SKILL / "references" / "tdd-workflow.md",
    SKILL / "references" / "versioning.md",
]

TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".toml", ".py"}
SEMVER_IDENTIFIER = r"(?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER_PRERELEASE = rf"{SEMVER_IDENTIFIER}(?:\.{SEMVER_IDENTIFIER})*"
SEMVER_BUILD = r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*"
SEMVER = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-{SEMVER_PRERELEASE})?(?:\+{SEMVER_BUILD})?$"
)
SEMVER_PARTS = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    rf"(?:-(?P<prerelease>{SEMVER_PRERELEASE}))?(?:\+{SEMVER_BUILD})?$"
)
MANIFEST_RELATIVE = "plugins/openbuild/.codex-plugin/plugin.json"
VERSION_SYNC_PATHS = {MANIFEST_RELATIVE, "CHANGELOG.md", "README.md", "README.ru.md"}
VERSIONED_CONTRACT_PATHS = {".agents/plugins/marketplace.json", "README.md", "README.ru.md"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def read_text(path: Path, errors: list[str]) -> str:
    data = path.read_bytes()
    relative = path.relative_to(ROOT)
    if data.startswith(b"\xef\xbb\xbf"):
        fail(errors, f"{relative}: UTF-8 BOM is not allowed")
    if b"\r" in data:
        fail(errors, f"{relative}: CR/CRLF detected; repository text must use LF")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(errors, f"{relative}: not valid UTF-8 ({exc})")
        return ""


def validate_json(path: Path, errors: list[str]) -> dict:
    text = read_text(path, errors)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(errors, f"{path.relative_to(ROOT)}: invalid JSON ({exc})")
        return {}
    if not isinstance(value, dict):
        fail(errors, f"{path.relative_to(ROOT)}: root must be an object")
        return {}
    return value


def validate_local_links(path: Path, text: str, errors: list[str]) -> None:
    pattern = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)")
    for match in pattern.finditer(text):
        target = match.group(1).strip().strip("<>").split("#", 1)[0]
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            fail(errors, f"{path.relative_to(ROOT)}: missing local link target {target}")


def semver_key(value: str) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    match = SEMVER_PARTS.fullmatch(value)
    if not match:
        raise ValueError(f"invalid SemVer: {value}")
    prerelease = match.group("prerelease")
    parts: tuple[tuple[int, int | str], ...] = ()
    if prerelease is not None:
        parts = tuple((0, int(item)) if item.isdigit() else (1, item) for item in prerelease.split("."))
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if prerelease is None else 0,
        parts,
    )


def contains_exact_version(text: str, version: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z.-]){re.escape(version)}(?![0-9A-Za-z.-])", text) is not None


def validate_semver_contract(errors: list[str]) -> None:
    valid = ["0.2.0-dev.2", "0.2.0", "1.0.0-alpha.1", "1.0.0+build.01"]
    invalid = ["0.2.0-dev..2", "0.2.0-dev.01", "01.0.0", "1.0.0-", "1.0.0+build..1"]
    for value in valid:
        if not SEMVER.fullmatch(value):
            fail(errors, f"internal SemVer validator rejected valid case {value}")
    for value in invalid:
        if SEMVER.fullmatch(value):
            fail(errors, f"internal SemVer validator accepted invalid case {value}")


def git_output(*args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def normalized_paths(*outputs: str | None) -> set[str]:
    result: set[str] = set()
    for output in outputs:
        if output:
            result.update(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())
    return result


def changes_versioned_contract(paths: set[str]) -> bool:
    return any(path.startswith("plugins/openbuild/") or path in VERSIONED_CONTRACT_PATHS for path in paths)


def is_public_package_path(path: str) -> bool:
    relative = Path(path.replace("\\", "/"))
    if any(part in {".git", ".tmp", "__pycache__"} for part in relative.parts):
        return False
    if relative.as_posix() == "TZ.md":
        return False
    if relative.as_posix().startswith("plugins/openbuild/"):
        return True
    return relative.suffix.lower() in TEXT_SUFFIXES or relative.name in {"LICENSE", ".gitignore", ".gitattributes"}


def text_from_snapshot(revision: str, path: str) -> str | None:
    selector = f":{path}" if revision == "INDEX" else f"{revision}:{path}"
    return git_output("show", selector)


def version_from_git(revision: str) -> str | None:
    text = text_from_snapshot(revision, MANIFEST_RELATIVE)
    if text is None:
        return None
    try:
        value = json.loads(text).get("version")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) and SEMVER.fullmatch(value) else None


def validate_version_snapshot(
    revision: str,
    previous_revision: str,
    changed_paths: set[str],
    errors: list[str],
    context: str,
) -> None:
    missing = VERSION_SYNC_PATHS - changed_paths
    if missing:
        fail(errors, f"version commit gate ({context}): synchronized files missing from one diff: {sorted(missing)}")
        return

    current = version_from_git(revision)
    previous = version_from_git(previous_revision)
    if current is None or previous is None:
        fail(errors, f"version commit gate ({context}): could not read strict SemVer manifests")
        return
    if semver_key(current) <= semver_key(previous):
        fail(errors, f"version commit gate ({context}): version did not increase ({previous} -> {current})")

    for path in ["README.md", "README.ru.md", "CHANGELOG.md"]:
        text = text_from_snapshot(revision, path)
        if text is None or not contains_exact_version(text, current):
            fail(errors, f"version commit gate ({context}): {path} does not contain exact version {current}")


def validate_version_progression(current: str, errors: list[str], commit_gate: bool) -> None:
    if git_output("rev-parse", "--is-inside-work-tree") != "true":
        return

    tracked_working = git_output("diff", "--name-only", "HEAD", "--")
    untracked_working = git_output("ls-files", "--others", "--exclude-standard")
    working_paths = normalized_paths(tracked_working, untracked_working)

    if commit_gate:
        unstaged_paths = normalized_paths(
            git_output("diff", "--name-only", "--"),
            untracked_working,
        )
        unstaged_package_files = {path for path in unstaged_paths if is_public_package_path(path)}
        if unstaged_package_files:
            fail(
                errors,
                f"commit gate: public package files are not fully staged: {sorted(unstaged_package_files)}",
            )
            return

        staged_paths = normalized_paths(git_output("diff", "--cached", "--name-only", "HEAD", "--"))
        if staged_paths:
            if changes_versioned_contract(staged_paths):
                validate_version_snapshot("INDEX", "HEAD", staged_paths, errors, "index versus HEAD")
            return
        if changes_versioned_contract(working_paths):
            fail(errors, "version commit gate: stage the complete task diff before validation")
            return

        committed_paths = normalized_paths(
            git_output("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", "--")
        )
        if changes_versioned_contract(committed_paths) and git_output("rev-parse", "HEAD^") is not None:
            validate_version_snapshot("HEAD", "HEAD^", committed_paths, errors, "HEAD versus HEAD^")
        return

    previous_revision: str | None = None
    context = ""
    if changes_versioned_contract(working_paths):
        previous_revision = "HEAD"
        context = "working tree versus HEAD"
    else:
        committed_paths = normalized_paths(
            git_output("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", "--")
        )
        if changes_versioned_contract(committed_paths):
            previous_revision = "HEAD^"
            context = "HEAD versus HEAD^"

    if previous_revision is None:
        return
    previous = version_from_git(previous_revision)
    if previous is None:
        return
    if semver_key(current) <= semver_key(previous):
        fail(
            errors,
            f"plugin.json: installable contract changed ({context}) but version did not increase "
            f"({previous} -> {current})",
        )


def public_text_files() -> list[Path]:
    result: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in {".git", ".tmp", "__pycache__"} for part in relative.parts):
            continue
        if relative.as_posix() == "TZ.md":
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", ".gitignore", ".gitattributes"}:
            result.append(path)
    return result


def main() -> int:
    args = sys.argv[1:]
    if any(arg != "--commit-gate" for arg in args) or len(args) > 1:
        print("Usage: python scripts/validate_package.py [--commit-gate]")
        return 2
    commit_gate = "--commit-gate" in args
    errors: list[str] = []
    validate_semver_contract(errors)

    for path in REQUIRED:
        if not path.is_file():
            fail(errors, f"missing required file: {path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    plugin = validate_json(PLUGIN / ".codex-plugin" / "plugin.json", errors)
    marketplace = validate_json(ROOT / ".agents" / "plugins" / "marketplace.json", errors)

    if plugin.get("name") != "openbuild":
        fail(errors, "plugin.json: name must be openbuild")
    version = plugin.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        fail(errors, "plugin.json: version must be strict SemVer")
    if isinstance(version, str) and SEMVER.fullmatch(version):
        validate_version_progression(version, errors, commit_gate)
    if plugin.get("license") != "MIT":
        fail(errors, "plugin.json: license must be MIT")
    if plugin.get("skills") != "./skills/":
        fail(errors, "plugin.json: skills must use ./skills/")

    entries = marketplace.get("plugins")
    if marketplace.get("name") != "openbuild" or not isinstance(entries, list) or len(entries) != 1:
        fail(errors, "marketplace.json: expected one plugin in the openbuild marketplace")
    elif entries[0].get("name") != "openbuild" or entries[0].get("source", {}).get("path") != "./plugins/openbuild":
        fail(errors, "marketplace.json: plugin name/path mismatch")

    skill_text = read_text(SKILL / "SKILL.md", errors)
    if not re.search(r"(?m)^name: build$", skill_text):
        fail(errors, "SKILL.md: missing name: build")
    if len(skill_text.splitlines()) > 500:
        fail(errors, "SKILL.md: exceeds the 500-line progressive-disclosure limit")
    required_skill_tokens = [
        "[code discovery](references/code-discovery.md)",
        "[the minimality protocol](references/minimality-protocol.md)",
        "[the TDD workflow](references/tdd-workflow.md)",
        "[versioning](references/versioning.md)",
        "openbuild-discovery",
        "TDD-first",
        "attempt budget",
        "version impact",
    ]
    for token in required_skill_tokens:
        if token not in skill_text:
            fail(errors, f"SKILL.md: missing orchestration contract {token}")

    minimality_text = read_text(SKILL / "references" / "minimality-protocol.md", errors)
    for token in ["## Decision ladder", "## Non-negotiable safeguards", "Minimality decision:"]:
        if token not in minimality_text:
            fail(errors, f"minimality-protocol.md: missing contract {token}")
    for path, token in [
        (SKILL / "references" / "tdd-workflow.md", "Minimality decision:"),
        (SKILL / "references" / "review-protocol.md", "Minimality assessment:"),
        (SKILL / "references" / "spec-template.md", "Minimality decision:"),
    ]:
        if token not in read_text(path, errors):
            fail(errors, f"{path.name}: missing minimality contract {token}")

    metadata_text = read_text(SKILL / "agents" / "openai.yaml", errors)
    if 'allow_implicit_invocation: false' not in metadata_text:
        fail(errors, "agents/openai.yaml: implicit invocation must be disabled")
    if "$build" not in metadata_text:
        fail(errors, "agents/openai.yaml: default prompt must mention $build")

    readme = read_text(ROOT / "README.md", errors)
    readme_ru = read_text(ROOT / "README.ru.md", errors)
    required_docs_tokens = [
        "codex plugin marketplace add",
        "codex plugin add openbuild@openbuild",
        "$openbuild:build",
        "$build new",
        "$build refine",
        "$build run",
        "$build full",
        "$build setup-models",
        "$skill-installer",
        "openbuild-discovery",
        "openbuild-review-fast",
        "TDD-first",
        "CONTRIBUTING.md",
    ]
    for token in required_docs_tokens:
        if token not in readme:
            fail(errors, f"README.md: missing documented token {token}")
        if token not in readme_ru:
            fail(errors, f"README.ru.md: missing documented token {token}")

    required_doc_sections = [
        ("## How automatic code discovery works", "## Как работает автоматический поиск по коду"),
        ("## How TDD-first implementation works", "## Как работает TDD-first реализация"),
        ("## How evidence-gated minimality works", "## Как работает evidence-gated minimality"),
        ("## How progressive review works", "## Как работает progressive review"),
        ("## Git and safety policy", "## Git и безопасность"),
    ]
    for english, russian in required_doc_sections:
        if english not in readme:
            fail(errors, f"README.md: missing required section {english}")
        if russian not in readme_ru:
            fail(errors, f"README.ru.md: missing required section {russian}")

    if "TZ.md" not in read_text(ROOT / ".gitignore", errors).splitlines():
        fail(errors, ".gitignore: local TZ.md must be ignored")
    if "## [0.1.0] - 2026-07-10" not in read_text(ROOT / "CHANGELOG.md", errors):
        fail(errors, "CHANGELOG.md: missing 0.1.0 release entry")
    changelog = read_text(ROOT / "CHANGELOG.md", errors)
    for token in ["openbuild-discovery", "TDD-first", "minimality", "version impact"]:
        if token not in changelog:
            fail(errors, f"CHANGELOG.md: missing Unreleased contract {token}")
    if isinstance(version, str) and not contains_exact_version(changelog, version):
        fail(errors, f"CHANGELOG.md: current plugin version {version} is not documented")

    contributing = read_text(ROOT / "CONTRIBUTING.md", errors)
    for token in [
        "Semantic Versioning",
        "plugins/openbuild/.codex-plugin/plugin.json",
        "version impact",
        "prerelease counter",
        "immutable",
    ]:
        if token not in contributing:
            fail(errors, f"CONTRIBUTING.md: missing versioning contract {token}")

    versioning_text = read_text(SKILL / "references" / "versioning.md", errors)
    for token in ["Version impact", "prerelease", "patch", "minor", "major", "immutable"]:
        if token not in versioning_text:
            fail(errors, f"references/versioning.md: missing contract {token}")

    for path, text in [(ROOT / "README.md", readme), (ROOT / "README.ru.md", readme_ru)]:
        if isinstance(version, str) and not contains_exact_version(text, version):
            fail(errors, f"{path.name}: current plugin version {version} is not documented")
        for stale in ["immutable stable tag", "### Stable `v0.1.0`", "stable tags"]:
            if stale.lower() in text.lower():
                fail(errors, f"{path.name}: stale stable-release wording {stale!r}")
    if not read_text(ROOT / "LICENSE", errors).startswith("MIT License"):
        fail(errors, "LICENSE: expected MIT license text")

    forbidden = ["[TO" + "DO", "TO" + "DO:", "C:" + "\\Users\\", "BIAS" + "MACHINE"]
    fixed_model = re.compile(r"\b(?:gpt[\s\-_‑–—]?\d|o\d(?:[-._][a-z0-9]+)?|claude[\s\-_‑–—]?\d|gemini[\s\-_‑–—]?\d)", re.IGNORECASE)
    active_model_assignment = re.compile(
        r'''(?im)^\s*["']?(?:model|model_id)["']?\s*[:=]\s*["'](?![<{])([^"']+)["']'''
    )
    for path in public_text_files():
        text = read_text(path, errors)
        relative = path.relative_to(ROOT)
        for marker in forbidden:
            if marker in text:
                fail(errors, f"{relative}: forbidden marker {marker!r}")
        if fixed_model.search(text):
            fail(errors, f"{relative}: fixed model slug is not allowed")
        assignment = active_model_assignment.search(text)
        if assignment:
            fail(errors, f"{relative}: active fixed model assignment is not allowed ({assignment.group(1)!r})")
        if path.suffix.lower() == ".md":
            validate_local_links(path, text, errors)

    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}")
        return 1

    print("OpenBuild package validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
