# Capability-aware model routing

Use this reference whenever Build delegates repository discovery, specification critique, implementation, log analysis, or review, and always for `$build configure-models` or its `$build setup-models` alias.

## Routing principles

1. Keep the current root agent as orchestrator and decision owner.
2. Resolve the effective model map before every agent dispatch. Route every repository search to its first configured read-only search worker before using the root. Keep decisions, targeted reads of already-known files, durable specification/version edits, validation, Git, and final synthesis with the root.
3. Advance semantic routes only after a completed result contains a configured evidence trigger. Transport never advances those ladders. Discovery alone may use one separately declared availability fallback from an exact stopped Spark source to canonical Terra for structured `model-unavailable` or model-specific `quota-exhausted` in a coherent pre-turn event stream; malformed/contradictory streams, conflicting `code`/`type` values, JSONL/stderr disagreement and any `turn.completed` are ineligible, and every other failure uses minimum targeted root recovery.
4. Choose models or tiers only from capabilities exposed by the runtime or confirmed configuration, then execute the selected profile through the packaged explicit-model runner.
5. Never rank a model by parsing its name. A model catalog may expose IDs, supported reasoning efforts, a default, or an upgrade path without exposing cost or a complete strength ordering.
6. Never claim that a model changed unless the spawn result, selected profile, or runtime evidence proves it.
7. Preserve only the documented targeted-root recovery for search. By default, block implementation and exact-review gates on runner failure. An eligible safe same-scope partial implementation diff may use the existing automatic root-completion authority after terminal zero proof; only a separate new owner-private recovery target writer requires an eligible immutable checkpoint and explicit user opt-in.
8. Keep search workers, specification critics, and reviewers read-only. Route code edits to a risk-matched Implementation worker under the same Ready, TDD, minimality, single-writer, validation, and review gates in [adaptive implementation delegation](implementation-delegation.md).

## User model map

`scripts/model_map.py` owns route selection. It loads one complete map in strict project → user → packaged order:

1. `<project>/.codex/openbuild/model-map.toml`;
2. `$CODEX_HOME/openbuild/model-map.toml`;
3. `<build-skill-root>/profiles/openbuild_model_map.toml`.

An existing higher-priority map must validate completely; never merge missing or invalid values from a lower scope. The map covers `discovery.default` plus `critic`, `implementation`, and `review` at low, medium, high, and critical risk. Every route provides an ordered exact-agent sequence, `max_steps`, `escalation_triggers`, stop behavior, and a confirmed failure policy. Map validity is not sufficient by itself: each effective canonical implementation/review profile must declare its exact `routing_rung` with `routing_tuple_confirmed = true`. Known Luna/Terra/Sol model-and-effort tuples must match that rung; an unknown custom tuple needs an explicitly confirmed rung and exact capability smoke. Resolve the map and effective profile before every created agent:

```text
model_map.py resolve --repo <workspace> --codex-home <codex-home> --use-case <discovery|critic|implementation|review> --risk <default|low|medium|high|critical>
```

Persist `map_source`, `map_sha256`, use case, risk, returned agents, and route step with the routing receipt. Invoke `agent_runner.py` only with the exact profile returned for that step. The next step is legal only after a transport-success result contains one of that route's configured semantic triggers.

The map cannot relax the safety envelope: `writer_policy` remains `single`; critic, implementation, and review transport failures remain `block`; search/critic/review remain read-only; implementation remains `workspace-write` under the single-writer lease with `semantic-before-edit` escalation; and discovery keeps targeted-root recovery. Only `discovery.default` may pair `transport_failure = "availability-fallback"` with canonical `availability_fallback_agent = "openbuild_search_balanced"` and a subset of `model-unavailable`/`quota-exhausted`. Absence of both optional fields preserves legacy `block`; complete map scopes never inherit them. A project/user profile override cannot bypass the map envelope by rebinding a safe canonical ID to a different known routing tuple: rung metadata is validated after profile precedence resolves, and fallback additionally requires exact Spark/low and Terra/medium descriptors. Automatic same-scope root-completion is not a map fallback and uses existing authority only after terminal full-tree zero proof, same-lifecycle reconciliation, registry vacancy, and exact scope/diff attribution. Exact `[outside-set-drift]` uses terminal abandonment v1. Exact `[outside-set-drift, preexisting-dirty-overlap]` uses terminal abandonment v2 for a recovery-target and v3 for a legacy `normal-contained` lease; neither route applies to `normal-legacy` or `normal-fallback`. All three finish the current owner lifecycle before routing resumes and authorize neither another map step nor diff acceptance; root completion remains a separate post-vacancy audit. The explicit legacy post-commit root-completion path is also not routing: it accepts no new writer/model, requires same-OS-account confirmation plus exact legacy binding/commit/remediation/Git evidence, and completes or returns closed `blocked` within the retained lifecycle. Only a new owner-private implementation checkpoint recovery writer requires separate explicit user authorization. Every critical route requires `critical_confirmed = true`. Configure it through [the model-map interview](model-map-interview.md).

