# Changelog

OpenBuild follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### 2.4.0-alpha.7

#### Added

- Added the durable M5 single-writer integration queue with immutable lane result tuples, generation-bound intents, an exclusive executor lease, dedicated detached integration and validation checkouts, and compare-and-swap updates limited to `refs/openbuild/integration`.
- Added accepted-base dependency bindings and stale-consumer rebind proof, root-owned prerelease ticket/finalization payloads, and a positive no-change abandonment receipt.
- Added real two-lane RecoveryRegistry coverage that keeps both contained writers active concurrently, commits both lanes, proves exclusive integrator ownership, and accepts them serially without scope or ticket reuse.

#### Changed

- Kept lane hard scopes owned until post-CAS validation, registry-resident integration acceptance, and acceptance-bound release; a prepared ref fence now blocks new admission across crash replay.
- Restored the dedicated integration checkout to its exact admitted tip after caught failure or creation-bound executor death during candidate preparation, preserving the same `integrating` intent for a clean replay while refusing cleanup under a live or unknown owner.
- Made each integrator instance non-reentrant so concurrent threads cannot reuse one durable executor lease or mutate the same checkout.
- Rejected dirty or checked-out integration refs, worker edits to version surfaces, duplicate prerelease tickets, stale dependency reuse, ambiguous CAS results, and unsupported integration-ref namespaces.
- Added real fault coverage for post-CAS replay, true validation failure, stale dependency rebind, dirty checked-out refs, positive no-op release, and root-only version finalization.
- Synchronized the manifest, changelog and README install pins for `2.4.0-alpha.7`; M6 capacity and ten-lane stress remain the next milestone.

### 2.4.0-alpha.6

#### Added

- Added an owner-verified recovery transition for an activated Windows Job lifecycle whose containment guardian stopped before publishing `guardian-zero` or a terminal receipt.
- Added exact coverage for stopped/reused guardian, worker, and Codex identities, authenticated ready/precommit/boundary evidence, tamper and live-process rejection, pre-checkpoint materialization, crash replay, dirty-diff preservation, and registry vacancy without handoff.

#### Changed

- Extended private `_reconcile-containment-loss` with a distinct `containment-loss-orphan-reconciliation-v1` path limited to `normal-contained` + `running` + `containment-loss-after-boundary` under the exact `windows-job` / `kill-on-close-no-breakaway` policy.
- Kept ordinary signed post-zero reconciliation unchanged; Linux, fallback, recovery-target, unknown/live identity, missing/tampered artifact, wrong policy, unsupported drift shape, and any ambiguous state remain fail-closed.
- Bound owner-observed orphan zero evidence and the synthetic unsuccessful terminal record to the immutable run/lease/provider/process tuple and durable observation digest, materialized a missing source checkpoint replay-safely, and reused the existing abandonment, invalidation, close, archive, and release phases.
- Synchronized the manifest, changelog and README install pins for `2.4.0-alpha.6`; M5 integration-queue work remains in progress after recovery.

### 2.4.0-alpha.5

#### Added

- Added a durable task-local milestone DAG scheduler with dependency-derived readiness, hotspot-first actionable ordering, canonical plan replay, multi-task isolation, and generation-CAS convergence.
- Added explicit `project-scheduler-lane-v1` bindings so scheduled lanes are authoritative without reinterpreting arbitrary legacy milestone strings.
- Added real two-lifecycle runner/guardian/RecoveryRegistry coverage that pauses after producer terminalization, proves the dependent remains denied before integration release, then integrates and completes both milestones.

#### Changed

- Prevented dependency-waiting milestones from acquiring a scheduler lane, worktree, hard scope, contained writer, or recovery authorization through either the coordinator wrapper or generic durable state sink.
- Required milestone completion to match the exact terminal lane archive, registry-resident integration acceptance, and acceptance-bound release or cancellation of every owned hard scope.
- Rejected control, normalization, Windows device/trailing, duplicate/case, cross-kind, and file/directory ancestor aliases in durable milestone scope plans.
- Synchronized the manifest, changelog and README install pins for `2.4.0-alpha.5`; the full integration queue, capacity/stress, migration/docs gate, and stable release remain later milestones.

### 2.4.0-alpha.4

#### Added

