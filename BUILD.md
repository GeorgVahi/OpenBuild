# Build: Наблюдаемая маршрутизация моделей OpenBuild

- Status: In progress
- Last updated: 2026-07-13
- Original request: Выяснить, почему при `$openbuild:build` не наблюдаются смена reasoning effort, работа профилей на Terra/Luna и расход отдельного пула Spark preview route, а также определить необходимые шаги и долговечные инструкции.
- Primary signal: Build через отдельный host-runtime selector адресно выбирает canonical underscore custom-agent ID, а trusted dispatch envelope доказывает selected role/model/reasoning/sandbox до search/edit/review; repository tests одновременно отклоняют подмену selector полем `task_name`, проверяют guided migration legacy дефисных profiles и подтверждают реальный Spark-first search на совместимой entitled surface.
- Review baseline: `main@c02b34e7372a73f7d9a7fb2bf234a81c95a429f3`, исходный status clean (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: implementation — M3 native bootstrap
- Specification revision: R-014
- Complexity: high — поведение пересекает plugin workflow, runtime capability schema, пользовательскую конфигурацию моделей, отдельный usage pool и fail/fallback semantics.
- Implementation mode: TDD-first — меняются routing/validation contracts; исходный red сигнал требует risk-matched writer tiers, evidence-only escalation и сохранение всех существующих code-writing gates.
- Version impact: major — M3 repository bootstrap применил `1.1.1 -> 2.0.0`; tag/Release не создавались. M4–M6 остаются незавершёнными до host-runtime и end-to-end evidence.
- Routing mode: configured-profiles
- Discovery mode: delegated — effective model/tier неизвестны.
- Search usage route: generic-subagent — адресный profile selector в доступной schema отсутствует; separate-pool profile не мог быть доказан, circuit breaker открыт для текущего Build-run.
- Search routing receipt: `openbuild-search-separate`; dispatch `unavailable`; configured model `runtime-resolved Spark preview`; observed agent/model/pool `unknown`; result `failed`; fallback `selector-unavailable`; затем использован generic read-only subagent.
- Implementation model route: risk-matched profiles — fast/balanced/strong routes выбираются по milestone risk; missing metadata не блокирует low/medium, high/critical сохраняют подтверждённый floor.
- Bootstrap exception: пользователь явно разрешил выполнить M3 обычным Codex workflow вне self-blocked legacy writer gate, затем вернуться к Build. M3 writer `root-only`, observed model/tier `unknown`; исключение не распространяется на M4–M6.

## 1. Outcome

### Problem

Девять пользовательских TOML-профилей существуют и задают разные модели и reasoning effort, но их `name` использует дефисы, которые текущий runtime отклоняет. Одновременно orchestration interface принимает только `task_name`, `message` и `fork_turns`, не отделяя task label от custom-agent selector. Наличие профиля не равно его выбору. OpenBuild 1.1.1 является набором workflow-инструкций и не содержит host router, поэтому generic spawn не гарантирует Terra, Luna, Sol или Spark и не даёт доказательств отдельного usage pool.

Дополнительно ожидаемое распределение ролей не означает, что все модели должны появляться в каждом run: Luna настроена только для low-risk fast review; Terra — для fallback search и balanced review; Sol — для strongest implementation и strong review; Spark — для separate-pool search.

### Desired behavior

1. До первого repository lookup Build проверяет, доступен ли отдельный addressable custom-agent selector и видны ли canonical underscore profiles.
2. Каждая делегация передаёт точный underscore ID через отдельный host selector; `task_name` остаётся только task label и никогда не считается selection evidence.
3. Setup обнаруживает legacy дефисные profiles, показывает migration diff, создаёт canonical underscore profiles только после разрешения и не удаляет legacy files до успешного reload/smoke и отдельного подтверждения.
4. Host runtime разрешает profile по TOML `name`, применяет его `model`, `model_reasoning_effort` и `sandbox_mode`, а затем возвращает trusted selected-role/model/reasoning/sandbox envelope.
5. Setup выполняет безопасный smoke-test профилей и фиксирует observed role/model/reasoning/pool result.
6. Каждый run записывает фактический route, fallback/circuit-breaker и ограничения; отсутствие метаданных никогда не маскируется как успешное переключение.
7. Reasoning effort выбирается по роли и риску и проверяется на дочернем thread, а не по неизменному индикатору root session.
8. Если Build ждёт выбора пользователя, каждый checkpoint/final дословно воспроизводит ID вопроса, все варианты, последствия, рекомендацию и короткий формат ответа; ссылка на specification не заменяет самодостаточный вопрос.
9. User-facing diagnostics и вопросы сохраняют смысловой паритет в `README.md`/`README.ru.md`, отвечают на языке пользователя и остаются читаемыми как plain Markdown без зависимости от визуального UI.

### In scope

- Контракт capability preflight и адресного profile selection.
- Canonical underscore identifiers для всех search/implementation/review roles и управляемая migration legacy дефисных user profiles.
- Отдельный host-runtime request/response contract для custom-agent selector и trusted selection metadata.
- Проверка Spark preview route, Terra, Luna и strongest writer через bounded smoke tests.
- Наблюдаемый routing/usage record и понятные сообщения о fallback/blocking.
- Инструкции для `AGENTS.md`, Build skill и setup/reload flow.
- Автоматическая валидация текстового контракта и, где runtime позволяет, интеграционный spawn probe.
- Контракт самодостаточного отображения blocking questions в user-facing сообщении.

### Out of scope

- Скрейпинг приватной usage-страницы или вычисление биллинга по имени модели.
- Принудительный расход токенов ради видимости без полезной роли или smoke-test цели.
- Изменение Codex backend, UI или schema `spawn_agent` из этого репозитория.
- Repository-owned MCP/CLI adapter, child-process router или API workaround; host-runtime изменение оформляется как отдельный внешний deliverable того же end-to-end ТЗ.
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
| Profile roles | `plugins/openbuild/skills/build/references/model-routing.md` | Normative dispatch использует девять canonical underscore IDs; дефисные имена остаются только migration input. | `agent_name` выбирает profile, независимый `task_name` не является selector; Build выбирает named role по phase/risk. |
| Verification | `plugins/openbuild/skills/build/references/model-routing.md:146` | После reload нужны discoverability и observed selection каждого profile. | Файловой проверки недостаточно. |
| Runtime tests | `scripts/validate_package.py` и `scripts/test_validate_package.py` | Валидатор и mutation tests фиксируют fast/balanced/strongest, unknown-metadata rule, evidence-only escalation и high/critical floors, но не выполняют spawn. | Статический contract защищён; effective routing проверяется отдельно после reload. |
| Validation policy | `CONTRIBUTING.md:42-57`, `scripts/validate_package.py:748-753` | Канонические команды — `python -m unittest discover -s scripts -p "test_*.py" -v` и `python scripts/validate_package.py`; валидатор не принимает package path. | Milestone checks должны использовать поддерживаемый CLI и realistic routing fixture/forward-test. |
| Version policy | `CONTRIBUTING.md:16-31`, `plugins/openbuild/.codex-plugin/plugin.json:3` | Manifest — authoritative source; breaking contract требует major и синхронизацию CHANGELOG/README. | Release surfaces синхронизированы на `2.0.1`; `2.0.0` остался непомеченным development commit. |
| Package hygiene/version gate | `scripts/validate_package.py` | Normal validator сканирует root `BUILD.md`, запрещает committed fixed model slugs/personal absolute paths и требует version bump при pending package paths. | Development bump выполнен; normal validator проходит, commit gate проверяется после точного staging. |
| Root config | `~/.codex/config.toml:1` | Future tasks используют balanced root; текущая task была запущена до изменения и сохраняет session-start strongest/high-effort effective route. | Изменение root и новых profiles требует новой task/session для runtime verification. |
| Spark profile | `~/.codex/agents/openbuild-search-separate.toml:1` | Spark preview route, `low`, read-only. | Профиль существует, но selection не доказан. |
| Fast/balanced writers | `~/.codex/agents/openbuild-implementation-fast.toml`, `~/.codex/agents/openbuild-implementation-balanced.toml` | Добавлены low-risk Direct и medium contained writer profiles с `workspace-write`. | Новые task/session могут выбирать minimum sufficient writer tier. |
| Luna profile | `~/.codex/agents/openbuild-review-fast.toml:1` | Luna назначена только low-risk review с effort `low`. | В high-risk run её отсутствие может быть правильным. |
| Strong profiles | `~/.codex/agents/openbuild-implementation-strongest.toml:1`, `~/.codex/agents/openbuild-review-strong*.toml:1` | Sol назначена writer/reviewer с `xhigh`, `high`, `max`. | Reasoning должен меняться только при выборе этих профилей. |
| Current spawn schema | runtime capability текущей сессии | Доступны только `task_name`, `message`, `fork_turns`; `agent_type/profile/model/model_reasoning_effort` отсутствуют. | Это непосредственный owner-layer blocker адресного routing. |
| Exact dispatch reproduction | runtime error текущего Build-run | Вызов с `task_name: openbuild-search-separate` отклонён до запуска: `agent_name must use only lowercase letters, digits, and underscores`. | Дефисные profile names несовместимы с текущим идентификаторным контрактом; circuit breaker открыт по `selector-unavailable`, а не по quota Spark. |
| Configured profiles | `~/.codex/agents/*.toml`, безопасный metadata-only audit 2026-07-13 | Девять профилей существуют; `openbuild-search-separate` настроен на runtime-resolved Spark preview/`low`, но все OpenBuild `name` используют дефисы. | Конфигурация намерения существует, однако ни exact profile selection, ни model/effort switch не произошли. |
| Local runtime | callable schema и `codex --version` probe текущей app-сессии | Callable schema не даёт selector; дополнительный `codex.exe` probe завершился `Access is denied`. | ТЗ не может полагаться на shell-обход и обязано проверяться через фактически предоставленный host interface. |
| Official custom-agent contract | [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents) | Поле `name` является source of truth; официальный поисковый пример использует `pr_explorer` и текущую Spark preview model, а filename при этом может содержать дефис. | Runtime-safe identifier и filename — разные сущности; простая смена filename проблему не решит. |
| Official model/effort contract | [Choosing models and reasoning](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning) | Agent TOML поддерживает `model` и `model_reasoning_effort`; Spark доступен как text-only research preview для подходящих Pro accounts. | Фактическое переключение требует выбора custom agent, а не только наличия TOML. |
| Official Spark pool contract | [Codex pricing](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan) | Spark имеет отдельный usage limit, меняющийся с demand, и не доступен через API at launch. | Separate-pool claim допустим после trusted exact selection; plugin-owned API adapter не может предполагать доступность Spark. |
| Current package version | `plugins/openbuild/.codex-plugin/plugin.json:3`, `README.md` | Release candidate использует `2.0.1`; `2.0.0` не тегировался, потому что release-metadata commit обязан иметь уникальную более высокую SemVer. | `v2.0.1` является авторизованным immutable release target; M4–M6 ещё не завершены. |

### Source of truth

Runtime tool schema и observed spawn metadata — источник истины для фактического выбора профиля. TOML — источник желаемой конфигурации. Build skill — источник policy/order, но не доказательство выполнения. Usage dashboard может быть вторичным подтверждением расхода, но не является доступным или допустимым источником для автоматического workflow.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD.md` | user + repository task specification | In progress / R-014 | D-001..D-015, T-001..T-006, AC-01..26, M1..M6 | Section 2/6 audit names Build skill, routing/discovery/TDD/delegation/minimality/review/versioning protocols, CONTRIBUTING and official Codex docs | yes | R-014 readiness preserved; M3 bootstrap implemented, M4 external |
| `plugins/openbuild/skills/build/SKILL.md` | repository workflow contract | release target 2.0.1; installed plugin cache remains 1.1.1 until refresh/new task | phase routing, canonical exact search/writer/reviewer dispatch, setup-models migration | Direct links audited to `code-discovery.md`, `model-routing.md`, `blindspot-protocol.md`, `spec-template.md`, `implementation-delegation.md`, `tdd-workflow.md`, `minimality-protocol.md`, `versioning.md`, `review-protocol.md` | yes | M3 aligned; D-014 external host contract remains |
| `plugins/openbuild/skills/build/references/code-discovery.md` + `model-routing.md` | repository routing contract | release target 2.0.1; cache refresh pending | separate-pool-first order, canonical IDs, migration plan/receipt, breaker, model/effort evidence | Links between both files and to delegation/review protocols audited from known paths | yes | M3 repository contract implemented; host selector remains external prerequisite |
| `plugins/openbuild/skills/build/references/blindspot-protocol.md` + `spec-template.md` | repository specification contract | release target 2.0.1; behavior unchanged in release metadata | source map, D/T/B ledgers, decision gate, Ready closure | Outgoing decision/coverage/application requirements audited; no unmapped external normative companion | yes | R-014 readiness contract preserved |
| `plugins/openbuild/skills/build/references/implementation-delegation.md`, `tdd-workflow.md`, `minimality-protocol.md`, `review-protocol.md`, `versioning.md` | repository implementation/review/release contract | release target 2.0.1; files read in full | canonical writer/reviewer selection, separate task label, gates, validation, SemVer | Internal links resolve within the mapped Build reference set | yes | M3 aligned; M4–M6 pending |
| `CONTRIBUTING.md` | repository maintainer policy | current `main` | validation, runtime smoke, version/commit policy | Links SemVer and package commands; no additional task specification named | yes only when implementing policy change | aligned; runtime smoke remains primary signal |
| Official Codex custom-agent/model/pricing docs | upstream product contract | fetched 2026-07-13 | custom-agent name source of truth, per-agent model/effort, Spark availability/pool | Direct official anchors recorded in evidence table; no local editable target | no | aligned with underscore profiles; current callable schema gap becomes host deliverable |

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| Дефисные OpenBuild role names против runtime-safe identifier grammar | Canonical underscore IDs + guided legacy migration | D-013, user reply 2026-07-13: `1a` | aligned |
| Native custom-agent contract против отсутствующего selector в callable `spawn_agent` | Двухконтурное ТЗ: OpenBuild integration + отдельный host-runtime selector/metadata deliverable, без adapter | D-014, user reply 2026-07-13: `2a` | aligned; external prerequisite explicit |
| Spark как primary search route | Явное текущее требование пользователя сохраняет уже описанный отдельный search route | D-015, user prompt 2026-07-13 + official pricing/subagent docs | aligned |

### Gap

OpenBuild описывает правильную лестницу, но его exact profile names не проходят текущую identifier validation, callable `spawn_agent` не отделяет task label от custom-agent selector, а repository не содержит host router. Поэтому TOML с runtime-resolved Spark preview/`low` остаётся лишь configured intent: workflow уходит в generic/root fallback, а переключение модели и дочернего reasoning не происходит и не наблюдается.

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
| D-013 | routing.identifier-migration | user | resolved | Как мигрировать публичные дефисные role names, которые runtime отклоняет? | Canonical underscore IDs во всех selectors/receipts/docs; setup выполняет permission-gated guided migration legacy дефисных profiles без silent overwrite/delete. | Ответ пользователя 2026-07-13: `1a`; runtime error и официальный underscore custom-agent example. | Определяет новые profile names, migration, fixtures и major compatibility note. |
| D-014 | routing.runtime-delivery-boundary | user | resolved | Что входит в реализацию, если host surface не предоставляет custom-agent selector? | Двухконтурное end-to-end ТЗ: OpenBuild changes плюс отдельный host-runtime selector/metadata contract; собственного MCP/CLI adapter нет. | Ответ пользователя 2026-07-13: `2a`; callable schema и plugin manifest boundary. | Actual switching считается завершённым только после обоих deliverables и end-to-end smoke. |
| D-015 | routing.spark-primary-search | user | resolved | Должен ли Spark реально использоваться для repository search? | Да: exact runtime-resolved Spark preview profile является primary search route на entitled/compatible surface; fallback допустим только после наблюдаемой разрешённой ошибки. | Текущий user prompt 2026-07-13; official docs подтверждают custom-agent example и separate limit. | AC обязаны различать configured profile, exact selection и allowed fallback. |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Считать `task_name` только task label, пока runtime/tool envelope явно не подтверждает custom-agent selection | selected | Callable schema description, exact rejection и официальный `name` source-of-truth; альтернатива «underscore task label = profile selection» не имеет evidence | Сохраняет D-004/D-007/D-011/D-015 и исключает ложное заявление о Spark/model/effort switch |
| T-002 | Зафиксировать wire contract `openbuild-agent-routing/1` с обязательным `agent_name`, correlation IDs, exact config fingerprint/generation и out-of-band host envelope | selected | Architecture critic: AC-02/18 допускали несовместимые field names и stale/misbinding; exact schema ниже | Сохраняет D-007/D-014/D-015; механизм не меняет выбранные роли или fallback outcomes |
| T-003 | Guided migration как hash-bound, create-if-absent, per-file atomic и idempotently resumable plan | selected | Product/architecture critics: collision, partial-write и rerun gaps; legacy files по D-013 уже сохраняются | Сохраняет D-003/D-013: ни один divergent target не перезаписывается без нового exact diff/permission |
| T-004 | Единая cross-layer dispatch/error state machine и termination acknowledgement | selected | Critics обнаружили три несовместимых vocabulary и race после timeout; taxonomy ниже переиспользует routing failure reasons | Сохраняет D-011/D-015: read-only fallback остаётся честным, edits требуют selected route, unknown termination блокирует нового writer |
| T-005 | Capability negotiation и host-first paired release gate | selected | Two-track D-014 требует exact compatible revisions; reproduction принадлежит Codex desktop current surface | Сохраняет D-014 и user outcome: OpenBuild 2.0 не объявляет feature complete до compatible desktop host + paired smoke |
| T-006 | Probe isolation и persisted diagnostics доказываются allowlisted host fields + synthetic sentinel denial; raw host errors не сохраняются | selected | Architecture critic: `read-only` не доказывает deny-read, raw paths/account data могут утечь | Сохраняет D-004/D-006/D-007 и AC-13 без чтения real user/repository secrets |

### Pending proposals

- None. D-013/D-014 applied in R-012; R-014 fresh high-risk closure is `COVERED` with no reopened decision.

## 4. User scenarios

### Primary scenario

1. Пользователь запускает `$openbuild:build setup-models` после reload/new session.
2. Build перечисляет discoverable profile names и effective settings без секретов.
3. Build адресно запускает короткие probes с `fork_turns: none` и синтетическим payload без repository/conversation/customer context: read-only для Spark, Terra и Luna; strongest writer получает пустую lease и обязан вернуть marker без изменения файлов.
4. Для каждого probe сохраняется requested profile, observed profile/model/reasoning, sandbox, pool evidence и результат.
5. Следующий `$openbuild:build new|run|full` выбирает профиль по роли/риску, добавляет routing record в specification и показывает пользователю компактный summary: `phase | requested profile | selected role | observed model/effort | pool evidence | status | fallback/breaker | record path`.

### Errors and edge cases

- Selector отсутствует -> не пытаться выдавать generic spawn за custom profile; честные read-only search/specification fallbacks разрешены, но любой profile-dependent edit/review route блокируется. Low/medium может продолжить при неполной model metadata только после trusted exact role selection по D-011; selector absence и metadata partial — разные состояния.
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

- [ ] AC-01: preflight до repository search фиксирует наличие/отсутствие отдельного addressable profile selector и discoverable canonical names: `openbuild_search_separate`, `openbuild_search_fallback`, `openbuild_implementation_fast`, `openbuild_implementation_balanced`, `openbuild_implementation_strongest`, `openbuild_review_fast`, `openbuild_review_balanced`, `openbuild_review_strong`, `openbuild_review_strongest`.
- [ ] AC-02: все profile-specific spawns передают exact underscore agent ID через отдельное host field `agent_name` или семантически эквивалентный selector; `task_name` остаётся независимым task label и не используется как суррогат selector.
- [ ] AC-03: setup smoke-test отдельно подтверждает Spark `low`, Terra `low/medium`, Luna `low`, Sol `high/xhigh/max` в пределах поддерживаемых runtime значений либо возвращает exact `dispatch_status`, `error_code`, `limitations` и normalized `fallback_reason` из единой T-004 taxonomy.
- [ ] AC-04: Spark probe отдельно фиксирует (a) официальный источник separate-limit mapping, (b) trusted runtime selection outcome и (c) usage amount как observed value либо `unobservable`; расход никогда не выводится из model slug или self-report.
- [ ] AC-05: каждый Build-run записывает machine-readable row `phase, request_id, dispatch_id, client_revision, host_build, capability_version, requested_profile, profile_fingerprint, selected_role, observed_model, observed_effort, pool_claim, provenance, dispatch_status, child_state, event_seq, fallback_reason, breaker, limitations` в текущую specification и показывает компактный user-facing summary со ссылкой на неё, включая early preflight failure/timeout.
- [ ] AC-06: Build выбирает `openbuild_implementation_fast` для low Direct, `openbuild_implementation_balanced` для medium contained и `openbuild_implementation_strongest` для high/critical work; required risk floor нельзя понижать. Legacy дефисные names не dispatch-ятся.
- [x] AC-07: отсутствие model/tier metadata записывается как `unknown`/`unobservable` и не блокирует exact configured low/medium route; high/critical остаются blocked без required strong/strongest route.
- [x] AC-08: документация объясняет, что Terra/Luna/Spark — специализированные маршруты, а не обязательные участники каждого run, согласно D-001.
- [ ] AC-09: package validator и tests отклоняют Build package, который теряет capability preflight, canonical underscore role selection, separation `agent_name` from `task_name`, observed verification или honest fallback contract.
- [ ] AC-10: selector-capable test runtime принимает canonical underscore `agent_name`; integration probe с synthetic payload, `fork_turns: none`, одной попыткой и 60-second timeout воспроизводимо доказывает применение custom profile по runtime-generated envelope; selector-less runtime возвращает явный compatibility failure и не проходит end-to-end acceptance.
- [ ] AC-11: любой `Questions` checkpoint/final содержит для каждого blocking D-ID полный текст вопроса, 2–3 взаимоисключающих варианта с последствиями, рекомендацию и формат ответа; тест отклоняет сообщение, которое просит коды без показанных вариантов.
- [ ] AC-12: EN/RU documentation и fixture outputs содержат одинаковые routing/error statuses, migration/collision recovery, supported-surface and mixed-version matrix, host prerequisite, rollout/rollback steps и последствия вариантов; вопрос остаётся понятным в plain-text rendering.
- [ ] AC-13: каждый profile smoke probe запускается только в отдельном task-owned `.tmp/openbuild-model-probe/<run-id>` workspace с runtime-enforced запретом чтения вне него; до/после сравнивается manifest/hash и любая неразрешённая мутация проваливает probe. Если такую изоляцию нельзя доказать, probe не запускается и получает `isolation-unavailable`.
- [ ] AC-14: реальный Questions checkpoint проверяется через ephemeral `codex exec` с `--output-last-message`; валидатор captured output проваливает negative case «коды ответа без предшествующих вариантов» и принимает полный canonical question block.
- [x] AC-15: writer escalation происходит только при росте scope/risk, insufficient confidence, deeper red/green signal, task-scoped validation failure или confirmed review finding; trivial work не создаёт лишний fan-out.
- [x] AC-16: все writer tiers используют одинаковые Ready, owner-layer, TDD, minimality, single-writer, handoff, validation, versioning и progressive-review contracts.
- [ ] AC-17: `setup-models` обнаруживает legacy дефисные TOML names, показывает exact create/update/remove plan и canonical underscore files, запрашивает permission до записи, не overwrites и не удаляет legacy files автоматически; cleanup предлагается отдельно только после TOML validation, reload и успешного exact-profile smoke.
- [ ] AC-18: host-runtime deliverable реализует exact `openbuild-agent-routing/1` request/response schema из section 6, включая separate `agent_name`, correlation/version/config/isolation/lifecycle fields и redacted structured error; task label и child display name остаются отдельными полями.
- [ ] AC-19: negative host/repository integration test доказывает, что underscore `task_name` без selector не загружает profile и не может дать `selected`; неизвестный/legacy дефисный `agent_name` возвращает deterministic validation/profile-not-discoverable result до repository search или edit.
- [ ] AC-20: fresh entitled end-to-end smoke показывает `openbuild_search_separate -> configured Spark preview model -> low -> read-only` в trusted envelope до первого repository lookup; только failed status, нормализованный в portable fallback vocabulary T-004, открывает breaker и разрешает read-only fallback. Usage amount остаётся `unobservable`, если runtime его не сообщает.
- [ ] AC-21: migration preview имеет immutable `plan_id`, stable `entry_id` и SHA-256 preconditions для каждого source/target; одно user approval может принять весь displayed plan, но authority хранится per entry. Отсутствующий target создаётся atomically, byte-identical canonical target получает `already-migrated`, divergent target получает `config-conflict` без записи. Partial run сохраняет per-file receipt; hash drift инвалидирует только affected entry, требует его нового exact diff/permission и не отменяет authority unchanged entries.
- [ ] AC-22: host contract `openbuild-agent-routing/1` валидируется consumer/provider contract tests и связывает request, dispatch, child thread, OpenBuild revision, host build/capability, selected profile and config fingerprint/generation в одном out-of-band envelope, который не может быть сформирован child message.
- [ ] AC-23: dispatch result state отделён от child lifecycle: `dispatch_status=selected|failed`; selected child проходит legal `not-created -> running -> completed` либо `running -> cancel-requested -> terminated|termination-unknown` transitions с monotonic `event_seq`. Новый writer/probe/fallback writer запрещён до `child_state=terminated|completed`, host termination acknowledgement и lease release. Search fallback после read-only timeout допустим только по явно записанной policy и не считается profile success.
- [ ] AC-24: isolation conformance создаёт synthetic sentinel вне probe workspace, не содержащий user/repository data, и требует host denial; envelope фиксирует `history_inherited=false`, `read_scope=probe-workspace-only`, `write_scope`, `network_access=false`, workspace identity и zero unexpected context sources. Один `selected_sandbox_mode=read-only` не проходит oracle.
- [ ] AC-25: preflight negotiates capability `custom_agent_selector_v1` и exact contract version; routing record содержит OpenBuild version/commit, host version/build, surface, capability version и profile fingerprint. Host-compatible Codex desktop release предшествует OpenBuild 2.0 public release; mixed-version matrix проверяет 1.1.1/new-host и 2.0/old-host, где old host fail-fast сообщает upgrade path и не заявляет switching.
- [ ] AC-26: AC-20 владеет OpenBuild maintainer совместно с authorized host maintainer; smoke использует fresh unique request после обоих exact revisions и authorized entitled test account без сохранения identity. Durable artifact хранит только allowlisted schema fields, relative/hashed workspace data, status/error code and revision/fingerprint; raw errors, absolute user paths, account IDs and entitlement details запрещены.

### Invariants

- Root остаётся владельцем product/architecture/specification/Git/final synthesis.
- Search/critics/review profiles остаются read-only; любой fast/balanced/strongest writer получает один и тот же bounded single-writer lease.
- Пользовательская конфигурация изменяется только по явному разрешению; текущий root default и два writer profile применены в рамках принятого пользователем плана.
- Legacy дефисные profiles остаются читаемым migration input, но никогда не считаются successful dispatch target; их удаление требует отдельного подтверждения после canonical smoke.
- OpenBuild не обещает экономию, отдельный pool или смену модели без runtime/config evidence.
- Одновременно работает не более одного writer.
- Probe не наследует историю, repository contents или пользовательские данные и не просит агента сообщить собственную модель как evidence.

## 6. Technical boundaries

### Affected layers and contracts

- `plugins/openbuild/skills/build/SKILL.md` — обязательный preflight, explicit role selection, smoke verification и user-facing diagnostics.
- `plugins/openbuild/skills/build/references/model-routing.md` — формальный selector/observability/fallback contract.
- `plugins/openbuild/skills/build/references/code-discovery.md` — первая separate-pool попытка только через addressable profile.
- Все repository-owned routing references, validators, fixtures и bilingual docs — canonical underscore role IDs и legacy migration contract.
- `scripts/validate_package.py` — статические обязательные tokens/ordering.
- `scripts/test_validate_package.py` — red/green coverage для новых contract clauses.
- Новый validator/fixture boundary для captured Questions output — структурная проверка D-ID, вариантов, последствий, рекомендации и reply format; exact filename выбирается при реализации рядом с существующими validators.
- `plugins/openbuild/skills/build/references/blindspot-protocol.md` и `spec-template.md` — единый self-contained interview/checkpoint contract без расхождения между specification и final response.
- `README.md`, `README.ru.md`, `CHANGELOG.md`, plugin version surfaces — синхронизация пользовательской инструкции и release impact.
- Codex runtime/surface — отдельный внешний deliverable: request selector, profile resolution по TOML `name`, применение model/effort/sandbox и trusted selected role/model/effort/sandbox envelope.
- Внешний host-contract artifact/issue — exact schema, error vocabulary, compatibility/version boundary и end-to-end acceptance для AC-18..20; он не маскируется как изменение plugin repository.

### Host contract `openbuild-agent-routing/1`

Contract имеет две explicit operations, передаваемые host tool вне prompt дочернего агента.

#### Operation: `preflight`

Request:

| Field | Type / required | Contract |
|---|---|---|
| `operation` | literal `preflight`, required | Не создаёт child и не выполняет repository lookup. |
| `contract_version`, `request_id` | literal + UUID, required | `openbuild-agent-routing/1` и fresh correlation ID. |
| `client_version`, `client_revision` | SemVer + commit/hash, required | Exact OpenBuild identity. |
| `required_capability` | literal, required | `custom_agent_selector_v1`. |
| `requested_agents` | unique canonical string array, required | Девять IDs AC-01 или task-scoped subset. |
| `requested_scope` | `user / project`, required | Current D-003 route uses `user`. |

Response:

| Field | Type / required | Contract |
|---|---|---|
| `operation`, `contract_version`, `request_id` | exact echo, required | Mismatch fails closed. |
| `host_surface`, `host_version`, `host_build`, `capability_version` | strings, required | Capability negotiation and mixed-version matrix. |
| `capability_status` | `supported / unsupported`, required | `unsupported` normalizes to `selector-unavailable`. |
| `profiles` | array, required | Per requested agent: `name`, `discoverable`, `scope`, exact-byte `fingerprint`, `config_generation`, effective `model`, `model_reasoning_effort`, `sandbox_mode`, or allowlisted limitation. |
| `conflicts` | array, required | Duplicate names/scopes and redacted source identities; empty when none. |
| `error_code`, `fallback_reason`, `limitations` | exhaustive enums, required | Uses taxonomy/mapping below; `none`/empty array when clean. |

Preflight response and receipt must precede the first repository-search event. Only a clean unique profile entry supplies `expected_profile_scope`, `expected_profile_fingerprint` and `expected_config_generation` to dispatch.

#### Operation: `dispatch`

Request:

| Field | Type / required | Contract |
|---|---|---|
| `operation` | literal `dispatch`, required | Creates at most one child after validation. |
| `contract_version` | literal string, required | `openbuild-agent-routing/1` |
| `request_id` | UUID, required | Уникален для каждой dispatch attempt и routing receipt. |
| `client_version`, `client_revision` | SemVer + commit/hash, required | Exact OpenBuild package/diff identity. |
| `required_capability` | literal string, required | `custom_agent_selector_v1`. |
| `agent_name` | `^[a-z0-9_]+$`, required | Единственный custom-profile selector; canonical value из AC-01. |
| `task_name` | string, optional | Presentation/task label; не участвует в profile resolution. |
| `message` | string, required | Worker brief. |
| `fork_turns` | `none / all / positive-integer`, required | History inheritance control. |
| `expected_profile_scope` | `user / project`, required after preflight | Для D-003 current setup — `user`. |
| `expected_profile_fingerprint` | SHA-256, required after preflight | Hash exact TOML bytes approved/validated before dispatch. |
| `expected_config_generation` | opaque string/integer, required after preflight | Invalidates stale preflight after reload/config change. |
| `probe_policy` | object, optional | Task-owned workspace ID and AC-24 isolation requirements for smoke probes. |

Host response является out-of-band tool metadata и содержит:

| Field | Type / required | Contract |
|---|---|---|
| `operation` | exact `dispatch`, required | Distinguishes it from preflight. |
| `contract_version`, `request_id` | exact echo, required | Несовпадение даёт `capability-mismatch`; response не используется. |
| `dispatch_id` | UUID, required | Связывает lifecycle events и termination acknowledgement. |
| `child_thread_id` | opaque ID, nullable until spawn | Не берётся из child text. |
| `host_surface`, `host_version`, `host_build`, `capability_version` | strings, required | Exact paired host identity. |
| `dispatch_status` | enum из T-004, required | State machine ниже. |
| `error_code` | enum или `none`, required | Stable machine code; raw error не является durable evidence. |
| `fallback_reason` | portable enum или `none`, required | Exact mapping below; non-fallback errors use `none`. |
| `selected_agent`, `selected_model`, `selected_model_reasoning_effort`, `selected_sandbox_mode` | strings, required when `selected` unless limitation explicitly allowed by D-011 | Effective host-owned selection, не self-report. |
| `profile_scope`, `profile_fingerprint`, `config_generation` | required when profile resolved | Должны совпасть с request preconditions. |
| `isolation` | structured object, required for probes | Поля AC-24; raw readable-root lists не сохраняются. |
| `event_seq`, `child_state`, `termination_acknowledged` | monotonic integer + exhaustive enum + boolean, required for lifecycle events | Gate для release lease/next writer. |
| `limitations` | exhaustive enum array, required | `metadata-partial`, `pool-unobservable`, `usage-unobservable`, `token-cap-unobservable`, `context-isolation-limited`; empty array means none. Arbitrary child text запрещён. |

Profile resolution выполняется только внутри trusted configured agent roots. Host индексирует exact TOML `name`; zero matches даёт `profile-not-discoverable`, more than one match даёт `config-conflict`, symlink/path escape из trusted root отклоняется. Exactly one file snapshot-ится до spawn; exact-byte fingerprint и config generation связываются с child configuration. Любой drift между preflight и dispatch даёт `config-changed` без spawn. Неявная precedence между duplicate user/project profiles запрещена.

### Dispatch lifecycle and error taxonomy

- `dispatch_status` describes only selector/spawn result: `selected` or `failed`. It never changes after dispatch and is not the child lifecycle.
- `child_state`: `not-created`, `running`, `cancel-requested`, `completed`, `terminated`, `termination-unknown`. Legal transitions: `not-created -> running -> completed`; `running -> cancel-requested -> terminated`; `cancel-requested -> termination-unknown -> terminated` when a late acknowledgement arrives. Every event repeats `request_id`/`dispatch_id` and increases `event_seq`.
- `error_code`: `none`, `invalid-request`, `invalid-agent-name`, `profile-not-discoverable`, `config-conflict`, `config-changed`, `atomic-create-unavailable`, `selector-unavailable`, `capability-mismatch`, `model-unavailable`, `quota-exhausted`, `spawn-failed`, `sandbox-mismatch`, `isolation-unavailable`, `worker-timeout`, `cancellation-failed`, `unusable-evidence`.
- Durable `fallback_reason`: `none`, `profile-not-discoverable`, `selector-unavailable`, `model-unavailable`, `quota-exhausted`, `spawn-failed`, `worker-timeout`, `unusable-evidence`.
- Exact normalization:

| Host `error_code` | `fallback_reason` | Fallback condition |
|---|---|---|
| `none` | `none` | No fallback. |
| `invalid-agent-name`, `profile-not-discoverable`, `config-conflict`, `config-changed` | `profile-not-discoverable` | Read-only search/spec fallback only; migration/config recovery remains visible. |
| `selector-unavailable`, `capability-mismatch` | `selector-unavailable` | Read-only search/spec fallback only. |
| `model-unavailable` | `model-unavailable` | Read-only search/spec fallback only. |
| `quota-exhausted` | `quota-exhausted` | Read-only search/spec fallback only. |
| `spawn-failed` | `spawn-failed` | Read-only search/spec fallback only. |
| `worker-timeout` | `worker-timeout` | Only after read-only/no-write proof; writer waits for termination acknowledgement. |
| `sandbox-mismatch`, `isolation-unavailable`, `unusable-evidence` | `unusable-evidence` | Read-only fallback only when no child can write and the receipt records the limitation. |
| `invalid-request`, `atomic-create-unavailable`, `cancellation-failed` | `none` | Fail closed; fix request/migration or obtain termination acknowledgement. |

- Read-only search/specification may fall back after one exact failed separate-route attempt with complete receipt; breaker transitions `closed -> open` and forbids another separate attempt in the same run.
- Ни один failed selector route не разрешает test/production edits. Low/medium допускают только `selected` exact role с `metadata-partial` limitation, когда effective profile fingerprint/sandbox не противоречат route; high/critical требуют complete proven tier.
- Timeout добавляет `worker-timeout` lifecycle event и вызывает cancel once: `running -> cancel-requested`. Writer/probe lease не освобождается и новый write-capable dispatch не начинается до `child_state=terminated` и `termination_acknowledged=true`; иначе child остаётся `termination-unknown` и milestone blocked. Read-only search fallback может продолжить только если host подтверждает no-write sandbox; это не превращает timed-out route в success.

### Guided migration transaction

1. Metadata-only preflight индексирует все TOML files в выбранном scope по filename и `name`, не печатая instructions или unrelated values.
2. Build создаёт immutable `plan_id`; каждая из девяти записей имеет stable `entry_id`, scope-relative source/target paths, trusted root fingerprint, SHA-256 preconditions и planned canonical bytes. Preview показывает пользователю resolved per-file action/diff, а durable record не сохраняет absolute home path.
3. Один ответ пользователя может approve весь displayed plan, но authority записывается per `entry_id` + exact precondition hashes. Drift аннулирует только affected entry; unchanged approved entries сохраняют authority. Drifted entry не меняется до отдельного re-preview/re-approval.
4. Target absent -> atomic create-if-absent in the same directory. Target byte-identical -> `already-migrated`. Любое иное содержимое, duplicate canonical `name` или unavailable atomic-create primitive -> no write with `config-conflict`/`atomic-create-unavailable`.
5. После каждого file operation durable task receipt фиксирует `created | already-migrated | conflict | atomic-create-unavailable | failed` и observed post-hash. Crash/partial failure безопасен, потому что legacy files не меняются; rerun продолжает unchanged approved entries и re-previews/re-approves только drifted/conflicting entries.
6. Reload + exact canonical smoke обязательны до cleanup. Cleanup — новый plan/diff/permission; rollback guide умеет восстановить legacy profiles из reviewed canonical files, если пользователь позже удалил legacy copies.

### Paired compatibility, rollout and evidence

- Capability handshake: `custom_agent_selector_v1` + exact `openbuild-agent-routing/1`; unknown version fails closed for profile-dependent work.
- Required matrix: OpenBuild 1.1.1/new host keeps legacy honest fallback without claiming selection; OpenBuild 2.0/old host fails preflight, permits only read-only fallback and shows host upgrade path; OpenBuild 2.0/compatible host passes AC-20.
- Current Codex desktop surface from the reproduced failure is mandatory for AC-20 and host-first rollout. CLI/IDE/plugin surfaces are listed supported only after the same capability handshake passes there.
- Compatible desktop host build is distributed before public OpenBuild 2.0 release. Release candidate records exact OpenBuild commit/version, host build/version/surface, capability/contract version, profile fingerprint, unique request/dispatch IDs and event ordering.
- Rollback host-first failure with OpenBuild 2.0 leaves writes blocked and directs reinstall of 1.1.1 or compatible host recovery; legacy profiles remain until separate cleanup. Tag/release publication still requires its own authorization.
- AC-20 smoke owners: OpenBuild maintainer + authorized host maintainer. Durable evidence is an allowlisted sanitized record; raw error strings, absolute user paths, account/workspace IDs, entitlement values and child self-report are discarded. Freshness requires request creation after both recorded revisions and no reused request/dispatch ID.

### Data and migration

Product data/schema migration не требуется. Configuration migration обязательна: `setup-models` metadata-only обнаруживает девять legacy дефисных profiles, показывает создание девяти canonical underscore TOML files с сохранением model/effort/sandbox/instructions, запрашивает permission, валидирует новые файлы и требует reload/new session. Legacy files не перезаписываются и не удаляются; после успешного canonical smoke Build отдельно предлагает cleanup с точным списком. Routing record хранится только в task specification, наследует её repository access/retention и удаляется вместе с ней; отдельное хранилище или бессрочный глобальный журнал не создаются.

### Security and privacy

Не читать и не печатать auth/session secrets, raw `.env` или приватный usage dashboard. Smoke probes используют новый пустой контекст, синтетический marker и отдельный task-owned workspace `.tmp/openbuild-model-probe/<run-id>`. Effective runtime permissions должны запрещать чтение вне probe workspace; отсутствие доказуемой deny-read/isolation capability даёт `isolation-unavailable` без запуска. До/после probe root сравнивает manifest/hash, а strongest-writer marker не разрешает файловых изменений. Diagnostic output содержит только profile name, model ID, effort, sandbox, подтверждённый pool label и redacted runtime error.

### Performance and concurrency

Smoke tests последовательные: одна попытка на profile, максимум 60 секунд, затем interrupt/cancel и запись partial outcome. Если runtime предоставляет token budget, используется минимальный поддерживаемый cap; если нет — `token_cap: unobservable`. Обычный Build использует параллельные read-only ветки только когда это полезно. Breaker исключает повторные неуспешные Spark attempts в одном run.

### Observability and errors

Routing record является обязательной таблицей в task specification с полями AC-05; допустимые неизвестные значения — только `unknown` (runtime не сообщил значение) и `unobservable` (surface не экспонирует класс данных). Источник provenance — `runtime-envelope`, `effective-config`, `official-doc`, `user-manual` или `none`; текст дочернего агента не является provenance. Каждый checkpoint/final повторяет компактный summary и ссылку на specification. `codex doctor --json` в текущей среде завершился timeout и не считается успешной проверкой discoverability.

### Versioning and release

Будущая OpenBuild-реализация является major change `1.1.1 -> 2.0.0`: canonical role IDs меняются, но guided migration сохраняет legacy files до доказанного smoke. Manifest, CHANGELOG и обе README обновляются одним implementation commit по repository policy; tag/release отдельно не авторизованы. Host-runtime deliverable versionируется и выпускается по политике его owning repository, не подменяется версией OpenBuild. Rollback: вернуть plugin/docs к 1.1.1 contract, оставить legacy profiles нетронутыми, отключить canonical dispatch и не заявлять actual model switch; опубликованные tags не перемещаются.

## 7. Validation and review

- Primary signal: fresh end-to-end trace показывает separate `agent_name=openbuild_search_separate`, trusted configured-Spark/`low`/`read-only` envelope и dispatch receipt до первого repository lookup; отдельные traces доказывают risk-matched model/effort для writers/reviewers, а negative case с одним `task_name` не выбирает profile.
- Repository red: текущий 1.1.1 routing contract/fixtures используют дефисные IDs и не требуют guided migration либо отдельный host selector; новые focused mutations должны падать до M3 implementation.
- Host red: текущая callable schema не имеет `agent_name`, а exact legacy ID отклоняется до spawn; host owner воспроизводит это своим narrow contract test до M4 implementation.
- Focused repository green: `python -m unittest discover -s scripts -p "test_*.py" -k UsageRoutingContractTests -v` и `python -m unittest discover -s scripts -p "test_*.py" -k SearchDispatchTraceTests -v` — proposed after M3; должны включать canonical/migration/task-label negative cases.
- Focused host green: authoritative host-runtime test command определяется и записывается owning repository; ТЗ требует schema/profile-resolution/envelope/error cases AC-18/19 и не выдумывает внешний command.
- Wider checks: `python -m unittest discover -s scripts -p "test_*.py" -v`, `python scripts/validate_package.py`, `git diff --check`, official skill/plugin validators и host-runtime owning suite.
- Manual/runtime check: fresh installed OpenBuild 2.0 candidate + compatible host + entitled account executes AC-20 in isolated workspace; dashboard optional and secondary.
- Historical baseline: prior 1.0/1.1 routing suite and package validation passed, but они не доказывают canonical selector или actual model switching и не засчитываются как green для M3..M6.
- Starting review tier: strong requested for high cross-repository contract/migration risk; observed tier may remain unknown.
- Required final tier: strong for OpenBuild diff and host diff, затем fresh end-to-end closure across both exact revisions.
- Review ladder: product/UX migration critic + architecture/data/security host-contract critic; after remediation, fresh strong closure. Diff review remains sequential and read-only.
- Minimality: native custom-agent files и host owner-layer selector используются напрямую; OpenBuild-owned MCP/router/runner, production dependency и hosted support surface исключены D-014.
- Runtime limitation: current surface не может выполнить AC-18/20. Это explicit external prerequisite, а не основание считать specification или configured TOML успешным model switch.

## 8. Milestones

### M1. Risk-matched implementation contract

- Status: Complete — historical pre-R-012 contract; current canonical AC-06/09 are reopened in M3
- Scope: fast/balanced/strongest routing, low/medium unknown-metadata rule, confirmed high/critical floors, evidence-only escalation, preserved coding methodology, deterministic validator/tests.
- Implementation mode: TDD-first.
- Writer lease: `root-only`; requested tier strong; session-start effective root configuration was strongest/high-effort, observed runtime envelope `unknown`; allowed paths were Build skill references, validator/tests, bilingual docs, manifest/changelog and this specification. Один writer, concurrent repository writers отсутствовали.
- Red: 2 expected routing-contract failures before production contract edits.
- Handoff: root reread the full task diff, ran focused then wider validation, and routed the diff to progressive review.
- Acceptance: historical AC-06/09 plus still-valid AC-07/15/16; current AC-06/09 require M3 evidence.
- Version: synchronized `0.4.0 -> 1.0.0`; release/tag absent.
- Commit: historical package work завершено до continuation baseline; exact prior milestone SHA не используется как current-task evidence.

### M2. Native profiles and user guidance

- Status: Complete as legacy-profile setup; canonical migration and runtime verification remain M3/M5.
- Scope: added user-scoped fast/balanced writer TOMLs, changed future root default to balanced, documented three writer tiers and updated setup-model count, README/CHANGELOG/version surfaces.
- Implementation mode: Direct for authorized config/docs after M1 contract green.
- Minimality: native custom-agent TOML only; no MCP router/runner and no new dependency.
- Forward tests: low and medium hypothetical tasks selected the minimum sufficient tier and preserved all method gates.
- Acceptance: AC-08 plus configuration portion of AC-03.
- Limitation: current task cannot prove the new profiles were selected; new task/session and native selector metadata are required.
- Commit: repository portion Pending; user-scoped config is intentionally outside Git.

### M3. Canonical profile migration and OpenBuild contract

- Status: Complete — repository bootstrap; user-profile writes and host/runtime proof remain M4/M5
- Scope: заменить normative exact role IDs на девять canonical underscore names; добавить guided legacy-profile migration, receipts, validators, bilingual docs и negative fixtures, где `task_name` не является selector.
- Excludes: silent overwrite/delete user profiles, repository-owned adapter, host-runtime implementation.
- Implementation mode: TDD-first — routing/validation/compatibility contract.
- Red signal: canonical search/writer fixtures failed because validator expected legacy дефисные IDs/`agent`; migration-contract fixture lacked all nine canonical IDs and plan/receipt semantics.
- Acceptance: AC-01, AC-02, AC-06, AC-09, AC-17, AC-21, repository half of AC-19.
- Minimality: reused the instruction-based skill, existing trace validator/tests and repository docs; no runtime adapter, new dependency, migration executable or extra package surface.
- Green: canonical fixtures 2/2; migration fixtures 12/12; routing contract 12/12; search 7/7; writer 4/4; review 6/6; final full-suite count recorded in the implementation log; package, skill, plugin, syntax and diff validators passed.
- Version: applied `1.1.1 -> 2.0.0` on `main` as the current development version; release/tag action none.
- Commit: same scoped M3 milestone commit as this status record; exact SHA is reported after Git creation.

### M4. Host-runtime custom-agent selector and trusted envelope

- Status: Pending — external owning repository/surface required
- Scope: отдельное request field для canonical `agent_name`, resolution по TOML `name`, применение model/effort/sandbox, trusted selection envelope, deterministic validation/errors и task-label separation.
- Excludes: OpenBuild-owned MCP/CLI/API adapter; Spark API access assumptions; usage-dashboard scraping.
- Implementation mode: TDD-first in the host runtime owner layer.
- Red signal: host contract test показывает, что profile нельзя выбрать отдельно от `task_name`, либо response не доказывает effective model/effort/sandbox.
- Acceptance: AC-18, AC-22, AC-23, AC-24 и host half of AC-19/25.
- Dependency: requires access/authority in the host-runtime repository; OpenBuild can publish the contract artifact but cannot claim host code completion.

### M5. End-to-end profile and Spark smoke matrix

- Status: Pending after M3/M4
- Scope: isolated probes for Spark search, fallback search, three writer tiers and four reviewer tiers; trusted selected-role/model/effort/sandbox envelope; breaker/fallback and mutation isolation.
- Excludes: inferred billing amount, forced all-model fan-out, production data.
- Acceptance: AC-03..05, AC-10, AC-13, AC-20, AC-22..26.
- Stop condition: selector-less host fails compatibility acceptance; unavailable entitlement/quota records the allowed error and breaker without a false success claim.

### M6. Documentation, compatibility and 2.0 release readiness

- Status: Pending after M3/M5
- Scope: EN/RU migration guide, supported-surface matrix, host prerequisite, rollback, CHANGELOG/manifest/readme synchronization, complete validation and progressive review.
- Excludes: tag, GitHub Release or publication without separate authorization.
- Acceptance: AC-11, AC-12, AC-25, AC-26, all remaining package/forward-test evidence.
- Version: implementation commit `2.0.0`; host-runtime version follows its owner policy.

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
| B-010 | observability/support/rollout/rollback/docs | covered | technical decision | AC-05/22/25/26, T-005/T-006: paired revisions, compatibility matrix, host-first rollout, sanitized evidence and major `1.1.1 -> 2.0.0` impact | M6 validation |
| B-011 | acceptance/testability/minimality/cost | covered | technical decision | Deterministic status/provenance vocabulary, bounded probe oracle, native mechanism first | none |
| B-012 | model usage policy | covered | product decision | D-001: адаптивная маршрутизация | none |
| B-013 | missing-selector behavior | covered | product decision | D-011: low/medium exact configured route с unknown metadata; high/critical stop | verify after reload |
| B-014 | runtime capability prerequisite | covered | technical decision | Compatibility release gate detects selector+metadata levels; repo cannot add missing selector | verify on new/reloaded compatible session |
| B-015 | self-contained question rendering | covered | technical decision | D-008, AC-11/14; ephemeral captured final + canonical/negative validator fixtures | run opt-in integration oracle |
| B-016 | current-run implementation authority | covered | product decision | D-009 superseded; root-only lease использовал session-start strongest/high-effort effective route | closure review |
| B-017 | risk-matched implementation tiers | covered | product decision | D-010, AC-06/15: native fast/balanced/strong profiles with evidence-only escalation | validate contract and forward-test |
| B-018 | method preservation across tiers | covered | product decision | D-012, AC-16: TDD/minimality/single-writer/handoff/review unchanged | run full validator and review |
| B-019 | runtime-safe role identifiers and backward compatibility | covered | product decision | D-013: canonical underscores + permission-gated guided migration, no silent overwrite/delete | M3 implementation |
| B-020 | host selector ownership and supported-surface boundary | covered | product decision | D-014: two deliverables, no adapter; host selector/envelope is explicit external prerequisite | M4 contract/implementation |
| B-021 | Spark as primary search route | covered | product decision | D-015 + official custom-agent/pricing evidence | preserve exact-selection oracle in later AC update |
| B-022 | exact wire schema, config resolution and envelope provenance | covered | technical decision | T-002 + Host contract v1 + AC-18/22 | provider/consumer contract tests |
| B-023 | migration collisions, atomicity, partial failure and idempotent rerun | covered | technical decision | T-003 + Guided migration transaction + AC-17/21 | migration mutation fixtures |
| B-024 | normalized errors, breaker, cancellation and orphan writer safety | covered | technical decision | T-004 + lifecycle taxonomy + AC-03/20/23 | state-machine fixtures |
| B-025 | mixed-version compatibility and coordinated rollout/rollback | covered | technical decision | T-005 + paired compatibility matrix + AC-25 | host-first paired smoke |
| B-026 | isolation proof, fresh evidence ownership and privacy redaction | covered | technical decision | T-006 + AC-24/26 | sentinel denial + allowlist validator |

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
| Переименование task label ошибочно примут за profile selection | high/high | T-001, D-013, AC-02/19: отдельный selector + trusted envelope + negative fixture | Handled in spec |
| Repository-owned adapter расширит dependency/auth/support boundary и всё равно не получит Spark через API | medium/high | D-014 исключает adapter; host deliverable и official Spark limitation отражены в AC-18..20/M4 | Handled in spec |
| Partial migration оставляет ambiguous mixed state | medium/high | Hash-bound create-if-absent plan, legacy preservation, per-file receipt and idempotent rerun | Handled in R-013 |
| Stale/replayed host envelope доказывает неверный route | low/high | Request/dispatch IDs, exact paired revisions, profile fingerprint/generation and out-of-band metadata | Handled in R-013 |
| Timed-out writer продолжает менять files после fallback | low/critical | `termination-unknown` blocks lease release and every new writer until host acknowledgement | Handled in R-013 |
| OpenBuild 2.0 выходит раньше compatible desktop host | medium/high | T-005 host-first release gate and mixed-version fail-fast matrix | Handled in R-013 |
| Durable smoke artifact раскрывает account/path/error data | low/high | T-006 allowlist, relative/hash-only workspace data and raw-error discard | Handled in R-013 |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-015/R-011 | Spark primary search route; user prompt 2026-07-13 | No-op: existing Problem/Desired behavior/AC-03/AC-04/M3 already require Spark profile selection and honest fallback; added evidence/decision/coverage provenance only | D-001, D-004, D-007, D-011; no inferred usage claim | D-013, D-014 |
| D-013/R-012 | Canonical underscore IDs + guided migration; user reply 2026-07-13 `1a` | Header/outcome, source reconciliation, D-013, AC-01/02/06/09/10/17/19, invariants, data migration, versioning, M3/M6, B-019 and risks | D-003 config permission, D-007 trusted evidence, D-012 engineering gates, legacy files preserved until separate cleanup | none |
| D-014/R-012 | Two-track OpenBuild + host-runtime deliverables, no adapter; user reply 2026-07-13 `2a` | Outcome/scope, source reconciliation, D-014, AC-02/10/18/19/20, technical boundaries, versioning, M4/M5, B-020 and risks | D-005 owner boundary, D-007 provenance, D-011 honest metadata behavior, D-015 Spark-first | none |
| T-002..T-006/R-014 | Outcome-neutral closure mechanisms from verified R-012/R-013 critic evidence | Host preflight/dispatch v1 schema, exact error mapping, lifecycle transitions, per-entry migration authority, AC-21..26, B-022..26, paired release and privacy rules | D-003/D-004/D-007/D-011/D-012/D-013/D-014/D-015; no product direction, supported actor or observable success criterion weakened | none |

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
| R-011 | reconciliation; critic not launched while awaiting user decisions | GAPS | B-019/D-013 and B-020/D-014 | Per protocol, wait for answers before normative edits or fresh critics. |
| R-012 | product/UX; strong requested, observed unknown | GAPS | selector-vs-metadata conflation, collision/recovery, error taxonomy, mixed-version rollout, correlated evidence | Verified; no D-013/D-014 reopen. Addressed by T-002..T-005, AC-21..26 and R-013 contract sections. |
| R-012 | architecture/data/security; strong requested, observed unknown | GAPS | exact schema/provenance, config snapshot, transaction/idempotency, isolation, cancellation race, paired release, redaction | Verified; no product-direction reopen. Addressed by T-002..T-006, AC-21..26, B-022..26 and R-013 contract sections. |
| R-013 | root adjudication; self-review limited | GAPS | Critic findings applied; fresh independent closure pending | Preserve D-013/D-014/D-015; dispatch fresh closure against R-013 only. |
| R-013 | reliability/validation closure; strong requested, observed unknown | GAPS | missing preflight operation, incomplete fallback/limitations wire fields, dispatch/child lifecycle contradiction, migration approval granularity, stale application/version receipts | Verified; addressed in R-014 without reopening D-013/D-014/D-015. |
| R-014 | root adjudication; self-review limited | GAPS | Preflight/dispatch schema, exact mapping/transitions, per-entry approval and receipts reconciled; fresh closure pending | Dispatch fresh closure against stable R-014. |
| R-014 | reliability/validation final closure; strong requested, observed unknown | COVERED | None; AC-01..26, B-001..26, M1..M6 and decision/application receipts coherent | Accepted with high confidence; no net-new gap or reopen request. Ready gate passed. |

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

### 2026-07-13 — R-011 routing reconciliation

- Changed: только `BUILD.md` reconciliation metadata, current evidence, complete in-scope source map, D-013..D-015, T-001, B-019..B-021, risks and pending proposals; implementation requirements/AC/milestones dependent on D-013/D-014 were not changed.
- Baseline: original review baseline preserved; continuation state `main@c02b34e7372a73f7d9a7fb2bf234a81c95a429f3`, initial status clean (`## main...origin/main`).
- Search routing receipt: requested `openbuild-search-separate`; configured runtime-resolved Spark preview/`low`; exact dispatch failed before spawn because the runtime identifier rejects дефисы and no separate selector exists; observed agent/model/pool unknown; fallback `selector-unavailable`; circuit breaker open; generic read-only discovery used.
- Official evidence: custom agent `name` is source of truth; official search example uses underscore ID with Spark; per-agent `model`/`model_reasoning_effort` are supported; Spark has a separate Pro research-preview usage limit and no API availability at launch.
- Primary signal: not met — exact Spark/model/effort selection remains unperformed and unobserved.
- Validation: repository discovery and metadata-only profile audit completed; `codex.exe` probe failed with `Access is denied` and is not claimed as passed.
- Version: current manifest `1.1.1`; specification-only refine creates no commit/version bump at this decision checkpoint.
- Remaining: user answers D-013/D-014, normative application receipt, fresh high-risk complementary critics and closure.

### 2026-07-13 — R-012 decision application

- Answers: D-013=`1a`, D-014=`2a` from user reply 2026-07-13.
- Applied: canonical underscore profile IDs, permission-gated guided migration with legacy preservation, separate host-runtime selector/envelope deliverable, explicit no-adapter boundary, AC-17..20 and M3..M6.
- Preserved: Spark-first search D-015; trusted evidence D-007; no false model/pool claims D-004/D-011; Ready/TDD/minimality/single-writer/handoff/review gates D-012.
- Routing: critic route cannot exact-select `openbuild-review-strong` because the same selector is unavailable; high-risk closure uses fresh generic read-only critics with observed model/tier unknown and disclosed limited routing evidence.
- Primary signal: specification application complete; Ready gate pending complementary critics and fresh closure.
- Version: future implementation major `1.1.1 -> 2.0.0`; current specification-only refine still creates no commit.
- Remaining: adjudicate R-012 product/UX and architecture/data/security findings, update semantic revision only if needed, run fresh closure and set Ready only on `COVERED`.

### 2026-07-13 — R-014 Ready closure

- Applied critic remediation: exact `preflight` + `dispatch` wire schema, profile fingerprint/generation, exhaustive limitations and fallback mapping, separate dispatch/child lifecycle, per-entry migration authority, isolation sentinel, paired host/plugin release and sanitized fresh evidence.
- Decisions: D-013/D-014/D-015 preserved; no open/reopened product decision.
- Coverage: B-001..B-026 `covered`; no `gap` rows.
- Closure: fresh read-only reliability/validation critic, strong requested/observed unknown, `COVERED`, confidence high, no net-new gap or reopen request.
- Primary signal: specification readiness met; implementation/runtime signal remains intentionally pending M3..M6.
- Validation: `git diff --check` and specification invariant checks run after this status update; implementation/package/runtime tests not claimed in refine mode.
- Version: future implementation remains major `1.1.1 -> 2.0.0`; no specification-only commit or release action.
- Remaining: none for Ready. A later `$openbuild:build run BUILD.md` must first obtain the M4 host owner/authority and satisfy the exact risk-matched writer route.

### 2026-07-13 — R-014 implementation preflight blocked at M3

- Invocation: `$openbuild:build run BUILD.md`; Ready revision R-014 and original `main@c02b34e7372a73f7d9a7fb2bf234a81c95a429f3` baseline preserved.
- Search routing: exact `openbuild-search-separate` dispatch failed before spawn because the callable schema has no custom-agent selector and rejects the legacy hyphenated identifier; configured model `runtime-resolved Spark preview`, observed agent/model/pool `unknown`, fallback `selector-unavailable`, circuit breaker open. The generic read-only discovery fallback was interrupted after repeated bounded waits without a result (`worker-timeout`); minimum root fallback then confirmed repository ownership.
- Repository evidence: OpenBuild owns the M3 skill/reference, validator/test, bilingual documentation and version surfaces. No selector-capable `spawn_agent` host implementation or proven strong/strongest equivalent writer route exists in this repository/runtime; M4 remains an external host-runtime deliverable.
- Implementation routing receipt: risk `high`; requested agent `openbuild-implementation-strongest`; requested tier `strongest`; dispatch `unavailable`; configured model `runtime-resolved strongest-writer model`; observed agent/model `unknown`; configured sandbox `workspace-write`, runtime sandbox unverified; lease `none`; result `failed`; fallback `selector-unavailable`.
- TDD/minimality: M3 remains TDD-first and selects the existing validator/test owner layer with no new dependency or adapter. The required high-risk writer gate failed before the red test, so no test or production edit is authorized; a generic worker or underscore task label would not prove custom-agent selection.
- Primary signal: not met — neither the trusted selector/envelope nor a risk-matched writer route is available. AC-01..06/09/17..26 and M3..M6 remain pending; no false Spark/model/reasoning claim is made.
- Validation: repository ownership was mapped with targeted `rg`; no implementation/package/runtime test is claimed because the protocol stopped before code edits. `git diff --check` is run after this execution-log update.
- Version/Git: manifest remains `1.1.1`; planned implementation impact remains major `2.0.0`; no milestone commit, push, tag or publication.
- Exact unblock condition: use a host surface/repository that exposes an addressable custom-agent selector and trusted selection metadata, then prove `openbuild-implementation-strongest` (or an equivalent high-tier workspace-write route) before the M3 red edit. Access/authority to the host-runtime owner is required for M4 and the end-to-end AC-20 smoke.

### 2026-07-13 — M3 native bootstrap implementation

- Authority: user explicitly requested `реализуй M3 обычным Codex workflow как bootstrap, затем продолжи Build`; this one-time root-only bootstrap resolves the legacy-name self-block and does not weaken the Build writer gate for M4–M6.
- Changed: nine normative custom-agent IDs now use underscores; `agent_name` is separated from `task_name` in search/writer/reviewer dispatch contracts and fixtures; setup contains a hash-bound guided legacy migration; validator/tests, EN/RU docs, contributor policy, manifest and changelog are synchronized.
- TDD red: `-k canonical` failed 2/2 because the validator still required legacy hyphenated IDs and `agent`; `-k runtime_safe_profile_ids` failed all nine canonical IDs and seven migration tokens. Both failures represented the intended owner-layer mismatch.
- Focused green before review: canonical 2/2; profile migration 4/4; UsageRoutingContractTests 12/12; SearchDispatchTraceTests 7/7; ImplementationDispatchTraceTests 4/4; ReviewEscalationTraceTests 6/6.
- First wider green: full unit suite 80/80; `python scripts/validate_package.py`; Python syntax compilation; official skill `quick_validate.py`; official plugin `validate_plugin.py`; `git diff --check`.
- Fresh review finding and remediation: the first validator accepted arbitrary non-empty plan/entry IDs, approval by ID without explicit hashes, status-only receipts, and no complete detected inventory. Four new negative tests reproduced the gap. The owner validator now binds the complete supported mapping and detected inventory into canonical SHA-256 IDs, binds authority to exact hashes/action, and requires observed preconditions plus result hashes.
- Review follow-up and remediation: ordered-trace cases showed that a matching approval placed after a `created` receipt, or an approval placed before its displayed preview, still passed. Each negative test failed first; the validator now requires the strict `preview -> exact matching authority -> created receipt` sequence. A final state-machine mutation also proved and closed the missing `create-if-absent -> created|hash-drift` status constraint. Focused migration suite is 12/12 after all remediations.
- Final green after remediation: full unit suite 88/88; `python scripts/validate_package.py`; Python syntax compilation; official skill `quick_validate.py`; official plugin `validate_plugin.py`; `git diff --check`.
- Final fresh review: PASS with no remaining P0/P1 in the bounded M3 migration scope; reviewer-observed model/tier remained `unknown`, so this is repository-contract evidence rather than a runtime model-switch claim.
- Package hygiene: fixed model slugs were removed from the public task specification after the first package-validator run rejected them; Spark/strongest selection remains runtime-resolved from user configuration and no profile/model switch is claimed.
- Minimality: existing instruction/reference and deterministic trace owner layers only; no new package file, dependency, executable migrator, MCP/CLI adapter, telemetry or user-config write.
- Version: manifest `1.1.1 -> 2.0.0`, current development version on `main`; README distinguishes it from the latest published immutable `v1.1.1`; no tag/Release/publication.
- Build continuation: M3 repository half complete. M4 remains pending because this repository and callable surface still contain no `agent_name` host selector or trusted envelope; M5/M6 remain dependent on M4 and separately permitted user-profile migration/smoke.

### 2026-07-13 — v2.0.1 release publication

- Authority: user explicitly requested publication of the latest changes after the M3 commit was pushed.
- Version decision: `2.0.0` remained an untagged development commit whose README/CHANGELOG truthfully said the release did not exist. Repository policy requires every new commit to advance SemVer, so the release-metadata commit uses patch `2.0.1`; no tag is moved or reused.
- Release scope: manifest, dated CHANGELOG entry, EN/RU release wording and installation pins, and this durable record only; M3 behavior is unchanged and M4–M6 remain pending.
- Publication target: annotated tag and GitHub Release `v2.0.1` from the exact release commit after full validation and clean remote-checkout verification.
