---
name: build
description: "Turn a plain-language idea or an existing BUILD.md, SPEC.md, or TZ.md into a repository-grounded specification, map linked normative sources, close blind spots through user-owned product decisions without repeating resolved choices, or execute it through automatic phase routing, separate-usage-pool-first code search, risk-matched model implementation, bounded writers, TDD-first milestones, evidence-gated minimality, version-aware commits, and progressive review. Use only when explicitly invoked as the standalone $build skill or a namespaced plugin skill such as $openbuild:build; do not invoke for ordinary build commands."
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
- `$build setup-models`: configure the permission-gated profiles used by explicit-model Codex CLI agents.
- `$build <idea-or-path>`: treat as `auto` when no mode is present.

Do not claim that Build registers `/build` or any other slash command. If a user types `/build` in prose, explain the supported explicit skill invocation instead of silently treating it as an installed command.

Reply and write the specification in the user's language. Keep paths, symbols, commands, and code in their native form.

## Explicit Code Discovery Delegation

OpenBuild implements code discovery only through `scripts/agent_runner.py` and the immutable packaged `openbuild_search_separate` profile. Before broad `rg`, route/symbol lookup, owner mapping, or cross-file evidence gathering, start and activate that profile as a separate subscription-authenticated Codex process pinned to `gpt-5.3-codex-spark`, low reasoning, and read-only sandbox.

Delegate repository search, `rg`, `Get-Content`, and local file reading to that process. Require only a compact evidence map with `path:line`, symbol/route, snippet/signature, and why it matters. Do targeted main-process reads only after its accepted terminal result.

Do not call a native Explorer or any other agent API for discovery. If the exact runner cannot start or finishes with invalid evidence, create no replacement agent: record the normalized failure and continue only with the minimum targeted root search needed to unblock the task. A trivial lookup or already-known path may be read directly.

## Initialize search routing

Before locating a specification, repository instructions, validation entry points, files, symbols, tests, routes, schemas, configs, logs, or similar implementations, read [code discovery](references/code-discovery.md) and [model routing](references/model-routing.md) from their already-known skill paths and initialize the exact-runner circuit-breaker state for this Build run.

Before the first non-trivial repository lookup, start the custom agent named `openbuild_search_separate` through the packaged `scripts/agent_runner.py` launcher. It resolves only the immutable packaged profile and starts `codex exec -m <model> -c model_reasoning_effort=<effort>`. Do so before the root runs `rg`, `rg --files`, file/symbol lookup, or an equivalent search command. Pass the canonical profile ID through `--agent` and an independent descriptive label through `--task-name`. Do not begin the lookup until the exact dispatch succeeds or records a terminal failure; after failure, create no replacement agent and use only the disclosed targeted root route.

Route every repository lookup used by specification selection, baseline discovery, reconciliation, implementation, or review through that order. Direct root reads are allowed only for an explicit user-supplied path, a runtime-provided path, an already-known skill/reference path, or a returned `path:line`; any new file/symbol/grep lookup returns to the search route. Git metadata commands such as branch, status, and `HEAD` inspection remain root-owned and are not code search.

## Run explicit-model agents

Before the first exact CLI dispatch, perform an OS-aware dependency checkpoint. On Windows, run `python --version`. On POSIX, run `python3 --version` first and use `python --version` only as a fallback. Run `codex --version` on every platform. Require Python 3.11 or newer. If either dependency is missing or too old, stop before creating an agent. Only on Windows, show the exact commands `winget install -e --id Python.Python.3.12` and `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"`. On POSIX, provide manual, platform-appropriate Python and Codex CLI installation guidance without choosing or running a package manager. Offer either manual installation followed by a user reply or execution of an applicable displayed command only after separate explicit permission. Wait for installation and rerun the OS-appropriate Python check plus `codex --version`, then ask the user to run `codex`, complete ChatGPT sign-in manually, and verify `codex login status`; never automate credentials. If installation or authentication is declined or unavailable, record the checkpoint failure and use only an honest supported fallback.

