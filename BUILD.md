# Build: Наблюдаемая маршрутизация моделей OpenBuild

- Status: In progress
- Last updated: 2026-07-13
- Original request: Выяснить, почему при `$openbuild:build` не наблюдаются смена reasoning effort, работа профилей на Terra/Luna и расход отдельного пула Spark preview route, а также определить необходимые шаги и долговечные инструкции.
- Primary signal: Build автоматически классифицирует phase, implementation mode и risk, запрашивает точный named custom agent для search/fast/balanced/strong implementation и review, сохраняет TDD/minimality/single-writer/review gates на каждом tier, эскалирует только по evidence и честно отделяет configured route от ненаблюдаемой runtime metadata.
- Review baseline: `main@7e29e4e085a557a691abe43011973b8743cb20ea`, исходный status clean (`## main...origin/main`), tag `v0.4.0`.
- Workflow target: Complete
- Starting phase: implementation
- Specification revision: R-009
- Complexity: high — поведение пересекает plugin workflow, runtime capability schema, пользовательскую конфигурацию моделей, отдельный usage pool и fail/fallback semantics.
- Implementation mode: TDD-first — меняются routing/validation contracts; исходный red сигнал требует risk-matched writer tiers, evidence-only escalation и сохранение всех существующих code-writing gates.
- Version impact: major — контракт маршрутизации implementation writer изменён с strongest-only на risk-matched tiers; authoritative manifest, CHANGELOG и обе README синхронизированы на development version `1.0.0`, опубликованным release остаётся `v0.4.0`.
- Routing mode: configured-profiles
- Discovery mode: delegated — effective model/tier неизвестны.
- Search usage route: generic-subagent — адресный profile selector в доступной schema отсутствует; separate-pool profile не мог быть доказан, circuit breaker открыт для текущего Build-run.
- Implementation model route: risk-matched profiles — fast/balanced/strong routes выбираются по milestone risk; missing metadata не блокирует low/medium, high/critical сохраняют подтверждённый floor.

## 1. Outcome

### Problem

Семь пользовательских TOML-профилей существуют и задают разные модели и reasoning effort, но текущий orchestration interface принимает только `task_name`, `message` и `fork_turns`. Наличие профиля не равно его выбору. OpenBuild 0.4.0 является набором workflow-инструкций и не содержит исполняемого маршрутизатора, поэтому generic spawn не гарантирует Terra, Luna, Sol или Spark и не даёт доказательств отдельного billing pool.

Дополнительно ожидаемое распределение ролей не означает, что все модели должны появляться в каждом run: Luna настроена только для low-risk fast review; Terra — для fallback search и balanced review; Sol — для strongest implementation и strong review; Spark — для separate-pool search.

### Desired behavior

1. До первого repository lookup Build проверяет, доступен ли адресный selector custom-agent role и видны ли требуемые profiles.
2. Каждая делегация указывает точное имя профиля, а не только свободное имя задачи.
3. Setup выполняет безопасный smoke-test профилей и фиксирует observed role/model/reasoning/pool result.
4. Каждый run записывает фактический route, fallback/circuit-breaker и ограничения; отсутствие метаданных никогда не маскируется как успешное переключение.
5. Reasoning effort выбирается по роли и риску и проверяется на дочернем thread, а не по неизменному индикатору root session.
6. Если Build ждёт выбора пользователя, каждый checkpoint/final дословно воспроизводит ID вопроса, все варианты, последствия, рекомендацию и короткий формат ответа; ссылка на specification не заменяет самодостаточный вопрос.
7. User-facing diagnostics и вопросы сохраняют смысловой паритет в `README.md`/`README.ru.md`, отвечают на языке пользователя и остаются читаемыми как plain Markdown без зависимости от визуального UI.

### In scope

- Контракт capability preflight и адресного profile selection.
- Проверка Spark preview route, Terra, Luna и strongest writer через bounded smoke tests.
- Наблюдаемый routing/usage record и понятные сообщения о fallback/blocking.
- Инструкции для `AGENTS.md`, Build skill и setup/reload flow.
- Автоматическая валидация текстового контракта и, где runtime позволяет, интеграционный spawn probe.
- Контракт самодостаточного отображения blocking questions в user-facing сообщении.

### Out of scope

