# Model-map interview

Use this protocol only for `$build configure-models` and the backward-compatible `$build setup-models` alias. Its purpose is to turn the user's preferences into one complete, validated routing map without requiring the user to understand profile files or runner internals.

## Conversation rules

- Speak in the user's language and explain every choice in plain language.
- Ask one to three questions per message. Do not dump the full questionnaire at once.
- Put the recommended option first, label it `Recommended`, explain the practical trade-off in one sentence, and always allow a custom answer.
- Adapt later questions to earlier answers. Skip only questions made irrelevant by a previous answer, and show what was skipped in the final preview.
- Separate facts from guesses. Use only available model evidence from the runtime, current official guidance, existing exact profiles, or explicit user confirmation.
- Never infer speed, quality, strength, price, or a separate usage pool from a model slug alone.
- Do not write configuration during the interview. Collect answers, show the exact diff, and require explicit permission at the end.
- A partial interview does not change active routing. The existing complete project, user, or packaged map remains effective.

## What the interview configures

The interview covers Discovery, Specification critics, Implementation, Review, and Critical work. It assigns the exact `model` and `reasoning effort` behind canonical profiles, then builds an ordered route for every use case. Every non-discovery use case must cover low, medium, high, and critical risk.

Each route records:

- which exact profile tries the task first;
- the ordered next profiles, if any;
- `max_steps`, equal to the number of profiles in that sequence;
- the allowed `escalation_triggers` for moving exactly one step;
- whether a clean semantic result stops the route;
- the fixed failure and sandbox policies.

The safety envelope is not customizable: search/critic/review stay read-only, implementation stays under a single-writer lease, transport failure is `block`, implementation escalation is `semantic-before-edit`, and only discovery may use the model-map `targeted-root` fallback. Every non-critical map route is a contiguous segment of its risk-specific reasoning-first ladder: it may start higher only before Sol, cannot skip a reasoning rung, and cannot contain the critical-only `strongest` profile. A non-critical route never starts on Sol/high; every critical route is exactly the direct `strongest` profile with `critical_confirmed = true`. Each canonical implementation/review profile override also declares its exact `routing_rung` and `routing_tuple_confirmed = true`. A known Luna/Terra/Sol model-and-effort tuple must equal that rung; an unknown custom tuple is allowed only with an explicitly user-confirmed rung and a successful exact capability smoke, never by inference from the model name. Automatic safe same-scope root-completion is not configurable here and uses existing authority; only a separate new owner-private implementation checkpoint recovery writer requires terminal full-tree zero proof plus explicit user opt-in. A model-map choice never authorizes destructive, external, secret-bearing, or live-infrastructure action.

## Block 0 — Current state and scope

Inspect the effective map and exact profiles without printing secrets. Report whether each value comes from project, user, or packaged configuration.

Ask:

1. Where should the new map apply?
   - **This project (Recommended)** — saves `.codex/openbuild/model-map.toml` and project profile overrides; other repositories keep their own routing.
   - **All my projects** — saves `$CODEX_HOME/openbuild/model-map.toml` and user profile overrides.
2. What should happen to current overrides?
   - **Use them as the starting point (Recommended)** — preserve confirmed choices and edit only requested values.
   - **Start from packaged defaults** — construct a fresh proposal; existing files are still untouched until final permission.
   - **Restore packaged defaults** — propose removal only of the selected-scope map and OpenBuild profile overrides, show every deletion, and ask separate destructive permission.

State the project or user scope in simple words before continuing. If the selected scope already has a map, validate it first; never silently merge an invalid or incomplete file with defaults.

## Block 1 — Available models and priorities

Run the dependency/authentication preflight from [model routing](model-routing.md). Inspect the model catalog only when the runtime exposes it. Record available model evidence, supported effort values, known usage-pool evidence, and existing profile mappings.

Ask:

