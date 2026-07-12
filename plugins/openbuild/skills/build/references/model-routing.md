# Capability-aware model routing

Use this reference whenever Build delegates repository discovery, specification critique, implementation, log analysis, or review, and always for `$build setup-models`.

## Routing principles

1. Keep the current root agent as orchestrator and decision owner.
2. Route every repository search to a bounded read-only worker mapped to a confirmed separate usage pool before spending the main model pool. Keep decisions, targeted reads of already-known files, durable specification/version edits, validation, Git, and final synthesis with the root.
3. When the separate pool is unavailable, route search to the minimum proven suitable main-pool model with low or minimal supported reasoning before using the root.
4. Choose models or tiers only from capabilities exposed by the runtime or confirmed configuration.
5. Never rank a model by parsing its name. A model catalog may expose IDs, supported reasoning efforts, a default, or an upgrade path without exposing cost or a complete strength ordering.
6. Never claim that a model changed unless the spawn result, selected profile, or runtime evidence proves it.
7. Preserve functional read-only and root-orchestration fallbacks; do not use an unproven model for code edits.
8. Keep search workers, specification critics, and reviewers read-only. Route code edits to a risk-matched Implementation worker under the same Ready, TDD, minimality, single-writer, validation, and review gates in [adaptive implementation delegation](implementation-delegation.md).

## Search usage-pool order

Use this order before any repository grep, file/symbol lookup, dependency trace, route/test/config/schema search, or log scan:

1. **Separate usage pool:** use a native selector or `openbuild-search-separate` profile whose exact model-to-pool mapping is confirmed by current official product guidance, runtime metadata, or the user. The current Spark preview is an example when the account/runtime exposes it; do not hard-code that example as a universal model ID.
2. **Efficient main-pool fallback:** use `openbuild-search-fallback` or a native main-pool model confirmed suitable for read-heavy work, with the lowest supported reasoning effort that can satisfy the search brief.
3. **Role-only fallback:** use a built-in read-heavy `explorer`; report the model and usage pool as unknown.
4. **Generic subagent fallback:** send a strict read-only search brief; report model, pool, and savings as unknown.
5. **Root fallback:** perform only the minimum targeted search needed to unblock the task and record that main-context usage was unavoidable.

Attempt the separate-pool route once before the first search branch. If the runtime reports quota exhaustion, model/profile unavailability, or an unsupported capability, open a circuit breaker for the current Build run and use the next branch without retrying the same failed route for every grep. Reset it only on a new Build invocation, verified runtime-state change, or explicit user instruction. Do not scrape or infer remaining quota from the private usage dashboard; record only the selected profile/model and an observed runtime/quota result.

Do not block `new`, `refine`, `run`, `full`, or `auto` merely because the separate pool is unavailable. Do not silently skip it when a confirmed route exists.

Official Codex guidance documents a separate usage limit for the Spark preview and supports per-agent `model` and `model_reasoning_effort` configuration. Keep exact model assignments dynamic because availability and model names can change: [Codex pricing and usage limits](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan), [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning).

## Critic and review capability order

For specification critics and diff reviewers, use the first supported native selector, configured `openbuild-review-*` profile, confirmed reasoning ladder, reviewer role, generic read-only subagent, or root self-review. Apply the complexity floor below; search-pool priority does not lower the reasoning depth required to adjudicate product, architecture, security, or code correctness.

## Complexity floor

| Class | Typical scope | Minimum starting review tier | Minimum final tier |
|---|---|---|---|
| `low` | Documentation, copy, or local mechanical work | Fast/economy when proven suitable | Fast/economy |
| `medium` | Contained behavior or refactoring with clear tests | Balanced | Balanced |
| `high` | Cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy | Strong requested | Strong requested; strongest available fallback if tier is unobservable |
| `critical` | Irreversible actions, live infrastructure, secrets, destructive migration, very high blast radius | Strongest requested | Strongest requested; root fallback plus required approvals if tier is unobservable |

Use the highest applicable risk. Discovery can use a cheaper read-only tier than final review, but the root must verify its evidence. When tier metadata is unavailable, request the appropriate depth, use the strongest available fallback, and record the limitation. Do not block completion solely because a model name or tier cannot be observed unless repository or user policy explicitly requires it.

