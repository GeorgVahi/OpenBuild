# Capability-aware model routing

Use this reference whenever Build delegates repository discovery, log analysis, or review, and always for `$build setup-models`.

## Routing principles

1. Keep the current root agent as orchestrator and decision owner.
2. Route broad repository search to a bounded read-only discovery worker when available; keep decisions, targeted verification, edits, and final synthesis with the root.
3. Use cheaper or faster subagents only when the runtime or confirmed configuration proves their suitability; do not assume savings from a role or model name.
4. Choose models or tiers only from capabilities exposed by the runtime or confirmed configuration.
5. Never rank a model by parsing its name. A model catalog may expose IDs, supported reasoning efforts, a default, or an upgrade path without exposing cost or a complete strength ordering.
6. Never claim that a model changed unless the spawn result, selected profile, or runtime evidence proves it.
7. Preserve a functional root-only fallback.

## Capability order

Use the first supported branch:

1. **Native selector:** the spawn tool accepts a model or tier and the runtime exposes a confirmed ordered ladder.
2. **Configured profiles:** available custom agents explicitly map `openbuild-discovery` and `openbuild-review-*` roles to confirmed models and reasoning efforts.
3. **Reasoning ladder:** one confirmed model supports ordered reasoning efforts suitable for the task.
4. **Role-only:** use a built-in read-heavy `explorer` or reviewer role, but report the model as unknown.
5. **Generic subagent:** send a strict read-only brief; report model and savings as unknown.
6. **Root-only:** perform targeted discovery and label review `self-review, limited`.

Do not block `new`, `refine`, `run`, or `full` merely because a higher branch is unavailable.

## Complexity floor

| Class | Typical scope | Minimum starting review tier | Minimum final tier |
|---|---|---|---|
| `low` | Documentation, copy, or local mechanical work | Fast/economy when proven suitable | Fast/economy |
| `medium` | Contained behavior or refactoring with clear tests | Balanced | Balanced |
| `high` | Cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy | Strong requested | Strong requested; strongest available fallback if tier is unobservable |
| `critical` | Irreversible actions, live infrastructure, secrets, destructive migration, very high blast radius | Strongest requested | Strongest requested; root fallback plus required approvals if tier is unobservable |

Use the highest applicable risk. Discovery can use a cheaper read-only tier than final review, but the root must verify its evidence. When tier metadata is unavailable, request the appropriate depth, use the strongest available fallback, and record the limitation. Do not block completion solely because a model name or tier cannot be observed unless repository or user policy explicitly requires it.

## Delegation contract

Give each explorer or reviewer:

- one bounded objective and repository scope;
- read-only instructions and prohibited actions;
- required evidence format: `path:line`, symbol or route, confirmed fact, relevance;
- a stop condition for sufficient coverage;
- a prohibition on architecture decisions, edits, commits, pushes, secrets, and final user answers.

Keep raw logs and large dumps out of the root context. Aggregate and deduplicate findings before making decisions.

For broad repository search, use the full search-plan, evidence-map, fallback, and root-verification contract in [code discovery](code-discovery.md). Discovery workers and reviewers are separate roles: discovery maps evidence; review evaluates a current diff and acceptance evidence.

## `$build setup-models`

### Preflight

1. Inspect the native spawn schema, discoverable agent roles/profiles, and model catalog when exposed.
2. If native selection already provides a proven ladder, explain it and avoid creating redundant files.
3. If only catalog IDs are available, do not invent an ordering. Use documented `upgrade`, supported reasoning-effort descriptions, runtime tier metadata, or a user-confirmed mapping.
4. Deduplicate tiers that resolve to the same effective model and effort.

### Proposal

Propose up to five roles, collapsing duplicates when fewer distinct tiers exist:

- `openbuild-discovery`: repository search and evidence gathering on the minimum proven suitable read-only model/tier;
- `openbuild-review-fast`: low-risk documentation and mechanical-change review;
- `openbuild-review-balanced`: normal contained changes;
- `openbuild-review-strong`: high-risk or escalated review;
- `openbuild-review-strongest`: critical or final escalated review.

For every role show:

- confirmed model ID and reasoning effort;
- evidence used to assign the tier;
- target file and scope;
- exact TOML content;
- whether a reload or new session is required.

Ask whether configuration should be user-scoped (`~/.codex/agents`) or project-scoped (`.codex/agents`). Then request separate permission before writing.

### Profile shape

Use the runtime-supported custom-agent schema. A typical generated profile is:

```toml
name = "openbuild-review-balanced"
description = "Read-only OpenBuild reviewer for contained changes."
model = "<confirmed-model-id>"
model_reasoning_effort = "<confirmed-supported-effort>"
sandbox_mode = "read-only"
developer_instructions = """
Review only the supplied task diff and specification.
Return evidence-backed findings, acceptance coverage, confidence, and a verdict.
Do not edit files, commit, push, or make product decisions.
"""
```

Do not ship placeholders as active configuration.

### Write boundary

- Show exact proposed files and diff first.
- Require explicit permission for durable configuration writes.
- Never overwrite or silently merge an existing file.
- On collision, propose a unique suffix or an explicit reviewed update.
- Create only read-only profiles.
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
Discovery tier: <observed tier or unknown>
Discovery branches: <objectives and worker count>
Starting review tier: <observed tier or unknown>
Required final tier: <tier based on risk>
Actual escalation: <tier sequence or none>
Limitations: <unavailable selectors, profiles, or independence>
```
