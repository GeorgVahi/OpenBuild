# Build: совместимая финализация terminal lease после обновления OpenBuild

- Status: Complete
- Last updated: 2026-07-18
- Original request: выяснить, почему уже выполненная и опубликованная задача оставила non-vacant single-writer registry, заблокировала следующую задачу, безопасно исправить OpenBuild и исключить повторение сценария.
- Primary signal: regression trace создаёт terminal state в формате 2.2.1, загружает его текущим reader, подтверждает старый binding без downgrade, а для уже закоммиченного same-scope результата отдельный user-authorized owner transition доказуемо invalidates checkpoint, закрывает guardian/archive и освобождает lease без handoff, нового writer или изменения workspace.
- Review baseline: `main@bbb701c894e463741013b3bc89939970dbac9698`; исходное состояние чистое (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: discovery
- Specification revision: R-007
- Complexity: high — меняются backward compatibility durable binding, terminal state transitions, Git provenance, single-writer concurrency и security boundary освобождения lease.
- Implementation mode: TDD-first — меняются persistence/compatibility/state-machine contracts.
- Version impact: patch `2.2.2` → `2.2.3` — backward-compatible исправление released lifecycle; authoritative source `plugins/openbuild/.codex-plugin/plugin.json`, синхронные поверхности `CHANGELOG.md`, `README.md`, `README.ru.md`, recovery reader floor и workflow contracts.
- Routing mode: `codex-exec-explicit-model`
- Discovery mode: mixed — exact search process завершился transport-success, но не нашёл тестовую точку и compatibility defect; после `unusable-evidence` выполнен один targeted root-recovery по уже локализованным owner symbols/tests.
- Search usage route: separate-pool → targeted root-recovery; второй discovery run не создавался.
- Search routing receipt: packaged map `OpenBuild defaults`, SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, discovery/default step 1/1, exact `openbuild_search_separate`, configured/observed `gpt-5.3-codex-spark`/low/read-only, `turn.completed`, exit 0, valid result, stopped tree; semantic result incomplete for tests/compatibility, normalized `unusable-evidence`.
- Implementation model route: resolve packaged `implementation.high`; expected start `openbuild_implementation_balanced`, further steps only after a valid configured pre-edit trigger.
- Implementation routing receipt: packaged map `OpenBuild defaults`, SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, implementation/high. Step 1 `openbuild_implementation_balanced` (`gpt-5.6-terra`/medium/workspace-write) completed transport-success before edit with semantic `NEEDS_ESCALATION`, adjudicated configured trigger `task-complexity-above-tier`; exact zero-write status confirmed, source checkpoint invalidation completed and registry vacant. Step 2 `openbuild_implementation_strong` (`gpt-5.6-terra`/xhigh/workspace-write) owned all M1 edits and completed `turn.completed`/exit 0/valid result/stopped tree. Independent root validation initially found one test tuple mismatch; active-lease Python validation also produced exact generated `__pycache__` outside-set drift, so the lifecycle was closed through `terminal-abandonment-v1`, checkpoint invalidation and exact vacancy rather than accepted handoff. Root used the existing same-scope completion authority, fixed the test binding and proof-phase mutation under TDD, reran 331 focused tests green, and recorded `_record-root-completion` with exact allowed-set/diff attribution.
- Review routing receipt: packaged high-risk route `openbuild_review_balanced` → `openbuild_review_strong` → `openbuild_review_sol_high`, map SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`. Earlier ladders exhausted their configured routes and every concrete finding was remediated through RED/GREEN. The final user-authorized fresh cycle started again at exact `openbuild_review_balanced` (`gpt-5.6-terra`/medium/read-only) and completed with valid `turn.completed`, exit 0, valid result and stopped tree; verdict `ACCEPT`, high confidence, complete AC-01–AC-12 coverage, no finding and no escalation trigger.

## 1. Outcome

### Problem

OpenBuild 2.2.1 успешно завершил writer (`turn.completed`, exit 0, valid result, full-tree zero), но terminal binding, записанный в registry, был digest от receipt с полем `run_dir`. В 2.2.2 public receipt стал privacy-safe и terminal binding был заменён на `run_id`; reload пересчитывает другой digest и fail-closed останавливается на `terminal receipt binding drifted during reload`.

После этого root уже создал и опубликовал task commit. Revalidation поэтому возвращает одновременно `git-control-plane-drift` и `outside-set-drift`. Автоматический `terminal-abandonment-v1` 2.2.2 по сохранённому D-003/T-003 контракту разрешён только для exact `[outside-set-drift]`, поэтому force-unlock корректно не произошёл, но owner API для доказанного уже завершённого post-commit результата отсутствует.

### Desired behavior

1. Новый reader распознаёт immutable terminal binding форматов 2.2.0/2.2.1 и текущего формата, принимает только digest, вычисленный из exact current run/receipt evidence, и не требует запуска старого кода.
2. Обычный успешный workflow всегда финализирует и освобождает lease до любых root workspace/Git/spec/version writes.
3. Для уже случившегося legacy post-commit состояния существует отдельный explicit user-authorized owner transition. Он принимает exact run и commit/evidence digests, сам доказывает commit provenance и allowed scope, не принимает handoff и не изменяет workspace.
4. Любая ambiguity процесса, guardian, identity, run, commit ancestry/parent, allowed paths, outbox, reason set или user authorization остаётся fail-closed без mutation.
5. После установленного исправления застрявшая задача может быть закрыта owner-командой; следующий writer запускается только после доказанной vacancy.

### In scope

- Backward-compatible verification terminal binding `run-dir-v1` и `run-id-v2`.
- Exact owner transition для verified post-commit root completion существующего stopped terminal lifecycle.
- Registry/source schema, reader-floor, replay/fault и negative tests.
- Static workflow guards, EN/RU docs, changelog и patch version 2.2.3.
- Операторская инструкция для уже застрявшего состояния без раскрытия private registry paths/nonces.

### Out of scope

- Ручное удаление registry/source/run artifacts.
- Автоматический mixed-reason abandonment или generic force-unlock.
- Откат/переписывание опубликованного task commit либо пользовательских изменений.
- Принятие старого worker handoff задним числом.
- Новый recovery writer, provider, dependency, hosted automation, tag/GitHub Release или изменение внешнего Lazy Trader workspace в рамках этого repository task.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Legacy binding | `v2.2.1:plugins/openbuild/skills/build/scripts/agent_runner.py:2652-2673` | `_terminal_binding` включает `run_dir`. | Stored 2.2.1 digest нельзя пересчитать текущей функцией. |
| Current binding | `plugins/openbuild/skills/build/scripts/agent_runner.py:3202-3222` | 2.2.2 binding заменяет path на `run_id`. | Privacy fix создал unhandled persisted-format transition. |
| Reload failure | `plugins/openbuild/skills/build/scripts/agent_runner.py:3473-3489` | Для stopped lease принимается только новый digest. | Успешный terminal lifecycle остаётся non-vacant. |
| Exact run owner | `plugins/openbuild/skills/build/scripts/agent_runner.py:3191-3199,3446-3448` | Current lease/plan уже владеет expected `run_id`. | Legacy digest можно проверить без ослабления run identity. |
| Mixed drift | `plugins/openbuild/skills/build/scripts/recovery_state.py:3401-3452` | HEAD/ref/index drift и outside records дают отдельные reasons. | Root commit закономерно создаёт смешанный набор. |
| Abandonment boundary | `plugins/openbuild/skills/build/scripts/recovery_state.py:4095-4169` | Автоматический abandon требует exact `[outside-set-drift]`, stopped success, zero и no outbox. | Generic mixed release нарушил бы locked fail-closed contract. |
| Terminal release | `plugins/openbuild/skills/build/scripts/recovery_state.py:4520-4594` | Close/release требует zero, guardian close, semantic invalidation и архив. | Новый outcome обязан пройти существующие owner gates. |
| Missing regression | `scripts/test_recovery_state.py:2244-2317` | Legacy fixture меняет reader floor, но terminal digest создаёт текущим helper и вызывает registry owner напрямую. | Runner-level 2.2.1 `run_dir` binding mismatch не воспроизведён. |
| Mixed negative | `scripts/test_recovery_state.py:2019-2056` | Mixed drift обязан отказать обычному abandonment без mutation. | Нужен отдельный authorized outcome, а не ослабление v1. |
| Ordering contract | `plugins/openbuild/skills/build/references/implementation-delegation.md:40-44,181-194` | Root writes/Git разрешены только после `_finalize-success` и vacancy. | Предотвращение уже заявлено, но compatibility trace/validator не ловит нарушение. |
| Version policy | `CONTRIBUTING.md:14-31`; `plugins/openbuild/.codex-plugin/plugin.json:3` | Каждый commit повышает manifest и синхронизирует docs/changelog. | Target patch 2.2.3 и новый reader floor входят в один commit. |

### Source of truth

`RecoveryRegistry` владеет persisted lifecycle и Git snapshot provenance; `reconcile_implementation_registry` владеет terminal receipt/run/guardian orchestration. Совместимость и remediation должны находиться в этих owners, а не в session-wrapper prose или downstream удалении файлов.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decisions | Outgoing normative links | Editable | Reconciliation |
|---|---|---|---|---|---|---|
| `BUILD-terminal-finalization-2.2.3.md` | current user + repository root spec | R-007 | D-001–D-008, T-001–T-009, AC-01–AC-12 | current owner/contracts listed below | yes | root |
| `BUILD-recovery-autonomy-2.2.2.md` | accepted historical user decision record | Complete R-005 | existing D-001–D-004; exact outside-only abandonment and no-force boundary | its source graph is closed at `:85-102`; current editable owners are mapped below, frozen historical BUILD nodes are not rewritten | no | aligned; current incident adds new evidence |
| `plugins/openbuild/skills/build/SKILL.md` | packaged workflow owner | 2.2.3 | lifecycle/order/authority/reporting | implementation/model/TDD/minimality/review/version references | yes | aligned: legacy binding and post-commit owner flow documented |
| `plugins/openbuild/skills/build/references/implementation-delegation.md` | single-writer and terminal order owner | 2.2.3 | D-001–D-003, root handoff/vacancy | model routing/TDD | yes | aligned: exact legacy incident and bytecode-artifact boundary |
| `plugins/openbuild/skills/build/references/model-routing.md` | exact route owner | 2.2.3 | no transport fallback/new writer | implementation/review | yes | aligned: post-commit completion is not routing |
| `plugins/openbuild/skills/build/references/tdd-workflow.md` | behavioral test owner | 2.2.3 | red/green recovery trace | delegation/minimality | yes | aligned: historical binding/post-commit/fault trace |
| `plugins/openbuild/skills/build/references/minimality-protocol.md` | technical minimality owner | 2.2.2 unchanged | owner-layer/no parallel fallback | none in scope | yes | aligned |
| `plugins/openbuild/skills/build/references/review-protocol.md` | high-risk acceptance owner | 2.2.3 | final recovery review gates | TDD/minimality/versioning | yes | aligned: compatibility/post-commit evidence required |
| `plugins/openbuild/skills/build/references/versioning.md`, `CONTRIBUTING.md` | version/release owner | current | patch/reader-floor/same-commit sync | manifest/changelog/READMEs | yes | aligned |
| `README.md`, `README.ru.md`, `CHANGELOG.md`, manifest | public behavior/version record | 2.2.3 | install/update/recovery behavior | release contract above | yes | aligned; validation/review pending |

Historical `BUILD-auto-continuation-2.2.1.md` and `BUILD-route-recovery-safety.md` remain frozen evidence already reconciled by the accepted 2.2.2 source graph; this task does not change their decisions or acceptance records.

### Source reconciliation receipts

| Conflict | Resolution basis | Authority | Result |
|---|---|---|---|
| Legacy private `run_dir` vs privacy-safe `run_id` | append exact compatible binding verifier; public receipt remains path-free | D-005 + current run evidence | aligned |
| Existing exact outside-only abandonment vs mixed post-commit incident | keep automatic v1 unchanged; add separate explicit verified-root-completion outcome | D-003/D-006 | aligned |
| Already published task commit vs no Git writes under lease | do not rollback; owner verifies historical commit and closes producer as no-handoff root completion | D-001/D-006 | aligned |

### Gap

Нет version-aware terminal binding verification и нет owner transition, который может безопасно закрыть legacy stopped-terminal после уже выполненного same-scope root commit, сохраняя exact mixed-drift fail-closed boundary.

## 3. Decision memory

### User-owned decisions

| ID | Decision key | Status | Selected outcome | Evidence | Consequence |
|---|---|---|---|---|---|
| D-001 | `automation.failure.root-remediation` | resolved/preserved | original `run/full` даёт bounded root-only same-scope remediation authority | accepted 2.2.2 decision record | не разрешает replacement writer |
| D-002 | `authorization.recovery-writer` | resolved/preserved | новый writer остаётся explicit opt-in и eligible/vacant only | accepted 2.2.2 decision record | не используется для unlock |
| D-003 | `automation.fail-closed-boundary` | resolved/preserved | unknown/mixed automatic abandonment, containment/ownership ambiguity и force-unlock запрещены | accepted 2.2.2 decision record | ordinary v1 остаётся exact outside-only |
| D-004 | `workspace.orchestration-artifacts` | resolved/preserved | owner-private artifacts вне workspace | accepted 2.2.2 decision record | private paths не публикуются |
| D-005 | `compatibility.terminal-binding-upgrade` | resolved | текущий OpenBuild обязан безопасно финализировать persisted terminal state предыдущего released формата без downgrade или ручного удаления | текущий запрос пользователя и приложенный incident trace | binding format становится explicit compatibility contract |
| D-006 | `recovery.completed-postcommit` | resolved | уже выполненный/опубликованный same-scope commit закрывается отдельным user-authorized owner transition только после independent Git/scope/terminal proof; без rollback, handoff или нового writer | текущий запрос после предложенной owner-level remediation | mixed drift не становится автоматическим force-unlock |
| D-007 | `authorization.postcommit-remediation-entrypoint` | resolved | В текущем Build-сеансе пользователь один раз явно подтверждает owner-only remediation exact opaque run handle + full task commit. После ответа trusted root controller создаёт owner-private action snapshot и через отдельный hidden issuance step получает одноразовую opaque capability, связанную с active-session action ID, exact run/commit/verification/scope tuple и expiry. Finalization атомарно потребляет capability под registry lock и сам повторно доказывает все наблюдаемые условия. Exact completed replay идемпотентен без повторного consumption/mutation; missing/expired/consumed capability и использование с другим run/commit/verification отвергаются. Пользователь получает только closed `terminal-root-completed` либо `blocked` с privacy-safe reason tokens. | текущий ответ пользователя `1а`; strong closure critic R-003 потребовал owner-enforceable issuance/capability boundary | observable current-session flow есть без public force API, raw registry path/nonce или ручного digest ввода |
| D-008 | `authorization.local-owner-principal` | resolved | Текущий OS account является допустимым owner principal для explicit remediation. Репозиторий не заявляет криптографическое различение Codex controller, активного chat response и другого процесса того же account. Current-session confirmation остаётся operator UX/audit correlation; security boundary — same-account owner плюс exact lifecycle/Git/scope proofs. | текущий ответ пользователя `A` после final Sol closure R-004 | repository-only реализация разрешена; same-account malicious process явно вне threat model, capability остаётся защитой от accidental/replay/cross-tuple use |

### Technical decision ledger

| ID | Mechanism | Status | Evidence/alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Один owner helper вычисляет version-tagged candidate records для current `run-id-v2` и legacy `run-dir-v1`; tag не входит в исторический hashed payload. `run-dir-v1` в точности реконструирует прежний `str(run_dir.resolve())` и прежний closed field order, но принимается только после current owner checks: directory name=`expected_run_id`, stable canonical path/object identity совпадает с загруженными private request/run artifacts, а alternate equivalent-name/different-path не существует. Stored digest обязан совпасть ровно с одним candidate; zero/multiple/dual match блокируется, downstream использует matched immutable digest. | selected | минимально расширяет `agent_runner.py`; downgrade и mutation registry не нужны; exact legacy serialization подтверждена tag v2.2.0/v2.2.1 | D-003/D-005, exact run/receipt/path identity сохраняются без публикации path |
| T-002 | Обычный `terminal-abandonment-v1` не меняется. Новый private transition `terminal-root-completion-v1` принимает exact run, full commit SHA, root verification digest и canonical user-action digest. | selected | отдельный outcome предотвращает расширение automatic abandon | D-001/D-003/D-006; caller не передаёт cause/paths/force flag |
| T-003 | Owner сам требует stopped transport success, authenticated zero, no outbox/handoff/quarantine, exact legacy binding, current reasons exactly `git-control-plane-drift + outside-set-drift`, full task commit ancestry и parent=`pre_snapshot.head`. NUL-decoded task-commit path set обязан в точности совпасть с отдельным `remediation-scope-v1` manifest: producer entries проходят исходный checkpoint `allowed_paths`, root-completion entries проходят exact same-account authorization/root attribution и не подменяют producer allowed-set. Preliminary proof фиксирует exact current `HEAD`, symbolic ref, full index, status/record snapshot, task commit metadata/path manifest и descendant commit IDs; непосредственно перед первым durable intent write под registry lock owner повторно захватывает тот же snapshot и требует byte-equality. Ref/index/worktree/commit drift между proof и barrier даёт no-mutation failure; committed intent сохраняет exact observed Git-provenance digest, поэтому более позднее независимое изменение не переопределяет proof. | selected | Git provenance/snapshot уже принадлежит `RecoveryRegistry`; разделяет writer allowlist и полный task/remediation scope | не принимает stale/чужой task commit/path attribution и не требует считать later descendant changes частью task commit |
| T-004 | Exact `terminal-root-completion-v1` schema содержит `disposition=root-completed`, run/lease/source IDs, source checkpoint/producer-allowed-set/remediation-scope/terminal-binding(format+digest)/zero/candidate/Git-provenance digests, full task commit, root verification digest, user-action/authorization digests, `checkpoint_invalidation=pending|completed` и completed-only checkpoint digest. Durable order: (1) registry intent `pending` + one history event and terminal success=false/no handoff; (2) source checkpoint invalidation `post-commit-root-completed` bound to the same evidence digest; (3) registry `completed` bound to the exact invalidated checkpoint digest; (4) existing guardian close → validated archive → release. Reload starts from the authoritative completed phase, validates every cross-binding and creates no duplicate event/invalidation/archive. | selected | intent-first replay avoids source mutation without a durable owner instruction; separate scope digest closes the producer/task ambiguity | D-003, zero/identity/archive invariants сохраняются |
| T-005 | Первый новый durable shape поднимает reader floor до 2.2.3; 2.2.0–2.2.2 читаются без rewrite-on-read, downgrade после нового write fail-closed до vacant retirement. | selected | recovery state-machine version contract | backward read и downgrade safety сохранены |
| T-006 | No dependency/service/public force API; runtime/tests в существующих owners, docs/version root-owned после lease release. | selected | minimality ladder | scope/observable outcome без лишней инфраструктуры |
| T-007 | После operator confirmation root controller текущего OS account создаёт canonical owner-private snapshot `post-commit-root-completion-user-action-v1` через существующий private snapshot owner. Snapshot содержит random 256-bit `session_action_id` только для audit correlation, exact normalized answer/intent, workspace identity digest, opaque run ID, full task commit, specification revision, milestone, producer allowed-set digest, remediation-scope digest и root-verification digest; public workspace/report его не получает. Hidden `_authorize-post-commit-root-completion` принимает snapshot ID+SHA и recomputable exact tuple, атомарно помечает snapshot issued и создаёт owner-private `post-commit-root-completion-authorization-v1` с random 256-bit capability, issued/expiry timestamps, tuple digest и `status=issued`. Один snapshot не может выпустить две capabilities; отсутствие/подмена/replay snapshot блокируется. По D-008 trust boundary — текущий OS account и owner-private state: repository tests доказывают issuance/tuple/replay mechanics, но не provenance chat response против другого same-account процесса. | selected | переиспользует staged private snapshot/durable owner patterns и честно ограничивает security claim | пользователь не вводит и не видит nonce/digest/private path; finalize без issued capability не проходит, а same-account issuance является owner-authorized по D-008 |
| T-008 | Hidden `_finalize-post-commit-root-completion` принимает opaque run handle, exact full task commit, root-verification digest и opaque authorization handle; raw capability material читается owner’ом только из private state и не передаётся в workspace/public receipt. Под registry lock owner требует `status=issued`, not expired, matching active-session action/run/commit/verification/scope tuple и затем в одном durability boundary связывает authorization digest с первым terminal intent и переводит capability в `consumed`. Crash/reload не оставляет consumed capability без matching intent и не допускает intent с reusable capability. Exact replay после completed transition сверяет сохранённые authorization/tuple digests и возвращает тот же closed success без второго consumption/event/invalidation/archive; replay до completion продолжает authoritative phase, а reuse capability с другим tuple или после unrelated blocked attempt отвергается. Stdout содержит только `outcome=terminal-root-completed`, schema, already-public task commit, `registry_vacant=true`, `writer_action=none` либо `outcome=blocked`, allowlisted `missing_evidence`, `required_action=restore-safety-evidence`, `writer_action=none`; stderr/receipts не раскрывают snapshot/capability/private paths/nonces. | selected | capability consumption является частью owner state transition, а не caller-asserted hash | explicit exact authorization не становится automatic unlock или generic public recovery API |
| T-009 | `remediation-scope-v1` — owner-private canonical manifest exact task-commit paths, каждый entry имеет normalized path и role=`producer|root-completion`. Digest domain-separated и связан с full task commit/parent, source checkpoint, specification revision, milestone, producer allowed-set digest и root verification. Owner сам recomputes commit paths: `producer` обязан проходить immutable checkpoint allowlist; `root-completion` обязан быть exact отдельным manifest entry, утверждённым same-account action snapshot и diff-attribution proof. Commit path set обязан равняться manifest path set; duplicate/overlap/unknown role, missing/extra path или manifest, который просто расширяет producer allowlist для будущего writer, блокируется. Current candidate outside-set delta хранится отдельно и может включать later descendant/uncommitted paths, но они не приписываются task commit, не входят remediation scope и остаются untouched; preexisting-overlap/unknown reason по-прежнему блокирует exact transition. | selected | faithfully explains task commit that legally includes root-owned completion files outside producer allowlist | не ослабляет future writer scope и не принимает unrelated path как часть завершённого commit |

Decision applied: D-007 фиксирует одноразовый exact run+commit owner flow, controller-issued private capability, atomic owner consumption и closed result contract. D-008 принимает текущий OS account как owner principal и запрещает заявлять недоказуемую chat-provenance защиту; blocking user decisions отсутствуют.

## 4. Scenarios and edge cases

### Primary legacy-binding scenario

1. 2.2.1 persisted `stopped-terminal` с digest от exact private `run_dir` receipt.
2. 2.2.3 reconstructs the same private run and receipt, matches `run-dir-v1`, does not rewrite on read and continues the owner lifecycle.
3. Ordinary exact outside-only state follows existing abandonment; normal success follows existing verified `_finalize-success`.

### Already committed scenario

1. Legacy task commit is an ancestor of current HEAD, its first parent equals snapshot HEAD, and every changed path is allowed.
2. Current user explicitly authorizes the exact opaque run handle + full task commit in the active Build session; root independently validates primary signal and stages a canonical owner-private user-action snapshot without asking the user for raw digests or private paths.
3. Hidden issuance command consumes that snapshot once and returns an opaque handle to a short-lived owner-private capability bound to the exact session action/run/commit/verification/scope tuple.
4. Hidden finalize command requires and atomically consumes the capability with the first `terminal-root-completion-v1` intent, invalidates the unusable checkpoint, closes containment/archive and releases without handoff.
5. Root accepts only closed `terminal-root-completed` with `registry_vacant=true`; an exact completed replay is idempotent, while absent/expired/consumed or cross-run/commit/verification capability use returns privacy-safe `blocked` without a second semantic transition.
6. Unrelated later workspace changes remain untouched.

### Errors

- Current-format state matching only `run-id-v2` → normal behavior.
- Neither or ambiguous binding candidate matches → blocked, no mutation.
- Commit missing/not full SHA/not ancestor/wrong parent/contains outside allowed path → blocked, no mutation.
- Reasons differ from exact mixed pair or contain preexisting overlap/unknown → blocked, no mutation.
- Missing user confirmation/snapshot/capability/remediation manifest, malformed/non-full commit, commit path missing/extra/role overlap, producer path outside immutable allowlist, root-completion attribution mismatch, snapshot/action/tuple mismatch, expired or already-consumed capability, replay against another run/commit/verification/scope or private-path input → blocked, no lifecycle mutation and no private data in the result; exact issued/completed replay follows T-008 only.
- Live/unknown tree, quarantine, identity/run/lease mismatch, outbox/handoff present → blocked, no mutation.
- Crash after registry intent pending, visible source invalidation, registry completed or guardian close → replay resumes the phase recorded by the exact cross-bound evidence exactly once.
- New implementation never commits/spec-writes before `_finalize-success` vacancy; regression contract fails if ordering prose/static guard is removed.

## 5. Acceptance criteria and invariants

- [x] AC-01: Runner-level fixture reproduces a real 2.2.1 `run_dir` terminal binding and proves 2.2.3 reload/reconcile accepts it while current `run-id-v2` and mismatched bindings retain exact behavior.
- [x] AC-02: Compatible binding verification uses version-tagged internal candidates, exact historical `str(run_dir.resolve())` serialization/current run ID, stable private path/object identity and the same closed receipt fields; zero/multiple/dual matches and equivalent-name/different-path candidates reject, while public receipts remain free of private path/profile/artifact data.
- [x] AC-03: `terminal-abandonment-v1` remains exact `[outside-set-drift]`; mixed reasons still reject its automatic path byte-for-byte.
- [x] AC-04: Explicit post-commit transition is reachable only after the same-account operator flow records confirmation of exact opaque run handle + full task commit, one-time action-snapshot issuance and presentation of the matching unexpired owner-private capability. It requires the canonical closed action/run/commit/verification/producer-allowed-set/remediation-scope tuple, root verification, stopped success/zero/no outbox, exact legacy binding, exact mixed reasons and owner-verified full commit ancestry/parent/path proof. Exact task commit paths equal `remediation-scope-v1`; producer entries pass immutable checkpoint allowlist, separately attributed root-completion entries pass the authorized manifest. Owner re-captures/byte-compares exact HEAD/ref/index/status/record/commit provenance immediately before atomically consuming capability with durable intent. Tests do not claim to authenticate chat provenance beyond D-008's OS-account principal.
- [x] AC-05: Successful post-commit remediation creates no handoff/new writer/retry/escalation, mutates no workspace/Git data, permanently invalidates the checkpoint, records privacy-safe terminal evidence, closes guardian/archive and leaves registry vacant.
- [x] AC-06: Wrong/ambiguous run, path identity, binding candidate, commit, ancestry/parent/path scope, missing/extra/duplicate remediation entry, producer/root role mismatch, reasons, process/guardian/identity, source/checkpoint/authorization evidence, missing/forged/expired/consumed capability, duplicate issuance, capability reuse against another tuple or ref/index/worktree race fails without lifecycle mutation where the durable phase has not begun; blocked output contains only allowlisted reason tokens.
- [x] AC-07: Exact-schema and fault/reload tests cover producer allowed-set vs remediation-scope separation, action snapshot → single issuance → atomic capability-consumption/intent-pending → source-invalidated → registry-completed → guardian/archive/release, every scope/authorization cross-binding and before-barrier Git race, proving one issuance, one consumption, one semantic event, one invalidation and one archive/release; exact completed replay is idempotent.
- [x] AC-08: Reader-floor fixtures load 2.2.0–2.2.2 without rewrite, raise to 2.2.3 on the first new transition and reject unsafe downgrade.
- [x] AC-09: Workflow/static contracts require finalization/vacancy before any root workspace, specification, version or Git write and require append-only terminal-binding compatibility tests for future receipt projection changes.
- [x] AC-10: Operator docs explain incident cause and the same-account confirmation → private one-time issuance → hidden owner finalization → closed result flow in English and Russian. They document the D-008 local-owner threat boundary, capability expiry/reconfirmation, exact idempotent replay, privacy-safe `terminal-root-completed|blocked`, and prohibited manual deletion/rollback/replacement-writer/private-capability actions without exposing private values.
- [x] AC-11: Manifest/changelog/README/recovery reader floor agree at 2.2.3; no tag/release publication is claimed.
- [x] AC-12: Focused/full tests, package validator, diff/commit gate and risk-matched independent review pass with no actionable finding.

Invariants:

- Один writer; root/Git/docs/version edits только после exact vacancy.
- No force-unlock, no live/unknown release, no retroactive worker handoff.
- No raw private paths/nonces/prompts in public receipt, checkpoint, archive, spec or report.
- Unrelated/user changes and published commit remain untouched.
- New recovery writer remains separate explicit eligible/vacant path.

## 6. Technical boundaries

- Runtime owners: `plugins/openbuild/skills/build/scripts/agent_runner.py`, `recovery_state.py`.
- Test owners: `scripts/test_agent_runner.py`, `scripts/test_recovery_state.py`.
- Static contract owners: `scripts/validate_package.py`, `scripts/test_validate_package.py`.
- Workflow docs: `SKILL.md`, implementation/model/TDD/review/version references.
- Release docs: manifest, changelog, README/README.ru.
- Data migration: no workspace migration/backfill; owner-private registry forward transition only.
- Security/privacy: session action IDs, snapshots, capabilities and verification digests are same-account controller/owner-generated private inputs, never user-entered secrets; capability raw material is excluded from workspace, command output and public receipts. Report exposes only a closed outcome, allowlisted blocked reason tokens and the commit SHA when already public/non-sensitive. Same-account hostile processes are outside the accepted threat model and no chat-provenance authentication is claimed.
- Concurrency: all verification and durable transitions under existing registry/source locks; Git commands are read-only and bounded.
- Rollback: code rollback to 2.2.2 allowed only before any 2.2.3 registry write or after explicit vacant retirement; never downgrade a non-vacant 2.2.3 registry.

## 7. Validation and review

- Red: focused runner fixture persists the 2.2.1 binding, then current reconcile raises `terminal receipt binding drifted during reload`; post-commit fixture remains occupied because ordinary abandonment rejects mixed reasons.
- Minimality: custom owner-layer — reuse existing binding, snapshot, Git, semantic invalidation, guardian/archive/release owners; skip new service/dependency/general unlock.
- Focused green: `python -m unittest scripts.test_agent_runner scripts.test_recovery_state scripts.test_validate_package -v` — 333 tests, 4 platform skips, exit 0.
- Wider: `python -m unittest discover -s scripts -p "test_*.py" -v` — 348 tests, 4 platform skips, exit 0; `python scripts/validate_package.py` passed; `git diff --check` passed.
- Commit gate: `git diff --cached --check`; `python scripts/validate_package.py --commit-gate`.
- Review: high-risk balanced start, sequential escalation only on configured concrete findings; focus compatibility, Git provenance, crash consistency, privacy, no-force and version parity.

## 8. Milestones

### M1. Compatibility and post-commit owner transition

- Status: Complete
- Implementation mode: TDD-first
- Delegation: bounded-worker after Ready; exact high-risk profile from model map.
- Allowed worker files: `plugins/openbuild/skills/build/scripts/agent_runner.py`, `plugins/openbuild/skills/build/scripts/recovery_state.py`, `scripts/test_agent_runner.py`, `scripts/test_recovery_state.py`, `scripts/validate_package.py`, `scripts/test_validate_package.py`.
- Forbidden worker files: this specification, manifest, changelog, READMEs, workflow docs, Git/index.
- Red/green: AC-01–AC-09 focused suite.
- Minimality: existing owner state machine; no dependency/service/force API.
- Acceptance: AC-01–AC-09.
- Review: all actionable findings from earlier tiers were remediated and the final fresh balanced reviewer returned `ACCEPT` with high confidence and no finding.
- Version/commit: root-owned after handoff/release.

### M2. Contract, version, docs and final validation

- Status: Complete
- Implementation mode: Direct for synchronized prose/version; TDD-first if validator behavior changes after M1.
- Delegation: root-only after M1 registry vacancy; reviewers read-only.
- Scope: workflow references, manifest 2.2.3, changelog, README parity, full suite, progressive review, scoped commit.
- Acceptance: AC-09–AC-12.
- Publication: none.

## 9. Coverage and risks

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence/decision |
|---|---|---|---|---|
| B-001 | outcome/scope/non-goals | covered | product + technical | current request, D-005/D-006, T-009 writer/task scope split, AC-01–AC-12 |
| B-002 | actors/permissions/authority | covered | product decision | D-008 explicitly selects current OS account as owner principal |
| B-003 | primary/error/recovery flows | covered | technical decision | T-001–T-004/T-009, scenarios, AC-01–AC-07 |
| B-004 | accessibility/localization/responsive UI | not applicable | repository fact | CLI/plugin; EN/RU docs covered AC-10 |
| B-005 | ownership/contracts/source of truth | covered | repository fact + technical decision | lifecycle/registry owners mapped; immutable producer allowlist and separate T-009 remediation manifest have distinct owners |
| B-006 | data/schema/migration/retention | covered | technical decision | T-004/T-005, AC-07/AC-08 |
| B-007 | security/privacy/abuse | covered | product + technical | D-008 accepted local-owner boundary; T-007/T-008 cover accidental/replay/cross-binding/privacy |
| B-008 | concurrency/ordering/idempotency | covered | technical decision | locks, replay, AC-05/AC-07/AC-09 |
| B-009 | integrations/timeouts/partial failure | covered | technical decision | existing guardian lifecycle + fault matrix |
| B-010 | compatibility/rollout/rollback | covered | product + technical | D-005, T-001/T-005, AC-01/AC-08/AC-11 |
| B-011 | observability/support/docs | covered | product decision | T-007 closed success/blocked contract and AC-10 EN/RU operator flow |
| B-012 | acceptance/testability/minimality/cost | covered | product + technical | tests reproduce root-completion path outside producer allowlist plus local-owner issuance/state mechanics |
| B-013 | Git provenance/path attribution | covered | technical decision | T-003/T-009, AC-04/AC-06 exact commit path manifest and Git barrier |
| B-014 | current external stuck registry execution | not applicable | repository fact | this repo task builds the fix; installing/running it against Lazy Trader is a separate explicit global/external action |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Legacy candidate becomes broad digest bypass | low/critical | exact closed fields + exact resolved run identity + negative ambiguity tests | mitigated |
| User digest is treated as proof without Git/scope evidence | medium/critical | owner computes ancestry/parent/path/reason proof itself | mitigated |
| Hidden local invocation forges current-session approval | medium/critical | one-time controller-staged action snapshot, random owner-issued capability and atomic consumption | mitigated within D-008 boundary |
| Same-account process cannot be distinguished from active Codex controller | inherent/high | D-008 accepts OS account as owner principal; docs/tests must not claim a stronger chat-provenance boundary | accepted |
| Producer allowlist is mistaken for full task/root-completion scope | medium/critical | immutable producer digest plus separate exact task-commit remediation manifest/digest and negative role/path tests | mitigated |
| Mixed transition becomes automatic force-unlock | medium/critical | separate private explicit command; v1 unchanged | mitigated |
| Crash leaves a newer retained lease | medium/high | two-phase invalidation and boundary replay tests | mitigated |
| Future receipt privacy change repeats incompatibility | medium/high | centralized append-only compatibility helper + validator mutation guard | mitigated |
| Docs encourage unsafe manual cleanup | low/high | explicit prohibited actions and owner-only procedure | mitigated |

### Decision application receipt

| Decisions | Source | Applied sections | Preserved | Open |
|---|---|---|---|---|
| D-001–D-004 | accepted `BUILD-recovery-autonomy-2.2.2.md` | outcome, exclusions, invariants, AC-03–AC-06 | no new writer/no force/private artifacts | none |
| D-005/D-006 | current user request after incident/remediation proposal | compatibility and separate post-commit outcome | D-001–D-004 and published/user changes | none |
| D-007 | current user answer `1а` | D-007, T-007/T-008, already-committed/errors scenarios, AC-04/06/07/10, B-002/B-007/B-011 and M2 | D-001–D-006; no force/public API/private disclosure | none |
| D-008 | current user answer `A` | D-008, T-007, AC-04/10, security boundary, B-002/B-005/B-007/B-012 and risk register | D-001–D-007; exact proofs/capability/privacy remain | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | Findings | Adjudication |
|---|---|---|---|---|
| R-001 | product/operator UX, balanced | GAPS/high confidence | operator entrypoint, single-use attestation and observable result missing | NEW operator gap → D-007 open; no dependent flow applied |
| R-001 | architecture/data/security, balanced | GAPS/high confidence | Git provenance TOCTOU, durable phase order, legacy path identity | applied outcome-neutral T-001/T-003/T-004 and AC-02/04/06/07 in R-002; B-006/B-007/B-013 covered |
| R-003 | reliability closure, strong | GAPS/high confidence | deterministic digest did not enforce current-session approval against arbitrary hidden local invocation | applied owner-technical private issuance/capability/atomic-consumption contract in R-004; no user decision reopened |
| R-004 | final reliability/security closure, Sol | GAPS/high confidence | repository owns OS-account-private state but has no authenticated active-chat/controller principal; tests cannot prove consent provenance | NEW product trust-boundary gap → D-008 open in R-005; no weakening applied |
| R-006 | post-decision final closure, Sol | GAPS/high confidence | task commit was required both to cause outside-set drift and to contain only producer-allowed paths; no distinct remediation scope owner | applied outcome-neutral T-003/T-004/T-007/T-009 and AC-04/06/07 in R-007; B-001/B-003/B-005/B-012/B-013 covered |
| R-007 | final scope/reliability closure, Sol | COVERED/high confidence | none | Ready: B-001–B-014 covered or correctly not applicable; implementation ready |

## 10. Open questions

Blocking product questions: none.

Non-blocking assumption: the concrete stuck Lazy Trader commit can satisfy parent/allowed-path ancestry proof; installation and external remediation are not performed by this repository-scoped run.

## 11. Agent activity ledger

Created logical agent runs: `16`.

| Run | Role/task | Actual model | Effort | Status/outcome | Work/mapping |
|---|---|---|---|---|---|
| A-001 | search / lifecycle-compatibility-discovery | `gpt-5.3-codex-spark` | low | completed transport; semantic `unusable-evidence` | localized runtime owners but omitted test/compatibility proof; Section 2 partially consumed, targeted root-recovery recorded |
| A-002 | critic / terminal-finalization-r001-product-ux-critic | `gpt-5.6-terra` | medium | completed / GAPS, high confidence | found missing operator authorization/attestation flow; D-007, B-002/B-011 |
| A-003 | critic / terminal-finalization-r001-architecture-critic | `gpt-5.6-terra` | medium | completed / GAPS, high confidence | found path identity, Git barrier and durable replay-order gaps; applied in R-002 T-001/T-003/T-004 |
| A-004 | critic / terminal-finalization-r003-closure-critic | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | found missing owner-enforceable current-session capability; applied in R-004 D-007/T-007/T-008 and AC-04/06/07/10 |
| A-005 | critic / terminal-finalization-r004-final-closure-critic | `gpt-5.6-sol` | high | completed / GAPS, high confidence | proved repository cannot authenticate chat provenance against another same-account process; opened D-008 in R-005 |
| A-006 | critic / terminal-finalization-r006-final-closure | `gpt-5.6-sol` | high | completed / GAPS, high confidence | found producer allowlist/task scope contradiction; applied separate remediation-scope manifest in R-007 |
| A-007 | critic / terminal-finalization-r007-final-closure | `gpt-5.6-sol` | high | completed / COVERED, high confidence | accepted all B-001–B-014 categories; no material finding; implementation Ready |
| A-008 | implementation / terminal-finalization-m1 step 1 | `gpt-5.6-terra` | medium | completed / `NEEDS_ESCALATION`, zero writes | configured trigger `task-complexity-above-tier`; semantic rejection digest `444c0153...cc743`, checkpoint invalidation completed, registry vacancy verified |
| A-009 | implementation / terminal-finalization-m1 step 2 | `gpt-5.6-terra` | xhigh | completed transport / valid result; handoff not accepted | changed only six leased runtime/test/static files; exact generated bytecode outside-set drift was terminally abandoned after root verification, then root used recorded same-scope completion authority |
| A-010 | review / terminal-finalization-r007-review-balanced | `gpt-5.6-terra` | medium | completed / `REVISE`, high confidence | found non-atomic registry/source capability consumption, missing distinct confirmed action-snapshot issuance boundary and missing durable legacy binding format; all three verified and remediated through focused RED/GREEN |
| A-011 | review / terminal-finalization-r007-review-strong | `gpt-5.6-terra` | xhigh | completed / `REVISE`, high confidence | found commit-only completed replay and the missing exact-visible-source-invalidation recovery branch; both verified and remediated through focused RED/GREEN |
| A-012 | review / terminal-finalization-r007-review-sol-high | `gpt-5.6-sol` | high | completed / `REVISE`, high confidence | found pending-intent scope bypass before release, unrotatable lost/expired authorization and source-first reader-floor fault; all three verified and remediated, but this was the terminal configured tier so the gate is route-exhausted |
| A-013 | review / terminal-finalization-r007-fresh-review-balanced | `gpt-5.6-terra` | medium | completed / `REVISE`, high confidence | reported raw capability presentation; root rejected it because D-008/T-008 intentionally make the opaque authorization handle the bearer token and keep capability material owner-private; material dispute advanced one route step |
| A-014 | review / terminal-finalization-r007-fresh-review-strong | `gpt-5.6-terra` | xhigh | completed / `REVISE`, high confidence | found post-release artifact write outside the privacy-safe error boundary and incomplete handler/barrier execution coverage; RED/GREEN moved the write under the closed boundary and added exact fault/replay plus second-barrier tests |
| A-015 | review / terminal-finalization-r007-fresh-review-sol-high | `gpt-5.6-sol` | high | completed / `REVISE`, high confidence | found copied same-name current binding acceptance and incomplete 2.2.0–2.2.2 no-rewrite matrix; both were remediated through authoritative request-path identity and parameterized behavioral coverage, but the terminal route is exhausted |
| A-016 | review / terminal-finalization-r007-fresh2-review-balanced | `gpt-5.6-terra` | medium | completed / `ACCEPT`, high confidence | independently verified the complete remediated diff, AC-01–AC-12, TDD/minimality/version parity and all recovery/privacy boundaries; no finding and no escalation trigger |

Pre-spawn dispatch failures: one review invocation included an implementation-only specification option and was rejected before run creation; the corrected command preserved the same balanced route.

## 12. Execution log

### 2026-07-18 — discovery and R-001 draft

- Root cause: 2.2.1 `run_dir` binding vs 2.2.2 `run_id` binding; post-terminal Git write created exact mixed drift rejected by ordinary v1.
- Changed: created this specification only.
- Validation: repository/test evidence mapped; readiness critics pending.
- Primary signal: not met; implementation pending.
- Version: planned patch 2.2.3; package remains 2.2.2.
- Commit/push: not created.

### 2026-07-18 — R-001 complementary critics and R-002 technical adjudication

- Product/operator critic opened D-007; no dependent operator flow or docs were changed.
- Architecture critic gaps were owner-technical and applied as exact path identity, Git snapshot barrier and intent-first four-phase replay contracts.
- Coverage: B-002/B-011 remain gap on D-007; B-006/B-007/B-013 closed by R-002 evidence-backed technical decisions.
- Primary signal: not met; implementation blocked at Questions.
- Version/commit: package unchanged; no commit.

### 2026-07-18 — R-003 D-007 application

- User selected option `1а`: current-session one-time owner-only authorization bound to exact opaque run handle and full task commit.
- Applied hidden command, canonical private attestation, exact idempotent replay and privacy-safe closed result contracts in D-007/T-007, scenarios, AC-04/06/10 and coverage.
- Coverage: B-002/B-011 are now covered; no blocking product questions remain.
- Primary signal: not met; implementation remains blocked until a fresh strong closure critic accepts R-003.

### 2026-07-18 — R-004 authorization-boundary adjudication

- Strong closure critic rejected a deterministic user-action digest because hidden local invocation could reproduce it without an issued approval.
- Applied an owner-technical two-step design: controller-staged current-session action snapshot, random short-lived owner-private capability, single issuance and atomic capability consumption with terminal intent.
- Added negative/expiry/cross-tuple/idempotent replay contracts and private-output constraints; preserved user-selected option `1а` and did not reopen a product decision.
- Primary signal: not met; implementation remains blocked until the fresh next-tier closure critic accepts R-004.

### 2026-07-18 — R-005 local-owner trust boundary

- Final Sol closure confirmed the capability state mechanics but rejected the unsupported claim that repository-local owner state authenticates an active chat response against another same-account process.
- Opened D-008 instead of silently weakening the threat model or inventing an unavailable host-signed attestation service.
- Primary signal: not met; implementation is blocked at Questions pending D-008.

### 2026-07-18 — R-006 D-008 application

- User selected `A`: the current OS account is the accepted owner principal for explicit post-commit remediation.
- Narrowed authorization claims accordingly: action snapshot/capability mechanics remain enforced, while chat-response provenance against another same-account process is explicitly outside the threat model.
- Coverage: B-002/B-005/B-007/B-012 are covered by the explicit product boundary and testable owner-state mechanics; no blocking product questions remain.
- Primary signal: not met; implementation remains blocked until a fresh final closure critic accepts R-006.

### 2026-07-18 — R-007 producer/task scope separation

- Fresh Sol closure found that a task commit could not both cause `outside-set-drift` and have every path inside the producer writer allowlist.
- Applied a separate immutable `remediation-scope-v1` manifest/digest for exact task-commit attribution: producer paths remain under the original allowlist, while explicitly authorized root-completion paths are separately bound and tested.
- Current candidate/later changes stay outside task attribution and untouched; ordinary automatic abandonment remains exact outside-only.
- Primary signal: not met; implementation remains blocked until a fresh final closure critic accepts R-007.

### 2026-07-18 — R-007 Ready closure

- Fresh Sol critic completed with `COVERED`, high confidence, no material findings and `IMPLEMENTATION_READY=yes`.
- Coverage: B-001–B-014 are covered or correctly not applicable; no product question remains.
- Status advanced to Ready; M1 TDD implementation may start under the bounded single-writer lease.

### 2026-07-18 — M1 implementation route step 1

- `openbuild_implementation_balanced` completed with valid stopped transport evidence and requested pre-edit escalation for the security/durability state-machine complexity.
- Workspace proof: no allowed file changed; only the pre-existing untracked specification remained.
- Root adjudicated configured trigger `task-complexity-above-tier`, recorded semantic rejection, completed source checkpoint invalidation and verified exact registry vacancy.
- Route advanced exactly one step to `openbuild_implementation_strong`; primary signal remains pending.

### 2026-07-18 — M1 strong implementation and root completion

- Strong writer changed only the six leased runtime/test/static files and completed with valid stopped terminal evidence.
- Independent root focused validation ran 331 tests and found one new fixture binding error; Python also created exact generated `__pycache__` outside the file allowlist while the lease was retained.
- Owner revalidation proved exact `[outside-set-drift]`; `_reconcile-terminal-abandonment` invalidated the checkpoint, closed the retained lifecycle with no handoff/new writer and left the registry vacant.
- Root same-scope TDD corrected the fixture revision and kept Git proof on an isolated in-memory source until durable intent. Targeted tests then passed, followed by 331 focused tests green with 4 platform skips under `PYTHONDONTWRITEBYTECODE=1`.
- Hardened follow-up: stable owner-private remediation manifest import, exact legacy-binding requirement and a regression guard forbidding generic reconciliation from pre-empting post-commit phases.
- Recorded root completion under original Build authority with allowed-set digest `02d4fa2f...43620` and diff-attribution digest `596cfc68...9fc7e`; M1 is complete with registry vacancy.

### 2026-07-18 — M2 version and contract synchronization

- Updated manifest, changelog, README/README.ru and SKILL/delegation/model/TDD/review/version contracts to 2.2.3 behavior.
- Documented the same-OS-account boundary, exact legacy post-commit operator flow, prohibited manual cleanup/rollback/replacement-writer actions, 2.2.0–2.2.2 compatibility and 2.2.3 downgrade implications.
- Added the active-lease `PYTHONDONTWRITEBYTECODE=1` rule so Python validation cannot manufacture unleased bytecode drift.
- Primary focused signal is green; full suite, validator, progressive review and commit remain pending.

### 2026-07-18 — balanced progressive review and remediation

- `openbuild_review_balanced` completed read-only with valid `turn.completed`, exit zero, stopped process tree and `REVISE` at high confidence.
- Root verified all three findings against T-004/T-007/T-008, added failing tests, then separated canonical confirmed action-snapshot creation from one-time capability issuance, made exact `run-dir-v1` format+digest owner evidence durable, and made the first registry intent authoritative for capability consumption across a registry/source crash window.
- Negative coverage now rejects snapshot tuple mismatch, duplicate snapshot issuance and non-legacy format. Fault injection proves reload accepts one intent with source authorization still `issued`, treats it as already consumed, repairs the source to `consumed` on exact replay and creates no second semantic event.
- Focused green: 332 tests, 4 platform skips, zero failures/errors. The concrete findings require the configured next review tier; strong review is pending.

### 2026-07-18 — strong progressive review and remediation

- `openbuild_review_strong` completed read-only with valid `turn.completed`, exit zero, stopped process tree and `REVISE` at high confidence after one non-terminal observation timeout on the same run.
- Root verified both findings: the private completed artifact was bound only to task commit, and a crash after durable source invalidation but before registry completion left the semantic phase pending without an exact replay branch.
- RED/GREEN now requires full released tuple validation before completed replay, rejects changed authorization handle/root verification/remediation scope, and recognizes only an exact `post-commit-root-completed` source invalidation with the matching authorization and candidate evidence before recording one completion event.
- Focused green after remediation: 332 tests, 4 platform skips, zero failures/errors. The configured concrete trigger requires the final `openbuild_review_sol_high` tier.

### 2026-07-18 — terminal Sol review, final remediation and route exhaustion

- `openbuild_review_sol_high` completed read-only with valid `turn.completed`, exit zero, stopped process tree and `REVISE` at high confidence after one soft observation timeout on the same run.
- Root verified all three findings and added RED/GREEN coverage: pending-intent replay now validates exact remediation scope before any invalidation/release; a different explicitly confirmed snapshot can atomically rotate an unconsumed lost/expired authorization and invalidates its old handle; identical action staging repairs a legacy registry reader floor after a source-first durability fault.
- Final focused validation: 332 tests, 4 platform skips, exit 0. Final full validation: 347 tests, 4 platform skips, exit 0. Package validation and `git diff --check` pass.
- Review route is exhausted because Sol/high is the terminal configured tier and returned no ACCEPT for the subsequently remediated diff. AC-01–AC-11 are met; AC-12, commit gate, commit and push remain intentionally incomplete. Outcome is `automation-exhausted`, not a request for unsafe force-unlock or manual review substitution.

### 2026-07-18 — fresh review cycle, post-release RED/GREEN and final route exhaustion

- User explicitly authorized a fresh high-risk review cycle. Balanced completed with a material capability-contract dispute; root preserved D-008/T-008's opaque bearer handle and owner-private raw capability boundary, then advanced exactly one step.
- Strong found that the fresh-path terminal artifact write occurred after the release but outside the closed error handler. A runner-level handler-chain RED reproduced the uncaught `RecoveryStateError`; GREEN now returns privacy-safe `blocked`, preserves the released state and lets exact replay materialize the artifact and return `terminal-root-completed`. A second Git-barrier race test proves byte-identical registry/source on rejection.
- Sol found that current `run-id-v2` accepted a copied same-name run directory and that the legacy reader-floor test covered only 2.2.1. RED/GREEN now binds terminal reconciliation to the immutable prompt/result parents recorded in `request.json`, rejects copied/malformed/ambiguous candidates, preserves normal current/legacy reload, and behaviorally loads 2.2.0, 2.2.1 and 2.2.2 without rewrite before the first 2.2.3 write.
- Current post-remediation validation: focused 333 tests and full 348 tests, each with 4 platform skips and exit 0; package validation and `git diff --check` pass.
- The Sol finding was remediated after the terminal configured review, so AC-12 and commit remain gated by `automation-exhausted`; no installation, external remediation, manual registry deletion or replacement writer was attempted.

### 2026-07-18 — final fresh review ACCEPT

- User explicitly authorized one more fresh review cycle on the fully remediated diff.
- Exact `openbuild_review_balanced` completed read-only with configured/observed `gpt-5.6-terra`/medium, `turn.completed`, exit 0, valid result and a stopped process tree.
- Verdict: `ACCEPT`, high confidence, complete AC-01–AC-12 coverage, no actionable finding and no escalation recommendation.
- Status advanced to Complete; the scoped 2.2.3 commit is authorized after final commit-gate validation. Push/publication remains unauthorized.
