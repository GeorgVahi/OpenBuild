# OpenBuild

[Русская версия](README.ru.md)

OpenBuild is a Codex workflow for turning a plain-language idea or an existing specification into a repository-grounded plan and, when requested, a tested implementation with automatic phase routing, iterative blind-spot critique, separate-usage-pool-first code search, risk-matched-model coding, bounded writers, evidence-gated minimality, TDD-first milestones, and progressive review.

It packages one explicit skill, **Build**, with six modes:

- `new` — create a specification and stop before code changes;
- `refine` — verify and improve an existing specification and stop before code changes;
- `run` — execute a ready or refinable specification;
- `full` — go from an idea through specification, implementation, validation, and review;
- `auto` — infer the target and resume at the first incomplete phase;
- `setup-models` — optionally configure permission-gated search-pool, fast/balanced/strong writer, and read-only review profiles.

OpenBuild is self-contained. It does not require separate discovery, TDD, or review skills, telemetry, a hosted service, or background network access.

> OpenBuild `0.4.0` is the current release. The immutable release tag is `v0.4.0`; pin it for reproducible installation or use `main` intentionally for unreleased changes.

The manifest development version on `main` is `1.0.3`; the latest immutable release tag and GitHub Release remain synchronized at `0.4.0` until separately authorized publication.

## Workflow at a glance

```mermaid
flowchart LR
    A["Idea or existing specification"] --> B{"Explicit mode or auto evidence"}
    B -->|new / full| C["Repository discovery"]
    B -->|refine| D["Specification reconciliation"]
    B -->|run| E["Readiness audit"]
    B -->|auto| F["First incomplete phase"]
    C --> D
    F --> C
    F --> D
    F --> E
    D --> G["Blind-spot coverage and decisions"]
    G --> H{"Ready gate"}
    H -->|gaps| D
    H -->|covered| T{"Workflow target"}
    E --> H
    T -->|specification only| Q["Ready specification"]
    T -->|implementation| I["Risk-matched implementation"]
    I --> J["Focused and risk-based validation"]
    J --> K["Progressive read-only review"]
    K -->|actionable finding| I
    K -->|accepted| L["Complete record and scoped Git handoff"]

    classDef input fill:#0f172a,color:#f8fafc,stroke:#38bdf8,stroke-width:2px;
    classDef phase fill:#172554,color:#eff6ff,stroke:#60a5fa,stroke-width:1.5px;
    classDef gate fill:#422006,color:#fffbeb,stroke:#f59e0b,stroke-width:2px;
    classDef done fill:#052e16,color:#ecfdf5,stroke:#34d399,stroke-width:2px;
    class A,B input;
    class C,D,E,F,G,I,J,K phase;
    class H,T gate;
    class Q,L done;
```

| Goal | Command | Stops at |
|---|---|---|
| Create or repair a specification | `$build new …` / `$build refine BUILD.md` | `Ready` |
| Implement an accepted specification | `$build run BUILD.md` | `Complete` |
| Run the whole lifecycle | `$build full …` | `Complete` |
| Resume from repository evidence | `$build …` / `$build auto …` | First valid terminal state |
| Configure optional model routes | `$build setup-models` | Validated profiles plus reload instructions |

## Requirements

- A current Codex surface that supports skills. Plugin installation is available in Codex CLI and supported plugin surfaces.
- Git, when Build is expected to create milestone commits or review a task diff.
- Windows is verified for `v0.4.0`. macOS and Linux are documented as best-effort until native validation is completed.

OpenBuild `0.4.0` supports Codex only. It does not claim compatibility with Claude Code, Cursor, Gemini CLI, or other coding agents.

## Install as a plugin — recommended

The plugin is the primary distribution channel. It gives you versioned marketplace installation and the namespaced invocation `$openbuild:build`.

### Pinned release `v0.4.0`

```bash
codex plugin marketplace add GeorgVahi/OpenBuild --ref v0.4.0
codex plugin add openbuild@openbuild
```

Start a new Codex thread, then verify that `OpenBuild` is installed:

```bash
codex plugin list
```

Invoke it explicitly:

```text
$openbuild:build new Add saved searches to this application
```