After that preflight, resolve `<build-skill-root>` from this selected skill's on-disk path, write one bounded UTF-8 prompt file per task, and start the selected role without shell interpolation:

```text
<python-3.11+> <build-skill-root>/scripts/agent_runner.py start --agent <exact-profile> --task-name <independent-label> --repo <workspace-root> --prompt-file <prompt-file>
# Persist the returned ready/running receipt before releasing the task prompt.
<python-3.11+> <build-skill-root>/scripts/agent_runner.py activate --run-dir <returned-run-dir>
```

The launcher requires saved ChatGPT authentication, forces the built-in OpenAI provider plus ChatGPT login method, rejects user-level provider/base-URL redirects, strips ambient API-key/base-URL variables, resolves project profiles before user profiles, and records the exact `-m`, `model_reasoning_effort`, sandbox, creation-bound worker/Codex process identities, JSONL, stderr, final-message, and `codex-exit.json` paths in its private run directory. `start` launches Codex with stdin held, returns the unactivated running receipt, and cannot release the task prompt; only the later explicit `activate` does that. It supplies the profile contract as developer instructions and mechanically disables the stable `features.multi_agent` capability, so repository/global delegation rules cannot recursively spawn a child. Start independent read-only branches separately when useful; keep implementation workers sequential under the single-writer lease.

The runner creates each absent run directory with mode `0700` on POSIX or a protected current-user-only DACL on Windows and rejects an existing directory with weaker ownership/permissions. It uses precise OS creation identities (Windows process handle time, Linux proc start ticks, or macOS microsecond start time), refuses process-group signalling after PID reuse, distinguishes zombie-only POSIX groups from executing descendants before reaping, and treats a failed start-receipt write as a startup failure that must clean up the unactivated process tree before returning control. A private marker is persisted before Codex `Popen` and upgraded with the creation identity before readiness; a spawn attempt without creation-bound stopped evidence is unconfirmed and cannot authorize fallback. Success or cancellation recovery requires a `codex-exit.json` record bound to the dispatched Codex PID/creation identity with exit code zero; missing, malformed, or identity-mismatched exit evidence carries a null/unknown code instead of a synthetic integer.

Poll each returned run directory with `agent_runner.py status --run-dir <path>` while keeping the user informed. `wait` is available for bounded automation, but a short parent timeout is non-terminal: do not recover, release a writer lease, or start another writer while either PID remains active. When interruption is required, run `agent_runner.py cancel --run-dir <path>` and proceed only after its receipt confirms the process tree stopped. Preserve the unactivated running receipt, record matching activation, then record the terminal receipt before consuming evidence. Accept a result only when the receipt reports `status: completed`, `dispatch_method: codex-exec-explicit-model`, the configured model and reasoning effort, a Codex PID/thread ID, terminal event `turn.completed`, a creation-bound Codex exit code of zero, a valid non-empty result, and a root-verified task outcome. A transport-success result that reports inability to complete the task is a failed handoff. A non-zero CLI exit, malformed JSONL, `turn.failed`, missing terminal event, model/quota error, ChatGPT-auth failure, sandbox mismatch, or semantic failure stops that agent route and uses the phase-specific safe recovery without creating another agent.

## Maintain the agent activity ledger

Append one durable row when Build actually creates any search, critic, implementation, or review agent through the exact runner. Count logical runs, not operating-system processes: a wrapper and its child `codex exec` are one logical run. Pre-spawn dispatch failures do not increment the created-run count; list them separately when they changed routing. Once created, a run remains visible when its result is unusable, cancelled, or timed out.

For every created run record its role and task, actual model and reasoning effort from the exact runner receipt, terminal and semantic outcome, a short factual description of completed work, and its AC, milestone, or specification-section mapping (or `none`). A pre-spawn failure is listed separately and does not create a ledger row. Keep PID, thread/run paths, raw prompts, logs, token/usage values, and authentication details out of the user-facing ledger and final answer.

