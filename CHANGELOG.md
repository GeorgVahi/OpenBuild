# Changelog

All notable changes to OpenBuild are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-07-10

### Added

- Automatic broad code-discovery routing to a dedicated read-only worker with compact evidence maps, root verification, and honest quota/model fallbacks.
- Self-contained Direct/Investigation/TDD-first classification with red → green → refactor milestones and reviewer TDD-evidence audits.
- Version-aware milestone commits with an explicit `version impact`, same-commit manifest/changelog/documentation synchronization, and immutable release boundaries.
- Public contributor, validation, Git, versioning, and release guidance in `CONTRIBUTING.md`.
- A deterministic commit gate and contract tests that require a unique higher SemVer version, changelog, and synchronized README references in every new OpenBuild commit.

### Changed

- Optional model setup now proposes an `openbuild-discovery` profile for the minimum proven suitable code-search model and a complete fast-to-strongest review ladder without hard-coding model slugs.
- Plugin and standalone invocations now share one explicit Build contract for `$openbuild:build` and `$build`.
- OpenBuild advanced from preview `v0.1.0` to `v0.2.0`; the earlier tag remains immutable.
- README terminology now identifies `v0.1.0` as a pinned prerelease instead of calling it stable.
- Continuations preserve the original task baseline so final review covers committed milestones as well as current work.
- Independent reviewers explicitly disable inherited conversation history when supported, and score-only escalation no longer drives cosmetic review loops.
- `refine` and `run` stop cleanly for a missing specification, while unrelated user changes and sensitive values remain protected from edits, commits, and output.

## [0.1.0] - 2026-07-10

### Added

- Canonical Build skill with `new`, `refine`, `run`, `full`, and `setup-models` modes.
- Repository-grounded specification template and collision-safe file selection.
- Capability-aware read-only discovery with honest model/role fallbacks.
- Complexity classification and bounded progressive review escalation.
- Permission-gated custom-agent model ladder setup.
- Codex plugin marketplace distribution and standalone skill installation path.
- Complete English and Russian documentation.

[Unreleased]: https://github.com/GeorgVahi/OpenBuild/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/GeorgVahi/OpenBuild/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GeorgVahi/OpenBuild/releases/tag/v0.1.0