### Preview from `main`

```bash
codex plugin marketplace add GeorgVahi/OpenBuild --ref main
codex plugin add openbuild@openbuild
```

Refresh a `main` installation:

```bash
codex plugin marketplace upgrade openbuild
codex plugin add openbuild@openbuild
```

### Switch between release tags

A versioned/tag-pinned marketplace is fixed to its selected tag. To move from one tag to another, remove the installed plugin and marketplace entry, then add the new tag:

```bash
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
codex plugin marketplace add GeorgVahi/OpenBuild --ref v0.4.0
codex plugin add openbuild@openbuild
```

Replace `v0.4.0` with the target release tag.

### Uninstall the plugin

```bash
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
```

## Install as a standalone skill

Standalone installation gives you the shorter `$build` invocation. Ask the preinstalled system skill installer to install the canonical Build folder:

```text
Use $skill-installer to install the skill from https://github.com/GeorgVahi/OpenBuild/tree/v0.4.0/plugins/openbuild/skills/build
```

To test unreleased changes, use the same path with `/tree/main/`; keep `v0.4.0` for a reproducible tagged installation.

Start a new Codex thread after installation. Open `/skills` or type `$` and verify that `build` appears, then invoke:

```text
$build new Add saved searches to this application
```

The installer refuses to overwrite an existing `$CODEX_HOME/skills/build` directory. Review that directory, back it up or remove it intentionally, and rerun the installer when updating. To uninstall the standalone version, remove only the confirmed `$CODEX_HOME/skills/build` directory and restart Codex.

The plugin and standalone channels use the same canonical source folder; there are no duplicated implementations in this repository.

## Usage

### 1. Create a specification from scratch

Plugin:

```text
$openbuild:build new Add a wishlist to the existing store
```

Standalone:

```text
$build new Add a wishlist to the existing store
```

Build will:

1. inspect the current repository and applicable `AGENTS.md` files;
2. establish a Git or artifact baseline;
3. delegate broad code search to bounded read-only discovery workers when available, then verify their evidence map;
4. create stable decision IDs and an evidence-backed blind-spot coverage ledger;
5. ask only unresolved product questions using short answers such as `1a 2b`;
6. run fresh risk-matched specification critics, deduplicate their findings, and repeat only for new gaps;
7. create `BUILD.md` in the user's language and stop before implementation once the current revision is covered.

Example question:

```text
1. [D-001] Who can keep a wishlist?
   a) Signed-in users only; the list follows the account.
   b) Guests too; the list starts locally and may merge after sign-in.
   Recommendation: 1a — it avoids an unresolved merge policy in the first version.

Reply with: 1a
```

### 2. Refine an existing specification

```text
$build refine BUILD.md
```

You can also pass `SPEC.md`, `TZ.md`, or another explicit path:

```text
$build refine docs/checkout-spec.md
```

Build compares the document with the current repository, preserves manual edits and stable decisions, bootstraps a coverage ledger for legacy documents, and runs fresh critics until every applicable concern is covered or explicitly not applicable. A resolved decision is never asked again unless verified new evidence reopens the same ID with its history intact. If several specification files are relevant or the selected file belongs to another task, Build asks before changing anything.

### 3. Execute a specification

```text
$build run BUILD.md
```

Build first verifies current-revision readiness through the coverage gate. It classifies implementation work as `Direct`, `Investigation`, or `TDD-first`, selects root-only or one bounded implementation worker, implements coherent milestones, reruns focused validation under root ownership, performs progressive review, updates the specification log, and creates scoped milestone commits when repository policy allows. It never pushes the user's repository without explicit authorization.

### 4. Run the full workflow

```text
$build full Add organization-level API keys with rotation and audit history
```

A bare invocation is an alias for `auto`; a new feature idea still targets the full workflow, but Build selects the first incomplete phase from repository and specification evidence:

```text
$build Add organization-level API keys with rotation and audit history
```

`full` and implementation-targeted `auto` may change implementation files after the specification reaches `Ready`. They still stop for destructive operations, secrets, live infrastructure, external publication without existing authorization, or a material scope expansion.

### 5. Select the phase automatically