- Скрейпинг приватной usage-страницы или вычисление биллинга по имени модели.
- Принудительный расход токенов ради видимости без полезной роли или smoke-test цели.
- Изменение Codex backend, UI или schema `spawn_agent` из этого репозитория.
- Дальнейшая запись в `~/.codex/agents`, `~/.codex/config.toml` или включение telemetry без отдельного разрешения пользователя; текущие fast/balanced profiles и balanced root применены по явному «давай сделаем всё обсужденное».
- Реализация в режиме `$openbuild:build new`.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Plugin boundary | `plugins/openbuild/.codex-plugin/plugin.json:21` | Plugin экспортирует skills directory; собственного MCP/router runtime нет. | Инструкция не может добавить отсутствующий параметр tool schema. |
| Build modes | `plugins/openbuild/skills/build/SKILL.md:7` | `setup-models` — декларативный режим skill. | Setup должен опираться на возможности host runtime. |
| Setup contract | `plugins/openbuild/skills/build/SKILL.md:188` | Требуются selector/profile discovery, permission перед записью и observed verification после reload. | Существующие TOML остаются `configured but unverified`. |
| Routing proof | `plugins/openbuild/skills/build/references/model-routing.md:7` | Model switch допустимо заявлять только по spawn/profile/runtime evidence. | Имя task/thread не доказывает модель или экономию. |
| Search order | `plugins/openbuild/skills/build/references/model-routing.md:18` | Separate pool должен пробоваться первым, затем fallback/explorer/generic/root. | Spark не гарантирован, если selector недоступен или breaker открыт. |
| Profile roles | `plugins/openbuild/skills/build/references/model-routing.md` | Профили адресуются как `openbuild-search-*`, `openbuild-review-*` и три `openbuild-implementation-*` tiers. | Model IDs внутри профилей не являются agent names; Build выбирает named role по phase/risk. |
| Verification | `plugins/openbuild/skills/build/references/model-routing.md:146` | После reload нужны discoverability и observed selection каждого profile. | Файловой проверки недостаточно. |
| Runtime tests | `scripts/validate_package.py` и `scripts/test_validate_package.py` | Валидатор и mutation tests фиксируют fast/balanced/strongest, unknown-metadata rule, evidence-only escalation и high/critical floors, но не выполняют spawn. | Статический contract защищён; effective routing проверяется отдельно после reload. |
| Validation policy | `CONTRIBUTING.md:42-57`, `scripts/validate_package.py:748-753` | Канонические команды — `python -m unittest discover -s scripts -p "test_*.py" -v` и `python scripts/validate_package.py`; валидатор не принимает package path. | Milestone checks должны использовать поддерживаемый CLI и realistic routing fixture/forward-test. |
| Version policy | `CONTRIBUTING.md:16-31`, `plugins/openbuild/.codex-plugin/plugin.json:3` | Manifest — authoritative source; breaking contract требует major и синхронизацию CHANGELOG/README. | Development surfaces синхронизированы на `1.0.0`; published release остаётся `v0.4.0`. |
| Package hygiene/version gate | `scripts/validate_package.py` | Normal validator сканирует root `BUILD.md`, запрещает committed fixed model slugs/personal absolute paths и требует version bump при pending package paths. | Development bump выполнен; normal validator проходит, commit gate проверяется после точного staging. |
| Root config | `~/.codex/config.toml:1` | Future tasks используют balanced root; текущая task была запущена до изменения и сохраняет session-start strongest/high-effort effective route. | Изменение root и новых profiles требует новой task/session для runtime verification. |
| Spark profile | `~/.codex/agents/openbuild-search-separate.toml:1` | Spark preview route, `low`, read-only. | Профиль существует, но selection не доказан. |
| Fast/balanced writers | `~/.codex/agents/openbuild-implementation-fast.toml`, `~/.codex/agents/openbuild-implementation-balanced.toml` | Добавлены low-risk Direct и medium contained writer profiles с `workspace-write`. | Новые task/session могут выбирать minimum sufficient writer tier. |
| Luna profile | `~/.codex/agents/openbuild-review-fast.toml:1` | Luna назначена только low-risk review с effort `low`. | В high-risk run её отсутствие может быть правильным. |
| Strong profiles | `~/.codex/agents/openbuild-implementation-strongest.toml:1`, `~/.codex/agents/openbuild-review-strong*.toml:1` | Sol назначена writer/reviewer с `xhigh`, `high`, `max`. | Reasoning должен меняться только при выборе этих профилей. |
| Current spawn schema | runtime capability текущей сессии | Доступны только `task_name`, `message`, `fork_turns`; `agent_type/profile/model/model_reasoning_effort` отсутствуют. | Это непосредственный owner-layer blocker адресного routing. |
| Local runtime | `codex --version`, `codex features list` | `codex-cli 0.144.0-alpha.4`, `multi_agent` stable/true; `multi_agent_v2` выключен и under development. | Multi-agent включён, но текущая exposed schema всё равно не даёт selector. |
| Official contract | [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) | Standalone TOML profiles поддерживают `model` и `model_reasoning_effort`; custom agent определяется полем `name`. | Нужен именно выбор agent name и новый session/reload после конфигурации. |

### Source of truth

Runtime tool schema и observed spawn metadata — источник истины для фактического выбора профиля. TOML — источник желаемой конфигурации. Build skill — источник policy/order, но не доказательство выполнения. Usage dashboard может быть вторичным подтверждением расхода, но не является доступным или допустимым источником для автоматического workflow.

### Gap

OpenBuild описывает правильную лестницу, но не имеет механизма выбрать profile через текущий generic `spawn_agent` и не имеет executable test, который провалится при невыбранном profile. Поэтому workflow честно может уйти в generic/root fallback, а пользователь не увидит Terra/Luna/Spark или изменение дочернего reasoning.

