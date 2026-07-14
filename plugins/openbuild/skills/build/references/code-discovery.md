# Code discovery protocol

Use this protocol before any repository search in every Build mode. The root agent remains the orchestrator, decision owner, durable specification/version editor, Git owner, and final reporter; implementation edits may be leased separately under [adaptive implementation delegation](implementation-delegation.md).

## Mandatory routing rule

1. Treat `rg`, `rg --files`, file or symbol lookup, repository-wide or targeted grep, dependency/route tracing, test/config/schema discovery, similar-pattern search, log scanning, and cross-file flow mapping as search operations covered by this rule.
2. Write a compact search plan with the objective, likely regions, independent branches, minimum evidence, and a stop condition.
3. Use the search usage-pool order in [model routing](model-routing.md). Dispatch the confirmed read-only route before the root runs any new repository search command through `<build-skill-root>/scripts/agent_runner.py`; the primary `codex-exec-explicit-model` route must pin the configured model and reasoning effort. Call `start`, durably record its unactivated running receipt, and only then call `activate`; require the eventual terminal receipt and `turn.completed` before using the evidence. On a recorded runner failure, use a direct native model-plus-effort selector when the runtime exposes both, otherwise pass `openbuild_search_separate` through `agent_name` or an equivalent selector with a separate descriptive `task_name` and record model/effort as unknown. Then use `openbuild_search_fallback`, an explorer role, a generic read-only subagent, or root fallback in that order.
4. Delegate independent search branches in parallel when capacity and scope justify it.
5. Aggregate and deduplicate results, surface contradictions and negative results, then decide whether more discovery is useful.
6. Let the root agent reread already-known critical files and lines before decisions or edits. If verification requires a new grep or lookup, send that search through the same usage-pool order.

Do not ask the user before falling back when a preferred model, profile, subagent slot, quota, or selector is unavailable. Do not treat a generic spawn or task label as exact selection. Open the current-run circuit breaker after a confirmed separate-pool quota/model/profile failure and do not pay for repeated failed attempts on every grep. Do not block the task solely because delegation is unavailable.

Give every worker branch a task-appropriate time and attempt budget. A short parent polling timeout without a final worker result is not by itself a worker failure; keep the user informed while useful work continues. Stop or interrupt a branch when the platform reports failure, quota, or unavailability, when the declared time budget is exceeded, or when two completed attempts return empty or unusable evidence. For an explicit runner process, use `cancel` and confirm both worker and Codex PIDs stopped before recording failure or starting fallback. Record the reason and continue with another worker or targeted root discovery instead of waiting indefinitely.

## Root-only exceptions

The root may read a relevant file directly when its path is already known or verify a returned `path:line` finding without another search. It may search only after the separate-pool and efficient-main worker branches are unavailable or repeatedly fail. Record a material root fallback, but do not pretend that delegation, separate-pool usage, or model switching occurred.

## Discovery worker contract

Give each worker:

- one bounded objective and repository/workspace scope;
- relevant symbols, strings, routes, or behaviors to locate;
- explicit read-only and no-destructive-action boundaries;
- a prohibition on edits, commits, pushes, architecture/product decisions, final user answers, and secret output;
- the evidence format and stop condition below.

Do not ask a discovery worker to implement, refactor, run destructive commands, or execute broad test suites. Use it for search and evidence mapping only.

## Evidence map

Require compact items in this form:

```text
path:line | symbol/component/route | short snippet or signature | confirmed fact and why it matters
```

Also request:

- search methods or terms used;
- relevant negative results;
- confirmed facts separated from uncertainty;
- confidence and any remaining evidence gap.

Keep raw logs, large file dumps, and repetitive matches out of the root context.

## Model and savings claims

- Never infer suitability, price, speed, or strength from a model name.
- Report a concrete model only when the runtime or confirmed profile exposes it.
- Prefer `openbuild_search_separate` only when its separate usage pool is confirmed. A legacy `openbuild-discovery` profile follows the same evidence rule.
- If the separate route is unavailable, prefer `openbuild_search_fallback` with the lowest supported reasoning effort that remains suitable.
- Do not scrape the user's private usage page or guess remaining quota. Treat runtime quota/unavailability errors or explicit user evidence as authoritative for the current-run circuit breaker.
- A different role, prompt, or thread is not proof of a different model or reduced token cost.

