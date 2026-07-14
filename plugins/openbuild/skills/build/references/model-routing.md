# Capability-aware model routing

Use this reference whenever Build delegates repository discovery, specification critique, implementation, log analysis, or review, and always for `$build setup-models`.

## Routing principles

1. Keep the current root agent as orchestrator and decision owner.
2. Route every repository search to the immutable packaged read-only search worker before using the root. Keep decisions, targeted reads of already-known files, durable specification/version edits, validation, Git, and final synthesis with the root.
3. When that exact route fails, create no replacement agent; use only the minimum targeted root search required to unblock the task.
4. Choose models or tiers only from capabilities exposed by the runtime or confirmed configuration, then execute the selected profile through the packaged explicit-model runner.
5. Never rank a model by parsing its name. A model catalog may expose IDs, supported reasoning efforts, a default, or an upgrade path without exposing cost or a complete strength ordering.
6. Never claim that a model changed unless the spawn result, selected profile, or runtime evidence proves it.
7. Preserve only the documented targeted-root recovery for search; block implementation and exact-review gates on runner failure.
8. Keep search workers, specification critics, and reviewers read-only. Route code edits to a risk-matched Implementation worker under the same Ready, TDD, minimality, single-writer, validation, and review gates in [adaptive implementation delegation](implementation-delegation.md).

## Primary explicit-model runtime

The only agent dispatch method is `codex-exec-explicit-model`, implemented by `<build-skill-root>/scripts/agent_runner.py` and requiring Python 3.11 or newer. For `openbuild_search_separate` it resolves only the fixed packaged Spark profile and ignores same-named project/user files; for every other role it resolves the exact canonical profile from `<project>/.codex/agents`, then `$CODEX_HOME/agents`, then the packaged default. It rejects missing or inherited `model` and `model_reasoning_effort`, verifies the role sandbox, and launches a separate process with argument-vector selection rather than a shell-composed command:

```text
codex exec --json --ephemeral -m <profile-model> -c model_reasoning_effort="<profile-effort>" -c features.multi_agent=false -c forced_login_method="chatgpt" -c model_provider="openai" --sandbox <profile-sandbox> -C <workspace> -o <result> -
```

The runner removes ambient API-key and provider-base-URL variables, requires `codex login status` to report saved ChatGPT authentication, forces the built-in OpenAI provider plus ChatGPT login method, and rejects redirects or custom `model_providers.openai` definitions in the user and every applicable project config layer. It passes the profile contract as developer instructions, snapshots the bounded prompt before `Popen`, sends that immutable snapshot through stdin, disables the stable multi-agent capability mechanically, and records the worker PID, Codex PID, process-group/creation identities, private exact-run artifacts, profile source, JSONL, stderr, and final message. Windows workers own a kill-on-close Job Object and termination uses an identity-checked process handle; POSIX cancellation verifies the whole recorded process group even after its leader exits. On POSIX, the run directory is `0700` and artifacts are `0600`; an explicitly supplied weaker directory is rejected.

Start with `agent_runner.py start`, retain and record its unactivated running receipt, then call `agent_runner.py activate` for that run directory. The activation artifact must repeat the live Codex PID and creation identity; the worker holds Codex stdin until that match, so no task action can precede the recorded receipt. Poll with `status`; use `wait` only with a bounded timeout. A timeout of the parent wait is non-terminal while the creation-bound worker or Codex process identity remains active or its liveness is unknown: never fall back or release a writer lease on that signal. Use `cancel` when interruption is required and continue only after every started process and process group is positively confirmed stopped. Implementation starts additionally require a pre-existing `--lease-id`, which is persisted before `Popen`, followed by a lease/run-bound activation event before edits. A dispatch is proven only when the receipt names the requested agent, configured model, reasoning effort, and sandbox, the readable non-empty result exists, and exactly one terminal JSONL event is its final nonblank event: `turn.completed`. `turn.failed`, malformed or trailing JSONL, missing result/terminal evidence, a non-zero CLI exit, unknown process liveness, or a stopped process tree without recoverable completion evidence fails the route. The CLI selection plus accepted terminal event is operational evidence of the requested model/effort; it is not a cryptographic attestation of provider-internal routing.

