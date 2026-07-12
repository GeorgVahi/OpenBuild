# Specification readiness and blind-spot protocol

Use this protocol before declaring any specification `Ready`. It turns product discovery and independent critique into a durable, resumable loop without repeatedly asking decisions that the user already made.

## Contents

1. Lifecycle routing
2. Coverage model
3. Decision memory and deduplication
4. Adaptive critic loop
5. Critic result
6. Ready gate

## Lifecycle routing

Separate the workflow target from the first incomplete phase.

- `new` and `refine` target `Ready` and stop before implementation.
- `run` and `full` target `Complete`.
- `auto`, including a bare invocation, infer the target from explicit user intent; default a feature idea to `Complete`, but honor an explicit request for specification-only work.
- An explicit mode or path always wins over inference.

Select the first incomplete phase from repository and specification evidence:

| Evidence | Start phase |
|---|---|
| No relevant specification | discovery |
| `Draft`, `Questions`, or repository/spec mismatch | reconciliation |
| Open product decision | interview |
| Legacy `Ready`, closed decisions but incomplete coverage, or no current closure pass | blind-spot critique; bootstrap or reconcile the ledger first |
| `Ready` with current closure evidence | stop for a specification-only target; otherwise implement |
| `In progress` | implementation; run a delta-audit before the earliest incomplete milestone |
| `Complete` | verification; revalidate the full acceptance set, current repository and task diff, focused and risk-based signals, documentation/version, security, migration, rollout/rollback, and review evidence; then no-op, resume the earliest invalid phase, or create a new task specification |

Record `Workflow target`, `Starting phase`, route evidence, and confidence in the specification. Treat a legacy `Ready` document without the current coverage ledger as needing reconciliation, not as implementation-ready. When several candidate files or materially different targets remain plausible, ask one routing question instead of guessing.

## Coverage model

Create a coverage ledger with stable `B-###` IDs before the first product-question round. Do not renumber or delete rows on later revisions. Add task-specific rows when discovery exposes another material concern.

Use only these row states:

- `gap` — evidence, a decision, or authority is still missing;
- `covered` — the concern is resolved with durable evidence or a linked decision;
- `not applicable` — the concern cannot affect this task, with a recorded reason.

Classify every row disposition as `repository fact`, `technical decision`, `product decision`, or `new authority`. A row remains `gap` until its disposition has evidence and an owner. Do not mark a row `not applicable` merely because the initial request omitted it.

Cover at least these semantic areas, combining rows only when one piece of evidence genuinely resolves them together:

- outcome, success signal, scope, and non-goals;
- actors, roles, permissions, and abuse boundaries;
- primary, alternate, empty, loading, error, cancel, retry, and recovery flows;
- accessibility, localization, responsive behavior, and user-visible compatibility;
- ownership, module boundaries, contracts, and source of truth;
- data validation, lifecycle, schema, migration, retention, and deletion;
- security, privacy, sensitive data, and trust boundaries;
- performance, capacity, concurrency, ordering, and idempotency;
- integrations, timeouts, offline behavior, and partial failure;
- observability, support, rollout, rollback, and release documentation;
- acceptance criteria, testability, minimality, cost, and operational limits.

Store each discovered gap under a stable semantic key such as `permissions.guest-write` or `data.retry-idempotency`. Use that key to detect the same gap when a later critic describes it with different words.

## Decision memory and deduplication

Assign every material product choice a stable `D-###` ID and `Decision key`. Record its owner, status, selected option, consequence, source, and evidence. Preserve IDs and history across turns and sessions. Keep legacy IDs such as `D-01` instead of renumbering them solely to match the current display format.

Use these states:

- `open` — the user still needs to decide;
- `resolved` — the answer is a locked constraint;
- `reopened` — verified new evidence materially challenges the resolved outcome;
- `superseded` — a later recorded decision replaced it without deleting history.

Before asking a question, compare its actor, trigger, behavior, and user-visible consequence with every existing decision key and coverage row. Treat semantic matches as duplicates even when wording differs. Link a duplicate finding to the existing `D-###`; do not ask it again.

Reopen a resolved decision only when verified new evidence shows a repository constraint, failing signal, upstream contract, user scope change, or material contradiction that prevents the selected outcome. Keep the same `D-###`, record the evidence and revision, and begin the new question by stating the previous choice and what changed. A critic preference, low confidence, or a differently worded alternative is not reopen evidence. When a technical change can preserve the selected product outcome, make and record that technical decision without disturbing the user.

Ask up to five open decisions per round in dependency order. Do not ask a conditional child decision until its parent answer activates that branch; otherwise mark the child concern `not applicable` with the parent decision as evidence. Display the stable decision ID but keep short reply codes:

```text
1. [D-007] <plain-language product question>
   a) <option and user-visible consequence>
   b) <option and user-visible consequence>
   Recommendation: 1a — <short reason>.

Reply with: 1a. A custom answer is also valid.
```

Partial answers resolve only the referenced decisions. Update the same specification before waiting or launching another critic. Never invent a minimum question count: zero or three questions are valid only when the coverage evidence supports them.

## Adaptive critic loop

Increment `Specification revision` only when semantic specification inputs change: a material user answer, product or technical decision, requirement, acceptance criterion, coverage disposition, scope, or repository evidence that affects the design. Do not increment it for audit metadata that merely records a critic verdict, deduplication/adjudication with no semantic change, timestamps, status transitions, validation results, writer leases, milestone progress, or execution logs. A closure verdict remains bound to the semantic revision it evaluated until one of those semantic inputs changes. Do not launch a critic while waiting for the user.

For every non-trivial specification revision:

1. Complete repository discovery and the root's first coverage pass.
2. Spawn a fresh read-only specification critic with the current specification, repository evidence, acceptance criteria, decision memory, and coverage ledger. Do not pass raw conclusions from earlier critics.
3. Require the critic to challenge coverage, identify only net-new gaps or evidence-backed reopen requests, and avoid product or architecture decisions.
4. Let the root verify repository facts, deduplicate semantic keys, assign durable IDs, reject unsupported findings, and resolve autonomous technical decisions.
5. Ask the user only the remaining open product decisions, update the same specification, increment its revision, and run the next required fresh pass.
6. Continue until the current revision satisfies the Ready gate.

Use risk-adaptive depth:

| Complexity | Required readiness depth |
|---|---|
| `low` | structured root self-audit; use one generalist critic when the change is non-trivial |
| `medium` | one fresh balanced critic and a fresh closure pass after material answers |
| `high` | two complementary critics covering product/UX and architecture/data/security, plus a strong closure pass |
| `critical` | three complementary adversarial perspectives, the strongest available closure pass, and any required authority checkpoint |

Run at most one pass for an unchanged tuple of `(specification revision, perspective, effective tier)`. Do not repeat a duplicate-only or no-progress pass at the same tuple. Move to an unused perspective or proven tier, adjudicate findings, or request the missing decision or authority. Repeat a full exploration wave only when scope or risk materially expands; otherwise run only the required closure pass after changes.

If independent critics are unavailable, perform sequential separated root-perspective passes matching the required depth and label each `self-review, limited`: one generalist for non-trivial low work; one balanced generalist for medium, followed by a fresh closure pass after material answers; two complementary product/UX and architecture/data/security passes plus a separate closure pass for high; and three complementary adversarial passes plus a closure pass for critical. Rebuild each perspective from the specification and evidence instead of copying the previous conclusion. Missing model/tier metadata alone does not block the workflow, but missing required perspective coverage does. Do not erase gaps or fabricate independence. If all available independent or root-fallback perspectives are exhausted while a gap remains, keep the specification out of `Ready` and record the exact blocker.

## Critic result

Require this structure:

```text
Specification revision: <R#>
Perspective: <product-ux | architecture-data-security | reliability-validation | generalist>
Requested/observed tier: <value or unknown>
Verdict: COVERED | GAPS
Confidence: high | medium | low

Coverage:
- B-###: covered | not applicable | gap — <evidence or challenge>

New gaps:
- NEW:<concern>:<semantic-key> — <repository fact | technical decision | product decision | new authority>
  Evidence: <path:line, contract, scenario, or explicit missing evidence>
  Impact: <observable consequence>

Reopen requests:
- D-### — <new evidence, contradiction, and changed consequence>

Duplicate/resolved references:
- <finding> -> <existing B-### or D-###>
```

Critics do not ask the user directly, allocate final IDs, edit files, change architecture, or decide product behavior. The root owns adjudication and the user-facing interview.

## Ready gate

Set `Ready` only when all conditions hold for the current specification revision:

- every coverage ledger row is `covered` or `not applicable` with evidence;
- no `gap`, blocking product decisions (open or reopened), material contradiction, or missing new authority remains;
- every critic finding and reopen request is linked, deduplicated, and adjudicated;
- acceptance criteria are observable and cover the selected outcomes and failure behavior;
- the risk-appropriate critic depth and a fresh closure verdict of `COVERED` are recorded for the current revision;
- route, implementation milestones, validation, rollback, and review plans are coherent with the final decisions.

Treat this as evidence-backed closure of the defined and task-specific concern model, not a claim of literal omniscience. When implementation later reveals a material product gap, pause the milestone, add or reopen only the affected ledger and decision IDs, rerun the required closure pass, and then resume.
