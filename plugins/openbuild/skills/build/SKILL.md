---
name: build
description: "Turn a plain-language idea or an existing BUILD.md, SPEC.md, or TZ.md into a repository-grounded specification, refine it, or execute it through delegated code discovery, TDD-first milestones, version-aware commits, capability-aware subagents, and progressive review. Use only when explicitly invoked as $build for new, refine, run, full, or setup-models workflows; do not invoke for ordinary build commands."
---

# Build

Run one durable workflow from an idea to an evidence-backed specification and, when requested, a reviewed implementation.

## Parse the invocation

Support these explicit modes:

- `$build new <idea>`: discover, interview, and create or update a specification; stop before implementation.
- `$build refine [path]`: verify and improve an existing specification; stop before implementation.
- `$build run [path]`: bring an existing specification to `Ready`, then implement it.
- `$build full <idea-or-path>`: run discovery, specification, implementation, validation, and review.
- `$build setup-models`: configure an optional, permission-gated model ladder for future subagents.
- `$build <idea>`: treat as `full` when no mode is present.

Treat `/build` only as a text alias when a user types it in prose. Do not claim that Build registers a slash command.

Reply and write the specification in the user's language. Keep paths, symbols, commands, and code in their native form.

## Select the specification safely

Use an explicit path when supplied. Otherwise:

1. Prefer a relevant existing `BUILD.md`.
2. Then consider a relevant `SPEC.md` or `TZ.md`.
3. For a new task with no relevant file, create `<project-root>/BUILD.md`.

Before changing an existing candidate, read it and confirm that it belongs to the current task. When several candidates are relevant or a file belongs to another task, ask which file to use or propose a descriptive `BUILD-<name>.md`. Never silently replace an unrelated document.

Read [the specification template](references/spec-template.md) before creating or materially restructuring a specification.

## Apply non-negotiable boundaries

- Obey all applicable `AGENTS.md`, repository policies, sandbox rules, and approval requirements.
- Treat current files and user edits as authoritative. Preserve unrelated changes and exclude them from edits, review, commits, and pushes.
- Keep the root agent as the owner of product questions, architecture, edits, finding adjudication, validation choices, Git, and final synthesis.
- Delegate repository reading, evidence gathering, log triage, and independent review as read-only work. Do not let explorers or reviewers edit, commit, push, or make product decisions.
- Route broad repository search through [code discovery](references/code-discovery.md) before the root performs broad search when a suitable worker is available. Keep targeted verification with the root.
- Keep reviewers read-only. Route confirmed behavioral findings through [the TDD workflow](references/tdd-workflow.md) under root ownership instead of asking a reviewer to edit.
- Before milestone or final commits, follow [versioning](references/versioning.md) when the repository has a version source or release policy.
- Never infer a model's cost or capability from its slug. Report a selected model or tier only when the runtime or confirmed configuration exposes it.
- Never alter user-level or project-level model configuration without showing the exact proposed changes and receiving separate permission.
- In `new` and `refine`, do not edit implementation files, run destructive commands, or begin milestones.
- During `run` and `full`, make milestone commits when Git is available, task changes can be isolated, and repository/user instructions do not forbid commits. Never push without explicit authorization.
- Stop before destructive or irreversible actions, secrets, purchases, live infrastructure, external publication without existing authorization, or material scope expansion.

## Establish the baseline

Before discovery or edits:

1. Find the project root and applicable instructions.
2. Inspect the current Git branch, `HEAD`, staged/unstaged/untracked state, remotes, version/release sources, and available validation entry points.
3. Record a durable review baseline in the specification. For Git, include `branch@SHA` and a concise initial status. For non-Git work, record the in-scope artifact manifest and hashes when practical.
4. Mark pre-existing or unrelated changes as out of scope.
5. On continuation, reread the specification and current project state instead of relying on chat memory.

## Discover repository evidence

Search only areas that can change the decision. Establish:

- current observable behavior and the owning source of truth;
- relevant data, state, request, or event flow;
- contracts, constraints, similar implementations, and compatibility requirements;
- real test and validation commands;
- affected users, data, integrations, security boundaries, and rollout concerns;
- the concrete mismatch between the requested result and the current project.

Read [code discovery](references/code-discovery.md) before file discovery, repository-wide grep, symbol lookup, dependency tracing, route mapping, test/config/schema search, or other broad repository inspection. Create a compact search plan, then use [model routing](references/model-routing.md) to select the first proven capability branch. Prefer a confirmed read-only `openbuild-discovery` profile or minimum sufficient native tier, but never invent the model or savings.

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

For non-trivial work, use fresh read-only passes across the relevant concerns:

- architecture, ownership, and module boundaries;
- user flows, errors, accessibility, and edge cases;
- tests, observability, regressions, and rollback;
- security, privacy, permissions, and data migration;
- performance, concurrency, and external integrations.

Combine related concerns rather than spawning one agent per bullet. Separate confirmed facts, autonomous technical decisions, product choices for the user, and actions requiring new authority.

## Ask only product questions

Ask only unresolved choices that materially change product behavior, UX, data, security, compatibility, cost, or scope. Do not ask for facts available in the repository.

Ask up to five questions per round using simple mutually exclusive options:

```text
1. <question in plain language>
   a) <option and user-visible consequence>
   b) <option and user-visible consequence>
   c) <option and user-visible consequence>
   Recommendation: 1a — <short reason>.

Reply with: 1a 2b 3c. A custom answer is also valid.
```

