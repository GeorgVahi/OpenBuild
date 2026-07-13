# Specification readiness and blind-spot protocol

Use this protocol before declaring any specification `Ready`. It turns product discovery and independent critique into a durable, resumable loop without repeatedly asking decisions that the user already made.

## Contents

1. Lifecycle routing
2. Specification source map
3. Coverage model
4. Decision authority and conflict protocol
5. Decision memory and deduplication
6. Decision application gate
7. Adaptive critic loop
8. Critic result
9. Ready gate

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

## Specification source map

Before asking a product question, changing normative specification content, or declaring coverage complete, inventory the complete in-scope specification graph:

- the selected root specification;
- every in-scope document linked, included, or named as a normative source;
- any repository or user-authored decision record that those documents cite as authority;
- the requirements, acceptance criteria, product area, and stable decision IDs each source owns;
- every outgoing normative link/include/name edge and the `path:line` or equivalent discovery evidence used to classify it;
- each source's status/revision, provenance, and whether Build is allowed to edit it.

Read every mapped normative source before synthesizing or restructuring the root. A source map may be marked complete only when every declared normative edge has a mapped target, every mapped source is reachable from the selected root, and each source records evidence that its outgoing references were audited. Initial mapping may record `aligned`, `conflict`, or `gap`; it cannot self-declare `deferred`. Deferral is a post-map reconciliation backed by a matching user decision. A resolved user decision has the same force whether it appears in the root, a linked child document, or an explicit user answer. The source's decision provenance must explicitly list that `D-###`; mere presence of the file is not proof that it owns the decision. Do not infer that the root silently overrides a linked source, that a newer file supersedes an older one, or that Build may rewrite every mapped file. Record missing, unreadable, ambiguously scoped, or contradictory sources as `gap` until evidence or the user resolves them.

Treat current files and manual edits as authoritative evidence. When two mapped sources disagree and neither contains an explicit precedence or supersession record, preserve both statements and route the conflict through the decision authority protocol instead of selecting one during synthesis.

## Coverage model

Create a coverage ledger with stable `B-###` IDs before the first product-question round. Do not renumber or delete rows on later revisions. Add task-specific rows when discovery exposes another material concern.

Use only these row states:

- `gap` — evidence, a decision, or authority is still missing;
- `covered` — the concern is resolved with durable evidence or a linked decision;
- `not applicable` — the concern cannot affect this task, with a recorded reason.

Classify every row disposition as `repository fact`, `technical decision`, `product decision`, or `new authority`. A row remains `gap` until its disposition has evidence and an owner. A `technical decision` disposition is valid only after the decision authority test proves that it preserves all locked product outcomes. Do not mark a row `not applicable` merely because the initial request omitted it.

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

## Decision authority and conflict protocol

OpenBuild is a bridge between user intent and implementation. The user owns every material product decision; the root discovers the choice, explains evidence, risks, and consequences, recommends an option, records the answer, and only then changes the approved product map.

Apply the product-impact test from consequences, not from the critic's label or the file being edited. A choice is user-owned when any option changes observable behavior, UX, eligibility, audience, age/platform/geography availability, permissions, privacy or data lifecycle, monetization/economy/rewards, safety or moderation, legal/platform gates, compatibility, cost, rollout, acceptance criteria, priorities, non-goals, or scope. Architecture/provider choices are also user-owned when they change one of those outcomes or create material lock-in, migration, or operating commitments. When classification is mixed or uncertain, classify it as a user-owned `product decision`.

Repository facts, law, policy, security constraints, and platform contracts can prove an option impossible or require new authority. They do not choose among the remaining viable product outcomes. Explain excluded options and evidence, then let the user select among the viable choices or explicitly defer/remove the affected scope.

An autonomous technical decision is allowed only when all viable technical options preserve every resolved `D-###`, user-authored normative requirement, acceptance criterion, invariant, and observable outcome. Assign it a stable `T-###` ID and record the selected mechanism, evidence, alternatives considered, and preservation proof. If resolving a so-called technical gap would alter a product-impact area, it is not a technical decision.