## Delegation contract

Give each explorer, specification critic, or reviewer:

- one bounded objective and repository scope;
- read-only instructions and prohibited actions;
- required evidence format: `path:line`, symbol or route, confirmed fact, relevance;
- a stop condition for sufficient coverage;
- a prohibition on architecture decisions, edits, commits, pushes, secrets, and final user answers.

Keep raw logs and large dumps out of the root context. Aggregate and deduplicate findings before making decisions.

For broad repository search, use the full search-plan, evidence-map, fallback, and root-verification contract in [code discovery](code-discovery.md). Discovery workers, specification critics, and reviewers are separate read-only roles: discovery maps repository evidence; critics challenge specification coverage; review evaluates a current diff and acceptance evidence. `openbuild-review-*` profiles may serve as fresh specification critics with a critic-specific brief and the current decision/coverage ledger.

## Implementation worker routing

Choose an Implementation worker only after the current specification revision passes the Ready gate. Classify the milestone before every lease and select the minimum sufficient proven coding tier:

- `openbuild-implementation-fast` for low-risk Direct documentation, cosmetic, or mechanical work with no behavior change;
- `openbuild-implementation-balanced` for medium-risk contained logic or refactoring with clear contracts and supported tests;
- `openbuild-implementation-strongest` for high-risk cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy, or sensitive state, and for critical work at the deepest supported effort.

Prefer exact native custom-agent selection or the configured profile for the selected tier. The root may use `root-only` only when its effective model satisfies that tier. A built-in worker or generic bounded subagent may edit only when configuration or runtime evidence supports the same tier. Never infer suitability, strength, cost, or pool from a model slug.

Never use `openbuild-search-separate`, `openbuild-search-fallback`, legacy `openbuild-discovery`, or `openbuild-review-*` profiles for code edits. Select `root-only`, `bounded-worker`, or `sequential-workers` from milestone ownership, overlap, dirty-state safety, risk, and validation evidence; never run concurrent writers in one checkout.

Pass only the milestone, baseline, allowed files, acceptance criteria, red or primary signal, focused green command, and stop conditions defined in [adaptive implementation delegation](implementation-delegation.md). The root independently verifies the returned diff and validation before review or Git actions.

**Escalate only on evidence.** Move from fast to balanced or balanced to strong/strongest when scope or risk increases, the selected agent reports insufficient confidence, the red/green signal exposes a deeper owner-layer problem, validation fails for a task-scoped reason, or review confirms an actionable gap. Do not fan out or escalate merely because a stronger model exists, and never repeat an unchanged task at the same tier.

Missing model/tier metadata alone does not block low or medium implementation when the exact named profile is configured, the requested selection and sandbox are recorded, and no runtime evidence contradicts it. Record observed fields as `unknown` or `unobservable`; do not claim a model switch or savings. High work still requires a confirmed strong route, and critical work requires the strongest proven route plus applicable approvals. When the required tier cannot be selected, stop before every test or production code edit and record the exact limitation rather than silently lowering the risk floor.

## `$build setup-models`

### Preflight

1. Inspect the native spawn schema, discoverable agent roles/profiles, and model catalog when exposed.
2. Identify whether current official guidance, runtime metadata, or the user confirms a separate-usage search model for this account/surface. Do not infer pool membership from a model slug alone.
3. Identify proven fast, balanced, and strong/strongest coding tiers plus the minimum efficient main-pool search fallback.
4. If native selection already provides every proven route, explain it and avoid creating redundant files.
5. If only catalog IDs are available, do not invent usage-pool membership or strength ordering. Use official product guidance, documented `upgrade`, supported reasoning-effort descriptions, runtime tier metadata, or a user-confirmed mapping.
6. Deduplicate roles that resolve to the same effective model, effort, sandbox, and usage pool.

### Proposal

Propose up to nine roles, collapsing duplicates when fewer distinct routes exist:

