# Changelog

All notable changes to OpenBuild are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.1.1] - 2026-07-14

### Added

- Added localized GitHub-ready workflow, usage-routing, and adaptive-delegation images to both READMEs, plus an OS-aware Python 3.11/Codex CLI dependency checkpoint: Windows gets permission-gated exact install commands, while POSIX gets manual platform-appropriate guidance without automatic package-manager selection; ChatGPT authentication remains manual.
- Added a durable agent activity ledger and a localized final report headed `Agents` in English or `Агенты` in Russian for every created search, critic, implementation, review, native fallback, and generic fallback logical run, with evidence-backed actual model/effort or `unknown`, terminal outcome, factual work, and acceptance/specification mapping.

### Changed

- Replaced the six matching Mermaid diagrams with the supplied image assets and documented truthful created-run counting, pre-spawn failures, wrapper/`codex exec` identity, unusable outcomes, and privacy boundaries.
- Corrected the Russian review-cycle arrows and both delegation diagrams so the public visuals preserve remediation-to-review escalation and acquire the writer lease before exact dispatch.
- Deterministic contract validation now mutation-tests the agent report, dependency checkpoint, bilingual image placement, and removal of the replaced Mermaid blocks while preserving blind-spot closure, `auto`, the separate usage pool, Risk-matched-model coding, the single-writer lease, TDD, minimality, and progressive review contracts.

## [2.1.0] - 2026-07-13

### Added

- Added a packaged cross-platform `agent_runner.py` that resolves exact OpenBuild profiles and starts separate `codex exec` processes with explicit model, reasoning-effort, and sandbox arguments under saved ChatGPT authentication.
- Added two-phase start/status/activate/wait receipts with creation-bound worker/Codex identities, immutable prompt snapshots, JSONL/stderr/result/exit-code artifacts, selected profile metadata, and terminal-event validation; only exit code zero plus one final `turn.completed` and a non-empty result is accepted.
- Added a zero-configuration read-only `openbuild_search_separate` profile pinned to `gpt-5.3-codex-spark` with low reasoning and the strict `rg`/`Get-Content` compact evidence-map contract.

### Changed

- `codex-exec-explicit-model` is now the primary discovery, implementation, and review dispatch. Native direct selectors and name-only custom-agent spawns are documented fallbacks and can no longer be reported as observed model switching without evidence.
- The `openbuild_search_separate` ID now resolves exclusively to the packaged `gpt-5.3-codex-spark` profile; same-named project/user files and the legacy migration path cannot replace that fixed discovery contract.
- Explicit-model workers are told that they are already delegated and may not spawn another agent, preventing recursive discovery delegation from global instructions.
- Routing trace validation now requires model reasoning effort and terminal `turn.completed` evidence for explicit CLI dispatches, while retaining the existing risk floors, single-writer lease, TDD, review, fallback, and root-owned Git controls.
- Runner hardening now disables the stable multi-agent capability mechanically, forces subscription-provider selection, rejects top-level and nested provider redirects across user/project config layers, binds Windows identity and termination to the original process object, places each Windows worker tree in a kill-on-close Job Object, creates run directories with a protected current-user-only Windows DACL, uses precise Linux/macOS creation identities, refuses reused-PID process-group signals, treats POSIX zombies as stopped execution while still reaping direct children, keeps POSIX run artifacts private, and performs unconditional terminal-recording cleanup across root/worker/output exceptions and interrupts.
- Activation artifacts are now bound to the live Codex PID plus creation identity, failed post-activation receipts return non-zero, and verified startup failures remain terminal even when `worker.json` could not be published.
- Startup failures no longer claim a stopped process tree when creation-bound cleanup evidence is unavailable; non-valid exit evidence cannot carry a stale code, and running review receipts must retain the exact missing/unknown/missing evidence tuple.
- The runner now persists a private pre-spawn marker before Codex `Popen` and upgrades it with the creation identity before publishing readiness, so a worker crash in that window either permits creation-bound cleanup or blocks fallback as unconfirmed; startup and cancellation receipts use a null/unknown code plus explicit evidence state instead of manufacturing exit code `-1`.
- Public receipt reconstruction now consumes that pre-spawn marker and honors an explicit unconfirmed startup flag, so an unidentified orphan window remains non-terminal and cannot authorize fallback or writer-lease release.
- Implementation launches now require a pre-existing lease ID persisted before `Popen`; honest failed explicit-search receipts may carry `turn.failed` into the documented fallback path.
- Deterministic traces now enforce the actual writer lifecycle (`lease → dispatch → unactivated receipt → matching activation → edits → terminal receipt → accepted handoff → release`) and require unchanged run/process identities plus positively stopped worker/Codex evidence before timeout fallback or lease release.
- Successful writer traces now require a run-bound `implementation-handoff-accepted` event after terminal exit/result evidence and before lease release; failed writer routes require complete independent failure evidence and cannot authorize handoff.
- Deterministic search traces now enforce `dispatch → unactivated receipt → matching activation → worker search → terminal receipt → evidence consumption`; failed search/writer receipts may preserve truthful `turn.completed` evidence only when independently bound exit/result evidence proves failure.
- Failed search runs can never emit `search-evidence-consumed`, and failed implementation runs cannot hide an accepted handoff behind a wrong or missing lease.
- Search validation now requires the fixed packaged Spark runner to be the first selected route, permits native selection only after its stopped terminal failure, and binds exactly one root consumption event to the successful terminal run; writer validation inspects accepted handoffs across the complete lease lifecycle, including events before dispatch.
- Native discovery receipts now bind a read-only sandbox across running and terminal evidence, and `per-spawn-model` fallback is rejected unless it carries a concrete model plus reasoning effort.
- Implementation and review native fallbacks now require their own route-bound stopped terminal runner failure first; direct per-spawn fallbacks must prove both model and reasoning effort, while exact-name compatibility remains honestly unobservable.
- Deterministic review traces now enforce `dispatch → unactivated receipt → matching activation → terminal receipt → review result`, preserve creation-bound process identities across the lifecycle, and reject review conclusions without a stopped process tree, exit code zero, and valid result evidence.
- Review completion now applies the same strict terminal-evidence validator as search and implementation and rejects booleans or numeric strings in place of an integer creation-bound exit code.
- Accepted JSONL completion now also requires a preceding non-empty `thread.started` identity, and package validation compares the complete packaged Explorer instruction to its canonical value so semantic drift cannot hide behind retained keywords.
- POSIX worker termination now preserves the short finalization window after Codex has exited or its creation-bound exit record has been persisted, allowing cancellation recovery instead of overwriting valid completion with a signal-induced failure.
- The explicit runner documents and enforces Python 3.11+ instead of claiming that profile-free Spark discovery has no runtime prerequisite.
- The existing blind-spot, `auto`, separate usage pool, Risk-matched-model coding, single-writer, and review contracts remain intact; Deterministic contract validation now covers the explicit-process receipts and packaged Spark route.