```text
$build auto BUILD.md
```

Explicit `new`, `refine`, `run`, or `full` remains authoritative. `auto` and a bare invocation inspect the relevant specification: `Draft` or `Questions` resumes reconciliation, legacy `Ready` without current coverage returns to critique, covered `Ready` starts implementation when requested, `In progress` resumes the earliest incomplete milestone, and `Complete` is revalidated before Build decides that no work remains or creates a new task specification.

### 6. Configure progressive model tiers

```text
$build setup-models
```

Build first checks the capabilities exposed by the current Codex runtime. If native selection already provides every route, no files are needed. Otherwise it may propose read-only `openbuild-search-separate` and `openbuild-search-fallback`; write-capable `openbuild-implementation-fast`, `openbuild-implementation-balanced`, and `openbuild-implementation-strongest`; and read-only `openbuild-review-fast`, `balanced`, `strong`, and `strongest` profiles. Existing `openbuild-discovery` remains a legacy route and is treated as separate-pool search only when its mapping is proven.

Before writing anything, Build must show:

- the detected model/reasoning evidence;
- the proposed model, reasoning, usage-pool, sandbox, and role mapping;
- user scope (`~/.codex/agents`) or project scope (`.codex/agents`);
- exact target files and exact diff.

It writes only after separate permission, shows every `workspace-write` implementation profile separately, never overwrites an existing profile, validates TOML, and requires a reload or new session before use. Configured profile evidence is recorded separately from observed runtime metadata. Declining setup leaves search, specification, and read-only review operational with honest fallbacks; implementation proceeds only when the selected low, medium, high, or critical risk tier is satisfied.

## How automatic phase routing works

Build records two separate choices: the workflow target (`Ready` for specification-only work or `Complete` for implementation) and the first incomplete phase. Explicit modes and paths win. In `auto`, artifact evidence selects discovery, reconciliation/interview, blind-spot critique, implementation/resume, or verification; only genuine ambiguity between materially different targets or specification files becomes a routing question.

A legacy specification marked `Ready` is not trusted blindly. If it lacks the current decision memory, coverage ledger, or fresh closure evidence, Build audits it before code changes. A completed specification is revalidated against the current repository and complete acceptance evidence: the full task diff, focused and risk-based signals, documentation/version, security, migration, rollout/rollback, and review. Only then may Build no-op; otherwise it resumes the earliest invalid phase.

## How automatic code discovery works

Before any `rg`, `rg --files`, file/symbol lookup, repository grep, dependency trace, route/test/config/schema search, or log scan, the root agent creates a compact search plan and dispatches the exact `openbuild-search-separate` custom agent. A direct per-spawn model selector wins when the runtime exposes one; otherwise Build selects the custom agent by exact name. A generic worker, descriptive task name, or profile mention is not accepted as model selection. Workers return only an evidence map with `path:line`, symbol or route, a confirmed fact, relevance, negative results, and confidence.

The root agent remains the orchestrator: it deduplicates evidence, verifies already-known critical files and lines with targeted reads, makes product and architecture decisions, owns durable specification/version edits, validates, owns Git, and writes the final answer. A new grep or lookup returns to the search worker. Search workers never edit or decide architecture; implementation edits use the separate risk-matched single-writer lease described below.

## How usage-aware model routing works