## 3. Decision memory

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | routing.model-usage-policy | user | resolved | Должен ли каждый Build-run использовать все модели или выбирать их по роли/риску? | Адаптивно по роли и риску; все профили обязательно проверяются только setup smoke matrix. | Ответ пользователя 2026-07-12. | Нет искусственного fan-out и расхода quota ради индикатора. |
| D-002 | routing.readonly-missing-selector | user | superseded | Что делать с discovery/spec/review, если addressable selector недоступен? | Заменено D-011: честный configured/unknown fallback для low/medium без универсального blocker. | Новое решение пользователя 2026-07-13. | История исходного stop-policy сохранена, актуальное поведение задаёт D-011. |
| D-003 | config.write-scope | user | resolved | Где хранить model profiles? | user-scoped `~/.codex/agents` | Семь профилей уже находятся в пользовательской области; project profiles отсутствуют. | Model IDs не коммитятся в OpenBuild repository. |
| D-004 | observability.private-usage | technical | resolved | Что считать доказательством separate-pool route и фактического расхода? | Официальная документация подтверждает отдельный limit Spark; trusted runtime selection подтверждает выбранный route; величина/декремент расхода остаётся `unobservable`, если runtime её не сообщает. Dashboard — только secondary manual signal. | [Codex pricing](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan) прямо описывает отдельный Spark usage limit; skill запрещает скрейпинг/догадки о private usage. | Routing проверяем без ложного заявления о величине списания. |
| D-005 | runtime.owner-boundary | technical | resolved | Может ли одна инструкция исправить отсутствие selector? | Нет; требуется runtime/surface с addressable custom agents. | Текущая tool schema не имеет нужного параметра. | Spec не обещает невозможное изменение prompt-only способом. |
| D-006 | observability.record-lifecycle | technical | resolved | Где хранить routing record и как долго? | В routing section/execution log текущего task specification; краткий summary обязателен в каждом user-facing checkpoint/final. Отдельная глобальная telemetry-база не создаётся. | Specification уже является durable resumable artifact Build. | Record живёт и удаляется вместе с task specification, доступ наследует repository permissions. |
| D-007 | observability.metadata-provenance | technical | resolved | Можно ли считать текст дочернего агента доказательством модели/effort/pool? | Нет; только runtime/tool-generated selected-role envelope или подтверждённая effective config. Self-report сохраняется как недоверенный результат probe. | Иначе агент может заявить произвольную модель. | Исключается false positive. |
| D-008 | interview.self-contained-options | user | resolved | Как показывать вопросы, когда Build ждёт решение? | В каждом user-facing checkpoint/final полностью показывать ID, взаимоисключающие варианты, последствия, рекомендацию и формат ответа; не отсылать пользователя только к файлу или кодам. | Предыдущий final ожидал `1a 2a`, но не воспроизвёл варианты; пользователь указал на дефект 2026-07-12. | Вопросы становятся самодостаточными и на них можно ответить без чтения скрытого commentary/specification. |
| D-009 | implementation.current-run-route | user | superseded | Как продолжить текущий `full` run, если custom profiles настроены, но runtime не даёт адресно выбрать или наблюдать strongest writer? | Заменено D-010/D-011. | Пользователь принял native risk-matched routing 2026-07-13. | Универсальный blocker удалён; risk floor остаётся обязательным. |
| D-010 | implementation.routing-strategy | user | resolved | Как автоматически выбирать модели без MCP/exec support burden? | Native custom agents; Build классифицирует phase/risk и выбирает fast, balanced или strong/strongest named profile. | Пользователь принял рекомендацию 2026-07-13. | Пользователь пишет только `$build <feature>`; model IDs остаются user-scoped. |
| D-011 | observability.missing-metadata | user | resolved | Блокирует ли отсутствие trusted model metadata реализацию? | Low/medium могут продолжить через exact configured named profile со статусом `unknown`/`unobservable`; high/critical требуют подтверждённый floor. | Пользователь принял рекомендацию 2026-07-13. | Нет ложных model/pool claims и нет ненужного universal stop. |
| D-012 | implementation.method-preservation | user | resolved | Можно ли менять model routing без потери существующих методик написания кода? | Ready, owner-layer, TDD red→green, minimality, single-writer, root handoff, validation, versioning и progressive review сохраняются на каждом tier. | Явное уточнение пользователя 2026-07-13. | Экономия достигается выбором tier и контекста, не ослаблением engineering gates. |

## 4. User scenarios

### Primary scenario

1. Пользователь запускает `$openbuild:build setup-models` после reload/new session.
2. Build перечисляет discoverable profile names и effective settings без секретов.
3. Build адресно запускает короткие probes с `fork_turns: none` и синтетическим payload без repository/conversation/customer context: read-only для Spark, Terra и Luna; strongest writer получает пустую lease и обязан вернуть marker без изменения файлов.
4. Для каждого probe сохраняется requested profile, observed profile/model/reasoning, sandbox, pool evidence и результат.
5. Следующий `$openbuild:build new|run|full` выбирает профиль по роли/риску, добавляет routing record в specification и показывает пользователю компактный summary: `phase | requested profile | selected role | observed model/effort | pool evidence | status | fallback/breaker | record path`.

### Errors and edge cases

- Selector отсутствует -> не пытаться выдавать generic spawn за custom profile; low/medium может продолжить только через exact configured profile с `unknown`/`unobservable`, а high/critical останавливается без подтверждённого required floor по D-011.
- Profile не discoverable после reload -> `configured but unverified`, предложить точную проверку пути/name/schema.
- Spark unavailable/quota/entitlement failure -> открыть breaker на run, зафиксировать runtime error без догадок о балансе, перейти по выбранной fallback policy.
- Observed model/reasoning не совпадает с TOML -> probe failed; не продолжать profile-dependent implementation.
- Runtime не возвращает model metadata, но подтверждает exact selected role -> pool/model claim остаётся ограниченным подтверждённой конфигурацией; dashboard не скрейпится.
- Luna не подходит по risk floor -> не запускать её только ради расхода; setup smoke test остаётся доказательством работоспособности профиля.
- Root reasoning indicator не меняется -> UI должен направлять пользователя в child thread/routing record, потому что root session сохраняет собственные settings.
- Runtime envelope неполон -> записать различающиеся поля как `unknown` или `unobservable`, не подставлять self-report дочернего агента.
- Probe не завершён за 60 секунд -> один раз отменить/прервать, записать `timeout` и partial metadata, открыть breaker для соответствующего route; повтор в том же setup-run запрещён.
- Blocking question существует только в specification, но не полностью показан пользователю -> checkpoint считается невалидным; Build обязан повторить полный вопрос, а не ждать коды ответа.

## 5. Requirements and acceptance criteria