If the explicit runner fails, record one of `profile-not-discoverable`, `profile-incomplete`, `cli-unavailable`, `chatgpt-auth-unavailable`, `model-unavailable`, `quota-exhausted`, `sandbox-mismatch`, `runner-failed`, `spawn-failed`, `worker-timeout`, or `unusable-evidence`. `worker-timeout` is valid only after `cancel` confirms every started process stopped; `unusable-evidence` is valid only after a completed result. Create no replacement agent. Search uses targeted root recovery, implementation remains blocked, and diagnostic root review cannot close an exact-review or release gate.

## Exact-agent dependency checkpoint

Before the first exact CLI dispatch in a Build run, select the preflight by host OS. On Windows, execute `python --version`. On POSIX, execute `python3 --version` first and use `python --version` only as a fallback. Execute `codex --version` on every platform; Python must be 3.11 or newer. If either check fails, stop before agent creation.

Show the `winget` and standalone PowerShell commands only on Windows.

```powershell
winget install -e --id Python.Python.3.12
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

The exact Windows commands are `winget install -e --id Python.Python.3.12` and `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"`; do not substitute another installer silently. On POSIX, provide manual, platform-appropriate Python and Codex CLI installation guidance without choosing or running a package manager.

Offer two paths: the user installs manually and replies after completion, or Build runs an applicable displayed command only with separate explicit permission. Wait for installation and rerun the OS-appropriate Python check plus `codex --version`. Authentication remains manual: ask the user to run `codex`, complete ChatGPT sign-in personally, and then verify `codex login status`. Never automate or request credentials. When installation/auth is declined or unavailable, record the dependency checkpoint; use targeted root recovery only for discovery and keep implementation/review gates blocked. Never claim an exact CLI agent was created.

## Search usage-pool order

Use this order before any repository grep, file/symbol lookup, dependency trace, route/test/config/schema search, or log scan:

1. **Exact Spark route:** run the packaged `openbuild_search_separate` profile through `agent_runner.py` as `codex-exec-explicit-model`. OpenBuild pins this zero-profile-setup search route exclusively to `gpt-5.3-codex-spark` with low reasoning and a read-only sandbox; same-named project/user profiles cannot override it.
2. **Root recovery:** after a stopped terminal exact-runner failure, perform only the minimum targeted root search needed to unblock the task and record the normalized failure. Do not create another search agent.

Attempt the exact separate-pool dispatch once before the first search branch. Do not run the first repository search until it succeeds or fails with one recorded reason: `profile-not-discoverable`, `profile-incomplete`, `cli-unavailable`, `chatgpt-auth-unavailable`, `model-unavailable`, `quota-exhausted`, `sandbox-mismatch`, `runner-failed`, or `spawn-failed`. Use `worker-timeout` or `unusable-evidence` only after a selected worker actually runs. Then open a circuit breaker for the current Build run and use the next branch without retrying the same failed route for every grep. Reset it only on a new Build invocation, verified runtime-state change, or explicit user instruction. Do not scrape or infer remaining quota from the private usage dashboard; record only the selected profile/model and an observed runtime/quota result.

Do not block specification-only work merely because the search route is unavailable, but disclose targeted root recovery. Do not silently skip it when the exact route is required.

Before the first repository search, emit the selected worker's unactivated `running` routing receipt with `configured_model`, `observed_model`, `fallback_reason`, and run/process identities, then record matching activation. After the worker search, emit its stopped terminal receipt and only then consume the evidence through exactly one root-owned event bound to that run. The terminal `codex-exec-explicit-model` receipt requires `turn.completed`, a creation-bound integer exit code of zero, a valid non-empty result, and semantic task success. The exact runner is the only created-agent route; after failure record the reason and use targeted root recovery.

OpenBuild ships reviewed concrete defaults for every canonical role and still permits exact project/user overrides for non-Spark roles. Spark remains immutable. Availability failures remain explicit and never select another agent route.

## Critic and review capability order

For specification critics and diff review, use the exact packaged or canonical `openbuild_review_*` profile through the runner. Apply the complexity floor. A diagnostic root pass may record gaps after runner failure but cannot satisfy a required independent closure.