- `openbuild-search-separate`: all repository search and evidence gathering on a confirmed separate usage pool, read-only;
- `openbuild-search-fallback`: the minimum proven suitable main-pool search model with low/minimal supported reasoning, read-only;
- `openbuild-implementation-fast`: a proven efficient coding route for low-risk Direct work, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild-implementation-balanced`: a proven balanced coding route for medium-risk contained behavior, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild-implementation-strongest`: a proven strong/strongest coding route for high or critical work, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild-review-fast`: low-risk documentation and mechanical-change review;
- `openbuild-review-balanced`: normal contained changes;
- `openbuild-review-strong`: high-risk or escalated review;
- `openbuild-review-strongest`: critical or final escalated review.

Treat an existing `openbuild-discovery` profile as a legacy search route. Use it first only when its model and separate-pool mapping are explicitly confirmed; otherwise place it at the appropriate fallback branch. The review profiles also support risk-matched fresh specification-closure passes and remain read-only.

For every role show:

- confirmed model ID and reasoning effort;
- evidence used to assign the tier;
- confirmed usage pool (`separate`, `main`, or `unknown`) and source of that claim;
- sandbox mode and whether the role may edit;
- target file and scope;
- exact TOML content;
- whether a reload or new session is required.

Ask whether configuration should be user-scoped (`~/.codex/agents`) or project-scoped (`.codex/agents`). Then request separate permission before writing.

### Profile shape

Use the runtime-supported custom-agent schema. Typical generated profiles are:

```toml
name = "openbuild-search-separate"
description = "Read-only OpenBuild code search routed to a separately metered usage pool."
model = "<confirmed-separate-usage-model-id>"
model_reasoning_effort = "<lowest-confirmed-suitable-effort>"
sandbox_mode = "read-only"
developer_instructions = """
Perform repository search and evidence mapping only.
Return compact path:line findings, negative results, confidence, and the observed search result.
Do not edit, decide architecture/product behavior, commit, push, or answer the user.
"""
```

```toml
name = "openbuild-implementation-<fast|balanced|strongest>"
description = "Risk-matched OpenBuild coding worker for one bounded single-writer lease."
model = "<confirmed-model-id-for-the-tier>"
model_reasoning_effort = "<tier-appropriate-supported-effort>"
sandbox_mode = "workspace-write"
developer_instructions = """
Edit only the files leased by the root for one Ready milestone.
Follow the supplied acceptance criteria and red/green signal; stop for product, architecture, scope, authority, or overlap changes.
Do not edit the specification/version, stage, commit, push, publish, or deploy.
"""
```

Generate review profiles with `sandbox_mode = "read-only"` and the specification/diff-review instructions already defined by this workflow.

Do not ship placeholders as active configuration.

### Write boundary

- Show exact proposed files and diff first.
- Require explicit permission for durable configuration writes.
- Never overwrite or silently merge an existing file.
- On collision, propose a unique suffix or an explicit reviewed update.
- Keep search and review profiles read-only. Create each `openbuild-implementation-fast`, `openbuild-implementation-balanced`, and `openbuild-implementation-strongest` profile with `workspace-write` only after separately showing its exact scope and receiving permission.
- Validate TOML after writing.
- Ask for reload or a new session, then verify the roles are discoverable.
- Until verification succeeds, report setup as configured but unverified.
- Never commit personal model IDs or generated profiles to OpenBuild itself.

## Routing record

Record this for each run or milestone:

```text
Complexity: <low|medium|high|critical> — <evidence>
Routing mode: <native-selector|configured-profiles|reasoning-ladder|role-only|generic-subagent|root-only>
Discovery mode: <delegated|mixed|root-fallback>
Search usage route: <separate-pool|main-efficient|role-only|generic-subagent|root-fallback>
Search model/tier: <observed value or unknown>
Separate-pool attempt: <used|unavailable|not configured; evidence and circuit-breaker state>
Discovery branches: <objectives and worker count>
Readiness critic depth: <perspectives, tiers, closure revision, and fallback>
Implementation delegation: <root-only|bounded-worker|sequential-workers|blocked; requested writer profile/tier, observed value or unknown, escalation, and exact blocker if any>
Writer-route evidence: <official/runtime/config/user mapping, exact requested profile, selection evidence, and limitations>
Starting review tier: <observed tier or unknown>
Required final tier: <tier based on risk>
Actual escalation: <tier sequence or none>
Limitations: <unavailable selectors, profiles, or independence>
```