- [ ] AC-01: preflight до repository search фиксирует наличие/отсутствие addressable profile selector и discoverable exact profile names.
- [ ] AC-02: все profile-specific spawns передают exact agent name; task name не используется как суррогат selector.
- [ ] AC-03: setup smoke-test отдельно подтверждает Spark `low`, Terra `low/medium`, Luna `low`, Sol `high/xhigh/max` в пределах поддерживаемых runtime значений либо возвращает точный status из vocabulary: `selected`, `configured-unverified`, `unavailable`, `isolation-unavailable`, `quota-failed`, `timeout`, `cancelled`, `metadata-partial`, `failed`.
- [ ] AC-04: Spark probe отдельно фиксирует (a) официальный источник separate-limit mapping, (b) trusted runtime selection outcome и (c) usage amount как observed value либо `unobservable`; расход никогда не выводится из model slug или self-report.
- [ ] AC-05: каждый Build-run записывает machine-readable row `phase, requested_profile, selected_role, observed_model, observed_effort, pool_claim, provenance, status, fallback, breaker, limitation` в текущую specification и показывает компактный user-facing summary со ссылкой на неё, включая early preflight failure/timeout.
- [x] AC-06: Build выбирает `openbuild-implementation-fast` для low Direct, `openbuild-implementation-balanced` для medium contained и `openbuild-implementation-strongest` для high/critical work; required risk floor нельзя понижать.
- [x] AC-07: отсутствие model/tier metadata записывается как `unknown`/`unobservable` и не блокирует exact configured low/medium route; high/critical остаются blocked без required strong/strongest route.
- [x] AC-08: документация объясняет, что Terra/Luna/Spark — специализированные маршруты, а не обязательные участники каждого run, согласно D-001.
- [x] AC-09: package validator и tests отклоняют Build package, который теряет capability preflight, exact role selection, observed verification или honest fallback contract.
- [ ] AC-10: там, где тестовый runtime раскрывает selector/metadata, integration probe с synthetic payload, `fork_turns: none`, одной попыткой и 60-second timeout воспроизводимо доказывает применение custom profile по runtime-generated envelope; иначе ограничение явно отделено от unit validation.
- [ ] AC-11: любой `Questions` checkpoint/final содержит для каждого blocking D-ID полный текст вопроса, 2–3 взаимоисключающих варианта с последствиями, рекомендацию и формат ответа; тест отклоняет сообщение, которое просит коды без показанных вариантов.
- [ ] AC-12: EN/RU documentation и fixture outputs содержат одинаковые routing statuses, последствия вариантов и recovery steps; вопрос остаётся понятным в plain-text rendering.
- [ ] AC-13: каждый profile smoke probe запускается только в отдельном task-owned `.tmp/openbuild-model-probe/<run-id>` workspace с runtime-enforced запретом чтения вне него; до/после сравнивается manifest/hash и любая неразрешённая мутация проваливает probe. Если такую изоляцию нельзя доказать, probe не запускается и получает `isolation-unavailable`.
- [ ] AC-14: реальный Questions checkpoint проверяется через ephemeral `codex exec` с `--output-last-message`; валидатор captured output проваливает negative case «коды ответа без предшествующих вариантов» и принимает полный canonical question block.
- [x] AC-15: writer escalation происходит только при росте scope/risk, insufficient confidence, deeper red/green signal, task-scoped validation failure или confirmed review finding; trivial work не создаёт лишний fan-out.
- [x] AC-16: все writer tiers используют одинаковые Ready, owner-layer, TDD, minimality, single-writer, handoff, validation, versioning и progressive-review contracts.

### Invariants

- Root остаётся владельцем product/architecture/specification/Git/final synthesis.
- Search/critics/review profiles остаются read-only; любой fast/balanced/strongest writer получает один и тот же bounded single-writer lease.
- Пользовательская конфигурация изменяется только по явному разрешению; текущий root default и два writer profile применены в рамках принятого пользователем плана.
- OpenBuild не обещает экономию, отдельный pool или смену модели без runtime/config evidence.
- Одновременно работает не более одного writer.
- Probe не наследует историю, repository contents или пользовательские данные и не просит агента сообщить собственную модель как evidence.

## 6. Technical boundaries

### Affected layers and contracts

- `plugins/openbuild/skills/build/SKILL.md` — обязательный preflight, explicit role selection, smoke verification и user-facing diagnostics.
- `plugins/openbuild/skills/build/references/model-routing.md` — формальный selector/observability/fallback contract.
- `plugins/openbuild/skills/build/references/code-discovery.md` — первая separate-pool попытка только через addressable profile.
- `scripts/validate_package.py` — статические обязательные tokens/ordering.
- `scripts/test_validate_package.py` — red/green coverage для новых contract clauses.
- Новый validator/fixture boundary для captured Questions output — структурная проверка D-ID, вариантов, последствий, рекомендации и reply format; exact filename выбирается при реализации рядом с существующими validators.
- `plugins/openbuild/skills/build/references/blindspot-protocol.md` и `spec-template.md` — единый self-contained interview/checkpoint contract без расхождения между specification и final response.
- `README.md`, `README.ru.md`, `CHANGELOG.md`, plugin version surfaces — синхронизация пользовательской инструкции и release impact.
- Codex runtime/surface — внешняя prerequisite: должен раскрывать addressable custom-agent selector и, для полной observability, selected role/model/effort metadata.

### Data and migration

Schema/data migration не требуется. Потребуется reload/new session для перечитывания user-scoped agent profiles и balanced root default. Девять TOML profiles сохраняются; дальнейшие изменения требуют нового разрешения или явного `setup-models`. Routing record хранится только в task specification, наследует её repository access/retention и удаляется вместе с ней; отдельное хранилище или бессрочный глобальный журнал не создаются.

### Security and privacy

Не читать и не печатать auth/session secrets, raw `.env` или приватный usage dashboard. Smoke probes используют новый пустой контекст, синтетический marker и отдельный task-owned workspace `.tmp/openbuild-model-probe/<run-id>`. Effective runtime permissions должны запрещать чтение вне probe workspace; отсутствие доказуемой deny-read/isolation capability даёт `isolation-unavailable` без запуска. До/после probe root сравнивает manifest/hash, а strongest-writer marker не разрешает файловых изменений. Diagnostic output содержит только profile name, model ID, effort, sandbox, подтверждённый pool label и redacted runtime error.

### Performance and concurrency

Smoke tests последовательные: одна попытка на profile, максимум 60 секунд, затем interrupt/cancel и запись partial outcome. Если runtime предоставляет token budget, используется минимальный поддерживаемый cap; если нет — `token_cap: unobservable`. Обычный Build использует параллельные read-only ветки только когда это полезно. Breaker исключает повторные неуспешные Spark attempts в одном run.

### Observability and errors

Routing record является обязательной таблицей в task specification с полями AC-05; допустимые неизвестные значения — только `unknown` (runtime не сообщил значение) и `unobservable` (surface не экспонирует класс данных). Источник provenance — `runtime-envelope`, `effective-config`, `official-doc`, `user-manual` или `none`; текст дочернего агента не является provenance. Каждый checkpoint/final повторяет компактный summary и ссылку на specification. `codex doctor --json` в текущей среде завершился timeout и не считается успешной проверкой discoverability.