```mermaid
flowchart TB
    R{"Task phase and evidence"}

    subgraph SEARCH["Search · read-only"]
        S0["Compact search plan"] --> S1{"Exact separate-agent dispatch?"}
        S1 -->|selected| S2["openbuild-search-separate"]
        S1 -->|recorded failure| S5["Failure receipt + circuit breaker"]
        S5 --> S3["Efficient main-pool fallback"]
        S3 --> S4["Explorer → generic worker → root"]
        S2 --> S6["Routing receipt before first search"]
    end

    subgraph WRITE["Implementation · exactly one writer"]
        W0{"Milestone risk"}
        W0 -->|low| W1["openbuild-implementation-fast"]
        W0 -->|medium| W2["openbuild-implementation-balanced"]
        W0 -->|high / critical| W3["openbuild-implementation-strongest"]
        W1 --> W4["Exact dispatch + routing receipt"]
        W2 --> W4
        W3 --> W4
        W4 --> W5["Same Ready, TDD, minimality, lease and validation gates"]
    end

    subgraph REVIEW["Review · read-only"]
        V0{"Diff risk floor"} --> V1["Exact profile: fast / balanced / strong / strongest"]
        V1 --> V2["Routing receipt + structured result"]
        V2 --> V3{"Accept with no concrete trigger?"}
        V3 -->|no| V4["Root adjudication, remediation and green validation"]
        V4 --> V5["Next proven tier only"]
        V5 --> V2
    end

    R --> S0
    S6 --> W0
    S4 --> W0
    W5 --> V0
    V3 -->|yes| Z["Verified completion"]

    classDef decision fill:#422006,color:#fffbeb,stroke:#f59e0b,stroke-width:2px;
    classDef search fill:#083344,color:#ecfeff,stroke:#22d3ee,stroke-width:1.5px;
    classDef write fill:#172554,color:#eff6ff,stroke:#60a5fa,stroke-width:1.5px;
    classDef review fill:#3b0764,color:#faf5ff,stroke:#c084fc,stroke-width:1.5px;
    classDef done fill:#052e16,color:#ecfdf5,stroke:#34d399,stroke-width:2px;
    class R,S1,W0,V0,V3 decision;
    class S0,S2,S3,S4,S5,S6 search;
    class W1,W2,W3,W4,W5 write;
    class V1,V2,V4,V5 review;
    class Z done;
```

Search always attempts a confirmed separate-usage route first, normally the exact custom agent `openbuild-search-separate` or an equivalent native selector. The current Spark preview is an official example of a separately limited, near-instant text model when the account and runtime expose it, but OpenBuild never pins that example universally. Before the first lookup, Build records the requested agent, dispatch method, configured and observed model, pool, result, and fallback reason. It may fall back only after `profile-not-discoverable`, `selector-unavailable`, `model-unavailable`, `quota-exhausted`, `spawn-failed`, or a selected worker's timeout/unusable evidence. It then opens the current-run circuit breaker and tries `openbuild-search-fallback`, explorer, a generic read-only subagent, and finally minimum root search. It does not scrape the private usage dashboard, guess remaining quota, or retry a failed separate route for every grep.

```text
search_agent: openbuild-search-separate
dispatch_method: per-spawn-model | exact-custom-agent | unavailable
configured_model: <profile/runtime value or unknown>
observed_agent: <runtime value or unknown>
observed_model: <runtime value or unknown>
pool: separate | main | unknown
dispatch_result: selected | failed
fallback_reason: none | <recorded allowed reason>
```

This routing receipt is the primary acceptance signal. The account usage dashboard remains useful secondary evidence, but it does not replace an observable exact-agent dispatch.

Code edits use an exact risk-matched writer while preserving the same Ready, TDD, minimality, single-writer, validation, and review gates at every tier. Before the first test or production edit, Build dispatches `openbuild-implementation-fast` for low risk, `openbuild-implementation-balanced` for medium risk, or `openbuild-implementation-strongest` for high/critical risk and emits an Implementation routing receipt. A generic worker, task label, profile mention, or stronger-than-requested agent does not count. Missing model metadata alone does not block an exact configured low or medium route, but Build records it as `unknown` and never claims an observed switch or saving. High and critical work still require their strong/strongest floor.

Progressive review uses the same exact-selection rule in read-only mode: low starts with `openbuild-review-fast`, medium with `openbuild-review-balanced`, high with `openbuild-review-strong`, and critical with `openbuild-review-strongest`. Each dispatch produces a Review routing receipt. Reviewers run sequentially through fast → balanced → strong → strongest from the risk floor; Build stops on sufficient acceptance evidence and advances exactly one proven tier only when a concrete trigger remains after root remediation and green validation.

Escalation is evidence-driven: Build moves to the next writer tier only when scope or risk increases, the current worker reports insufficient confidence, the red/green signal exposes a deeper owner-layer problem, validation fails for a task-scoped reason, or review confirms an actionable finding. It never launches stronger writers merely to demonstrate model switching. Exact `model` and `model_reasoning_effort` values stay in user- or project-scoped custom-agent files rather than the portable plugin.

