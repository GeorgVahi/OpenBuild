# Code discovery protocol

Use this protocol before any repository search in every Build mode. The root agent remains the orchestrator, decision owner, durable specification/version editor, Git owner, and final reporter; implementation edits may be leased separately under [adaptive implementation delegation](implementation-delegation.md).

## Mandatory routing rule

1. Treat `rg`, `rg --files`, file or symbol lookup, repository-wide or targeted grep, dependency/route tracing, test/config/schema discovery, similar-pattern search, log scanning, and cross-file flow mapping as search operations covered by this rule.
2. Write a compact search plan with the objective, likely regions, independent branches, minimum evidence, and a stop condition.
3. Resolve `discovery.default` through `<build-skill-root>/scripts/model_map.py` before the root runs any new repository search command. Launch its first returned exact profile through runner-owned `dispatch` (`agent_runner.py dispatch`) as `codex-exec-explicit-model`; the runner durably records the unactivated running receipt, captures the full Git tracked + untracked/non-ignored content fingerprint and exact effective map hash/route binding, then immediately activates that physical run. Record matching `search-agent-activated` evidence before the first repository search. Require the stopped terminal receipt, `turn.completed`, exit code zero, strict `openbuild.discovery.v1` validation, and equal pre/reported/post fingerprints before using evidence.
4. Put independent search branches into the current exact worker's prompt when scope justifies them. Advance exactly one configured semantic route step only when a completed search reports a listed evidence trigger and the route has another step. Separately, the one-shot Terra availability fallback may run after an exact stopped Spark attempt only when complete JSONL/stderr collection succeeds, creation-bound `codex-exit.json` evidence is valid, the runner exit exactly rederives from the event stream with no cleanup error, every explicit error record—including raw top-level `code` and exact raw availability `type` records—in a coherent pre-turn stream normalizes to the same structured `model-unavailable` or model-specific `quota-exhausted` reason, and no unknown non-protocol `type`, unrecognized error-bearing event, unreadable/malformed/nonregular JSONL or structured stderr, cancellation, timeout, result artifact of any type, conflicting `code`/`type` value, or JSONL/stderr disagreement exists; dispatch it with `--search-fallback-source <Spark-run-handle> --expected-map-sha256 <same-map-sha256>`, no prompt replacement, and the canonical `openbuild_search_balanced` target. The Spark source request must carry neither a fallback source nor any fallback binding; only the owner-generated Terra target binding may expose the normalized source reason. Missing, malformed or identity-mismatched Codex exit evidence, any runner/cleanup error, or any other transport failure is invalid and cannot authorize fallback. Missing structured evidence or result means only initial no-follow absence; every present JSONL, stderr, and result artifact is read through one verified regular non-reparse descriptor whose identity must match before open, through EOF, and after read. A directory, symlink, FIFO, other non-regular object, unreadable file, check/open/read replacement, empty result or malformed file is invalid and cannot authorize fallback. All other transport/exact-selection/result failures use only minimum targeted root recovery.
5. Aggregate and deduplicate results, surface contradictions and negative results, then decide whether more discovery is useful.
6. Let the root agent reread already-known critical files and lines before decisions or edits. If verification requires a new grep or lookup, send that search through the same usage-pool order.

Do not ask the user before consuming the packaged one-shot Terra fallback or targeted root recovery. Terra is allowed only after exact structured Spark model-access/model-specific-limit evidence and a fully stopped creation-bound process. Message-only, generic account/workspace limits, auth, CLI, network, sandbox, spawn, timeout, runner, malformed result, fingerprint drift, unknown error, replay, cross-run, map/profile/prompt drift, or Terra failure opens the current-run circuit breaker and proceeds directly to targeted root recovery.

Give every worker branch a task-appropriate time and attempt budget. A short parent polling timeout without a final worker result is not by itself a worker failure; keep the user informed while useful work continues. Stop or interrupt a branch when the platform reports failure, quota, or unavailability, when the declared time budget is exceeded, or when the completed attempt returns empty, unusable, or semantically failed evidence. Use `cancel` and confirm both worker and Codex PIDs stopped before classifying an eligible Spark fallback or starting targeted root recovery.

## Root-only exceptions

The root may read a relevant file directly when its path is already known or verify a returned evidence range without another search. It may search after the exact runner records a terminal failure and the one-shot availability route is ineligible, rejected, or exhausted. Record material root recovery and do not pretend another agent or model ran.

## Discovery worker contract

Give each worker:

- one bounded objective and repository/workspace scope;
- relevant symbols, strings, routes, or behaviors to locate;
- explicit read-only and no-destructive-action boundaries;
- a prohibition on edits, commits, pushes, architecture/product decisions, final user answers, and secret output;
- the evidence format and stop condition below.

Do not ask a discovery worker to implement, refactor, run destructive commands, or execute broad test suites. Use it for search and evidence mapping only.

## Evidence map

