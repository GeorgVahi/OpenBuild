---
name: build
description: "Turn a plain-language idea or an existing BUILD.md, SPEC.md, or TZ.md into a repository-grounded specification, iteratively close product and architecture blind spots without repeating resolved decisions, or execute it through automatic phase routing, separate-usage-pool-first code search, risk-matched model implementation, bounded writers, TDD-first milestones, evidence-gated minimality, version-aware commits, and progressive review. Use only when explicitly invoked as the standalone $build skill or a namespaced plugin skill such as $openbuild:build; do not invoke for ordinary build commands."
---

# Build

Run one durable workflow from an idea to an evidence-backed specification and, when requested, a reviewed implementation.

## Parse the invocation

Support these explicit modes. The examples use standalone `$build`; plugin users apply the same mode suffix to `$openbuild:build` or the namespace assigned by their marketplace:

- `$build new <idea>`: discover, interview, and create or update a specification; stop before implementation.
- `$build refine [path]`: verify and improve an existing specification; stop before implementation.
- `$build run [path]`: bring an existing specification to `Ready`, then implement it.
- `$build full <idea-or-path>`: run discovery, specification, implementation, validation, and review.
- `$build auto <idea-or-path>`: infer the workflow target and start at the first incomplete phase.
- `$build setup-models`: configure an optional, permission-gated model ladder for future subagents.
- `$build <idea-or-path>`: treat as `auto` when no mode is present.

Do not claim that Build registers `/build` or any other slash command. If a user types `/build` in prose, explain the supported explicit skill invocation instead of silently treating it as an installed command.

Reply and write the specification in the user's language. Keep paths, symbols, commands, and code in their native form.

## Initialize search routing

Before locating a specification, repository instructions, validation entry points, files, symbols, tests, routes, schemas, configs, logs, or similar implementations, read [code discovery](references/code-discovery.md) and [model routing](references/model-routing.md) from their already-known skill paths. Inspect the runtime's native selectors and discoverable profiles without searching the repository, select the first available search branch, and initialize the separate-pool circuit-breaker state for this Build run.

Before the first non-trivial repository lookup, follow this explicit delegation instruction: Spawn the custom agent named `openbuild-search-separate`. Do so before the root runs `rg`, `rg --files`, file/symbol lookup, or an equivalent search command. When the callable spawn schema exposes a direct model selector, bind the confirmed separate-pool model there; otherwise select the configured custom agent by its exact name. A generic subagent, a descriptive task name, or a prompt that merely mentions the profile is not proof that the profile was selected. Do not begin the lookup until the exact dispatch succeeds or returns an allowed fallback reason, and emit the search routing receipt defined by the discovery protocol.

Route every repository lookup used by specification selection, baseline discovery, reconciliation, implementation, or review through that order. Direct root reads are allowed only for an explicit user-supplied path, a runtime-provided path, an already-known skill/reference path, or a returned `path:line`; any new file/symbol/grep lookup returns to the search route. Git metadata commands such as branch, status, and `HEAD` inspection remain root-owned and are not code search.

## Select the specification safely

Use an explicit path when supplied and verify that it exists before `refine`, `run`, or path-based `auto`. Otherwise:

1. Prefer a relevant existing `BUILD.md`.
2. Then consider a relevant `SPEC.md` or `TZ.md`.
3. For `new`, `full`, or `auto` with a new idea, create `<project-root>/BUILD.md` when no relevant file exists.

For `refine` or `run`, stop and request a valid path when no relevant specification exists or a supplied explicit path does not exist. Before changing an existing candidate, read it and confirm that it belongs to the current task. When several candidates are relevant or a file belongs to another task, ask which file to use or propose a descriptive `BUILD-<name>.md`. Never silently replace an unrelated document.

Read [the specification template](references/spec-template.md) before creating or materially restructuring a specification.

Read [the specification readiness protocol](references/blindspot-protocol.md), then record the workflow target and first incomplete phase. Explicit modes and paths override inference. A legacy `Ready` file without the current decision memory, coverage ledger, and closure evidence returns to readiness audit before implementation.

## Apply non-negotiable boundaries