Codex officially supports per-agent `model`, `model_reasoning_effort`, and sandbox settings, and documents the Spark preview as separately limited. Because availability changes, `$build setup-models` must verify the current account/runtime mapping before writing profiles: [Codex pricing and usage limits](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan), [Codex subagents and model choice](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning).

## How blind-spot critique works

Before `Ready`, Build gives every applicable concern a stable coverage ID and a state: `gap`, `covered`, or `not applicable` with evidence. The ledger covers outcomes and non-goals, actors and permissions, primary and failure flows, accessibility and localization, ownership and contracts, data and migrations, security and privacy, performance and concurrency, integrations, observability, rollout/rollback, and acceptance/testability. Task-specific concerns are added rather than forced into a generic row.

Product decisions receive stable `D-###` IDs. A resolved ID is a locked constraint even if a later critic rephrases the same question. Reopening is allowed only when verified new repository evidence, a failing signal, an upstream constraint, or an explicit scope change materially breaks the selected outcome; Build preserves the same ID and explains what changed.

For every non-trivial revision, a fresh read-only critic receives the current specification, decision memory, coverage ledger, and repository evidence. It reports only new gaps, evidence-backed reopen requests, and duplicates linked to existing IDs. The root verifies and deduplicates findings, resolves repository and technical gaps itself, and asks the user up to five remaining product decisions per round. The loop continues on new revisions until the risk-appropriate fresh closure pass returns `COVERED`; the same critic perspective/tier is never repeated on an unchanged revision.

Depth follows risk: low work gets a structured self-audit and a critic when non-trivial; medium gets a fresh balanced critic and post-answer closure; high gets complementary product/UX and architecture/data/security critics plus a strong closure; critical gets adversarial perspectives, the strongest available closure, and required authority checkpoints. Exhausted critics with an open gap leave the specification out of `Ready`. This is evidence-backed closure of defined and task-specific concerns, not a claim of literal omniscience.

## How TDD-first implementation works

Behavior, contracts, validation, routing, state, auth or permissions, persistence, concurrency, integrations, security, and non-trivial user-facing changes use a red → green → refactor workflow. Build finds the narrowest supported test path, records a meaningful failing signal when practical, makes the minimum coherent owner-layer change, requires focused green validation, and refactors only after green.

Direct documentation or cosmetic work does not get ceremonial failing tests. Investigation work first reproduces or traces the failure and is reclassified as TDD-first before behavior changes. When an automated red signal is impractical, Build records why and uses the best reproducible contract or runtime signal.

Reviewers stay read-only. They audit the red signal, owning layer, focused green result, and risk-based coverage. Confirmed behavioral findings go back to the root agent, which runs remediation through the same TDD-first workflow before requesting another review.

## How adaptive implementation delegation works

```mermaid
flowchart LR
    A["Root classifies milestone and risk"] --> B{"Ready and required tier proven?"}
    B -->|no| X["Stop and record the exact blocker"]
    B -->|yes| C["Dispatch exact risk profile + routing receipt"]

    subgraph LEASE["Exclusive writer lease · root pauses edits"]
        C --> C1["Issue one bounded writer lease"]
        C1 --> D["Red or primary signal"]
        D --> E["Minimum owner-layer change"]
        E --> F["Focused green validation"]
        F --> G["Diff, evidence and assumptions handoff"]
    end

    G --> H["Root releases lease and rereads full diff"]
    H --> I["Independent risk-based validation"]
    I --> J["Progressive read-only review"]
    J -->|confirmed finding| A
    J -->|accepted| K["Version, changelog and scoped Git action"]

    classDef root fill:#0f172a,color:#f8fafc,stroke:#38bdf8,stroke-width:2px;
    classDef gate fill:#422006,color:#fffbeb,stroke:#f59e0b,stroke-width:2px;
    classDef worker fill:#172554,color:#eff6ff,stroke:#60a5fa,stroke-width:1.5px;
    classDef stop fill:#450a0a,color:#fef2f2,stroke:#f87171,stroke-width:2px;
    classDef done fill:#052e16,color:#ecfdf5,stroke:#34d399,stroke-width:2px;
    class A,H,I,J root;
    class B gate;
    class C,C1,D,E,F,G worker;
    class X stop;
    class K done;
```

