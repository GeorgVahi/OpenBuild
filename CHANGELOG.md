# Changelog

OpenBuild follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.2.3] - 2026-07-18

### Added

- Added exact backward-compatible terminal binding recognition for released 2.2.0/2.2.1 `run_dir` receipts alongside the current opaque `run_id` format. Legacy state is verified without rewrite-on-read and private run paths never enter public receipts.
- Added a hidden, same-OS-account, one-time post-commit root-completion flow for an already published legacy task: owner-private remediation scope/capability issuance, exact task commit parent/ancestry/path attribution, repeated Git provenance checks, replay-safe checkpoint invalidation, guardian/archive close, and privacy-safe `terminal-root-completed` or `blocked` output.

### Changed

- The recovery reader floor is now `2.2.3` after the first new durable transition. Exact 2.2.0–2.2.2 state remains readable without rewrite-on-read; unsafe downgrade remains blocked until explicit vacant retirement.
- Producer writer allowlists and full task remediation scope are now distinct immutable bindings, so separately authorized root-owned specification/version/documentation paths never broaden a future writer lease.
- The packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes remain unchanged; both README files now pin and describe 2.2.3.

### Fixed

- Prevented a 2.2.2 reader from retaining an otherwise completed 2.2.1 lease solely because the terminal binding projection changed from `run_dir` to `run_id`.
- Prevented post-commit Git proof from mutating the authoritative source checkpoint before the durable root-completion intent, and bound the second Git barrier to the first verified candidate checkpoint.
- Required remediation manifests to use the stable owner-private external-file importer and required the post-commit path to prove the legacy binding without generic reconciliation pre-empting its resumable phases.
- Split same-account confirmation from capability issuance through a canonical owner-private action snapshot, persisted exact `run-dir-v1` format evidence, and made the first durable terminal intent authoritative for capability consumption across the registry/source crash window.
- Made exact visible source invalidation replay complete the pending registry phase once, and replaced commit-only completed replay with a private full-tuple artifact that revalidates authorization, verification, scope and release evidence before returning success.
- Added explicit unconsumed-capability rotation through a fresh confirmed snapshot, required pending-intent scope validation before any release, and made identical action staging repair a legacy reader floor after a source-first durability fault.

## [2.2.2] - 2026-07-17

### Added

- Added owner-private bounded UTF-8 prompt staging, stable external-file import, immutable prompt ID/SHA cross-binding, authorization retirement, and lifecycle-invoked reference-aware snapshot garbage collection. Blob, run prompt, and request bindings now cross the file/replace/metadata durability barriers before authority or release; POSIX owner/mode and Windows protected-DACL checks guard both normal and recovery prompt paths.
- Added the exact replay-safe `terminal-abandonment-v1` outcome for stopped transport-success lifecycles whose only semantic failure is `outside-set-drift`; it permanently invalidates the source checkpoint, accepts no handoff, closes the existing guardian, archives the terminal evidence, and releases the same lease.

### Changed

- Same-scope recovery now reconciles the current lifecycle automatically before considering root completion. The root does not write any workspace path while the implementation registry is non-vacant, and it asks the user only for a material product, architecture, scope, permissions, privacy, security, destructive, external, or publication decision—not for permission that cannot change retained evidence.
- New recovery writers remain explicit one-shot opt-in operations with an eligible immutable checkpoint and exact vacancy. Missing process/containment/ownership evidence remains `blocked`; exhausted safe executor capability is reported as `automation-exhausted` without starting another writer.
- The recovery reader floor is now `2.2.2` after the first new durable transition. Exact 2.2.0/2.2.1 state remains readable without rewrite-on-read, and downgrade still requires explicit vacant retirement.
- The packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes remain unchanged; both README files now pin and describe 2.2.2.

### Fixed

- Prevented orchestrator prompt/spec/version artifacts from manufacturing `outside-set-drift`, and prevented repeated manual recovery authorization from being suggested when it cannot make an ineligible checkpoint or occupied registry usable.
- Public runner receipts now return an opaque owner-allocated run handle plus prompt digest/classification instead of absolute run, profile, and artifact paths; legacy explicit paths remain controller-private.
- Terminal reconciliation now rejects a normal or recovery-target directory whose owner-derived run ID differs from the current lease before any state mutation, and executable closed-outcome/root-completion audit records cover the user-decision boundary.
- Recovery-target abandonment now reads its run ID from the shared lease/plan owner, and every recovery-target terminal outcome retires consumed authorization through a replay-safe source/registry boundary before GC. Prompt GC rebarriers and validates each authoritative private source before classification; malformed state fails closed, and grant/lease references outrank release tombstones.
- Public receipt failures now use closed classifications rather than raw CLI, event, artifact, or filesystem error text; `external-action` matches the selected decision class exactly, and `_record-root-completion` durably records the audited automatic action before root edits.
- Added end-to-end, legacy-forward, exact-schema, mutation, stable-object, prompt-retention, and platform privacy coverage for autonomous terminal reconciliation.

