# Progressive review protocol

Use this protocol for every `run` and `full` milestone and for the final task diff.

## Inputs

Provide the reviewer with:

- the current specification and acceptance criteria;
- the saved review baseline;
- the exact task diff, including committed milestone changes and relevant uncommitted work;
- validation commands and current results;
- the requested review tier and the evidence supporting that tier;
- the repository path and explicit read-only boundary.

Use a fresh context when available. Do not reveal earlier reviewer conclusions; pass source artifacts instead.

## Required result

Ask for this structure:

```text
Review mode: independent | self-review-limited
Routing mode: native-selector | configured-profiles | reasoning-ladder | role-only | generic-subagent | root-only
Requested tier: fast | balanced | strong | strongest | unknown
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

Escalation recommendation:
- <next tier and trigger, or none>
```

A finding without concrete evidence, impact, and an actionable owning-layer fix is not sufficient by itself.

## Score semantics

The optional score is a secondary escalation signal, not the completion gate.

- `9.5-10.0`: no known actionable gap and strong evidence coverage.
- `8.0-9.4`: credible improvement, uncertainty, or incomplete coverage remains.
- below `8.0`: material correctness, safety, or acceptance gaps remain.

Do not force a reviewer to invent a score when the runtime does not support calibrated scoring. Do not make cosmetic changes merely to raise a number.

## Root adjudication

For every finding, the root agent must:

1. Reproduce or verify the evidence.
2. Decide whether it is task-scoped and actionable.
3. Fix confirmed findings in the owning layer.
4. Reject hypothetical, duplicate, style-only, or pre-existing out-of-scope findings with a recorded reason.
5. Rerun affected validation.

Reviewers do not edit, commit, push, expand scope, or make product decisions.

## Escalation triggers

After adjudication and remediation, move one proven tier higher when any trigger remains:

- score is below `9.5`;
- confidence is low;
- acceptance coverage is incomplete or based on weak evidence;
- reviewers conflict on a material conclusion;
- relevant validation fails or cannot be interpreted;
- a high or critical finding remains unresolved;
- the diff changed materially after the previous review;
- the task's complexity floor requires a stronger final tier.

Escalation means a stronger confirmed model/profile or supported reasoning effort. Changing only the prompt, role label, or thread is not a model escalation; report it accurately.

## Loop bounds

- Run at most one review per unchanged diff and effective tier.
- Fix confirmed issues before moving up unless the stronger tier is needed to resolve a conflict.
- Never downgrade below the task's complexity floor.
- Stop escalating when distinct proven tiers are exhausted.
- If subagents are unavailable, run one root self-review and label it `self-review, limited`.
- If the strongest available review still returns blocking issues, keep the milestone or task incomplete and record the blocker.

## Acceptance gate

Accept a milestone only when all are true:

- its primary signal is met;
- relevant validation is green;
- every acceptance criterion is covered by authoritative evidence;
- no confirmed actionable finding remains;
- reviewer confidence and tier satisfy the complexity floor;
- the current diff, not a stale earlier diff, was reviewed.

For `high` and `critical` work, a high score from a cheaper reviewer never replaces an available strong or strongest final pass. If tier selection is unavailable, use the strongest available root/reviewer fallback, disclose `observed tier: unknown`, and rely on evidence, validation, and applicable approval policy rather than fabricating or automatically failing a tier claim.