## Select the specification safely

Use an explicit path when supplied and verify that it exists before `refine`, `run`, or path-based `auto`. Otherwise:

1. Prefer a relevant existing `BUILD.md`.
2. Then consider a relevant `SPEC.md` or `TZ.md`.
3. For `new`, `full`, or `auto` with a new idea, create `<project-root>/BUILD.md` when no relevant file exists.

For `refine` or `run`, stop and request a valid path when no relevant specification exists or a supplied explicit path does not exist. Before changing an existing candidate, read it and confirm that it belongs to the current task. When several candidates are relevant or a file belongs to another task, ask which file to use or propose a descriptive `BUILD-<name>.md`. Never silently replace an unrelated document.

Read [the specification template](references/spec-template.md) before creating or materially restructuring a specification.

Read [the specification readiness protocol](references/blindspot-protocol.md), then record the workflow target and first incomplete phase. Explicit modes and paths override inference. A legacy `Ready` file without the current decision memory, coverage ledger, and closure evidence returns to readiness audit before implementation.

Before the first product question or material restructuring, build the specification source map required by the readiness protocol. Inventory the selected root document and every in-scope normative file it links to, includes, or names as a companion; read those sources, record every outgoing normative edge with discovery evidence, record their authority and decision provenance, and preserve resolved choices found anywhere in that graph. The map is complete only when every edge target is mapped and every source is reachable from the root. Do not assume that the root file overrides a linked specification. An unreadable, ambiguous, or conflicting normative source remains a gap.

## Apply non-negotiable boundaries

- Obey all applicable `AGENTS.md`, repository policies, sandbox rules, and approval requirements.
- Treat current files and user edits as authoritative. Preserve unrelated changes and exclude them from edits, review, commits, and pushes.
- Keep the root agent as the owner of the interview, recommendations, evidence verification, outcome-neutral technical decisions, specification and version edits after the applicable decision gate, finding adjudication, validation choices, Git, and final synthesis. The user owns material product decisions and architecture/provider choices that cross the product-impact boundary. Lease implementation edits only through [adaptive implementation delegation](references/implementation-delegation.md).
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

Read [code discovery](references/code-discovery.md) before any repository grep, file discovery, symbol lookup, dependency tracing, route mapping, test/config/schema search, or log scan. Create a compact search plan, then use [model routing](references/model-routing.md): dispatch the exact packaged search agent first. If it fails, create no replacement agent and use only the minimum targeted root search needed to unblock the task. Never invent pool membership, quota, model switching, strength, or savings.

Put independent search branches into the single exact worker's bounded prompt when useful. Require a compact evidence map with `path:line`, symbol or route, confirmed fact, relevance, negative results, and confidence. Aggregate and deduplicate the map, then let the root perform targeted verification. Give the exact run a task-appropriate time and single-attempt budget. A short parent polling timeout is not a completed worker failure. After a confirmed terminal failure, confirmed cancellation at the declared budget, or a semantically unusable result, create no second discovery attempt and transition directly to targeted root recovery.

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

Follow [the specification readiness protocol](references/blindspot-protocol.md). Build a complete specification source map, durable coverage ledger, user decision memory with stable `D-###` IDs, outcome-neutral technical decision ledger with stable `T-###` IDs, and a risk-adaptive fresh critic loop for every non-trivial specification. Treat critic findings and their labels only as candidates: the root verifies evidence, applies the product-impact test, resolves repository facts and only outcome-neutral technical gaps, deduplicates semantic matches, and asks the user about every remaining material choice.

## Protect user decision authority

The user owns any choice that crosses the product-impact boundary by changing observable product behavior, UX, eligibility or audience, age/platform/geography availability, permissions, privacy or data lifecycle, monetization/economy/rewards, safety/moderation/legal gates, compatibility, cost, rollout, acceptance criteria, or scope. The same rule applies to an architecture or provider choice when it changes those outcomes or creates material lock-in. Repository, legal, security, and platform evidence may rule out an impossible option or change the recommendation, but it does not authorize the root to choose a remaining product outcome.