For each conflict between mapped normative sources:

1. preserve both statements and their provenance;
2. link a semantic duplicate to its existing `D-###`, or create/reopen one stable ID;
3. show the previous or current choice, the new conflict evidence, and why it matters;
4. offer mutually exclusive viable options, including preserve/adapt, change, and defer/remove when applicable;
5. explain user-visible consequences, material risks, and a recommendation;
6. wait for the user's answer before changing the conflicting normative requirements.

Never silently choose the root document, a critic preference, a safer default, a compliance-heavy default, or the easiest implementation. Close each mapped conflict with a structured reconciliation receipt. Its resolution basis must be either (a) an explicit precedence/supersession record whose mapped authority source, record type, governed target, source revision, and positive line number all match the source map, or (b) a specific `D-###`, exact user-answer source, and selected outcome. Free-text evidence, root preference, file date, or critic recommendation cannot change a conflict to `aligned`; deferral also requires a specific matching user decision and cannot originate in the initial map. A resolved choice may be propagated into an inconsistent dependent document without a new question only when the edit demonstrably preserves that exact choice. Any semantic change requires evidence-backed reopening and a new user answer.

## Decision memory and deduplication

Assign every material user-owned product choice a stable `D-###` ID and `Decision key`. Record its owner as `user`, status, selected option, consequence, source, and evidence. Keep autonomous outcome-neutral mechanisms in the separate `T-###` technical decision ledger. Preserve IDs and history across turns and sessions. Keep legacy IDs such as `D-01` instead of renumbering them solely to match the current display format.

Use these states:

- `open` — the user still needs to decide;
- `resolved` — the answer is a locked constraint;
- `reopened` — verified new evidence materially challenges the resolved outcome;
- `superseded` — a later recorded decision replaced it without deleting history.

Before asking a question, compare its actor, trigger, behavior, and user-visible consequence with every existing decision key and coverage row. Treat semantic matches as duplicates even when wording differs. Link a duplicate finding to the existing `D-###`; do not ask it again.

Reopen a resolved decision only when verified new evidence shows a repository constraint, failing signal, upstream contract, user scope change, or material contradiction that prevents the selected outcome. Keep the same `D-###`, record the evidence and revision, and begin the new question by stating the previous choice and what changed. A second user answer cannot overwrite the locked outcome until this explicit `decision-reopened` transition has been recorded; a semantic duplicate leaves the existing decision unchanged. A critic preference, low confidence, or a differently worded alternative is not reopen evidence. When a technical change can preserve the selected product outcome, record it under `T-###` with preservation proof without disturbing the user.

Ask up to five open decisions per round in dependency order. Do not ask a conditional child decision until its parent answer activates that branch; otherwise mark the child concern `not applicable` with the parent decision as evidence. Display the stable decision ID but keep short reply codes:

```text
1. [D-007] <plain-language product question>
   a) <option and user-visible consequence>
   b) <option and user-visible consequence>
   Recommendation: 1a — <short reason>.

Reply with: 1a. A custom answer is also valid.
```

Partial answers resolve only the referenced decisions. Update the same specification before waiting or launching another critic. Never invent a minimum question count: zero or three questions are valid only when the coverage evidence supports them.

## Decision application gate

For normative content that depends on an `open` or `reopened` `D-###`, Build may write only the source map, repository evidence, coverage ledger, decision records, pending proposals, risk register, draft questions, and non-normative audit metadata needed to support the interview. Do not change that dependent normative specification content—scope, non-goals, product behavior, UX, actors, permissions, data policy, monetization, acceptance criteria, product roadmap, milestones, or linked normative files—based on an unanswered choice. An answered independent ID may be applied immediately while unrelated IDs remain open.

After an answer, apply exactly the resolved choice and rebuild every dependent part of the product map. Every normative write captures the authorizing decision version, exact current answer source, and selected outcome at the moment of the write. Record a decision application receipt for the current revision with one structured mapping for every normative decision/target/change tuple:

