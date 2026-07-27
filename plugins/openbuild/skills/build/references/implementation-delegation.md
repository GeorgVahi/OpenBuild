# Adaptive implementation delegation

Use this protocol after the Ready gate to route every code edit to the minimum sufficient proven coding tier for its risk, either as the root or one bounded implementation worker. Preserve one decision owner, the full TDD and validation contract, and one active writer in the shared workspace.

## Delegation modes

Select and record one mode per milestone:

- `root-only` — keep edits with the root only when its effective model satisfies the selected risk tier, especially for unclear ownership, overlapping dirty files, critical or destructive scope, sensitive authority boundaries, or a milestone too coupled to isolate safely;
- `bounded-worker` — lease one coherent milestone with known owning files, acceptance criteria, and a reproducible red or primary signal to one implementation worker;
- `sequential-workers` — use different bounded workers for disjoint milestones, one after another, with a completed root handoff gate between them.

Do not use parallel write-heavy workers in one checkout. Discovery workers, specification critics, and reviewers remain read-only and may run in parallel when their scopes are independent.

Choose the minimum sufficient implementation depth:

| Complexity | Packaged default implementation mode |
|---|---|
| `low` | Luna/medium `openbuild_implementation_fast`, then only on completed pre-edit capability evidence Luna/xhigh `openbuild_implementation_luna_xhigh` → Terra/medium `openbuild_implementation_balanced` → Terra/xhigh `openbuild_implementation_strong` → Sol/high `openbuild_implementation_sol_high` |
| `medium` | Terra/medium `openbuild_implementation_balanced`, then only on completed pre-edit capability evidence Terra/xhigh `openbuild_implementation_strong` → Sol/high `openbuild_implementation_sol_high` |
| `high` | the same Terra/medium → Terra/xhigh → Sol/high ladder, with high-risk validation and review gates |
| `critical` | Sol/xhigh `openbuild_implementation_strongest` with the deepest supported reasoning; never delegate destructive execution |

Use the effective user, project, or packaged model map for every complexity class, as defined by [model routing](model-routing.md). Resolve `implementation.<risk>` before the lease and start its first exact profile. The table above describes the packaged defaults, not a hard-coded override of a configured map. The effective profile must declare the canonical role's exact `routing_rung` and `routing_tuple_confirmed = true`; a known Luna/Terra/Sol model-and-effort tuple must match it, while an unknown custom tuple requires explicit rung confirmation and capability smoke. Escalate only after the current worker returns a valid configured `NEEDS_ESCALATION` trigger before any edit. Do not infer capability from a model name, and do not claim a route or delegation without runtime/configuration evidence.

## Exact writer dispatch

Dispatch the first exact profile returned by `<build-skill-root>/scripts/model_map.py resolve --use-case implementation --risk <risk>` before every test or production code edit. Record the map source/hash and route step. First establish the lease record, then use runner-owned `<build-skill-root>/scripts/agent_runner.py dispatch --lease-id <lease-id>` with the complete recovery-capable tuple `--allowed-file <path>` (repeat as needed), `--specification-revision <revision>`, and `--recovery-target-milestone <milestone>`. Give that command an explicit external controller timeout of at least 120 seconds (`120000` milliseconds for millisecond-based tools); never use the controller's shorter implicit default. This startup/activation budget is separate from the later immutable 900-second observation budget. `dispatch` durably records the unactivated receipt, immediately activates the same run, and durably records the activated receipt before returning; legacy `start` and `activate` remain compatible but are not ordinary orchestration. A controller timeout before that receipt is a transport/controller failure and creates neither activation proof nor replacement-writer authority. Keep the lease active for the whole process. Accept handoff only after the terminal receipt proves the exact model, effort, sandbox, process lifecycle, exit zero, valid result evidence, and a semantically completed task, and root finalization has durably committed the handoff and released containment.