## Primary explicit-model runtime

The only agent dispatch method is `codex-exec-explicit-model`, implemented by `<build-skill-root>/scripts/agent_runner.py` and requiring Python 3.11 or newer. For every canonical role it resolves the exact profile from `<project>/.codex/agents`, then `$CODEX_HOME/agents`, then the packaged default. It rejects missing or inherited `model` and `model_reasoning_effort`, verifies the role sandbox, validates the effective implementation/review routing rung and known tuple, and requires every search override to preserve the exact canonical Explorer developer instructions. It launches a separate process with argument-vector selection rather than a shell-composed command:

```text
codex exec --json --ephemeral -m <profile-model> -c model_reasoning_effort="<profile-effort>" -c features.multi_agent=false -c forced_login_method="chatgpt" -c model_provider="openai" --sandbox <profile-sandbox> -C <workspace> -o <result> -
```

The runner removes ambient API-key and provider-base-URL variables, requires `codex login status` to report saved ChatGPT authentication, forces the built-in OpenAI provider plus ChatGPT login method, and rejects redirects or custom `model_providers.openai` definitions in the user and every applicable project config layer. It passes the profile contract as developer instructions, snapshots the bounded prompt before `Popen`, sends that immutable snapshot through stdin, disables the stable multi-agent capability mechanically, and records the worker PID, Codex PID, process-group/creation identities, private exact-run artifacts, profile source, JSONL, stderr, and final message. Recovery-capable Windows runs use an authenticated outside-Job guardian as the sole owner of a kill-on-close Job. Linux uses `clone3(CLONE_INTO_CGROUP)` to create the worker inside cgroup v2 before exec, then requires a native worker-private cgroup/mount namespace, read-only cgroup view, zero capabilities/no inherited control descriptors, active write-denial proof and guardian-side membership revalidation; an environment delegation marker alone is never containment proof. Failure before the durable boundary disables recovery before prompt release. Ordinary non-recovery POSIX cancellation still verifies the whole recorded process group even after its leader exits. On POSIX, the run directory is `0700` and artifacts are `0600`; on Windows, current-user-only DACLs protect run and recovery state. Existing locations with weaker ownership or permissions are rejected.

Normal OpenBuild launch uses runner-owned `agent_runner.py dispatch`, which durably writes the unactivated receipt, immediately activates that same creation-bound run, durably writes the activated receipt, then returns. Every invocation sets an explicit external controller timeout of at least 120 seconds (`120000` milliseconds when required by the controller); a shorter implicit default must never own this atomic handshake. That controller budget covers only dispatch preflight/startup/activation and is distinct from the post-activation observation budget. `start` and `activate` remain legacy-compatible diagnostics only. Immediately before a recovery-capable activation, the registry re-captures and compares the exact bound normal or recovery snapshot; drift durably retains an unactivated abort. The activation artifact must repeat the live Codex PID and creation identity and exposes a privacy-safe immutable activation/deadline window. Poll with `status`; use nonterminal `wait --soft-timeout-exit-zero` windows of 45, 90 and 120 seconds followed by the remaining time in one immutable 900-second observation budget. Each returned `status: timeout` keeps the same process, lease and route and is not a CLI failure. At the hard deadline the root records deadline evidence, calls `cancel` automatically, and requires every started process and process group to be positively stopped before any classification; a completion recovered during cancellation finalizes normally. The strict legacy timeout exit remains available when the flag is omitted. Implementation launch additionally requires a pre-existing `--lease-id`, persisted before process creation, followed by a lease/run-bound activation event before edits. A dispatch is proven only when the receipt names the requested agent, configured model, reasoning effort, and sandbox, the readable non-empty result exists, and exactly one terminal JSONL event is its final nonblank event: `turn.completed`. `turn.failed`, malformed or trailing JSONL, missing result/terminal evidence, an unexpected non-zero CLI exit, unknown process liveness, or a stopped process tree without recoverable completion evidence fails the route. A controller timeout before the activated receipt is a transport/controller failure, never activation proof or replacement-writer authority. The CLI selection plus accepted terminal event is operational evidence of the requested model/effort; it is not a cryptographic attestation of provider-internal routing.