After `Ready`, each milestone selects `root-only`, `bounded-worker`, or `sequential-workers`, then dispatches the exact minimum sufficient writer profile from milestone risk and records its routing receipt before a lease or edit. Reasoning effort scales from low/minimal for mechanical changes to the deepest supported effort for critical work. A worker is used only when the owning files, acceptance criteria, red or primary signal, and stop conditions are clear; `root-only` remains limited to documented safety cases and requires the root to satisfy the selected tier. An unavailable required tier blocks that milestone instead of authorizing a risk-floor downgrade.

The shared checkout has one active writer. A worker receives a baseline and exact allowed files, cannot edit the specification, version, changelog, or unrelated files, cannot make product or architecture decisions, and cannot stage, commit, push, publish, or deploy. The root does not edit while the lease is active. After handoff, the root rechecks the complete diff, rereads changed code, reruns focused and risk-based validation, updates durable records and versioning, and only then starts progressive review or Git actions. Multiple worker milestones run strictly sequentially.

## How evidence-gated minimality works

After the Ready gate and before code changes, Build evaluates every proposed file, dependency, abstraction, configuration surface, and compatibility layer through an evidence-gated ladder: is it needed now; does the repository already solve it; does the standard library or native platform cover it; does an installed dependency fit; and only then, what is the minimum coherent custom change in the owning layer. Build stops at the first option that satisfies the complete acceptance criteria, invariants, repository conventions, and risk constraints.

Minimality governs technical means, not accepted product scope. It never trades away supported tests, trust-boundary validation, security, privacy, accessibility, data-loss handling, error handling, observability, compatibility, migration or rollback safety, concurrency correctness, or required performance. A deliberate simplification with a known ceiling records that ceiling and an observable upgrade trigger instead of building the speculative upgrade immediately.

Reviewers audit the completed diff for duplicated sources of truth, avoidable dependencies, custom code covered by standard or native capabilities, speculative abstractions or configuration, and downstream symptom patches. Line count and code golf are not success metrics; a finding is actionable only when the smaller path preserves accepted behavior and risk coverage.

## How progressive review works

Build classifies each task as `low`, `medium`, `high`, or `critical`. It starts at the minimum sufficient review tier rather than always wasting a strongest-model pass:

| Complexity | Typical work | Starting review request |
|---|---|---|
| `low` | Documentation or mechanical local changes | `openbuild-review-fast` |
| `medium` | Contained behavior or refactoring with tests | `openbuild-review-balanced` |
| `high` | Cross-layer state, public contracts, persistence, concurrency, auth, permissions, privacy | `openbuild-review-strong` |
| `critical` | Irreversible actions, live infrastructure, secrets, destructive migration | `openbuild-review-strongest` |

Reviewers return acceptance coverage, evidence-backed findings, confidence, a verdict, and an optional score. After confirmed findings are fixed and validation reruns, Build escalates when confidence is low, coverage is incomplete, reviewers conflict, validation fails, a high-impact finding remains, or the diff changed materially. A score below `9.5` triggers escalation only when the reviewer ties it to a concrete finding, uncertainty, or coverage gap.

The score is only a secondary escalation signal. An evidence-backed accept verdict with sufficient confidence, green validation, complete acceptance coverage, and no confirmed actionable findings is enough even when a score is omitted or below `9.5` without a concrete gap. Reviewers are exact-dispatched one at a time, each with a read-only sandbox and Review routing receipt. The loop starts at the risk floor, follows fast → balanced → strong → strongest without skipping a proven tier, and never repeats the same reviewer on an unchanged diff.

When Codex does not expose a model selector, Build does not invent one. It falls back through configured profiles, supported reasoning efforts, a read-only explorer role, a generic subagent, and finally root-only self-review. The effective mode and any unknown tier are recorded explicitly.

## Specification resolution