- Added generation-bound runner safe-stop/rebind intents with exact guardian consumption, full-tree-zero evidence, clean allowed-set rebind, and checkpoint-bound dirty recovery.
- Added immutable session binding for the lane recovery root and durable-owner integration validation in a separate owner-private detached checkout of the exact non-empty integration-ref tip.
- Extended the real two-lane process fixture through dirty recovery, coherent-prefix integration, active-scope release, waiting-expansion cancellation, and terminal progress of the neighboring lane.
- Added a crash-boundary regression proving that a durable safe-stop completion can replay and materialize its local receipt without closing the rebound lane.

#### Changed

- Allowed recovery targets to resume across their active checkpoint-authorized scope subset while a conflicting dynamic expansion remains waiting.
- Made successful recovery verification observe the authorized parent checkpoint without mutating its immutable authorization binding.
- Preserved already released scope records across unrelated later lane transitions while continuing to reject new or changed release state outside the acceptance-owned sink.
- Rejected direct-store evidence forgery, empty-commit acceptance, validation checkout mutation, and use of one lane's acceptance to release another lane's active scopes.
- Bound clean validation status, HEAD and tree before and after execution, removed caller-selected recovery roots from the durable sink, and covered later unrelated transitions preserving released records byte-for-byte.
- Bound every new contained terminal archive and integration acceptance to the exact writer `run_id`, and made lane writer/worktree identity immutable across generic durable transitions.
- Required every durable writer attach and every same-writer transition back into `running` to match the exact active lane-local registry lease. Detach remains limited to an exact vacant recovery-ready archive or a safe-stop completion whose durable sink independently reloads a vacant registry and matches the full schema-valid terminal archive.
- Made the durable lane set append-only through the generic state sink, preventing a live or legacy lane from disappearing without a future purpose-specific terminal lifecycle.
- Persisted completed safe-stop evidence in the project lane before materializing the runner-local receipt, closing the post-CAS crash window.
- Synchronized the manifest, changelog and README install pins for `2.4.0-alpha.4`; DAG scheduling, the full integration queue and the stable release remain later milestones.

### 2.4.0-alpha.3

#### Added

- Added a durable project-wide scope/resource lease manager for canonical file, directory, contract, and resource scopes, while keeping soft intents non-authoritative.
- Added atomic pre-start scope expansion, deterministic inactive-reservation cycle handling, and monotonic waiter fairness.
- Added focused collision, alias, resource, fairness, expansion, cycle, and synchronized two-contender CAS fixtures.

#### Changed

- Made concurrent lane admission retry the project generation CAS so two simultaneous claims converge on exactly one active owner and one `waiting-for-scope` lane.
- Required an active project hard-scope grant before runner allowed paths or a contained writer can become write-capable.
- Kept live-writer expansion, live-cycle safe-stop and scope release fail-closed until the R-032 runner/integration owner handshakes land in the next prerelease.
- Synchronized the README version pins for the `2.4.0-alpha.3` development snapshot; the M3 cross-owner bridge, DAG scheduling and integration remain later milestones.

### 2.4.0-alpha.2

#### Added

- Added generation-bound task-lane creation and replay across distinct Git worktrees while preserving the existing one-writer RecoveryRegistry invariant inside each lane.
- Added the runner-to-project-lane bridge: exact private lane routing, lane-scope allowed-set confinement, lane-local registry selection, pre-prompt CAS attach, successful `waiting-for-integration`, isolated containment-loss quarantine/close, and checkpoint-bound same-lane `recovery-ready` replay.
- Added a real two-worktree acceptance fixture that launches two concurrent runner/guardian/fake-Codex process trees, proves both workers execute at the same barrier, keeps one lane live while the other is cancelled, and launches a reserved recovery-target process in that same failed lane.
- Added explicit, scope-bound `protected-user-work` adoption intents with content/index identity checks, integration-commit verification, rollback, and replay-safe acceptance.
- Added owner-derived `terminal-abandonment-v5` for the exact completed `normal-contained` reason `[preexisting-dirty-overlap]`, preserving writer bytes and the Git index while closing the original lifecycle without handoff, diff acceptance, root-completion authority, or artificial drift.

#### Changed

- Kept timeout and process disappearance from releasing lane authority: affected lanes remain quarantined until full-tree-zero evidence, lane-local recovery vacancy, and explicit terminal close.
- Kept exact schema-1 M1 project states readable without rewrite; the first lane-session bind migrates only the original generation-zero, empty-collection shape under the existing lock and generation CAS.
- Raised the private recovery reader floor to 2.4.0 while retaining exact no-rewrite reads of 2.3.6 registries; v5 promotes the floor before source invalidation and remains replay-safe across its durable phases.
- Synchronized the README version pins for the `2.4.0-alpha.2` development snapshot; scope scheduling and integration remain later milestones.