1. What matters most across routine work?
   - **Balanced speed and quality (Recommended)** — start economical and escalate only on concrete evidence.
   - **Maximum speed** — use the fastest confirmed route and fewer steps, accepting more blocked handoffs.
   - **Maximum quality** — start higher and allow more evidence-gated steps, using more time and allowance.
2. How should speed, quality, and usage limits be traded off when they conflict?
   - **Protect the separate/cheaper confirmed pool first (Recommended)** — only when the pool distinction is proven.
   - **Protect the main allowance** — prefer confirmed routes outside it when available.
   - **Ignore pool separation** — optimize only for task outcome.
3. Should reasoning effort usually be economical or deep?
   - **Scale with risk (Recommended)** — low effort for routine work, medium/high for harder work, deepest only for critical work.
   - **Keep it economical** — lower effort where the runtime supports it.
   - **Keep it deep** — higher effort for all configured roles.

If no trustworthy capability ordering exists, recommend retaining packaged role assignments and ask the user to confirm any custom ordering explicitly.

## Block 2 — Discovery

Explain: Discovery finds files, symbols, routes, owners, and cross-file evidence. It cannot edit. The packaged route uses `openbuild_search_separate` on Spark/low for one step.

Ask:

1. Which confirmed model should search first?
   - **Packaged Spark/low (Recommended)** — preserves the dedicated fast search route when available.
   - **Balanced search** — use `openbuild_search_balanced` with the chosen model/effort.
   - **Custom exact search model** — bind it to a canonical search profile.
2. How many semantic search attempts may run?
   - **One step (Recommended)** — then the root uses a minimal targeted lookup if the exact route fails.
   - **Two steps** — the second runs only after a completed first result reports insufficient evidence, ambiguous ownership, or a cross-file gap.
   - **Up to four steps** — configure the exact sequence and accept the additional time/usage.
3. Which evidence gaps justify the next configured search step?
   - **All three canonical gaps (Recommended)** — `insufficient-evidence`, `ambiguous-ownership`, and `cross-file-gap`.
   - **Only insufficient evidence** — narrower escalation.
   - **Custom subset** — choose only from the canonical gaps.

Every `openbuild_search_separate`, `openbuild_search_balanced`, `openbuild_search_strong`, and `openbuild_search_strongest` override must copy the canonical Explorer developer instructions exactly. Only model and reasoning effort may change; the sandbox remains read-only.

## Block 3 — Specification critics

Explain: critics challenge specification coverage and contradictions before implementation. They use fresh read-only `openbuild_review_*` profiles with a critic-specific prompt.

For low, medium, high, and critical, ask adaptively:

1. Which exact model/profile tries first?
2. What is the maximum ordered sequence: one, two, three, four, or five steps?
3. Which completed-result triggers may advance one step: `coverage-gap`, `unresolved-contradiction`, `low-confidence`, or `material-uncertainty`?

Recommend Luna/medium → Luna/xhigh → Terra/medium → Terra/xhigh → Sol/high for low, Terra/medium → Terra/xhigh → Sol/high for medium/high, and Sol/xhigh directly for critical unless confirmed model evidence supports a better assignment. Stop immediately on a current-revision `COVERED` result with sufficient confidence.

## Block 4 — Implementation

Explain: implementation agents may edit only their leased files; one writer is active at a time. Changing models after edits would split ownership, so escalation is allowed only before the first write.

For low, medium, high, and critical, ask:

1. Which exact model/profile gets the first attempt?
2. If it reports a real capability gap before editing, which exact profile is next?
3. How many route steps are allowed, from one to five?
4. Which pre-edit reasons justify the next step: `task-complexity-above-tier`, `unresolved-cross-layer-reasoning`, `validation-strategy-uncertain`, or `capability-gap`?
5. What reasoning effort should each selected profile use?

Recommend `openbuild_implementation_fast` → `openbuild_implementation_luna_xhigh` → `openbuild_implementation_balanced` → `openbuild_implementation_strong` → `openbuild_implementation_sol_high` for low, the Terra/medium → Terra/xhigh → Sol/high suffix for medium/high, and `openbuild_implementation_strongest` (Sol/xhigh) directly for critical. Require `max_steps` to match the explicit sequence. A successful implementation stops the route. A transport, authentication, quota, sandbox, spawn, timeout, runner, or evidence failure blocks the milestone and never tries a stronger writer.

