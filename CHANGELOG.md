# Changelog

All notable changes to OpenBuild are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Automatic broad code-discovery routing to a dedicated read-only worker with compact evidence maps, root verification, and honest quota/model fallbacks.
- Self-contained Direct/Investigation/TDD-first classification with red → green → refactor milestones and reviewer TDD-evidence audits.
- Evidence-gated minimality for implementation and remediation: omit unneeded code, reuse repository solutions, prefer standard-library/native/installed capabilities, and write custom code only as a minimum coherent owner-layer change.
- Version-aware milestone commits with an explicit `version impact`, same-commit manifest/changelog/documentation synchronization, and immutable release boundaries.
- Public contributor, validation, Git, versioning, and release guidance in `CONTRIBUTING.md`.

### Changed

- Optional model setup now proposes an `openbuild-discovery` profile for the minimum proven suitable code-search model and a complete fast-to-strongest review ladder without hard-coding model slugs.
- Main preview plugin version advanced to `0.2.0-dev.3`; immutable release `v0.1.0` remains unchanged.
- README terminology now identifies `v0.1.0` as a pinned prerelease instead of calling it stable.

## [0.1.0] - 2026-07-10

### Added

- Canonical Build skill with `new`, `refine`, `run`, `full`, and `setup-models` modes.
- Repository-grounded specification template and collision-safe file selection.
- Capability-aware read-only discovery with honest model/role fallbacks.
- Complexity classification and bounded progressive review escalation.
- Permission-gated custom-agent model ladder setup.
- Codex plugin marketplace distribution and standalone skill installation path.
- Complete English and Russian documentation.

[Unreleased]: https://github.com/GeorgVahi/OpenBuild/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GeorgVahi/OpenBuild/releases/tag/v0.1.0
