# Build: самовосстанавливающийся OpenBuild без операционных остановок

- Status: In progress
- Last updated: 2026-07-27
- Original request: подготовить и выпустить новый релиз OpenBuild, который исправляет irrecoverable quarantined writer lease после потери guardian/checkpoint и перестаёт прерывать выполнение на безопасно разрешимых внутренних проблемах — partial writer diff, false-green focused signal, checkpoint limits/reparse points, исчерпанный review ladder и недоступная Browser-сессия.
- Primary signal: детерминированные fixtures воспроизводят все предоставленные цепочки и доказывают, что OpenBuild сохраняет diff, достигает доказанной vacancy, автоматически выбирает следующий безопасный same-scope шаг и завершает план без операционного запроса пользователю; опубликованный `v2.4.1` устанавливается из удалённого marketplace ref.
- Review baseline: `main@f0d5bf68a4e8ee0e20bb95475944d43eab2098af`, исходное состояние чистое (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: discovery
- Specification lineage: `76670abf96785973fd216601dd1a465659843bcc010edf004a3fd95b638c7969`
- Specification revision: R-010
- Complexity: high — меняются recovery snapshot, durable lease/quarantine continuation, single-writer/root-completion authority и progressive-review release gate.
- Implementation mode: TDD-first — меняются наблюдаемое поведение, state-machine contracts и маршрутизация validation/review.
- Version impact: patch `2.4.0` → `2.4.1` — backward-compatible исправление обещанной автономности; источник версии `plugins/openbuild/.codex-plugin/plugin.json`, синхронные поверхности `CHANGELOG.md`, `README.md`, `README.ru.md`.
- Routing mode: `codex-exec-explicit-model`
- Discovery mode: root-recovery — exact read-only search был создан и завершился `turn.completed`/exit `0` со stopped tree, но runner отклонил результат как `result-evidence-invalid`; завершённый turn не допускает Terra fallback.
- Search usage route: separate-pool → targeted root-recovery; circuit breaker открыт для новых discovery agents в этом Build-run.
- Search routing receipt: packaged `OpenBuild defaults`, SHA-256 `3f9eceafea582baa2394a0c9744c0dbfc260b4daeb37475aca3f1c611e007701`, discovery/default step 1/1, exact `openbuild_search_separate`, configured `gpt-5.3-codex-spark`/low/read-only, terminal `turn.completed`, exit `0`, invalid result evidence, stopped process tree, fallback none.
- Implementation model route: packaged `implementation.high`; точный профиль будет разрешён перед writer dispatch, дальнейший step разрешён только по валидному pre-edit semantic trigger.
- Implementation routing receipt: packaged map SHA-256 `3f9eceafea582baa2394a0c9744c0dbfc260b4daeb37475aca3f1c611e007701`, implementation/high. Step 1 A-007 exact Balanced/medium completed transport-success with zero-write configured `NEEDS_ESCALATION: task-complexity-above-tier`; semantic rejection and source checkpoint invalidation completed, registry vacant. Step 2 A-008 Strong/xhigh exceeded its immutable observation deadline after producing an allowlisted partial diff; root cancelled the full tree, registry reached proven vacancy, rejected the false-green handoff through independent tests and completed the same scope directly. A later package-wide Windows lock finding added a root-owned R-006 owner fix in `project_state.py`.
- Review routing receipt: packaged `review.high`; A-009 Balanced/medium returned three production-integration findings, remediated in R-007. A-010 Strong/xhigh returned one scoped-inventory finding, remediated in R-008. A-011 Sol/high returned one high cross-task ledger finding and one low stale-spec finding, remediated in R-010. The fresh lineage-bound A-012 Balanced/medium review returned `ACCEPT` with no actionable current-diff findings; `stop_on_success=true` closed the route without unnecessary higher steps.

## 1. Outcome

### Problem

OpenBuild формально содержит безопасные recovery primitives, но coordinator policy и checkpoint inventory не складываются в непрерывный пользовательский workflow:

- exact Windows guardian loss может оставить lease в `containment-loss-after-boundary` без terminal receipt, `guardian-zero` и публичного checkpoint, после чего агент сообщает об irrecoverable quarantine вместо автоматического owner reconciliation;
- recovery snapshot рекурсивно хеширует все Git-ignored объекты, поэтому многогигабайтная `.scratch` или служебный reparse point в `node_modules/.bin` отключают checkpoint, хотя эти объекты не принадлежат task diff;
- после semantic `BLOCKED`, terminal abandonment или неполного focused signal сохранённый allowlisted diff остаётся без автоматического post-vacancy root-completion, и пользователь получает просьбы повторить RUN либо «разрешить исправить Mx напрямую»;
- исправления после последнего reviewer ошибочно считаются исчерпавшими общий review budget, хотя новый diff ещё не получил независимый review;
- отсутствие подключённой Codex Browser-сессии превращается в permission prompt на локальный Playwright, хотя локальная same-scope QA обратима и не требует новой продуктовой authority.

### Desired behavior

Пользователь один раз задаёт конечный результат. После этого OpenBuild сам выполняет все обратимые task-scoped действия, для которых уже есть доказанная authority: наблюдает тот же процесс, reconciles тот же lifecycle, сохраняет diff, выполняет root completion, исправляет подтверждённый false-green сигнал, запускает новый review epoch для изменённого diff и использует доступный локальный browser QA runtime.

Workflow останавливается только когда отсутствует обязательное safety/ownership evidence либо действительно требуется новое решение о product, architecture, scope, permissions, privacy, security, destructive/external/publication действии.

### In scope

- Ограничить recovery checkpoint task-relevant inventory без обхода allowed/status safety checks.
- Детерминировать automatic continuation после quarantine, terminal abandonment, semantic rejection и partial diff.
- Уточнить review budget как budget одного immutable diff revision, а не всего пользовательского Build.
- Добавить автоматическую локальную Browser/Playwright substitution policy.
- Закрепить поведение executable/static contract tests, документацией и release validation.
- Выпустить стабильный `2.4.1`.

### Out of scope

- Force-unlock, удаление private registry, подделка checkpoint/receipt или принятие живого/неатрибутируемого writer diff.
- Автоматизация credentials, authenticated external UI sessions или destructive cleanup пользовательских данных.
- Ослабление single-writer, exact-model, containment, fingerprint, allowed-set и Git provenance gates.
- Новый dependency/provider/hosted infrastructure.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Ignored inventory | `plugins/openbuild/skills/build/scripts/recovery_state.py:4225` | Snapshot получает все ignored paths через `git ls-files --others --ignored` и рекурсивно записывает их. | `.scratch` и `node_modules` расходуют byte/record budget и встречают reparse-point до запуска contained writer. |
| Byte limit | `plugins/openbuild/skills/build/scripts/recovery_state.py:3958` | Любой хешируемый chunk участвует в общем `max_bytes` и вызывает `checkpoint byte limit exceeded`. | Ignored build cache может понизить run до `normal-legacy`, хотя task files малы. |
| Existing orphan repair | `plugins/openbuild/skills/build/scripts/agent_runner.py:6077` | `_reconcile-containment-loss` уже имеет точную Windows pre-zero ветвь и post-zero ветвь. | Нужен автоматический coordinator selection, а не unsafe registry repair. |
| Root completion | `plugins/openbuild/skills/build/scripts/agent_runner.py:6623` | `_record-root-completion` умеет доказуемо авторизовать same-scope root completion после vacancy. | Предоставленные кейсы не должны требовать нового пользовательского разрешения. |
| Current policy | `plugins/openbuild/skills/build/references/implementation-delegation.md:40` | Документ уже запрещает routine operational prompts. | Реальное поведение расходится с обещанным контрактом. |
| Review loop | `plugins/openbuild/skills/build/references/review-protocol.md:157` | Запрещён повтор reviewer только для неизменённого diff, но `max_steps` не определён явно на diff revision. | Coordinator интерпретировал ceiling как исчерпанный после исправлений старого diff. |
| Release source | `plugins/openbuild/.codex-plugin/plugin.json:3` | Baseline version — `2.4.0`; candidate version — `2.4.1`. | Изменение является стабильным patch-релизом. |
| Package checks | `CONTRIBUTING.md:50` | Репозиторий требует unittest, package validator, diff checks и staged commit gate. | Release должен пройти одинаковые source/staged проверки. |

### Source of truth

Runtime ownership разделён между `recovery_state.py` (checkpoint/registry state), `agent_runner.py` (process/lease reconciliation и root-completion audit) и `SKILL.md` с `references/implementation-delegation.md`/`review-protocol.md` (coordinator policy). Исправление должно согласовать эти слои; downstream prose workaround не считается достаточным.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD-recovery-self-healing-2.4.1.md` | текущий Build root | In progress/R-010, lineage `76670abf…` | требования, AC, T-###, milestones; применяет D-001–D-003 | ссылки в таблице evidence являются implementation evidence, нормативных дочерних spec нет | yes | aligned |
| Текущий пользовательский запрос и приложенные incident traces | user | 2026-07-27 | D-001, D-002, D-003 | outgoing normative links отсутствуют | no | aligned |

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| Операционные permission prompts против желаемой автономности | текущий запрос явно требует, чтобы OpenBuild решал подобные проблемы сам и не прерывался | D-001, текущий user message | aligned |
| Repair без потери diff и без ручного private-registry edit | формулировка главного вопроса в incident trace | D-002, текущий user message | aligned |
| Подготовка против публикации | пользователь просит «подготовить и выпустить новый релиз» | D-003, текущий user message | aligned |

### Gap

Есть безопасные низкоуровневые transitions, но отсутствует одна обязательная автоматическая continuation loop, а checkpoint захватывает нетасковые ignored bytes. Поэтому fail-closed защита превращается в детерминированную остановку даже при достаточных evidence и authority.

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | workflow.internal-problem.auto-continue | user | resolved | Должен ли Build прерываться на безопасно разрешимых внутренних проблемах? | Нет; OpenBuild сам продолжает до результата, пока существует безопасный progress-making same-scope root/reconcile/validation/review path под исходным `full`/`run`/implementation-targeted `auto`. | Текущий запрос: «мой таргет чтобы опен билд подобные "проблемы" сам решал и не прерывался»; приложенные цепочки показывают нежелательность повторных RUN/direct-fix/QA/review permission prompts. | Routine operational prompts запрещены; новый writer после исчерпания root authority остаётся отдельным security-sensitive действием, а не маскируется как routine вопрос. |
| D-002 | recovery.preserved-diff.no-private-edit | user | resolved | Какой repair outcome допустим? | Освободить irrecoverable lease без потери рабочего diff и без ручного редактирования private registry. | Приложенный incident, «Главный вопрос». | Только owner-derived, evidence-bound reconciliation; force unlock исключён. |
| D-003 | release.stable.publish | user | resolved | Нужен ли только локальный fix или опубликованный релиз? | Подготовить и выпустить новый стабильный bugfix-релиз. | Первая строка текущего запроса. | Patch version, commit, push, annotated tag и GitHub Release входят в scope после green gates. |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Новый private snapshot policy `task-relevant-v2` хеширует allowed paths и Git-visible status paths; ignored classification запрашивается у Git только bounded batches literal allowed-root pathspecs с collapsed ignored directories, поэтому ignored paths вне task scope не перечисляются и не расходуют checkpoint budget. Legacy source без policy читается как `full-ignored-v1` и один сохраняет global traversal/revalidation. | selected | Текущий полный ignored traversal создаёт ложные blockers; пост-фильтрация global buffered output также недостаточна, как подтвердил A-010. Policy binding предотвращает cross-mode сравнение. | D-002, allowed-set/reparse/status/Git provenance gates остаются; task diff не теряется; old readers fail-closed на floor `2.4.1`. |
| T-002 | Ввести обязательный automatic continuation audit перед любым incomplete Build response после implementation start; `_record-root-completion --continuation-action` после durable audit пишет digest-bound `automatic-continuation.json`. | selected | Низкоуровневые reconcile/root-completion команды уже существуют, но policy без production call site применялась недетерминированно. | D-001/D-002; audit не создаёт authority, routine action продолжает workflow, `new-writer` остаётся `decision-required`. |
| T-003 | `max_steps` применяется к одной immutable diff revision; remediation создаёт новую revision и новый последовательный review epoch. | selected | Запрет повторения на unchanged diff сохраняется; старый terminal review не доказывает исправленный diff. | D-001; independent current-diff review остаётся обязательным. |
| T-004 | При отсутствии Codex Browser использовать project-native e2e, затем уже установленный локальный Playwright/browser runtime с fresh temporary profile, stripped secret/auth environment, loopback/file-only target и denied external network/action; иначе fallback недопустим. | selected | Локальная обратимая QA не является external action только при доказанной изоляции; authenticated external session не подменяется. | D-001; acceptance evidence не ослабляется, external auth boundary сохранена. |
| T-005 | Root-completion-first: новый recovery writer не считается routine continuation и не запускается автоматически. Только после доказанного отсутствия safe same-scope root path он может стать отдельным `decision-required` security action с exact checkpoint/scope consequences. | selected | Все предоставленные M1/M2/false-green кейсы имеют attributable partial diff и решаются root completion; inferred replacement-writer authority не нужна. | D-001/D-002; routine prompts устранены без расширения writer authority. |
| T-006 | Review remediation доказывает progress через canonical `openbuild.review-progress.v2`: stable specification lineage, revision, full diff SHA-256, validation receipt digest, AC coverage digest, sorted stable open/closed finding keys. Каждый reviewer dispatch обязан передать эти поля; runner под workspace lock consults matching lineage и append-only сохраняет owner-private digest ledger, отклоняет concurrent drift и четвёртую попытку одного immutable diff. Legacy v1 entries остаются проверяемыми, но не блокируют новый lineage. | selected | Pure helper без production caller не закрывал review loop; repository-wide latest entry блокировал независимые Build-задачи, per-diff `max_steps` недостаточен против бесконечной цепочки, а prose findings нельзя сравнивать replay-safe. | D-001; OpenBuild продолжает при доказанном прогрессе, независимый Build получает `first-review`, workspace artifact не создаётся, а exhaustion остаётся fail-closed. |
| T-007 | Reviewer findings получают обязательный stable `finding_key` по semantic owner/contract/consequence, независимый от wording и line drift; root канонизирует/deduplicates keys перед progress digest. | selected | Без stable keys paraphrase обходит cycle detection. | D-001 и AC-09/10 сохраняются; reviewer остаётся read-only, root владеет adjudication. |
| T-008 | `_browser-qa-substitute` владеет subprocess: фиксирует revision + pre/post full-diff SHA-256, argv/scenario digests, nonce/fresh profile/stripped env и запускает child только suspended внутри kill-on-close Job. До resume обязательный independent runner-trusted network guard должен привязать loopback/file allowlist; project/child stdout или callback не являются network evidence. | selected | A-009 показал, что прежний callback мог просто пересказать child stdout. На платформе без trusted pre-execution guard command fail-closed до child code вместо unsafe local fallback. | T-004/D-001; current-diff QA не ослабляется, external action authority не создаётся, отсутствие guard не превращается в permission prompt. |
| T-009 | Browser receipt acceptance rederives every digest, включая guard attachment, и rejects stale revision/diff/scenario/command, missing/duplicate nonce, wrong process identity, path/cookie/secret fields, guard-observed external request/action, nonzero/unknown exit, live tree, replay и artifact replacement. | selected | Sol/high critic доказал false-green через replay старого receipt; A-009 доказал self-report gap сетевой части. | D-001/D-002, AC-11/15 и privacy invariants сохранены. |
| T-010 | Mutable Windows coordinator publication повторяет только transient access/sharing violations `5/32/33` в ограниченном двухсекундном окне с exponential backoff; прочие ошибки и исчерпание окна остаются fail-closed. | selected | Два package-wide run последовательно упали на разные `MoveFileEx`/`os.replace` locks, а каждый exact isolated rerun прошёл; бесконечный retry либо blanket error suppression недопустимы. | D-001; durable write-through barrier, temp-file identity, lock ownership и non-transient failure semantics сохраняются. |

### Pending proposals

- Нет.

## 4. User scenarios

### Primary scenario

1. Пользователь запускает `full`, `run` или implementation-targeted `auto`.
2. Writer/guardian/test/reviewer/browser path сталкивается с одним из предоставленных внутренних blockers.
3. OpenBuild сохраняет task diff, доказывает состояние процессов/lease и автоматически выбирает допустимый continuation.
4. Пользователь получает завершённый результат и release evidence, а не инструкцию перезапустить Build или выдать ещё одно routine разрешение.

### Errors and edge cases

- Guardian/worker/Codex identity live, unknown или drifted → fail-closed `blocked`, без force-unlock и нового writer.
- Diff выходит за allowed scope либо не может быть независимо атрибутирован → `blocked`, bytes сохраняются.
- Ignored path одновременно является explicit allowed path → он остаётся полностью защищённым allowed inventory.
- Non-ignored untracked/modified outside-set path меняется → recovery eligibility по-прежнему снимается.
- Trusted pre-execution browser network guard недоступен или AC требует authenticated external session → substitute fail-closed до child code, limitation фиксируется без просьбы разрешить небезопасный fallback.
- Reviewer нашёл defect на последней ступени → root исправляет defect, присваивает новый diff identity и автоматически запускает свежий risk-floor review epoch.

## 5. Requirements and acceptance criteria

- [x] AC-01: `.scratch`/`node_modules` и другие ignored paths вне allowed/status не перечисляются global Git query, не входят в recovery record/byte budget и не отключают containment.
- [x] AC-02: ignored reparse point вне allowed/status не блокирует checkpoint; reparse point внутри allowed path по-прежнему fail-closed.
- [x] AC-03: explicit allowed ignored file/dir полностью хешируется и revalidates как allowed inventory.
- [x] AC-04: tracked, modified и non-ignored untracked outside-set drift по-прежнему делает recovery ineligible.
- [x] AC-05: exact pre-zero Windows orphan quarantine автоматически проходит существующий owner reconciliation, если обязательные identity/provider/activation evidence валидны.
- [x] AC-06: после v1–v5 terminal abandonment и доказанной vacancy same-revision/same-milestone/same-allowed partial diff автоматически проходит `_record-root-completion` audit без нового user prompt.
- [x] AC-07: semantic `BLOCKED`/false-green focused signal с безопасным attributable partial diff продолжается root-owned TDD remediation, а не просьбой «исправь Mx напрямую».
- [x] AC-08: OpenBuild автоматически исчерпывает reconcile/root-completion path для attributable partial diff; новый recovery writer не предлагается как «разреши продолжить», а появляется только как отдельный `decision-required` security action после доказанного отсутствия safe root path.
- [x] AC-09: после progress-making remediation reviewed diff получает новую identity и свежий sequential same-lineage review epoch; каждый dispatch обязан consult/append owner-private valid `openbuild.review-progress.v2`, а независимый Build lineage получает `first-review` и не наследует старый `max_steps`.
- [x] AC-10: один и тот же tier не повторяется на неизменённом diff, reviewers остаются read-only и route ceiling остаётся risk-bound; findings содержат stable `finding_key`, concurrent ledger drift/repeated/no-progress digest и четвёртая same-diff попытка детерминированно возвращают `automation-exhausted`.
- [x] AC-11: недоступная Codex Browser-сессия заменяется локальным QA только через runner-owned `openbuild.browser-qa.v1`, связанный с current revision/full diff/argv/scenario/nonce/process и independent network guard, установленным до child resume; project/child self-report не принимается, а отсутствие guard fail-closed до child code без permission prompt. Negative tests также отклоняют stale, tampered, replayed и external/live/nonzero receipts.
- [x] AC-12: перед incomplete final response `_record-root-completion` durably binds audit к automatic continuation action; `decision-required`, `blocked` и `automation-exhausted` используются только по их доказанным границам и не маскируются под permission prompt.
- [x] AC-13: package tests, focused recovery/runner tests, full unittest, validator, UTF-8/line-ending checks и staged commit gate проходят.
- [x] AC-14: manifest, changelog, EN/RU README и install pins синхронно указывают `2.4.1`.
- [ ] AC-15: annotated tag `v2.4.1`, GitHub Release и remote install/smoke подтверждают опубликованный reviewed commit.

### Invariants

- Ни один continuation path не стартует второй writer при non-vacant lease.
- Никакие bytes рабочего diff не удаляются автоматически ради прохождения recovery.
- Private paths, nonces, credentials и raw registry state не попадают в публичные receipts/docs.
- Recovery authority не расширяет allowed set, revision, milestone или publication scope.
- Новый recovery writer не получает inferred authority из исходного запроса; его exact one-shot authorization остаётся отдельной security boundary.
- Legacy registry generations продолжают читаться без rewrite-on-read; reader floor не понижается.
- Published tags не перемещаются и не перезаписываются.

## 6. Technical boundaries

### Affected layers and contracts

- `recovery_state.py` — task-relevant snapshot inventory.
- `agent_runner.py` — durable continuation receipt вокруг существующих reconciliation/root-completion primitives, owner-private review-progress dispatch ledger и runner-owned independently guarded Browser QA substitute lifecycle/receipt.
- `SKILL.md`, `implementation-delegation.md`, `review-protocol.md` — обязательная non-interruption loop, review epochs и QA substitution.
- `validate_package.py` и tests — запрет регрессии к routine permission prompts и stale-review closure.
- manifest/changelog/READMEs — release contract.

### Data and migration

Private checkpoint/source allowlist получает обязательный `snapshot_policy`. Новые источники используют `task-relevant-v2`; legacy sources без поля интерпретируются только как `full-ignored-v1` и revalidate прежним mode без rewrite-on-read. Первый durable `task-relevant-v2` write повышает reader floor до `2.4.1`; старый reader fail-closed на non-vacant 2.4.1 state. Vacant registry retirement остаётся rollback boundary.

### Security and privacy

Ignored exclusion не разрешает writer редактировать ignored paths: lease allowlist и workspace diff attribution остаются отдельными gates. Любой explicit allowed ignored path проходит прежнюю no-follow/reparse/content проверку. Repair не принимает отсутствующую process identity и не синтезирует guardian evidence вне уже предусмотренной Windows orphan ветви. Новый writer не получает inferred authority. Локальный browser fallback запускается без persistent/authenticated profile и без external network/action capability только после independent pre-execution guard; иначе child не запускается.

### Performance and concurrency

Checkpoint cost становится пропорционален allowed + Git-visible dirty inventory, а не размеру build caches. Single-writer и project-lane isolation не меняются. Review epochs последовательны.

### Observability and errors

Continuation audit публикует privacy-safe outcome и выбранный next action только после durable root audit. `blocked` перечисляет только missing evidence; `decision-required` — только пользовательскую decision axis; routine success path не публикует просьбу о дополнительном разрешении. Owner-private review ledger сохраняет canonical progress digest, dispatch identity и stable finding keys. Browser substitution записывает runner-owned current-diff/guard receipt digest, runtime, scenarios/check count и evidence limitation; raw path/nonce/process/credential данные остаются private.

### Versioning and release

Version source: `plugins/openbuild/.codex-plugin/plugin.json`. Следующая стабильная версия: `2.4.1`. User D-003 уже авторизует push, annotated tag и GitHub Release после текущего full-diff review и commit gate.

## 7. Validation and review

- Primary signal: realistic regression trace для incident chain + remote `v2.4.1` install smoke.
- Red signal: новые focused tests сначала доказывают текущие failures — ignored byte/reparse blocker, post-abandonment permission gap, stale review ceiling/cycle key и отсутствие enforceable Browser receipt.
- Minimality decision: reused existing recovery/review owners; без новой зависимости, force-unlock или второго coordinator.
- Focused green: `python -m unittest scripts.test_recovery_state scripts.test_agent_runner scripts.test_validate_package -v`.
- Targeted checks: `python scripts/validate_package.py`; `git diff --check`.
- Wider checks: `python -m unittest discover -s scripts -p "test_*.py" -v`.
- Manual/runtime check: clean packaged plugin install; exact-runner smoke; remote install from candidate tag after publication.
- Starting review tier: Balanced — high-risk minimum.
- Required final tier: Balanced, с переходом только по concrete trigger; remediation на ceiling создаёт новую diff revision и свежий epoch.
- Review ladder: packaged `review.high`, sequential, one reviewer per unchanged `(diff identity, tier)`.
- Review focus: checkpoint security, lease vacancy, partial-diff attribution, no useless prompts, current-diff coverage, compatibility and release integrity.

## 8. Milestones

### M1. Task-relevant checkpoint и automatic continuation

- Status: Complete
- Scope: recovery inventory, continuation audit/classification, fixtures для orphan/abandonment/semantic partial diff.
- Excludes: version/publication edits.
- Implementation mode: TDD-first
- Delegation: bounded-worker — step 1 lease `release-241-r005-m1m2` completed zero-write escalation; step 2 lease `release-241-r005-m1m2-strong`, requested `openbuild_implementation_strong` / packaged high step 2; unchanged allowed set, specification/version/changelog/README/Git forbidden.
- Red signal: worker adds focused regression fixtures for AC-01–AC-12 and first runs them against current owners, requiring failure on ignored inventory, stale continuation/review and unbound Browser evidence.
- Minimality decision: reused existing owners + Python standard library; skipped new registry, dependency, browser package and parallel coordinator; ceiling is project-native harness emitting the runner nonce-bound observation.
- Focused green: `python -m unittest scripts.test_recovery_state scripts.test_agent_runner -v`
- Validation: focused + package validator.
- Acceptance: AC-01–AC-08, AC-12
- Review: A-009 finding `525f77…` remediated in R-007; A-010 scoped-inventory finding remediated in R-008; fresh R-010 review pending
- Version: unchanged
- Commit: Pending

### M2. Review epoch и локальная QA substitution

- Status: Complete
- Scope: coordinator/review/validation contracts, canonical review-progress owner, runner-owned Browser QA launch/observation/receipt и static/executable regression tests.
- Excludes: external authenticated browser automation.
- Implementation mode: TDD-first
- Delegation: тот же lease `release-241-r005-m1m2` в одном coherent owner-layer milestone; writer не меняет specification/version/release surfaces.
- Red signal: package contract принимает stale review ceiling/permission prompt, paraphrased finding cycle и stale/tampered/self-authored Browser evidence без runner provenance.
- Minimality decision: изменить существующие references/validator, не добавлять browser dependency.
- Focused green: `python -m unittest scripts.test_validate_package -v`
- Validation: focused + full package.
- Acceptance: AC-09–AC-13
- Review: A-009 findings `e41f45…` and `4f5d4d…` remediated in R-007; A-011 lineage finding `7c62f5…` remediated in R-010; fresh R-010 review pending
- Version: unchanged
- Commit: Pending

### M3. Stable release 2.4.1

- Status: In progress
- Scope: manifest, changelog, EN/RU README, final validation, commit, push, tag, GitHub Release, remote smoke.
- Excludes: переписывание опубликованных tags.
- Implementation mode: Direct для version/docs; TDD-first gates уже закрыты M1/M2.
- Delegation: root-only — version, Git и publication принадлежат root.
- Red signal: не применимо; version surfaces проверяются package validator.
- Minimality decision: существующий SemVer/release contract.
- Focused green: `python scripts/validate_package.py --commit-gate`
- Validation: full unittest, validator, diff checks, clean install, remote tag/release smoke.
- Acceptance: AC-13–AC-15
- Review: Pending
- Version: `2.4.0` → `2.4.1`
- Commit: Pending

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome.scope.success | covered | product decision | D-001–D-003, AC-01–AC-15 | critic verification |
| B-002 | actors.permissions | covered | product decision | D-001/D-002 и T-005; root completion автоматичен, новый writer сохраняет отдельную security authority | critic verification |
| B-003 | recovery.primary-alternate-errors | covered | technical decision | T-001/T-002, AC-01–AC-08/12 | fixtures |
| B-004 | ui.localization.responsive | not applicable | repository fact | Плагин не содержит пользовательский UI; EN/RU docs parity покрыта AC-14. | none |
| B-005 | ownership.contracts | covered | repository fact | `recovery_state.py`, `agent_runner.py`, policy references | critic verification |
| B-006 | data.schema.migration.retention | covered | technical decision | T-001: versioned snapshot policy, legacy mode, first-write floor `2.4.1`, no rewrite-on-read | compatibility tests |
| B-007 | security.privacy.trust | covered | product decision | D-002/T-004/T-005 запрещают force unlock/path leaks/inferred writer authority/authenticated browser reuse | adversarial tests |
| B-008 | performance.capacity | covered | technical decision | T-001 ограничивает inventory task-relevant paths | large ignored fixture |
| B-009 | concurrency.idempotency | covered | repository fact | single-writer/owner transitions сохраняются | replay tests |
| B-010 | integrations.partial-failure | covered | technical decision | T-004/T-008/T-009: runner-owned current-diff substitute или authenticated-session exception | contract tests |
| B-011 | observability.support | covered | technical decision | privacy-safe continuation outcome/next action + review-progress/Browser QA receipt digests | runner tests/docs |
| B-012 | rollout.rollback.release | covered | product decision | D-003, patch SemVer, immutable tag | release checklist |
| B-013 | acceptance.testability | covered | technical decision | focused + full + canonical progress + Browser provenance/replay/tamper fixtures + remote signals | validation plan |
| B-014 | minimality.cost | covered | technical decision | existing owners, standard library, no dependency | reviewer audit |
| B-015 | review.current-diff | covered | technical decision | T-003/T-006/T-007, AC-09/10: per-diff epoch + persisted canonical progress key | review trace |
| B-016 | browser.qa-fallback | covered | technical decision | T-004/T-008/T-009, AC-11 требуют runner-owned current-diff isolated receipt | agent-runner/package fixtures |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Excluding ignored data hides task-relevant state | medium/high | explicit allowed ignored paths остаются fully inventoried; Git-visible status сохраняется | Open |
| Automatic continuation releases ambiguous lease или создаёт лишний writer | low/critical | exact identity/zero/vacancy gates; один source-bound recovery grant; negative replay/second-target/tamper tests | Open |
| Review epochs loop indefinitely | low/medium | owner-private digest ledger consult/append перед dispatch, максимум три review одного immutable diff; repeated semantic cycle → `automation-exhausted` | Open |
| Local browser substitute weakens AC или использует auth/external side effect | medium/high | fresh temp profile, stripped auth/secrets, suspended child и independent pre-resume network guard; при недоступной изоляции child не запускается | Open |
| Release docs расходятся с runtime | medium/medium | package validator + commit gate + remote smoke | Open |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-005 | self-resolve routine internal problems while canonical evidence proves net progress; текущий user request и incident chains | Outcome, scenarios, T-002/T-003/T-005–T-009, AC-05–AC-12, M1/M2 | D-002/D-003, fail-closed/single-writer invariants | none |
| D-002/R-005 | preserve diff, no manual private-registry edit; incident trace | Out of scope, T-001/T-005/T-009, AC-02–AC-08/11, security/migration boundaries, M1/M2 | D-001/D-003, provenance/privacy | none |
| D-003/R-005 | prepare and publish stable bugfix release; текущий user request | AC-14/15, version/release, M3 | D-001/D-002, immutable tags/current-diff evidence | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | product/UX, Balanced | GAPS, high confidence | recovery-writer opt-in contradicted D-001; Browser QA evidence disclosure absent from AC | D-001 finding deduplicated against explicit no-interruption outcome; R-002 removes prompt via T-005/AC-08 and adds evidence disclosure to AC-11/B-011/B-016 |
| R-002 | architecture/data/security, Balanced | GAPS, high confidence | inferred recovery authority, unversioned snapshot policy, browser isolation, cross-revision review termination | R-003 keeps writer authority separate, adds policy/floor compatibility, isolated browser predicate and progress/cycle detection |
| R-003 | reliability/validation, Strong | GAPS, high confidence | canonical progress key и enforceable Browser isolation receipt отсутствовали | R-004 adds T-006/T-007 canonical persisted progress identity and T-008 strict runner-owned Browser receipt |
| R-004 | reliability/validation, Sol/high | GAPS, high confidence | Browser receipt не имел runner-owned provenance/freshness/replay binding | R-005 expands T-008 and adds T-009 current-diff/command/scenario/nonce/process binding with negative controls |
| R-005 | reliability/validation, Sol/high | COVERED, high confidence | none | Ready gate closed; implementation/validation/release remain pending |

## 10. Open questions

Blocking product questions:

- None.

Non-blocking assumptions:

- `gh` и publication credentials доступны; проверяется перед tag/release, но не меняет implementation scope.
- Local Playwright policy является fallback order, а не требованием добавлять dependency в OpenBuild.

## 11. Agent activity ledger

Created logical agent runs: 12.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | discovery/release-recovery-continuation-discovery | `gpt-5.3-codex-spark` | low | transport completed; semantic evidence rejected | Read-only repository discovery result не использован; mapping none | exact runner: `turn.completed`, exit 0, stopped tree, `result-evidence-invalid` |
| A-002 | yes | critic/readiness-r001-product-ux | `gpt-5.6-terra` | medium | completed; GAPS, high confidence | Нашёл contradiction D-001/AC-08 и missing Browser evidence disclosure; R-002, B-002/B-011/B-016 | exact runner: `turn.completed`, exit 0, valid result, stopped tree |
| A-003 | yes | critic/readiness-r002-architecture-security | `gpt-5.6-terra` | medium | completed; GAPS, high confidence | Нашёл authority, snapshot-policy, browser-isolation и review-cycle gaps; R-003, T-001/T-004–T-006 | exact runner: `turn.completed`, exit 0, valid result, stopped tree |
| A-004 | yes | critic/readiness-r003-strong-closure | `gpt-5.6-terra` | xhigh | completed; GAPS, high confidence | Нашёл отсутствие canonical persisted progress key и enforceable Browser receipt; R-004, T-006–T-008 | exact runner: `turn.completed`, exit 0, valid result, stopped tree |
| A-005 | yes | critic/readiness-r004-terminal-closure | `gpt-5.6-sol` | high | completed; GAPS, high confidence | Нашёл Browser receipt provenance/freshness/replay gap; R-005, T-008/T-009 | exact runner: `turn.completed`, exit 0, valid result, stopped tree |
| A-006 | yes | critic/readiness-r005-fresh-terminal-closure | `gpt-5.6-sol` | high | completed; COVERED, high confidence | Закрыл B-001–B-016 без новых gaps/reopens; R-005 Ready | exact runner: `turn.completed`, exit 0, valid result, stopped tree |
| A-007 | yes | implementation/m1m2_r005_self_healing_release | `gpt-5.6-terra` | medium | completed; zero-write `NEEDS_ESCALATION: task-complexity-above-tier` | Capability preflight only; M1/M2 unchanged, step 2 approved | exact runner: `turn.completed`, exit 0, valid result, stopped tree; semantic rejection/invalidation complete |
| A-008 | yes | implementation/m1m2_r005_self_healing_release_strong | `gpt-5.6-terra` | xhigh | hard deadline; cancelled with full-tree stop, allowlisted partial diff preserved | Produced M1/M2 owner/test/reference diff; root rejected false-green recovery tests, proved registry vacancy, then completed and validated the same scope | exact runner: no terminal event/result, cancel receipt failed-closed, worker/Codex stopped, registry lease/quarantine vacant |
| A-009 | yes | review/r006-current-diff-balanced | `gpt-5.6-terra` | medium | completed; `ESCALATE`, high confidence | Found three production integration gaps: continuation helper had no lifecycle caller, review progress was not durable/dispatch-bound, Browser network evidence could be child self-report; R-007, AC-06–AC-12 | exact runner `20260727T123951Z-4731cce565`: `turn.completed`, exit 0, valid result, stopped tree |
| A-010 | yes | review/r007-current-diff-strong | `gpt-5.6-terra` | xhigh | completed; `ESCALATE`, high confidence | Found global ignored-path enumeration/buffering before v2 scope filtering; R-008, T-001, AC-01/B-008 | exact runner `20260727T133537Z-9b70e32611`: `turn.completed`, exit 0, valid result, stopped tree |
| A-011 | yes | review/r009-current-diff-sol-high | `gpt-5.6-sol` | high | completed; `ESCALATE`, high confidence | Found missing specification-lineage partition in the workspace-private review ledger and stale spec receipts; R-010, AC-09/10 | exact runner `20260727T144709Z-2746cc0f90`: `turn.completed`, exit 0, valid result, stopped tree |
| A-012 | yes | review/r010-lineage-current-diff-balanced | `gpt-5.6-terra` | medium | completed; `ACCEPT`, no actionable findings | Independently verified current R-010 recovery, lineage, containment, Windows, version/docs and package diff; release gates only remain | exact runner `20260727T151631Z-3d1dfb85e4`: `turn.completed`, exit 0, valid result, stopped tree |

Pre-spawn dispatch failures (not included in created count): (1) one initial A-009 attempt omitted the required paired search-fallback source while supplying the expected model-map SHA; runner rejected it before agent creation, after which the exact review dispatch was corrected; (2) the first Sol/high attempt after R-008 was rejected before agent creation because the new progress ledger prohibited the intended sequential R-007 → R-008 epoch transition.

## 12. Execution and validation log

### 2026-07-27 — discovery and R-001 draft

- Changed: создана отдельная спецификация, потому что существующий `BUILD.md` относится к другой незавершённой задаче.
- Routing: discovery packaged map SHA-256 `3f9eceafea582baa2394a0c9744c0dbfc260b4daeb37475aca3f1c611e007701`; A-001 exact Spark/low result invalid, circuit breaker → targeted root recovery.
- Primary signal: not met.
- Validation: repository baseline clean; implementation checks pending.
- Minimality decision: reuse recovery/runner/policy owners, no new dependency.
- Review: readiness critics pending.
- Version: patch `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: fresh high-risk critics, Ready gate, TDD implementation, progressive review, publication.

### 2026-07-27 — product/UX critique and R-002

- Changed: automatic authority расширена на один exact same-scope recovery target; Browser fallback evidence сделан обязательным.
- Routing: A-002 exact `openbuild_review_balanced`, `gpt-5.6-terra`/medium/read-only, completed valid.
- Primary signal: not met.
- Validation: specification consistency audit; implementation pending.
- Minimality decision: reuse existing owner-private recovery grant, add no dependency.
- Review: product/UX `GAPS`, оба finding применены; architecture/security и strong closure pending.
- Version: patch `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: R-002 complementary critic and closure.

### 2026-07-27 — architecture/security critique and R-003

- Changed: removed inferred writer authority; added `task-relevant-v2`/legacy snapshot policy and 2.4.1 reader floor; isolated browser predicate; progress-based review cycle termination.
- Routing: A-003 exact `openbuild_review_balanced`, `gpt-5.6-terra`/medium/read-only, completed valid.
- Primary signal: not met.
- Validation: specification/repository owner audit; implementation pending.
- Minimality decision: version existing private source schema and reuse current capture/revalidation owners.
- Review: architecture/data/security `GAPS`, all four findings applied; strong closure pending.
- Version: patch `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: fresh R-003 strong closure.

### 2026-07-27 — strong closure critique and R-004

- Changed: defined `openbuild.review-progress.v1`, stable finding keys and strict runner-owned `openbuild.browser-qa.v1` receipt.
- Routing: A-004 exact `openbuild_review_strong`, `gpt-5.6-terra`/xhigh/read-only, completed valid.
- Primary signal: not met.
- Validation: specification/repository owner audit; implementation pending.
- Minimality decision: two pure executable owner contracts inside existing runner; no browser dependency or new state registry.
- Review: Strong `GAPS`, both technical findings applied; terminal closure pending.
- Version: patch `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: fresh R-004 terminal closure.

### 2026-07-27 — terminal closure critique and R-005

- Changed: Browser substitute теперь runner-owned и bound к current revision/diff/command/scenarios/nonce/process с replay/tamper negatives.
- Routing: A-005 exact `openbuild_review_sol_high`, `gpt-5.6-sol`/high/read-only, completed valid.
- Primary signal: not met.
- Validation: specification/repository owner audit; implementation pending.
- Minimality decision: generic subprocess/receipt lifecycle в существующем runner, project-native harness остаётся внешним входом.
- Review: Sol/high `GAPS`, единственный technical finding применён; fresh R-005 closure pending.
- Version: patch `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: fresh current-revision terminal closure, затем implementation.

### 2026-07-27 — R-005 Ready closure

- Changed: normative requirements unchanged; status advanced to Ready after fresh closure.
- Routing: A-006 exact `openbuild_review_sol_high`, `gpt-5.6-sol`/high/read-only, completed valid.
- Primary signal: not met; implementation pending.
- Validation: source-map, decision, coverage and acceptance closure `COVERED`.
- Minimality decision: existing owner layers, standard library, no new dependency.
- Review: fresh Sol/high readiness closure, high confidence, no gaps/reopens.
- Version: patch `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: TDD implementation, progressive review, full validation and publication.

### 2026-07-27 — implementation step-1 capability escalation

- Changed: no workspace implementation edits.
- Routing: A-007 exact `openbuild_implementation_balanced`, Terra/medium/workspace-write; configured zero-write trigger; semantic rejection/checkpoint invalidation complete, registry vacant; Strong/xhigh step 2 approved.
- Primary signal: not met.
- Validation: `git status` confirmed only root-owned specification before rejection.
- Minimality decision: unchanged.
- Review: not started.
- Version: unchanged `2.4.0`.
- Commit: not created.
- Remaining: Strong writer on unchanged R-005/allowlist.

### 2026-07-27 — implementation deadline, root completion and R-006 validation delta

- Changed: A-008 produced the allowed M1/M2 diff but missed its immutable 15-minute deadline. Root cancelled the creation-bound tree, verified registry vacancy, ran the full recovery module, found 15 false-green failures, repaired legacy policy fixtures/reader-floor expectations, strengthened review finding/progress and Browser receipt verification, and added release surfaces for `2.4.1`.
- Continuation: no permission prompt and no replacement writer. Existing root authority completed the attributable diff after the stopped-tree/vacancy audit.
- Validation: `scripts.test_recovery_state` 75/75; `scripts.test_agent_runner` 160/160 (4 skipped platform fixtures); `scripts.test_validate_package` 177/177; Browser substitute subprocess smoke green; package validator and `git diff --check` green.
- Package-wide finding: two separate 586-test runs each completed 584 tests but hit different transient Windows file locks in unrelated coordinator fixtures. Every exact failed test passed in isolation. R-006 adds bounded retry for mutable coordinator replace on Win32 `5/32/33`; `test_project_runtime` then passed 23/23.
- Primary signal: implementation behavior proven; one clean package-wide run, staged gate, review and remote publication remain.
- Minimality decision: one existing project-state publish owner, two-second bounded retry, no dependency, no blanket suppression, no change to immutable publication or non-transient failure semantics.
- Review: current-diff progressive review pending.
- Version: `2.4.0` → `2.4.1`.
- Commit: not created.
- Remaining: clean wide validation, current R-006 review, staged commit gate, commit/push/tag/release/remote smoke.

### 2026-07-27 — A-009 review remediation and R-007

- Review: A-009 exact Balanced/medium completed with `ESCALATE`, high confidence, on full-diff digest `4749b3502c38391483dbe9e0e39485f388a0c7a39b586c4baa5452bfaf7b2734`. Accepted finding keys: continuation production caller `525f77bdc45711dffa9479b334378ce8fe6280ff7311b09acd177e83f18ace94`, durable review dispatch owner `e41f45590880c19a209960341d1be220c391dcd1aadf8d52760e275a1a4e3472`, independent Browser network containment `4f5d4d8ddf9cbc628202e4c665bd013fc5cf23cc33ae2729ac1d536e84e07647`.
- Changed: `_record-root-completion` now durably emits a root-audit-bound automatic continuation action; every reviewer CLI dispatch requires canonical progress inputs and atomically appends an owner-private digest ledger after compare-and-swap consultation; Browser substitute rejects project/child network self-report and fails closed before child execution unless an independent guard attaches while the Windows child is suspended.
- Validation: focused R-007 contract tests 7/7; exact previously affected lifecycle tests 8/8; full `scripts.test_agent_runner` 163/163 with 4 platform skips. Package validator, full suite, fresh Strong review and staged/release gates pending.
- Minimality decision: existing recovery private state root, workspace lock, standard library and Windows suspended/Job lifecycle reused; no workspace review artifact, browser dependency, firewall mutation, force-unlock or new writer.
- Version: remains `2.4.1`.
- Commit: not created.
- Remaining: package/static validation, clean full suite, fresh Strong current-diff review, staged commit gate and publication.

### 2026-07-27 — A-010 Strong finding and R-008

- Review: A-010 exact Strong/xhigh completed with `ESCALATE`, high confidence. Finding `0a96b3f82e61a35f7217a1402bda834b88f17c5c0062c877dbf4fff46dbe8537` showed that v2 filtered ignored paths only after global `git ls-files --others --ignored` output had already been buffered.
- Changed: `task-relevant-v2` now minimizes overlapping allowed roots, converts them to literal top-level pathspecs, batches argv to 16 KiB, asks Git to collapse fully ignored directories, rejects any returned outside-scope path and enforces record bounds while parsing. `full-ignored-v1` alone retains the global query. The regression fails if v2 omits the pathspec separator or literal allowed path.
- Validation: R-008 policy regressions 4/4; full recovery module 75/75; recovery package mutation contract and package validator green; `git diff --check` green. One earlier full R-007 suite attempt failed a transient parallel-guardian liveness assertion, its isolated rerun passed, and the following full R-007 suite passed 590/590 with 9 platform skips. The fresh R-008 full suite also passed 590/590 with 9 platform skips in 577.930 seconds.
- Minimality decision: changed the existing snapshot owner and its validator only; no cache cleanup, new dependency, global memory copy, or legacy behavior rewrite.
- Version: remains `2.4.1`.
- Commit: not created.
- Remaining: Sol/high current-diff review, staged gate and publication.

### 2026-07-27 — review-epoch owner fix and R-009

- Primary signal: the first Sol/high dispatch after R-008 failed before spawn with `review progress specification revision drifted`, reproducing the review-ceiling interruption class despite a new diff, changed validation evidence and a newly closed finding.
- Changed: `review_progress_decision` now accepts only a strictly advancing specification revision paired with a changed full-diff digest; same-diff revision churn and backward/non-advancing revisions fail closed, while all finding-closure, validation/AC and immutable-diff exhaustion checks remain active.
- Validation: the initial focused invocation used an incorrect unittest class name and failed before running the target test; the corrected exact regression passed 1/1. Full `scripts.test_agent_runner` passed 163/163 with 4 platform skips; `scripts.test_validate_package` passed 177/177; package validator and `git diff --check` passed. The fresh R-009 full suite passed 590/590 with 9 platform skips in 582.652 seconds.
- Minimality decision: changed the existing canonical progress-decision owner and its focused unit contract only; no ledger reset, deletion, manual registry edit, permission prompt or retry-ceiling bypass.
- Version: remains `2.4.1`.
- Commit: not created.
- Remaining: Sol/high current-diff review, staged gate and publication.

### 2026-07-27 — A-011 lineage finding and R-010

- Review: A-011 exact Sol/high completed with `ESCALATE`, high confidence. High finding `7c62f525dafa77f8d7a7e15d24f1104e0ed2b5d9cdc8f8607f5e9a06398921f6` proved that the repository-wide latest ledger entry would reject a later unrelated Build at R-001. Low finding `1017bc7d9f5b9f42f25a68ede506a93e89828fd647ae1c31bc263eb61726b2ff` identified stale source-map and milestone receipts.
- Changed: each new Build specification now receives a stable random 64-hex lineage digest. Canonical progress is `openbuild.review-progress.v2`; dispatch counts and compares only entries with that lineage. Existing v1 entries remain digest-verified/readable but cannot block a v2 lineage. Same-lineage revision/diff/finding/validation ceilings remain fail-closed. Source map and M1/M2 receipts are synchronized to R-010/A-011.
- Red signal: the A-011 reproduction `previous task R-009 → unrelated task R-001` failed before dispatch; a new regression requires the unrelated lineage to receive `first-review` in the same workspace.
- Validation: exact R-010 progress/lineage tests passed 3/3; full `scripts.test_agent_runner` passed 163/163 with 4 platform skips; `scripts.test_validate_package` passed 177/177; package validator and `git diff --check` passed. The fresh R-010 full suite passed 590/590 with 9 platform skips in 618.203 seconds.
- Minimality decision: versioned the existing canonical progress record and filtered the existing private ledger in place; no ledger deletion/reset, new registry, dependency or workspace state.
- Version: remains `2.4.1`.
- Commit: not created.
- Remaining: fresh high-route current-diff review, staged gate and publication.

### 2026-07-27 — A-012 fresh R-010 review acceptance

- Review: A-012 exact Balanced/medium completed with `ACCEPT`, no actionable current-diff findings. It independently verified lineage partitioning, legacy v1 readability, same-lineage ceilings, scoped ignored inventory, continuation authority, Browser fail-closed containment, bounded Windows retry and synchronized `2.4.1` release surfaces.
- Routing: fresh high-risk epoch began at configured step 1 after the material R-010 remediation; `stop_on_success=true` closed the route, so Strong/Sol were not dispatched on the accepted immutable diff.
- Validation: reviewer-local package validator and `git diff --check` passed. Its combined unittest attempt could not create temporary directories inside the read-only sandbox; the root-owned fresh 590/590 R-010 suite remains the primary executable signal.
- Version: remains `2.4.1`.
- Commit: not created.
- Remaining: staged commit gate, release commit, push, annotated tag, GitHub Release and remote install/smoke.

### 2026-07-27 — staged release gate

- Validation: the exact task-owned candidate was staged; `git diff --cached --check` and `python scripts/validate_package.py --commit-gate` passed. AC-13 is complete.
- Scope: 18 task-owned files, including this durable specification; no unrelated workspace changes were staged.
- Version: staged manifest, changelog and both README pins agree on stable `2.4.1`.
- Commit: pending.
- Remaining: commit, push, annotated tag, GitHub Release and remote install/smoke.