- Obey all applicable `AGENTS.md`, repository policies, sandbox rules, and approval requirements.
- Treat current files and user edits as authoritative. Preserve unrelated changes and exclude them from edits, review, commits, and pushes.
- Keep the root agent as the owner of product questions, architecture, specification and version edits, finding adjudication, validation choices, Git, and final synthesis. Lease implementation edits only through [adaptive implementation delegation](references/implementation-delegation.md).
- Keep search workers, specification critics, and reviewers read-only. Permit only the selected risk-matched implementation worker to edit its leased file set; it never makes product or architecture decisions, changes the specification/version, or controls Git.
- Allow only one active writer in the shared workspace. The root does not edit while a worker lease is active, and multiple implementation workers run sequentially with a root handoff gate between them.
- Route every repository lookup through [code discovery](references/code-discovery.md) and its separate-pool-first order. Keep only direct reads of explicit, runtime-provided, or already-known `path:line` targets with the root.
- Keep reviewers read-only. Route confirmed behavioral findings through [the TDD workflow](references/tdd-workflow.md) under root ownership instead of asking a reviewer to edit.
- Before milestone or final commits, follow [versioning](references/versioning.md). In a versioned repository, give every Build-created commit a unique higher version unless an applicable repository policy explicitly defines a different release-only scheme.
- Never infer a model's cost or capability from its slug. Report a selected model or tier only when the runtime or confirmed configuration exposes it.
- Never alter user-level or project-level model configuration without showing the exact proposed changes and receiving separate permission.
- In `new`, `refine`, and specification-targeted `auto`, do not edit implementation files, run destructive commands, or begin milestones.
- During `run`, `full`, and implementation-targeted `auto`, make milestone commits when Git is available, task changes can be isolated, and repository/user instructions do not forbid commits. Never push without explicit authorization.
- Never print or commit secret values, tokens, passwords, cookies, private keys, customer data, raw `.env` contents, or credential-bearing remote URLs. Inspect only the metadata needed for the task and redact credentials from durable specifications, logs, reviews, and reports.
- Stop before destructive or irreversible actions, secrets, purchases, live infrastructure, external publication without existing authorization, or material scope expansion.

## Establish the baseline

Before discovery or edits:

1. Find the project root and applicable instructions.
2. Inspect the current Git branch, `HEAD`, staged/unstaged/untracked state, remotes, version/release sources, and available validation entry points.
3. Record a durable review baseline in the specification. For Git, include `branch@SHA` and a concise initial status. For non-Git work, record the in-scope artifact manifest and hashes when practical. On continuation of the same task, preserve the original baseline instead of replacing it with the latest milestone.
4. Mark pre-existing or unrelated changes as out of scope.
5. On continuation, reread the specification and current project state instead of relying on chat memory. If the original baseline is absent, recover it from the parent of the first identifiable task commit when evidence permits; otherwise record the earliest verifiable boundary and the resulting review limitation.

## Discover repository evidence

Search only areas that can change the decision. Establish:

- current observable behavior and the owning source of truth;
- relevant data, state, request, or event flow;
- contracts, constraints, similar implementations, and compatibility requirements;
- real test and validation commands;
- affected users, data, integrations, security boundaries, and rollout concerns;
- the concrete mismatch between the requested result and the current project.

Read [code discovery](references/code-discovery.md) before any repository grep, file discovery, symbol lookup, dependency tracing, route mapping, test/config/schema search, or log scan. Create a compact search plan, then use [model routing](references/model-routing.md): dispatch the exact confirmed separate-usage search agent first, fall back to the minimum suitable main-pool model at low/minimal supported reasoning only after an allowed recorded failure, and use root search only when worker routes are unavailable. Never invent pool membership, quota, model switching, strength, or savings.

Delegate independent search branches when useful. Require a compact evidence map with `path:line`, symbol or route, confirmed fact, relevance, negative results, and confidence. Aggregate and deduplicate the map, then let the root perform targeted verification. Give each branch a task-appropriate time and attempt budget. A short parent polling timeout is not a completed worker failure. Fall back when the platform reports unavailability/quota/failure, the declared budget is exceeded, or two completed attempts return unusable evidence; record the actual mode instead of waiting indefinitely.

## Classify the implementation mode

Before implementation, assign and record one mode using [the TDD workflow](references/tdd-workflow.md):

- `Direct` for documentation, cosmetic, or obvious local edits without behavior changes;
- `Investigation` while the root cause or owning layer is unclear;
- `TDD-first` for behavior, logic, contracts, auth or permissions, persistence, routing, state, concurrency, integrations, security, or non-trivial user-visible changes.

Do not force a failing test for Direct work. Reclassify Investigation work to TDD-first before changing behavior.

## Classify complexity and risk

Assign `low`, `medium`, `high`, or `critical` before implementation and record the reasons in the specification. Use the highest applicable risk, not an average.

- `low`: documentation, copy, styling, or a local mechanical change without behavior changes.
- `medium`: contained logic or refactoring with clear contracts and supported tests.
- `high`: cross-layer behavior, public contracts, persistence, concurrency, authentication, authorization, privacy, or sensitive state/data flow.
- `critical`: irreversible changes, live infrastructure, secrets or permissions, destructive migrations, or very high blast radius.

