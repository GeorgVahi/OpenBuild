# TDD-first workflow

Use this protocol for implementation and remediation in `run`, `full`, and implementation-targeted `auto`. Keep reviewers read-only. The root agent owns classification, test selection, validation, and finding adjudication; the risk-matched coding tier performs each root-owned or bounded leased owner-layer edit under [adaptive implementation delegation](implementation-delegation.md).

## Classify the work

- **Direct:** documentation, copy, cosmetic styling, comments, or an obvious local edit with no runtime behavior change. Do not force a failing test; use the narrowest meaningful validation.
- **Investigation:** the root cause or owning layer is not yet clear. Reproduce or trace the primary failure before selecting a fix. Reclassify the implementation as TDD-first when behavior must change.
- **TDD-first:** logic, contracts, validation, routing, state transitions, auth or permissions, persistence, concurrency, background work, integrations, security, or non-trivial user-visible behavior.

Record the implementation mode and reason in the specification. Use the highest-risk applicable mode instead of treating the whole task as an average.

## Red → green → refactor

For TDD-first work:

1. Identify the owning layer and an observable primary signal.
2. Find the narrowest existing supported test path before creating a new harness.
3. Define the smallest contract-level or user-visible failing test, expected failure, minimality decision, and exact test/production file set without editing them.
4. Resolve `implementation.<risk>` through the effective model map, select its first exact root or bounded implementation worker, acquire the single-writer lease for that profile, then launch it through runner-owned `dispatch` with the lease ID and complete structured checkpoint tuple required by [adaptive implementation delegation](implementation-delegation.md). The runner durably records the unactivated `running` Implementation routing receipt, immediately activates that exact run, and returns its activated receipt; record the map source/hash, route step, and matching `implementation-agent-activated` event before any test or production code edit. A completed worker may return a configured `NEEDS_ESCALATION` trigger before any edit; after the root verifies zero writes and transport success, root must durably record `semantic-handoff-rejected` with pending checkpoint invalidation. Reconciliation invalidates the source checkpoint and published recovery artifact and records completion; failure retains the lease. Only completion permits guardian close, release, and approval of exactly one next configured route step. Infrastructure or transport failure never authorizes escalation. If the exact route is unavailable or fails, stop implementation, confirm full-tree zero, keep the milestone blocked, and create no replacement writer. An eligible safe same-scope partial diff may use automatic root-completion under the existing authority. Only a later new checkpoint-bound recovery target writer requires explicit user opt-in; this is not a model escalation or automatic fallback. Once any edit occurs, keep the same writer for the remaining red/green cycle unless the exact automatic root-completion branch applies or the user grants new scope authority.
5. Under that lease, add or modify the test when needed, run it, and record the expected failing signal. A failure caused by broken setup, unrelated code, or an invalid assertion is not a useful red signal.
6. Under the same lease, apply [the minimality protocol](minimality-protocol.md) and implement the smallest coherent owner-layer change supported by repository evidence.
7. Rerun the focused test and require a successful exit before calling it green.
8. Refactor only after green and only when it removes current complexity without widening scope.
9. Require the terminal Implementation routing receipt. A transport-success receipt permits a run-bound `implementation-handoff-accepted` event only after root semantic verification. A semantic `BLOCKED` result instead requires durable `semantic-handoff-rejected`, authenticated guardian close, and lease release with no handoff; verified zero-write `NEEDS_ESCALATION` additionally requires source-checkpoint invalidation before close, release, and any next-route approval. A matching failed/cancelled receipt with complete failure evidence and the process tree stopped also forbids accepted handoff and permits lease release only while the milestone stays incomplete. Then complete the applicable root handoff or remediation gate, run wider validation according to risk, and update durable documentation when behavior, commands, or contracts changed.

When a meaningful automated red signal is impractical, document why and use the best reproducible contract, runtime, or structural signal. Do not invent a test harness merely to perform TDD ceremonially, and never claim a test passed without running it successfully.