### Versioning and release

Breaking routing contract получил development major bump `0.4.0 -> 1.0.0`: authoritative manifest, `CHANGELOG.md`, `README.md` и `README.ru.md` синхронизированы. Это не создаёт tag или release; последний опубликованный release остаётся `v0.4.0`. Rollback: вернуть plugin/version/docs к предыдущему контракту, не удалять user-scoped profiles, начать новую session и проверить legacy strongest-only route; task specifications остаются обычными repository artifacts.

## 7. Validation and review

- Primary signal: risk-matched contract выбирает fast/balanced/strongest writer, сохраняет одинаковые engineering gates, разрешает `unknown` metadata только для low/medium и повышает tier только по evidence.
- Red signal: focused `UsageRoutingContractTests` после добавления новых требований дал 2 failures — package не содержал risk-tier contract и evidence-only escalation. Отдельный unsupported module-path invocation завершился `ModuleNotFoundError` и не считается TDD red.
- Focused green: `python -m unittest discover -s scripts -p "test_*.py" -k UsageRoutingContractTests -v` — сначала 6/6, после review hardening 7/7.
- Wider green: canonical unit suite — 27/27 до review hardening; полный повтор после мутационных high/critical checks обязателен ниже в execution log.
- Targeted green: `python scripts/validate_package.py` — passed до review hardening; повтор обязателен после исправлений.
- Structure green: skill `quick_validate.py` и plugin `validate_plugin.py` — passed.
- Diff hygiene: `git diff --check` — passed до review hardening; повтор обязателен перед Git.
- Forward tests: low-risk README typo выбрал `openbuild-implementation-fast` без ceremonial red; medium parser bug выбрал `openbuild-implementation-balanced` с owner-layer TDD. Оба сохранили Ready/minimality/single-writer/handoff/validation/version/review и не эскалировали без evidence.
- Progressive review: initial strong-requested review returned `REVISE` for stale durable evidence and missing high/critical mutation locks; both were fixed. Fresh strong-requested closure review returned `ACCEPT` with high confidence and no actionable findings; observed tier remained `unknown`, context isolation limited.
- Minimality: используются native custom agents и существующие validators; собственный MCP/router/runner, production dependency и hosted support surface не добавлены.
- Runtime limitation: текущая callable spawn schema не раскрывает exact custom-agent selector или trusted model envelope. Новые user TOML и balanced root начинают действовать в новой task/session; реальное переключение и pool usage в этой task не заявляются.

## 8. Milestones

### M1. Risk-matched implementation contract

- Status: Complete
- Scope: fast/balanced/strongest routing, low/medium unknown-metadata rule, confirmed high/critical floors, evidence-only escalation, preserved coding methodology, deterministic validator/tests.
- Implementation mode: TDD-first.
- Writer lease: `root-only`; requested tier strong; session-start effective root configuration was strongest/high-effort, observed runtime envelope `unknown`; allowed paths were Build skill references, validator/tests, bilingual docs, manifest/changelog and this specification. Один writer, concurrent repository writers отсутствовали.
- Red: 2 expected routing-contract failures before production contract edits.
- Handoff: root reread the full task diff, ran focused then wider validation, and routed the diff to progressive review.
- Acceptance: AC-06, AC-07, AC-09, AC-15, AC-16.
- Version: synchronized `0.4.0 -> 1.0.0`; release/tag absent.
- Commit: Pending final closure and commit gate.

### M2. Native profiles and user guidance

- Status: Complete with runtime verification deferred to reload.
- Scope: added user-scoped fast/balanced writer TOMLs, changed future root default to balanced, documented three writer tiers and updated setup-model count, README/CHANGELOG/version surfaces.
- Implementation mode: Direct for authorized config/docs after M1 contract green.
- Minimality: native custom-agent TOML only; no MCP router/runner and no new dependency.
- Forward tests: low and medium hypothetical tasks selected the minimum sufficient tier and preserved all method gates.
- Acceptance: AC-08 plus configuration portion of AC-03.
- Limitation: current task cannot prove the new profiles were selected; new task/session and native selector metadata are required.
- Commit: repository portion Pending; user-scoped config is intentionally outside Git.

### M3. Runtime smoke matrix

