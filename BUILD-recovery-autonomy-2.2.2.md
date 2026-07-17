# Build: автономное восстановление OpenBuild без бесполезных разрешений

- Status: Complete — AC-01–AC-22, full validation, fresh Sol/high acceptance review and staged commit gate passed; scoped commit/push follows this final gate.
- Last updated: 2026-07-17
- Original request: пользователь принял рекомендации по устранению остановок OpenBuild на `outside-set-drift`, retained lease и повторных разрешениях, которые не могут изменить checkpoint eligibility или registry vacancy. Нужно подготовить ТЗ для внедрения в текущий плагин и последующего выпуска исправления после 2.2.1.
- Primary signal: детерминированный end-to-end trace воспроизводит исходную цепочку failure и доказывает, что OpenBuild автоматически закрывает тот же безопасно остановленный lifecycle, не создаёт workspace prompt artifacts, не спрашивает бесполезное разрешение и продолжает только через допустимый root-only same-scope remediation либо честно блокируется на реальной authority/evidence границе.
- Review baseline: `main@256a629e401d74a81679e0567988428af0fac315`; исходное состояние чистое (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: implementation
- Specification revision: R-005
- Complexity: high — меняются durable state transitions, authorization semantics, single-writer concurrency, downgrade safety и пользовательская граница автоматизации.
- Implementation mode: TDD-first — меняется наблюдаемое поведение lifecycle/recovery и exact-schema registry.
- Version impact: patch `2.2.1` → `2.2.2` — backward-compatible исправление обещанного 2.2.1 autonomous same-scope поведения; источник версии `plugins/openbuild/.codex-plugin/plugin.json`, синхронные поверхности `CHANGELOG.md`, `README.md`, `README.ru.md`.
- Routing mode: `codex-exec-explicit-model`
- Discovery mode: delegated — exact read-only discovery завершён с валидным terminal receipt.
- Search usage route: separate-pool — packaged `openbuild_search_separate`, без fallback.
- Search routing receipt: packaged map `OpenBuild defaults`, SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, discovery/default step 1/1, exact `openbuild_search_separate`, configured/observed `gpt-5.3-codex-spark`/low/read-only, `turn.completed`, exit 0, valid result, stopped process tree.
- Implementation model route: packaged `implementation.high` — `openbuild_implementation_balanced` (`gpt-5.6-terra`/medium) → при валидном pre-edit trigger `openbuild_implementation_strong` (`gpt-5.6-terra`/xhigh) → `openbuild_implementation_sol_high` (`gpt-5.6-sol`/high), max 3; transport fallback запрещён.
- Implementation routing receipt: packaged map SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`; A-009 exact balanced/medium завершён transport-success и zero-write `NEEDS_ESCALATION: task-complexity-above-tier`; A-010 exact strong/xhigh достиг immutable 900-second deadline, был автоматически отменён с full-tree-stop, оставил только allowlisted partial diff и не создал handoff; registry освобождён, после чего T-004 standing authority зафиксировал root-only same-revision/same-scope completion.
- Review routing receipt: packaged `critic.high`, map `OpenBuild defaults`, SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`; balanced R-001 → strong R-002 → Sol/high R-003/R-004 gaps применены последовательно; fresh R-005 `openbuild_review_sol_high` (`gpt-5.6-sol`/high/read-only) завершён `COVERED`, high confidence. Implementation ladder A-011–A-017 последовательно устранил все evidence-backed findings; A-017 exact Sol/high завершён `ACCEPT`, high confidence, findings none, exact runner `turn.completed`, exit 0, valid result, stopped process tree.

## 1. Outcome

### Problem

OpenBuild 2.2.1 обещает не превращать routine same-scope lifecycle work в вопросы пользователю, но для semantic failure с изменившимся snapshot безопасная автоматическая ветка не замкнута. Snapshot включает tracked, untracked и ignored paths; созданный самим orchestrator prompt или преждевременное обновление спецификации может дать `outside-set-drift`. Неполная semantic rejection удерживает stopped lease, новый `_authorize-recovery` закономерно отказывает как occupied, а следующий вопрос пользователю не способен сделать checkpoint eligible или освободить registry.

Это безопасный `fail-closed`, но плохой recovery UX и незавершённый owner lifecycle: разрешение пользователя подменяет отсутствующий технический terminal transition.

### Desired behavior

1. Prompt, recovery prompt, run receipts и иные orchestration artifacts создаются только в owner-private location вне workspace. Runner-owned private snapshot остаётся источником фактически переданного prompt.
2. Пока implementation registry не vacant, root не изменяет ни один workspace path, включая BUILD/specification, version/changelog, ignored файлы и prompt artifacts; допускаются только read-only диагностика, user updates и owner reconciliation того же lifecycle.
3. После terminal receipt и authenticated full-tree-zero OpenBuild автоматически и идемпотентно доводит тот же lifecycle до одного допустимого исхода: accepted handoff, semantic rejection, terminal abandonment либо доказанный quarantine/blocker.
4. Если semantic success/rejection нельзя доказать из-за checkpoint/scope drift, terminal abandonment не принимает handoff, не авторизует escalation/retry/recovery writer, сохраняет privacy-safe archive, закрывает guardian и освобождает lease после всех identity/zero gates.
5. Исходный `run`, `full` или implementation-targeted `auto` запрос является standing authority для root-only завершения той же задачи после безопасного terminal release, когда diff и scope независимо атрибутируемы, root удовлетворяет risk floor, а product/architecture/permission/privacy/security/destructive/external/publication решений не возникло.
6. Если checkpoint ineligible или registry occupied, OpenBuild не просит разрешение, которое не может изменить эти факты. Он сначала reconcile тот же lifecycle; затем использует допустимый root-only branch либо сообщает `automation-exhausted`/`blocked` с недостающим evidence и без запуска writer.
7. Новый checkpoint-bound recovery target writer сохраняет текущий explicit user opt-in, eligible immutable checkpoint и exact vacancy. Настоящая ambiguity живого процесса, containment/identity, ownership/scope или user-owned решения остаётся fail-closed.

### In scope

- Owner-private prompt staging и runtime guard против workspace prompt source.
- Идемпотентный same-lifecycle reconciliation entrypoint и terminal-abandon disposition.
- Exact-schema registry/history/archive, reader-floor и downgrade-safety изменения.
- Standing authority и decision-boundary инструкции для root-only same-scope remediation.
- Запрет workspace mutation root-оркестратором при non-vacant implementation lease.
- End-to-end, fault-injection, schema, validator и forward tests.
- Manifest, changelog, English/Russian README и release validation для 2.2.2.

### Out of scope

- Автоматическая авторизация нового recovery writer.
- Принятие failed, partial, ambiguous или out-of-scope handoff как успешного.
- Освобождение lease при живом/неизвестном process tree или неподтверждённом guardian/identity evidence.
- Автоматическое разрешение product/architecture/scope/permissions/privacy/security/destructive/external/publication решений.
- Откат, удаление или перезапись посторонних/пользовательских workspace changes.
- Новый provider, production dependency, hosted service либо изменение model ladder.
- Публикация tag/GitHub Release в specification-only фазе.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Prompt ownership | `plugins/openbuild/skills/build/SKILL.md:56-60`; `plugins/openbuild/skills/build/scripts/agent_runner.py:3378-3419` | Skill требует bounded prompt file, но не требует location вне repo; runner принимает любой существующий path, затем копирует bytes в private run dir. | Orchestrator может сам создать watched workspace drift до recovery revalidation. |
| Single writer | `plugins/openbuild/skills/build/SKILL.md:101-104`; `plugins/openbuild/skills/build/references/implementation-delegation.md:118-150` | Root не должен редактировать workspace при active lease. | Правило существует, но prompt/spec timing не закреплён runtime/validator contract. |
| Snapshot scope | `plugins/openbuild/skills/build/scripts/recovery_state.py:2860-2944` | Snapshot инвентаризирует allowed paths, `git status --untracked-files=all` и ignored paths. | Workspace prompt или ignored artifact способен изменить checkpoint. |
| Drift classification | `plugins/openbuild/skills/build/scripts/recovery_state.py:3085-3136` | Любой изменившийся record вне allowed paths даёт `outside-set-drift` и `recovery-ineligible`. | Повторная авторизация не может вернуть eligibility. |
| Zero-write escalation | `plugins/openbuild/skills/build/scripts/recovery_state.py:3143-3151`; `plugins/openbuild/skills/build/references/implementation-delegation.md:52` | `NEEDS_ESCALATION` требует полного byte-equal private snapshot; drift удерживает stopped lease без semantic disposition. | Нужен отдельный non-success terminal outcome, не подделывающий zero-write. |
| Terminal owner | `plugins/openbuild/skills/build/scripts/agent_runner.py:2746-3001` | `reconcile_implementation_registry` уже идемпотентно проводит terminal evidence, zero proof, invalidation, guardian close и release, но не имеет terminal-abandon disposition. | Исправление должно расширить owner state machine, а не создавать child fallback. |
| Semantic command | `plugins/openbuild/skills/build/scripts/agent_runner.py:3029-3078` | `_reject-handoff` сначала reconciles transport state, затем пишет exact `blocked|needs-escalation`; failure остаётся fail-closed. | Нужен replay-safe путь для semantic outcome, который нельзя доказать. |
| Recovery authorization | `plugins/openbuild/skills/build/scripts/agent_runner.py:3084-3150`; `plugins/openbuild/skills/build/scripts/recovery_state.py:3170-3188` | Existing mismatched lease даёт occupied; grant требует eligible candidate checkpoint. | User opt-in не должен изображаться лекарством от occupied/ineligible state. |
| Reservation | `plugins/openbuild/skills/build/scripts/recovery_state.py:3237-3302` | Grant consumption требует exact vacancy и повторной checkpoint binding проверки. | Эти safety gates сохраняются. |
| Pre-boundary cleanup | `plugins/openbuild/skills/build/scripts/recovery_state.py:3316-3344` | Recovery target уже может безопасно освободить pre-boundary lease при `tree_empty` и `no_user_code`. | Новый transition должен переиспользовать доказательный стиль, а не общий force-unlock. |
| Contained release | `plugins/openbuild/skills/build/scripts/recovery_state.py:3911-3989` | Release требует terminal state, zero proof, guardian close и валидируемый privacy-safe archive. | Terminal abandonment обязан пройти те же gates. |
| Authority conflict | `plugins/openbuild/skills/build/references/implementation-delegation.md:34-52,190` | Routine root completion не должен спрашивать пользователя, но repair вне узкой safe branch запрещён и new writer требует authority. | Требуется точное расширение automatic root-only branch, не blanket permission. |
| Existing tests | `scripts/test_agent_runner.py:1790-1977`; `scripts/test_recovery_state.py:855-895` | Semantic rejection и outside drift тестируются раздельно. | Нет интеграционного trace исходной пользовательской цепочки. |
| Static contract | `scripts/validate_package.py:3135-3190,4200-4466` | Validator фиксирует старый root-repair запрет и текущих recovery owners/tokens. | Он должен запрещать регресс к бесполезным prompts и force-unlock. |
| Released promise | `CHANGELOG.md:11-18`; `README.ru.md:79-89`; `README.md:79-89` | 2.2.1 заявляет bounded automatic retry/root completion и отсутствие routine operational questions. | Изменение исправляет уже заявленное поведение. |
| Version policy | `plugins/openbuild/.codex-plugin/plugin.json:1-4`; `CONTRIBUTING.md:14-31` | Manifest authoritative; backward-compatible fix — patch; каждый commit синхронизирует manifest/changelog/READMEs. | Целевая версия 2.2.2. |

### Source of truth

`RecoveryRegistry` и `reconcile_implementation_registry` владеют durable lifecycle. `SKILL.md` и `implementation-delegation.md` владеют orchestration/authority contract. Новый механизм не должен жить только в prompt prose или downstream try/catch.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD-recovery-autonomy-2.2.2.md` | user + repository root spec | R-005 Ready | D-001–D-004, T-001–T-009, AC-01–AC-22 | Все строки ниже; discovery/critic receipts и evidence table | yes | root |
| `BUILD-auto-continuation-2.2.1.md` | accepted historical Build spec | Complete R-023 | routine questions, same-scope retry/root completion | `:23-41`; связанные runtime/instruction owners mapped ниже | no | aligned; расширяется без переписывания истории |
| `BUILD-route-recovery-safety.md` | accepted historical Build spec | Complete R-029 | opt-in recovery, stopped-tree/single-writer gates | `:23-44`; runtime owners mapped ниже | no | aligned; explicit new-writer opt-in сохраняется |
| `plugins/openbuild/skills/build/SKILL.md` | packaged workflow contract | 2.2.1 | D-001–D-004 orchestration boundary | `references/implementation-delegation.md`, `model-routing.md`, `tdd-workflow.md`, `minimality-protocol.md`, `review-protocol.md`, `versioning.md`; direct audit | yes | gap: prompt location и terminal abandon отсутствуют |
| `plugins/openbuild/skills/build/references/implementation-delegation.md` | implementation authority owner | 2.2.1 | D-001–D-003, single-writer/root handoff | links to model routing; direct audit `:1-192` | yes | gap: automatic branch не замкнут |
| `plugins/openbuild/skills/build/references/model-routing.md` | exact-route owner | 2.2.1 | D-002/D-003, route failure boundary | links to implementation delegation/review; direct audit `:1-269` | yes | aligned; transport escalation ban preserved |
| `plugins/openbuild/skills/build/references/tdd-workflow.md` | behavioral implementation protocol | 2.2.1 | red/green and owner-layer remediation | implementation delegation + minimality; direct audit `:1-65` | yes | gap: terminal-abandon fixture not named |
| `plugins/openbuild/skills/build/references/minimality-protocol.md` | minimal mechanism policy | 2.2.1 | T-001–T-009 | no additional in-scope normative edge; direct audit `:1-56` | yes | aligned |
| `plugins/openbuild/skills/build/references/review-protocol.md` | final diff review owner | 2.2.1 | high-risk acceptance/review | TDD/minimality/versioning links mapped here; direct audit `:1-183` | yes | aligned |
| `plugins/openbuild/skills/build/references/versioning.md` | version contract | 2.2.1 | T-006 | CONTRIBUTING/manifest evidence; direct audit `:1-72` | yes | aligned |
| `CONTRIBUTING.md` | repository release policy | current main | validation and patch release policy | `CHANGELOG.md`, manifest, READMEs at `:14-69` | yes | aligned |
| `README.md`, `README.ru.md`, `CHANGELOG.md` | public behavior/release record | 2.2.1 | D-001–D-003 public promise | manifest/release rules mapped above | yes | gap until 2.2.2 implementation |

Every in-scope normative edge is mapped above. Unrelated specification-interview/model-configuration references from `SKILL.md` are outside this lifecycle fix and do not own D-001–D-004.

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| 2.2.0 explicit recovery writer vs requested autonomy | scopes differ: new writer remains opt-in; existing root-only task completion becomes standing authority | D-001 + D-002, current user answer “принимаю твои рекомендации” | aligned |
| fail-closed retained lease vs automatic continuation | terminal abandonment releases only after existing zero/identity/guardian gates and accepts no handoff | D-001 + D-003; T-002 | aligned |
| prompt file CLI compatibility vs no workspace artifacts | preserve external `--prompt-file`; reject in-workspace source before lease/process and document migration | D-004; T-001 | aligned |

### Gap

Нет durable outcome для stopped contained lease, когда semantic disposition/checkpoint нельзя доказать, но process/identity/zero evidence достаточно, чтобы безопасно закрыть producer без handoff. Одновременно orchestration contract не гарантирует external prompt location и не даёт root точной standing-authority ветки после такого release.

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | `automation.failure.root-remediation` | user | resolved | Что делать после безопасно остановленного failed/ambiguous handoff в прежнем scope? | Исходный `run/full/implementation-auto` даёт bounded standing authority на root-only same-scope remediation без operational prompt. | Текущий ответ пользователя: “принимаю твои рекомендации”. | Убирает второй бесполезный вопрос, не разрешая replacement writer. |
| D-002 | `authorization.recovery-writer` | user | resolved | Нужно ли автоматически запускать новый recovery writer? | Нет; сохранить exact eligible checkpoint + explicit one-shot user opt-in. | Принятые рекомендации и существующий 2.2.0 safety contract. | Автономность достигается reconciliation/root-only, а не скрытым writer fallback. |
| D-003 | `automation.fail-closed-boundary` | user | resolved | Какие случаи остаются user-owned/fail-closed? | Product/architecture/scope/permissions/privacy/security/destructive/external/publication решения и неизвестное process/containment/ownership evidence. | Принятые рекомендации. | Blanket force-recovery запрещён. |
| D-004 | `workspace.orchestration-artifacts` | user | resolved | Где хранить prompt/run/recovery artifacts? | Только owner-private location вне workspace. | Принятые рекомендации. | OpenBuild не инвалидирует checkpoint собственным prompt-файлом и не засоряет diff. |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Единый owner helper stable-acquire применяется и к обычному `start`/`dispatch`, и к `_authorize-recovery` до private run dir, registry initialization/grant/reservation и process spawn: он открывает `prompt_source` один раз как стабильный read-only object, получает canonical final path/file identity из открытого object, доказывает нахождение вне workspace, читает bytes из того же object и повторно сверяет identity/metadata. Recovery authorization после proof сохраняет bytes как immutable current-user-only content-addressed owner snapshot и binding в target plan; recovery `start` читает snapshot, а не повторно открывает caller path. Symlink/junction/reparse/path/content swap либо отсутствие platform proof дают actionable fail-closed. Existing external `--prompt-file` сохраняется как authorization input. | selected | `agent_runner.py:3083-3148` и `:3378-3419` имеют два resolve/read flow; recovery plan сейчас хранит только SHA и start повторно читает named source. Одной prose-инструкции недостаточно. | D-004; фактически проверенные bytes становятся private snapshot, model/sandbox/task content не меняются; raw bytes не попадают в public registry/archive. |
| T-002 | Добавить exact semantic terminal disposition `abandoned` только с cause `outside-set-drift` в schema `terminal-abandonment-v1` и idempotent private reconciliation entrypoint для того же run. Durable disposition содержит exact run/lease/source/checkpoint/allowed-set/terminal-receipt/zero-proof/candidate-snapshot bindings; `evidence_digest` вычисляет owner из canonical record, а не принимает от caller. | selected | Это единственный подтверждённый screenshot/repository gap; более широкий cause enum оставил бы произвольную semantic terminalization. Текущие `blocked|needs-escalation` не описывают этот исход; force unlock отвергнут. | D-001/D-003; handoff/outbox/escalation/retry остаются запрещены, unknown reason fail-closed. |
| T-003 | `abandoned` разрешён только для exact current stopped-terminal lease с transport-success terminal receipt, authenticated full-tree zero, совпавшими run/lease/source/provider/process identities, отсутствующим accepted outbox и повторной checkpoint revalidation, чей exact closed reason set равен `[outside-set-drift]`; owner replay-safe привязывает permanent checkpoint invalidation, canonical evidence и terminal failure, затем guardian close → validated archive → release. | selected | Переиспользует `acknowledge_guardian_close`/`release_contained_terminal`; любые дополнительные причины (`git-control-plane-drift`, `preexisting-dirty-overlap`, unknown) не abandon-ятся автоматически. | Все containment/privacy invariants сохраняются; replay сравнивает тот же canonical record/digest. |
| T-004 | Root-only remediation eligibility вычисляется отдельно после vacancy: original task authority + same revision/milestone/scope + attributable diff + risk-capable root + отсутствие D-003 boundary. | selected | Не смешивать terminal release с permission to edit. | D-001–D-003; чужие changes не становятся task diff. |
| T-005 | Новые registry/history/archive варианты проходят exact allowlist validation; запись нового формата поднимает reader floor до 2.2.2. Upgrade читает 2.2.0/2.2.1 state без rewrite-on-read и может детерминированно продолжить legacy `stopped-terminal` lifecycle через новый owner transition; первый новый write атомарно повышает floor. | selected | Exact schema и downgrade floor уже являются owner contract; нужен отдельный interrupted-2.2.1 forward fixture. | Не допускает unsafe old-reader interpretation или скрытую destructive migration. |
| T-006 | Выпуск как patch 2.2.2 без production dependencies и без public model-map change. | selected | `CONTRIBUTING.md:14-31`, обещание 2.2.1 в changelog/README. | Публичная совместимость и D-001–D-004 сохраняются. |
| T-007 | Нормализованный user-facing outcome `decision-required` используется только для D-003 material user-owned choices и содержит closed privacy-safe `decision_class` (`product`, `architecture`, `scope`, `permissions`, `privacy`, `security`, `destructive`, `external-action`, `publication`) плюс `required_action=provide-decision`; evidence/process/containment/ownership ambiguity остаётся `blocked`, а отсутствие способного безопасного исполнителя — `automation-exhausted`. | selected | Product/UX critic подтвердил, что эти три исхода должны быть машинно и операторски различимы. | Не превращает технический blocker в запрос магической permission-фразы и не расширяет authority. |
| T-008 | `prompt_snapshot_id` и `prompt_sha256` входят в exact private authorization intent до durable grant commit, участвуют в immutable existing-grant replay comparison и затем exact-match проверяются/копируются в consumed-grant record, target plan и recovery lease. Snapshot создаётся до grant; grant и reservation остаются существующими отдельными transitions, но crash replay не может сменить prompt. | selected | `recovery_state.py:428-457,3170-3335` сейчас не связывает private grant с prompt, поэтому blob → grant → reservation нужны как три fault boundaries. | D-002: user action authorizes exact checkpoint + exact prompt; не делает grant многоразовым и не раскрывает snapshot ID публично. |
| T-009 | Runner предоставляет owner-private staging API для bounded UTF-8 prompt bytes и использует staged snapshot как preferred orchestration input. Оно создаёт regular file/blob с POSIX `st_uid==euid` и mode `0600` в `0700` owner dir либо Windows current-user-owned protected DACL без broad/inherited ACE; compatibility `--prompt-file` проходит те же ownership/mode/DACL + stable-object checks и импортируется в snapshot. Exact retention states: `orphan-unreferenced`, `grant-referenced`, `lease-referenced`, `released`; owner GC удаляет только доказанно unreferenced/released blobs под lock, исключает runner run directories из sweep и не меняет retention фактического private run `prompt.md`. | selected | Stable containment без access-control proof допускает world-readable prompt; неопределённый GC ломает replay либо удерживает дубликаты бесконечно. | D-004/privacy invariant; raw bytes/path не входят в public grant/checkpoint/history/archive/report. |

### Pending proposals

- None. Все product-impacting решения для текущего scope подтверждены пользователем.

## 4. User scenarios

### Primary scenario

1. Implementation worker terminalizes, а semantic acceptance/rejection не может завершиться из-за drift.
2. OpenBuild не создаёт recovery prompt в workspace и не спрашивает пользователя о routine remediation.
3. Он повторно загружает exact registry, подтверждает stopped tree/identity, записывает `abandoned`, закрывает guardian, архивирует и освобождает lease.
4. После vacancy root независимо классифицирует diff. Если T-004 выполнен, root завершает исходный scope, запускает validation/review и продолжает workflow; иначе сообщает точный blocker без нового writer.

### Errors and edge cases

- In-workspace prompt source до dispatch → pre-spawn failure с actionable external-location error; registry/process/workspace не изменены.
- `outside-set-drift` после terminal stop → checkpoint остаётся ineligible; permission question не создаётся; same lifecycle reconciles.
- Existing lease в `_authorize-recovery` → no new prompt/write; сначала owner reconciliation current run.
- Crash после записи `abandoned`, до guardian close/archive/release → повтор той же reconciliation завершает переход без второго history event.
- Crash после archive, до CLI receipt → reload возвращает тот же terminal outcome и vacancy, не создаёт writer.
- Live/unknown tree, guardian identity loss, containment quarantine → no abandon/release/root edit; factual blocker.
- User-owned or unattributable outside changes → terminal producer можно закрыть после доказательств, но root remediation не начинается и changes не откатываются.
- Valid zero-write `NEEDS_ESCALATION` без drift → прежняя one-rung automatic escalation сохраняется; `abandoned` её не подменяет.
- Eligible checkpoint + explicit user opt-in → прежний recovery target path сохраняется.
- Old 2.2.1 registry → upgrade/load green; registry с новым 2.2.2 event → downgrade fail-closed по reader floor.

## 5. Requirements and acceptance criteria

- [x] AC-01: Ни один prompt-consuming OpenBuild route, включая normal `start`/`dispatch` и `_authorize-recovery`, не использует source внутри workspace; stable-object containment/read завершается до private run dir, registry initialization/grant/reservation и process, а in-workspace/identity-unstable/unprovable source даёт actionable privacy-safe failure без этих side effects.
- [x] AC-02: Private run snapshot содержит UTF-8 bytes/digest, прочитанные из того же identity/privacy-verified file object; POSIX symlink/owner/mode/content swap, Windows junction/reparse/owner/DACL/content swap и concurrent path replacement не могут подменить проверенный source, а public receipts не раскрывают snapshot ID/private paths/raw bytes.
- [x] AC-03: При non-vacant implementation lease orchestration contract и validator запрещают root workspace writes, включая spec/version/changelog/prompt artifacts, до owner terminal release.
- [x] AC-04: Private reconcile command принимает exact run, является replay-safe и продолжает только допустимый переход текущего lease; он не создаёт новый run/writer/grant.
- [x] AC-05: `abandoned` может быть записан только после stopped-terminal transport success, authenticated full-tree zero, exact identity bindings, no accepted outbox и owner-derived `terminal-abandonment-v1` evidence для exact reason set `[outside-set-drift]`; caller-supplied cause/digest и любой иной/mixed reason отклоняются без mutation.
- [x] AC-06: `abandoned` меняет terminal success на false, двухфазно и replay-safe делает source checkpoint permanently recovery-ineligible, создаёт no handoff, no retry/escalation/recovery authority и сохраняет validated privacy-safe terminal archive.
- [x] AC-07: Guardian close и lease release после abandonment используют существующие owner gates; live/unknown/quarantined producer никогда не освобождается автоматически.
- [x] AC-08: `outside-set-drift`, `recovery-ineligible` и occupied registry не порождают operational permission prompt; авторизация не изображается средством исправления evidence.
- [x] AC-09: После vacancy root-only same-scope remediation запускается без нового вопроса только при T-004 eligibility; audit log фиксирует authority, scope/diff attribution и automatic action.
- [x] AC-10: Новый recovery writer по-прежнему требует explicit user opt-in, eligible immutable checkpoint, exact allowed-set/spec revision и vacancy.
- [x] AC-11: Product/architecture/scope/permissions/privacy/security/destructive/external/publication выбор возвращает `decision-required` с closed T-007 class/action; process/containment/ownership ambiguity остаётся `blocked`, а capability exhaustion — `automation-exhausted`; ни один из исходов не запускает writer и не просит бесполезную permission-фразу.
- [x] AC-12: End-to-end fixture воспроизводит `NEEDS_ESCALATION/semantic failure → orchestrator-like outside artifact drift → retained lease → attempted recovery` и доказывает autonomous same-lifecycle abandon/release без user prompt или writer.
- [x] AC-13: Fault-injection tests покрывают crash/reload на каждой durable boundary нового перехода, duplicate/replay, mismatched digest/run/lease/source/checkpoint/terminal/zero/candidate binding, caller-supplied или incorrect/mixed cause, prompt TOCTOU swaps, artifact-write failure и guardian-close failure.
- [x] AC-14: Schema/mutation tests отклоняют unknown/missing disposition/schema/cause/history/archive/evidence fields, неверный digest producer/binding, unsafe downgrade и force-unlock path; existing 2.2.0/2.2.1 fixtures остаются green.
- [x] AC-15: `SKILL.md`, implementation/model/TDD/review/version contracts, validator, CHANGELOG и обе README согласованно описывают один и тот же decision boundary.
- [x] AC-16: Manifest и user-facing pins синхронно переходят `2.2.1` → `2.2.2`; full contributor suite, package validator, commit gate, platform fixtures и fresh high-risk review проходят.
- [x] AC-17: Forward fixture загружает persisted interrupted 2.2.1 `stopped-terminal` lifecycle без rewrite-on-read, выполняет один digest-bound 2.2.2 abandon/invalidate/archive/release chain, повышает reader floor только первым новым write и при повторном reload возвращает идентичный result без второго history/archive event.
- [x] AC-18: Outcome fixtures доказывают, что material user choice → `decision-required`, missing/ambiguous safety evidence → `blocked`, exhausted safe executor/route → `automation-exhausted`, а routine outside drift при всех v1 gates → autonomous `terminal-abandoned`; каждый report содержит только соответствующее privacy-safe действие.
- [x] AC-19: `_authorize-recovery` POSIX/Windows fixtures покрывают in-workspace source, symlink/junction/reparse и path/content swap, доказывая отсутствие registry generation/grant/lease/run-dir/process mutation. Успешный flow создаёт один immutable `prompt_snapshot_id`/digest-bound target plan; replay не дублирует state, recovery `start` использует exact snapshot без повторного caller-path read, а missing/mismatched/orphan snapshot обрабатывается по owner fail-closed/GC contract.
- [x] AC-20: Exact-schema/fault fixtures доказывают, что private authorization intent до grant commit содержит `prompt_snapshot_id`/`prompt_sha256`; existing-grant replay, consumed-grant record, target plan и lease cross-validate оба поля. Crash/reload после blob write, grant commit и reservation commit сохраняет тот же prompt binding; другой prompt не reuse-ит grant и не мутирует state.
- [x] AC-21: Runner-owned staging создаёт bounded UTF-8 snapshot с POSIX owner/mode `0600`+`0700` boundary либо Windows current-user protected DACL. Compatibility file с чужим owner, group/other bits или broad/inherited DACL отклоняется до blob/registry/run side effects; platform mutation fixtures и package validator требуют один shared privacy contract для normal/recovery paths.
- [x] AC-22: Retention fixtures покрывают `orphan-unreferenced`, `grant-referenced`, `lease-referenced`, `released`, explicit `authorization-retired`, terminal release и legacy retirement. GC под lock никогда не удаляет referenced blob, исключает runner run directories, idempotently удаляет только eligible duplicate snapshot, не затрагивает фактический run `prompt.md`, а `prompt.md` bytes + `request.json` prompt digest и authority/terminal result совпадают при reload до/после GC.

### Invariants

- Один active writer; root не пишет при active lease.
- Никогда не принимать ambiguous/failed handoff и не подделывать zero-write proof.
- Никогда не запускать replacement/escalation из transport/infrastructure/containment failure.
- Никакого force-unlock: каждый release имеет terminal, zero, guardian и identity evidence.
- No raw private paths/nonces/prompt/logs в public checkpoint, archive или user report.
- Сохранять unrelated/user changes без rollback, staging или включения в task diff.
- Git, version, commit и publication остаются root-owned.

## 6. Technical boundaries

### Affected layers and contracts

- `agent_runner.py` — shared stable prompt acquisition for normal dispatch and `_authorize-recovery`, private recovery prompt snapshot binding, reconciliation CLI, orchestration of abandonment/close/release.
- `recovery_state.py` — exact disposition/history/archive schemas, transition owner, reader floor и idempotent reload.
- `SKILL.md` + references — no-workspace-artifact, no-root-write-during-lease, standing root-only remediation и no-useless-question contract.
- `scripts/test_agent_runner.py`, `scripts/test_recovery_state.py` — red/green integration, state and fault tests.
- `scripts/validate_package.py`, `scripts/test_validate_package.py` — static/mutation guards and instruction parity.
- `README.md`, `README.ru.md`, `CHANGELOG.md`, manifest — public behavior/version.

### Exact `terminal-abandonment-v1` contract

- Owner transition принимает только `run_dir`/current registry identity и не принимает от caller `cause`, `evidence_digest`, lease/source/checkpoint digests или флаг force. Он повторно читает private request/terminal receipt и current registry/source под существующим owner lock/rebarrier.
- Единственный автоматический v1 cause — `outside-set-drift`, причём повторная revalidation должна вернуть exact reason set `[outside-set-drift]`. Любая дополнительная или unknown причина, отсутствие candidate snapshot либо binding mismatch возвращает `blocked` и не меняет lease/source.
- Exact `semantic_disposition` shape для нового варианта: `disposition="abandoned"`, `schema="terminal-abandonment-v1"`, `cause="outside-set-drift"`, `evidence_digest`, `checkpoint_allowed=false`, `checkpoint_invalidation="pending"|"completed"`, `run_id`, `lease_id`, `source_state_id`, `source_checkpoint_digest`, optional only-when-completed `checkpoint_digest`, `allowed_set_digest`, `terminal_binding_digest`, `zero_proof_digest`, `candidate_snapshot_digest`. Unknown/missing fields и иные значения отклоняются.
- Owner вычисляет `evidence_digest` domain-separated canonical hash из `schema`, `cause`, exact run/lease/source identity, исходного public checkpoint digest, allowed-set digest, terminal receipt binding digest, canonical full-tree-zero proof digest и privacy-safe candidate public snapshot digest. Digest не включает сам себя и post-invalidation `checkpoint_digest`; связь с последним устанавливается отдельным completed phase.
- Переход двухфазный и idempotent: registry записывает `pending` disposition и terminal failure → source checkpoint получает permanent reason `terminal-abandoned-outside-set-drift` с тем же evidence digest → registry записывает `completed` и exact invalidated `checkpoint_digest` → guardian close → validated archive/release. Reload после любой границы либо завершает тот же digest-bound transition, либо fail-closed; второго event/archive/release не создаёт.
- History/archive allowlists получают только exact `terminal-abandonment-recorded`/completed binding и существующий privacy-safe semantic disposition digest. Accepted handoff/outbox, retry, escalation grant и recovery authorization при любом phase запрещены.

### Stable external prompt acquisition contract

- Один helper/contract обслуживает normal `start`/`dispatch` и private `_authorize-recovery`; отдельный менее строгий recovery reader запрещён. Documented orchestration создаёт prompt через runner-owned private staging API, принимающий bounded UTF-8 bytes без command-line interpolation и возвращающий opaque private snapshot reference; compatibility `--prompt-file` сохраняется как import input.
- Containment проверяется по final canonical path открытого file object, а bytes читаются из того же object; предварительный `Path.resolve()` или строковый prefix сами по себе proof не являются.
- Runner фиксирует platform file identity и metadata до/после read, использует доступный no-follow/reparse-safe/deny-write механизм и отклоняет link/junction/reparse/path/content swap. Если платформа не может доказать identity и стабильность объекта, preflight завершается fail-closed.
- До импорта compatibility file helper доказывает current-user privacy того же открытого object: POSIX regular file с `st_uid == geteuid()` и отсутствием group/other permission bits (`mode & 0o077 == 0`) внутри owner-controlled staging boundary; Windows regular non-reparse file с owner=current user SID и protected DACL, разрешающим доступ только current user/SYSTEM/Administrators без inherited/broad ACE. Непроверяемый owner/ACL/mode отклоняется.
- Workspace boundary сравнивается component-aware с Windows case/reparse и POSIX symlink semantics. Containment, privacy proof и read завершаются до private run-dir creation, registry initialization/grant/reservation и process spawn; invalid input не повышает registry/source generation и не оставляет blob/grant/lease/run dir.
- Exact bytes атомарно сохраняются вне workspace в immutable current-user-only content-addressed owner snapshot. Snapshot имеет opaque keyed `prompt_snapshot_id` и отдельный `prompt_sha256`; raw bytes/path не входят в CLI args, public receipt или public state. Normal/recovery start загружает snapshot по ID, повторно проверяет digest/UTF-8 и не открывает caller path для task content.
- `_authorize-recovery` передаёт snapshot bindings в `grant_authorization`; exact private authorization, consumed-grant record, target plan и recovery lease обязаны содержать один и тот же `prompt_snapshot_id`/`prompt_sha256`. Existing-grant replay сравнивает их до возврата grant; mismatch не мутирует state. Snapshot write, grant commit и reservation commit — отдельные fault-injection boundaries.
- Ошибка сообщает privacy-safe класс (`prompt-inside-workspace`, `prompt-identity-unstable`, `prompt-containment-unprovable`, `prompt-owner-untrusted`, `prompt-permissions-too-broad`) и действие «использовать owner-private staging API», но не раскрывает private absolute path.

### Prompt snapshot authorization and retention state machine

- `orphan-unreferenced`: snapshot durable, но ни private authorization, ни run/lease его не reference-ят (включая crash после blob write или failed authorization до grant). Он не даёт authority; owner GC может удалить его только после locked/rebarrier scan всех private source authorizations, consumed grants, leases и live run bindings.
- `grant-referenced`: private authorization intent exact-bind-ит snapshot ID/SHA вместе с user-action/checkpoint/spec/milestone. Blob сохраняется через reload и не GC-ится между durable grant и reservation. Если grant становится non-consumable из-за checkpoint invalidation/stale epoch, отдельный exact `authorization-retired` owner transition при vacant registry убирает reference; до этого fail-closed retention предпочтительнее удаления.
- `lease-referenced`: consumed-grant record, target plan и current recovery lease cross-bind-ят тот же snapshot. Blob сохраняется до durable run `prompt.md`/`request.json` prompt-digest binding и затем как минимум до validated terminal archive + lease release; missing/mismatched blob блокирует start/replay без process spawn или displacement.
- `released`: после validated terminal archive/release owner записывает private idempotent release/tombstone binding; authorization blob становится GC-eligible. GC sweep не входит в runner run directories и удаляет только duplicate owner blob. Existing private run-dir `prompt.md` и его текущая retention/cleanup policy не меняются 2.2.2 и не удаляются новым blob GC.
- Normal dispatch snapshot становится `released`, когда private run `prompt.md` bytes и `request.json` prompt digest durability взаимно подтверждены до spawn. Replayed staging/import с теми же bytes использует один content-addressed blob; GC/reload не создают второй authority-bearing record.
- Legacy target plan без snapshot bindings не получает synthetic blob и не запускается: он остаётся fail-closed до существующего safe retirement/manual re-authorization path. Legacy retirement и failed authorization без durable grant не удерживают raw bytes после orphan GC.

### Data and migration

- Existing owner-private 2.2.0/2.2.1 registry/source generations загружаются без rewrite-on-read.
- Новый disposition/history/archive shape записывается только новым owner transition и требует reader floor 2.2.2.
- Private authorization, consumed-grant record, recovery target plan и lease 2.2.2 добавляют exact `prompt_snapshot_id`/`prompt_sha256` cross-binding; raw prompt bytes живут только в owner snapshot/run artifact и не сериализуются в public grant/checkpoint/history/archive. Legacy reserved recovery target без binding не запускается автоматически и остаётся fail-closed с migration diagnostic; legacy stopped source lifecycle для AC-17 не требует такого target plan.
- Persisted 2.2.1 `stopped-terminal` lease без нового disposition является допустимым input для того же v1 transition: 2.2.2 сначала валидирует старый exact shape, затем при подтверждённом `[outside-set-drift]` выполняет один новый write-chain, повышает reader floor и выдаёт тот же terminal result при повторном reload.
- Downgrade не удаляет state и не пытается его интерпретировать; fail-closed retirement разрешён только по существующему explicit-vacant contract.
- Миграция workspace data и backfill не нужны.

### Security and privacy

- Prompt source/import и private artifacts обязаны пройти T-009 POSIX ownership/mode либо Windows owner/protected-DACL proof; runner-owned staging создаёт эти permissions сам. Public receipts содержат только digest/classification и не содержат snapshot ID/path/raw bytes.
- Abandonment не ослабляет containment, identity, zero-proof или archive validation.
- Cause enum не содержит raw path; private owner может использовать paths для attribution, public report — только privacy-safe IDs/categories.

### Performance and concurrency

- Один registry lock и bounded idempotent reconciliation; polling/fan-out не добавляются.
- Prompt path containment проверяется component-aware canonical resolution с учётом Windows case/reparse и POSIX symlink semantics; не полагаться только на строковый prefix.
- Reconciliation не удерживает lock во время долгого process wait; durable compare-and-transition выполняется под owner lock.

### Observability and errors

- Нормализованные outcomes: `reconciled`, `terminal-abandoned`, `root-completion-authorized`, `decision-required`, `automation-exhausted`, `blocked`.
- `decision-required` содержит только T-007 `decision_class` и `required_action`; `blocked` содержит недостающее evidence/safety condition, `automation-exhausted` — исчерпанные безопасные executor/route capabilities. Эти outcomes не взаимозаменяемы.
- User report объясняет, какое evidence позволило/запретило continuation, но не предлагает permission, неспособное изменить evidence.
- Agent ledger и execution log фиксируют automatic action, не private paths/PIDs/tokens.

### Versioning and release

- Version source: `plugins/openbuild/.codex-plugin/plugin.json`.
- Target: 2.2.2 patch при неизменном scope; material public API/compatibility expansion требует пересмотра impact до commit.
- Same-commit sync: manifest, `CHANGELOG.md`, `README.md`, `README.ru.md` и все изменённые package contracts/tests.
- Tag/GitHub Release/publication выполняются только в будущей implementation/release фазе с применимой authority; опубликованные tags не перемещаются.

## 7. Validation and review

- Primary signal: AC-12 end-to-end trace плюс AC-13 durable fault matrix, AC-17 legacy forward replay, AC-18 outcome separation и AC-19–AC-22 recovery prompt containment/grant/privacy/retention matrix.
- Red signal: новая integration fixture на текущем 2.2.1 удерживает lease/отказывает recovery либо требует manual authority после outside drift.
- Minimality decision: custom owner-layer — расширить существующие `RecoveryRegistry`/`reconcile_implementation_registry`; новый параллельный recovery service, dependency или generic force-unlock не нужен.
- Focused green: `python -m unittest scripts.test_recovery_state scripts.test_agent_runner scripts.test_validate_package -v`.
- Targeted checks: stable-object containment/TOCTOU/owner/mode/DACL fixtures Windows/POSIX для normal и `_authorize-recovery`; blob→grant→reservation crash/replay cross-bindings; retention/retirement/GC states; exact abandonment schema/digest mutations; legacy 2.2.1 forward replay; decision/blocker/exhaustion outcomes; exact no-prompt forward fixture.
- Wider checks: `python -m unittest discover -s scripts -p "test_*.py" -v`; `python scripts/validate_package.py`; `git diff --check`.
- Commit gate: staged task diff → `git diff --cached --check`; `python scripts/validate_package.py --commit-gate`.
- Manual/runtime check: fresh installed 2.2.2 plugin executes a realistic stopped semantic-drift scenario and records no workspace prompt artifact/no operational question.
- Starting review tier: balanced (`openbuild_review_balanced`, Terra/medium) for high risk.
- Required final tier: R-001 balanced и R-002 strong findings escalated до Sol/high; R-003/R-004 Sol/high дали configured gaps. После factual change R-005 требуется fresh closure на той же максимальной `openbuild_review_sol_high` tuple; дальнейшего tier/fallback нет.
- Review focus: state-machine completeness, crash consistency, concurrency, authorization boundary, downgrade/privacy, platform path containment, regression to useless prompts.

## 8. Milestones

### M1. Reproduce and lock the failed lifecycle

- Status: Complete
- Scope: integration red fixtures matching AC-12/AC-17–AC-22; normal/recovery prompt stable-object/privacy/location/snapshot, grant crash binding, retention/GC и no-root-write contract mutations.
- Excludes: production behavior change.
- Implementation mode: TDD-first
- Delegation: bounded-worker — A-009 balanced/medium доказанно отказался до edits с configured `task-complexity-above-tier`; source checkpoint invalidated и lease released, A-010 exact `openbuild_implementation_strong`/xhigh одобрен для того же M1–M3 allowlist; no spec/version/Git.
- Red signal: current 2.2.1 cannot reach archived vacant terminal outcome without misleading recovery/manual authority in the drift sequence.
- Minimality decision: reuse existing RecoveryRegistry/runner fixtures.
- Focused green: end-to-end retained-lease trace, legacy-forward, exact-schema, prompt privacy/binding/retention и durable-boundary fixtures проходят в полном suite.
- Acceptance: AC-01–AC-03, AC-08, AC-11–AC-14, AC-17–AC-22.

### M2. Own prompt isolation and terminal reconciliation

- Status: Complete
- Scope: T-001–T-005/T-007–T-009 in `agent_runner.py`/`recovery_state.py` plus focused state/fault tests.
- Excludes: docs/version and model map.
- Implementation mode: TDD-first
- Delegation: bounded-worker A-010 left an allowlisted stopped partial diff; root completed the same R-005/M1–M3 scope under recorded T-004 authority after vacancy.
- Red signal: M1 plus per-boundary fault cases.
- Minimality decision: custom owner-layer extension; no dependency/service/general repair API.
- Focused green: focused runner/recovery/validator unit suites.
- Acceptance: AC-01–AC-14, AC-17–AC-22.

### M3. Align workflow authority and static contracts

- Status: Complete
- Scope: `SKILL.md`, implementation/model/TDD/review references, package validator и mutation tests.
- Excludes: runtime rewrites outside confirmed findings.
- Implementation mode: TDD-first for validator behavior; Direct for synchronized prose after green.
- Delegation: root-only after A-010 terminal release; no overlapping writer.
- Red signal: validator принимает старый contradictory contract либо не требует no-useless-question/abandonment gates.
- Minimality decision: extend existing static owner, not duplicate prompts in every profile.
- Focused green: `scripts.test_validate_package` плюс package validator.
- Acceptance: AC-03, AC-08–AC-11, AC-14, AC-15, AC-18.

### M4. Version, docs, full validation and release review

- Status: Complete
- Scope: manifest 2.2.2, changelog, README parity, full suite, installed forward smoke, progressive high-risk review, scoped commit; publication only with authority.
- Excludes: tag/Release before explicit release action.
- Implementation mode: Direct for version/docs; validation/review only after runtime green.
- Delegation: root-owned version/Git; reviewers read-only.
- Red signal: package validator reports stale 2.2.1 sync before bump.
- Minimality decision: repository-native release workflow.
- Focused green: focused runner/recovery/validator suite — 329 run, OK, 4 skipped; full discovery — 344 run, OK, 4 skipped; package validator, `git diff --check`, staged `git diff --cached --check` and `python scripts/validate_package.py --commit-gate` pass; A-017 fresh Sol/high review завершён `ACCEPT`, high confidence, findings none.
- Acceptance: AC-15, AC-16.

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome/success/scope | covered | product decision | D-001–D-004, AC-01–AC-22 | closed by R-005 COVERED |
| B-002 | actors/permissions/authority | covered | product decision | D-001–D-003, T-004/T-007/T-008 | closed by R-005 COVERED |
| B-003 | primary/error/retry/recovery flows | covered | technical decision | exact abandonment contract, T-001–T-004/T-008/T-009, AC-12/AC-19–AC-22 | closed by R-005 COVERED |
| B-004 | accessibility/localization/responsive UI | not applicable | repository fact | CLI/plugin lifecycle has no visual UI; EN/RU prose parity covered B-011 | none |
| B-005 | ownership/contracts/source of truth | covered | repository fact | runtime/instruction evidence table + actual `prompt.md` owner | closed by R-005 COVERED |
| B-006 | data/schema/migration/retention | covered | technical decision | exact v1/grant shapes, T-005/T-008/T-009, AC-14/AC-17/AC-20/AC-22 | closed by R-005 COVERED |
| B-007 | security/privacy/abuse | covered | product + technical decision | D-003/D-004, T-001–T-003/T-005/T-009, AC-21 | closed by R-005 COVERED |
| B-008 | concurrency/ordering/idempotency | covered | technical decision | abandonment phases + blob/grant/reservation boundaries, AC-04/AC-13/AC-17/AC-20/AC-22 | closed by R-005 COVERED |
| B-009 | integrations/timeouts/partial failure | covered | technical decision | guardian matrix + blob/grant/reservation/GC fault fixtures | closed by R-005 COVERED |
| B-010 | compatibility/rollout/rollback | covered | technical decision | T-005/T-006/T-009, AC-17/AC-22, version section | closed by R-005 COVERED |
| B-011 | observability/support/docs | covered | technical decision | T-007/T-009, AC-18/AC-21/AC-22, README/changelog parity | closed by R-005 COVERED |
| B-012 | acceptance/testability/minimality | covered | technical decision | AC-12–AC-22, validation, milestones | closed by R-005 COVERED |
| B-013 | prompt path containment/platform semantics | covered | technical decision | shared stable/privacy/staging contract, T-001/T-008/T-009, AC-01/AC-02/AC-13/AC-19–AC-22 | closed by R-005 COVERED |
| B-014 | user-owned outside diff attribution | covered | product + technical decision | D-003, T-004/T-007, AC-09/AC-11 | closed by R-005 COVERED |
| B-015 | downgrade reader floor | covered | technical decision | T-005, AC-14/AC-17 | closed by R-005 COVERED |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Abandonment превращается в force-unlock или произвольную semantic terminalization | medium/critical | owner-derived v1 digest, exact `[outside-set-drift]`, stopped/identity/zero/guardian/outbox gates + mutation tests | Handled by AC-05–AC-07/AC-13/AC-14 |
| Root принимает чужой diff после release | medium/high | separate T-004 eligibility; unattributable changes block edits | Handled by AC-09/AC-11 |
| In-workspace prompt rejection ломает custom callers | medium/medium | сохранить external `--prompt-file`, actionable pre-spawn error, docs/migration note; impact re-evaluate if public contract found | Open |
| Old reader неверно трактует new event | medium/high | reader floor 2.2.2 + downgrade fixtures | Handled by AC-14 |
| Platform path containment/TOCTOU bypass | low/high | same-open-object identity/read proof; link/junction/reparse/content-swap fixtures Windows/POSIX | Handled by AC-01/AC-02/AC-13 |
| `_authorize-recovery` сохраняет grant/lease из непроверенного prompt или start повторно открывает подменённый path | medium/critical | shared preflight before registry mutation; immutable owner snapshot + plan binding + AC-19 mutations | Handled by T-001/AC-01/AC-19 |
| Crash между blob, grant и reservation меняет prompt либо GC удаляет grant-bound blob | medium/critical | exact prompt bindings в authorization/consumed/plan/lease; три fault boundaries; reference-aware GC | Handled by T-008/AC-20/AC-22 |
| External prompt world-readable или принадлежит другому principal | medium/high | runner-owned private staging + enforced POSIX owner/mode and Windows protected-DACL proof | Handled by T-009/AC-21 |
| Prompt blobs сохраняются бесконечно либо удаляются до replay/archive | medium/high | exact four-state retention, authorization retirement and idempotent locked GC | Handled by T-009/AC-22 |
| Interrupted 2.2.1 state после upgrade остаётся зависшим или дублирует terminal events | medium/high | persisted legacy stopped-terminal forward/reload fixture | Handled by AC-17 |
| User не отличает реальное решение от evidence blocker/capability exhaustion | medium/medium | closed `decision-required` class и раздельные outcome fixtures | Handled by T-007/AC-18 |
| Prose и runtime снова расходятся | medium/high | static validator tokens + end-to-end forward fixture | Handled by AC-15 |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-001 | accepted recommendations; current user message | Outcome, scenarios, AC-04–AC-09, M1–M3 | D-002/D-003, no concurrent writer/no ambiguous handoff | none |
| D-002/R-001 | explicit new writer remains opt-in; accepted recommendations | Out of scope, AC-06/AC-10, T-002/T-004 | 2.2.0 checkpoint authorization | none |
| D-003/R-001 | true authority/evidence boundaries remain fail-closed; accepted recommendations | Outcome, edge cases, AC-05–AC-11, risks | containment/privacy/user-change invariants | none |
| D-004/R-001 | artifacts outside workspace; accepted recommendations | Desired behavior, T-001, AC-01–AC-03, M1/M2 | prompt bytes/digest and exact-runner contract | none |
| Critics/R-002 | accepted NEW-PUX-001/002 and NEW-ADS-001/002 after root evidence check | T-001–T-003/T-005/T-007, exact contracts, AC-01/02/05/06/11/13/14/17/18, coverage/risks/milestones | D-001–D-004; no generic abandon, force-unlock or authority expansion | fresh strong closure |
| Critic/R-003 | accepted NEW-CLOSE-001 after root evidence check | T-001 shared normal/recovery reader, private snapshot/plan binding, AC-01/AC-19, validation/milestones/risks | D-001–D-004; recovery writer opt-in and public prompt privacy | fresh Sol/high closure |
| Critic/R-004 | accepted NEW-SOL-001/002/003 after root evidence check | T-008/T-009, exact grant cross-binding, staging privacy and retention state machine, AC-20–AC-22, validation/risks | D-001–D-004; external `--prompt-file` compatibility and run artifact policy | fresh R-004 Sol/high closure |
| Critic/R-005 | accepted NEW-R4-001 after root evidence check | replaced nonexistent `task.md` with authoritative `prompt.md`; excluded run dirs from blob GC; strengthened AC-22 prompt/request-digest reload proof | D-001–D-004 and all R-004 state/privacy decisions | fresh R-005 Sol/high closure |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | product/operator UX, balanced | GAPS/high confidence; `coverage-gap` | NEW-PUX-001 legacy interrupted-state forward outcome; NEW-PUX-002 distinct genuine-decision outcome; no reopen | accepted into R-002 as AC-17 and T-007/AC-18 |
| R-001 | architecture/data/security, balanced | GAPS/high confidence; `coverage-gap`, `material-uncertainty` | NEW-ADS-001 exact authenticated abandonment evidence; NEW-ADS-002 prompt TOCTOU-safe acquisition; no reopen | accepted into R-002 as exact v1/stable-object contracts and AC-01/02/05/13/14 |
| R-002 | reliability/validation, strong | GAPS/high confidence; `coverage-gap` | NEW-CLOSE-001 `_authorize-recovery` lacked stable pre-mutation prompt proof/snapshot binding; no reopen | accepted into R-003 as shared T-001 contract and AC-19 |
| R-003 | final reliability/security ceiling, Sol/high | GAPS/high confidence; `coverage-gap`, `material-uncertainty` | NEW-SOL-001 durable grant prompt binding; NEW-SOL-002 owner/mode/DACL staging privacy; NEW-SOL-003 retention/GC; no reopen | accepted into R-004 as T-008/T-009 and AC-20–AC-22 |
| R-004 | final state/authorization/privacy, Sol/high | GAPS/high confidence; `coverage-gap` | NEW-R4-001 retention contract named nonexistent `task.md` instead of owner `prompt.md`; no reopen | accepted into R-005 factual owner-name correction and AC-22 |
| R-005 | final owner-contract closure, Sol/high fresh revised tuple | COVERED/high confidence; triggers none; `READY` | new gaps none; reopen none; B-001–B-015 covered | closed; specification may enter implementation workflow |

## 10. Open questions

Blocking product questions:

- None.

Non-blocking assumptions:

- Patch 2.2.2 остаётся корректным, пока implementation не создаёт новый public capability и сохраняет external `--prompt-file`; reviewer обязан переоценить impact при другом diff.
- Current root может выполнять automatic remediation только после доказательства effective high-risk capability; иначе outcome `automation-exhausted`, а не новый permission prompt.

## 11. Agent activity ledger

Created logical agent runs: `17`.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | search / recovery-autonomy-2.2.2-spec-discovery | `gpt-5.3-codex-spark` | low | completed / evidence consumed | mapped runtime, instruction, test, validator and release owners; Sections 2, 6–9 | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-002 | yes | critic / recovery-autonomy-r001-product-ux-critic | `gpt-5.6-terra` | medium | completed / GAPS, high confidence | found legacy-forward and decision-outcome coverage gaps; R-001 → R-002 | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-003 | yes | critic / recovery-autonomy-r001-architecture-critic | `gpt-5.6-terra` | medium | completed / GAPS, high confidence | found abandonment-evidence and prompt-TOCTOU gaps; R-001 → R-002 | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-004 | yes | critic / recovery-autonomy-r002-strong-closure | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | found recovery-authorization prompt/snapshot gap; R-002 → R-003 | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-005 | yes | critic / recovery-autonomy-r003-sol-closure | `gpt-5.6-sol` | high | completed / GAPS, high confidence | found grant crash binding, prompt access-control and retention/GC gaps; R-003 → R-004 | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-006 | yes | critic / recovery-autonomy-r004-sol-closure | `gpt-5.6-sol` | high | completed / GAPS, high confidence | found factual run-artifact owner mismatch; R-004 → R-005 | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-007 | yes | critic / recovery-autonomy-r005-sol-closure | `gpt-5.6-sol` | high | completed / COVERED, high confidence, READY | closed B-001–B-015 with no trigger/gap/reopen; R-005 Ready | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-008 | yes | search / recovery-autonomy-2.2.2-execution-delta-audit | `gpt-5.3-codex-spark` | low | completed / evidence consumed | revalidated runtime/test/static owners and one bounded M1–M3 lease; no decision gap | exact runner `turn.completed`, exit 0, valid result, stopped process tree |
| A-009 | yes | implementation / recovery-autonomy-2.2.2-m1-m3-tdd-implementation | `gpt-5.6-terra` | medium | completed / `NEEDS_ESCALATION: task-complexity-above-tier`, zero writes | capability preflight for M1–M3; authorized exact strong step without changing ACs | exact runner `turn.completed`, exit 0, valid result, stopped process tree; semantic rejection/invalidation/close/release completed |
| A-010 | yes | implementation / recovery-autonomy-2.2.2-m1-m3-strong-implementation | `gpt-5.6-terra` | xhigh | hard deadline / cancelled, no handoff | produced an allowlisted partial M1–M3 runtime/test diff; root completed that same scope only after full-tree stop and vacancy | immutable 900-second deadline, automatic cancel, stopped process tree, registry vacant; no worker handoff accepted |
| A-011 | yes | review / recovery-autonomy-2.2.2-implementation-review-balanced | `gpt-5.6-terra` | medium | completed / REVISE, high confidence | found one AC-02 privacy leak in public runner receipts: absolute run/profile/artifact paths | exact runner `turn.completed`, exit 0, valid result, stopped process tree; finding accepted and remediated with opaque run handle plus mutation coverage |
| A-012 | yes | review / recovery-autonomy-2.2.2-implementation-review-strong | `gpt-5.6-terra` | xhigh | completed / REVISE, high confidence | found missing exact lease/run binding and executable outcome/root-completion audit coverage | exact runner `turn.completed`, exit 0, valid result, stopped process tree; both findings accepted and remediated TDD-first |
| A-013 | yes | review / recovery-autonomy-2.2.2-implementation-review-sol-closure | `gpt-5.6-sol` | high | completed / REVISE, high confidence | found recovery-target abandonment, grant/release GC precedence, public failure privacy, external-action token and durable root-audit gaps | exact runner `turn.completed`, exit 0, valid result, stopped process tree; all findings accepted and remediated TDD-first |
| A-014 | yes | review / recovery-autonomy-2.2.2-implementation-review-sol-final | `gpt-5.6-sol` | high | completed / REVISE, high confidence | found missing crash-durability for the root-completion authority audit | exact runner `turn.completed`, exit 0, valid result, stopped process tree; remediated with shared durable replacement and five-stage fault/replay coverage |
| A-015 | yes | review / recovery-autonomy-2.2.2-implementation-review-sol-closure | `gpt-5.6-sol` | high | completed / REVISE, high confidence | found non-durable prompt blob/run bindings and GC without a production lifecycle hook | exact runner `turn.completed`, exit 0, valid result, stopped process tree; remediated with durable blob/prompt/request ordering and start/terminal GC hooks |
| A-016 | yes | review / recovery-autonomy-2.2.2-implementation-review-sol-final-closure | `gpt-5.6-sol` | high | completed / REVISE, high confidence | found GC bypass of authoritative private-source validation and missing general recovery-target authorization retirement | exact runner `turn.completed`, exit 0, valid result, stopped process tree; remediated with rebarriered source loading and replay-safe successful/semantic terminal retirement |
| A-017 | yes | review / recovery-autonomy-2.2.2-implementation-review-sol-acceptance | `gpt-5.6-sol` | high | completed / ACCEPT, high confidence | independently covered AC-01–AC-22; critical/high/medium/low findings none | exact runner `turn.completed`, exit 0, valid result, stopped process tree; implementation review ladder closed |

Pre-spawn dispatch failures: `1` — первый вызов A-002 передал critic-несовместимый `--specification-revision`; runner отклонил его до создания writer/process, повторный корректный dispatch использовал revision из prompt.

## 12. Execution and validation log

### 2026-07-17 — discovery and initial specification

- Changed: created `BUILD-recovery-autonomy-2.2.2.md`; implementation/package files unchanged.
- Routing: packaged discovery/default step 1/1, map SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`; A-001 exact read-only terminal success.
- Primary signal: not met — specification-only phase; runtime implementation pending.
- Validation: repository evidence and source graph mapped; readiness critic pending.
- Minimality decision: custom owner-layer extension planned; no dependency/service/force-unlock.
- Review: pending high-risk readiness depth.
- Version: planned patch `2.2.1` → `2.2.2` during implementation commit; unchanged now.
- Commit: not created.
- Remaining: two complementary readiness critics, root adjudication and fresh strong closure.

### 2026-07-17 — R-001 complementary critics and R-002 adjudication

- Changed: применены четыре подтверждённых gaps без пересмотра D-001–D-004; добавлены exact `terminal-abandonment-v1`, stable external prompt acquisition, interrupted-2.2.1 forward replay и distinct `decision-required` contracts.
- Routing: packaged critic/high; A-002/A-003 exact balanced read-only terminal success; evidence triggers `coverage-gap`/`material-uncertainty` требуют следующий strong step.
- Primary signal: not met — specification-only phase; runtime implementation pending.
- Validation: critic facts сверены с `recovery_state.py:786-821,3085-3188,3680-3839` и `agent_runner.py:2829-2908,3029-3078,3378-3419`; semantic decisions не переоткрыты.
- Minimality decision: v1 автоматически abandon-ит только exact `[outside-set-drift]`; generic recovery-ineligible/force path не добавляется.
- Review: R-002 fresh strong closure pending.
- Version: planned patch `2.2.1` → `2.2.2`; package files unchanged.
- Commit: not created.
- Remaining: strong closure, final spec validation and status `Ready` if covered.

### 2026-07-17 — R-002 strong closure and R-003 adjudication

- Changed: strong finding NEW-CLOSE-001 применён; T-001 теперь один contract для normal dispatch и `_authorize-recovery`, а recovery start получает task bytes только из immutable owner snapshot, привязанного к target plan.
- Routing: A-004 exact `openbuild_review_strong`/Terra xhigh read-only terminal success; `coverage-gap` последовательно поднимает final fresh closure на `openbuild_review_sol_high`.
- Primary signal: not met — specification-only phase; runtime implementation pending.
- Validation: finding сверено с `agent_runner.py:3083-3148,3430-3492`; текущий recovery authorization действительно читает named path до registry flow и сохраняет в plan только SHA.
- Minimality decision: shared helper + existing owner state; отдельный reader/service/dependency не добавляется.
- Review: R-003 fresh Sol/high ceiling closure pending.
- Version: planned patch `2.2.1` → `2.2.2`; package files unchanged.
- Commit: not created.
- Remaining: Sol/high closure, final spec validation and status `Ready` if covered.

### 2026-07-17 — R-003 Sol/high closure and R-004 adjudication

- Changed: NEW-SOL-001/002/003 применены; prompt ID/SHA теперь bind-ятся до grant commit и через consumed/plan/lease, staging доказывает POSIX owner/mode или Windows protected DACL, retention/retirement/GC имеют exact states.
- Routing: A-005 exact `openbuild_review_sol_high`/Sol high read-only terminal success; ceiling reached, поэтому fresh closure повторяет ту же tier только после semantic revision R-004.
- Primary signal: not met — specification-only phase; runtime implementation pending.
- Validation: findings сверены с `recovery_state.py:428-457,3170-3335`, `agent_runner.py:506-530,3083-3148,3378-3419` и `SKILL.md:48-69`.
- Minimality decision: existing private authorization/source/registry owners расширяются exact fields/state; новый service/dependency не добавляется.
- Review: R-004 fresh Sol/high closure pending; higher tier/fallback absent.
- Version: planned patch `2.2.1` → `2.2.2`; package files unchanged.
- Commit: not created.
- Remaining: fresh R-004 Sol/high closure, final spec validation and status `Ready` if covered.

### 2026-07-17 — R-004 Sol/high closure and R-005 factual correction

- Changed: NEW-R4-001 применён; все retention/non-interference references используют фактический runner artifact `prompt.md`, его `request.json` prompt digest, а blob GC явно исключает run directories.
- Routing: A-006 exact `openbuild_review_sol_high`/Sol high read-only terminal success; fresh R-005 closure остаётся на ceiling tier после changed revision.
- Primary signal: not met — specification-only phase; runtime implementation pending.
- Validation: owner name сверено с `agent_runner.py:3418-3419` и `scripts/test_agent_runner.py:885,1549,2881-2986`; repository run artifact `task.md` отсутствует.
- Minimality decision: factual spec correction only; runtime scope не расширен.
- Review: R-005 fresh Sol/high closure pending; higher tier/fallback absent.
- Version: planned patch `2.2.1` → `2.2.2`; package files unchanged.
- Commit: not created.
- Remaining: fresh R-005 Sol/high closure, final spec validation and status `Ready` if covered.

### 2026-07-17 — R-005 readiness closure

- Changed: status set to `Ready`; no package/runtime implementation files changed.
- Routing: A-007 exact `openbuild_review_sol_high`/Sol high read-only terminal success; verdict `COVERED`, confidence high, triggers/gaps/reopen none, determination `READY`.
- Primary signal: not met by design — this is `$openbuild:build new`; runtime implementation and AC execution belong to future `run`.
- Secondary signal: B-001–B-015 independently closed; all prior gaps adjudicated into R-005.
- Validation: strict UTF-8 без BOM, trailing whitespace 0, contiguous D-001–D-004/T-001–T-009/AC-01–AC-22/B-001–B-015 и все owner paths — pass; `python -m unittest scripts.test_validate_package -v` — 165/165 pass.
- Package validator: `python scripts/validate_package.py` выполнил contracts и вернул единственный expected non-zero release gate — untracked specification при manifest 2.2.1 требует version bump; gate намеренно остаётся до implementation/release commit, false pass не заявляется.
- Git: branch `main`; task scope — только untracked `BUILD-recovery-autonomy-2.2.2.md`; tracked diff отсутствует, `git diff --check` exit 0.
- Minimality decision: final spec retains existing owner layers, one bounded outside-drift abandonment cause, no force-unlock/service/dependency/model-map change.
- Review: readiness complete at configured ceiling.
- Version: planned patch `2.2.1` → `2.2.2` during implementation; manifest/package remain 2.2.1 now.
- Commit/push: not created; repository policy would require release-surface version sync in any implementation commit.
- Remaining: execute `$openbuild:build run BUILD-recovery-autonomy-2.2.2.md` in a separate implementation phase.

### 2026-07-17 — run preflight and balanced capability escalation

- Changed: workflow target moved to `Complete`/`In progress`; package/runtime files remain unchanged.
- Routing: A-008 exact read-only discovery success; packaged implementation/high step 1 A-009 exact Terra/medium workspace-write transport success with canonical pre-edit `NEEDS_ESCALATION: task-complexity-above-tier`.
- Primary signal: not met; writer made zero tracked/workspace implementation edits.
- Validation: `git diff --name-only` empty and `git diff --check` exit 0 before semantic rejection; private owner revalidated the complete snapshot, durably invalidated the A-009 checkpoint, closed guardian, released lease and returned exact vacancy without quarantine.
- Minimality decision: one coherent M1–M3 allowlist, no extra owner/model-map/version files and no replacement on transport failure.
- Review: pending implementation diff.
- Version: 2.2.1 unchanged; patch 2.2.2 remains planned for the final task commit.
- Commit: not created.
- Remaining: exact step 2 `openbuild_implementation_strong` for the same R-005/M1–M3 scope.

### 2026-07-17 — M1–M4 implementation and validation

- Changed: added owner-private bounded prompt staging, stable external import, prompt ID/SHA grant/plan/lease bindings, authorization retirement and reference-aware GC; added exact two-phase `terminal-abandonment-v1`, automatic same-lifecycle reconciliation, 2.2.2 reader floor/legacy forward replay, closed root-completion/outcome contracts, validator mutations, manifest/changelog/README parity.
- Routing: A-010 exact strong/xhigh timed out after allowlisted edits and was automatically cancelled with full-tree-stop; no handoff was accepted. Registry vacancy plus attributable same-revision/same-milestone/same-allowlist diff satisfied T-004, so root recorded and executed automatic same-scope completion without a new writer or user prompt.
- Primary signal: met — the end-to-end fixture reaches exact `outside-set-drift`, retains the stopped lease without handoff, then private reconciliation records abandonment, invalidates the checkpoint, closes guardian/archive and releases the same lease without user authority or replacement writer.
- Secondary signals: mixed reasons reject without byte mutation; pre-write/after-replace faults replay across pending/source phases; persisted 2.2.1 stopped lifecycle advances once; blob→grant→reservation faults preserve one prompt binding; Windows protected-DACL and stable-object fixture passes, POSIX-only paths remain covered by platform-gated contracts.
- Validation: `python -m unittest discover -s scripts -p "test_*.py" -v` — 335 run, OK, 4 skipped platform fixtures; `python scripts/validate_package.py` — pass; `git diff --check` — pass.
- Minimality decision: extended existing `RecoveryRegistry`, runner reconciliation and package-contract owners; no dependency, service, generic abandon cause, force-unlock, automatic recovery writer, model-map or infrastructure change.
- Review: fresh implementation diff review pending at packaged `review.high` starting tier.
- Version: manifest and public surfaces synchronized at patch `2.2.2`; first 2.2.2 durable write raises reader floor, exact 2.2.0/2.2.1 reads remain no-rewrite.
- Commit/push: not yet created; tag/GitHub Release/publication remain out of scope.
- Remaining: exact fresh high-risk review, any evidence-backed remediation, final commit gate and scoped Git publication.

### 2026-07-17 — balanced implementation review and AC-02 remediation

- Changed: public runner receipts now expose only an owner-allocated opaque `run_handle` plus prompt digest/classification; absolute run directory, profile source and artifact paths remain private. Generated handles resolve only below the private default run root, while controller-supplied legacy paths remain compatible and privately retained.
- Routing: A-011 exact packaged `openbuild_review_balanced`/Terra medium completed read-only review with `REVISE`, high confidence and one high AC-02 finding; no other acceptance gap was reported. The actionable finding advances the fresh review route to exact strong/xhigh.
- Primary signal: remains met; AC-02 now also has a direct receipt-redaction fixture and package mutation guard.
- Validation: focused runner/recovery/validator suite — 322 run, OK, 4 skipped; full `python -m unittest discover -s scripts -p "test_*.py" -v` — 337 run, OK, 4 skipped; `python scripts/validate_package.py` and `git diff --check` pass.
- Minimality decision: changed the existing public projection and run-reference resolver; no mapping service, dependency, workspace artifact or new authority path was added.
- Review: fresh exact strong/xhigh implementation review pending on the remediated diff.
- Version: remains synchronized at patch `2.2.2`.
- Commit/push: not yet created; tag/GitHub Release/publication remain out of scope.
- Remaining: exact strong review, any evidence-backed remediation, final commit gate and scoped Git publication.

### 2026-07-17 — strong implementation review and exact-run/outcome remediation

- Changed: terminal reconciliation now derives the expected run ID from the current normal lease or recovery-target plan, rejects a mismatched private directory before guardian/state transitions, and hashes the exact opaque run ID into terminal evidence. Added an executable closed outcome classifier and privacy-safe `root-completion-authorized` audit record.
- Routing: A-012 exact packaged `openbuild_review_strong`/Terra xhigh completed read-only review with `REVISE`, high confidence, one high exact-run finding and one medium fixture/audit finding. Both were accepted; the actionable findings advance final closure to the configured Sol/high ceiling.
- Primary signal: AC-12 now includes semantic `NEEDS_ESCALATION`, orchestrator-like outside drift, retained lease, rejected replacement authorization with no mutation, then autonomous same-lifecycle abandon/release.
- Secondary signals: normal-contained and recovery-target run-ID mismatch fixtures prove byte-for-byte private registry/source preservation; closed decision/blocker/exhaustion/abandonment reports and root-completion audit are executable and privacy-safe.
- Validation: focused runner/recovery/validator suite — 324 run, OK, 4 skipped; full `python -m unittest discover -s scripts -p "test_*.py" -v` — 339 run, OK, 4 skipped; `python scripts/validate_package.py` and `git diff --check` pass.
- Minimality decision: exact owner comparison plus two pure privacy-safe record constructors; no new writer, service, dependency, public status, workspace artifact or authority expansion.
- Review: fresh exact Sol/high closure pending on the remediated diff.
- Version: remains synchronized at patch `2.2.2`.
- Commit/push: not yet created; tag/GitHub Release/publication remain out of scope.
- Remaining: full validation, Sol/high closure, final commit gate and scoped Git publication.

### 2026-07-17 — Sol/high review and final owner-boundary remediation

- Changed: recovery-target abandonment uses the shared lease/plan run-ID owner, retires consumed authorization during checkpoint invalidation and replays across a visible source-commit fault. Live grant/lease prompt references now outrank release tombstones. Public failures are closed classifications, `external-action` matches T-007, and `_record-root-completion` durably writes an idempotent vacancy/no-handoff-bound audit before root edits.
- Routing: A-013 exact packaged `openbuild_review_sol_high`/Sol high completed read-only review with `REVISE`, high confidence and five concrete findings. All were accepted; the changed diff requires a fresh same-ceiling Sol/high closure because no higher configured tier exists.
- Primary signal: retained-lease drift, replacement denial, normal/recovery exact-run gates, both normal and recovery-target abandonment/release, and durable root audit are executable.
- Secondary signals: GC immediately after grant commit retains a reused released-ID blob; every public failure source maps to a closed classification; recovery-target authorization retirement survives after-visible source replacement and reload.
- Validation: targeted finding fixtures and package validator pass; focused runner/recovery/validator suite — 326 run, OK, 4 skipped; full `python -m unittest discover -s scripts -p "test_*.py" -v` — 341 run, OK, 4 skipped; `python scripts/validate_package.py` and `git diff --check` pass.
- Minimality decision: reused existing source/registry/history/run-dir owners and private CLI; no service, dependency, public status, workspace artifact, writer or authority expansion.
- Review: fresh same-ceiling Sol/high closure pending on the remediated diff.
- Version: remains synchronized at patch `2.2.2`.
- Commit/push: not yet created; tag/GitHub Release/publication remain out of scope.
- Remaining: full validation, fresh Sol/high closure, commit gate and scoped Git publication.

### 2026-07-17 — Sol/high durability, retention and acceptance closure

- Changed: A-014–A-016 findings were reproduced red and remediated in the existing owner layers. Root-completion authority, prompt key/blob/run bindings now cross file-sync, write-through replace, post-replace rebarrier and parent-metadata barriers before success/release. Lifecycle GC is production-invoked, validates every private source through the authoritative locked/rebarriered loader, and never deletes on malformed state. Every prompt-bound recovery-target terminal outcome retires consumed authorization; a crash after visible source replacement replays to one retirement/release.
- Routing: A-014, A-015 and A-016 exact Sol/high read-only reviews completed `REVISE` with evidence-backed findings; each factual diff change required a fresh same-ceiling review. A-017 exact Sol/high completed `ACCEPT`, high confidence, AC-01–AC-22 covered, findings none.
- Primary signal: met — the retained-lease/outside-drift trace autonomously terminalizes the same lifecycle with no handoff, replacement writer or operational permission prompt.
- Secondary signals: five-stage durable root/prompt faults, exact source-schema/digest GC failures, grant/lease retention precedence, successful and semantic recovery-target retirement, and source-commit/registry-commit crash replay are executable.
- Validation: focused runner/recovery/validator suite — 329 run, OK, 4 skipped; full `python -m unittest discover -s scripts -p "test_*.py" -q` — 344 run, OK, 4 skipped; `python scripts/validate_package.py` and `git diff --check` pass.
- Minimality decision: reused the existing durable replacement, registry/source/history/reconciliation and GC owners; no dependency, service, provider, model-map, writer or authority expansion.
- Review: implementation ladder closed with A-017 `ACCEPT` at the configured high-risk ceiling.
- Version: manifest, changelog, README and package contracts remain synchronized at patch `2.2.2`; exact legacy reads remain no-rewrite.
- Commit/push: staged commit gate passed; task-scoped commit/push follows this final specification write. Tag/GitHub Release/publication remain out of scope.
- Remaining: task-scoped commit and push.
