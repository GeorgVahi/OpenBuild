#!/usr/bin/env python3
"""Validate the public OpenBuild package without third-party dependencies."""

from __future__ import annotations

import json
import re
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
    ROOT / "LICENSE",
    ROOT / "CHANGELOG.md",
    PLUGIN / ".codex-plugin" / "plugin.json",
    SKILL / "SKILL.md",
    SKILL / "agents" / "openai.yaml",
    SKILL / "references" / "spec-template.md",
    SKILL / "references" / "code-discovery.md",
    SKILL / "references" / "model-routing.md",
    SKILL / "references" / "review-protocol.md",
    SKILL / "references" / "tdd-workflow.md",
]

TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".toml", ".py"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


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
    errors: list[str] = []

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
    if version != "0.2.0-dev.1":
        fail(errors, "plugin.json: main preview version must be 0.2.0-dev.1")
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
        "[the TDD workflow](references/tdd-workflow.md)",
        "openbuild-discovery",
        "TDD-first",
        "attempt budget",
    ]
    for token in required_skill_tokens:
        if token not in skill_text:
            fail(errors, f"SKILL.md: missing orchestration contract {token}")

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
    ]
    for token in required_docs_tokens:
        if token not in readme:
            fail(errors, f"README.md: missing documented token {token}")
        if token not in readme_ru:
            fail(errors, f"README.ru.md: missing documented token {token}")

    required_doc_sections = [
        ("## How automatic code discovery works", "## Как работает автоматический поиск по коду"),
        ("## How TDD-first implementation works", "## Как работает TDD-first реализация"),
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
    for token in ["openbuild-discovery", "TDD-first", "0.2.0-dev.1"]:
        if token not in changelog:
            fail(errors, f"CHANGELOG.md: missing Unreleased contract {token}")
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