Classify a decision as autonomous technical work only when it selects an implementation mechanism that preserves every resolved `D-###`, user-authored requirement, acceptance criterion, invariant, and observable outcome. Record it as `T-###` with that preservation evidence. If the classification is mixed or uncertain, treat it as a user-owned `D-###`. A critic's `technical decision` label is never sufficient authority by itself.

When normative sources conflict, preserve each source and its provenance, link the conflict to an existing `D-###` or create a new open one, and ask the user. Never silently prefer the root document, the critic recommendation, the safer default, or the easiest implementation. A conflict may close without a new question only when an already-mapped authority record explicitly names the precedence/supersession relation, target, revision, and line. Initial source mapping cannot self-declare a user deferral. A resolved decision may be propagated to inconsistent dependent documents only when the edit preserves that exact decision; changing it requires evidence-backed reopening and a new user answer.

## Ask product questions before normative edits

Ask only open or evidence-backed reopened decisions that cross the product-impact boundary. Do not ask for facts available in the repository or repeat a resolved decision under different wording. A later answer cannot replace a locked `D-###` until the same ID has an explicit `decision-reopened` transition with evidence.

Ask up to five questions per round using simple mutually exclusive options:

```text
1. [D-###] <question in plain language>
   Context: <current requirement or conflict and its source>
   a) <option and user-visible consequence>
   b) <option and user-visible consequence>
   c) <option and user-visible consequence>
   Risks: <material risk or trade-off for the options>
   Affected product map: <requirements, specifications, acceptance criteria, or milestones likely to change>
   Recommendation: 1a — <short reason>.

Reply with: 1a 2b 3c. A custom answer is also valid.
```

Show each stable `D-###` ID, the current decision or conflict provenance, mutually exclusive options, user-visible consequences, material risks, the affected product-map areas, and a reasoned recommendation; put the recommended choice first and keep the reply format short. Before waiting, update only the specification source map, evidence, coverage, open/reopened decision records, pending proposals, risk register, and question log. Do not change normative specification content—requirements, scope, non-goals, product behavior, UX, permissions, data policy, monetization, acceptance criteria, roadmap, milestones, or linked normative files—on the basis of an open or reopened decision. Partial answers close only their referenced IDs.

After the user answers, apply exactly the resolved `D-###` choices across the root and dependent specifications, then rebuild the affected product map, requirements, acceptance criteria, and milestones. Record a decision application receipt mapping each applied ID to its exact current answer source and selected outcome, changed files/sections/criteria, preserved decisions, and remaining open IDs. A reopened decision invalidates the prior write/application authorization for that ID and requires fresh application of every previously affected target/change tuple. A user-confirmed no-op is valid only when the user repeats the pre-reopen outcome and the receipt covers that entire tuple set. If application or a later critic exposes another product-impacting choice, start another interview round and keep the status at `Questions`; do not silently resolve it or advance to `Ready`.

## Reach the Ready gate

Require the specification to contain:

- workflow target, starting phase, and current specification revision;
- user outcome, scope, and exclusions;
- repository evidence, a complete specification source map, and source of truth;
- durable user-owned `D-###` decisions and outcome-neutral `T-###` technical decisions with provenance and reopen history;
- a complete evidence-backed coverage ledger and adjudicated critic log;
- observable acceptance criteria and invariants;
- failure modes, edge cases, compatibility, security, data, rollout, and rollback concerns;
- complexity class and model-routing mode;
- version source, policy, and expected version impact, or why versioning is not applicable;
- primary signal, validation strategy, coherent milestones, and review plan;
- a current decision application receipt for every Build-made normative change after the latest answer;
- no gaps, blocking product decisions, contradictions, missing authority, or unapproved normative changes.