### Exact sequential reviewer dispatch

Dispatch the exact starting reviewer through `agent_runner.py` before every progressive-review ladder: `low` → `openbuild_review_fast`, `medium` → `openbuild_review_balanced`, `high` → `openbuild_review_strong`, and `critical` → `openbuild_review_strongest`. Persist the unactivated `running` Review routing receipt, call `activate`, record the matching `review-agent-activated` event, and require the stopped terminal receipt with `codex-exec-explicit-model`, `turn.completed`, creation-bound exit code zero, valid result evidence, and a semantically completed review; only then use the result. Failure blocks the gate instead of selecting another reviewer route.

Run reviewers one at a time in this order: fast → balanced → strong → strongest. Begin at the complexity floor, never below it. Stop after an evidence-backed `ACCEPT` with sufficient confidence, complete acceptance coverage, green validation, and no actionable finding. Move exactly one proven tier higher only when the previous structured result records a trigger from [the review protocol](review-protocol.md). The root adjudicates and remediates confirmed findings through TDD/minimality, reruns affected validation, and only then dispatches the next exact reviewer. Reviewers remain read-only and never fix their own findings.

Emit one unactivated `running` and one stopped terminal Review routing receipt around a matching `review-agent-activated` event. The dispatch event separates canonical `agent_name` from descriptive `task_name`. Both receipts carry `diff_revision`, `risk_floor`, `requested_agent`, `task_name`, `requested_tier`, `dispatch_method`, `configured_model`, `model_reasoning_effort`, `observed_agent`, `observed_model`, `terminal_event`, `activated`, `run_status`, `sandbox`, `dispatch_result`, `fallback_reason`, `process_tree_stopped`, `run_dir`, worker/Codex PIDs and creation identities, `codex_exit_evidence`, `codex_exit_code`, and `result_evidence`. The terminal receipt must preserve the original route and identities and precede `review-result`. Do not repeat the same tier on an unchanged diff or skip a proven intermediate tier. If an exact profile or runner is unavailable, record the primary-runtime failure and leave the gate incomplete; create no replacement reviewer.

## Complexity floor

| Class | Typical scope | Minimum starting review tier | Minimum final tier |
|---|---|---|---|
| `low` | Documentation, copy, or local mechanical work | Fast/economy when proven suitable | Fast/economy |
| `medium` | Contained behavior or refactoring with clear tests | Balanced | Balanced |
| `high` | Cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy | Strong | Strong |
| `critical` | Irreversible actions, live infrastructure, secrets, destructive migration, very high blast radius | Strongest | Strongest |

Use the highest applicable risk. Discovery can use a cheaper read-only tier than final review, but the root must verify its evidence. A required review tier must be proven by the exact runner receipt; otherwise leave the gate incomplete.

## Delegation contract

Give each explorer, specification critic, or reviewer:

- one bounded objective and repository scope;
- read-only instructions and prohibited actions;
- required evidence format: `path:line`, symbol or route, confirmed fact, relevance;
- a stop condition for sufficient coverage;
- a prohibition on architecture decisions, edits, commits, pushes, secrets, and final user answers.

Keep raw logs and large dumps out of the root context. Aggregate and deduplicate findings before making decisions.

For broad repository search, use the full search-plan, evidence-map, fallback, and root-verification contract in [code discovery](code-discovery.md). Discovery workers, specification critics, and reviewers are separate read-only roles: discovery maps repository evidence; critics challenge specification coverage; review evaluates a current diff and acceptance evidence. `openbuild_review_*` profiles may serve as fresh specification critics with a critic-specific brief and the current decision/coverage ledger.

## Implementation worker routing

Choose an Implementation worker only after the current specification revision passes the Ready gate. Classify the milestone before every lease and select the minimum sufficient proven coding tier:

- `openbuild_implementation_fast` for low-risk Direct documentation, cosmetic, or mechanical work with no behavior change;
- `openbuild_implementation_balanced` for medium-risk contained logic or refactoring with clear contracts and supported tests;
- `openbuild_implementation_strongest` for high-risk cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy, or sensitive state, and for critical work at the deepest supported effort.