Authentication, permissions, secrets, persistence, migrations, concurrency, and public contracts set a conservative minimum tier. Reclassify when discovery or the diff expands scope.

## Audit blind spots

Follow [the specification readiness protocol](references/blindspot-protocol.md). Build a durable coverage ledger, decision memory with stable IDs, and a risk-adaptive fresh critic loop for every non-trivial specification. Treat critic findings as candidates: the root verifies evidence, resolves repository and technical gaps, deduplicates semantic matches, and asks only remaining product choices.

## Ask only product questions

Ask only open or evidence-backed reopened decisions that materially change product behavior, UX, data, security, compatibility, cost, or scope. Do not ask for facts available in the repository or repeat a resolved decision under different wording.

Ask up to five questions per round using simple mutually exclusive options:

```text
1. <question in plain language>
   a) <option and user-visible consequence>
   b) <option and user-visible consequence>
   c) <option and user-visible consequence>
   Recommendation: 1a — <short reason>.

Reply with: 1a 2b 3c. A custom answer is also valid.
```

Show each stable `D-###` ID, put the recommended safe/default choice first, and keep the reply format short. Update the same specification with evidence, decision state, coverage, draft acceptance criteria, and open questions before waiting. Partial answers close only their referenced IDs.

## Reach the Ready gate

Require the specification to contain:

- workflow target, starting phase, and current specification revision;
- user outcome, scope, and exclusions;
- repository evidence and source of truth;
- durable user decisions and autonomous technical decisions with stable IDs and reopen history;
- a complete evidence-backed coverage ledger and adjudicated critic log;
- observable acceptance criteria and invariants;
- failure modes, edge cases, compatibility, security, data, rollout, and rollback concerns;
- complexity class and model-routing mode;
- version source, policy, and expected version impact, or why versioning is not applicable;
- primary signal, validation strategy, coherent milestones, and review plan;
- no gaps, blocking product decisions, contradictions, or missing authority.

Require the risk-appropriate critic depth and a fresh `COVERED` closure verdict for the current specification revision. Do not claim literal omniscience; require closure across every defined and task-specific concern with evidence or a justified `not applicable` disposition.

In `new`, `refine`, or specification-targeted `auto`, set the specification to `Ready`, summarize it, and stop. In `run`, `full`, or implementation-targeted `auto`, set it to `Ready` and immediately continue unless the user requested a checkpoint or the risk/authority policy requires one.

## Implement milestones

For each milestone:

1. Reconfirm its acceptance criteria, implementation mode, complexity floor, and owning files.
2. Read and apply [the minimality protocol](references/minimality-protocol.md) before the first code change. Record which rung is selected, what complexity is skipped, and any known ceiling with its observable upgrade trigger.
3. Select `root-only`, `bounded-worker`, or `sequential-workers` through [adaptive implementation delegation](references/implementation-delegation.md). Route every test and production code edit to the risk-matched writer tier: fast for low-risk Direct work, balanced for medium contained behavior, and strong/strongest for high or critical work. Keep one active writer, preserve the same TDD/minimality/validation gates at every tier, and record requested profile, observed metadata or `unknown`, evidence, escalation, and lease. Escalate only on task evidence; if the required risk tier cannot be selected, stop rather than lower the risk floor.
4. For TDD-first work, follow [the TDD workflow](references/tdd-workflow.md): establish the owner and primary signal, run the smallest meaningful red test when practical, then implement the minimum coherent owner-layer change.
5. For Direct or Investigation work, use the narrow signal appropriate to that mode and reclassify before changing behavior.
6. After every worker handoff, let the root verify the complete diff and rerun focused validation independently.
7. Require focused green validation, refactor only after green when it removes current complexity, then run wider checks according to risk.
8. Review the task diff against the saved baseline. Revert only accidental out-of-scope edits made by Build during this task; leave pre-existing or user-owned unrelated changes untouched and exclude them from review and commits.
9. Apply [versioning](references/versioning.md): classify the version impact, update required version/changelog/documentation surfaces in the same commit, and validate their agreement. Use `not applicable` only when there is no authoritative version source or no commit will be created.
10. Run the built-in progressive review described in [the review protocol](references/review-protocol.md) against the complete diff, including versioning changes.
11. Adjudicate every finding. Fix confirmed actionable issues, rerun affected validation, and repeat review whenever remediation or version synchronization changes the reviewed diff.
12. Close the milestone only when its primary signal is met, validation is green, acceptance coverage is complete, and no actionable finding remains.
13. Update milestone status, evidence, delegation, review mode/tier, and validation log in the specification.
14. Create a scoped milestone commit when allowed and safe. Do not include unrelated changes and do not push without explicit authorization.