- Status: Pending external/new-session signal
- Scope: bounded isolated selection probes for search, three implementation tiers and four review tiers; trusted selected-role/model/effort envelope when exposed.
- Excludes: dashboard scraping, inferred billing, custom router/runtime schema.
- Acceptance: remaining runtime portions of AC-01..05, AC-10, AC-13, AC-14.
- Stop condition: when selector or isolation metadata is unavailable, record `configured-unverified`/`isolation-unavailable`; do not claim model switch or token savings.

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome/success/scope | covered | technical decision | Primary signal включает user-facing summary, durable record и AC-01..10 | none |
| B-002 | actors/permissions/abuse | covered | technical decision | Root ownership; separate permission for user config; no secrets | none |
| B-003 | primary/alternate/error/retry/recovery | covered | technical decision | Scenario и error matrix; per-run breaker | none |
| B-004 | accessibility/localization/responsive UX | covered | technical decision | AC-12: EN/RU semantic parity и readable plain Markdown; responsive visual UI не принадлежит repo | validate bilingual fixtures/docs |
| B-005 | ownership/contracts/source of truth | covered | technical decision | D-005/D-007: runtime envelope/config/docs разделены; self-report недоверен | none |
| B-006 | data/migration/retention/deletion | covered | technical decision | D-006: record только в task specification, lifecycle наследуется | none |
| B-007 | security/privacy/trust | covered | technical decision | AC-13: isolated task-owned workspace, runtime deny-read proof, manifest/hash mutation check; no dashboard scraping | validate isolation or return `isolation-unavailable` |
| B-008 | performance/concurrency/idempotency | covered | technical decision | Bounded sequential probes; read-only parallelism; breaker | none |
| B-009 | integrations/timeouts/partial failure | covered | technical decision | One attempt/profile, 60-second timeout, cancel/partial status и breaker | none |
| B-010 | observability/support/rollout/rollback/docs | covered | technical decision | AC-05 summary/schema; compatibility matrix; explicit plugin/session rollback; D-002/AC-07 classified as breaking with major `0.4.0 -> 1.0.0` impact | none |
| B-011 | acceptance/testability/minimality/cost | covered | technical decision | Deterministic status/provenance vocabulary, bounded probe oracle, native mechanism first | none |
| B-012 | model usage policy | covered | product decision | D-001: адаптивная маршрутизация | none |
| B-013 | missing-selector behavior | covered | product decision | D-011: low/medium exact configured route с unknown metadata; high/critical stop | verify after reload |
| B-014 | runtime capability prerequisite | covered | technical decision | Compatibility release gate detects selector+metadata levels; repo cannot add missing selector | verify on new/reloaded compatible session |
| B-015 | self-contained question rendering | covered | technical decision | D-008, AC-11/14; ephemeral captured final + canonical/negative validator fixtures | run opt-in integration oracle |
| B-016 | current-run implementation authority | covered | product decision | D-009 superseded; root-only lease использовал session-start strongest/high-effort effective route | closure review |
| B-017 | risk-matched implementation tiers | covered | product decision | D-010, AC-06/15: native fast/balanced/strong profiles with evidence-only escalation | validate contract and forward-test |
| B-018 | method preservation across tiers | covered | product decision | D-012, AC-16: TDD/minimality/single-writer/handoff/review unchanged | run full validator and review |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Prompt claims routing without runtime proof | high/high | exact selector + observed record + tests | Handled in spec |
| Supported surface still hides model/effort metadata | medium/high | separate selected-role evidence from model/pool claims; bounded limitation | Open |
| Forced all-model fan-out wastes quota | medium/medium | D-001 adaptive routing | Handled |
| Несовместимая surface скрывает effective model metadata | medium/medium | D-011 honest unknown for low/medium; hard stop for high/critical | Handled in contract |
| Final просит коды без отображения вариантов | medium/high | D-008, AC-11 и validator fixture | Handled in spec |
| Writer probe читает или меняет активный workspace | medium/high | AC-13 isolation gate; no run when isolation is unprovable | Handled in spec |
| EN/RU diagnostics расходятся | medium/medium | AC-12 parity fixtures and review | Handled in spec |
| Spark entitlement/quota absent | medium/medium | breaker and honest fallback; no balance inference | Handled |
| User profiles drift from plugin expectations | medium/medium | setup smoke matrix after reload | Handled |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | product-UX/reliability-validation; strong requested, observed unknown | GAPS | user-facing summary, pool oracle, record schema, reproducible probes | Принято; D-004/D-006/D-007, AC-03..05/10 и R-002 закрывают gaps. |
| R-001 | architecture-data-security; strong requested, observed unknown | GAPS | context minimization, metadata authenticity, record lifecycle, resource cancellation, rollout/rollback | Принято; synthetic probes, provenance contract, lifecycle, timeout и compatibility gate добавлены в R-002. |
| R-003 | reliability-validation + product/architecture closure; strong requested, observed unknown | GAPS | localization applicability, probe filesystem isolation, captured question-render oracle, status consistency | Принято; AC-12..14, B-004/B-007/B-015 и Draft/R-004 закрывают gaps. |
| R-004 | product/UX + architecture/security + reliability/validation closure; strong requested, observed unknown | COVERED | None; all B-001..B-015 covered, AC-01..14 testable at specification level | Accepted with high confidence; Ready gate passed. |
| R-005 | architecture/runtime + reliability/readiness; strong requested, observed unknown | GAPS | Current-revision closure отсутствует; `Starting phase: implementation` противоречит D-009/B-016 до capability preflight. | Принято; R-007 переводит run в blind-spot critique, добавляет текущие repository validation/version/package-hygiene facts и требует свежий closure. |
| R-007 | product/UX + architecture/data/security + reliability/validation; strong requested, observed unknown | GAPS | Unsupported `Reconciliation` status; D-002/AC-07 breaking fallback был ошибочно классифицирован как minor. | Принято; R-008 использует допустимый `Draft` и major `0.4.0 -> 1.0.0`, не переоткрывая D-002. |
| R-008 | product/UX + architecture/data/security + reliability/validation closure; strong requested, observed unknown | COVERED | None; B-001..B-016 covered, D-001..D-009 resolved, AC-01..14 observable and fully mapped. | Accepted with high confidence; Ready restored, implementation remains capability-blocked. |
| R-009 | progressive diff review; strong requested, observed unknown, independent-context isolation limited | REVISE | stale execution record; high/critical floors not mutation-locked | Принято: sections 2/7/8/11 reconciled; validator tokens and four mutations added. Fresh closure pending. |
| R-010 | closure diff review; strong requested, observed unknown, independent-context isolation limited | ACCEPT | None; remediation, method preservation, bilingual docs and version surfaces verified | Accepted with high confidence; no actionable findings. |

## 10. Open questions

Blocking product questions:

- None.

Non-blocking assumptions:

- Профили остаются user-scoped; их exact model IDs могут меняться через отдельный `$openbuild:build setup-models` flow после официальной/runtime проверки.
- Spark preview route доступен только при соответствующем account entitlement; конфигурация файла сама entitlement не создаёт.

## 11. Execution and validation log

### 2026-07-12 — discovery и initial specification

