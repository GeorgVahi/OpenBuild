# Progressive review protocol

Use this protocol for every `run`, `full`, and implementation-targeted `auto` milestone and for the final task diff.

## Inputs

Provide the reviewer with:

- the current specification and acceptance criteria;
- the current specification revision, coverage-ledger closure, and readiness-critic evidence;
- the saved review baseline;
- the exact task diff, including committed milestone changes and relevant uncommitted work;
- validation commands and current results;
- the implementation mode and, for TDD-first work, the owning layer plus red/green evidence;
- the implementation delegation mode and, when used, the single-writer lease plus root handoff evidence;
- the observed search usage route/circuit breaker and risk-matched writer profile/tier evidence or disclosed limitation;
- the recorded minimality decision, skipped complexity, and any ceiling/upgrade trigger;
- the version impact, authoritative version source, and synchronized version/changelog/documentation evidence;
- the requested review tier and the evidence supporting that tier;
- the repository path and explicit read-only boundary.

Use a fresh context with conversation-history inheritance disabled when the runtime supports it, such as `fork_turns: "none"` or an equivalent `fork_context: false`. If no isolation control exists, disclose possible inherited context and label independence as limited. Do not reveal earlier reviewer conclusions; pass source artifacts instead.

## Exact dispatch and routing receipt

Resolve `review.<risk>` through `<build-skill-root>/scripts/model_map.py` and select its first exact returned reviewer. Start it through `<build-skill-root>/scripts/agent_runner.py`; `codex-exec-explicit-model` pins the resolved model, reasoning effort, and read-only sandbox in a separate process. Record the map source/hash and route step, the unactivated `running` receipt, call `activate`, record `review-agent-activated`, and wait for the stopped terminal receipt. Accept a review only after that receipt records `turn.completed`, creation-bound exit code zero, valid result evidence, and a semantically completed review. Transport failure blocks the exact review/release gate; create no replacement reviewer.

Run the resolved route strictly sequentially, moving at most one configured step at a time and stopping at both `max_steps` and the risk-specific ceiling. The packaged defaults start Luna/medium for low, Terra/medium for medium/high, and Sol/xhigh for critical; low and non-critical routes raise reasoning on the same model before changing models. The non-critical route ends at Sol/high; Sol/xhigh is critical-only and is never a post-review escalation target for low, medium, or high risk. After every dispatch, record this complete lifecycle before using the result:

```text
Review routing receipt (first `running`, then terminal):
routing_map_source: <project | user | packaged path>
routing_map_sha256: <effective map hash>
route_step: <1..max_steps>
diff_revision: <commit/status/hash identity>
risk_floor: <exact first configured profile/model-effort step>
requested_agent: <exact openbuild_review_* profile>
task_name: <independent descriptive task label>
requested_tier: <exact configured profile/model-effort step>
dispatch_method: <codex-exec-explicit-model|unavailable>
configured_model: <profile model or unknown>
model_reasoning_effort: <profile effort or unknown>
observed_agent: <runtime agent or unknown>
observed_model: <runtime model or unknown>
terminal_event: <turn.completed|turn.failed|none>
activated: <false in the recorded running receipt; true in the terminal receipt>
run_status: <running|completed|failed>
sandbox: <read-only or observed value>
dispatch_result: <selected|failed>
fallback_reason: <none|profile-not-discoverable|profile-incomplete|cli-unavailable|chatgpt-auth-unavailable|model-unavailable|quota-exhausted|runner-failed|spawn-failed>
process_tree_stopped: <false in running; true in terminal>
run_dir: <protected run artifact directory>
worker_pid: <worker PID>
worker_process_identity: <creation-bound identity>
codex_pid: <Codex PID>
codex_process_identity: <creation-bound identity>
codex_exit_evidence: <missing while running; valid|missing|malformed|identity-mismatch when terminal>
codex_exit_code: <integer|unknown|null>
result_evidence: <missing while running; valid|missing|empty|invalid when terminal>

Review activation event:
event: review-agent-activated
diff_revision: <same diff identity>
requested_agent: <same exact profile>
task_name: <same independent label>
run_dir: <same run directory>
worker_process_identity: <same creation-bound identity>
codex_process_identity: <same creation-bound identity>
activated: true
```

The two receipts and activation event prove routing intent, process continuity, and observed selection separately. The running receipt must carry the exact non-terminal evidence tuple `codex_exit_evidence: missing`, `codex_exit_code: unknown|null`, and `result_evidence: missing`. The terminal receipt must preserve every routing and process identity from the running receipt, positively confirm the process tree stopped, and carry concrete model/effort plus valid exit/result evidence before `review-result`. Any exact-runner or semantic failure leaves the gate incomplete and creates no replacement reviewer.

## Required result

Ask for this structure:

```text
Review mode: independent | self-review-limited
Routing mode: codex-exec-explicit-model | diagnostic-root-review
Requested tier: fast | luna_xhigh | balanced | strong | sol_high | strongest | unknown
Observed model/tier: <verified value or unknown>
Diff identity: <commit range, status, or artifact hashes>
Verdict: ACCEPT | REVISE | ESCALATE | BLOCKED
Confidence: high | medium | low
Score: <0.0-10.0 or omitted>

Acceptance coverage:
- AC-01: met | not met | not verified — <evidence>

Findings:
1. <critical|high|medium|low> — <path:line or authoritative evidence>
   Impact: <observable consequence>
   Fix: <smallest owning-layer correction>

Validation assessment:
- <check and interpretation>

TDD assessment:
- <met | not met | not applicable — red signal, owner layer, focused green, and risk coverage>

Delegation assessment:
- <met | not met | not applicable — requested risk-matched writer profile/tier, observed model or unknown, escalation evidence, writer lease, allowed files, baseline, root handoff, and Git ownership>

Minimality assessment:
- <met | not met — selected rung, repository evidence, avoidable complexity, and preserved safeguards>

Version assessment:
- <met | not met | not applicable — impact, version source, synchronized files, and release evidence>

Escalation recommendation:
- <next tier and trigger, or none>
```

A finding without concrete evidence, impact, and an actionable owning-layer fix is not sufficient by itself.

## Score semantics

The optional score is a secondary escalation signal, not the completion gate.

- `9.5-10.0`: no known actionable gap and strong evidence coverage.
- `8.0-9.4`: may indicate a credible improvement, uncertainty, or incomplete coverage when the reviewer names the concrete gap.
- below `8.0`: material correctness, safety, or acceptance gaps remain.

Do not force a reviewer to invent a score when the runtime does not support calibrated scoring. A score alone is never an escalation trigger; require an evidence-backed finding, uncertainty, or coverage gap. Do not make cosmetic changes merely to raise a number.

## Root adjudication

For every finding, the root agent must:

1. Reproduce or verify the evidence.
2. Decide whether it is task-scoped and actionable.
3. For a confirmed behavioral finding, establish or reproduce the failing signal and fix it in the owning layer through [the TDD workflow](tdd-workflow.md).
4. For a confirmed minimality finding, verify that the smaller path preserves acceptance criteria and safeguards, then fix it through [the minimality protocol](minimality-protocol.md); route any behavior change through TDD-first.
5. Reject hypothetical, duplicate, line-count-only, style-only, or pre-existing out-of-scope findings with a recorded reason.
6. Rerun affected validation.

Reviewers do not edit tests or implementation, run write-capable remediation, commit, push, expand scope, or make product decisions. They audit TDD evidence when applicable; the root owns the remediation cycle.

## Escalation triggers

After adjudication and remediation, move one configured route step when a trigger allowed by the resolved map remains:

- score is below `9.5` and is tied to a concrete finding, uncertainty, or coverage gap;
- confidence is low;
- acceptance coverage is incomplete or based on weak evidence;
- reviewers conflict on a material conclusion;
- relevant validation fails or cannot be interpreted;
- a high or critical finding remains unresolved;
- the diff changed materially after the previous review;
- a material dispute remains and the next configured reviewer is still within the classified risk ceiling.

Escalation means a stronger confirmed model/profile or supported reasoning effort. Changing only the prompt, role label, or thread is not a model escalation; report it accurately.

Dispatch the next exact reviewer only after the current reviewer returns its structured result, the root adjudicates every finding, confirmed changes are remediated through the owning TDD/minimality workflow, and affected validation is green. If no configured trigger remains, stop; do not spend another route step merely to seek a higher score. If a trigger remains, advance exactly one available configured step within the classified risk ceiling and give the next reviewer source artifacts rather than the previous conclusion. An unresolved low-, medium-, or high-risk Sol/high review exhausts the route and leaves the task incomplete; it never promotes the diff to the critical-only Sol/xhigh profile.

## Loop bounds

- Run at most one review per unchanged diff and effective tier.
- Run only one reviewer at a time; do not fan out the progressive ladder.
- Follow the resolved ordered route without skipping a configured intermediate step.
- Fix confirmed issues before moving up unless the stronger tier is needed to resolve a conflict.
- Never downgrade below the task's complexity floor.
- Stop escalating when `max_steps`, the distinct configured profiles, or the risk-specific ceiling is exhausted; non-critical review stops at Sol/high and strongest remains critical-only.
- If exact review is unavailable, a root self-review may diagnose gaps but cannot satisfy the review or release gate without a new explicit user override.
- If the highest risk-eligible review still returns blocking issues, keep the milestone or task incomplete and record the blocker.

## Acceptance gate

Accept a milestone only when all are true:

- its primary signal is met;
- relevant validation is green;
- TDD-first work has a meaningful red signal and focused green evidence, or a documented reason why an automated red signal was impractical;
- delegated implementation stayed within one active writer lease and passed independent root diff/validation handoff;
- the minimality decision is evidence-backed and no confirmed avoidable dependency, duplicate implementation, speculative abstraction, or downstream symptom patch remains;
- required version, changelog, and documentation surfaces agree with the reviewed diff and no published tag was rewritten;
- every acceptance criterion is covered by authoritative evidence;
- no confirmed actionable finding remains;
- reviewer confidence and tier satisfy the complexity floor;
- the current diff, not a stale earlier diff, was reviewed.

For every risk, an evidence-backed `ACCEPT` at the current configured step may close the gate when coverage is complete, validation is green, confidence is sufficient, and no configured trigger remains. Critical work uses only a map with `critical_confirmed = true`. If exact profile selection fails, keep the gate incomplete and report the terminal reason.