Require the risk-appropriate critic depth and a fresh `COVERED` closure verdict for the current specification revision. Do not claim literal omniscience; require closure across every defined and task-specific concern with evidence or a justified `not applicable` disposition.

In `new`, `refine`, or specification-targeted `auto`, set the specification to `Ready`, summarize the applied and preserved decisions, and stop. In `run`, `full`, or implementation-targeted `auto`, set it to `Ready` and immediately continue only after the decision authority and application gates pass, unless the user requested a checkpoint or the risk/authority policy requires one.

## Implement milestones

For each milestone:

1. Reconfirm its acceptance criteria, implementation mode, complexity floor, and owning files.
2. Read and apply [the minimality protocol](references/minimality-protocol.md) before the first code change. Record which rung is selected, what complexity is skipped, and any known ceiling with its observable upgrade trigger.
3. Select `root-only`, `bounded-worker`, or `sequential-workers` through [adaptive implementation delegation](references/implementation-delegation.md). For a bounded writer, validate the exact profile, acquire and record the single-writer lease, then `start` that risk-matched writer tier through `scripts/agent_runner.py`: `openbuild_implementation_fast` for low, `openbuild_implementation_balanced` for medium, and `openbuild_implementation_strongest` for high or critical. Record the unactivated `running` receipt before calling `activate`; then record its lease/run-bound `implementation-agent-activated` event before the first edit. The worker receives no task prompt and cannot edit before activation. Keep the lease active through every worker edit, then require `codex-exec-explicit-model`, terminal `turn.completed`, creation-bound exit code zero, valid result evidence, and semantic task success in the final receipt before recording the run-bound `implementation-handoff-accepted` event, consuming the result, and releasing the lease. A matching failed/cancelled terminal receipt with complete independent exit/result failure evidence and a confirmed stopped process tree permits lease release but keeps the milestone incomplete and forbids accepted handoff or another writer route. Pass the exact canonical ID through `agent_name` and a separate descriptive `task_name`. Keep one active writer, preserve the same TDD/minimality/validation gates at every tier, and record requested profile, concrete model/effort evidence, escalation, and lease. Escalate only on task evidence; if the required risk tier cannot be selected, stop rather than lower the risk floor.
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

Build an ordered ladder from the canonical profiles and run each reviewer only through `scripts/agent_runner.py` as `codex-exec-explicit-model`. Dispatch the exact starting reviewer from risk: `openbuild_review_fast` for low, `openbuild_review_balanced` for medium, `openbuild_review_strong` for high, and `openbuild_review_strongest` for critical. Persist the unactivated `running` Review routing receipt, call `activate`, record the matching `review-agent-activated` event, and consume the result only after a stopped terminal receipt proves `turn.completed`, creation-bound exit code zero, valid result evidence, and a semantically completed review with unchanged route/process identities. Exact review failure blocks the review/release gate; root self-review may diagnose but cannot close it without a new explicit user override.

Run reviewers strictly sequentially from the risk floor through `fast → balanced → strong → strongest`. Stop on an evidence-backed `ACCEPT` with sufficient confidence, complete coverage, green validation, and no actionable finding. Move exactly one proven tier higher only when a concrete trigger remains after root adjudication, TDD/minimality remediation, and affected green validation. Never fan out reviewers, skip a proven intermediate tier, repeat a tier on an unchanged diff, or let a reviewer edit.

Use a fresh reviewer context with history inheritance disabled when the runtime supports it, such as `fork_turns: "none"` or an equivalent `fork_context: false`. If isolation controls are unavailable, disclose that the context may be inherited and do not claim full independence. Pass the specification, preserved original baseline, current full task diff, validation evidence, and acceptance criteria without leaking earlier reviewer conclusions.

Require a structured result containing verdict, confidence, acceptance coverage, evidence-backed findings, observed routing mode/tier, and an optional score. Low confidence, incomplete coverage, conflicting reviews, failed validation, unresolved high-impact findings, or a material post-review diff triggers escalation after confirmed findings are handled. A score below `9.5` triggers escalation only when the reviewer ties it to a concrete finding, uncertainty, or coverage gap.