## [2.2.1] - 2026-07-16

### Changed

- OpenBuild now launches exact agents through one runner-owned `dispatch` operation that durably records the unactivated receipt and immediately activates the same run. Legacy `start`/`activate` commands remain compatible, while ordinary orchestration can no longer leave a reviewer or writer waiting behind an unreleased prompt gate.
- Routine internal decisions no longer interrupt the user: 45/90/120-second checks remain soft observations, the same run continues automatically within one immutable 15-minute budget, and the hard deadline triggers safe cancellation and full-tree-stop verification without a confirmation question.
- Verified zero-write same-profile retries, canonical or unambiguously malformed configured escalation requests, and safe root completion now follow bounded automatic policies. Transport, infrastructure, containment, scope, route, privacy, or authorization ambiguity still fails closed and material product or architecture decisions remain user-owned.
- The packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes remain unchanged; both README files now pin and describe 2.2.1.

### Fixed

- Added immutable activation/deadline evidence and package mutation tests so atomic activation, the 900-second observation budget, automatic retry/escalation boundaries, and the routine-question boundary cannot silently regress.

## [2.2.0] - 2026-07-16

### Added

- Added Luna/xhigh and Sol/high implementation and read-only review profiles. The packaged defaults now advance reasoning before changing models: low-risk routes use Luna/medium → Luna/xhigh → Terra/medium → Terra/xhigh → Sol/high, while medium/high routes use Terra/medium → Terra/xhigh → Sol/high.
- Added an owner-private recovery registry with immutable lease-start checkpoints, explicit opt-in authorization, one-shot recovery targets, authenticated terminal handoff outboxes, and a `2.2.0` reader floor that blocks unsafe downgrade until an explicitly vacant registry is retired.

### Changed

- Soft `wait` timeouts remain observations rather than terminal failures. OpenBuild now observes the same run through 45, 90 and 120 second windows with an explicit zero-exit soft-timeout mode, retaining strict exit-code compatibility when the flag is omitted; the third observation reports status without automatic cancellation. No replacement writer or model escalation is created from timeout, transport, or containment failure. A successful contained writer remains leased until root independently verifies its diff and primary signal, finalizes the handoff, and closes the guardian.
- Transport-completed `BLOCKED` and verified zero-write `NEEDS_ESCALATION` results now use a root-owned one-shot semantic rejection transition. They create no accepted handoff and reject replay or later success finalization. Escalation persists a resumable checkpoint-invalidation-pending boundary; invalidation failure retains the lease, and only registry-bound completion permits containment close, release, and the next configured route step.
- Updated both README files and localized routing diagrams for the reasoning-first packaged defaults. Model-map precedence remains project → user → packaged, and all agents still run through `codex-exec-explicit-model`; unknown-model agent routes remain forbidden.
- Structured review results now name the added `luna_xhigh` and `sol_high` tiers explicitly instead of reporting an exact reasoning-first route as `unknown`.
- Project and user model maps now fail closed unless non-critical routes are contiguous reasoning-first ladder segments with a non-Sol initial step and no critical-only strongest profile; critical routes remain one direct strongest step. Implementation traces also reject replayed terminal receipts and writer-lease releases.
- Effective canonical implementation/review profile overrides now bind an explicit confirmed routing rung. Known Luna/Terra/Sol model-and-effort tuples must match that rung, preventing a safe map ID from being rebound directly to Sol or a weaker critical profile; unknown custom tuples require an explicitly confirmed rung and capability smoke.
- Recovery snapshots now hold non-following, identity-checked path objects through hashing and enumeration. POSIX uses handle-relative `dir_fd` traversal and Windows holds every component without delete sharing, so concurrent file/directory replacement fails closed instead of escaping the workspace snapshot.
- One-shot ordinary fallback process binding now resolves every durable replacement fault as either the prior claimed generation or the exact re-barriered bound generation. The runner verifies the returned digest/process receipt and quarantines claimed or tentatively bound ambiguity instead of entering ordinary terminal release.
- Registry and private-source generations now use exact top-level and nested allowlist schemas before durable replacement and on every reload. Unknown lease/history/outbox/grant fields, invalid state-specific evidence, malformed checkpoint authorization, and raw private paths in public checkpoint projections fail closed even when a generation carries a self-consistent recomputed digest.
- Authoritative contained leases now require a complete cross-binding from the reserved provider/IPC plan through guardian identity and affirmative precommit membership to the exact worker PID/creation identity. Digest-consistent missing or mismatched receipts fail before reload and activation.
- Terminal zero proof and guardian close now require complete identity-bound records. `NEEDS_ESCALATION` first requires a freshly captured private snapshot byte-equal to the authoritative pre-snapshot; semantic rejection then uses an exact disposition matrix, lease/run/source-bound history, and a reload-validated private-source invalidation before containment can close or release.