## Owner-layer guardrails

- Fix the source-of-truth layer, not a downstream symptom.
- Do not add duplicate decision logic, defensive state repair, or child-side fallbacks to hide an upstream defect.
- Do not weaken validation, authentication, authorization, session/device checks, payment/webhook verification, or secret handling.
- Do not replace supported repository tests or risk-appropriate coverage with a smaller ad hoc check merely to reduce code.
- Stop for required approval before migrations, backfills, destructive data work, notification sends, live infrastructure, secrets, or other irreversible actions.

## Reviewer TDD audit

Reviewers read this protocol when the implementation mode is TDD-first, but remain read-only. They assess:

- whether the selected test or primary signal represents the acceptance criterion;
- whether the recorded red result failed for the intended reason;
- whether the change is in the owning layer and is the minimum coherent fix;
- whether the minimality decision is backed by repository evidence without weakening the accepted behavior or risk coverage;
- whether focused green and wider validation were actually run and interpreted correctly;
- whether regression, edge, security, data, and concurrency coverage matches the task risk.

For recovery-autonomy changes, the red/green evidence must include the owner-level sequence `outside-set-drift` -> retained stopped lease -> private same-lifecycle `terminal-abandonment-v1` -> checkpoint invalidation -> guardian close/archive/release, with no handoff, writer, or user prompt. Recovery-overlap changes additionally reproduce a recovery-target over a pre-dirty allowed file, require the exact pair `[outside-set-drift, preexisting-dirty-overlap]` to select `terminal-abandonment-v2`, reject normal/additional/control-plane variants without mutation, cover schema/binding and every durable replay phase, prove unsafe downgrade rejection after pending v2, and demonstrate that root completion is absent before vacancy and separately audited afterward without Git/workspace mutation. When terminal compatibility changes, construct an actual historical `str(run_dir.resolve())` receipt and prove exact-one `run-dir-v1`/`run-id-v2` matching without rewrite or path leakage. When post-commit completion changes, reproduce exact mixed drift with a task commit containing separately attributed root-completion paths outside the immutable producer allowlist; cover stable private manifest import, canonical confirmed action snapshot → one issuance, snapshot mismatch/replay, capability expiry/cross-binding, owner-enforced legacy format+digest, exact task parent/ancestry/path roles, the second Git barrier, and a fault between intent persistence and private authorization consumption whose reload treats the intent as authoritative without a second event. Also inject a fault after durable source invalidation but before registry completion, prove exact one-time phase recovery, and reject completed replay when authorization handle, verification or scope differs from the full released tuple. Include invalidation/completion/release replay, closed output, later-change preservation, mixed-reason no-mutation, 2.2.0–2.2.3 reader-floor forward replay, prompt stable-object/privacy/binding/retention boundaries, and the distinct `decision-required`, `blocked`, and `automation-exhausted` outcome contracts when those surfaces change. Run Python validation under an active exact-file lease with `PYTHONDONTWRITEBYTECODE=1` unless bytecode cache paths are themselves leased.

A reviewer must not edit tests or implementation, commit, push, or run write-capable remediation. It returns evidence-backed findings to the root. The root verifies each finding and routes confirmed behavioral remediation back through the red → green workflow before requesting another review.

## Completion record

For each milestone record:

```text
Implementation mode: Direct | Investigation | TDD-first
Delegation: root-only | bounded-worker | sequential-workers — <requested writer tier/profile, observed model or unknown, lease, escalation, and handoff evidence>
Owning layer: <path/symbol or contract>
Red signal: <command/scenario and expected failure, or documented reason not practical>
Minimality decision: omitted as unneeded | reused existing | standard library | native platform | installed dependency | custom owner-layer | not applicable — <evidence>
Minimal implementation: <summary>
Focused green: <exact command/scenario and result>
Wider validation: <checks and results>
Reviewer TDD assessment: <met | not met | not applicable — evidence>
Remaining gaps: <none or exact limitation>
```