If the explicit runner fails, record one of `profile-not-discoverable`, `profile-incomplete`, `cli-unavailable`, `chatgpt-auth-unavailable`, `model-unavailable`, `quota-exhausted`, `sandbox-mismatch`, `runner-failed`, `spawn-failed`, `worker-timeout`, or `unusable-evidence`. `worker-timeout` is valid only after `cancel` confirms every started process stopped; `unusable-evidence` is valid only after a completed result. Only exact structured/model-bound Spark `model-unavailable` or `quota-exhausted` from a coherent pre-turn stream with no JSONL error or completed turn may create one canonical Terra discovery agent through an atomic source claim; unknown/message-only/global limits and all other roles/reasons cannot. Search otherwise uses targeted root recovery. If normal implementation checkpoint capture is unavailable before containment, including `checkpoint byte limit exceeded`, the ordinary `normal-legacy` path uses a domain-separated lowercase SHA-256 of its requested allowed set for reservation and activation instead of an empty binding; this enables no recovery capability. Implementation remains blocked unless either the exact automatic same-scope root-completion branch is eligible under existing authority or a new owner-private checkpoint recovery writer is explicitly authorized; diagnostic root review cannot close an exact-review or release gate. A next configured semantic step is not transport recovery: it is allowed only after a completed semantically insufficient result with a listed trigger.

Routing reports `decision-required` only for a material product, architecture, scope, permissions, privacy, security, destructive, external, or publication choice; missing/ambiguous process, containment, ownership, or safety evidence is `blocked`; exhausted safe executor/route capability is `automation-exhausted`. No classification starts a replacement writer or asks for permission that cannot change the evidence.

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

1. **Configured exact route:** resolve `discovery.default` through `model_map.py`, then run its first returned profile through `agent_runner.py` as `codex-exec-explicit-model`. The zero-setup packaged map starts `openbuild_search_separate` on `gpt-5.3-codex-spark` with low reasoning and a read-only sandbox, captures the full content fingerprint, and requires strict `openbuild.discovery.v1`.
2. **Semantic escalation:** after a completed transport-success search reports a configured evidence gap, advance exactly one step in the returned route and never exceed `max_steps`. Stop on sufficient evidence.
3. **Availability fallback:** only after an exact created Spark process is fully stopped, complete JSONL/stderr collection succeeds, creation-bound `codex-exit.json` evidence is valid, the runner exit exactly rederives from the event stream with no cleanup error, and every explicit error record in its private JSON evidence—including raw top-level `code` and exact raw availability `type` records—normalizes to the same `model-unavailable` or model-specific `quota-exhausted` reason in a coherent pre-turn stream with no JSONL error, completed turn, cancellation, timeout, or result artifact, atomically claim that source once and dispatch canonical `openbuild_search_balanced` Terra with `--search-fallback-source` and the same map/prompt/fingerprint/instructions bindings. The Spark source must carry no fallback source or fallback binding; a preinjected reason is ignored in its public receipt and rejected before claim, while only the owner-generated Terra target binding may expose the normalized source reason. Missing, malformed or identity-mismatched Codex exit evidence and any runner/cleanup error reject fallback. Missing structured evidence or result means only initial no-follow absence. Every present JSONL, stderr, and result read must retain one verified regular non-reparse descriptor identity from pre-open `lstat` through `fstat`, EOF, final `fstat`, and final `lstat`; any directory, symlink, FIFO, other non-regular artifact, unreadable/empty/malformed file, check/open/read replacement, unknown non-protocol `type`, unrecognized error-bearing event, conflicting record—including conflicting `code`/`type` values in one payload or disagreement between JSONL and stderr evidence—or differently normalized reason rejects the complete stream.
4. **Root recovery:** after any ineligible/rejected failure or failed/invalid Terra result, perform only the minimum targeted root search needed and record the normalized failure. No third search agent exists.

