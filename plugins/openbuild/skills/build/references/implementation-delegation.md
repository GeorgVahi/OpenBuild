# Adaptive implementation delegation

Use this protocol after the Ready gate to route every code edit to the minimum sufficient proven coding tier for its risk, either as the root or one bounded implementation worker. Preserve one decision owner, the full TDD and validation contract, and one active writer in the shared workspace.

## Delegation modes

Select and record one mode per milestone:

- `root-only` — keep edits with the root only when its effective model satisfies the selected risk tier, especially for unclear ownership, overlapping dirty files, critical or destructive scope, sensitive authority boundaries, or a milestone too coupled to isolate safely;
- `bounded-worker` — lease one coherent milestone with known owning files, acceptance criteria, and a reproducible red or primary signal to one implementation worker;
- `sequential-workers` — use different bounded workers for disjoint milestones, one after another, with a completed root handoff gate between them.

Do not use parallel write-heavy workers in one checkout. Discovery workers, specification critics, and reviewers remain read-only and may run in parallel when their scopes are independent.

Choose the minimum sufficient implementation depth:

| Complexity | Default implementation mode |
|---|---|
| `low` | exact `openbuild_implementation_fast` profile for Direct, documentation, cosmetic, or mechanical work without behavior changes |
| `medium` | exact `openbuild_implementation_balanced` profile for contained logic or refactoring with clear contracts and supported tests |
| `high` | exact `openbuild_implementation_strongest` profile for cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy, or sensitive state |
| `critical` | exact `openbuild_implementation_strongest` profile with the deepest supported reasoning; never delegate destructive execution |

Use a risk-matched coding model for every complexity class, as defined by [model routing](model-routing.md). Select fast for low-risk Direct work, balanced for contained medium-risk behavior, and strong/strongest for high or critical work. Scale supported reasoning effort within the selected tier: low/minimal when safe for mechanical work, medium for contained behavior, high for cross-layer work, and the deepest supported effort for critical reasoning. Escalate only after evidence shows that the current tier is insufficient. Do not infer capability from a model name, and do not claim a route or delegation without runtime/configuration evidence.

## Exact writer dispatch

Dispatch that exact profile before every test or production code edit: `low` → `openbuild_implementation_fast`, `medium` → `openbuild_implementation_balanced`, and `high` or `critical` → `openbuild_implementation_strongest`. When the callable spawn schema exposes a direct model selector, bind the profile's confirmed model there; otherwise pass the canonical profile ID through `agent_name` and a separate descriptive label through `task_name`. A generic worker, descriptive task name, prompt mention, or stronger-than-requested profile is not the selected risk route and must not start editing.

Emit an Implementation routing receipt after dispatch and before granting the single-writer lease or changing any file:

```text
Implementation routing receipt:
risk: <low|medium|high|critical>
requested_agent: <exact openbuild_implementation_* profile>
task_name: <independent descriptive task label>
requested_tier: <fast|balanced|strongest>
dispatch_method: <per-spawn-model|exact-custom-agent|unavailable>
configured_model: <profile model or unknown>
observed_agent: <runtime agent or unknown>
observed_model: <runtime model or unknown>
sandbox: <workspace-write or observed value>
lease: <milestone ID or none>
dispatch_result: <selected|failed>
fallback_reason: <none|profile-not-discoverable|selector-unavailable|model-unavailable|quota-exhausted|spawn-failed|sandbox-mismatch|tier-unproven|lease-conflict>
```

For low or medium work, a failed exact dispatch may use another writer only when native selection or runtime/configuration evidence proves the same requested tier, sandbox, and lease; record the failed exact attempt and replacement identity instead of calling it the requested profile. For high or critical work, block before editing if the required profile/model floor is not proven. `root-only` remains a safety mode for coupled, sensitive, destructive, or overlapping scope, but it may edit only when the root's observed model satisfies the same tier and its receipt records `dispatch_method: risk-matched-root`; never use it as a silent convenience fallback.

## Single-writer lease

Before spawning an implementation worker, acquire a single-writer lease in the specification and worker brief:

Keep one active writer for the entire lease; do not overlap root edits or another worker with it.
Treat the lease and milestone log as execution metadata, not a semantic specification change. Increment the specification revision only if the lease preparation changes a decision, requirement, acceptance criterion, coverage disposition, scope, or design-relevant repository evidence; otherwise the existing readiness closure remains current.