## Block 5 — Review

Explain: review agents are read-only and inspect the current diff and acceptance evidence. The root fixes confirmed findings before any next review step.

For low, medium, high, and critical, ask:

1. Which exact model/profile reviews first?
2. What is the maximum ordered sequence?
3. Which completed-result triggers may advance one step: `actionable-finding`, `coverage-gap`, `low-confidence`, or `material-dispute`?
4. Should a clean result stop immediately? This must remain **Yes (Recommended)**.

Recommend the matching five-rung Luna/medium → Luna/xhigh → Terra/medium → Terra/xhigh → Sol/high review ladder for low, its Terra/medium → Terra/xhigh → Sol/high suffix for medium/high, and Sol/xhigh directly for critical. Never repeat the same profile on an unchanged diff or skip a configured intermediate step.

## Block 6 — Critical work and failure policy

Critical work includes destructive or irreversible changes, live infrastructure, secrets, permissions, destructive migrations, and very high blast radius. Explain that model routing does not grant authority for the action itself.

Ask:

1. Which strongest confirmed model/effort should handle critical implementation and review?
   - **Strongest confirmed profile at deepest supported effort (Recommended)**.
   - **A named alternative** — show the evidence and trade-off before accepting it.
2. If that exact route is unavailable, what should happen?
   - **Block and report the reason (Required)** — no weaker or unknown-model replacement.
3. Confirm the critical map.
   - **I confirm these critical routes** — writes `critical_confirmed = true` for every critical route.
   - **Do not configure critical routes yet** — stop without writing any partial map.

Also confirm the non-negotiable global values: `writer_policy = "single"`, `failure_policy = "block"`, `transport_failure = "block"`, and no production action is authorized by this interview.

## Block 7 — Final preview and permission

Build a final preview containing:

- the selected scope and effective precedence;
- a plain-language table for every discovery/critic/implementation/review risk route;
- each ordered profile, exact model, reasoning effort, sandbox, and profile source;
- `max_steps`, escalation mode, and escalation triggers;
- all critical confirmations and fixed failure rules;
- exact target paths and the exact diff for the complete map and profile overrides;
- redundant overrides omitted from the proposal;
- validation and smoke commands;
- any unverified model/pool claim or unavailable smoke.

Ask: **Apply this exact configuration?** Accept only an explicit yes that refers to the current preview. If any answer changes, regenerate the complete preview and permission request.

## Write and verify

After permission:

1. Recheck that every target still has the previewed content/hash. Drift cancels permission for that file.
2. Write the complete map to `.codex/openbuild/model-map.toml` or `$CODEX_HOME/openbuild/model-map.toml`. Never write a partial route set.
3. Write only necessary canonical profiles under `.codex/agents` or `$CODEX_HOME/agents`. Preserve the role's packaged developer instructions and sandbox; change only confirmed model/effort values. For implementation/review roles, also write the role's exact `routing_rung` and `routing_tuple_confirmed = true`; known Luna/Terra/Sol tuples must match that rung, while an unknown custom tuple requires the user's explicit rung confirmation. Never overwrite a changed file without a new exact diff and permission.
4. Run `model_map.py validate --path <selected-model-map>`.
5. Resolve every route and confirm project → user → packaged precedence and exact profile evidence.
6. Run one launcher smoke per distinct model/effort/sandbox tuple, not one per duplicate role. Require terminal `turn.completed`, exit zero, valid semantic output, and observed model/effort evidence.
7. Report `configured and verified`, `configured but unverified`, or `not changed` accurately. Recommend a new Codex thread so the installed skill and configuration are loaded cleanly.

If any validation fails, keep the existing effective complete map authoritative, report the exact failure, and do not claim that the new map is active.