Attempt the configured first dispatch once before the first search branch. Do not run root search until it succeeds, one eligible Terra fallback finishes, or the route fails with one recorded reason: `profile-not-discoverable`, `profile-incomplete`, `cli-unavailable`, `chatgpt-auth-unavailable`, `model-unavailable`, `quota-exhausted`, `sandbox-mismatch`, `runner-failed`, or `spawn-failed`. Use `worker-timeout` or `unusable-evidence` only after a selected worker actually runs. Every ineligible failure opens the circuit breaker directly; an eligible stopped Spark failure spends the single fallback claim, then success is consumed or Terra failure opens it. Reset only on a new Build invocation, verified runtime-state change, or explicit user instruction. Do not scrape or infer remaining quota from the private usage dashboard.

Do not block specification-only work merely because the search route is unavailable, but disclose targeted root recovery. Do not silently skip it when the exact route is required.

Before the first repository search, emit the selected worker's unactivated `running` receipt, then matching activation. After it stops, emit its terminal receipt and consume evidence only when `turn.completed`, creation-bound exit zero, strict JSON validation, and equal fingerprints are all valid. Availability receipts additionally record normalized reason, instruction/profile sequence digests and source-handle digest; raw provider errors, prompt snapshot IDs and private paths remain private. After an ineligible or exhausted failure record the reason and use targeted root recovery.

OpenBuild ships reviewed concrete defaults for every canonical role. Project/user overrides may change exact model and effort for normal semantic routes; search overrides keep canonical instructions immutable. The availability fallback is stricter: its route starts with exact Spark, and it runs only when the resolved source remains exact Spark/low/read-only and target exact Terra/medium/read-only. Source-time Spark/Terra profile-file and instruction digests are persisted with the route and must exactly match a claim-time recomputation before the one-shot target starts.

## Critic and review capability order

For specification critics and diff review, use the exact packaged or canonical `openbuild_review_*` profile through the runner. Apply the complexity floor. A diagnostic root pass may record gaps after runner failure but cannot satisfy a required independent closure.

### Exact sequential reviewer dispatch

Resolve the exact starting reviewer through `model_map.py` before every critic or progressive-review ladder, using its classified risk and corresponding use case. Launch the first returned profile through runner-owned `agent_runner.py dispatch`, which durably records the unactivated `running` Review routing receipt, immediately activates that exact run, and returns its activated receipt. Persist the map source/hash and route step, record the matching `review-agent-activated` event from that receipt pair, and require the stopped terminal receipt with `codex-exec-explicit-model`, `turn.completed`, creation-bound exit code zero, valid result evidence, and a semantically completed review; only then use the result. Transport failure blocks the gate instead of selecting another reviewer route.

Run reviewers one at a time in the returned order. Stop after an evidence-backed `ACCEPT` with sufficient confidence, complete acceptance coverage, green validation, and no actionable finding. Move exactly one route step only when the previous structured result records a configured trigger from [the review protocol](review-protocol.md), and stop at `max_steps`. The root adjudicates and remediates confirmed findings through TDD/minimality, reruns affected validation, and only then dispatches the next exact reviewer. Reviewers remain read-only and never fix their own findings.

Emit one unactivated `running` and one stopped terminal Review routing receipt around a matching `review-agent-activated` event. The dispatch event separates canonical `agent_name` from descriptive `task_name`. Both receipts carry the routing-map source/hash/step, `diff_revision`, `risk_floor`, `requested_agent`, `task_name`, `requested_tier`, `dispatch_method`, `configured_model`, `model_reasoning_effort`, `observed_agent`, `observed_model`, `terminal_event`, `activated`, `run_status`, `sandbox`, `dispatch_result`, `fallback_reason`, `process_tree_stopped`, `run_dir`, worker/Codex PIDs and creation identities, `codex_exit_evidence`, `codex_exit_code`, and `result_evidence`. The terminal receipt must preserve the original route and identities and precede `review-result`. Do not repeat the same profile on an unchanged diff or skip a configured intermediate step. If an exact profile or runner is unavailable, record the primary-runtime failure and leave the gate incomplete; create no replacement reviewer.