The worker assesses capability before its first write. If the assigned profile is insufficient, it must make no test or production edit and return `NEEDS_ESCALATION` with a reason listed by the resolved route: `task-complexity-above-tier`, `unresolved-cross-layer-reasoning`, `validation-strategy-uncertain`, or `capability-gap`. Only a completed `codex-exec-explicit-model` run with `turn.completed`, exit code zero, valid result evidence, a stopped process tree, concrete observed model evidence, and verified zero writes may authorize the root to release the lease and advance exactly one configured route step without exceeding `max_steps`. Record the root-owned `implementation-escalation-approved` event before the next lease. A critical route is used only when its map records `critical_confirmed = true`.

Infrastructure or transport failure—including CLI, authentication, quota, model availability, sandbox, spawn, runner, timeout, or unusable evidence—never authorizes escalation. Keep the milestone blocked, release only after the process tree is confirmed stopped, and create no replacement writer. Checkpoint-capture unavailability before containment, including a byte-limit failure, may select the existing non-recovery normal path only after a domain-separated lowercase SHA-256 binds the exact requested allowed set through reservation and activation; an empty `activation_allowed_set_digest` is invalid, and this path creates no recovery capability. A later recovery target writer is a separate, owner-private lifecycle rather than transport fallback: it requires terminal full-tree zero proof, an eligible immutable checkpoint, and explicit user opt-in bound to the same allowed scope and specification revision. Once any test or production edit occurs, capability escalation is forbidden for that milestone; the same writer owns the full red/green implementation and handoff unless the exact safe same-scope automatic root-completion branch applies.

Acquire the single-writer lease before dispatch, pass its ID and structured checkpoint tuple to runner-owned `dispatch`, retain the durable unactivated and activated receipts for that exact run, record the matching `implementation-agent-activated` event, and only then permit the first test or production edit. Replace the running receipt with the terminal receipt after the process finishes. Observe one run through nonterminal `wait --soft-timeout-exit-zero` windows of 45, 90 and 120 seconds and then its remaining time under one immutable 900-second observation budget; no soft observation releases the lease, changes writer/model, or starts recovery. At the hard deadline record evidence, call `cancel` automatically, and require the authenticated kernel full-tree zero proof before any terminal transition. A completion recovered during cancellation follows normal finalization. A safe same-scope partial diff can consume the already-authorized root-completion action, but never becomes the failed worker handoff. A successful contained run keeps the lease through root verification and private `_finalize-success`; a failed contained run closes its guardian and releases incomplete without a handoff. The exact closed automatic branches below may continue; every other unsafe or ambiguous state remains blocked without an operational permission question.

For an already-resolved project task lane, pass the complete project lane tuple together with the ordinary lease/checkpoint fields and set `--repo` to that lane's registered worktree. Pass the same tuple to private recovery authorization before consuming a lane checkpoint. Before activation the runner revalidates common-directory, anchor, integration ref, branch, admitted base and allowed-file containment in the lane hard scopes. An ordinary source lane must be clean; a recovery lane may retain only the exact checkpoint-bound dirty state. The exact schema-1 M1 state without `lane_session` is read without repair only at generation zero with empty M1 collections and is written in the current form only by the first locked lane-session generation CAS. The runner uses the coordinator-provided lane recovery root, commits the lane-local contained lease first, CAS-attaches the exact lease/run/allowed-set to the project lane second, and publishes the prompt gate only after both owners agree. Failed or rejected terminals quarantine only that lane. Exact containment-loss reconciliation closes it after lane-local vacancy; a retained eligible checkpoint instead records `recovery-ready`, and only an explicitly reserved recovery-target lease with that digest may re-enter the same lane. The successful accepted handoff records `waiting-for-integration` without releasing project scopes. Runner code never creates a lane, grants scope, schedules work, commits, or integrates.

## Automatic orchestration 2.2.2

Routine same-scope reversible lifecycle work is autonomous: Build never asks whether to continue or cancel, retry, activate, escalate, or perform an authorized root completion. Automatic same-scope root-completion requires no operational user prompt. Questions remain only for a material product, architecture/provider, permission/privacy/security, destructive, external/publication, or scope-authority decision. If no safe branch remains, report `automation-exhausted` or `blocked`, name the non-sensitive missing evidence, and confirm that no writer starts; do not turn that operational state into a yes/no prompt.