### 2.4.0-alpha.1

#### Added

- Added the first R-031 project coordinator owner for automatic I0 setup, one-use BA0 bootstrap authority, immutable anchor publication, clean B0 state, and sink-free typed observers.
- Added Windows-supported durability and concurrency fixtures plus registry-aware transition-token validation without weakening the fixed-model prohibition.

#### Changed

- Kept the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes.
- Synchronized the README version pins for the `2.4.0-alpha.1` development snapshot; later parallel-lane milestones remain unreleased.

## [2.3.6] - 2026-07-22

### Fixed

- Extended private post-zero containment-loss reconciliation only for a legacy `normal-contained` lease whose fresh reasons are exactly `[git-control-plane-drift, outside-set-drift, preexisting-dirty-overlap]`.
- Added owner-derived `terminal-abandonment-v4` with a distinct checkpoint invalidation reason. It binds the fresh candidate snapshot and reuses the authenticated reconciliation, close, unsuccessful archive, and same-lease release path without accepting a handoff, diff, commit, or root-completion authority.
- Kept the same triple ineligible for ordinary terminal abandonment and kept every other additional, unknown, or control-plane reason no-mutation fail-closed.

### Changed

- Raised the first-write reader floor to 2.3.6 while retaining exact no-rewrite reads through 2.3.5; floor promotion still precedes private-source invalidation.
- Added a committed-HEAD regression matching the observed quarantined lifecycle and synchronized runtime schemas, owner docs, release pins, and package contracts for 2.3.6.
- Preserved the current README workflow, packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes.

## [2.3.5] - 2026-07-22

### Fixed

- Added the private `_reconcile-containment-loss` transition for the exact `containment-loss-after-boundary` state where the same lease is already `stopped-terminal`, its authenticated guardian zero and terminal/run/provider/process bindings match, and the original guardian and worker creation identities are stopped or reused.
- Made the transition record one digest-bound `containment-loss-reconciliation-v1` owner event, atomically clear quarantine while selecting the applicable existing terminal-abandonment v1/v2/v3 intent, invalidate the source checkpoint, record a reconciliation-specific guardian close, archive the lifecycle as unsuccessful and abandoned, and release the same lease without accepting a handoff or starting a writer.
- Kept missing or tampered ready/zero evidence, guardian failure/close, handoff/outbox/prior semantic state, pre-zero lease states, live or unknown original identities, other quarantine reasons, and ineligible abandonment reasons fail-closed without registry/source/workspace mutation or force-unlock. Every durable phase is replayable.

### Changed

- Raised the first-write reader floor to 2.3.5 while retaining exact no-rewrite reads of 2.2.0–2.2.3, 2.2.5, and 2.3.2 generations; floor promotion precedes private-source invalidation.
- Added owner, runner, tamper, no-mutation, reader-floor, package-contract, and observable no-handoff regressions, and synchronized the Build skill, lifecycle references, both READMEs, manifest, changelog, and release pins for 2.3.5.
- Preserved the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, exact model/rung validation, single-writer ownership, and the ban on unknown-model agent routes.

## [2.3.4] - 2026-07-20

### Fixed

- Allowed the post-vacancy root-completion audit to recognize exactly one unsuccessful activated `normal-legacy` release after the 900-second deadline, instead of requiring a contained terminal archive that a non-recovery lease cannot produce.
- Bound new implementation requests to their run identity, specification revision, descriptive milestone, allowed-set digest, and lease kind before activation, then repeated that binding's digest in the durable activated and recomputed failed/stopped terminal receipts. The legacy audit also requires exact vacancy, the failed release to be the only registry-history event carrying that lease ID, and absence of handoff or abandonment artifacts before authorizing root-only continuation.
- Added a narrow 2.3.3 migration path only when the new binding field is absent rather than explicit `null`, the checkpoint-limit run has a valid non-recovery allowed-set digest, the revision is canonical `R-<digits>`, and its exact lowercase `r<digits>` token is present in the immutable task label. It creates no writer, handoff, retry, escalation, recovery capability, or diff acceptance.

### Changed