- Changed: создан `BUILD.md`; implementation/config files не изменялись.
- Routing: generic-subagent; effective model/pool/effort unknown; separate profile не addressable в текущей spawn schema, breaker открыт.
- Primary signal: not met — controlled named-profile spawn невозможен через текущий tool contract.
- Validation: `codex --version` -> `codex-cli 0.144.0-alpha.4`; `codex features list` -> `multi_agent` stable/true; `codex doctor --json` -> timeout, failed validation.
- Minimality decision: native custom-agent support first; no custom router proposed at this revision.
- Review: R-001 и R-003 critics вернули GAPS; findings adjudicated в R-002/R-004. Fresh R-004 closure returned COVERED with high confidence; observed tier unknown.
- Version: not changed; no commit in `new` mode.
- Remaining: implementation через `$openbuild:build run BUILD.md`; до совместимого selector strongest-writer route остаётся blocked.

### 2026-07-12 — full implementation preflight

- Changed: workflow target переключён на `Complete`; implementation files не изменялись.
- Routing: setup profiles обнаружены в `~/.codex/agents`, но callable spawn schema не имеет profile selector; status `configured-unverified`, circuit breaker открыт для addressable routes в текущем run.
- Primary signal: not met — named-profile spawn matrix и trusted strongest-writer selection недоступны.
- Validation: `codex-cli 0.144.0-alpha.4`; root config requests effort `high`; implementation profile requests effort `xhigh`; effective current-session model remains unobservable.
- Minimality decision: native custom-agent mechanism first; не добавлять обходной router и не редактировать code generic worker.
- Review: not started; no implementation diff.
- Version: unchanged; commit not created.
- Remaining: D-009; implementation blocked: strongest coding route unproven.

### 2026-07-12 — repeated run preflight

- Changed: none; implementation/config files не изменялись.
- Routing: повторный run видит ту же selector-less spawn schema; configured profiles остаются unverified.
- Primary signal: not met.
- Validation: branch/HEAD unchanged; only task-owned untracked `BUILD.md`; `codex-cli 0.144.0-alpha.4`.
- Review: not started; no implementation diff.
- Version: unchanged; commit not created.
- Remaining: D-009; если повторный invocation означал 1a, reload/retry не экспонировал selector.

### 2026-07-12 — implementation route decision

- Changed: D-009 resolved as 1a; implementation/config files не изменялись.
- Routing: current run stopped; configured profiles remain unverified until a new selector-capable session/surface.
- Primary signal: not met.
- Validation: no implementation diff; Git branch/HEAD unchanged.
- Review: not started.
- Version: unchanged; commit not created.
- Remaining: start a new session/surface, verify addressable profiles, then run `$openbuild:build run BUILD.md`.

### 2026-07-12 — R-008 run reconciliation

- Changed: только `BUILD.md`; добавлены authoritative validation/version/package-hygiene evidence, исправлены неподдерживаемые validation commands и непереносимые durable markers, fallback contract классифицирован как major, текущая revision переведена в readiness critique. Test/production/config files не изменялись.
- Baseline: preserved `main@7e29e4e085a557a691abe43011973b8743cb20ea`; initial status clean; текущий task status содержит только untracked `BUILD.md`.
- Discovery: delegated generic subagents; observed model/tier/pool unknown; separate-pool selector не экспонирован, circuit breaker открыт для текущего run.
- Routing record:

| phase | requested_profile | selected_role | observed_model | observed_effort | pool_claim | provenance | status | fallback | breaker | limitation |
|---|---|---|---|---|---|---|---|---|---|---|
| implementation-preflight | `openbuild-implementation-strongest` | unknown | unknown | unknown | unknown | none | `configured-unverified` | none; D-009 stop | open | `spawn_agent` exposes only `task_name`, `message`, `fork_turns`; no trusted selected-role envelope |

- Primary signal: not met — controlled named-profile spawn и trusted strongest-writer selection недоступны.
- Validation evidence: `codex-cli 0.144.0-alpha.4`; `multi_agent` stable/true; `multi_agent_v2` under development/false; branch/HEAD unchanged; authoritative version `0.4.0`; canonical unit suite 26/26 passed; `git diff --check` passed; после portable wording `python scripts/validate_package.py` failed only на ожидаемом unchanged-version gate до implementation bundle и не заявляется как passed.
- Implementation: blocked — strongest coding route unproven; D-009/AC-06 applied; writer lease не выдавался, red test и production edits не запускались.
- Minimality: native selector remains the required owner mechanism; custom MCP/router и generic writer не добавлялись.
- Version: unchanged; no implementation commit can be created while writer routing is blocked.
- Readiness review: R-008 fresh closure `COVERED`, confidence high, requested strong/observed tier unknown; status restored to `Ready` without changing semantic revision.
- Remaining: новый selector-capable session/surface и capability preflight перед M1; текущий run останавливается по D-009/AC-06.

### 2026-07-13 — selector capability preflight

- Changed: только execution metadata в `BUILD.md`; semantic revision R-008, decisions, acceptance criteria и implementation files не изменялись.
- Baseline: preserved `main@7e29e4e085a557a691abe43011973b8743cb20ea`; текущий status содержит только task-owned untracked `BUILD.md`.
- Routing: профили `openbuild-search-separate`, `openbuild-search-fallback`, `openbuild-implementation-strongest` и `openbuild-review-*` обнаружены в user-scoped configuration, но callable `spawn_agent` schema по-прежнему принимает только `task_name`, `message`, `fork_turns`; addressable profile selector и trusted selected-role envelope отсутствуют. Separate-pool attempt имеет status `configured-unverified`; circuit breaker открыт.
- Runtime evidence: `codex-cli 0.144.0-alpha.4`; `multi_agent` stable/true; `multi_agent_v2` under development/false.
- Primary signal: not met — exact profile selection, observed role/model/reasoning и controlled strongest-writer lease недоступны.
- Implementation: blocked — D-009/AC-06 применены; writer lease, red test, production edits, review и commit не выполнялись.
- Version: unchanged (`0.4.0`); release action none.
- Remaining: запустить `$openbuild:build run BUILD.md` на session/surface, где `spawn_agent` адресно принимает custom-agent profile и возвращает trusted selection metadata.

### 2026-07-13 — current desktop-session run preflight