Before dispatch, stage prompt bytes through runner-owned `stage-prompt` on stdin and pass the returned owner-private `--prompt-snapshot-id`/`--prompt-sha256` binding. The compatibility `--prompt-file` input must be outside the workspace and pass the same stable-open-object, no-follow, identity, ownership and private mode/DACL proof before lifecycle side effects. Blob, private `prompt.md`, and `request.json` bindings must complete file sync, write-through replace, post-replace rebarrier, and parent metadata barrier before a grant/release or prompt gate can become authoritative; lifecycle reconciliation invokes reference-aware GC only after durable run binding or terminal release and never removes a grant-/lease-referenced blob. Never place prompt, recovery prompt, receipt, helper, ignored artifact, specification update, version, or changelog write in the workspace while an implementation registry is non-vacant. Root may diagnose read-only and may reconcile only the current owner lifecycle until exact vacancy.

After stopped transport success and authenticated full-tree zero, exact `[outside-set-drift]` with no handoff/outbox is reconciled automatically through private `_reconcile-terminal-abandonment`. The exact owner-derived `terminal-abandonment-v1` record changes terminal success to false, permanently invalidates the source checkpoint, produces no retry/escalation/grant/new run/new writer, then uses the existing guardian-close/archive/release gates. A recovery-target with the exact sorted pair `[outside-set-drift, preexisting-dirty-overlap]` selects owner-derived `terminal-abandonment-v2`, its distinct invalidation reason, and retirement of the consumed recovery authorization. A legacy `normal-contained` lease with the same exact pair selects owner-derived `terminal-abandonment-v3` and `terminal-abandoned-legacy-normal-overlap` without fabricating a recovery authorization. A completed legacy `normal-contained` lease with the exact single reason `[preexisting-dirty-overlap]` selects owner-derived `terminal-abandonment-v5` and `terminal-abandoned-legacy-normal-dirty-overlap`; it preserves the writer-produced bytes and Git index and requires no artificial outside drift. All four ordinary paths reach vacancy through the existing gates without accepting a handoff or creating root-completion authority; root completion remains a separate post-vacancy audit. Caller cause/digest input, `normal-legacy`, `normal-fallback`, any additional/unknown/control-plane reason, live or unknown process state, containment/identity/ownership ambiguity, and quarantine are fail-closed without mutation or force-unlock.

The sole quarantine exception is private `_reconcile-containment-loss`. Its existing post-zero branch accepts the same `stopped-terminal` lease only after authenticated guardian zero was durably recorded; it rechecks the private run and terminal bindings, byte-equal ready/zero evidence, absent failure/close/handoff/outbox/semantic state, and stopped-or-reused original guardian and worker creation identities before one digest-bound `containment-loss-reconciliation-v1` event atomically clears quarantine and records the applicable v1/v2/v3/v5 abandonment intent. Only this quarantine path may instead select v4 for a legacy `normal-contained` lease whose fresh reasons are exactly `[git-control-plane-drift, outside-set-drift, preexisting-dirty-overlap]`; the ordinary abandonment command still rejects that triple.

Its distinct pre-zero branch is restricted to an activated legacy `normal-contained` lease still exactly `running` after its Windows guardian stopped before terminal receipt or `guardian-zero`. It requires the durable `windows-job` / `kill-on-close-no-breakaway` provider and affirmative precommit membership, authenticated byte-equal ready/precommit/boundary evidence, exact worker/Codex launch and activation binding, and stopped-or-reused guardian, worker, and Codex creation identities. The owner persists a replay-stable observation, records `containment-loss-orphan-reconciliation-v1`, derives a clearly owner-originated unsuccessful terminal/zero proof without creating `guardian-zero`, and replay-safely materializes a missing source checkpoint before selecting only an already supported exact abandonment reason shape. Checkpoint invalidation, reconciliation-specific close, abandoned archive, and release then reuse the existing durable phases and resume idempotently after a crash. Neither branch accepts a handoff or diff or creates a retry, escalation, grant, run, writer, or root-completion authority. Every other pre-zero shape, Linux/recovery-target/fallback lease, tampered or missing evidence, live/unknown identity, other quarantine reason, or unsupported additional/control-plane revalidation reason remains fail-closed.

