# Build specification template

Use this as a flexible structure. Remove irrelevant sections and keep the document concise enough to remain the durable source of truth for a long-running task.

```markdown
# Build: <short outcome>

- Status: Draft | Questions | Ready | In progress | Complete
- Last updated: YYYY-MM-DD
- Original request: <one to three sentences in the user's language>
- Primary signal: <observable proof of success>
- Review baseline: <Git branch@SHA and initial status, or a non-Git artifact manifest>
- Workflow target: Ready | Complete
- Starting phase: discovery | reconciliation | interview | blind-spot critique | implementation | verification
- Specification revision: R-001
- Complexity: low | medium | high | critical — <evidence>
- Implementation mode: Direct | Investigation | TDD-first — <evidence>
- Version impact: not applicable | prerelease | patch | minor | major — <version source, policy, and evidence>
- Routing mode: codex-exec-explicit-model | root-recovery | blocked
- Discovery mode: delegated | mixed | root-recovery — <exact runner evidence or root recovery reason>
- Search usage route: separate-pool | root-recovery — <exact result or terminal failure and circuit breaker>
- Search routing receipt: <model-map source/hash/step, exact agent, dispatch method, configured/observed model, pool, result, and fallback reason>
- Implementation model route: <ordered exact canonical profile/model/effort steps, up to five> | blocked — <semantic outcome, pre-edit escalation, and blocker>
- Implementation routing receipt: <model-map source/hash/step, risk, exact requested agent/tier, dispatch method, configured/observed model, workspace-write sandbox, lease, result, and fallback reason>
- Review routing receipt: <model-map source/hash/step, diff revision, risk floor, exact requested agent/tier, dispatch method, configured/observed model, read-only sandbox, result, and fallback reason>

## 1. Outcome

### Problem

<What is currently wrong or missing, and who it affects.>

### Desired behavior

<What the user can observe or do after completion.>

### In scope

- <required result>

### Out of scope

- <explicit exclusion>

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| <flow> | `path:line` | <fact> | <decision impact> |

### Source of truth

<Owning layer, data, or state.>

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `<root-or-linked-spec>` | <user/repository/upstream> | <value> | <requirements, ACs, D-###> | <mapped targets or none; path:line audit evidence> | yes/no/unknown | aligned/conflict/gap |

Include the selected root, every linked or named normative companion, and cited decision records. The graph is complete only when every outgoing edge target is mapped and every source is reachable from the root. A resolved user decision keeps the same authority wherever it is stored, but the owning source must explicitly list its `D-###`; do not assume the root overrides a linked source.

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| `<source>` | explicit precedence/explicit supersession/user decision | <mapped authority source + record type + governed target + revision + positive line, or D-### + exact answer source + selected outcome> | aligned/deferred |

Free-text evidence or root preference is not a valid conflict resolution. `Deferred` is allowed only here as a post-map result of a matching user decision, never as an initial source-map assertion.

### Gap

<Exact mismatch between the request and current project.>

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | <actor.trigger.behavior> | user | open/resolved/reopened/superseded | <question> | <answer> | <source, revision, or new evidence> | <what this determines> |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | <outcome-neutral implementation choice> | proposed/selected/superseded | <repository or contract evidence> | <resolved D-###, requirements, ACs, invariants, and observable outcomes preserved> |

### Pending proposals

- <Proposed normative change linked to an open/reopened D-###; not yet applied to approved requirements, acceptance criteria, roadmap, milestones, or linked specifications.>

## 4. User scenarios

### Primary scenario

1. <action>
2. <observable result>

### Errors and edge cases

- <condition> -> <expected behavior>

## 5. Requirements and acceptance criteria

- [ ] AC-01: <observable user or contract result>.
- [ ] AC-02: <observable result>.

### Invariants

- <behavior that must remain true>.

## 6. Technical boundaries

### Affected layers and contracts

