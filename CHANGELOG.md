# Changelog

OpenBuild follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.1.3] - 2026-07-14

### Changed

- Restored the three localized README diagrams with short headings and updated model routing to show targeted root recovery only; packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes remain unchanged.

## [2.1.2] - 2026-07-14

### Added

- Added zero-setup packaged defaults for every canonical discovery, implementation, and review role, with project → user → packaged precedence for non-Spark overrides.

### Changed

- Made `codex-exec-explicit-model` the only agent dispatch path. Removed native, name-only, generic, role-only, deprecated search-fallback, and other unknown-model agent routes.
- Exact-runner failures now create no replacement agent: discovery uses disclosed targeted root recovery, while implementation and review gates remain incomplete.
- Shortened both README files to the automatic workflow, the four supported install/update commands, concise path-based usage, exact model routing, and simplified progressive review.