Before every test or production code edit, acquire the single-writer lease for the exact selected profile, then start it through `agent_runner.py` as `codex-exec-explicit-model` with `--lease-id <id>`. Separate the canonical `agent_name` from the descriptive `task_name`. Record the lease-bound unactivated `running` Implementation routing receipt, call `activate`, record `implementation-agent-activated`, and keep the lease active through all worker writes. A completed receipt with `turn.completed`, creation-bound exit code zero, valid result evidence, and a semantically completed task must precede `implementation-handoff-accepted`, result consumption, and release. A failed, cancelled, or semantically unsuccessful receipt permits lease release only with the milestone incomplete and forbids another writer route.

Never use `openbuild_search_separate`, legacy `openbuild-discovery`, or `openbuild_review_*` profiles for code edits. Use bounded or sequential exact implementation workers and never run concurrent writers in one checkout.

Pass only the milestone, baseline, allowed files, acceptance criteria, red or primary signal, focused green command, and stop conditions defined in [adaptive implementation delegation](implementation-delegation.md). The root independently verifies the returned diff and validation before review or Git actions.

**Escalate only on evidence.** Move from fast to balanced or balanced to strong/strongest when scope or risk increases, the selected agent reports insufficient confidence, the red/green signal exposes a deeper owner-layer problem, validation fails for a task-scoped reason, or review confirms an actionable gap. Do not fan out or escalate merely because a stronger model exists, and never repeat an unchanged task at the same tier.

Every created implementation agent must have concrete model, effort, and sandbox evidence from the runner receipt. When the required exact route cannot be selected or the semantic handoff fails, stop before further test or production edits rather than lowering the risk floor, and record the limitation.

## `$build setup-models`

### Preflight

1. Verify `codex`, saved ChatGPT authentication, `scripts/agent_runner.py`, discoverable agent roles/profiles, and the model catalog when exposed.
2. Identify whether current official guidance, runtime metadata, or the user confirms a separate-usage search model for this account/surface. Do not infer pool membership from a model slug alone.
3. Identify proven fast, balanced, and strong/strongest coding tiers for optional canonical overrides.
4. If complete exact profiles already provide every proven route, run one launcher smoke per distinct model/effort/sandbox tuple and avoid creating redundant files.
5. If only catalog IDs are available, do not invent usage-pool membership or strength ordering. Use official product guidance, documented `upgrade`, supported reasoning-effort descriptions, runtime tier metadata, or a user-confirmed mapping.
6. Deduplicate roles that resolve to the same effective model, effort, sandbox, and usage pool.
7. Detect canonical underscore IDs separately from legacy hyphenated OpenBuild profiles; never treat filename discovery or `task_name` as exact selection.

### Proposal

The packaged `openbuild_search_separate` route is fixed and is never proposed as a writable profile. The packaged implementation/review profiles work without setup; propose only requested canonical overrides:

- `openbuild_implementation_fast`: a proven efficient coding route for low-risk Direct work, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild_implementation_balanced`: a proven balanced coding route for medium-risk contained behavior, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild_implementation_strongest`: a proven strong/strongest coding route for high or critical work, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild_review_fast`: low-risk documentation and mechanical-change review;
- `openbuild_review_balanced`: normal contained changes;
- `openbuild_review_strong`: high-risk or escalated review;
- `openbuild_review_strongest`: critical or final escalated review.

Treat an existing `openbuild-discovery` profile as inactive legacy configuration. The review profiles also support risk-matched fresh specification-closure passes and remain read-only.

For every role show:

- confirmed model ID and reasoning effort;
- evidence used to assign the tier;
- confirmed usage pool (`separate`, `main`, or `unknown`) and source of that claim;
- sandbox mode and whether the role may edit;
- target file and scope;
- exact TOML content;
- whether a reload or new session is required.

Ask whether configuration should be user-scoped (`~/.codex/agents`) or project-scoped (`.codex/agents`). Then request separate permission before writing.

### Guided legacy-profile migration

Map the supported legacy names to canonical runtime-safe IDs without changing their configured model, reasoning effort, sandbox, or developer instructions. The legacy `openbuild-search-separate` name is deliberately excluded: the canonical ID is reserved for the immutable packaged Spark profile, so setup reports any such legacy file as inactive and does not create a canonical replacement.

| Legacy `name` | Canonical `name` |
|---|---|
| `openbuild-implementation-fast` | `openbuild_implementation_fast` |
| `openbuild-implementation-balanced` | `openbuild_implementation_balanced` |
| `openbuild-implementation-strongest` | `openbuild_implementation_strongest` |
| `openbuild-review-fast` | `openbuild_review_fast` |
| `openbuild-review-balanced` | `openbuild_review_balanced` |
| `openbuild-review-strong` | `openbuild_review_strong` |
| `openbuild-review-strongest` | `openbuild_review_strongest` |

Before any configuration write, build and show one immutable `plan_id` containing the complete supported mapping, the complete detected-legacy inventory, and a stable `entry_id` for every detected legacy profile. Each entry carries scope-relative source/target paths, a trusted configuration-root fingerprint, legacy/canonical names, source, target, and rendered-canonical SHA-256 values, the complete exact TOML diff, and one action: `create-if-absent`, `already-migrated`, or `config-conflict`. Derive each `entry_id` from its canonical entry serialization and the `plan_id` from the complete mapping, inventory, and entry IDs so an unchanged rerun produces the same identifiers. A missing target is `create-if-absent`; a target matching the rendered canonical SHA-256 is `already-migrated`; a different target hash is `config-conflict` and must not be written.

Ask permission for the displayed plan before writing and persist per-entry authority bound to that entry's exact source, target, and rendered hashes plus planned action. Create approved missing targets atomically without overwriting either legacy or canonical files. Recheck both SHA-256 preconditions immediately before each write; hash drift invalidates only that entry and requires a new exact diff and permission while unchanged entries keep their authority. Record one resumable receipt per entry with the observed source/target preconditions, result hash or `not-written`, and `created`, `already-migrated`, `config-conflict`, or `hash-drift`; never claim a partial run as complete.

Validate TOML, reload or start a new session, verify canonical discoverability and exact selection, then offer legacy cleanup as a separate displayed plan and permission. Never delete or rename a legacy file during canonical creation. This is a guided migration, not a silent bulk rewrite.

### Profile shape

Use the runtime-supported custom-agent schema. Typical generated profiles are:

```toml
name = "openbuild_implementation_<fast|balanced|strongest>"
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
- Keep search and review profiles read-only. Create each `openbuild_implementation_fast`, `openbuild_implementation_balanced`, and `openbuild_implementation_strongest` profile with `workspace-write` only after separately showing its exact scope and receiving permission.
- Validate TOML after writing.
- Ask for reload or a new session when configuration discovery needs it, then verify each role with `agent_runner.py`, terminal `turn.completed`, and a semantically successful result.
- Until explicit-model smoke succeeds, report setup as configured but unverified.
- Never commit user-specific overrides to OpenBuild itself; the reviewed packaged defaults are the portable runtime contract.

## Routing record

Record this for each run or milestone:

```text
Complexity: <low|medium|high|critical> — <evidence>
Routing mode: <codex-exec-explicit-model|root-recovery|blocked>
Discovery mode: <delegated|mixed|root-recovery>
Search usage route: <separate-pool|root-recovery>
Search model/tier: <observed value or unknown>
Separate-pool attempt: <used|unavailable|not configured; evidence and circuit-breaker state>
Discovery branches: <objectives and worker count>
Search routing receipt: <agent, dispatch method, configured/observed model, pool, result, fallback reason>
Readiness critic depth: <perspectives, tiers, closure revision, and fallback>
Implementation delegation: <root-only|bounded-worker|sequential-workers|blocked; requested writer profile/tier, observed value or unknown, escalation, and exact blocker if any>
Writer-route evidence: <official/runtime/config/user mapping, exact requested profile, selection evidence, and limitations>
Starting review tier: <observed tier or unknown>
Required final tier: <tier based on risk>
Actual escalation: <tier sequence or none>
Limitations: <unavailable selectors, profiles, or independence>
```
