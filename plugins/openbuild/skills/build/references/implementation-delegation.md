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

Dispatch that exact profile before every test or production code edit: `low` → `openbuild_implementation_fast`, `medium` → `openbuild_implementation_balanced`, and `high` or `critical` → `openbuild_implementation_strongest`. First establish the lease record, then use `<build-skill-root>/scripts/agent_runner.py start --lease-id <lease-id>`. Record the returned unactivated running receipt, call `activate`, and keep the lease active for the whole process. Accept handoff only after the terminal receipt proves the exact model, effort, sandbox, process lifecycle, exit zero, valid result evidence, and a semantically completed task. Any runner or semantic failure leaves the milestone incomplete and cannot select another writer route.

Acquire the single-writer lease before dispatch, pass its ID to `start`, record the initial unactivated `running` receipt while the lease is active, call `activate`, record the matching `implementation-agent-activated` event, and only then permit the first test or production edit. Replace the running receipt with the terminal receipt after the process finishes. A bounded `wait` timeout is not a failed dispatch and never releases the lease. Use `cancel`, confirm that every started process stopped, and only then record a failed route and release the incomplete milestone's lease. That milestone remains blocked; do not grant a replacement lease or continue its edits.

```text
Implementation routing receipt:
risk: <low|medium|high|critical>
requested_agent: <exact openbuild_implementation_* profile>
task_name: <independent descriptive task label>
requested_tier: <fast|balanced|strongest>
dispatch_method: <codex-exec-explicit-model|unavailable>
configured_model: <profile model or unknown>
model_reasoning_effort: <profile effort or unknown>
observed_agent: <runtime agent or unknown>
observed_model: <runtime model or unknown>
terminal_event: <turn.completed|turn.failed|none>
sandbox: <workspace-write or observed value>
lease: <milestone ID or none>
activated: <false for the recorded running receipt; true after activation>
run_dir: <private runner directory>
worker_pid: <creation-bound worker PID>
worker_process_identity: <recorded OS creation identity>
codex_pid: <creation-bound Codex PID>
codex_process_identity: <recorded OS creation identity>
run_status: <running|completed|failed>
dispatch_result: <selected|failed>
fallback_reason: <none|profile-not-discoverable|profile-incomplete|cli-unavailable|chatgpt-auth-unavailable|model-unavailable|quota-exhausted|runner-failed|spawn-failed|sandbox-mismatch|lease-conflict>
process_tree_stopped: <false while running; true for every terminal receipt>
codex_exit_evidence: <valid|missing|malformed|identity-mismatch on terminal explicit-model receipts>
codex_exit_code: <integer|unknown|null on terminal explicit-model receipts>
result_evidence: <valid|missing|empty|invalid on terminal explicit-model receipts>
```

Every terminal explicit-model receipt carries all three exit/result evidence fields. Valid exit evidence requires an integer exit code; missing, malformed, or identity-mismatched exit evidence requires an unknown exit code. Accepted handoff requires `turn.completed`, valid creation-bound exit evidence with code zero, and a valid non-empty result. Every failed terminal receipt requires a non-zero code, missing/malformed/identity-mismatched exit record, or missing/empty/invalid result as independent failure evidence, including when JSONL reports `turn.failed`; once its process tree is stopped, that accurate failed receipt releases the lease while leaving the milestone incomplete.

Record the ordered activation separately; all bindings come from the already-recorded running receipt:

```text
event: implementation-agent-activated
lease: <same milestone ID>
agent_name: <same exact openbuild_implementation_* profile>
task_name: <same independent task label>
run_dir: <same private runner directory>
worker_process_identity: <same creation identity>
codex_process_identity: <same creation identity>
activated: true
```

Consume a successful worker result only through this event after the matching terminal receipt:

```text
event: implementation-handoff-accepted
lease: <same milestone ID>
agent_name: <same exact openbuild_implementation_* profile>
task_name: <same independent task label>
run_dir: <same private runner directory>
worker_process_identity: <same creation identity>
codex_process_identity: <same creation identity>
result_evidence: valid
```

For every risk tier, a failed or semantically unsuccessful exact dispatch blocks further editing. Do not replace it with another agent, label, or root writer under the same milestone.

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

While the lease is active, the root does not edit workspace files or spawn another writer. It may continue read-only reasoning and user updates that cannot invalidate the lease. If new user input replaces the milestone, interrupt the worker and close the old milestone before separately routing the new request.

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

Require the lease-bound pending request and initial routing receipt for `openbuild_implementation_fast`, `openbuild_implementation_balanced`, or `openbuild_implementation_strongest` before edits, then require its terminal receipt, semantic success, and run-bound accepted-handoff event before consuming output or releasing a completed milestone. Read-only search/discovery and `openbuild_review_*` profiles are never implementation workers.

Every created implementation run requires concrete model, effort, and sandbox evidence. If the required tier cannot be selected or complete the task, stop before further test and production code edits rather than lowering the risk floor.

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

Do not accept a worker result merely because it reports success. If it changed forbidden files, used stale assumptions, cannot prove the primary signal, or exposed a new product/architecture choice, keep the milestone incomplete and blocked. Do not repair that milestone through the root or a replacement lease; report the exact blocker and request new authority when required.

For `sequential-workers`, complete this gate before issuing the next lease. Record the actual mode, verified worker identity/role, allowed files, validation, and handoff in the milestone log.
