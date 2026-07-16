# Build: автоматическая оркестрация implementation-агентов

- Status: Complete — R-023 implementation, validation and progressive review passed; root-owned release publication follows the scoped commit.
- Last updated: 2026-07-16
- Original request: выпустить OpenBuild 2.2.1 без контроля внутренних шагов агентной оркестрации со стороны пользователя: автоматически выполнять start→activate, продолжать wait/cancel/handoff, запускать следующий ограниченный профиль после однозначного malformed escalation при нулевом diff и повторять безопасно остановленный zero-write lease с увеличенным timeout. Пользователю задаются только материальные product/architecture/permissions/privacy/destructive/external/publication/scope вопросы.
- Primary signal: детерминированные contract fixtures отклоняют routine operational prompts, подтверждают абсолютный 15-минутный wait/cancel deadline, one-shot same-profile retry и one-step malformed escalation, сохраняя transport, full-tree-stop, zero-write, scope и single-writer gates.
- Review baseline: `main@9306c8a7c20ec884ac4cb329888f9b06633d2695`; исходное состояние чистое (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: reconciliation — новый запрос переоткрывает две завершённые политики 2.2.0.
- Specification revision: R-023
- Complexity: high — меняются user-authority, lifecycle/cancellation, single-writer и semantic-escalation контракты.
- Implementation mode: TDD-first — меняется наблюдаемое поведение Build и проверяемые routing/recovery контракты.
- Version impact: patch `2.2.0` → `2.2.1` — пользователь выбрал точный релиз исправления; manifest остаётся источником версии, changelog и обе README синхронизируются в том же commit.
- Routing mode: `codex-exec-explicit-model`
- Discovery mode: delegated
- Search usage route: separate-pool — exact `openbuild_search_separate`, `gpt-5.3-codex-spark`/low/read-only, terminal `turn.completed`, exit `0`, valid result, stopped process tree; evidence consumed by root.
- Search routing receipt: packaged map `OpenBuild defaults`, SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, discovery/default step 1/1, no fallback.
- Implementation model route: `implementation.high`; balanced zero-write malformed escalation was normalized to the configured trigger, then exact strong completed under the bounded lease.
- Review routing receipt: pending current-revision critic and final diff review.

## 1. Outcome

### Problem

OpenBuild 2.2.0 intentionally asks for fresh user authority after a failed/partial writer and stops automatic observation after 45 → 90 → 120 seconds. In practice this creates repeated pauses even when the safe answer is predetermined: a zero-write worker clearly requests the next configured rung but formats the marker incorrectly, or a live worker simply needs bounded observation and eventual safe cancellation.

### Desired behavior

1. An exact agent that completed transport successfully, changed no file, unambiguously requested capability escalation and supplied a configured trigger is normalized to `NEEDS_ESCALATION` even when its marker syntax is malformed. After its lane-specific rejection/stop/release gate closes—checkpoint invalidation only for applicable contained implementation—OpenBuild automatically approves exactly the next configured route step for the same specification revision, milestone and allowed files.
2. OpenBuild observes one run without user prompts for a total maximum wait budget of 15 minutes, including the existing 45, 90 and 120 second windows. If no terminal result exists at the deadline, it calls `cancel` automatically and proceeds only after authoritative stopped-tree evidence.
3. A cancellation race that yields a valid completed result follows normal root verification/finalization. Otherwise a safe in-scope partial diff receives standing root-completion authority for the same milestone; root audits the diff, preserves TDD/validation/review and never starts a concurrent or replacement writer. Unsafe, out-of-scope or ambiguous state remains blocked without inventing a handoff.
4. A safely stopped zero-write agent that recommends repeating with more time is retried automatically once using a fresh physical run and, only for writer lanes, a fresh lease; exact profile, specification revision, milestone, allowed-set digest and the full 900-second observation budget remain unchanged.
5. Build never asks the user to approve routine agent operations that preserve locked outcomes and safety invariants. It asks only when a choice changes product behavior/scope, architecture/provider commitments, permissions/privacy/security, destructive or external actions, publication, cost/compatibility, or another user-owned outcome. Exhausted safe automation is reported as a blocker rather than converted into an operational permission question.
6. Every exact-agent `start` is followed automatically by `activate` as the immediate next orchestration action after the unactivated receipt is durably captured. No user message, `wait`, cancellation question or repository work may occur between them. If the prompt gate times out before activation and no task action/write occurred, OpenBuild automatically retries the same exact profile once with a fresh run and immediate activation; it never substitutes a different reviewer or root review for the required exact gate.

### In scope

- Build workflow instructions and the routing/delegation contracts for both automatic branches.
- One bounded same-profile retry after a safely stopped zero-write attempt, plus the general operational-versus-user-decision boundary.
- Contract validator and mutation tests that prevent return of the old confirmation prompts.
- English/Russian documentation, changelog and manifest synchronization for 2.2.1.
- Preservation of zero-write proof, exact next-rung selection, checkpoint invalidation, containment, single-writer and root verification.

### Out of scope

- Automatic recovery after transport, authentication, quota, sandbox, provider or containment failure.
- Escalation after any test or production edit.
- More than one automatic next-rung replacement for one malformed result.
- More than one automatic same-profile retry for one logical milestone attempt or reuse of a terminal physical lease/run ID.
- Accepting failed/partial output as a successful handoff without root verification and green validation.
- New dependencies, providers, hosted automation, changes to model-map topology, tag/GitHub Release publication or push without separate authority.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Wait policy | `plugins/openbuild/skills/build/SKILL.md:70`; `references/model-routing.md:44`; `references/implementation-delegation.md:34` | 2.2.0 performs 45/90/120 soft observations, then asks for explicit polling/cancellation and never auto-cancels. | Direct owner of the repeated user interruption.
| Wait runtime | `plugins/openbuild/skills/build/scripts/agent_runner.py:4210-4224` | `wait` already supports arbitrary bounded timeouts and zero-exit soft observations; `cancel` owns safe interruption. | No new process primitive is required.
| Recovery policy | `plugins/openbuild/skills/build/SKILL.md:72`; `references/model-routing.md:13,124,130`; `references/implementation-delegation.md:32,40,178` | Recovery/root completion requires explicit user opt-in; only exact configured `NEEDS_ESCALATION` permits next-rung approval. | These are the conflicting confirmation gates.
| Semantic runtime | `plugins/openbuild/skills/build/scripts/agent_runner.py:3009`; `scripts/recovery_state.py` semantic-rejection owner | The existing private transition already records `blocked|needs-escalation`, zero-write proof, invalidation and release ordering. | The change can reuse the hardened owner layer.
| Contract tests | `scripts/test_validate_package.py:553-616,2962+`; `scripts/test_agent_runner.py`; `scripts/test_recovery_state.py` | Existing tests lock single-writer, explicit handoff authority, soft timeout and zero-write escalation. | Narrow mutations can establish RED before policy edits.
| Version policy | `CONTRIBUTING.md:16-39`; `plugins/openbuild/.codex-plugin/plugin.json:3` | Every commit must bump the manifest and synchronize CHANGELOG plus both READMEs. | Fix ships coherently as 2.2.1.

### Source of truth

The Build skill and its `model-routing.md`/`implementation-delegation.md` references own orchestration and user-authority policy. `agent_runner.py` plus `recovery_state.py` remain the lifecycle/security owners. `validate_package.py` and its unit tests are the executable package contract.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD-auto-continuation-2.2.1.md` | current user request | R-022 / Ready | D-001, D-006..D-010; AC-01..AC-60 | predecessor, workflow/recovery contracts and release policy listed below | yes | root |
| `BUILD-route-recovery-safety.md` | prior user decisions and 2.2.0 release record | header Complete / R-029; stale internal source-map row says In progress | prior D-001 opt-in, T-002 no-auto-cancel, D-003/D-004 routing, D-005 2.2.0 | names `BUILD.md` plus current skill/recovery/routing/validation owners; audited at lines 1-80 and 139-278 | no | header is current lifecycle authority; stale self-row is recorded, not propagated; conflict only for explicitly reopened policies |
| `BUILD.md` | older custom-agent/runtime task | R-014 / In progress | separate M4-M6 host-runtime scope | its source map names the same Build reference set and CONTRIBUTING; audited relevant lines 1-126, 350-385, 660-700 | no | separate predecessor; no scope absorbed |
| `plugins/openbuild/skills/build/SKILL.md` + `references/model-routing.md` + `references/implementation-delegation.md` | current plugin workflow contract | 2.2.0 | polling, exact routing, semantic rejection, recovery/root-completion authority | internal links to code discovery, readiness, TDD, minimality, review and versioning were audited; unaffected safeguards remain normative | yes | two targeted policy conflicts |
| `agent_runner.py` + `recovery_state.py` + contract tests | runtime owner | 2.2.0 | wait/cancel, containment, zero-write, rejection/invalidation, handoff | no outgoing task specification; executable contracts identified by delegated discovery and targeted root reads | only if RED proves necessary | aligned; reuse first |
| `CONTRIBUTING.md` + manifest + CHANGELOG + README files | repository release policy | current 2.2.0 | D-007 version/docs/validation | CONTRIBUTING names SemVer and contributor commands; README links skill source and recovery contract | yes | aligned |

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| Prior opt-in-only recovery vs automatic malformed-marker replacement | evidence-backed reopening of prior D-001 by explicit new user scope | Current user request, 2026-07-16: «разрешим автоматически запускать замену при возврате некорректных маркеров» | narrowed automatic exception; all other recovery remains opt-in |
| Prior no-auto-cancel wait vs 15-minute maximum | new D-006 | Current user request, 2026-07-16: «макс окно ожидания сделаем 15 минут» and request to apply confirmations automatically | 15-minute automatic observe/cancel/root-handoff policy |
| Prior 2.2.0 release target vs 2.2.1 | new D-007 | Current user request, 2026-07-16: «выпустить релиз 2.2.1» | patch target 2.2.1; publication still separately gated |
| Routine agent-operation confirmations vs autonomous workflow | new D-008/D-009 | Current user addition, 2026-07-16: «юзер не должен каждый шаг агентов контролить… их надо автоматом делать» and the web-writer retry example | bounded safe retry/continuation is automatic; only user-owned material decisions are asked |
| Predecessor header `Complete` vs its stale source-map self-row `In progress` | explicit current-file authority at the document header and completed release log | `BUILD-route-recovery-safety.md:3,1148-1159`; stale row retained as historical inconsistency | treat predecessor as Complete/R-029 without editing it |

### Gap

The runtime primitives are safe and sufficient, but the orchestration contract still stops for user confirmation at both target points and the package validator does not prevent that old behavior from returning.

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | `recovery.continuation-policy` | user | resolved after reopen | May OpenBuild continue automatically after a failed implementation result? | Automatically advance one rung for either canonical or unambiguously normalized malformed escalation intent when transport succeeded, a configured trigger exists, full-tree stop and exact zero-write/scope proofs pass. | Prior D-001 was opt-in; current user request plus D-008 explicitly remove routine internal continuation questions on 2026-07-16. | Removes escalation confirmations without turning transport failure into escalation.
| D-006 | `wait.maximum-automatic-window` | user | resolved | How long may Build wait without asking, and what happens at the limit? | One 15-minute maximum automatic observation budget including 45/90/120; then automatic cancel, stop proof and normal/root-completion handoff for a safe same-scope diff. | Current user request and screenshot, 2026-07-16. | Removes repeated polling/cancellation questions while bounding delay.
| D-007 | `release.target-version` | user | resolved | Which version carries the fix? | Stable patch 2.2.1 after local validation/review; push/tag/GitHub Release are not implied. | Current user request, 2026-07-16. | Fixes synchronized version/docs scope.
| D-008 | `orchestration.user-question-boundary` | user | resolved | Which internal agent decisions require user confirmation? | None when the action is bounded, reversible, same-scope and preserves locked product/architecture/security outcomes; ask only for material user-owned decisions or new authority. | Current user addition, 2026-07-16. | Removes operational polling from the user-facing workflow without weakening decision authority.
| D-009 | `orchestration.zero-write-same-profile-retry` | user | resolved | May a safely stopped zero-write worker be repeated with more time? | Automatically retry once with a fresh physical lease/run, same exact profile/revision/milestone/allowed set and a 900-second maximum observation budget. | Current user example, 2026-07-16: web-writer safely stopped and recommends same lease with increased timeout. | Removes the repeat-lease confirmation while bounding loops.
| D-010 | `orchestration.automatic-activation` | user | resolved | Should the user approve or monitor prompt-gate activation? | No. Build durably records the start receipt and immediately activates the same run; an unactivated timeout gets one automatic same-profile fresh retry, never an alternate review substitute. | Current user example, 2026-07-16: reviewer never saw the task because `activate` was omitted. | Makes exact-agent dispatch actually start without exposing an internal gate to the user.

Preserved predecessor decisions: D-002 external patcher scope, D-003/D-004 reasoning-first exact routing and the non-critical/critical route boundaries remain unchanged.

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-101 | On activation, `agent_runner.py` persists privacy-safe UTC `observation_started_at` and `observation_deadline_at = started + 900s` in the activation artifact and exposes both in `status/wait` receipts. In one root lifetime, waits also use a monotonic remaining budget: `min(45, remaining)`, `min(90, remaining)`, `min(120, remaining)`, then `remaining`. Duplicate/early observations never reset or extend it. On reload, the durable UTC deadline is the upper bound; missing/invalid/future-drifted evidence cancels or blocks immediately rather than granting a fresh budget. | selected | A small additive runner receipt field closes reload accounting without changing registry v1. | Same run, process identity, lease, writer, route and model are retained; maximum waiting never resets after root reload.
| T-102 | Parse one authority line only after UTF-8 and CRLF→LF normalization plus leading blank-line removal. The canonical raw form is exactly case-sensitive `NEEDS_ESCALATION: <trigger>` with one ASCII space and `[a-z0-9-]+` trigger. If raw is not canonical, remove at most one leading `>` plus surrounding ASCII whitespace/backticks and match case-insensitive `^(NEEDS(?:_|[ -])ESCALATION|ESCALATION(?:_|[ -])NEEDED):[ \t]*([a-z0-9-]+)$` as normalized malformed. The trigger must occur in the dispatch-time route-family list; the full result must contain no second escalation marker or standalone `BLOCKED`/`COMPLETED`. Reason text may follow only on later non-authority lines. | selected | Disjoint raw/normalized predicates make classification deterministic and fail closed. | Preserves configured-trigger, zero-write, one-step, no-edit and no-infrastructure-escalation invariants.
| T-103 | At the 900-second deadline call existing `cancel`. One terminal disposition ID is consumed exactly once: valid `completed` recovered before/during cancel → normal finalization; otherwise stop proof → scoped-diff classification → root-only completion or blocked. | selected | Reuses cancellation, zero proof and root handoff; explicit ordering prevents double finalization. | Never overlaps writers, never accepts a failed handoff, keeps focused/wider validation and progressive review.
| T-104 | Enforce the behavior through owner docs plus `validate_package.py` mutation tests; change runtime code only if RED exposes a missing primitive. | selected | Current runtime already provides wait, cancel, rejection, invalidation and finalization. | Smallest owner-layer change; no new dependency or duplicate state machine.
| T-105 | Root may recommend one same-profile retry after exactly one verified reason: `observation-deadline`, `activation-gate-timeout`, or transport-success terminal output whose sole authority line is `RETRY_SAME_PROFILE: execution-window-insufficient`. Every branch requires a stopped tree, valid applicable source evidence, zero writes, unchanged logical task/profile/scope, and no infrastructure/auth/quota/sandbox/provider/containment failure. It consumes one logical retry action and creates one fresh plan/run with the full T-101 budget. | selected | Applies D-009 to the closed three-branch retry matrix while remaining fail closed. | No transport replacement, profile escalation, scope drift, concurrent writer or repeated operational question.
| T-106 | Treat operational actions as autonomous technical work only when they preserve all locked D/AC/invariants and remain within existing authority. If no safe branch remains, report `automation-exhausted` with evidence and no yes/no prompt. | selected | The readiness protocol already reserves material product choices for the user; implementation docs currently over-ask for routine lifecycle authority. | User decision authority becomes narrower and clearer, not weaker.
| T-107 | The selected BUILD specification's execution log is the production owner of a closed automatic-action ledger, written by the single root only after lane-specific terminal/full-tree-stop/release evidence: contained additionally requires archive, guardian close and registry vacancy; legacy requires ordinary stop plus lease release; read-only requires terminal full-tree stop. The row precedes any new target lease/root edit. Allowed `kind` is exactly `same-profile-retry|next-rung-escalation|root-completion`; allowed `status` is `authorized|started|completed|blocked`. Each row binds stable public action/source/evidence/scope/route facts with lane-defined nullability and no private fields. | selected | OpenBuild already treats the durable specification/execution log as its resumable decision/lease record while registry remains the contained-process owner. | Crash/reload resumes only the same incomplete ledger action; fabricated lane evidence blocks.
| T-108 | Retry/escalation uses the complete original dispatch snapshot, not a newly interpreted route: privacy-safe map source scope/content hash, use-case/risk, ordered agents, step/max-steps, complete trigger set, exact current/next agent, and effective profile scope/content fingerprint/model/effort/sandbox. Before starting, re-resolve privately and require equality of every projected field; any drift blocks. | selected | Raw source paths remain owner-private; scope enums plus content fingerprints prove precedence/content without disclosure. | Prevents configuration drift from changing the authorized writer after source completion.
| T-109 | Add executable marker/deadline/automatic-action trace validators and mutation tests, and make lifecycle fixtures validate actual receipts/ledger rows in order. Runtime scope explicitly includes runner-owned `dispatch`, unactivated/activated receipt artifacts, activation/deadline fields and a privacy-safe effective-profile fingerprint; registry v1 remains unchanged. | selected | Static prose tokens alone cannot prove replay, race and binding behavior; deterministic runtime fixtures are the established package contract. | Gives executable lifecycle evidence without duplicating containment/recovery state.
| T-110 | Fail closed on root reload and rollback. Reload scans the ledger before any automatic action: `authorized` may start once after all bindings and its exact lane gate revalidate; `started` may only resume the same physical run/root completion; ambiguity becomes `blocked` and never asks a routine question. Package rollback to 2.2.0 additionally requires the owner registry globally vacant/retired as applicable, completed contained outbox/archive/guardian close and no nonterminal 2.2.1 action. | selected | This fences workflow state that registry v1 intentionally does not own without fabricating per-lane evidence. | No budget reset, action replay or downgrade past a pending 2.2.1 action.
| T-111 | Whole-result marker conflict scan canonicalizes every logical line by CRLF→LF, optional single leading `>` and surrounding ASCII whitespace/backticks; case-insensitive full-line marker grammar applies to every line, including fenced text. Exactly one authority line is allowed; any other escalation line or standalone `BLOCKED|COMPLETED` line rejects. | selected | Removes implementation-dependent code-block/quote/token scanning. | AC-05 authorization is deterministic across implementations.
| T-112 | Encode ledger rows as canonical JSON objects owned by `actor="root"`; exact enums, scalar types, lowercase SHA-256 fields, action-ID derivation and append transitions are defined in the canonical evidence subsection. | selected | Closes schema/replay ambiguity without registry changes. | Single-root authority is mechanically validatable.
| T-113 | Persist the complete immutable dispatch snapshot object inside every action row, plus its canonical digest, rather than an opaque digest alone. | selected | Resolver fields and effective profile fingerprint are authoritative inputs. | Every route/profile field is reconstructable and equality-tested before start.
| T-114 | Activation evidence uses exact UTC RFC3339 microsecond timestamps; idempotent activation must byte-match the original artifact, deadline must equal start+900 seconds, and reload follows one deterministic cancel/block sequence. | selected | Removes clock/repeated-activation ambiguity. | D-006 remains bounded across reload.
| T-115 | Bind observation-deadline retry/root-completion to the source activation deadline, hard-deadline observation, terminal cancel receipt, no recovered completion, authoritative pre-snapshot and canonical post-stop attestation with empty outside delta and scoped changed records. Activation-gate and early-window retry instead use their distinct closed evidence rows. | selected | Existing snapshot algorithm supplies stable provenance inputs while the three retry reasons remain disjoint. | Ambiguous/user changes cannot acquire automatic authority.
| T-116 | Every ledger row binds `target_plugin_version="2.2.1"`; rollback scans every automatic-action row in the selected root specification and its mapped task specifications, and proceeds only when all matching rows are terminal `completed|blocked`. | selected | Version/scanning scope becomes explicit and auditable. | 2.2.0 never resumes through an unrecognized pending 2.2.1 action.
| T-117 | Inside runner-owned `dispatch`, enforce `start → durable unactivated receipt → activate → durable activated receipt → return`. The validator rejects an activated receipt without its exact preceding unactivated artifact or any process/run identity drift. An activation-gate timeout is eligible for the same one-shot `same-profile-retry` action only when `activated=false`, prompt release/task events are absent, the process tree is stopped and source snapshot is unchanged. | selected | Preserves the security reason for receipt-before-prompt while the single command makes interleaving impossible. | No task starts before a recorded receipt, and no required exact review is replaced by an unproven fallback.
| T-118 | Add runner-owned `dispatch` as the normal OpenBuild launch command. Inside one invocation it performs start, durably writes the public unactivated dispatch receipt, activates that exact run, writes the activated receipt and only then returns control. On activation failure it keeps/cancels the exact run according to existing containment proof and returns no task result. Legacy `start`/`activate` stay available for compatibility but Build does not use them for ordinary orchestration. | selected | A single runner command provides an authoritative no-intervening-action boundary while preserving receipt-before-prompt ordering. | The prompt gate self-activates from the user's perspective without weakening containment evidence.
| T-119 | Bind every automatic action to `source_disposition_id` and `logical_attempt_id`. Retry/escalation additionally bind preallocated target run/applicable lease plan digests and status-bound target receipt digests; root-completion binds no target and keeps those fields null. Exactly one automatic action of any kind may consume one source disposition, and one logical attempt may consume at most one same-profile retry across all three retry reasons. | selected | Conditional preallocation mirrors actual dispatch versus root-edit lifecycles and makes reload lineage testable. | Fresh physical retry identity is exact and one-shot without fabricating a root target.
| T-120 | Declare a canonical rollback-ledger scan set derived from the closed specification-source graph: resolve every mapped source path relative to the root spec, include only sources declaring task-specification authority, normalize/sort unique paths, reject cycles, duplicates, missing/unreadable sources or an undeclared task-spec edge, then scan all matching 2.2.1 rows for terminality. | selected | Makes rollback scope deterministic instead of relying on prose “mapped specs.” | No pending action can hide in a mapped predecessor/task spec.
| T-121 | Permit exactly two action paths: `authorized → blocked` before dispatch, with target receipt digests null; or `authorized → started → completed|blocked`. On the started path, retry/escalation target receipts must match the exact started run/applicable lease, while root-completion keeps every target plan/receipt field null and uses its action ledger as edit authority. | selected | Makes fail-closed revalidation/dispatch failure and root completion legal without fabricating a target run. | No action can remain ambiguous or require fake terminal receipts.
| T-122 | Separate owner-private runner/resolver receipts from the user-facing/public ledger projection. The ledger allowlist contains only enums, timestamps, canonical IDs and content fingerprints; raw paths, run directories, PIDs, process identities, prompts, nonces and artifacts are forbidden. Legacy raw CLI output remains owner-private and backward-compatible. | selected | Existing runner stdout is an internal operational receipt, not the final/public ledger. | Automatic evidence remains auditable without leaking local/private data.
| T-123 | Exclude each source map's exact self row from rollback graph edges while requiring it as the source declaration. Only distinct normalized task-spec rows create edges; ordinary graph cycle/alias/missing/unreadable checks remain fail closed. | selected | Source maps intentionally contain self declarations. | The declared three-spec scan set is reachable without accepting a real cycle.
| T-124 | Make the ledger total across `contained|legacy|read-only` source/target lanes with state-specific nullability: contained lanes require archive/lease bindings; legacy/read-only lanes use terminal receipt plus stopped-tree evidence and null unsupported archive/lease fields. | selected | Current runtime intentionally has no recovery registry/archive for read-only and some legacy runs. | Universal auto-activation/retry can be represented without fabricated evidence.
| T-125 | Define canonical dispatch plan and privacy-safe public receipt projections with domain-separated digests and a private-to-public projection validator. | selected | Opaque digests alone cannot prove plan/receipt lineage; raw internal receipts remain private. | AC-24/25/28 become executable without exposing local identifiers.
| T-126 | Make error terminalization state-aware: revalidation/dispatch error before start is `authorized→blocked`; any later validation/receipt error is `started→blocked` using the last valid target receipt projection. | selected | Both paths already exist in the allowed transition graph. | No malformed action remains nonterminal or fabricates pre-start state.
| T-127 | Enforce an exact `kind × source_lane × target_lane` matrix and lane-specific pre-action ordering, defined in canonical evidence below. | selected | Prevents universal contained ordering from fabricating evidence for legacy/read-only lanes. | Every promised automatic branch has one legal evidence path.
| T-128 | Limit both same-profile retry and automatic next-rung escalation to one per `logical_attempt_id`; root completion also consumes the mutually exclusive source disposition. | selected | D-001 authorizes one malformed-marker replacement, not an automatic ladder. | A replacement cannot recursively escalate again without a new material decision/authority.
| T-129 | Persist `target_run_plan_digest` before process creation. `dispatch --adopt-plan <digest>` scans the owner-private run root: zero physical matches dispatches the persisted plan once; exactly one matching plan-bound run returns/adopts that run; multiple or mismatched matches fail closed. | selected | Closes both sides of the crash boundary without duplicating a physical run. | Authorized resume never creates an orphan duplicate, including read-only lanes.
| T-130 | Let the trusted projection layer emit either a normal public receipt or a canonical projection-error receipt bound to the plan/action and stopped-tree result. The latter can terminalize `started→blocked` without accepting task evidence. | selected | A malformed first private receipt still needs a legal fail-closed terminal row. | Rollback and reload never remain fenced by an unrepresentable error.
| T-131 | Complete canonical route, lease-plan and receipt relational schemas, including action/plan/route bindings and exact per-state nullability. | selected | Standalone hashes do not prove lineage. | Every public digest is independently derivable and cross-checked.
| T-132 | Rollback groups append-only ledger rows by `action_id`, validates each complete chain, and requires only the latest valid state to be terminal; historical authorized/started rows remain evidence. | selected | Append-only history must not be mistaken for current nonterminal state. | Completed/blocked actions no longer fence rollback forever.
| T-133 | Persist route-wide configured triggers unchanged and bind a separate exact `next_profile` public fingerprint object whenever `next_agent` exists. | selected | Resolver triggers describe the route, while current/next profiles have distinct tuples. | Escalation target is independently proven without corrupting terminal route evidence.
| T-134 | Close every canonical object/domain/cross-equality, source-evidence derivation and projection error enum in the evidence section. | selected | Validators need one result, not delegated matrices. | Fabricated lineage/error values fail deterministically.
| T-135 | Require a canonical dispatch plan for every exact run, automatic or ordinary. Root persists it before `dispatch`; crash recovery always uses the single form `dispatch --adopt-plan <digest>` to activate/resume/cancel the exact plan-bound run, never redispatch blindly. | selected | Ordinary dispatch has the same crash window as automatic retries. | D-010 survives root crash for every agent lane.
| T-136 | Add a third same-profile retry reason `early-window-insufficient`, accepted only from transport-success, zero-write, terminal output with canonical authority line `RETRY_SAME_PROFILE: execution-window-insufficient`. | selected | Applies D-009 to the user's early safe-stop example without treating infrastructure failure as retry evidence. | Same one-shot retry budget and exact scope/profile rules remain unchanged.
| T-137 | Derive `authorization_id` from source/scope/route-family evidence before allocating any applicable plans; set `action_id` from authorization plus the resulting target plan digests, which are both null for root-completion. | selected | Removes circular action↔plan hashing while preserving root target nullability. | Allocation/replay order is deterministic.
| T-138 | Split immutable source/target step snapshots from one stable `route_family` object. `logical_attempt_id` binds the family, not a mutable step, so automatic escalation cannot reset its budget. | selected | Retry preserves step; escalation advances exactly one step within the same family. | Source and target tuples are independently proven.
| T-139 | Bind selected trigger/classifier result, retry reason, cancel reason, prompt-release proof, stopped-tree and post-stop attestation through exact canonical evidence objects/domains and state tables. | selected | No authorization may depend on an unrecorded inference. | Every automatic branch is locally testable.
| T-140 | Give every ordinary dispatch a fresh 128-bit public `dispatch_generation_id` and an append-only root dispatch-attempt chain `planned→started→terminal|blocked`; adoption only resumes the same nonterminal generation. | selected | Identical later tasks must not collide with old plan bytes. | Ordinary crash recovery is unique and consumed.
| T-141 | Preserve the resolver-returned `escalation_triggers` list byte-for-byte, including order and duplicates. Require it non-empty only when `max_steps > 1`; a one-step route may return either an empty or non-empty list. | selected | Exactly matches the current model-map validator instead of tightening runtime configuration out of scope. | Trigger evidence and runtime owner agree.
| T-142 | Define one closed three-row retry matrix for observation deadline, activation timeout and early window, all sharing the same one-retry logical-attempt budget. | selected | Removes stale “both/two” wording. | D-009 has exactly three deterministic safe predicates.
| T-143 | Represent canonical and normalized-malformed escalation as separate exact classifier results under the same bounded one-rung authority. | selected | Closes the D-001/D-008 contradiction without broadening transport recovery. | Both safe forms are automatic and testable.
| T-144 | Define canonical stopped-tree and post-stop attestation objects, digest domains and receipt cross-equalities. | selected | Every source authority must be locally derivable. | Cancel/recovery facts cannot be inferred from prose.
| T-145 | Include every current criterion through AC-60 in M1 acceptance and validation coverage. | selected | Latest closure requirements are part of the same release milestone. | No readiness criterion can be omitted from green.
| T-146 | Treat route triggers as resolver evidence, not a normalized set. | selected | Avoids mutating supported one-step/duplicate configurations. | Runtime compatibility is preserved.
| T-147 | Persist the nonterminal observation-timeout receipt separately from the subsequent terminal cancellation receipt and bind both into source evidence. | selected | `timeout` remains an observation, never a terminal result. | Deadline classification is replay-safe without contradicting runner states.
| T-148 | Define canonical escalation from the exact raw marker and normalized malformed escalation from every other accepted normalized form. | selected | Makes the two classifier rows disjoint and exhaustive. | Canonical output is not mislabeled malformed.
| T-149 | Persist an exact observation-stage receipt distinguishing 45/90/120 checkpoints, hard deadline and activation-gate timeout before any cancellation. | selected | A soft poll timeout can never authorize cancel/retry. | Reload expiry records hard-deadline evidence first.
| T-150 | Cross-bind prompt-release proof to the same run/plan in both observation and terminal receipts. | selected | Prevents borrowing a no-prompt proof from another run. | Activation retry remains exact-run only.
| T-151 | Keep both legal automatic-action paths: pre-start `authorized→blocked` and post-start `authorized→started→completed|blocked`. | selected | Aligns acceptance text with the closed state machine. | Validation errors cannot strand an action.

### Pending proposals

- None.

## 4. User scenarios

### Malformed escalation marker with zero writes

1. An exact implementation or read-only agent completes with `turn.completed`, exit 0 and a valid result that clearly asks for the next configured rung with a configured trigger, but its marker syntax is not canonical.
2. Root proves the complete authoritative source snapshot is byte-equal and no allowed/outside/control-plane write occurred.
3. Root records `needs-escalation` and completes the exact source lane's rejection/stop/release gate; only applicable contained implementation performs checkpoint invalidation, containment close and lease release.
4. Without asking the user, root records automatic approval and starts exactly the next configured profile for the same revision, milestone and allowed files. A second malformed result does not create another automatic replacement.

### Writer exceeds the wait budget

1. Build observes the same run through 45, 90, 120 and one remaining bounded window, without asking whether to continue.
2. If no terminal receipt exists when the total reaches 900 seconds, Build automatically calls `cancel`.
3. Only a receipt proving the whole process tree stopped allows continuation.
4. A completion race uses normal finalization. A safe partial diff is audited and completed root-only under the same acceptance/validation contract. Ambiguous/out-of-scope state remains blocked.

### Safely stopped zero-write worker requests more time

1. The old physical process tree is proven empty, the terminal run has no accepted handoff, and the authoritative snapshot proves zero writes.
2. Root records `automatic_retry_used` for the logical attempt and completes the source lane's stop/release gate; archive/lease evidence is present only where that lane owns it.
3. Without asking the user, Build creates one fresh run and, for a writer target only, a fresh lease with the same exact profile, specification revision, milestone and allowed-set digest, then applies the full 900-second deadline.
4. A second same-profile retry request is not repeated; Build follows another already-authorized safe branch or reports `automation-exhausted` without an operational confirmation question.

### Prompt gate was not activated

1. `start` returns an unactivated exact-runner receipt and OpenBuild durably captures it.
2. The immediate next orchestration action is `activate` for that same run; the user sees no checkpoint question.
3. If the activation gate already expired, root proves `activated=false`, no prompt/task event, stopped tree and unchanged snapshot, records `same-profile-retry` with reason `activation-gate-timeout`, then starts one fresh identical run and immediately activates it.
4. Review/critic gates still require the same exact profile and independent result; root review or another unspecified method cannot substitute for the failed unactivated attempt.

### Errors and edge cases

- Malformed output does not contain a configured trigger or clear escalation intent -> blocked; no automatic writer.
- Any file/control-plane write occurred before escalation -> no escalation/replacement.
- Route has no next step or automatic replacement already used -> blocked.
- Transport/auth/quota/sandbox/provider/containment failure -> blocked; no escalation.
- Cancellation cannot prove full-tree stop or liveness is unknown -> quarantine; no root edit or replacement.
- Partial diff touches forbidden paths or introduces a product/architecture choice -> blocked and reported.
- Same-profile retry would change profile, risk, scope, revision or allowed digest, or the retry bit is already consumed -> reject and report without asking for permission.
- Dispatch-time map hash/profile tuple no longer matches before a retry or next-rung start -> `automation-exhausted`; never reinterpret authority from the new map.
- Root reload finds missing/deadline-drifted timing evidence or an ambiguous ledger row -> cancel/block immediately, preserve safety, and do not ask for a routine approval.
- Any event/action occurs between unactivated receipt and `activate`, or activation retry lacks proof that the prompt never opened -> block; never infer that review happened.

## 5. Requirements and acceptance criteria

- [ ] AC-01: No user prompt occurs after the 45, 90 or 120 second observations; all are part of one 900-second automatic observation budget for the same run.
- [ ] AC-02: At 900 seconds without a terminal result, Build calls `cancel` automatically and performs no handoff/edit/replacement until full-tree stop is proven.
- [ ] AC-03: A valid completion racing with cancellation follows the existing successful root verification/finalization path.
- [ ] AC-04: A safe partial diff after cancellation may be completed root-only without another user confirmation, but is never recorded as the failed worker's accepted handoff.
- [ ] AC-05: An unambiguous malformed escalation intent is normalized only with valid transport/terminal/model evidence, a configured trigger, exact zero-write proof and a next route step.
- [ ] AC-06: Automatic malformed-marker continuation advances exactly one configured rung, once, with unchanged specification revision, milestone and allowed-file digest.
- [ ] AC-07: Infrastructure/transport failure, any edit, scope drift, missing trigger, invalidation failure or route exhaustion never authorizes automatic replacement.
- [ ] AC-08: Existing checkpoint invalidation, containment close, single-writer lease, semantic rejection, root verification and archive invariants remain enforced.
- [ ] AC-09: Validator mutation tests fail when either automatic policy is removed or weakened; focused and full package suites are green.
- [ ] AC-10: Manifest, CHANGELOG and both README files consistently describe stable release 2.2.1 in English/Russian.
- [ ] AC-11: A safely stopped zero-write attempt may create exactly one fresh same-profile retry with the identical revision/milestone/allowed digest and a new physical lease/run; it never reuses the old identity or silently escalates.
- [ ] AC-12: Build does not ask for routine wait/cancel/retry/escalation/handoff approvals covered by D-001/D-006/D-008/D-009; it asks only when a material user-owned outcome or new authority is required.
- [ ] AC-13: When safe automation is exhausted or blocked, EN/RU guidance states the non-sensitive reason, confirms no writer will start, and names the missing evidence/user-owned decision without asking a routine yes/no question.
- [ ] AC-14: Every automatic action has one replay-safe durable trace after its lane-specific terminal/stop/release gate and before the first new lease/root edit; contained additionally requires archive/guardian close/registry vacancy, while legacy/read-only never fabricate them.
- [ ] AC-15: Classifier and trace validators execute deterministic positive/negative fixtures for grammar, route drift, duplicate action/start, crash-resume and cancel/root-completion ordering; prose-only mutation coverage is insufficient.
- [ ] AC-16: `status/wait` receipts expose immutable activation start/deadline evidence; reload cannot reset the 900-second budget, and missing/drifted evidence fails closed.
- [ ] AC-17: The production automatic-action ledger has a closed schema/enum, rejects private/unknown fields, binds post-stop diff attestation and the complete route/profile snapshot, and fences rollback until every action is terminal.
- [ ] AC-18: Canonical action rows validate exact event/actor/version/enums/types/digests, derive `action_id` from immutable canonical JSON, and allow exactly `authorized→blocked` before start or `authorized→started→completed|blocked`, with one row per state.
- [ ] AC-19: Full route snapshot persistence/revalidation covers map source/scope/hash/use-case/risk, ordered agents, step/max-steps/triggers/current/next agent and effective profile source/fingerprint/model/effort/sandbox.
- [ ] AC-20: Observation-deadline same-profile retry is authorized only after the immutable 900-second deadline caused cancellation, no valid completion was recovered, the exact source tree stopped, and authoritative pre/post evidence proves zero writes; activation-gate retry is governed separately by AC-23.
- [ ] AC-21: Root completion binds a canonical pre/post attestation and empty outside delta before `started`; rollback scan rejects any mapped nonterminal 2.2.1 action.
- [ ] AC-22: Every exact agent is activated immediately after its durably captured unactivated receipt, with no user message, wait/status/cancel or task/repository action in between.
- [ ] AC-23: An activation-gate timeout with no prompt/task/write may create exactly one fresh same-profile retry and immediate activation; exact critic/review gates are never replaced by root or an unspecified method.
- [ ] AC-24: Normal OpenBuild agent launch uses one runner-owned `dispatch` command that persists unactivated then activated receipts for the same run before returning; no root/user/repository action can interleave.
- [ ] AC-25: Every automatic action binds one source disposition/logical attempt; retry/escalation additionally bind preallocated target run/applicable lease plans and exact started receipts, while root-completion keeps all target fields null. Retry reasons share one same-profile budget.
- [ ] AC-26: Rollback scan derives a complete normalized task-spec graph and fails closed on cycle/duplicate/missing/unreadable/undeclared edges or any nonterminal matching 2.2.1 action.
- [ ] AC-27: Automatic-action validation accepts `authorized→blocked` with null target receipts; started retry/escalation rejects fabricated/missing applicable target receipts, while started root-completion requires all target plan/receipt fields to remain null.
- [ ] AC-28: Public ledger/agent reporting rejects raw map/profile/run paths, PIDs, process identities, prompts, nonces and artifacts; source/profile equality uses scope enums plus content fingerprints.
- [ ] AC-29: `agent_runner.py dispatch` is implemented and runtime-tested as the normal OpenBuild path; legacy `start`/`activate` remain compatible.
- [ ] AC-30: Rollback traversal treats exact self rows as declarations, not edges, while rejecting every distinct-path cycle or alias.
- [ ] AC-31: Ledger validation supports contained, legacy and read-only lanes without fabricated archive/lease values and enforces exact lane-specific required/null fields.
- [ ] AC-32: Canonical dispatch plan and public receipt objects derive target plan/receipt digests and validate projection from the owner-private legacy receipt.
- [ ] AC-33: Before-start errors terminalize `authorized→blocked`; after-start errors terminalize `started→blocked`, so no action remains nonterminal from a validation failure.
- [ ] AC-34: The lane/action matrix permits only same-lane retries, same-family next-rung escalation and implementation-only root completion, with lane-specific stopped/release/archive ordering.
- [ ] AC-35: One logical attempt can consume at most one same-profile retry and one automatic next-rung escalation; a replacement cannot auto-escalate again.
- [ ] AC-36: After a root crash, a plan-bound orphan run is found/adopted exactly once by plan digest or blocks; it is never redispatched.
- [ ] AC-37: A first public-projection failure after physical start produces a canonical plan-bound projection-error receipt and legally terminalizes `started→blocked`.
- [ ] AC-38: Lease plan, dispatch plan and every public receipt state have exact schemas/domains/nullability and repeat action/plan/route bindings.
- [ ] AC-39: Route snapshots enforce agent/step/ceiling/trigger/use-case/risk/effort/sandbox relations, not just scalar types.
- [ ] AC-40: Coverage and fixtures enumerate every autonomous branch authorized by D-008..D-010 rather than “two named branches.”
- [ ] AC-41: Rollback validates complete action chains and evaluates terminality from each action's latest state, not every historical row.
- [ ] AC-42: Route snapshots preserve configured triggers and bind both current and exact next-profile public tuples/fingerprints.
- [ ] AC-43: All canonical evidence objects, enum domains, ID/digest derivations, state nullability and cross-object equalities are locally complete.
- [ ] AC-44: Every ordinary/automatic exact dispatch has a persisted plan and uses `dispatch --adopt-plan` after crash to resume the same run.
- [ ] AC-45: A terminal transport-success zero-write `RETRY_SAME_PROFILE: execution-window-insufficient` result may consume the same one-shot retry budget before the hard deadline; arbitrary or infrastructure failures may not.
- [ ] AC-46: Authorization, plan and action IDs form an acyclic canonical derivation with no self-reference.
- [ ] AC-47: Stable route-family plus separate source/target step snapshots bind exact escalation/retry tuples without resetting logical-attempt budgets.
- [ ] AC-48: Canonical evidence records classifier/trigger/retry/cancel/prompt-release/stopped-tree/attestation facts and exhaustive receipt state/nullability.
- [ ] AC-49: Every ordinary dispatch has a unique durable generation chain; adoption cannot reuse a terminal generation for a later identical task.
- [ ] AC-50: Trigger evidence matches the resolver exactly: preserve the returned ordered list; require non-empty only for multi-step routes.
- [ ] AC-51: One closed three-branch retry matrix shares one retry budget and rejects every other stop/failure reason.
- [ ] AC-52: Canonical and normalized-malformed safe escalation each have an exact classifier value and advance one configured rung without a prompt.
- [ ] AC-53: Stopped-tree and post-stop attestation objects have exact schemas/domains and bind to terminal/cancel receipt facts.
- [ ] AC-54: M1 and its validation matrix cover every current criterion through AC-60.
- [ ] AC-55: One-step routes preserve any resolver-returned trigger list; no out-of-scope uniqueness or emptiness constraint is introduced.
- [ ] AC-56: Deadline/activation classification binds one nonterminal observation-timeout receipt and one later terminal cancellation receipt; `timeout` never becomes terminal.
- [ ] AC-57: Exact raw `NEEDS_ESCALATION: <trigger>` classifies canonical; every other accepted normalized spelling classifies malformed, with no overlap.
- [ ] AC-58: Persisted observation stages distinguish 45/90/120 soft checkpoints from hard-deadline and activation-gate expiry; only the latter two can precede cancel classification.
- [ ] AC-59: Reload at/after the immutable deadline persists hard-deadline observation evidence before cancellation.
- [ ] AC-60: Prompt-release proof run binding equals both observation and terminal source receipt bindings.

### Invariants

- One active writer; root never edits while a worker lease is live.
- `status: timeout` remains non-terminal and strict wait without the soft flag retains exit 3.
- Failed/partial output never emits `implementation-handoff-accepted`.
- No automatic model/profile change follows infrastructure, transport or containment failure.
- Critical routing, model-map topology, sandbox and exact-profile evidence are unchanged.
- Automatic retry/escalation counters are one-shot action IDs in the durable root trace and cannot reset on root reload or wording changes.

## 6. Technical boundaries

### Affected layers and contracts

- `SKILL.md` — top-level 900-second observation/cancel and malformed-marker authorization.
- `references/model-routing.md` — exact route and failure boundaries.
- `references/implementation-delegation.md` — lease, root-completion and one-shot malformed escalation rules.
- readiness/question boundary references as needed — operational actions are not user-owned decisions merely because an agent stopped.
- `scripts/validate_package.py` + `scripts/test_validate_package.py` — executable text-contract and mutation tests.
- README/CHANGELOG/manifest — 2.2.1 release communication.
- `agent_runner.py` — add runner-owned `dispatch`, durable unactivated/activated receipt artifacts, privacy-safe activation/deadline/profile fingerprint evidence and runtime tests; recovery registry v1/state machine stays unchanged.

### Data and migration

No registry or user-data migration. Existing 2.2.0 owner-private registry remains authoritative for contained process/lease ownership and compatible at the same reader floor. New automatic authority uses the selected BUILD execution log's closed ledger schema after the exact source lane's terminal/stop/release gate; activation/deadline fields are additive run-receipt evidence, not registry state. Ledger rows are retained with the task specification and contain only public digests/enums.

### Security and privacy

No private run paths, PIDs, nonces, prompts or raw checkpoint data enter public docs/receipts. Automatic decisions consume only existing public/owner-private proofs.

### Performance and concurrency

Maximum automatic observation is one immutable 900-second activation deadline plus a live monotonic remaining budget; intermediate observations and root reload cannot reset it. Polling reuses the same process and lease; cancellation/root completion begins only after zero-process proof. A retry uses a fresh physical lease/run and a separate one-shot budget.

### Observability and errors

Record whether completion was `normal`, `cancel-race-completed`, `auto-root-completion`, `auto-malformed-escalation`, `auto-same-profile-retry`, `automation-exhausted`, or `blocked`, without exposing private identifiers. For blocked/exhausted outcomes, EN/RU user guidance says no writer was started and identifies the missing safe evidence or material decision.

### Automatic action and cancellation ordering

| Evidence/state | Automatic action | Terminal disposition | User prompt |
|---|---|---|---|
| live run before absolute deadline | wait for `remaining`; preserve same lease/run/profile | none | never |
| terminal completion observed before or recovered during cancel | stop proof, root verify, `_finalize-success` | `normal` or `cancel-race-completed` exactly once | never |
| one of the three exact retry predicates, tree stopped, zero diff | satisfy the source lane's close/release gate; one fresh same-profile retry if unused | `auto-same-profile-retry` | never |
| deadline reached, tree stopped, same-scope partial diff | release failed handoff; consume standing root-completion authority once; root verifies/fixes/tests | `auto-root-completion`, never worker handoff | never |
| zero-write valid/malformed escalation grammar and configured trigger | apply the lane-specific rejection/close/release gate, including checkpoint invalidation only when contained implementation requires it; next exact rung once | `auto-malformed-escalation` | never |
| unknown liveness, forbidden diff, validation failure, route/retry exhaustion or material new decision | quarantine/block; no new writer/root edit | `blocked` or `automation-exhausted` | only for the material user-owned decision, never for routine continuation |

Lane/action matrix:

| Kind | Allowed source → target | Required pre-action ordering |
|---|---|---|
| `same-profile-retry` | `contained→contained`, `legacy→legacy`, `read-only→read-only` | contained: terminal → full-tree zero → archive/guardian close/registry vacancy; legacy: terminal → ordinary full-tree stop → lease release; read-only: terminal/activation failure → full process-tree stop. All require exact zero-write/snapshot proof. |
| `next-rung-escalation` | `contained→contained` or `legacy→legacy` implementation; `read-only→read-only` critic/review | same lane-specific stop/release order; implementation additionally requires semantic rejection/checkpoint invalidation where applicable. Cross-family/read-only-to-writer transitions are forbidden. |
| `root-completion` | `contained→root`, `legacy→root` implementation only | contained archive/vacancy or legacy terminal/stop/release, then post-stop attestation; read-only/root sources are forbidden. |

No other lane/kind combination validates. A `logical_attempt_id` may contain at most one automatic `next-rung-escalation` and at most one same-profile retry total; consuming either does not reset through the replacement's new source disposition. One source disposition remains mutually exclusive across all kinds.

Root-completion eligibility is exact and applies only to implementation source lanes `contained|legacy`: the old tree is stopped and lease released; contained requires its archive digest, while legacy requires its valid terminal receipt and complete ordinary process-tree stop proof with null archive. A canonical post-stop worktree/diff attestation is captured and bound to the action before any root edit; changed paths are a subset of the original allowed set and attributable to that run; specification revision/milestone/allowed digest are unchanged; no product/architecture/permission/privacy/external/destructive choice appeared; root satisfies the risk floor; focused validation can be reproduced. The authority is one-shot and `started` is durably recorded before the first root edit. Same-scope remediation may continue under that one action; validation failure eventually records `blocked` and cannot manufacture another retry/replacement. Read-only agents never use root completion.

The root-owned automatic-action ledger is ordered `old terminal receipt → full-tree zero proof → semantic/failure disposition → checkpoint invalidation when applicable → lane-specific close/release gate → automatic-action authorized → started → completed|blocked`. The close/release gate is exact: contained requires terminal archive, guardian close and registry vacancy; legacy requires ordinary full-tree stop and lease release with null archive; read-only requires terminal full-tree stop with null archive/lease. A stable `authorization_id` is derived from source authority before applicable plan allocation; the stable `action_id` then binds that authorization to the target plan digest pair, which is `(null,null)` for root-completion. Neither contains PID, run path, nonce or prompt. An `authorized` action may resume only after re-verifying its lane gate and every binding; `started` without terminal completion resumes the exact target receipt/root task and never creates another. Duplicate, mismatched, fabricated or out-of-order evidence blocks.

### Canonical automatic-action evidence

Each ledger line is one UTF-8 canonical JSON object (`ensure_ascii=false`, sorted keys, separators `,`/`:`, LF terminator) with exactly these fields: `event="automatic-action"`, `actor="root"`, `target_plugin_version="2.2.1"`, `authorization_id`, `action_id`, `source_disposition_id`, `logical_attempt_id`, `source_lane`, `target_lane`, `kind`, `status`, `selected_trigger`, `classifier_result`, `retry_reason`, `cancel_reason`, `prompt_release_proof_digest`, `source_observation_digest`, `source_terminal_digest`, `source_archive_digest`, `evidence_digest`, `pre_snapshot_digest`, `post_snapshot_digest`, `post_stop_diff_digest`, `specification_revision`, `milestone`, `allowed_set_digest`, `route_family`, `route_family_digest`, `source_route_snapshot`, `source_route_snapshot_digest`, `target_route_snapshot`, `target_route_snapshot_digest`, `current_agent`, `next_agent`, `retry_count`, `target_run_plan_digest`, `target_lease_plan_digest`, `target_run_receipt_digest`, `target_lease_receipt_digest`. No other field is allowed. Digests/IDs are lowercase 64-hex strings unless explicitly nullable below; revision/milestone/agent IDs are non-empty ASCII identifiers; lanes are exactly `contained|legacy|read-only|root`. `next_agent` is null only for root completion, equals `current_agent` for same-profile retry, and equals the target snapshot agent for escalation. `retry_count` is integer 0 or 1; booleans are never integers. `kind` is exactly `same-profile-retry|next-rung-escalation|root-completion`; `status` is exactly `authorized|started|completed|blocked`; retry/classifier/cancel fields follow the closed evidence matrix below.

`route_family` is exact public `{map_source_scope,map_sha256,use_case,risk,agents,max_steps,escalation_triggers}`. Source scope is `project|user|packaged`; use case is `implementation|critic|review`; risk is `low|medium|high|critical`; agents are ordered unique and `max_steps == agents.length`. `escalation_triggers` is the resolver-returned ordered list without deduplication or normalization; it must be non-empty when `max_steps > 1`, while either cardinality is valid for one step. `route_family_digest = SHA-256("openbuild-route-family-v1\0" || canonical_json(route_family))`.

A route step snapshot is exact `{route_family_digest,route_step,current_agent,profile_scope,profile_sha256,model,reasoning_effort,sandbox}`. Step is one-based, agent equals `route_family.agents[step-1]`, effort is `low|medium|high|xhigh`, and sandbox is `workspace-write` for implementation or `read-only` for critic/review. Source snapshot describes the completed/source agent. Target snapshot equals source for retry, is step+1 with the independently resolved target profile for escalation, and is null for root completion. Source/target digests use domains `openbuild-source-route-step-v1` and `openbuild-target-route-step-v1`. Private re-resolution must reproduce family and both applicable steps byte-for-byte. `logical_attempt_id` binds the stable `route_family_digest`, not either step digest.

The canonical lease plan object is `{schema_version:1,authorization_id,dispatch_generation_id,logical_attempt_id,lease_kind,agent_name,specification_revision,milestone,allowed_set_digest,target_route_snapshot_digest}`. Automatic plans carry their 64-hex `authorization_id` and null generation; ordinary plans carry null authorization and a fresh lowercase 32-hex `dispatch_generation_id`. `lease_kind` is `contained|legacy`, and the object exists only for writer lanes. `target_lease_plan_digest = SHA-256("openbuild-lease-plan-v1\0" || canonical_json(lease_plan))`. The canonical dispatch plan object is `{schema_version:1,authorization_id,dispatch_generation_id,logical_attempt_id,agent_name,task_name_digest,workspace_identity_digest,prompt_digest,lease_plan_digest,target_route_snapshot_digest,specification_revision,milestone,allowed_set_digest}` with the same identity rule; `lease_plan_digest` is null for read-only lanes and must equal the canonical lease-plan digest for writers. `target_run_plan_digest = SHA-256("openbuild-dispatch-plan-v1\0" || canonical_json(dispatch_plan))`. Plans never contain `action_id`, removing circular hashing. Every ordinary or automatic private runner request repeats both applicable plan digests before any process creation.

The privacy-safe public dispatch receipt is exactly `{schema_version:1,authorization_id,action_id,dispatch_generation_id,target_run_plan_digest,target_route_snapshot_digest,run_binding_id,status,dispatch_method,dispatch_result,agent_name,task_name_digest,lease_binding_id,activated,configured_model,model_reasoning_effort,sandbox,profile_scope,profile_sha256,activated_at,observation_started_at,observation_deadline_at,terminal_event,codex_exit_evidence,codex_exit_code,result_evidence,cancelled,completion_recovered_during_cancel,process_tree_stopped}`. Automatic receipts repeat authorization/action and have null generation; ordinary receipts have null authorization/action and repeat the plan's generation. `status` is `running|completed|failed|timeout`; `dispatch_method` is exactly `codex-exec-explicit-model`; `dispatch_result` is `selected|failed`; `lease_binding_id` is null for read-only lanes and required for writers. Running-unactivated has `activated=false`, all three timestamps/terminal/exit/result fields null and `process_tree_stopped=false`; activated-running has `activated=true`, all timestamps valid, terminal/exit/result null and stopped false; observation timeout preserves those bindings with status `timeout`, `cancelled=false` and stopped false and is never terminal. Terminal completed uses `turn.completed`, valid exit 0/result and stopped true. Terminal failed from ordinary transport uses `turn.failed`; terminal failed from root cancellation uses `terminal_event=null|turn.failed`, `cancelled=true`, `completion_recovered_during_cancel=false` and stopped true. Exit/result evidence remains `valid|missing|malformed|identity-mismatch` and `valid|missing|empty|invalid`, with integer exit only when valid. `run_binding_id`/`lease_binding_id` are domain-separated HMAC-SHA-256 opaque IDs created with a distinct owner-private dispatch key stored/reloaded under the existing current-user-only state root; missing/key drift blocks projection. Every public receipt has `public_receipt_digest = SHA-256("openbuild-dispatch-receipt-v1\0" || canonical_json(public_receipt))`; `target_run_receipt_digest` equals that value for a target terminal receipt. Canonical lease receipt `{schema_version:1,authorization_id,action_id,dispatch_generation_id,target_lease_plan_digest,lease_binding_id,agent_name,allowed_set_digest,status}` uses status `active|released|blocked` and domain `openbuild-lease-receipt-v1`. The projection function consumes the legacy owner-private runner receipt, verifies the exact allowed source fields and cross-bindings, drops raw profile/run/artifact paths, PIDs/process identities/thread/prompt/nonces/usage, and rejects an unknown source field before emitting the public object. Legacy command stdout remains owner-private and unchanged.

Every emitted timeout also persists exact observation-stage evidence `{schema_version:1,stage,observed_at,activation_gate_deadline_at,activated_at,observation_deadline_at,run_binding_id,target_run_plan_digest,status:"timeout"}` with UTC timestamps. `stage` is `checkpoint-45|checkpoint-90|checkpoint-120|hard-deadline|activation-gate`. Checkpoint/hard-deadline rows require null activation-gate deadline, non-null activation/deadline, and `observed_at < observation_deadline_at` for checkpoints or `observed_at >= observation_deadline_at` for hard deadline. Activation-gate requires a non-null gate deadline, null activation/observation timestamps and `observed_at >= activation_gate_deadline_at`. `observation_stage_digest = SHA-256("openbuild-observation-stage-v1\0" || canonical_json(stage_receipt))`; `source_observation_digest = SHA-256("openbuild-source-observation-v1\0" || canonical_json({public_receipt_digest,observation_stage_digest}))`. Only `hard-deadline|activation-gate` source observations authorize cancellation classification. On reload at/after either deadline, root persists this evidence before invoking `cancel`; 45/90/120 rows remain nonterminal telemetry only.

A canonical projection-error receipt is `{schema_version:1,authorization_id,action_id,dispatch_generation_id,target_run_plan_digest,target_route_snapshot_digest,phase,error_code,process_tree_stopped,evidence_digest}` with `phase=start|activation|running|terminal` and `error_code=unknown-private-field|missing-binding|binding-mismatch|invalid-status-matrix|dispatch-key-unavailable|projection-schema-invalid`. If trusted private evidence proves process creation, stopped proof must be true before terminalization; otherwise phase is start and no process is claimed. Its digest uses `openbuild-dispatch-projection-error-v1`. It never counts as a successful task receipt; it exists only to append `started→blocked` or pre-start `authorized→blocked` according to the physical-create proof.

Canonical source evidence is `{schema_version:1,source_lane,source_observation_digest,source_terminal_digest,source_archive_digest,stopped_tree_digest,pre_snapshot_digest,post_snapshot_digest,post_stop_diff_digest,allowed_set_digest,route_family_digest,source_route_snapshot_digest,selected_trigger,classifier_result,retry_reason,cancel_reason,prompt_release_proof_digest,specification_revision,milestone}` with lane/matrix nullability already defined. Observation digest is required only for observation-deadline, activation-gate-timeout and root-completion rows; it is null for early retry and both escalation rows. Every digest names a persisted canonical object: observation/terminal/archive and stopped-tree receipts; pre/post snapshots; post-stop diff attestation; prompt-gate proof; route family/source step. `evidence_digest = SHA-256("openbuild-source-evidence-v1\0" || canonical_json(source_evidence))`; `source_disposition_id = SHA-256("openbuild-source-disposition-v1\0" || canonical_json({source_observation_digest,source_terminal_digest,source_archive_digest,evidence_digest,specification_revision,milestone,allowed_set_digest}))`; `logical_attempt_id = SHA-256("openbuild-logical-attempt-v1\0" || canonical_json({specification_revision,milestone,allowed_set_digest,route_family_digest}))`. Before allocating plans, `authorization_id = SHA-256("openbuild-action-authorization-v1\0" || canonical_json({source_disposition_id,logical_attempt_id,source_lane,target_lane,kind,selected_trigger,classifier_result,retry_reason,cancel_reason,prompt_release_proof_digest,route_family_digest,source_route_snapshot_digest,target_route_snapshot_digest,current_agent,next_agent,retry_count,specification_revision,milestone,allowed_set_digest}))`. After allocating both applicable plans, `action_id = SHA-256("openbuild-automatic-action-v1\0" || canonical_json({authorization_id,target_run_plan_digest,target_lease_plan_digest}))`.

Canonical stopped-tree evidence is `{schema_version:1,run_binding_id,lease_binding_id,worker_process_state,codex_process_state,executing_descendant_count,process_tree_stopped}`. Binding IDs are 64-hex; the lease binding is null only for read-only; both states are exactly `stopped`, descendant count is integer zero, and the final flag is true. `stopped_tree_digest = SHA-256("openbuild-stopped-tree-v1\0" || canonical_json(stopped_tree))`. Its run/lease bindings must equal the source terminal receipt and its final flag must equal that receipt's `process_tree_stopped=true`.

The retry/action evidence matrix is exhaustive:

| Kind/reason | `selected_trigger` | `classifier_result` | `retry_reason` | `cancel_reason` | `prompt_release_proof_digest` |
|---|---|---|---|---|---|
| same-profile / observation deadline | null | `observation-deadline` | `observation-deadline` | `observation-deadline` | null |
| same-profile / activation gate | null | `activation-gate-timeout` | `activation-gate-timeout` | `activation-gate-timeout` | required |
| same-profile / early result | null | `early-window-insufficient` | `early-window-insufficient` | null | null |
| next-rung canonical escalation | configured non-empty trigger | `canonical-needs-escalation` | null | null | null |
| next-rung normalized malformed escalation | configured non-empty trigger | `normalized-malformed-needs-escalation` | null | null | null |
| root completion | null | `observation-deadline-partial-diff` | null | `observation-deadline` | null |

No other combination validates. The activation proof is exact `{schema_version:1,prompt_released:false,task_event_seen:false,activation_artifact_seen:false,gate_timeout:true,source_run_binding_id,target_run_plan_digest}` and its digest uses `openbuild-prompt-release-proof-v1`; any true/missing/unknown field blocks retry. Its run and plan bindings must equal the activation-gate observation and terminal source receipts. Selected escalation trigger must occur in the immutable route-family list and the target step must be exactly source step + 1.

Cross-object equality is exact: plans repeat authorization/generation/logical attempt/agent/revision/milestone/allowed-set/target-step bindings where those fields exist; dispatch plan lease digest equals the lease-plan digest; private request plan digests equal the persisted plan objects; public receipts repeat plan identity and add the computed action for automatic work; profile fields equal the target snapshot; lease receipts equal the lease plan plus action; started ledger receipt digests equal the canonical public receipt/lease receipt or projection-error digest. Observation deadline and root completion bind an observation receipt `status=timeout`, `activated=true`, `cancelled=false`, stopped false, followed by a terminal cancellation receipt `status=failed`, `activated=true`, `cancelled=true`, `completion_recovered_during_cancel=false`, stopped true. Activation-gate retry uses the same pair with `activated=false`. Early retry and both escalation classifiers have null observation digest and require one terminal `status=completed`, `turn.completed`, valid exit 0/result, `cancelled=false`, recovered-during-cancel false and stopped true. Run/lease/plan/route identities must match across each pair. Any completion recovered during cancel follows normal completion and forbids automatic retry/root-completion. These equalities must match the matrix `cancel_reason`; any other receipt state blocks. Any mismatch follows T-126/T-130.

Every source lane requires `source_terminal_digest` plus stopped-tree evidence. `source_archive_digest` is required only for `contained` and null for `legacy|read-only`; root is not a source lane. `target_run_plan_digest` is required for retry/escalation and null for root completion. `target_lease_plan_digest` is required only for contained/legacy writer targets and null for read-only/root. Both target receipt digests are null at `authorized`. Legal transitions are exactly (a) `authorized → blocked` before dispatch, retaining null receipt digests, or (b) `authorized → started → completed|blocked`, where `target_run_receipt_digest` is required for every non-root target and `target_lease_receipt_digest` is required only for contained/legacy writers; root completion keeps all target plan/receipt fields null. Every status row repeats byte-identical immutable fields. No status may be skipped/reordered/duplicated. Exactly one automatic action of any kind may consume a `source_disposition_id`; exactly one same-profile retry across all three reasons may consume a `logical_attempt_id`; `retry_count=1` forbids another. Only actor root writes rows after the applicable lane is stopped/released. Schema/revalidation/dispatch errors before `started` write `authorized→blocked`; errors after `started` write `started→blocked` using the last valid receipt projection. No error rewrites history or fabricates a pre-start state.

Activation evidence is exactly `{activated_at,observation_started_at,observation_deadline_at,codex_pid,codex_process_identity}` in the private activation artifact; public receipts expose only the three timestamps. Timestamps use UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`; `observation_started_at == activated_at` and deadline is exactly 900 seconds later. A repeated activation must load the existing artifact and reproduce all fields byte-for-byte. Live orchestration uses monotonic remaining time capped by the UTC deadline. On reload, missing/malformed/mismatched/future-start evidence blocks; `now >= deadline` first persists the exact `hard-deadline` observation-stage receipt, then deterministically invokes `cancel`. Only cancel stop proof allows classification, otherwise quarantine/block. If `now < started_at` by more than five seconds, treat it as clock drift and follow the blocking path, never reset or fabricate the budget.

Canonical changed records are a path-sorted unique array of exact `{path,status,before_sha256,after_sha256}` objects: normalized workspace-relative UTF-8 path; status `added|modified|deleted`; each hash lowercase 64-hex or null exactly on the absent side. `changed_records_digest = SHA-256("openbuild-changed-records-v1\0" || canonical_json(records))`. Outside-set delta has the same schema and digest domain `openbuild-outside-set-delta-v1`; `outside_set_delta_empty` is true iff its array length is zero. The canonical post-stop attestation is `{schema_version:1,baseline_head,pre_snapshot_digest,post_snapshot_digest,allowed_set_digest,changed_records_digest,outside_set_delta_digest,outside_set_delta_empty}` where the head is lowercase 40- or 64-hex and every digest is 64-hex. `post_stop_diff_digest = SHA-256("openbuild-post-stop-attestation-v1\0" || canonical_json(attestation))`. It is captured after terminal full-tree zero proof and before ledger authorization. Retry requires `pre_snapshot_digest == post_snapshot_digest`, empty changed records/outside delta, the matching matrix reason and source-receipt equality above, and no infrastructure/auth/quota/sandbox/provider/containment failure. Root completion requires identical baseline/control-plane/outside evidence, changed records wholly within the original allowed set, and binds the attestation digest before the `started` row/first root edit; any attribution ambiguity blocks.

The activation-timeout retry predicate requires: original receipt `activated=false`; activation artifact/prompt-gate/task-event artifacts prove no prompt release or task event; timeout is specifically the activation gate; full tree is stopped; pre/post snapshot and control plane are byte-equal; effective route/profile/scope are unchanged. It consumes the same `logical_attempt_id` retry budget as the other retry reasons. The fresh attempt is launched through runner-owned `dispatch` under T-118, and its returned started receipt digests must match the preallocated plan digests.

Early-window retry canonicalization uses the same logical-line normalization as T-111 but accepts exactly one authority line matching case-insensitive `^RETRY_SAME_PROFILE:[ \t]*execution-window-insufficient$`; any second retry/escalation marker or standalone `BLOCKED|COMPLETED` conflict rejects. It additionally requires transport `turn.completed`, exit 0, valid result, full-tree stop, zero-write pre/post attestation and no failure category. It consumes the same one-retry `logical_attempt_id` budget and never changes route step/profile.

Before process creation, every ordinary/automatic private request stores `target_run_plan_digest`. After any root crash, root invokes the single form `agent_runner.py dispatch --adopt-plan <digest>`. The runner scans only its owner-private run root, validates exact current-user ownership, reads private requests without printing them, and returns: zero matches → the persisted plan may dispatch once; one match unactivated/live → durably activate that same run; one match activated/terminal → return the same run's normal or projection-error public receipt; multiple/mismatched matches → block/quarantine. It never redispatches when a physical match exists. For an automatic action, a physically started match appends/adopts `started` before further wait/cancel and an unstarted failed match appends `blocked`; ordinary dispatch resumes through its plan without an action ledger. This applies to writer and read-only lanes.

Ordinary dispatches use a separate append-only root execution-log chain with exact row `{event:"dispatch-attempt",actor:"root",dispatch_generation_id,target_run_plan_digest,status}` and statuses `planned|started|terminal|blocked`. A fresh generation is allocated before every logically new ordinary dispatch; only `planned→started→terminal|blocked` is legal, immutable fields repeat exactly, and adoption may resume only the latest nonterminal chain for that digest/generation. A previous terminal generation can never satisfy or suppress a later identical task. Automatic actions never write this row because their action ledger is authoritative.

### Versioning and release

Authoritative version source: `plugins/openbuild/.codex-plugin/plugin.json`. Target 2.2.1 is a patch fix selected by D-007. Rollback to immutable 2.2.0 is schema-compatible but occurs only after exact registry vacancy, completed outbox/archive, guardian close and no nonterminal 2.2.1 automatic-action ledger row; explicit registry retirement is required only below the 2.2.0 reader floor. Commit is standing-authorized when checks/review are green and the task diff is isolatable; push/tag/GitHub Release are not authorized by this request.

Rollback ledger scan root is `BUILD-auto-continuation-2.2.1.md`. Resolve its `Specification source map` recursively using normalized workspace-relative paths; a row is a task specification exactly when its authority/owner cell contains `task`, `user request`, or `prior user decisions`. Each document's row whose normalized path equals that document is a required self declaration and is excluded from outgoing edges. Distinct task-spec rows are edges. The expected normalized sorted unique scan set for R-022 is `["BUILD-auto-continuation-2.2.1.md","BUILD-route-recovery-safety.md","BUILD.md"]`. Each source's distinct outgoing task-spec edges must appear in its source map; distinct-path cycle, duplicate alias, path escape, missing/unreadable source, unexpected task-spec edge or set mismatch blocks rollback. Validate every complete append-only chain grouped by `action_id`, require immutable fields and legal ordering across all historical rows, and evaluate current terminality only from the latest row; every matching 2.2.1 action's latest status must be `completed|blocked`.

## 7. Validation and review

- Primary signal: policy mutation tests plus package validation prove both automatic branches and unchanged safety guards.
- Red signal: new `ImplementationDelegationContractTests` mutations fail because the current docs require explicit prompts and have no absolute 900-second deadline, malformed-marker grammar, one-shot same-profile retry or operational-question boundary.
- Minimality decision: reuse existing start/activate/wait/cancel/reject/invalidate/finalize primitives behind a small runner-owned `dispatch`, plus pure classifier/automatic-action trace validation; no registry state-machine change or dependency.
- Focused green: `python -m unittest scripts.test_validate_package.ImplementationDelegationContractTests -v`.
- Targeted checks: `python -m unittest scripts.test_validate_package -v`; `python scripts/validate_package.py`; `git diff --check`.
- Wider checks: `python -m unittest discover -s scripts -p "test_*.py" -v`.
- Required fixture matrix: absolute deadline grammar/equality/repeated activation/remaining arithmetic/reload/missing/future-drift; no prompt after 45/90/120; completion-before/during-cancel; deadline-cancel, activation-timeout and canonical early-window retry positives plus conflict/infrastructure negatives; lane×kind positives/negatives/order; stopped zero/allowed/forbidden diff and attestation drift; malformed marker and second escalation rejection; every route current/next/step/ceiling/trigger/use-case/risk/effort/sandbox/scope/fingerprint relation; canonical source/action/logical/lease/dispatch/public/error objects, domains, enums, nullability and every cross-equality; pre/post-start blocked paths; ordinary/automatic orphan adoption zero/one/multiple and unactivated activation; source mutual exclusion and shared retry/escalation budgets; legacy compatibility; projection redaction/error codes/key reload; activation retry/exact-review non-substitution; rollback graph, complete chain, invalid history and latest-state cases; EN/RU branch guidance.
- Manual/runtime check: exact runner smoke/fixture must show immutable activation/deadline fields across status/wait and one realistic zero-write operational trace; no private value is printed.
- Commit gate after task-scoped staging: `git diff --cached --check`; `python scripts/validate_package.py --commit-gate`. Any unstaged package path or version/docs mismatch blocks commit.
- Starting review tier: balanced high-risk.
- Required final tier: balanced minimum; advance only on a concrete configured finding, with high-risk complementary readiness perspectives before implementation.
- Review focus: accidental transport escalation, repeated automatic replacement, elapsed-budget semantics, cancellation race, partial-diff authority, documentation parity and rollback.

## 8. Milestones

### M1. Close the 2.2.1 contract

- Status: Complete
- Scope: reconcile decisions, add RED contract tests, update workflow owner docs, version/docs.
- Excludes: model-map and runtime registry schema changes; publication remains root-owned after all gates pass.
- Implementation mode: TDD-first
- Delegation: balanced pre-edit zero-write escalation followed by one exact strong bounded writer; root completed only same-scope contract/docs remediation.
- Red signal: current contract tests do not require 900-second automatic wait/cancel or malformed-marker normalization.
- Minimality decision: existing runner primitives + one `dispatch` wrapper, additive receipt evidence, owner docs and executable validator/runtime fixtures.
- Acceptance: AC-01 through AC-60.
- Review: Balanced REVISE finding remediated; fresh balanced review ACCEPT, high confidence 0.93, no findings.
- Version: `2.2.0` → `2.2.1`.
- Commit: Root-owned scoped release commit pending at documentation time.

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome/scope/non-goals | covered | product decision | D-001/D-006/D-007, AC-01..10 | critic |
| B-002 | actors/permissions | covered | product decision | D-008..D-010 authorize bounded wait/cancel, malformed one-rung escalation, three reasons sharing one retry budget, root completion and atomic activation; all other material choices remain user-owned | fixtures/critic |
| B-003 | primary/alternate/error/cancel/retry | covered | technical decision | T-101..T-103 and scenarios | fixtures |
| B-004 | accessibility/localization/responsive UX | not applicable | repository fact | no UI; EN/RU prose parity is AC-10 | docs check |
| B-005 | ownership/contracts/source of truth | covered | repository fact | owner table and source map | critic |
| B-006 | data/schema/migration/retention | covered | technical decision | T-107/T-109/T-110 closed BUILD-ledger schema/retention; registry v1 unchanged | schema/privacy fixtures |
| B-007 | security/privacy/trust | covered | technical decision | existing private proof boundary preserved | review |
| B-008 | concurrency/ordering/idempotency | covered | technical decision | one lease, one automatic rung, stop proof | mutation tests |
| B-009 | integrations/timeouts/partial failure | covered | product + technical decision | D-006, T-101..T-103 | cancellation cases |
| B-010 | observability/support | covered | technical decision | named outcome dispositions | docs/review |
| B-011 | compatibility/rollout/rollback | covered | product decision | D-007; no reader-floor/schema change; rollback 2.2.0 | version validation |
| B-012 | acceptance/testability/minimality/cost | covered | technical decision | AC-09 and validation plan; no new dependency | RED/green |
| B-013 | malformed-marker ambiguity | covered | technical decision | T-102 requires clear intent + configured trigger | adversarial critic |
| B-014 | cancellation race/partial authority | covered | product + technical decision | D-006/T-103; normal success vs root-only completion | adversarial critic |
| B-015 | same-profile zero-write retry | covered | product + technical decision | D-009/T-105/AC-11 | mutation fixtures |
| B-016 | operational question boundary | covered | product decision | D-008/T-106/AC-12..13 | complementary critic |
| B-017 | absolute deadline accounting | covered | technical decision | T-101 plus ordering table and fixture matrix | RED/green |
| B-018 | rollback registry precondition | covered | repository fact | existing 2.2.0 reader floor; exact vacancy/outbox/archive/close | docs validation |
| B-019 | automatic authority durability/replay | covered | technical decision | T-107/AC-14 ordered root trace after the exact lane gate | executable trace fixtures |
| B-020 | dispatch-time route binding | covered | technical decision | T-102/T-108; original map hash/step/triggers/next profile | drift fixtures |
| B-021 | runtime proof versus prose | covered | technical decision | T-109/AC-15 requires executable classifier/trace validation | RED/green |
| B-022 | deadline persistence/reload | covered | technical decision | T-101/T-110/AC-16 additive activation receipt and fail-closed reload | runner fixtures |
| B-023 | automatic-action production owner | covered | technical decision | T-107/AC-17 selected BUILD execution log, closed schema, single-root ordering | lifecycle trace fixtures |
| B-024 | pending-action rollback fence | covered | technical decision | T-110/AC-17 no nonterminal action before downgrade | rollback fixtures |
| B-025 | prompt-gate automatic activation | covered | product + technical decision | D-010/T-117/AC-22..23 strict adjacency and one fresh exact retry | activation trace fixtures |
| B-026 | automatic-action target lineage/mutual exclusion | covered | technical decision | T-119/AC-25 plan/receipt digests, source disposition and shared logical attempt | replay/crash fixtures |
| B-027 | atomic user-transparent dispatch/activation | covered | technical decision | T-118/AC-24 runner-owned `dispatch` | runner fixtures |
| B-028 | rollback ledger graph closure | covered | technical decision | T-120/AC-26 canonical three-spec scan set and fail-closed graph rules | rollback fixtures |
| B-029 | pre-start blocked action path | covered | technical decision | T-121/AC-27 null receipt rules and legal terminal transition | ledger fixtures |
| B-030 | public/private evidence projection | covered | technical decision | T-122/AC-28 scope+fingerprint ledger, legacy raw CLI remains private | redaction fixtures |
| B-031 | dispatch runtime ownership/scope | covered | technical decision | T-109/T-118/AC-29 explicit runner implementation | runtime fixtures |
| B-032 | rollback self-row handling | covered | technical decision | T-123/AC-30 self declaration exclusion | graph fixtures |
| B-033 | ledger lane totality | covered | technical decision | T-124/AC-31 contained/legacy/read-only nullability | lane fixtures |
| B-034 | terminal critical trigger set | covered | technical decision | T-141 allows empty triggers iff the route has one step (`max_steps == 1`) | critical route fixture |
| B-035 | distinct retry predicates | covered | technical decision | AC-20 observation deadline; AC-23 activation gate | retry fixture matrix |
| B-036 | state-aware action errors | covered | technical decision | T-121/T-126/AC-33 pre/post-start blocked paths | error fixtures |
| B-037 | canonical dispatch plan/receipt lineage | covered | technical decision | T-125/AC-32 domain-separated objects/projection | runtime/redaction fixtures |
| B-038 | contributor commit gate | covered | repository fact | CONTRIBUTING staged diff and commit-gate commands | run after staging |
| B-039 | lane lifecycle matrix | covered | technical decision | T-127/AC-34 exact kind×lane ordering | lane fixtures |
| B-040 | escalation logical-attempt one-shot | covered | technical decision | T-128/AC-35 one auto next-rung total | replay fixtures |
| B-041 | dispatch/ledger crash adoption | covered | technical decision | T-129/AC-36 plan-bound zero/one/multiple adoption | crash fixtures |
| B-042 | first-projection failure | covered | technical decision | T-130/AC-37 canonical error receipt | projection fixtures |
| B-043 | canonical plan/receipt chain | covered | technical decision | T-125/T-131/AC-38 exact objects/domains/states | lineage fixtures |
| B-044 | route relational closure | covered | technical decision | T-108/T-131/AC-39 agent/step/ceiling/trigger/lane relations | route fixtures |
| B-045 | autonomous branch totality | covered | product decision | B-002/AC-40 enumerates every D-008..D-010 branch | prompt-boundary fixtures |
| B-046 | append-only rollback latest state | covered | technical decision | T-132/AC-41 validate chain, latest terminal only | rollback fixtures |
| B-047 | target profile/route trigger binding | covered | technical decision | T-133/AC-42 route-wide triggers + next-profile fingerprint | route fixtures |
| B-048 | canonical evidence relational closure | covered | technical decision | T-134/AC-43 local enums/domains/equalities/IDs | mutation fixtures |
| B-049 | ordinary dispatch crash adoption | covered | technical decision | T-135/AC-44 plan every dispatch, unified adopt | crash fixtures |
| B-050 | D-009 early-window retry | covered | product decision | T-136/AC-45 exact authority grammar + zero-write success | retry fixtures |
| B-051 | circular action/plan identity | covered | technical decision | T-137/AC-46 authorization precedes plans; action follows plan digests | identity fixtures |
| B-052 | escalation resets logical attempt | covered | technical decision | T-138/AC-47 stable route family plus distinct source/target steps | route replay fixtures |
| B-053 | source evidence closure | covered | technical decision | T-139/AC-48 exact classifier/cancel/prompt/stopped/attestation bindings | evidence mutation fixtures |
| B-054 | ordinary plan collision/adoption | covered | technical decision | T-140/AC-49 fresh generation and append-only dispatch chain | crash fixtures |
| B-055 | route trigger cardinality | covered | technical decision | T-141/AC-50 mirrors resolver `max_steps == 1` rule | resolver fixtures |
| B-056 | retry-matrix drift | covered | technical decision | T-142/AC-51 closed three-row reason matrix | exhaustive retry fixtures |
| B-057 | canonical versus malformed escalation authority | covered | product + technical decision | D-001/D-008, T-143/AC-52 exact classifier rows | escalation fixtures |
| B-058 | stopped/attestation digest closure | covered | technical decision | T-144/AC-53 exact objects, domains and receipt equalities | evidence fixtures |
| B-059 | milestone acceptance drift | covered | technical decision | T-145/AC-54 M1 covers AC-01..60 | commit gate |
| B-060 | resolver trigger compatibility | covered | repository fact + technical decision | T-141/T-146/AC-50/55 preserves resolver list exactly | resolver fixtures |
| B-061 | observation timeout mistaken for terminal | covered | technical decision | T-147/AC-56 separate observation and cancellation receipts | cancellation fixtures |
| B-062 | escalation classifier overlap | covered | technical decision | T-102/T-148/AC-57 disjoint raw versus normalized predicates | grammar fixtures |
| B-063 | stale AC action transition | covered | technical decision | T-151/AC-18 both legal state paths | ledger fixtures |
| B-064 | soft timeout authorizes hard cancellation | covered | technical decision | T-149/AC-58..59 exact observation-stage time evidence | deadline fixtures |
| B-065 | borrowed activation proof | covered | technical decision | T-150/AC-60 run/plan equality | binding fixtures |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Arbitrary zero-write failure is mistaken for escalation. | medium/high | Require unambiguous intent, configured trigger, valid terminal evidence and exact one-rung route. | Handled by T-102/AC-05..07 |
| A second writer starts while the first tree is alive. | low/high | Existing containment/lease/zero-proof gate remains mandatory. | Handled by AC-02/08 |
| Automatic cancel interrupts a legitimate long writer. | medium/medium | User-selected hard 900-second maximum; preserve valid completion race and safe root completion. | Accepted by D-006 |
| Partial diff is treated as accepted worker handoff. | low/high | Separate `auto-root-completion` authority; root reruns TDD/validation/review and never emits worker handoff. | Handled by T-103/AC-04 |
| Patch docs drift between languages/version surfaces. | medium/medium | Validator + full release synchronization in one commit. | Pending implementation |
| Automatic same-profile retry loops or reuses a terminal lease identity. | low/high | Fresh physical lease/run, identical logical bindings and one durable retry consumption. | Handled by T-105/AC-11 |
| Removing prompts hides why automation stopped. | medium/medium | `automation-exhausted`/`blocked` EN/RU guidance with no sensitive details and no routine yes/no prompt. | Handled by T-106/AC-13 |
| Root reload duplicates an automatic retry or completion authority. | low/high | Stable action ID, ordered authorized/started/terminal events and resume-same-action rule after revalidating the exact lane gate. | Handled by T-107/AC-14 |
| Model-map/profile override drifts after the source run. | low/high | Bind dispatch-time map and exact tuple; re-resolve only for equality, never reinterpret. | Handled by T-108/AC-14 |
| Wall-clock/reload resets the observation budget. | low/high | Persist UTC activation/deadline, use monotonic budget live, fail closed on missing/future-drift evidence. | Handled by T-101/T-110/AC-16 |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-001 | automatic malformed-marker one-rung replacement — current user request 2026-07-16 | outcome, scope, scenario, AC-05..08, M1 | zero-write, configured trigger, exact route, no transport escalation | none |
| D-006/R-001 | automatic wait/cancel with maximum 15 minutes — current user request 2026-07-16 | outcome, scenario, AC-01..04, T-101/T-103, M1 | same run/lease, stop proof, no failed handoff | none |
| D-007/R-001 | stable 2.2.1 — current user request 2026-07-16 | version impact, AC-10, version/release, M1 | SemVer/release gates; no implicit push/tag/release | none |
| D-008/R-002 | internal orchestration is automatic; ask only material user-owned decisions — current user addition 2026-07-16 | outcome/scope, D-008, T-106, AC-12..13, action table, risks | product/architecture/security/external authority remains user-owned | none |
| D-009/R-002 | one automatic same-profile retry with more time — current user example 2026-07-16 | desired behavior, scenario, T-105, AC-11, fixture matrix, M1 | fresh physical identity, same scope/profile, no loop/escalation | none |
| R-003 technical application | no new product outcome; apply D-001/D-006/D-008/D-009 through replay-safe trace and dispatch-time binding | T-102/T-107..109, AC-14..15, B-019..21, fixture matrix | registry v1 and all containment/privacy invariants preserved | none |
| R-004 technical application | no new product outcome; close strong reliability gaps with activation deadline receipts, closed production ledger schema, full route equality, diff attestation and rollback fence | T-101/T-105/T-107..111, AC-16..17, B-022..24 | D-001/D-006/D-008/D-009 and registry v1 preserved | none |
| D-010/R-006 | activation is automatic; one fresh exact retry after an unactivated prompt-gate timeout — current user example 2026-07-16 | desired behavior, scenario, T-117, AC-22..23, B-025, fixture matrix | start receipt still precedes prompt release; exact review cannot be substituted | none |
| R-007 technical application | no new product outcome; make activation atomic to root and close lineage/rollback schema gaps | T-117..120, AC-24..26, B-026..28 | D-010 plus all routing/containment/user-authority invariants | none |
| R-008 technical application | no new product outcome; close pre-start blocked, privacy projection, runtime scope and self-row gaps | T-108/T-109/T-121..123, AC-27..30, B-029..32 | all user decisions and registry v1 preserved | none |
| R-009 technical application | no new product outcome; close lane totality, critical triggers, retry predicates, state-aware errors, receipt lineage and commit-gate coverage | T-124..126, AC-31..33, B-033..38 | all user decisions, legacy CLI and registry v1 preserved | none |
| R-010 technical application | no new product outcome; close lane ordering, escalation replay, orphan adoption, projection errors, canonical lineage and route relations | T-127..131, AC-34..40, B-039..45 | D-001/D-006/D-008..D-010 and safety invariants preserved | none |
| R-011 technical application | apply existing D-009 early retry and close rollback/target/evidence/ordinary-crash relations | T-132..136, AC-41..45, B-046..50 | all locked decisions and safety invariants preserved | none |
| R-012 technical application | remove identity cycles, bind stable route family/source-target steps, close evidence and ordinary-generation identity, and make the three retry reasons exhaustive | T-137..142, AC-46..51, B-051..56 | all locked user decisions and fail-closed boundaries preserved | none |
| R-013 technical application | unify canonical/malformed escalation authority, mirror actual resolver trigger cardinality, close stopped/attestation digests and include all criteria in M1 | T-143..146, AC-52..55, B-057..60 | D-001/D-008 automatic internal continuation and all safety boundaries preserved | none |
| R-014 technical application | separate observation timeout from terminal cancellation and make canonical/malformed escalation predicates disjoint | T-147..148, AC-56..57, B-061..62 | all user outcomes, runner state semantics and fail-closed escalation preserved | none |
| R-015 technical application | persist exact observation stage/time, cross-bind activation proof and align AC-18 with both legal action paths | T-149..151, AC-58..60, B-063..65 | all automatic behavior and runner state semantics preserved | none |
| R-016 technical application | qualify target-receipt requirements by retry/escalation versus root-completion | T-121 and AC-27 | root-completion nullability and all action paths preserved | none |
| R-017 technical application | propagate root-completion target nullability into T-119 and AC-25 | T-119 and AC-25 | all lineage, replay and one-shot budgets preserved | none |
| R-018 technical application | qualify T-115 retry evidence, align zero-match adoption and make action-ID null target pair explicit | T-115/T-129/T-137 and canonical ledger text | all locked branch predicates and replay guarantees preserved | none |
| R-019 technical application | qualify automatic-action ordering by contained, legacy and read-only lifecycle evidence | T-107/AC-14/canonical ordering | no lane fabricates registry/archive/lease evidence | none |
| R-020 technical application | propagate lane-specific authorization into reload, data/migration, coverage and risk summaries | T-110, data/migration, B-019 and risk register | package rollback's global registry fence remains distinct | none |
| R-021 technical application | qualify action-table retry/escalation close steps and update B-059 through AC-60 | action table and B-059 | lane matrix and milestone acceptance preserved | none |
| R-022 technical application | propagate lane-neutral escalation/retry wording into Outcome and user scenarios | outcome items 1/4 and scenario steps | exact lane matrix remains authoritative | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | product/UX / balanced | GAPS, high confidence | deadline accounting, malformed grammar, cancel ordering, root authority, blocked guidance, rollback and fixture coverage | adjudicated into T-101..T-106, AC-11..13, action table, exact eligibility, fixture matrix and B-015..18; semantic inputs plus D-008/D-009 create R-002 |
| R-002 | architecture/data/security / balanced | GAPS, high confidence | durable action/root authority, route-snapshot binding, grammar canonicalization and runtime proof | adjudicated in R-003 through T-102/T-107..109, AC-14..15, ordered trace and executable fixtures; no D reopen |
| R-003 | reliability/validation / strong | GAPS, high confidence | production action owner/atomic boundary, deadline reload, retry predicate, full route equality, conflict scan, diff attribution and rollback fence | adjudicated in R-004 through T-101/T-105/T-107..111, AC-16..17 and B-022..24; no D reopen |
| R-004 | reliability/validation / strong | GAPS, high confidence | exact ledger schema, full snapshot artifact, timestamp semantics, positive retry predicate, pre/post attribution and version-bound rollback scan | adjudicated in R-005 through T-112..116 and AC-18..21; no D reopen |
| R-005 | strong closure | superseded before dispatch | user added automatic activation after prompt-gate omission | D-010/T-117 creates semantic revision R-006 |
| R-006 | reliability/validation / strong | GAPS, high confidence | conflicting ledger schemas, missing target lineage, unverifiable start→activate adjacency, open rollback graph and stale source-map row | adjudicated in R-007 through canonical single schema, T-118..120, AC-24..26 and updated source map; no D reopen |
| R-007 | reliability/validation / strong | GAPS, high confidence | no legal pre-start blocked path, raw path/private receipt conflict, dispatch omitted from affected scope and self-row rollback cycle | adjudicated in R-008 through T-108/T-109/T-121..123 and AC-27..30; no D reopen |
| R-008 | reliability/validation / Sol-high terminal | GAPS, high confidence | lane totality, critical empty triggers, conflicting retry predicates, state-aware errors, canonical plan/public receipt lineage and commit-gate omission | adjudicated in R-009 through T-124..126, AC-31..33, canonical plan/receipt projection and staged gates; no D reopen |
| R-009 | reliability/validation / Sol-high terminal | GAPS, high confidence | lane ordering, escalation logical replay, orphan start, first projection error, plan/receipt chain, route relations and incomplete authority coverage | adjudicated in R-010 through T-127..131, AC-34..40, lane/plan/adoption schemas and B-039..45; no D reopen |
| R-010 | reliability/validation / Sol-high terminal | GAPS, high confidence | append-only rollback latest state, target profile/triggers, canonical evidence relations, ordinary dispatch crash adoption and D-009 early retry | adjudicated in R-011 through T-132..136, AC-41..45 and B-046..50; no D reopen |
| R-011 | reliability/validation / Sol-high terminal | GAPS, high confidence | circular action/plan identity, source/target route lineage, non-closed source evidence, ordinary-plan collision, trigger cardinality and stale retry matrix | adjudicated in R-012 through T-137..142, AC-46..51 and B-051..56; no D reopen |
| R-012 | reliability/validation / Sol-high terminal | GAPS, high confidence | canonical/malformed escalation authority conflict, resolver trigger-cardinality mismatch, missing stopped/attestation digest closure and stale M1 acceptance range | adjudicated in R-013 through T-143..146, AC-52..55 and B-057..60; no D reopen |
| R-013 | reliability/validation / Sol-high terminal | GAPS, high confidence | nonterminal timeout was used as terminal cancellation evidence; canonical/malformed classifier predicates overlapped | adjudicated in R-014 through T-147..148, AC-56..57 and B-061..62; no D reopen |
| R-014 | reliability/validation / Sol-high terminal | GAPS, high confidence | stale AC-18 transition, no hard-versus-soft observation stage/time evidence, activation proof not cross-bound | adjudicated in R-015 through T-149..151, AC-58..60 and B-063..65; no D reopen |
| R-015 | reliability/validation / Sol-high terminal | GAPS, high confidence | AC-27/T-121 incorrectly required target receipts for started root-completion | adjudicated in R-016 by lane/kind-qualified T-121 and AC-27; no D reopen |
| R-016 | reliability/validation / Sol-high terminal | GAPS, high confidence | T-119/AC-25 still unconditionally required target plans/receipts for root-completion | adjudicated in R-017 by kind-qualified T-119/AC-25; no D reopen |
| R-017 | reliability/validation / Sol-high terminal | GAPS, high confidence | T-115 overgeneralized deadline evidence; T-129 contradicted zero-match dispatch; T-137/general ID text assumed non-null plans | adjudicated in R-018 through branch-qualified evidence/adoption/ID language; no D reopen |
| R-018 | reliability/validation / Sol-high terminal | GAPS, high confidence | T-107/AC-14/general ordering incorrectly required contained archive/guardian/registry evidence for all lanes | adjudicated in R-019 with exact lane-specific close/release gates; no D reopen |
| R-019 | reliability/validation / Sol-high terminal | GAPS, high confidence | data/migration, B-019 and replay risk still used universal registry-vacancy wording | adjudicated in R-020 with exact lane-gate language plus distinct global rollback fence; no D reopen |
| R-020 | reliability/validation / Sol-high terminal | GAPS, high confidence | two action-table rows still implied contained archive/invalidation for every lane; B-059 stopped at AC-55 | adjudicated in R-021 with lane-qualified actions and AC-60 coverage; no D reopen |
| R-021 | reliability/validation / Sol-high terminal | GAPS, high confidence | Outcome and scenarios still assumed checkpoint invalidation/archive/lease for read-only/legacy paths | adjudicated in R-022 with lane-specific rejection/stop/release and optional writer lease language; no D reopen |
| R-022 | reliability/validation / Sol-high terminal | COVERED, high confidence | none; lane gates, all 60 criteria, deadline, root-completion nullability, adoption/replay, privacy, exact review and rollback are consistent | Ready gate passed; proceed to M1 TDD implementation |

## 10. Open questions

Blocking product questions: None.

Non-blocking assumptions:

- “Макс окно ожидания 15 минут” означает один hard maximum automatic wait budget from activation, а не сбрасываемый idle timer; это закреплено T-101.
- “Некорректный escalation-маркер” ограничен fail-closed грамматикой T-102; свободный текст и произвольный `BLOCKED` не нормализуются.

## 11. Agent activity ledger

Created logical agent runs: 27.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | discovery / owners of wait and malformed escalation policies | `gpt-5.3-codex-spark` | low | completed / evidence accepted | Mapped workflow docs, runtime owners, tests, version and predecessor specification; supports sections 2, 6 and M1 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-002 | yes | critic product/UX / R-001 auto-continuation | `gpt-5.6-terra` | medium | completed / GAPS, high confidence | Found deadline, classifier, cancellation, authority, UX, rollback and testability gaps; mapped to R-002 T/AC/B records | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-003 | yes | critic architecture/data/security / R-002 autonomous orchestration | `gpt-5.6-terra` | medium | completed / GAPS, high confidence | Found durable authority, route snapshot, canonical grammar and runtime-proof gaps; mapped to R-003 T/AC/B records | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-004 | yes | critic reliability/validation strong closure / R-003 | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | Found production ledger owner, reload deadline, retry predicate, route equality, diff attribution and rollback-fence gaps; mapped to R-004 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-005 | yes | critic reliability/validation strong closure / R-004 | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | Found exact ledger, full route artifact, deadline grammar, retry/attribution and version-fence gaps; mapped to R-005/R-006 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-006 | yes | critic reliability/validation strong closure / R-006 | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | Found ledger schema conflict, target lineage, activation interleaving, rollback graph and source-map drift; mapped to R-007 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-007 | yes | critic reliability/validation strong closure / R-007 | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | Found pre-start blocked, privacy projection, runtime scope and rollback self-row gaps; mapped to R-008 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-008 | yes | critic terminal reliability/validation / R-008 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found lane totality, terminal trigger, retry predicate, action-error, receipt-lineage and commit-gate gaps; mapped to R-009 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-009 | yes | critic terminal reliability/validation / R-009 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found lane ordering, escalation replay, orphan dispatch, projection error, lineage, route-relation and coverage gaps; mapped to R-010 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-010 | yes | critic terminal reliability/validation / R-010 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found rollback latest-state, target-profile/trigger, canonical evidence, ordinary dispatch crash and early retry gaps; mapped to R-011 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-011 | yes | critic terminal reliability/validation / R-011 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found identity cycle, route-lineage, evidence-closure, ordinary-generation, trigger-cardinality and retry-matrix gaps; mapped to R-012 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-012 | yes | critic terminal reliability/validation / R-012 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found escalation-authority, resolver-cardinality, stopped/attestation digest and M1-range gaps; mapped to R-013 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-013 | yes | critic terminal reliability/validation / R-013 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found observation/terminal receipt conflict and overlapping escalation classifiers; mapped to R-014 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-014 | yes | critic terminal reliability/validation / R-014 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found stale AC transition, missing observation-stage time evidence and activation-proof binding; mapped to R-015 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-015 | yes | critic terminal reliability/validation / R-015 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found unqualified target-receipt requirement contradicting root-completion nullability; mapped to R-016 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-016 | yes | critic terminal reliability/validation / R-016 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found the same root-completion target-nullability contradiction in T-119/AC-25; mapped to R-017 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-017 | yes | critic terminal reliability/validation / R-017 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Found stale deadline-retry, zero-match adoption and non-null action-plan wording; mapped to R-018 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-018 | yes | critic terminal reliability/validation / R-018 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Confirmed R-018 fixes; found universal contained-only ordering contradicting legacy/read-only lanes; mapped to R-019 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-019 | yes | critic terminal reliability/validation / R-019 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Confirmed lane matrix; found stale universal vacancy language in data, coverage and replay risk summaries; mapped to R-020 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-020 | yes | critic terminal reliability/validation / R-020 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Confirmed rollback separation; found contained-only action-table summaries and stale B-059 acceptance range; mapped to R-021 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-021 | yes | critic terminal reliability/validation / R-021 | `gpt-5.6-sol` | high | completed / GAPS, high confidence | Confirmed 60 criteria; found contained/writer-only assumptions in early Outcome and scenarios; mapped to R-022 | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-022 | yes | critic terminal reliability/validation / R-022 | `gpt-5.6-sol` | high | completed / COVERED, high confidence | Closed readiness across lane gates, all 60 criteria, deadline, root completion, plan adoption/replay, privacy, exact review and rollback | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-023 | yes | implementation / M1 first high-risk route step | `gpt-5.6-terra` | medium | completed / zero-write malformed escalation normalized | Returned an invalid next-profile marker with no file changes; root normalized it to configured `task-complexity-above-tier`, durably rejected the handoff and advanced exactly one route step without a user prompt | exact runner `turn.completed`, exit 0, valid result, stopped tree; independently verified zero writes |
| A-024 | yes | implementation / M1 strong route step | `gpt-5.6-terra` | xhigh | completed / handoff accepted | Added atomic dispatch/deadline evidence, automatic-orchestration owner contracts and executable runner/package fixtures under one bounded lease | exact runner `turn.completed`, exit 0, valid result, stopped tree; root verification and handoff materialized |
| A-025 | yes | progressive review / first complete diff | `gpt-5.6-terra` | medium | completed / REVISE, high confidence | Found stale manual activation and over-broad explicit-opt-in language in owner instructions; root mapped and remediated the bounded documentation/contract finding | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-026 | yes | progressive review / remediated diff `8236031bbfbfa110e2fd5d2c64c28389e277cce6` | `gpt-5.6-terra` | medium | completed / ACCEPT, confidence 0.93 | Verified atomic activation, one 900-second budget, bounded retry/escalation/root-completion, authority boundary, 2.2.1 parity and unchanged safety controls; no findings or escalation trigger | exact runner `turn.completed`, exit 0, valid result, stopped tree |
| A-027 | yes | progressive release review / final README and validator delta `2cd18d1eba5c77908f7c099ecd5fe79afe3a9f23` | `gpt-5.6-terra` | medium | completed / ACCEPT, confidence 0.94 | Verified final EN/RU hard-deadline and new-writer authority wording plus mutation guards as part of the complete diff; no findings or escalation trigger | exact runner `turn.completed`, exit 0, valid result, stopped tree |

Pre-spawn dispatch failures: None.

## 12. Execution and validation log

### 2026-07-16 — discovery and R-001 bootstrap

- Changed: created a separate 2.2.1 specification and mapped the completed 2.2.0 predecessor without altering it.
- Routing: packaged discovery/default step 1/1, exact `openbuild_search_separate`, `gpt-5.3-codex-spark`/low/read-only; accepted terminal evidence, no fallback.
- Primary signal: not yet met; implementation and review pending.
- Validation: baseline and owner evidence inspected; no implementation test claimed.
- Minimality decision: reuse existing wait/cancel/rejection/invalidation/finalization primitives unless RED proves a runtime gap.
- Version: planned patch `2.2.0` → `2.2.1`.
- Commit: not created.
- Remaining: high-risk readiness critics, RED, implementation, validation and progressive review.

### 2026-07-16 — R-002 operational-autonomy expansion

- Changed: applied the user's additional automatic same-profile retry and general no-routine-prompts policy; adjudicated every R-001 product/UX gap.
- Decisions: D-008/D-009 resolved from the current user addition; D-001/D-006/D-007 preserved.
- Routing: A-002 balanced product/UX critic completed after 45-second soft observation plus the next bounded wait; no replacement.
- Primary signal: not yet met; R-002 complementary critics and implementation pending.
- Validation: specification-only reconciliation; no implementation green claimed.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: architecture/data/security critic, fresh closure, RED, implementation and final review.

### 2026-07-16 — R-003 durable automatic-action contract

- Changed: adjudicated A-003 with exact grammar, dispatch-time route/profile binding, ordered replay-safe root trace and executable classifier/trace fixtures.
- Decisions: D-001/D-006/D-008/D-009 preserved; no product decision reopened.
- Routing: A-003 balanced architecture/data/security critic completed after 45-second soft observation plus the next bounded wait; its coverage-gap trigger authorizes exactly the next strong critic rung.
- Primary signal: not yet met; R-003 strong closure and implementation pending.
- Minimality: registry v1 remains unchanged unless focused RED proves a missing receipt field; pure owner-layer validation is required, not prose-only checks.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: strong readiness closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-004 strong-gap adjudication

- Changed: selected additive runner deadline receipts and a closed, privacy-safe BUILD execution-log ledger with full route/diff bindings and fail-closed reload/rollback.
- Decisions: no D reopen; all changes are outcome-neutral mechanisms preserving D-001/D-006/D-008/D-009.
- Routing: A-004 exact strong Terra/xhigh completed after the full 45/90/120 cycle and automatic status polling; no user confirmation, replacement or route change.
- Primary signal: not yet met; fresh R-004 strong closure and implementation pending.
- Validation: critic independently ran the existing 4/4 delegation contract tests; package validator is expected non-green until 2.2.1 surfaces are implemented.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh strong closure, RED, bounded implementation, full validation and final review.

### 2026-07-16 — R-005/R-006 executable evidence and automatic activation

- Changed: specified canonical ledger/route/deadline/attestation/version evidence, then applied D-010 so every start receipt is immediately followed by activation and an unactivated timeout gets one fresh exact retry.
- Decisions: D-010 resolved from the current user example; D-001/D-006/D-008/D-009 preserved.
- Routing: A-005 exact strong Terra/xhigh completed on the same run after 45/90/120 observations; no user confirmation or replacement.
- Primary signal: not yet met; fresh R-006 strong closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: R-006 strong closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-007 atomic dispatch and lineage closure

- Changed: selected runner-owned atomic `dispatch`, one canonical ledger schema, mutually exclusive source action/shared retry budget, target plan→receipt lineage and explicit rollback graph closure.
- Decisions: no D reopen; D-010 remains automatic activation with exact receipt-before-prompt safety.
- Routing: A-006 strong Terra/xhigh completed on the same correctly activated run after three soft observations.
- Primary signal: not yet met; R-007 strong closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: R-007 strong closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-008 terminal-closure remediation

- Changed: added legal pre-start blocked transition, privacy-safe public projection, explicit dispatch runtime scope and rollback self-row exclusion.
- Decisions: no D reopen; all changes are technical applications of the locked automatic-orchestration outcomes.
- Routing: A-007 strong Terra/xhigh completed after the same-run 45/90/120 cycle and automatic polling; its coverage gaps authorize the terminal Sol/high closure step.
- Primary signal: not yet met; terminal R-008 closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-009 lane and receipt closure

- Changed: made the ledger total over contained/legacy/read-only lanes, allowed empty terminal triggers, separated retry predicates, defined state-aware errors and canonical plan/public receipt projection, and added contributor commit gates.
- Decisions: no D reopen; D-001/D-006/D-008..D-010 remain locked.
- Routing: A-008 exact Sol/high terminal critic completed after automatic same-run observation and returned six technical gaps.
- Primary signal: not yet met; fresh R-009 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-010 relational and crash-window closure

- Changed: added exact lane matrix/order, one auto-escalation per logical attempt, plan-bound orphan adoption, projection-error receipt, canonical plan/receipt state chain, strict route relations and complete autonomous-authority coverage.
- Decisions: no D reopen; all changes preserve the locked automatic behavior and user-question boundary.
- Routing: A-009 fresh Sol/high terminal critic completed after automatic observation and returned seven technical closure gaps.
- Primary signal: not yet met; fresh R-010 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-011 evidence and early-retry closure

- Changed: latest-state rollback chains, route-wide trigger plus next-profile binding, locally complete evidence domains/equalities, ordinary dispatch crash adoption and D-009 early-window retry grammar.
- Decisions: D-009 applied without reopening; all other decisions preserved.
- Routing: A-010 fresh Sol/high terminal critic completed after automatic observations and returned five technical/application gaps.
- Primary signal: not yet met; fresh R-011 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-012 identity and exhaustive-retry closure

- Changed: introduced acyclic authorization/action derivation, stable route-family identity with distinct source/target steps, locally closed source evidence, fresh ordinary dispatch generations and an exhaustive three-reason retry matrix.
- Decisions: no D reopen; the changes are internal orchestration mechanics under the existing autonomous authority.
- Routing: A-011 fresh Sol/high terminal critic completed after automatic observations and returned six technical closure gaps.
- Primary signal: not yet met; fresh R-012 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-013 authority and evidence closure

- Changed: unified canonical/malformed safe escalation authority, preserved actual resolver trigger lists, defined stopped-tree/post-stop digest objects and receipt equalities, and extended M1 through AC-55.
- Decisions: no D reopen; these corrections apply D-001/D-008 consistently without broadening unsafe recovery.
- Routing: A-012 fresh Sol/high terminal critic completed after automatic observation and returned four concrete closure gaps.
- Primary signal: not yet met; fresh R-013 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-014 timeout and classifier closure

- Changed: bound nonterminal observation receipts separately from terminal cancellation receipts and made raw canonical versus normalized-malformed escalation predicates disjoint.
- Decisions: no D reopen; runner state semantics and D-001/D-008 remain intact.
- Routing: A-013 fresh Sol/high terminal critic completed after automatic observation and returned two technical contradictions.
- Primary signal: not yet met; fresh R-014 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-015 observation-stage closure

- Changed: persisted exact checkpoint/hard/activation-gate observation stages, bound prompt proof to the same run/plan and aligned AC-18 with both legal action paths.
- Decisions: no D reopen; these are replay/validation mechanics under the locked autonomous policy.
- Routing: A-014 fresh Sol/high terminal critic completed after automatic observation and returned three technical gaps.
- Primary signal: not yet met; fresh R-015 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-016 root-completion nullability closure

- Changed: qualified target plan/receipt requirements to retry/escalation and preserved null targets for root-completion.
- Decisions: no D reopen; this aligns one stale criterion with the already selected action schema.
- Routing: A-015 fresh Sol/high terminal critic completed after automatic observation and returned one internal contradiction.
- Primary signal: not yet met; fresh R-016 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-017 lineage nullability propagation

- Changed: propagated kind-qualified target plan/receipt rules into T-119 and AC-25.
- Decisions: no D reopen; this removes the final stale duplicate of the root-completion nullability rule.
- Routing: A-016 fresh Sol/high terminal critic completed after automatic observation and identified that duplicate contradiction.
- Primary signal: not yet met; fresh R-017 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-018 stale-contract propagation

- Changed: qualified deadline-only evidence, aligned zero-match plan adoption with dispatch-once and made root-completion's null plan pair explicit in action-ID derivation.
- Decisions: no D reopen; these changes synchronize earlier T rows with the canonical section.
- Routing: A-017 fresh Sol/high terminal critic completed after automatic observation and returned three stale-contract contradictions.
- Primary signal: not yet met; fresh R-018 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-019 lane-order closure

- Changed: made automatic-action authorization follow exact contained, legacy and read-only terminal/stop/release gates.
- Decisions: no D reopen; no lane may fabricate registry/archive/lease evidence it does not own.
- Routing: A-018 fresh Sol/high terminal critic completed after automatic observation, confirmed R-018 and found one universal-ordering contradiction.
- Primary signal: not yet met; fresh R-019 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-020 lane-summary propagation

- Changed: propagated lane-specific gates into reload, data/migration, coverage and replay-risk text while retaining the distinct package-rollback registry fence.
- Decisions: no D reopen; summary prose now matches the canonical lane matrix.
- Routing: A-019 fresh Sol/high terminal critic completed after automatic observation, confirmed the lane matrix and found three stale summary references.
- Primary signal: not yet met; fresh R-020 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-021 action-table and milestone closure

- Changed: lane-qualified retry/escalation action-table close steps and updated B-059 to AC-60.
- Decisions: no D reopen; canonical lane and milestone rules are unchanged.
- Routing: A-020 fresh Sol/high terminal critic completed after automatic observation and found two stale summaries.
- Primary signal: not yet met; fresh R-021 terminal closure and implementation pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: fresh terminal closure, RED, bounded implementation, validation and final review.

### 2026-07-16 — R-022 outcome/scenario lane closure

- Changed: made the top-level outcome and escalation/retry scenarios exact across contained, legacy and read-only lanes.
- Decisions: no D reopen; only evidence wording changed to match the canonical lane matrix.
- Routing: A-021 fresh Sol/high terminal critic completed after automatic observation, confirmed AC-01..60 and found early contained/writer-only assumptions.
- Primary signal: readiness met by fresh R-022 `COVERED`; implementation signal pending.
- Version: patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: RED, bounded implementation, validation and final review.

### 2026-07-16 — R-022 Ready gate

- Changed: no normative change after R-022; status advanced to Ready.
- Routing: A-022 fresh Sol/high terminal critic returned `COVERED` with high confidence and complete concern-family evidence.
- Primary signal: readiness passed; M1 implementation may begin.
- Version: target patch 2.2.1 unchanged.
- Commit: not created.
- Remaining: TDD implementation, package validation, progressive review and release commit.

### 2026-07-16 — R-023 implementation and review closure

- Changed: added runner-owned atomic `dispatch`, privacy-safe activation/deadline evidence, soft observation mode, automatic 15-minute lifecycle instructions, bounded same-profile retry and malformed-escalation/root-completion authority contracts; synchronized manifest, changelog and both READMEs to 2.2.1.
- TDD: contract RED rejected missing automatic ownership; dispatch RED rejected the absent wrapper; a root remediation RED exposed duplicate JSON receipts; focused fixes made all signals green and added negative regression fixtures for manual activation and over-broad permission prompts.
- Delegation: A-023 produced verified zero writes plus a malformed escalation marker and was automatically normalized to the configured trigger; A-024 completed the exact next strong route under the single-writer lease. Root independently verified the allowed diff and primary signals before accepting the handoff.
- Validation: `python scripts/validate_package.py` passed; final `python -m unittest discover -s scripts -p "test_*.py"` passed 326 tests with 4 platform skips; `git diff --check` passed. The official plugin validator passed and the official skill validator passed under `PYTHONUTF8=1` after its default Windows `cp1252` read failed. Runtime smoke returned exactly one activated JSON receipt with an immutable deadline 900 seconds after activation.
- Review: A-025 returned REVISE for stale manual-control language; root remediated it with owner-doc and negative contract changes. A-026 independently returned ACCEPT with confidence 0.93. A pre-release README audit then closed stale third-checkpoint/new-writer wording, and A-027 returned final ACCEPT with confidence 0.94, no findings and no escalation recommendation.
- Minimality: reused existing start/activate/wait/cancel/rejection/finalization primitives and the Python standard library; no dependency, registry schema version or alternate control plane was added.
- Version: manifest and release documentation are 2.2.1; rollback remains package rollback to 2.2.0 under the existing registry-vacancy fence.
- Commit: root-owned scoped release commit follows this final log.
- Remaining: publish the authorized 2.2.1 release artifacts; no implementation or review blocker remains.