### Security

- Added an authenticated outside-job Windows guardian with kill-on-close full-tree containment and fail-closed Linux cgroup v2 containment. Linux now creates the worker inside its cgroup before exec with `clone3(CLONE_INTO_CGROUP)`, then requires authenticated private cgroup/mount namespaces, read-only control views, active migration-write denial, zero capabilities/no inherited control descriptors, and guardian-side membership revalidation; the delegation environment marker is intent, not proof. A normal source run may use one proved pre-boundary ordinary-process fallback when native containment is unavailable; a recovery target never falls back, and post-boundary containment loss quarantines the lease. Git's trailing-slash markers for ignored nested repositories are normalized and recursively inventoried under the same checkpoint limits instead of silently disabling containment.
- Removed the obsolete production post-spawn cgroup attachment helper; package validation now rejects reintroducing either that API or a direct production `cgroup.procs` write path.
- Windows workers are now created suspended and resume only after verified guardian-owned Job assignment. The guardian that owns native membership also commits the process-bound registry generation atomically from root's perspective: pre-replacement failures retain the prior generation, while a fully visible expected generation is re-barriered and treated as committed. Ambiguous fallback spawn, identity, or bind attempts retain the claimed lease in quarantine.
- A recovery-capable normal source now re-captures and byte-compares its private pre-snapshot after the normal lease is durably reserved; only a matching `normal-snapshot-bound` generation may claim containment. Immediately before activation, normal-source and recovery-target snapshots are recaptured again; drift durably retains an unactivated abort and never opens the prompt gate. Guardian request, ready, precommit, provider receipt and containment-bound records repeat the reserved provider and IPC plan IDs, and either ID drifting fails before gate release.
- Recovery snapshot capture now binds Git's extended index tag and fails closed on `assume-unchanged`, `skip-worktree`, or any other non-normal entry. Every Windows path component is inspected without following it first; a reparse point, including an ancestor directory junction, is rejected before checkpoint classification, hashing or recursion. Contained terminal release now preserves a validated privacy-safe digest archive binding terminal, zero-proof, guardian-close, provider/process and semantic/handoff evidence after the active lease/outbox are cleared.

## [2.1.5] - 2026-07-14

### Added

- Added `$build configure-models`, a deep plain-language interview that creates a complete project or user model map for discovery, specification critics, implementation, review, escalation limits, reasoning effort, and explicitly confirmed critical routes.
- Added a strict `model_map.py` resolver, packaged route defaults, and balanced/strong/strongest read-only search profiles with exact model, effort, sandbox, source, and map-hash evidence.

### Changed

- Every created agent now resolves the model map in project → user → packaged order before the `codex-exec-explicit-model` runner. Semantic evidence may advance one configured step; transport failure never selects another model, single-writer and read-only boundaries remain fixed, and unknown-model agent routes remain forbidden.
- Updated both README files with the concise configuration command and retained the packaged defaults as zero-setup behavior.

## [2.1.4] - 2026-07-14

### Added

- Added the packaged `openbuild_implementation_strong` Sol/high profile and a validated pre-edit `NEEDS_ESCALATION` receipt for one-tier writer escalation with zero writes.

### Changed

- Medium- and high-risk implementation now starts on Terra balanced; Sol high requires completed capability evidence, while Sol xhigh is critical-only. High-risk review now starts on Terra balanced and escalates to Sol only for a concrete remaining trigger.
- Updated the localized README routing diagrams; packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes remain enforced.

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