```text
D-###: <selected outcome and exact answer source>
Target/change: <root or linked file and stable semantic change>
Changed: <sections, requirements, acceptance criteria, milestones>
Preserved: <locked D-### IDs and invariants not changed>
Remaining open: <D-### IDs or none>
```

Every Build-made normative change must cite either a resolved user-owned `D-###` or an existing locked requirement it propagates without semantic change. A `T-###` may justify implementation detail only; it cannot authorize a normative product change. Editorial restructuring and deduplication may proceed autonomously only when meaning is provably unchanged.

Reopening a `D-###` invalidates every prior normative write/application authorization for that ID. Preserve the pre-reopen outcome and complete set of affected `(target, change)` tuples. After the new user answer, rebuild and receipt each tuple separately against the new decision version; applying one target does not authorize the others. A no-op receipt is valid only when the user repeats the exact pre-reopen outcome and explicitly confirms the entire prior tuple set already matches it. Never attach a pre-reopen write to the new answer source or outcome.

If applying an answer exposes another product-impacting choice, record it under a stable `D-###`, leave the affected normative text as a pending proposal, ask another round, and keep the specification in `Questions`. Do not treat the user's answer to one ID as blanket approval for adjacent critic findings or contradictions.

## Adaptive critic loop

Increment `Specification revision` only when semantic specification inputs change: a material user answer, product or technical decision, requirement, acceptance criterion, coverage disposition, scope, or repository evidence that affects the design. Do not increment it for audit metadata that merely records a critic verdict, deduplication/adjudication with no semantic change, timestamps, status transitions, validation results, writer leases, milestone progress, or execution logs. A closure verdict remains bound to the semantic revision it evaluated until one of those semantic inputs changes. Do not launch a critic while waiting for the user.

For every non-trivial specification revision:

1. Complete repository discovery and the root's first coverage pass.
2. Spawn a fresh read-only specification critic with the current specification, repository evidence, acceptance criteria, decision memory, and coverage ledger. Do not pass raw conclusions from earlier critics.
3. Require the critic to challenge coverage, identify only net-new gaps or evidence-backed reopen requests, and avoid product or architecture decisions.
4. Let the root verify repository facts, deduplicate semantic keys, assign durable IDs, reject unsupported findings, apply the product-impact test, and resolve only outcome-neutral `T-###` technical decisions.
5. Present every remaining open product decision as a decision packet, wait for the user, apply answered IDs through the decision application gate, increment the revision, and run the next required fresh pass.
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
  Decision authority: <repository fact | user D-### | outcome-neutral technical T-### | external authority>

Reopen requests:
- D-### — <new evidence, contradiction, and changed consequence>

Duplicate/resolved references:
- <finding> -> <existing B-### or D-###>
```

Critics do not ask the user directly, allocate final IDs, edit files, change architecture, or decide product behavior. The root owns adjudication and the user-facing interview.

## Ready gate

Set `Ready` only when all conditions hold for the current specification revision:

- the specification source map is complete and every mapped normative source was reconciled or explicitly deferred by the user;
- every coverage ledger row is `covered` or `not applicable` with evidence;
- no `gap`, blocking product decisions (open or reopened), material contradiction, or missing new authority remains;
- every critic finding and reopen request is linked, deduplicated, and adjudicated;
- every Build-made normative change is traceable to a resolved `D-###` or a locked requirement propagated without semantic change;
- the latest normative edits are covered by a decision application receipt with no remaining open IDs;
- every normative write and application receipt is bound to the current decision version, answer source, and selected outcome;
- every `T-###` includes preservation proof and has no normative product effect;
- acceptance criteria are observable and cover the selected outcomes and failure behavior;
- the risk-appropriate critic depth and a fresh closure verdict of `COVERED` are recorded for the current revision;
- route, implementation milestones, validation, rollback, and review plans are coherent with the final decisions.

Treat this as evidence-backed closure of the defined and task-specific concern model, not a claim of literal omniscience. When implementation later reveals a material product gap, pause the milestone, add or reopen only the affected ledger and decision IDs, rerun the required closure pass, and then resume.