- Changed: только execution metadata в `BUILD.md`; semantic revision R-008, решения, acceptance criteria и implementation/config files не изменялись.
- Baseline: сохранён `main@7e29e4e085a557a691abe43011973b8743cb20ea`; текущий status по-прежнему содержит только task-owned untracked `BUILD.md`; tag на `HEAD` — `v0.4.0`.
- Instructions and ownership: repository/nested `AGENTS.md` отсутствуют, поэтому применён переданный пользователем global layer; `CONTRIBUTING.md`, `README.md`, manifest и validator подтверждают version/validation policy и отсутствие repository-owned host router/schema implementation.
- Discovery: две read-only generic-subagent ветки проверили repository policy/validation и runtime-contract ownership; observed model/tier/pool неизвестны. Адресные search profiles нельзя выбрать через callable schema, поэтому separate-pool и efficient-profile routes имеют status `configured-unverified`, circuit breaker открыт.
- Routing record:

| phase | requested_profile | selected_role | observed_model | observed_effort | pool_claim | provenance | status | fallback | breaker | limitation |
|---|---|---|---|---|---|---|---|---|---|---|
| search-preflight | `openbuild-search-separate` | unknown | unknown | unknown | unknown | effective-config | `configured-unverified` | generic read-only subagents after selector preflight | open | callable `spawn_agent` schema exposes no custom-agent profile selector or trusted selected-role envelope |
| implementation-preflight | `openbuild-implementation-strongest` | unknown | unknown | unknown | unknown | effective-config | `configured-unverified` | none; D-009 stop | open | strongest writer cannot be selected or observed through the callable schema |

- Runtime evidence: user-scoped profiles are present, but callable `spawn_agent` still accepts only `task_name`, `message`, `fork_turns`. A supplemental `codex --version` / feature probe was attempted and failed to start with `Access is denied`; it is recorded as failed validation and does not replace tool-schema evidence.
- Primary signal: not met — exact profile selection, trusted role/model/reasoning envelope, Spark route outcome and controlled strongest-writer lease remain unavailable.
- Validation: `git branch --show-current` -> `main`; `git rev-parse HEAD` -> preserved baseline SHA; `git status --short --branch` -> only `?? BUILD.md`; `git diff --check` and the explicit `BUILD.md` trailing-whitespace check passed. `python scripts/validate_package.py` returned non-zero only because the pending task artifact does not increase manifest version (`0.4.0 -> 0.4.0`); this expected pre-implementation gate is not claimed as passed. Unit tests were not rerun because no validator or implementation contract changed.
- Implementation: blocked by D-009/AC-06 and the strongest-writer protocol; writer lease, red test, production edits, progressive diff review, commit and push were not performed.
- Minimality: native addressable selector remains the required owner mechanism; repository-local router/MCP and generic-writer downgrade remain skipped.
- Version: unchanged (`0.4.0`); version impact remains planned major only if implementation becomes authorized and proceeds; release action none.
- Remaining: retry `$openbuild:build run BUILD.md` only on a session/surface whose callable spawn contract exposes exact custom-agent selection and trusted selection metadata.

### 2026-07-13 — risk-matched routing implementation

- Changed: Build skill and delegation/TDD/routing references now select fast, balanced or strongest implementation profiles by risk, preserve the same Ready/owner-layer/TDD/minimality/single-writer/handoff/validation/version/review gates, and escalate only on evidence. Validator/tests, bilingual docs, manifest and changelog were synchronized. User scope gained fast/balanced writer profiles and a balanced future root default.
- Baseline and lease: `main@7e29e4e085a557a691abe43011973b8743cb20ea`; `root-only` writer, strong requested, session-start strongest/high-effort effective configuration, runtime model envelope `unknown`; allowed files were the task specification, Build package/docs/tests/version surfaces and the two explicitly authorized user profiles plus safe root model keys. No concurrent repository writer.
- TDD red: focused routing suite initially failed two new assertions because the package lacked risk-matched tier selection and evidence-only escalation. An earlier unsupported module-path invocation failed with `ModuleNotFoundError` and was not counted as red.
- Focused green: `python -m unittest discover -s scripts -p "test_*.py" -k UsageRoutingContractTests -v` — 7/7 after adding independent mutations for confirmed-high and strongest-proven-critical floors.
- Wider green: `python -m unittest discover -s scripts -p "test_*.py" -v` — 28/28; `python scripts/validate_package.py` — passed; `git diff --check` — passed.
- Structural green: Build skill `quick_validate.py` — passed; plugin `validate_plugin.py` — passed; TOML parse — 10/10 files (nine OpenBuild profiles plus config).
- Forward tests: fresh low-risk typo scenario selected fast/Direct with no ceremonial red; fresh medium parser scenario selected balanced/TDD-first. Both retained the common method gates and did not escalate without evidence.
- Root handoff: root reread task-owned paths, verified focused then wider signals, synchronized development version `1.0.0`, and reviewed the complete diff. Latest published release remains `v0.4.0`; no tag/release action.
- Progressive review R-009: strong requested, observed tier `unknown`, limited context isolation, verdict `REVISE`. Findings were stale durable evidence and missing high/critical mutation locks; both were corrected before the 28/28 rerun. Fresh closure review pending.
- Closure review R-010: strong requested, observed tier `unknown`, limited context isolation, verdict `ACCEPT`, confidence high; no actionable findings. Reviewer independently reran routing 7/7, package validation and full-diff whitespace check.
- Minimality: native TOML custom agents only; no MCP router/runner, production dependency, provider, infrastructure or telemetry.
- Remaining limitation: current task cannot observe the newly configured profile selection or separate-pool decrement. Reload/new task is required; until runtime metadata exists, no model-switch or token-saving claim is made.
- Local plugin refresh: cachebuster helper temporarily changed manifest to `1.0.0+codex.20260712220137`; `codex plugin add openbuild@openbuild` could not start because `codex.exe` returned `Access is denied`. Manifest was restored to clean `1.0.0`; reinstall is not claimed and must be retried from a shell/session allowed to execute Codex.
