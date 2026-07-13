# Changelog

All notable changes to OpenBuild are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

Target development version: `1.0.2`.

### Changed

- Repository discovery now requires an exact `openbuild-search-separate` custom-agent dispatch before the first non-trivial lookup; generic workers, task labels, and profile mentions no longer count as model selection.
- Search fallback now uses a fixed observable failure vocabulary and emits a routing receipt with requested/configured/observed route metadata before any repository search.
- Deterministic routing-trace fixtures reject root-first search, silent generic fallback, missing receipts, and unrecognized fallback reasons while preserving the existing circuit breaker and honest runtime-metadata limitations.
- Reworked the GitHub-facing English and Russian documentation with native Mermaid diagrams for the end-to-end lifecycle, risk-matched model routing, and the single-writer TDD/handoff safety loop.
- Added a compact command-to-outcome map so new users can choose `new`, `refine`, `run`, `full`, `auto`, or `setup-models` without reading the complete workflow reference first.
- Risk-matched-model coding now selects fast, balanced, or strong/strongest writers from milestone risk while preserving the existing blind-spot Ready gate, `auto` routing, TDD red/green workflow, evidence-gated minimality, single-writer lease, root handoff, validation, versioning, and progressive review methods.
- Low and medium implementation may continue through an exact configured named profile when runtime model metadata is `unknown` or `unobservable`; high and critical work still require their strong/strongest floor, and no route may claim model switching or savings without evidence.
- Escalation now requires scope/risk growth, insufficient worker confidence, a deeper red/green signal, task-scoped validation failure, or a confirmed review finding instead of launching a stronger model merely because it exists.
- `$build setup-models` now supports `openbuild-implementation-fast`, `openbuild-implementation-balanced`, and `openbuild-implementation-strongest` alongside separate usage pool search and risk-matched read-only review profiles.
- Deterministic contract validation covers writer-tier selection, evidence-only escalation, metadata limitations, and the unchanged TDD and single-writer controls in both languages.

## [0.4.0] - 2026-07-12

### Added

- Evidence-backed blind-spot closure with stable coverage and decision IDs, duplicate-question suppression, evidence-gated reopening, risk-adaptive fresh specification critics, and a current-revision Ready gate.
- Automatic lifecycle routing that separates the requested workflow target from the first incomplete specification or implementation phase.
- Adaptive implementation delegation with root-only, bounded-worker, and sequential-worker modes protected by a single-writer lease and root validation handoff.
- Usage-aware routing that sends every repository search to a confirmed separate usage pool first, applies a per-run circuit breaker on quota/profile failure, then falls back to an efficient main-pool search route.
- Strongest-proven-model coding for every test and production code edit, with complexity-scaled reasoning, an optional permission-gated `openbuild-implementation-strongest` profile, and an implementation blocker instead of an unproven downgrade.
- Deterministic contract validation for phase routing, specification readiness, decision memory, critic-loop bounds, implementation delegation, and usage-aware model routing across the skill, template, and both READMEs.

### Changed

- A bare Build invocation now selects `auto`; a new idea still targets completion while existing specifications resume from evidence-backed state.
- Read-only review profiles may also serve as fresh specification critics, while implementation workers remain bounded, sequential, and isolated in a separately permissioned write profile.
- `$build setup-models` now proposes separate-pool search, efficient search fallback, strongest implementation, and risk-based review roles from current official/runtime/user-confirmed evidence instead of one generic discovery profile.

## [0.3.1] - 2026-07-12

### Added

- Evidence-gated minimality for implementation and remediation: omit unneeded code, reuse repository solutions, prefer standard-library/native/installed capabilities, and write custom code only as a minimum coherent owner-layer change.

### Changed

- OpenBuild advanced from release `v0.2.0` to `v0.3.1`; `v0.2.0` remains immutable, and committed development version `0.3.0` was never tagged.

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

[Unreleased]: https://github.com/GeorgVahi/OpenBuild/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/GeorgVahi/OpenBuild/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/GeorgVahi/OpenBuild/compare/v0.2.0...v0.3.1
[0.2.0]: https://github.com/GeorgVahi/OpenBuild/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GeorgVahi/OpenBuild/releases/tag/v0.1.0