## Search routing receipt

Emit two lifecycle receipts for a selected worker. Before the worker's first repository search, record its unactivated `run_status: running` receipt, then record a matching `search-agent-activated` event and activate it. After a successful worker search, record the terminal receipt with unchanged run/process identities and a stopped process tree; only then emit exactly one root-owned, run-bound `search-evidence-consumed` and use its evidence. A failed run never emits `search-evidence-consumed`; its terminal failed receipt must precede a separately identified fallback search/run. The first selected route must be the fixed packaged Spark runner; native selection requires its earlier stopped terminal failed receipt. A failed initial dispatch likewise records one terminal failed receipt before fallback search. Use `none` when no fallback occurred and otherwise use only the failure vocabulary from [model routing](model-routing.md). If a selected worker later times out or returns unusable evidence, preserve the original `search-dispatch: selected` attempt and update the terminal routing receipt to `dispatch_result: failed` before moving to the next route. A `worker-timeout` fallback additionally requires an `agent-cancellation-confirmed` lifecycle event between the running and terminal receipts with the worker PID, `codex_started: <true|false>`, the Codex PID when it started, and `worker_stopped: true`, `codex_stopped: true`; derive it only from the runner's confirmed cancellation receipt. `unusable-evidence` requires a completed worker result rather than cancellation.

```text
search_agent: openbuild_search_separate
task_name: <independent descriptive task label>
dispatch_method: codex-exec-explicit-model | per-spawn-model | exact-custom-agent | unavailable
configured_model: <profile/runtime value or unknown>
model_reasoning_effort: <profile/runtime value or unknown>
sandbox: read-only | unknown before any process starts
observed_agent: <runtime value or unknown>
observed_model: <runtime value or unknown>
terminal_event: turn.completed | turn.failed | none
activated: true | false — false for the pre-search running receipt, true after activation
run_status: running | completed | failed
pool: separate | main | unknown
dispatch_result: selected | failed
fallback_reason: none | profile-not-discoverable | profile-incomplete | cli-unavailable | chatgpt-auth-unavailable | selector-unavailable | model-unavailable | quota-exhausted | sandbox-mismatch | runner-failed | spawn-failed | worker-timeout | unusable-evidence
process_tree_stopped: false while running | true when terminal
run_dir: private run directory
worker_pid: creation-bound worker PID
worker_process_identity: recorded OS creation identity
codex_pid: creation-bound Codex PID
codex_process_identity: recorded OS creation identity
codex_exit_evidence: valid | missing | malformed | identity-mismatch
codex_exit_code: integer | unknown | null
result_evidence: valid | missing | empty | invalid
```

Every terminal `codex-exec-explicit-model` receipt must carry all three exit/result evidence fields. `codex_exit_evidence: valid` requires a non-boolean integer exit code; `missing`, `malformed`, or `identity-mismatch` requires `codex_exit_code: unknown` or null. Accepted completion requires `terminal_event: turn.completed`, `codex_exit_evidence: valid`, `codex_exit_code: 0`, and `result_evidence: valid`. Every failed terminal receipt requires a non-zero exit code, malformed/missing/identity-mismatched exit evidence, or invalid/missing/empty result evidence to independently establish failure, including when JSONL records `turn.failed`.

Bind evidence use to that terminal run:

```text
event: search-evidence-consumed
actor: root
search_agent: openbuild_search_separate
run_dir: <same terminal run directory>
```

The configured model proves only the intended profile mapping. Claim actual model selection or separate-pool usage only when the exact named dispatch or runtime metadata supports it. Treat the usage dashboard as secondary evidence rather than the dispatch acceptance signal.

## Discovery record

Record enough evidence in the specification to resume safely:

```text
Discovery mode: delegated | mixed | root-fallback
Search usage route: separate-pool | main-efficient | role-only | generic-subagent | root-fallback
Observed search model/tier: <verified value or unknown>
Separate-pool attempt: used | unavailable | not configured — <runtime/profile evidence and circuit-breaker state>
Search branches: <objectives and workers>
Search routing receipt: <exact dispatch, configured/observed model, pool, result, and fallback reason>
Evidence map: <key path:line findings>
Fallback or limitations: <quota, selector, profile, failures, or none>
```