For TDD-first milestones, require the reviewer to audit the red signal, owning layer, focused green result, and risk-based coverage without editing. The root verifies confirmed findings and sends behavioral remediation back through the TDD workflow before the next review cycle.

Treat scores only as secondary escalation signals. An evidence-backed `ACCEPT` with green validation, complete acceptance coverage, sufficient confidence, and no actionable findings is enough even when an optional score is omitted or below `9.5` without a concrete gap. Never accept work from a number alone. Bound the loop by the distinct available tiers and do not repeat the same reviewer on an unchanged diff. For high and critical work, require the exact strong/strongest final pass even when a cheaper reviewer scores it highly. If the runtime cannot prove the required exact tier, keep the review and release gate incomplete.

If the strongest required reviewer still finds blocking issues, keep the task incomplete and record the exact blocker. A root self-review may diagnose failures but never substitutes for the required exact reviewer or claims independence.

## Configure the optional model ladder

For `$build setup-models`, read [model routing](references/model-routing.md) and follow its setup procedure.

First verify the Codex CLI, saved ChatGPT authentication, the fixed packaged Spark search route, and the explicit-model runner, then inspect only capabilities actually exposed by the runtime and current official/user-confirmed evidence. Configure optional overrides for the packaged fast/balanced/strong implementation tiers and review ladder used by `codex-exec-explicit-model`. Propose deduplicated role mappings; show model, reasoning effort, sandbox, target scope, exact file paths, and exact diff. Detect supported legacy hyphenated OpenBuild profile names and follow the guided migration contract in [model routing](references/model-routing.md); canonical creation and later legacy cleanup require separate displayed plans and permissions.

Ask for separate permission before writing user-level `~/.codex/agents` or project-level `.codex/agents`. Never write or migrate a same-named `openbuild_search_separate` profile because the runner reserves that ID for its packaged Spark contract. Canonical project/user profiles may override packaged implementation/review defaults. Show each writer's exact `workspace-write` boundary separately, never overwrite or silently merge an existing profile, validate TOML, and require an explicit launcher smoke with a semantically successful result.

If setup is declined, keep the packaged defaults unchanged. If an override or packaged route cannot be selected and complete semantically through the exact runner, apply the phase-specific blocked or targeted-root recovery rule; never create an unverified replacement agent.

## Complete the workflow

After all milestones:

1. Run relevant end-to-end validation.
2. Review the full task diff against the saved baseline with a fresh reviewer at the minimum final tier.
3. Verify every acceptance criterion with authoritative evidence.
4. Check documentation, version impact, compatibility, migration, rollout/rollback, security, and remaining risks.
5. Fix confirmed gaps and repeat affected checks and review.
6. Set `Complete` only when every requirement is proven. Otherwise preserve the exact status and continue or request missing authority.
7. Update the final specification log and agent activity ledger, then create the final scoped commit when allowed. Push only when explicitly authorized.

Report the outcome, workflow route, specification revision and critic closure, specification source map, asked/resolved/preserved/reopened decisions, decision application receipt, closed milestones, search usage route and circuit breaker, requested implementation profile/tier, exact runner model/effort evidence or a pre-spawn failure, escalation and delegation, red/green evidence, minimality decisions, version impact and before/after version, acceptance evidence, validation, review mode/tier, commits, documentation status, migration implications, and real remaining risks.

End every completed Build response with a concise localized agent section. Use `Agents` for an English response and `Агенты` for a Russian response. State the number of actually created logical agent runs, list pre-spawn dispatch failures separately, and include one table row per ledger run with `Role/task`, `Actual model/effort`, `Status/outcome`, `Work`, and `AC/milestone/spec mapping`. Every created-agent row comes from an exact runner receipt; never invent missing model evidence.