Put the recommended safe/default choice first. Update the working specification with evidence, decisions, draft acceptance criteria, and open questions before waiting.

## Reach the Ready gate

Require the specification to contain:

- user outcome, scope, and exclusions;
- repository evidence and source of truth;
- user decisions and autonomous technical decisions;
- observable acceptance criteria and invariants;
- failure modes, edge cases, compatibility, security, data, rollout, and rollback concerns;
- complexity class and model-routing mode;
- version source, policy, and expected version impact, or why versioning is not applicable;
- primary signal, validation strategy, coherent milestones, and review plan;
- no blocking product questions.

Run a fresh contradiction and unknown-unknown audit. Add repository facts directly; return to the interview only for a new material product choice.

In `new` or `refine`, set the specification to `Ready`, summarize it, and stop. In `run` or `full`, set it to `Ready` and immediately continue without asking for a second approval unless the user requested a checkpoint.

## Implement milestones

For each milestone:

1. Reconfirm its acceptance criteria, implementation mode, complexity floor, and owning files.
2. For TDD-first work, follow [the TDD workflow](references/tdd-workflow.md): establish the owner and primary signal, run the smallest meaningful red test when practical, then implement the minimum coherent owner-layer change.
3. For Direct or Investigation work, use the narrow signal appropriate to that mode and reclassify before changing behavior.
4. Require focused green validation, refactor only after green when it removes current complexity, then run wider checks according to risk.
5. Review the task diff against the saved baseline and remove unrelated changes.
6. Apply [versioning](references/versioning.md): classify the version impact, update required version/changelog/documentation surfaces in the same commit, and validate their agreement. Use `none` when policy does not require a bump.
7. Run the built-in progressive review described in [the review protocol](references/review-protocol.md) against the complete diff, including versioning changes.
8. Adjudicate every finding. Fix confirmed actionable issues, rerun affected validation, and repeat review whenever remediation or version synchronization changes the reviewed diff.
9. Close the milestone only when its primary signal is met, validation is green, acceptance coverage is complete, and no actionable finding remains.
10. Update milestone status, evidence, review mode/tier, and validation log in the specification.
11. Create a scoped milestone commit when allowed and safe. Do not include unrelated changes and do not push without explicit authorization.

## Run progressive review

Read [the review protocol](references/review-protocol.md) for `run` and `full`.

Build an ordered ladder only from native per-spawn selectors, confirmed custom agent profiles, or supported reasoning-effort tiers. Choose the minimum sufficient starting tier from the complexity class. A discovery tier may be cheaper than the required final review tier.

Use a fresh reviewer context when available. Pass the specification, baseline, current task diff, validation evidence, and acceptance criteria without leaking earlier reviewer conclusions.

Require a structured result containing verdict, confidence, acceptance coverage, evidence-backed findings, observed routing mode/tier, and an optional score. A score below `9.5`, low confidence, incomplete coverage, conflicting reviews, failed validation, unresolved high-impact findings, or a material post-review diff triggers escalation after confirmed findings are handled.

For TDD-first milestones, require the reviewer to audit the red signal, owning layer, focused green result, and risk-based coverage without editing. The root verifies confirmed findings and sends behavioral remediation back through the TDD workflow before the next review cycle.

Treat scores only as escalation signals. Never accept work from a number alone. Bound the loop by the distinct available tiers and do not repeat the same reviewer on an unchanged diff. For high and critical work, request the required strong/strongest final pass even when a cheaper reviewer scores it highly. If the runtime cannot prove tiers, use the strongest available root/reviewer fallback, record `observed tier: unknown`, and evaluate completion from evidence unless project policy explicitly requires a named tier.

If the strongest available reviewer still finds blocking issues, keep the task incomplete and record the exact blocker. Missing tier metadata alone is a disclosed limitation, not an automatic blocker. When no independent reviewer exists, perform sequential self-review and label it `self-review, limited` rather than claiming independence.

## Configure the optional model ladder

For `$build setup-models`, read [model routing](references/model-routing.md) and follow its setup procedure.

First detect whether a native selector already provides a proven ladder. If configuration is useful, inspect only capabilities actually exposed by the runtime. Propose a deduplicated `fast`, `balanced`, `strong`, and `strongest` mapping; show the model/reasoning evidence, target scope, exact file paths, and exact diff.

Ask for separate permission before writing user-level `~/.codex/agents` or project-level `.codex/agents`. Prefer a uniquely named read-only `openbuild-discovery` profile for broad code search plus risk-appropriate `openbuild-review-*` profiles. Never overwrite or silently merge an existing profile. Validate TOML, instruct the user to reload or start a new session, then verify that profiles are actually discoverable before claiming model switching works.

If setup is declined or unsupported, leave zero-config routing fully functional and report the effective fallback mode.

## Complete the workflow

After all milestones:

1. Run relevant end-to-end validation.
2. Review the full task diff against the saved baseline with a fresh reviewer at the minimum final tier.
3. Verify every acceptance criterion with authoritative evidence.
4. Check documentation, version impact, compatibility, migration, rollout/rollback, security, and remaining risks.
5. Fix confirmed gaps and repeat affected checks and review.
6. Set `Complete` only when every requirement is proven. Otherwise preserve the exact status and continue or request missing authority.
7. Update the final specification log and create the final scoped commit when allowed. Push only when explicitly authorized.

Report the outcome, closed milestones, discovery routing/fallback, implementation mode and red/green evidence, version impact and before/after version, acceptance evidence, validation, review mode/tier, commits, documentation status, migration implications, and real remaining risks.
