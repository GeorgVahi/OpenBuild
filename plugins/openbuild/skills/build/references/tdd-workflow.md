# TDD-first workflow

Use this protocol for implementation and remediation in `run` and `full`. Keep reviewers read-only; the root agent owns classification, test selection, edits, validation, and finding adjudication.

## Classify the work

- **Direct:** documentation, copy, cosmetic styling, comments, or an obvious local edit with no runtime behavior change. Do not force a failing test; use the narrowest meaningful validation.
- **Investigation:** the root cause or owning layer is not yet clear. Reproduce or trace the primary failure before selecting a fix. Reclassify the implementation as TDD-first when behavior must change.
- **TDD-first:** logic, contracts, validation, routing, state transitions, auth or permissions, persistence, concurrency, background work, integrations, security, or non-trivial user-visible behavior.

Record the implementation mode and reason in the specification. Use the highest-risk applicable mode instead of treating the whole task as an average.

## Red → green → refactor

For TDD-first work:

1. Identify the owning layer and an observable primary signal.
2. Find the narrowest existing supported test path before creating a new harness.
3. Add or select the smallest contract-level or user-visible test that should fail for the missing behavior when practical.
4. Run it and record the expected failing signal. A failure caused by broken setup, unrelated code, or an invalid assertion is not a useful red signal.
5. Apply [the minimality protocol](minimality-protocol.md) and implement the smallest coherent owner-layer change supported by repository evidence.
6. Rerun the focused test and require a successful exit before calling it green.
7. Refactor only after green and only when it removes current complexity without widening scope.
8. Run wider validation according to risk, then update durable documentation when behavior, commands, or contracts changed.

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

A reviewer must not edit tests or implementation, commit, push, or run write-capable remediation. It returns evidence-backed findings to the root. The root verifies each finding and routes confirmed behavioral remediation back through the red → green workflow before requesting another review.

## Completion record

For each milestone record:

```text
Implementation mode: Direct | Investigation | TDD-first
Owning layer: <path/symbol or contract>
Red signal: <command/scenario and expected failure, or documented reason not practical>
Minimality decision: omitted as unneeded | reused existing | standard library | native platform | installed dependency | custom owner-layer | not applicable — <evidence>
Minimal implementation: <summary>
Focused green: <exact command/scenario and result>
Wider validation: <checks and results>
Reviewer TDD assessment: <met | not met | not applicable — evidence>
Remaining gaps: <none or exact limitation>
```