```text
Milestone: <ID and outcome>
Lease owner: <worker role or identifier>
Requested writer profile/tier: <fast|balanced|strong|strongest plus exact profile>
Observed model/tier: <verified value or unknown>
Writer-route evidence: <official/runtime/config/user mapping and selection evidence>
Baseline: <branch@SHA plus task status/diff identity>
Allowed files: <exact paths or narrow owned directory>
Forbidden files: <specification, version/changelog, unrelated dirty paths, generated outputs>
Acceptance criteria: <IDs>
Implementation mode: <Direct | TDD-first>
Red or primary signal: <exact command/scenario and expected reason>
Required focused green: <exact command/scenario>
Stop conditions: <new product choice, architecture conflict, scope expansion, destructive/external action, secret, or file overlap>
```

Require all of these before granting the lease:

- the root has recorded the current branch, status, task diff, and pre-existing user changes;
- the selected root or worker satisfies the milestone's risk-matched coding tier; otherwise no lease is granted;
- allowed files have one clear owner and do not overlap active user or agent edits;
- the specification is `Ready` at its current revision;
- the worker can complete a coherent outcome without making product or architecture decisions;
- no other implementation worker or root edit is active.

While the lease is active, the root does not edit workspace files or spawn another writer. It may continue read-only reasoning and user updates that cannot invalidate the lease. If new user input changes the milestone, interrupt the worker before editing or issuing a replacement lease.

## Worker contract

Tell the implementation worker to:

1. Reread the allowed files and applicable repository instructions from disk.
2. Confirm the baseline and stop if allowed files changed or overlap is unclear.
3. Run or verify the supplied red or primary signal when practical.
4. Make the smallest coherent owner-layer change only inside the allowed file set.
5. Run the supplied focused check and report its exact result.
6. Return changed paths, a concise diff summary, validation evidence, assumptions, and any stop-condition finding.

The worker must not:

- make product or architecture decisions, or reopen accepted product behavior;
- edit the durable specification, version sources, changelog, release notes, or unrelated files;
- stage, commit, push, tag, publish, deploy, or mutate external systems;
- add production dependencies or infrastructure without existing approval;
- continue after discovering a new product choice, owner-layer conflict, secret, destructive action, or material scope expansion.

Require the exact dispatch and Implementation routing receipt above for `openbuild_implementation_fast`, `openbuild_implementation_balanced`, or `openbuild_implementation_strongest` before the selected worker receives its lease. Read-only search/discovery and `openbuild_review_*` profiles are never implementation workers. A proven equivalent native selector, built-in worker, generic bounded subagent, or `root-only` route may write only under the explicitly recorded exception above and when the same lease, TDD, minimality, validation, and review controls remain in force.

Missing model/tier metadata alone does not block low or medium implementation when the exact named profile is configured, the requested agent selection is recorded, its sandbox is appropriate, and no runtime evidence contradicts the route. Record the effective model/tier as `unknown` or `unobservable`; never claim a model switch or usage saving from the profile name alone. For high work require a confirmed strong route, and for critical work require the strongest proven route plus any applicable authority checkpoint. If the required tier cannot be selected, stop before all test and production code edits rather than silently lowering the risk floor.

## Root handoff gate

After the worker finishes or stops, release the lease and let the root:

1. Recheck branch, status, full task diff, and user-owned changes against the lease baseline.
2. Verify that every changed path was allowed and that no unrelated state was overwritten.
3. Reread the implementation and adjudicate every assumption or reported conflict.
4. Rerun the focused green check independently, then widen validation according to risk.
5. Route any newly discovered product gap through the blind-spot protocol before further code edits.
6. Update the durable specification, minimality record, version/changelog/documentation, and validation log itself.
7. Run progressive review against the complete current diff.
8. Commit only after validation and review pass; keep Git exclusively root-owned.

Do not accept a worker result merely because it reports success. If it changed forbidden files, used stale assumptions, cannot prove the primary signal, or exposed a new product/architecture choice, keep the milestone incomplete and repair under a new root-owned signal or a new bounded lease.

For `sequential-workers`, complete this gate before issuing the next lease. Record the actual mode, verified worker identity/role, allowed files, validation, and handoff in the milestone log.