## Complexity floor

| Class | Typical scope | Minimum starting review tier | Minimum final tier |
|---|---|---|---|
| `low` | Documentation, copy, or local mechanical work | Fast/economy when proven suitable | Fast/economy |
| `medium` | Contained behavior or refactoring with clear tests | Balanced | Balanced |
| `high` | Cross-layer behavior, public contracts, persistence, concurrency, auth, permissions, privacy | Balanced | Balanced unless concrete evidence triggers Strong |
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

Choose an Implementation worker only after the current specification revision passes the Ready gate. Classify the milestone before every lease, resolve `implementation.<risk>` through `model_map.py`, and select the first returned exact profile. The packaged map uses:

- `openbuild_implementation_fast` (Luna/medium) as the low-risk starting route, followed only on valid pre-edit capability evidence by `openbuild_implementation_luna_xhigh`, `openbuild_implementation_balanced` (Terra/medium), `openbuild_implementation_strong` (Terra/xhigh), and terminal `openbuild_implementation_sol_high`;
- `openbuild_implementation_balanced` as the starting route for medium-risk contained logic and high-risk cross-layer behavior, followed by the same-model `openbuild_implementation_strong` before `openbuild_implementation_sol_high`;
- `openbuild_implementation_strongest` (Sol/xhigh) directly for critical work at the deepest supported effort.

Before every test or production code edit, acquire the single-writer lease for the exact selected profile, then launch it through runner-owned `agent_runner.py dispatch` as `codex-exec-explicit-model` with `--lease-id <id>`, repeated `--allowed-file`, `--specification-revision`, and `--recovery-target-milestone`. Separate the canonical `agent_name` from the descriptive `task_name`. The runner durably records the lease-bound unactivated `running` Implementation routing receipt, immediately activates that exact run, and returns its activated receipt; record the routing-map source/hash/step plus `implementation-agent-activated`, and keep the lease active through all worker writes. A completed receipt with `turn.completed`, creation-bound exit code zero, valid result evidence, and a semantically completed task must precede root diff/primary-signal verification. Only private root success finalization, durable `implementation-handoff-accepted` materialization, guardian close, and registry release permit result consumption. A transport-completed semantic `BLOCKED` or verified zero-write `NEEDS_ESCALATION` instead requires private durable `semantic-handoff-rejected` before guardian close and lease release; `NEEDS_ESCALATION` also invalidates the source checkpoint and published recovery artifact before close, release, and next-route approval. A failed or cancelled receipt produces no handoff. An eligible safe same-scope partial diff may continue through automatic root-completion under existing authority. Only a new recovery target writer requires explicit user opt-in and a still-eligible immutable checkpoint rather than transport or model escalation.

Never use `openbuild_search_separate`, legacy `openbuild-discovery`, or `openbuild_review_*` profiles for code edits. Use bounded or sequential exact implementation workers and never run concurrent writers in one checkout.

Pass only the milestone, baseline, allowed files, acceptance criteria, red or primary signal, focused green command, and stop conditions defined in [adaptive implementation delegation](implementation-delegation.md). The root independently verifies the returned diff and validation before review or Git actions.

**Escalate only on evidence.** Before any edit, the selected worker may return `NEEDS_ESCALATION` only after a completed transport-success run with valid terminal evidence, concrete observed model evidence, a stopped process tree, verified zero writes, and a trigger listed by the resolved route. The root first records durable semantic rejection with `checkpoint_invalidation=pending`. Reconciliation must idempotently invalidate the source checkpoint and published recovery artifact and bind `completed`; failure retains the lease. Only then may root authenticate guardian close, release the current lease, record approval, and advance exactly one configured route step without exceeding `max_steps`. Once any edit occurs, the same writer owns the complete milestone and escalation is forbidden. Do not fan out or escalate merely because another model exists, and never repeat an unchanged task at the same step.