## Run progressive review

Read [the review protocol](references/review-protocol.md) for `run`, `full`, and implementation-targeted `auto`.

Build an ordered ladder only from native per-spawn selectors, confirmed custom agent profiles, or supported reasoning-effort tiers. Choose the minimum sufficient starting tier from the complexity class. A discovery tier may be cheaper than the required final review tier.

Use a fresh reviewer context with history inheritance disabled when the runtime supports it, such as `fork_turns: "none"` or an equivalent `fork_context: false`. If isolation controls are unavailable, disclose that the context may be inherited and do not claim full independence. Pass the specification, preserved original baseline, current full task diff, validation evidence, and acceptance criteria without leaking earlier reviewer conclusions.

Require a structured result containing verdict, confidence, acceptance coverage, evidence-backed findings, observed routing mode/tier, and an optional score. Low confidence, incomplete coverage, conflicting reviews, failed validation, unresolved high-impact findings, or a material post-review diff triggers escalation after confirmed findings are handled. A score below `9.5` triggers escalation only when the reviewer ties it to a concrete finding, uncertainty, or coverage gap.

For TDD-first milestones, require the reviewer to audit the red signal, owning layer, focused green result, and risk-based coverage without editing. The root verifies confirmed findings and sends behavioral remediation back through the TDD workflow before the next review cycle.

Treat scores only as secondary escalation signals. An evidence-backed `ACCEPT` with green validation, complete acceptance coverage, sufficient confidence, and no actionable findings is enough even when an optional score is omitted or below `9.5` without a concrete gap. Never accept work from a number alone. Bound the loop by the distinct available tiers and do not repeat the same reviewer on an unchanged diff. For high and critical work, request the required strong/strongest final pass even when a cheaper reviewer scores it highly. If the runtime cannot prove tiers, use the strongest available root/reviewer fallback, record `observed tier: unknown`, and evaluate completion from evidence unless project policy explicitly requires a named tier.

If the strongest available reviewer still finds blocking issues, keep the task incomplete and record the exact blocker. Missing tier metadata alone is a disclosed limitation, not an automatic blocker. When no independent reviewer exists, perform sequential self-review and label it `self-review, limited` rather than claiming independence.

## Configure the optional model ladder

For `$build setup-models`, read [model routing](references/model-routing.md) and follow its setup procedure.

First detect whether native custom-agent routing already provides a confirmed separate-usage search route, an efficient main-pool search fallback, fast/balanced/strong implementation tiers, and a review ladder. If configuration is useful, inspect only capabilities actually exposed by the runtime and current official/user-confirmed pool evidence. Propose deduplicated role mappings; show model, reasoning effort, usage pool, sandbox, target scope, exact file paths, and exact diff.

Ask for separate permission before writing user-level `~/.codex/agents` or project-level `.codex/agents`. Prefer read-only `openbuild-search-separate` and `openbuild-search-fallback`; write-capable `openbuild-implementation-fast`, `openbuild-implementation-balanced`, and `openbuild-implementation-strongest`; and risk-appropriate read-only `openbuild-review-*` profiles. Show each writer's exact `workspace-write` boundary separately. Never overwrite or silently merge an existing profile. Validate TOML, instruct the user to reload or start a new session, then verify discoverability. Treat configured profile evidence separately from observed runtime model/pool metadata.

If setup is declined or unsupported, leave search, specification, and read-only review operational through honest zero-config fallbacks. Low or medium implementation may continue only through a configured or observed route that satisfies its selected tier; missing metadata alone is recorded as `unknown` rather than a universal blocker. Keep high or critical implementation blocked when its required strong/strongest route cannot be selected.

## Complete the workflow

After all milestones:

1. Run relevant end-to-end validation.
2. Review the full task diff against the saved baseline with a fresh reviewer at the minimum final tier.
3. Verify every acceptance criterion with authoritative evidence.
4. Check documentation, version impact, compatibility, migration, rollout/rollback, security, and remaining risks.
5. Fix confirmed gaps and repeat affected checks and review.
6. Set `Complete` only when every requirement is proven. Otherwise preserve the exact status and continue or request missing authority.
7. Update the final specification log and create the final scoped commit when allowed. Push only when explicitly authorized.

Report the outcome, workflow route, specification revision and critic closure, preserved/reopened decisions, closed milestones, search usage route and circuit breaker, requested implementation profile/tier, observed model metadata or `unknown`, escalation and delegation, red/green evidence, minimality decisions, version impact and before/after version, acceptance evidence, validation, review mode/tier, commits, documentation status, migration implications, and real remaining risks.