Once vacant, the original implementation request authorizes `root-completion-authorized` only for the same revision, milestone and allowed scope, with an independently attributable partial diff, an adequate root risk floor, and no user-owned boundary. The closed outcome classifier is: `decision-required` only for `product|architecture|scope|permissions|privacy|security|destructive|external-action|publication` with `required_action=provide-decision`; `blocked` only for missing or ambiguous safety/process/containment/ownership evidence; `automation-exhausted` only when safe executor/route capabilities under current authority are exhausted. These states never start a writer and never request permission that cannot change the evidence. A checkpoint-bound recovery target remains a new writer and still requires explicit one-shot user opt-in, eligibility, exact binding and vacancy.

The normal exact-agent path is one runner-owned `dispatch`: durable unactivated receipt → immediate `activate` of the same physical run → durable activated receipt → return. Activation records privacy-safe `activated_at`, `observation_started_at`, and `observation_deadline_at = started + 900 seconds`; status/wait expose them. There is no root/user/task/repository action between the two receipts. If the activation gate expires with `activated=false`, no prompt/task/write artifact, unchanged authoritative snapshot, and a full stopped-tree proof, it is one eligible `same-profile-retry` reason and never a substitute root/review gate.

Exactly one `same-profile-retry` may consume one immutable logical-attempt budget for exactly these closed reasons: `observation-deadline`, `activation-gate-timeout`, or transport-success terminal `RETRY_SAME_PROFILE: execution-window-insufficient`. Each requires zero writes, full-tree stop, unchanged specification revision/milestone/allowed-set/profile/route snapshot, and a fresh physical run plus a fresh writer lease where applicable. Infrastructure, authentication, quota, sandbox, provider, containment, transport, scope, or profile drift never authorizes retry. A retry cannot escalate, reuse a terminal identity, or consume a second budget.

For a transport-success terminal zero-write result, canonical `NEEDS_ESCALATION: <configured-trigger>` or the one unambiguous normalized malformed authority line classifies respectively as `canonical-needs-escalation` or `normalized-malformed-needs-escalation`. It must have exactly one authority line, no conflicting `BLOCKED`/`COMPLETED` marker, a configured trigger from the immutable dispatch-time route family, and an exact next step. After the source lane's semantic rejection/stop/release gate, Build advances exactly one configured rung once; another replacement cannot auto-escalate. Infrastructure or transport failure, any write, invalid trigger, route exhaustion, failed invalidation, or ambiguous evidence never escalates.

Lane evidence is exact and nullable by owner: contained work requires terminal full-tree zero, semantic disposition, applicable checkpoint invalidation, archive, guardian close, and registry vacancy before an automatic action; legacy work requires terminal ordinary full-tree stop and lease release with null archive; read-only work requires terminal full process-tree stop with null archive and lease. The root execution log records the authorized/start/completed-or-blocked automatic action before any fresh lease or root edit, preserves one active writer, and reload revalidates the same action rather than creating another.

For a recovery-capable normal source, the first source snapshot is only a preliminary checkpoint candidate. `start` durably reserves the normal lease, then the registry owner re-captures the same keyed snapshot and requires byte-exact equality before committing `normal-snapshot-bound`; only that state may consume the contained launch token. Drift during the preliminary-snapshot-to-reservation window releases the still-unactivated reservation and fails the start, so a completed intervening writer cannot become attributable to the new source. Immediately before activation, the owner re-captures the exact bound normal pre-snapshot or recovery candidate under the registry lock. Drift records an `activation-provenance-drift` abort, retains `process-bound-unactivated`, and never opens the prompt gate; a retry cannot bypass that retained abort.