Every created implementation agent must have concrete model, effort, and sandbox evidence from the runner receipt. Infrastructure or transport failure—including CLI, authentication, quota, model availability, sandbox, spawn, runner, timeout, or unusable evidence—never authorizes a stronger writer. When the exact route cannot be selected or the semantic handoff fails without a valid pre-edit escalation result, stop before further test or production edits rather than lowering the risk floor, and record the limitation. Do not confuse a user-authorized checkpoint recovery target for the same allowed scope with a stronger model-map writer.

### Automatic continuation boundaries

The root owns automatic continuation after exact lane gates, not a second control plane. It observes a live run through 45/90/120 soft checkpoints and the remaining part of one immutable 900-second observation budget, then records hard-deadline evidence, calls `cancel`, and waits for full-tree stop. Completion recovered during cancel is ordinary completion; an eligible same-scope partial implementation diff uses the existing root-completion authority only after its post-stop attestation. The root never asks whether to continue or cancel.

One fresh same-profile retry is automatic only for `observation-deadline`, `activation-gate-timeout`, or a transport-success zero-write terminal `RETRY_SAME_PROFILE: execution-window-insufficient`, and all three share one `same-profile-retry` budget. It preserves the complete dispatch-time route/profile/revision/milestone/allowed-set binding and obtains a new physical run and applicable writer lease. Transport, infrastructure, authentication, quota, sandbox, provider, containment, scope, map, or profile failure is not a retry branch.

Canonical `NEEDS_ESCALATION: <trigger>` and an unambiguously normalized malformed marker are the only automatic one-rung escalation forms. Their classifier results are `canonical-needs-escalation` and `normalized-malformed-needs-escalation`; both require transport success, exact zero writes, one configured trigger, a stopped source tree, and the lane-specific semantic rejection/invalidation/close/release gate before the next exact profile starts. A second automatic escalation, a changed route family, any edit, a missing trigger, or a transport failure remains blocked. Contained lanes require archive/guardian close/registry vacancy where their owner requires it; legacy and read-only lanes keep unsupported archive/lease evidence null rather than fabricating contained proof.

## `$build configure-models`

Run the complete adaptive procedure in [the model-map interview](model-map-interview.md). `$build setup-models` is a backward-compatible alias and must run the same interview, validation, preview, and permission gates.

### Preflight

1. Verify `codex`, saved ChatGPT authentication, `scripts/agent_runner.py`, discoverable agent roles/profiles, and the model catalog when exposed.
2. Identify whether current official guidance, runtime metadata, or the user confirms a separate-usage search model for this account/surface. Do not infer pool membership from a model slug alone.
3. Identify proven fast, balanced, strong, and strongest coding tiers for optional canonical overrides.
4. If complete exact profiles already provide every proven route, run one launcher smoke per distinct model/effort/sandbox tuple and avoid creating redundant files.
5. If only catalog IDs are available, do not invent usage-pool membership or strength ordering. Use official product guidance, documented `upgrade`, supported reasoning-effort descriptions, runtime tier metadata, or a user-confirmed mapping.
6. Deduplicate roles that resolve to the same effective model, effort, sandbox, and usage pool.
7. Detect canonical underscore IDs separately from legacy hyphenated OpenBuild profiles; never treat filename discovery or `task_name` as exact selection.

### Proposal

The packaged profiles and model map work without setup. Propose only the complete requested map plus canonical profile overrides needed to realize it:

- `openbuild_search_separate`: packaged fast search route; an override may change model/effort only while preserving the exact canonical Explorer instructions and read-only sandbox;
- `openbuild_search_balanced`: optional balanced read-only discovery step;
- `openbuild_search_strong`: optional strong read-only discovery step;
- `openbuild_search_strongest`: optional deepest read-only discovery step;