- <layer or contract> — <change or preserved behavior>.

### Data and migration

<Schema, backfill, compatibility, and rollback, or why none is required.>

### Security and privacy

<Permissions, validation, and sensitive data, or why none is affected.>

### Performance and concurrency

<Load, races, caching, or why none is affected.>

### Observability and errors

<How failures are detected and diagnosed.>

### Versioning and release

<Authoritative version source, current/next version, changelog/docs synchronization, and whether a release action is authorized.>

## 7. Validation and review

- Primary signal: <main proof>.
- Red signal: <failing test/reproduction and intended reason, or why not applicable/practical>.
- Minimality decision: <omitted as unneeded | reused existing | standard library | native platform | installed dependency | custom owner-layer | not applicable — evidence>.
- Focused green: `<exact command or scenario>` -> <result>.
- Targeted checks: `<command or scenario>`.
- Wider checks: `<risk-based command or scenario>`.
- Manual/runtime check: <if required>.
- Starting review tier: <tier and evidence>.
- Required final tier: <tier and evidence>.
- Review ladder: <exact profiles dispatched sequentially, trigger/remediation between tiers, and stop reason>.
- Review focus: <correctness, security, data, UX, etc.>.

## 8. Milestones

### M1. <coherent outcome>

- Status: Pending | In progress | Complete
- Scope: <included work>
- Excludes: <excluded work>
- Implementation mode: Direct | Investigation | TDD-first
- Delegation: root-only | bounded-worker | sequential-workers | blocked — <lease owner, requested risk-matched writer profile/tier, observed model or unknown, allowed files, escalation, or exact blocker>
- Red signal: <test/reproduction and expected failure, or not applicable with reason>
- Minimality decision: <selected rung, skipped complexity, and any ceiling/upgrade trigger>
- Focused green: `<command or scenario>` -> <result>
- Validation: `<commands or scenarios>`
- Acceptance: AC-01, AC-02
- Review: Pending | Accepted — <exact agent, routing receipt, mode/tier/confidence, verdict, coverage, findings, escalation trigger or stop reason>
- Version: unchanged | `<previous> -> <next>` — <impact/evidence>
- Commit: Pending | `<sha>` | Not applicable

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | <stable semantic concern/key> | gap/covered/not applicable | repository fact/technical decision/product decision/new authority | <path:line, D-###, or reason> | <owner/action or none> |

Keep stable `B-###` IDs for outcome/scope, actors/permissions, primary and alternate flows, errors/recovery, accessibility/localization/responsive UX, ownership/contracts, data/migration/retention, security/privacy/abuse, compatibility/rollout/rollback, performance/concurrency/idempotency, integrations/partial failure, observability/support, acceptance/testability/minimality, and task-specific concerns.

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| <risk> | <assessment> | <action> | Open/Handled/Accepted |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-### | <answer and provenance captured by each write> | <every target/change tuple, fresh after reopen; no-op only for the repeated outcome and complete prior tuple set> | <D-### and invariants> | <D-### or none> |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | <generalist/product-UX/architecture-data-security/reliability-validation; observed tier> | COVERED/GAPS | <semantic keys, D-###, or none> | <linked B-###/D-### and action> |

## 10. Open questions

Blocking product questions:

- <D-### or None>.

Non-blocking assumptions:

- <assumption and how it will be verified>.

## 11. Agent activity ledger

Created logical agent runs: `<count>`.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | <search/critic/implementation/review and task> | <exact runner value> | <exact runner value> | <terminal and semantic outcome> | <short factual work; AC, milestone, or specification section, or none> | <accepted non-private receipt evidence> |

Create a row only after the exact-runner logical agent run exists. A wrapper and its child `codex exec` count as one logical run. Pre-spawn dispatch failures do not increment the created-run count; list normalized failures separately when they affected routing. Keep every created terminal run visible even when unusable, cancelled, or timed out.