Each snapshot binds `git ls-files --stage -v -z`; only the normal `H` index tag is eligible. `assume-unchanged`, `skip-worktree`, unmerged/non-normal tags, or any other status-suppressing index state makes recovery capability unavailable rather than trusting porcelain status. Snapshot capture walks every path component with non-following metadata and rejects every Windows `FILE_ATTRIBUTE_REPARSE_POINT` before file/directory/symlink classification, hashing or recursion, so a directory junction at the final path or any ancestor cannot inventory content outside the workspace as an allowed or ignored descendant. It then holds the same object identity through hashing and enumeration: POSIX opens and descends handle-relative with `O_NOFOLLOW` and `dir_fd`, while Windows holds the workspace/component handles without delete sharing and reads the final file handle. Identity and metadata are revalidated before release, so a concurrent file or directory swap makes the snapshot ineligible instead of following replacement content.

`turn.completed` is transport evidence, not semantic acceptance. If the result is `BLOCKED`, or is a configured pre-edit `NEEDS_ESCALATION` with independently verified zero writes, root must use private `_reject-handoff --run-dir <run-dir> --disposition blocked|needs-escalation --evidence-digest <sha256>`. The owner records a one-shot semantic rejection, changes terminal success to false, creates no handoff outbox, and rejects replay or `_finalize-success`. The disposition is exact and lease/run/source-bound: `blocked` requires `checkpoint_allowed=true`, `checkpoint_invalidation=not-required` and no checkpoint digest, while `needs-escalation` first re-captures the full private snapshot and requires byte equality with the authoritative pre-snapshot, then requires `checkpoint_allowed=false` and a pending or completed invalidation. Any allowed, ignored, outside, index or Git control-plane drift retains the stopped lease without semantic disposition. `blocked` may retain an independently revalidated partial-diff checkpoint for an already-authorized automatic root-completion or a later explicitly authorized new recovery writer. `needs-escalation` first persists `checkpoint_invalidation=pending`; reconciliation idempotently invalidates the authoritative source checkpoint and published run artifact, then records registry-bound `completed`. Completed state reloads only with one matching rejection event, one matching invalidation event and a private source whose invalidation reason, evidence and checkpoint digest all agree. Failure or crash retains the lease and resumes the same pending transition. Only completion permits guardian close, lease release, and root approval of exactly the next configured route step.

On Windows, the outside-Job guardian creates the worker suspended, assigns and verifies it inside the kill-on-close Job, and only then resumes it. On Linux, the guardian uses `clone3(CLONE_INTO_CGROUP)` so the worker and even an immediate pre-boundary fork are born inside the private cgroup before any worker exec code; post-spawn attach is forbidden and no production helper may expose it. On every supported platform the guardian that owns native membership also commits the process-bound-unactivated registry generation and returns its digest; root only verifies that receipt before opening the worker gate. The authenticated guardian request, ready receipt, nonce-bound precommit, registry provider receipt and final containment-bound record repeat the same reserved `provider_plan_id` and `ipc_plan_id`; provider/precommit guardian identity and provider kind must agree, affirmative populated/membership proof is mandatory, and precommit worker PID/creation identity must equal the process receipt. Terminal zero proof repeats the exact provider, guardian, worker PID and creation identity, and guardian close repeats the same guardian identity before either record is authoritative. The complete binding is revalidated for every authoritative contained process-bound/running/terminal generation, so digest-consistent drift fails before reload or activation. Before any registry or private-source durable replace, validate the complete top-level and nested allowlist schema, including the lease-state evidence set, outbox/history/tombstone/grant records, private authorization and opaque public checkpoint projection; repeat the same validation on reload. A self-consistent digest never makes unknown fields, malformed state, or a raw public path authoritative. A pre-replacement commit failure retains the prior source or recovery-target generation and tears down the still-gated tree. If replacement became visible before an error, the owner re-barriers and rereads the exact expected digest, then classifies it as committed; a mismatching or unreadable generation remains fail-closed. On Linux, a delegation marker only permits the guardian to attempt setup. Before the durable boundary it must authenticate a worker-private cgroup/mount namespace receipt proving read-only cgroup mounts, denied migration writes, no inherited cgroup-control descriptors, zero capabilities/no-new-privileges and unchanged guardian-observed membership. Missing or drifting proof is containment unavailability or quarantine according to the boundary phase, never permission to continue recovery uncontained. If the one-shot ordinary fallback is claimed but Popen, creation-identity capture, or the process-bound registry write is ambiguous, retain that exact lease under `fallback-launch-ambiguous` quarantine; never route it through ordinary terminal release. The fallback bind uses the same visible-generation resolution: pre-replacement faults retain the claim, a visible exact generation is re-barriered and returned only with the matching digest/process receipt, and unreadable, mismatched or tentatively bound ambiguity is quarantined. Before clearing a contained lease, persist and reload-validate a privacy-safe terminal archive that binds digests of terminal, zero-proof, guardian-close, provider/process and semantic/handoff/outbox evidence.