- `openbuild_implementation_fast`: Luna/medium low-risk starting route, write-capable only inside the parent-approved workspace and a single-writer lease;
- `openbuild_implementation_luna_xhigh`: same-model low-risk reasoning escalation before Terra;
- `openbuild_implementation_balanced`: Terra/medium starting route for medium- and high-risk work;
- `openbuild_implementation_strong`: Terra/xhigh same-model reasoning escalation before Sol;
- `openbuild_implementation_sol_high`: terminal non-critical Sol/high route;
- `openbuild_implementation_strongest`: direct critical-only Sol/xhigh route;
- `openbuild_review_fast` and `openbuild_review_luna_xhigh`: Luna/medium and Luna/xhigh low-risk review steps;
- `openbuild_review_balanced` and `openbuild_review_strong`: Terra/medium and Terra/xhigh review steps;
- `openbuild_review_sol_high`: terminal non-critical Sol/high review step;
- `openbuild_review_strongest`: critical Sol/xhigh review.

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

Map the supported legacy names to canonical runtime-safe IDs without changing their configured model, reasoning effort, sandbox, or developer instructions. The legacy `openbuild-search-separate` name is deliberately excluded because search overrides must adopt the current exact canonical Explorer instructions; report it as inactive and let the interview propose a newly rendered canonical profile instead of copying it blindly.

| Legacy `name` | Canonical `name` |
|---|---|
| `openbuild-implementation-fast` | `openbuild_implementation_fast` |
| `openbuild-implementation-luna-xhigh` | `openbuild_implementation_luna_xhigh` |
| `openbuild-implementation-balanced` | `openbuild_implementation_balanced` |
| `openbuild-implementation-strong` | `openbuild_implementation_strong` |
| `openbuild-implementation-sol-high` | `openbuild_implementation_sol_high` |
| `openbuild-implementation-strongest` | `openbuild_implementation_strongest` |
| `openbuild-review-fast` | `openbuild_review_fast` |
| `openbuild-review-luna-xhigh` | `openbuild_review_luna_xhigh` |
| `openbuild-review-balanced` | `openbuild_review_balanced` |
| `openbuild-review-strong` | `openbuild_review_strong` |
| `openbuild-review-sol-high` | `openbuild_review_sol_high` |
| `openbuild-review-strongest` | `openbuild_review_strongest` |

Before any configuration write, build and show one immutable `plan_id` containing the complete supported mapping, the complete detected-legacy inventory, and a stable `entry_id` for every detected legacy profile. Each entry carries scope-relative source/target paths, a trusted configuration-root fingerprint, legacy/canonical names, source, target, and rendered-canonical SHA-256 values, the complete exact TOML diff, and one action: `create-if-absent`, `already-migrated`, or `config-conflict`. Derive each `entry_id` from its canonical entry serialization and the `plan_id` from the complete mapping, inventory, and entry IDs so an unchanged rerun produces the same identifiers. A missing target is `create-if-absent`; a target matching the rendered canonical SHA-256 is `already-migrated`; a different target hash is `config-conflict` and must not be written.

Ask permission for the displayed plan before writing and persist per-entry authority bound to that entry's exact source, target, and rendered hashes plus planned action. Create approved missing targets atomically without overwriting either legacy or canonical files. Recheck both SHA-256 preconditions immediately before each write; hash drift invalidates only that entry and requires a new exact diff and permission while unchanged entries keep their authority. Record one resumable receipt per entry with the observed source/target preconditions, result hash or `not-written`, and `created`, `already-migrated`, `config-conflict`, or `hash-drift`; never claim a partial run as complete.

Validate TOML, reload or start a new session, verify canonical discoverability and exact selection, then offer legacy cleanup as a separate displayed plan and permission. Never delete or rename a legacy file during canonical creation. This is a guided migration, not a silent bulk rewrite.

### Profile shape

Use the runtime-supported custom-agent schema. Typical generated profiles are:

```toml
name = "<exact canonical openbuild_implementation_* ID from the displayed route>"
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
- Keep search and review profiles read-only. Create every canonical `openbuild_implementation_*` profile with `workspace-write` only after separately showing its exact scope and receiving permission.
- Validate TOML after writing.
- Ask for reload or a new session when configuration discovery needs it, then verify each role with `agent_runner.py`, terminal `turn.completed`, and a semantically successful result.
- Until explicit-model smoke succeeds, report setup as configured but unverified.
- Never commit user-specific overrides to OpenBuild itself; the reviewed packaged defaults are the portable runtime contract.

## Routing record

Record this for each run or milestone:

```text
Complexity: <low|medium|high|critical> — <evidence>
Model map: <source, SHA-256, use case, risk, route step/max_steps>
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