## [2.0.1] - 2026-07-13

### Changed

- All nine OpenBuild custom-agent profiles now use canonical underscore IDs, with `agent_name` reserved for exact profile selection and `task_name` kept as an independent task label.
- Search, Risk-matched-model coding, and progressive review receipts now carry the selector/label separation; Deterministic contract validation rejects legacy selector use and task-label substitution.
- `$build setup-models` now previews a canonical-SHA-bound, permission-gated, resumable migration from legacy hyphenated profiles with complete inventory, hash-bound per-entry authority, observed precondition/result receipts, and conflict-safe actions; it never overwrites or deletes user configuration silently.
- The existing blind-spot, `auto`, separate usage pool, TDD, single-writer, minimality, versioning, and evidence-gated review contracts remain intact.

## [1.1.1] - 2026-07-13

### Changed

- Blind-spot closure now requires a root-reachable graph of every linked normative specification, audits every outgoing edge, and preserves only decisions explicitly declared by their provenance source instead of treating the root document as an implicit override.
- Product-impacting choices now remain user-owned: Build presents viable options, consequences, risks, and a recommendation, then waits before changing requirements, acceptance criteria, roadmaps, milestones, or linked specifications.
- User `D-###` decisions and outcome-neutral technical `T-###` decisions are separated by a consequence-based authority test; uncertain or mixed choices return to the user.
- Locked decisions now require an explicit evidence-backed reopen transition before a later answer can change their outcome, and `Ready` rejects applications bound to stale decision versions.
- Post-answer reconciliation now snapshots the authorizing decision version/source/outcome on every normative write, rebuilds the affected product map, and records a per-target decision application receipt; reopening invalidates prior authorization for every affected tuple, and no-op requires the repeated outcome plus complete tuple coverage, while new product gaps keep the specification in `Questions` rather than being closed as technical cleanup.
- Deterministic contract and trace tests reject product-to-technical relabeling, incomplete linked-source graphs, free-text conflict resolution, false decision provenance, normative writes before the user answer, and `Ready` without a post-write application receipt.
- Existing `auto`, separate usage pool, Risk-matched-model coding, single-writer, and review contracts remain unchanged; Deterministic contract validation now covers the new blind-spot authority gate.

## [1.0.4] - 2026-07-13

### Changed

- Implementation now exact-dispatches `openbuild-implementation-fast`, `openbuild-implementation-balanced`, or `openbuild-implementation-strongest` from milestone risk before every test or production edit and records a workspace-write routing receipt before the single-writer lease begins.
- Progressive review now exact-dispatches the risk-floor `openbuild-review-*` profile, records a read-only routing receipt, stops on sufficient acceptance evidence, and escalates sequentially through fast → balanced → strong → strongest only after a concrete remaining trigger, root remediation, and green validation.
- Deterministic writer and reviewer trace fixtures reject generic or stronger-than-requested writer substitution, sandbox/receipt ordering errors, reviewer tier skips, trigger-free escalation, missing remediation, and unresolved strongest-tier blockers.
- The Build skill, TDD workflow, specification template, contributor guide, and bilingual diagrams now carry the same exact-dispatch receipts without weakening Ready, blind-spot closure, minimality, single-writer, validation, versioning, or root-owned Git controls.
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

[Unreleased]: https://github.com/GeorgVahi/OpenBuild/compare/v2.1.1...HEAD
[2.1.1]: https://github.com/GeorgVahi/OpenBuild/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/GeorgVahi/OpenBuild/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/GeorgVahi/OpenBuild/compare/v1.1.1...v2.0.1
[1.1.1]: https://github.com/GeorgVahi/OpenBuild/compare/v1.0.4...v1.1.1
[1.0.4]: https://github.com/GeorgVahi/OpenBuild/compare/v0.4.0...v1.0.4
[0.4.0]: https://github.com/GeorgVahi/OpenBuild/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/GeorgVahi/OpenBuild/compare/v0.2.0...v0.3.1
[0.2.0]: https://github.com/GeorgVahi/OpenBuild/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GeorgVahi/OpenBuild/releases/tag/v0.1.0