- Added positive, reused-lease (including a prior unactivated release), mixed-kind, source-digest, explicit-null, descriptive-task, revision-drift/collision, task-case, and missing-activation regressions for checkpoint-limit timeout release → root completion, plus package-contract checks for the executable owner and all lifecycle documentation surfaces.
- Synchronized the Build skill, model-routing and implementation-delegation contracts, both README files, manifest, changelog, and release pins for 2.3.4 while preserving registry schema/reader floor 2.3.2, the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes.

## [2.3.3] - 2026-07-20

### Fixed

- Required every exact-runner `dispatch` invocation to use an explicit external controller timeout of at least 120 seconds (`120000` milliseconds for millisecond-based tools), covering authentication preflight, containment startup, creation-bound Codex readiness, and publication of the atomic activated receipt.
- Kept the controller handshake budget separate from the immutable 900-second post-activation observation budget. A controller timeout before the activated receipt remains a fail-closed transport failure and creates no activation proof, handoff, retry, escalation, or replacement-writer authority inside that lifecycle.
- Fixed `normal-legacy` activation after recovery checkpoint capture is unavailable, including `checkpoint byte limit exceeded`. Ordinary implementation reservations now carry a domain-separated lowercase SHA-256 of the exact requested allowed set instead of an empty `activation_allowed_set_digest`; the activation owner also rejects empty or malformed digest arguments before any state transition. The binding permits activation without claiming checkpoint recovery capability.

### Changed

- Added runner and package-contract regressions for checkpoint-limit activation and the controller budget, and synchronized the Build skill, model-routing and implementation-delegation contracts, both README files, and release pins for 2.3.3.
- Preserved registry schema/reader floor 2.3.2, the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, the ban on unknown-model agent routes, single-writer ownership, and all terminal-reconciliation rules.

## [2.3.2] - 2026-07-20

### Fixed

- Added owner-derived `terminal-abandonment-v3` for a legacy `normal-contained` lease whose only terminal revalidation reasons are the exact sorted pair `[outside-set-drift, preexisting-dirty-overlap]`. The transition invalidates the checkpoint with a distinct reason, closes the existing guardian/archive lifecycle, and releases the same registry lease without accepting the diff or creating a handoff, retry, escalation, grant, writer, or root-completion authority.
- Preserved the recovery-target-only `terminal-abandonment-v2` contract and kept `normal-legacy`, `normal-fallback`, additional/unknown/control-plane reasons, live or ambiguous process state, quarantine, and binding drift fail-closed without mutation or force-unlock.
- Raised the durable reader floor to 2.3.2 while retaining exact 2.2.0–2.2.3 and 2.2.5 generations as no-rewrite legacy reads. The first new durable registry/source write promotes the floor before source replacement, so an existing 2.3.1 lifecycle can migrate safely and an older reader fails closed after promotion.

### Changed

- Updated both README files, lifecycle/reference contracts, package checks, and release pins for 2.3.2.
- Preserved the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes.

## [2.3.1] - 2026-07-19

### Fixed

- Required a valid non-zero creation-bound Codex exit code before a structured Spark model/quota failure can authorize the one-shot Terra discovery fallback. A zero exit now fails closed even if a forged or inconsistent failed-run envelope otherwise matches the terminal fields.
- Added direct eligibility, package-contract, and mutation regressions for the zero-exit boundary and updated the pinned install documentation to 2.3.1.

### Changed

- Updated both README files and release pins for 2.3.1.
- Preserved the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes.

## [2.3.0] - 2026-07-19

### Added

- Added strict `openbuild.discovery.v1` results for every packaged search profile: bounded JSON, safe repository-relative paths, tight line ranges, required owner/test evidence, and a full Git tracked plus untracked/non-ignored content fingerprint verified before and after the read-only scout.
- Added a discovery-only, one-shot Spark availability route. Exact structured `model-unavailable` or model-specific `quota-exhausted` evidence from a stopped `gpt-5.3-codex-spark` process may dispatch canonical Terra through `openbuild_search_balanced`; all other failures retain targeted root recovery.
- Added replay-safe source claims bound to the failed receipt, map hash, resolved Spark/Terra profile descriptors, canonical instruction digest, immutable prompt ID/SHA, fingerprint, reason, and target run. Public receipts expose only normalized reasons and privacy-safe digests.

### Changed