Build uses an explicit path when provided. Otherwise it prefers a relevant `BUILD.md`, then a relevant `SPEC.md` or `TZ.md`, and creates `BUILD.md` for a new task. It never silently replaces a specification that belongs to another task. `auto` also inspects the selected document's status, revision, coverage, and incomplete milestones to choose the starting phase.

## Git and safety policy

- Existing user changes remain out of scope unless the specification explicitly includes them.
- `new`, `refine`, and specification-targeted `auto` may edit only the specification.
- `run`, `full`, and implementation-targeted `auto` may edit implementation files after the Ready gate.
- Milestone commits are created when Git is available, changes can be isolated, and applicable instructions do not forbid commits.
- Push always requires explicit authorization.
- Model configuration requires a separate preview and permission.
- Discovery workers, specification critics, and reviewers are read-only. A bounded implementation worker may edit only one leased file set; writers never overlap, and the root owns decisions, specification/version edits, handoff validation, Git, and final reporting.
- No telemetry, daemon, `curl | shell`, hidden auto-update, or background network service is included.
- Build follows the repository's `AGENTS.md`, sandbox, approval, validation, and security rules.

## Versioning and commits

Before a milestone or final commit, Build discovers the repository's authoritative version source and policy, then records `version impact` as `not applicable`, `prerelease`, `patch`, `minor`, or `major`. In a versioned repository, every Build-created commit receives a unique higher version by default, with the changelog and required documentation updated in that same commit.

Build does not invent versioning for an unversioned repository, and it follows an explicit repository policy that uses release-only or generated versions. OpenBuild itself requires a bump for every commit after the repository root, including prose, internal validation changes, and otherwise empty commits. Build never moves a published tag. Tag creation, GitHub Release creation, package publication, and promotion from prerelease to stable remain separately authorized publication actions.

OpenBuild's own contributor, version, commit, and release rules are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## Troubleshooting

### The skill does not appear

- Start a new thread or restart Codex after installation.
- For the plugin, run `codex plugin list` and confirm `openbuild@openbuild` is installed and enabled.
- Open `/skills` or type `$` to inspect discovered skills.
- Use `$openbuild:build` for the plugin and `$build` for standalone installation.

### Both `$build` and `$openbuild:build` appear

You installed both channels. They use the same source but are separate local installations. Prefer the namespaced plugin invocation or intentionally remove the standalone `$CODEX_HOME/skills/build` directory.

### Model switching is reported as unavailable or unverified

Run `$build setup-models`, reload Codex or start a new thread, and inspect the search routing receipt on the next Build run. Without a native selector or configured custom-agent profiles, OpenBuild cannot prove that search used a separate quota or that an observed model switch occurred. A generic subagent or task name does not count as selecting `openbuild-search-separate`; Build must report an explicit fallback reason instead. It can still use honest read-only fallbacks. For implementation, configured fast or balanced named profiles may proceed with runtime metadata recorded as `unknown`; high and critical milestones stop unless their required strong/strongest route can be selected.

### Build refuses to overwrite a specification

The discovered file is ambiguous or belongs to another task. Pass the intended path explicitly or choose a descriptive file such as `BUILD-wishlist.md`.

### The worktree is already dirty

Build records the initial status, excludes unrelated changes, and commits only task-scoped files. If changes cannot be isolated safely, it stops before committing rather than hiding or publishing them.

## Development and validation

See [CONTRIBUTING.md](CONTRIBUTING.md) for the `main` workflow, Semantic Versioning rules, same-commit version gate, and immutable release checklist.

From the repository root:

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
python scripts/validate_package.py
```

The release process also runs the official Codex skill and plugin validators, clean plugin installation, standalone installation from the tagged GitHub path, forward-tests for `new`, `refine`, `run`, `auto`, duplicate-decision suppression, evidence-backed reopening, risk-adaptive critic closure, exact separate-agent dispatch, routing-receipt trace fixtures, circuit-breaker fallback, risk-matched writer selection and escalation, single-writer handoff, evidence-gated minimality, TDD-first remediation, and model-routing fallbacks, and a fresh full-diff review.

Useful official references:

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex subagents and custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex pricing and usage limits](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan)

## License

[MIT](LICENSE)