Require exactly one UTF-8 JSON object with schema `openbuild.discovery.v1`: `schema`, `worktree_fingerprint`, `summary`, `owners`, `couplings`, `tests`, `flows`, `constraints`, and `uncertainties`. `owners`, `couplings`, `tests`, and `flows` are flat evidence arrays; every item directly contains `path`, `line_start`, `line_end`, `symbol`, `reason`, and optional `kind`/`related_path`. Owners and tests are non-empty. `constraints` and `uncertainties` are arrays of bounded strings, never evidence objects or nested structures. Paths are normalized repository-relative inventory members and literal backslashes fail closed. Every range stays inside the current file, satisfies `line_end - line_start + 1 <= 200`, and never combines distant symbols in one item. The canonical rejected evidence segments are `.git`, `.venv`, `.cache`, `.mypy_cache`, `.nox`, `.pytest_cache`, `.ruff_cache`, `.tox`, `__pycache__`, `artifacts`, `coverage`, `dist`, `generated`, `node_modules`, `out`, `target`, and `vendor`; legitimate source directories named `build` remain valid. The runner also rejects unknown fields, missing evidence, oversized output, partial fingerprint inventory, symlink/reparse escapes, and worktree drift. Fingerprinting rejects link/reparse ancestors for regular files, symlinks and gitlinks; final symlink target bytes and gitlink markers are read only between same-object identity checks, without following a symlink target. Checked-out gitlinks contribute a bounded nested tracked plus untracked/nonignored content fingerprint, repeated before and after marker capture so concurrent drift fails closed. Keep raw logs, large dumps, and repetitive matches out of the root context.

## Model and savings claims

- Never infer suitability, price, speed, or strength from a model name.
- Report a concrete model only when the runtime or confirmed profile exposes it.
- The exact route resolved from the effective project, user, or packaged model map is mandatory for created discovery agents. The packaged default is Spark/low first and canonical Terra/medium only for the two exact availability triggers. Legacy complete maps without availability fields keep `block` plus targeted root recovery; map scopes are never merged.
- Do not scrape the user's private usage page or guess remaining quota. Treat runtime quota/unavailability errors or explicit user evidence as authoritative for the current-run circuit breaker.
- A different role, prompt, or thread is not proof of a different model or reduced token cost.

## Search routing receipt

Emit two lifecycle receipts for each exact worker. Runner-owned `dispatch` durably records the unactivated `run_status: running` receipt, activates that same physical run, and returns the activated receipt; record matching `search-agent-activated` before search. After success, require unchanged identities, a stopped tree, valid strict evidence and equal fingerprints before one root-owned `search-evidence-consumed`. A failed Spark receipt may precede exactly one source-bound Terra receipt; the one-shot claim binds source receipt, eligible reason, map hash, source-time and claim-time source/target profile descriptors, instructions digest, prompt snapshot ID/SHA, and target run. Replay, cross-run, second fallback, or drift is rejected before target process start. At the immutable hard deadline, cancel automatically and record `agent-cancellation-confirmed` only after both processes are stopped. Failed or unusable evidence never emits `search-evidence-consumed`.

```text
search_agent: <exact current profile returned by the model map>
map_source: <project | user | packaged path>
map_sha256: <effective map hash>
route_step: <1..max_steps>
task_name: <independent descriptive task label>
dispatch_method: codex-exec-explicit-model | unavailable
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
fallback_reason: none | profile-not-discoverable | profile-incomplete | cli-unavailable | chatgpt-auth-unavailable | model-unavailable | quota-exhausted | sandbox-mismatch | runner-failed | spawn-failed | worker-timeout | unusable-evidence
process_tree_stopped: false while running | true when terminal
run_dir: private run directory
worker_pid: creation-bound worker PID
worker_process_identity: recorded OS creation identity
codex_pid: creation-bound Codex PID
codex_process_identity: recorded OS creation identity
codex_exit_evidence: valid | missing | malformed | identity-mismatch
codex_exit_code: integer | unknown | null
result_evidence: valid | missing | empty | invalid
transport_failure_reason: none | model-unavailable | quota-exhausted
instructions_sha256: <privacy-safe canonical instructions digest>
profile_descriptor_sha256: <resolved profile descriptor digest>
search_fallback_source_digest: <privacy-safe source handle digest or none>
search_fallback_profile_sequence_sha256: <Spark/Terra descriptor sequence digest or none>
```

Every terminal `codex-exec-explicit-model` receipt must carry all three exit/result evidence fields. `codex_exit_evidence: valid` requires a non-boolean integer exit code; `missing`, `malformed`, or `identity-mismatch` requires `codex_exit_code: unknown` or null. Accepted completion requires `terminal_event: turn.completed`, `codex_exit_evidence: valid`, `codex_exit_code: 0`, and `result_evidence: valid`. Every failed terminal receipt requires a non-zero exit code, malformed/missing/identity-mismatched exit evidence, or invalid/missing/empty result evidence to independently establish failure, including when JSONL records `turn.failed`.

Bind evidence use to that terminal run:

```text
event: search-evidence-consumed
actor: root
search_agent: <same exact current profile>
run_dir: <same terminal run directory>
```

The configured model proves only the intended profile mapping. Claim actual model selection or separate-pool usage only when the exact named dispatch or runtime metadata supports it. Treat the usage dashboard as secondary evidence rather than the dispatch acceptance signal.

## Discovery record

Record enough evidence in the specification to resume safely:

```text
Discovery mode: delegated | mixed | root-recovery
Search usage route: separate-pool | root-recovery
Observed search model/tier: <verified value or unknown>
Separate-pool attempt: used | unavailable | not configured — <runtime/profile evidence and circuit-breaker state>
Search branches: <objectives and workers>
Search routing receipt: <exact dispatch, configured/observed model, pool, result, and fallback reason>
Evidence map: <key path:line findings>
Fallback or limitations: <quota, selector, profile, failures, or none>
```