- Packaged and explicit model maps may use paired discovery-only `availability_fallback_agent` and `availability_fallback_triggers` fields with `transport_failure = "availability-fallback"`. Complete legacy project/user maps without them remain valid and keep `block` plus targeted-root behavior without inheritance.
- Strengthened the existing Spark scout by adapting the fresh read-only, structured evidence, fingerprint, and root-verification ideas from [di-sukharev/code-scout-skill](https://github.com/di-sukharev/code-scout-skill) to OpenBuild's exact runner and model map; no upstream code or runtime dependency is vendored.
- Made the canonical search instructions mirror the strict validator grammar explicitly: owner/coupling/test/flow evidence is flat, constraints and uncertainties are bounded strings, and every line range is arithmetically limited without combining distant symbols.
- Updated English/Russian documentation, configuration guidance, contributor checks, package validation, and release pins for 2.3.0.
- Preserved the packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes; both README files pin the same release.

### Fixed

- Rejected malformed, unknown, conflicting, post-turn, completed, cancelled, timed-out, runner/cleanup-failed, or result-bearing Spark failure streams before availability classification; complete JSONL/stderr collection and valid creation-bound `codex-exit.json` evidence must succeed, the clean runner exit must exactly rederive from the event stream, every explicit error record—including raw top-level `code` and exact raw availability `type` records—must normalize to the same eligible reason, and unknown non-protocol `type` records, unrecognized error-bearing events, unreadable/malformed/nonregular JSONL or structured stderr, conflicting `code`/`type` values, JSONL/stderr disagreement, or any existing non-regular/unreadable/empty/malformed result artifact fail closed. Only initial no-follow absence counts as missing; every present JSONL, stderr, and result read stays bound to one verified regular non-reparse descriptor identity through EOF and rejects check/open/read replacement. Discovery maps with availability fallback must start with the exact Spark profile, the persisted source route binds both Spark and Terra descriptor identities before the source process starts, and a Spark source carrying any preinjected fallback binding is rejected before claim or receipt publication.
- Applied ancestor reparse rejection and before/after object-identity checks to symlink and gitlink fingerprint branches, closing the remaining no-follow path-swap boundary.
- Made one-shot Spark fallback claims crash-durable before target request or process creation: POSIX now fsyncs the parent directory, while Windows publishes the exclusive claim through a write-through, no-replace move.
- Validated fingerprint constants, lowercase digest, and non-boolean nonnegative counters before equality; checked-out gitlinks now contribute bounded nested tracked plus untracked/nonignored content and count it against the global limits.
- Made the 2.2.5 registry reader-floor promotion durable before every new private-source generation, including the first recovery-capable source preflight and completion of an abandonment already pending on a legacy floor.
- Recovery targets whose only terminal revalidation reasons are the exact sorted pair `[outside-set-drift, preexisting-dirty-overlap]` now close through owner-derived `terminal-abandonment-v2` instead of retaining an unreleasable lease. The transition uses a distinct checkpoint invalidation, retires the consumed recovery authorization, and reuses the existing identity, zero-proof, guardian, archive, and release gates.
- V2 accepts no handoff, retry, escalation, grant, writer, or diff and creates no root-completion authority. Normal leases, additional/unknown/control-plane reasons, live or ambiguous process state, quarantine, and binding drift remain fail-closed without mutation or force-unlock; root completion remains a separate post-vacancy audit.
- The first durable write by the new recovery owner raises the reader floor to 2.2.5. Exact 2.2.0–2.2.3 floors remain readable without rewrite, while an older reader cannot open a non-vacant floor-2.2.5 registry before explicit vacant retirement.

## [2.2.4] - 2026-07-18

### Fixed

- Post-commit root completion now accepts an actual task parent reached from the immutable writer checkpoint through a complete strictly linear chain of root-only commits. Every path changed by every intervening commit must remain outside the producer allowlist; commit path collection forces `--no-renames` so configured rename detection cannot hide an old producer path. Merge history, unrelated or incomplete ancestry, rename-hidden overlap, and other producer-scope overlap still fail closed before durable intent.
- Git provenance now binds the checkpoint head, actual task parent, and every verified intervening commit ID, while the existing repeated repository barrier continues to reject a concurrent ref/index/worktree change without lifecycle mutation.

### Changed

- Package and release documentation now identify 2.2.4. The durable recovery schema does not change: its reader floor remains 2.2.3 and exact 2.2.0–2.2.2 state remains readable without rewrite-on-read.
- The packaged defaults, `codex-exec-explicit-model`, project → user → packaged precedence, and the ban on unknown-model agent routes remain unchanged; both README files now pin and describe 2.2.4.

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