```text
Implementation routing receipt:
routing_map_source: <project | user | packaged path>
routing_map_sha256: <effective map hash>
route_step: <1..max_steps>
risk: <low|medium|high|critical>
requested_agent: <exact openbuild_implementation_* profile>
task_name: <independent descriptive task label>
requested_tier: <exact configured profile/model-effort step>
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

For every risk tier, a failed exact dispatch or a semantic result other than completed work or a valid configured pre-edit `NEEDS_ESCALATION` blocks further editing. Do not replace transport failure with another agent, label, or root writer under the same milestone.

An activated `normal-legacy` failure release can authorize root completion only after exact registry vacancy when its single unsuccessful `legacy-terminal-released` event is the only registry-history event carrying that lease ID. The owner must reject a successful or unactivated release, any handoff or abandonment artifact, a mismatched run/task/profile/process identity, a non-stopped recomputed terminal receipt, allowed-scope or revision drift, and any mismatch in the pre-activation source-binding digest repeated by the activated and terminal receipts. New requests persist a structured binding for run identity, revision, descriptive milestone, allowed-set digest, and legacy lease kind before activation. Compatibility with 2.3.3 is limited to requests where that field is absent rather than explicit `null`, the exact `checkpoint byte limit exceeded` downgrade, a valid non-recovery allowed-set digest, a canonical `R-<digits>` specification revision, and its exact lowercase `r<digits>` token already bound in the immutable task label. The audit starts no process and accepts no worker result; it only records the original Build request's same-scope root authority after independent partial-diff attribution.

## Single-writer lease

Before spawning an implementation worker, acquire a single-writer lease in the specification and worker brief:

Keep one active writer for the entire lease; do not overlap root edits or another worker with it.
Treat the lease and milestone log as execution metadata, not a semantic specification change. Increment the specification revision only if the lease preparation changes a decision, requirement, acceptance criterion, coverage disposition, scope, or design-relevant repository evidence; otherwise the existing readiness closure remains current.

```text
Milestone: <ID and outcome>
Lease owner: <worker role or identifier>
Requested writer profile/tier: <exact configured canonical profile/model-effort step>
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

Require the lease-bound pending request and initial routing receipt for the selected canonical `openbuild_implementation_*` profile before edits, then require its terminal receipt, semantic success, root verification digest, durable run-bound accepted-handoff event, guardian close, and registry release before consuming output or releasing a completed milestone. Read-only search/discovery and `openbuild_review_*` profiles are never implementation workers.

Every created implementation run requires concrete model, effort, and sandbox evidence. If the starting route step cannot be selected, or if it cannot complete the task and did not return a valid configured pre-edit `NEEDS_ESCALATION`, stop before further test and production code edits rather than lowering the risk floor or bypassing the map.

## Root handoff gate

After a contained worker terminalizes, keep the successful lease retained while the root:

1. Recheck branch, status, full task diff, and user-owned changes against the lease baseline.
2. Verify that every changed path was allowed and that no unrelated state was overwritten.
3. Reread the implementation and adjudicate every assumption or reported conflict.
4. Rerun the focused green check independently, then widen validation according to risk.
5. Create a canonical root verification receipt and pass its lowercase SHA-256 digest to private `_finalize-success`; require the durable outbox event, authenticated guardian close, and registry vacancy before accepting the handoff or releasing the completed milestone.
   If semantic review instead yields `BLOCKED` or verified zero-write `NEEDS_ESCALATION`, pass the evidence digest to `_reject-handoff`, require a durable semantic-rejection receipt, no handoff trace, authenticated guardian close, and registry vacancy, and keep the milestone incomplete.
   If a released 2.2.0/2.2.1 stopped-success lease instead already has its exact task commit published and the only current reasons are `git-control-plane-drift` + `outside-set-drift`, do not call generic reconciliation or broaden the producer allowlist. Under an explicit same-OS-account confirmation of opaque run + full commit, build an owner-private exact remediation manifest, create one canonical confirmed snapshot through `_stage-post-commit-root-completion-action`, pass its opaque ID/SHA exactly once to `_authorize-post-commit-root-completion`, and consume the issued handle through `_finalize-post-commit-root-completion`. Require owner-enforced legacy `run-dir-v1` format+digest, full-tree zero, no handoff/outbox/quarantine, exact commit parent/ancestry/path roles, a repeated Git barrier, durable intent-authoritative capability consumption, replay of an exact visible source invalidation, checkpoint completion, guardian/archive close, and `registry_vacant=true`. A completed replay must revalidate the full released tuple, including authorization handle, verification and scope, before returning success. `blocked` is not success, and manual registry deletion/rollback/replacement writer is forbidden.
6. Route any newly discovered product gap through the blind-spot protocol before further code edits.
7. After release, update the durable specification, minimality record, version/changelog/documentation, and validation log itself.
8. Run progressive review against the complete current diff.
9. Commit only after validation and review pass; keep Git exclusively root-owned.

Do not accept a worker result merely because it reports success. If it changed forbidden files, used stale assumptions, cannot prove the primary signal, or exposed a new product/architecture choice, keep the milestone incomplete and blocked. Do not repair an edited or failed milestone through a replacement lease without new explicit user authority, and do not use root repair outside the exact safe same-scope automatic root-completion branch. Besides a completed, verified zero-write configured `NEEDS_ESCALATION` and exact one-step root approval, the only built-in new-writer path is one explicitly authorized checkpoint-bound recovery target whose source tree is terminally empty and whose repository provenance revalidates exactly. Report any other blocker without turning routine operational state into a permission question.

While the lease is active, validation must not create unleased workspace artifacts. For Python checks set `PYTHONDONTWRITEBYTECODE=1` unless every expected cache path is explicitly part of the allowed set; generated `__pycache__` drift is real outside-set evidence and must never be hidden or manually erased to force finalization.

For `sequential-workers`, complete this gate before issuing the next lease. Record the actual mode, verified worker identity/role, allowed files, validation, and handoff in the milestone log.

## R-005 continuation and review epochs

For an attributable partial diff, run the existing root-completion audit before emitting any incomplete response. Call `_record-root-completion` with the intended `--continuation-action`; only after the owner durably writes the audit does it persist the digest-bound automatic continuation receipt. `RUN`, direct-fix, QA, and review are automatic same-authority continuation actions and provided incidents cannot regress them to repeated permission prompts. `new-writer` remains a decision-required security action with its own recovery eligibility, binding, and user opt-in; do not force-unlock, fabricate a handoff, or reuse an unsafe lease.

`max_steps` is bounded per immutable full-diff revision, not per task lifetime. Pass the canonical revision/full-diff/validation/AC digests and sorted de-duplicated stable open/closed `finding_key` values to every review dispatch. The runner compares them against an owner-private digest ledger under its workspace lock, appends the dispatch before process creation, rejects concurrent ledger drift, and refuses a fourth attempt for one immutable diff. A material fix begins a fresh review epoch automatically. Unchanged finding keys, or a diff-only change without validation/AC advance or a finding closure, close the automatic route as `automation-exhausted`; they never create a workspace artifact or a permission question.

Browser QA is a runner-owned generic substitute lifecycle, not a writer or a user-supplied receipt. It requires a private nonce/observation channel, fresh temporary profile, credential/provider environment stripping, loopback/file-only scenario allowlist, creation-bound child identity, equal pre/post full-worktree fingerprints, argv and scenario-manifest digests, and an independent guard attached while the child is suspended. Only that guard may prove zero external requests/actions; project/child stdout and callbacks are untrusted. Missing pre-execution isolation fails closed before child code, while exit zero and a stopped process tree remain mandatory before projecting `openbuild.browser-qa.v1`.