Actual model and effort come from the accepted explicit-runner receipt. Never create an agent row from a requested label or unverified native dispatch. Do not include any PID, thread ID, private run path, raw prompt, raw log, token or usage value, or authentication detail.

Pre-spawn dispatch failures (not included in created count): <profile/route -> normalized reason, or none>.

The final localized report uses `Agents` for English and `Агенты` for Russian. It states the created logical-run count and renders one row per ledger entry with role/task, actual model/effort, status/outcome, work, and AC/milestone/spec mapping.

## 12. Execution and validation log

### YYYY-MM-DD — <stage>

- Changed: <summary>.
- Routing: <model-map source/hash/steps; search receipt/circuit breaker; implementation exact dispatch/receipt/lease; sequential review receipts>.
- Primary signal: met | not met | partially validated.
- Validation: `<command>` -> <result>.
- Minimality decision: <selected rung and evidence>.
- Review: <mode, tier, verdict, confidence, and material decisions>.
- Version: <impact, previous/next value, synchronized files, or not applicable>.
- Commit: `<sha>` | not created.
- Remaining: <next step or none>.
```

## Quality gate

- Every required outcome has an observable acceptance criterion.
- Repository evidence supports decisions without becoming a raw code dump.
- Product decisions are separate from autonomous technical choices.
- The specification source map is a closed root-reachable graph: every outgoing normative edge has discovery evidence and a mapped target, and every locked `D-###` is declared by its provenance source.
- Every source conflict has a structured reconciliation receipt backed by explicit precedence/supersession authority or a matching user decision; free-text preference cannot align it.
- `D-###` belongs to the user; each `T-###` is outcome-neutral and proves preservation of locked requirements, acceptance criteria, invariants, and observable behavior.
- Workflow target, starting phase, and specification revision reflect current artifact evidence.
- Stable decision IDs preserve resolved answers; reopening requires recorded new evidence and history.
- A second answer cannot replace a locked outcome without an explicit `decision-reopened` transition; Ready rejects applications from stale decision versions.
- Reopening invalidates prior write/application authorization for that `D-###`; the new decision version must rebuild and receipt every prior target/change tuple separately, or record a user-confirmed no-op for the repeated outcome and complete tuple set.
- Every coverage-ledger row is `covered` or `not applicable` with evidence before `Ready`; question count is never a substitute for coverage.
- The current revision has the risk-appropriate fresh readiness-critic closure and no unadjudicated gaps, contradictions, or missing authority.
- No unanswered `D-###` has changed normative requirements, scope, product behavior, UX, permissions, data policy, monetization, acceptance criteria, roadmap, milestones, or linked specifications.
- The decision application receipt maps every Build-made normative change to a resolved user decision or a locked requirement propagated without semantic change.
- Complexity and routing claims use actual risk and runtime evidence.
- Every Build-created commit in a versioned repository receives a unique higher version by default; required manifest, changelog, and documentation updates stay in the same commit.
- Broad code discovery records delegation or an honest root fallback, with critical findings verified by the root.
- TDD-first milestones record an intended red signal, owner-layer implementation, and focused green evidence, or explain why an automated red signal was impractical.
- Implementation milestones record an evidence-backed minimality decision without weakening acceptance criteria or safeguards.
- Delegated implementation records one active writer lease, allowed files, root handoff validation, and root-only Git ownership.
- Every test or production code edit follows an exact risk-matched writer dispatch and Implementation routing receipt; every progressive review follows an exact read-only reviewer dispatch and Review routing receipt.
- Reviewer escalation is sequential from the risk floor, advances one proven tier only after a concrete remaining trigger, and stops when acceptance evidence is sufficient.
- Milestones deliver coherent outcomes rather than arbitrary file groups.
- Validation commands exist or are explicitly marked as proposed.
- Blocking questions are empty before implementation starts.
- `Complete` is supported by acceptance evidence, green validation, and review.
