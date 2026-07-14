# Build: Схемы README и фактический отчёт об агентах

- Status: Release pending
- Last updated: 2026-07-14
- Original request: Поставить предоставленные EN/RU схемы в самый верх соответствующих GitHub README, удалить нижние дубли и расширить финальный ответ Build фактической статистикой созданных агентов, реально выбранных моделей и выполненной работы с привязкой к пунктам ТЗ. Отдельно определить корректную зависимость от Codex CLI и допустимость его проверки/установки.
- Primary signal: README на GitHub начинаются с правильных локализованных схем без прежнего Mermaid-дубля; каждый завершённый Build-ответ содержит проверяемый реестр всех действительно созданных дочерних агентов с фактической моделью/effort или `unknown`, краткой работой, статусом и привязкой к AC/ТЗ.
- Review baseline: `main@15ff1ae9b4f13532ce76154d17939e7f83e7d7be`, исходный status clean (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: implementation
- Specification revision: R-003
- Complexity: medium — меняется публичный контракт финального ответа workflow, двуязычная документация и детерминированная contract validation; runtime данных и безопасности не затронуты.
- Implementation mode: TDD-first — финальный пользовательский контракт требует mutation-теста валидатора; перенос схем и текст документации относятся к Direct в том же milestone.
- Version impact: patch — пользователь выбрал release `2.1.1` для обратно совместимой документационной и workflow-contract доработки; commit, push, tag и GitHub Release явно авторизованы.
- Routing mode: codex-exec-explicit-model с fallback
- Discovery mode: mixed — explicit-model поиск завершился без пригодных repository evidence, встроенный Explorer превысил budget, затем использован минимальный root fallback.
- Search usage route: root-fallback — separate-pool attempt фактически запустил `gpt-5.3-codex-spark`/`low`, но Windows read-only ACL сделал результат непригодным; `openbuild_search_fallback` не настроен; role-only Explorer остановлен по timeout.
- Search routing receipt: run `20260714T071613Z-8745b66618`, `openbuild_search_separate`, `codex-exec-explicit-model`, configured/observed `gpt-5.3-codex-spark`, effort `low`, read-only, `turn.completed`, exit `0`, result file valid, semantic result `unusable-evidence`; затем `openbuild_search_fallback` -> `profile-not-discoverable`, Explorer -> `worker-timeout`, root fallback.
- Implementation model route: native bounded fallback — exact `openbuild_implementation_balanced` завершился pre-spawn `profile-not-discoverable`; matching native writer получает single-writer lease, actual model/effort остаются `unknown` без runtime metadata.

## 1. Outcome

### Problem

В обоих README workflow-схема находится ниже release/history-текста как Mermaid-блок, поэтому GitHub-страница не открывается визуальным объяснением продукта. Финальный контракт Build перечисляет route/model metadata по отдельным этапам, но не требует компактно показать пользователю общее число фактически созданных агентов, их реальные модели, выполненную работу, статус и связь с требованиями. Из-за этого configured intent можно спутать с реальным запуском, а неуспешные или прерванные попытки остаются незаметными.

README упоминают Codex CLI в отдельных разделах, но общий Requirements не отделяет обязательность CLI для explicit-model `codex exec` от работоспособности native/root fallbacks. Plugin manifest не содержит lifecycle/install hook, который мог бы безопасно установить внешний host CLI.

### Desired behavior

1. Основной `README.md` сразу после заголовка показывает `Workflow-en.png`; `README.ru.md` — `Workflow-ru.png`.
2. Старые локализованные Mermaid-блоки `Workflow at a glance` / `Workflow в одной схеме` удалены, чтобы схема не дублировалась.
3. Mermaid-схемы в `How usage-aware model routing works` и `How adaptive implementation delegation works` заменены соответственно на `usage-en.png`/`usage-ru.png` и `delegat-en.png`/`delegat-ru.png`.
4. Каждый финальный Build-ответ имеет короткий локализованный раздел `Agents` для английского ответа или `Агенты` для русского с числом реально созданных дочерних agent runs и одной строкой на run.
5. Строка агента содержит роль/задачу, фактическую модель и reasoning effort по runtime evidence либо `unknown`, фактический status/outcome, краткую выполненную работу и связанные `AC-##`, milestone или пункт ТЗ, если связь существует.
6. Pre-spawn dispatch failures не увеличивают число созданных агентов, но перечисляются отдельно, если повлияли на route/fallback. Wrapper PID и запущенный им `codex exec` считаются одним логическим agent run.
7. Configured/requested model никогда не выдаётся за фактическую без подтверждённого selection evidence. Completed process с непригодным результатом показывается как созданный, но не как полезно завершивший задачу.
8. До первого CLI-agent dispatch Build выполняет OS-aware preflight: Windows — `python --version`, POSIX — сначала `python3 --version` с допустимым fallback на `python --version`; `codex --version` выполняется везде. Windows install-команды показываются только на Windows; POSIX получает ручную platform-appropriate guidance без автоматического выбора package manager. Build предлагает пользователю установить и ответить после завершения либо отдельно разрешить выполнить применимую показанную команду, затем ждёт установки и ручного ChatGPT sign-in.

### In scope

- Верхняя EN/RU workflow-схема, usage-aware и delegation EN/RU схемы, удаление шести соответствующих Mermaid-блоков.
- Финальный output contract Build и долговечный agent activity ledger в spec template.
- Детерминированная validator/mutation coverage нового контракта.
- Двуязычное объяснение реального agent/model отчёта и интерактивного CLI preflight/install checkpoint.
- Версия `2.1.1`, dated changelog, синхронные README release pins, commit/push/tag/GitHub Release.

### Out of scope

- Тихая автоматическая установка внешнего Codex CLI без отдельного разрешения пользователя в конкретном run.
- Изменение Codex host/runtime, provider routing, usage dashboard или модели root-agent.
- Package registry publication; Git tag/GitHub Release `v2.1.1` входят в scope.
- Изменение старого `BUILD.md` и локального `TZ.md` другой задачи.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| EN README | `README.md:45` | `Workflow at a glance` начинается после release history и содержит Mermaid. | Блок нужно заменить верхним image reference и удалить дубль. |
| RU README | `README.ru.md:45` | `Workflow в одной схеме` повторяет локализованный Mermaid. | Нужен отдельный RU asset. |
| Image assets | `plugins/openbuild/lib/Workflow-en.png`, `Workflow-ru.png`, `usage-en.png`, `usage-ru.png`, `delegat-en.png`, `delegat-ru.png` | Пользователь поместил все шесть source PNG в plugin tree; root визуально проверил локализацию и читаемость. | Asset authority закрыта без реконструкции preview. |
| Final output owner | `plugins/openbuild/skills/build/SKILL.md:248` и `:260` | `Complete the workflow` задаёт финальный user-facing report, но не агрегирует agents. | Это owner layer пользовательского ответа. |
| Durable state | `plugins/openbuild/skills/build/references/spec-template.md:1` | Template уже хранит отдельные search/implementation/review receipts, но не единый agent ledger. | Реестр можно собрать без нового runtime service. |
| Runtime evidence | `plugins/openbuild/skills/build/references/model-routing.md:16` | Explicit runner фиксирует model, effort, sandbox, PIDs, terminal event и result evidence. | Эти receipt — источник фактической модели explicit runs. |
| CLI invocation | `plugins/openbuild/skills/build/scripts/agent_runner.py:2`, `:552`, `:774` | Runner запускает Codex CLI, проверяет ChatGPT login и имеет явный `cli-unavailable` failure. | CLI обязателен для exact process route, но failure уже маршрутизируется. |
| Official Windows install | `https://learn.chatgpt.com/docs/codex/cli` | Официальный standalone installer: `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 \| iex"`; npm не требуется. | Можно дать zero-prerequisite PowerShell path и выполнить его только после явного согласия. |
| Plugin manifest | `plugins/openbuild/.codex-plugin/plugin.json` | Manifest содержит metadata/skills, но не installer hook. | Плагин не должен тайно ставить host dependency. |
| Validation owner | `scripts/validate_package.py:2726`, `scripts/test_validate_package.py:1315` | Usage-routing contract и mutation tests уже проверяют двуязычные route/model promises. | Новый report contract должен жить рядом. |
| Version source | `plugins/openbuild/.codex-plugin/plugin.json:3` | Текущая версия `2.1.0`; repository policy требует уникальный bump на commit. | Пользователь авторизовал patch release `2.1.1`. |

### Source of truth

`SKILL.md` владеет обязательным финальным ответом; `spec-template.md` владеет долговечным журналом; terminal runner/native receipts владеют фактом model/effort/status. README только объясняют контракт, а validator защищает его от drift.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD-agent-usage-report.md` | текущий user request / root record | R-003 | D-001–D-003, AC-01–AC-08 | Прямых normative companions нет; repository evidence перечислены выше. | yes | aligned; Ready after closure adjudication |

`BUILD.md` и `TZ.md` прочитаны как существующие документы другой, более широкой задачи маршрутизации; новый root не объявляет их companions и не меняет их решения.

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| Новый report contract против существующих receipts | locked request propagated without semantic change | D-001, user request 2026-07-14 | aligned |
| CLI fallback против correct CLI spawning | explicit user decision | D-002, user reply 2026-07-14: installer prompt/delegation/wait | aligned |
| Requested diagrams против отсутствующих binaries | explicit asset provenance | D-003, user reply 2026-07-14 + six files in `plugins/openbuild/lib/` | aligned |

### Gap

Fresh balanced-profile dispatch не был доступен; fresh native generalist critic завершился с `GAPS`. Root применил все четыре новые группы замечаний в R-003: полный состав logical agents, точные CLI/Python команды, self-contained wording и repository release-smoke. Blocking gaps отсутствуют; revision `Ready`.

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | build.final.agent-activity | user | resolved | Что показывать о делегированных agents? | Количество, реально запущенные модели, краткую работу и связь с пунктами ТЗ. | Текущий user request. | Определяет AC-03–AC-05. |
| D-002 | install.codex-cli.behavior | user | resolved | Как вести себя с Codex CLI при установке/запуске? | Проверить CLI OS-aware; на Windows при отсутствии дать zero-prerequisite PowerShell command, на POSIX — manual platform-appropriate guidance без автоматического выбора package manager; ждать ручной установки или предложить применимую делегированную установку с отдельным разрешением; затем дождаться ручного sign-in. | User reply 2026-07-14 + R-003 portability application preserving the Windows command specifically requested by the user. | Определяет AC-07 и CLI dependency checkpoint. |
| D-003 | docs.diagram.assets-and-release | user | resolved | Какие assets и release использовать? | Шесть PNG из `plugins/openbuild/lib/`; release `2.1.1` с commit, push, tag и GitHub Release. | User reply 2026-07-14. | Определяет AC-01–AC-03 и AC-08. |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Один logical agent run на созданный child thread/process; pre-spawn failure отдельно. | selected | Runner имеет wrapper и Codex PID одного run; native agent имеет один thread. | Сохраняет точный requested count без двойного счёта. |
| T-002 | `actual model` берётся только из accepted explicit selection/runtime metadata; иначе `unknown`. | selected | Существующий model-routing contract запрещает inference из slug/profile intent. | Выполняет D-001 и не ослабляет честность routing. |
| T-003 | Ledger хранится в spec template и синтезируется SKILL финальным ответом. | selected | Уже существуют per-stage receipts; новый service/dependency не нужен. | Выполняет D-001 минимальным owner-layer change. |
| T-004 | Использовать официальный Windows standalone installer для CLI, а Python 3.11+ проверять отдельно. | selected | Official Codex CLI page exposes built-in PowerShell `irm ... install.ps1 \| iex`; installer execution remains approval-gated, auth stays manual. Если Python отсутствует, Windows-подсказка использует `winget install -e --id Python.Python.3.12`, а при отсутствии `winget` отправляет на официальный python.org installer. | Выполняет D-002 без скрытого Node/npm dependency или credential automation. |
| T-005 | Сохранить визуальный язык предоставленных PNG, но исправить connector semantics, противоречащие normative safety/review contract. | selected | Independent visual review и root inspection подтвердили инвертированный RU review flow и dispatch-before-lease в delegation pair; правка сделана precise-object-edit через imagegen и визуально перепроверена. | Выполняет AC-02/AC-03 без ослабления single-writer/review порядка. |

### Pending proposals

- None.

## 4. User scenarios

### Primary scenario

1. Пользователь запускает `$openbuild:build` для задачи с поиском, writer и review.
2. Build записывает logical agent runs по мере фактического spawn и terminal evidence.
3. В финале пользователь видит общий count и компактную таблицу с actual model/effort, работой, status и AC/ТЗ.

### Errors and edge cases

- Profile resolution падает до child spawn -> count не растёт; failure перечисляется отдельно.
- Child создан, но timeout/cancel/unusable evidence -> count растёт, status честно показывает failure/partial/no usable work.
- Runtime не раскрывает model/effort -> `unknown`, requested/configured можно показать отдельно, но не в колонке actual.
- Один runner создаёт wrapper и `codex exec` -> считается одним агентом.
- Agent работал на общий discovery без точного AC -> связь указывается как milestone/spec section, не выдумывается.

## 5. Requirements and acceptance criteria

- [x] AC-01: `README.md` показывает `Workflow-en.png` сразу после H1/языковой навигации; `README.ru.md` симметрично показывает `Workflow-ru.png`; старые workflow Mermaid-блоки отсутствуют.
- [x] AC-02: usage-aware sections показывают `usage-en.png`/`usage-ru.png` вместо текущих Mermaid-блоков.
- [x] AC-03: adaptive delegation sections показывают `delegat-en.png`/`delegat-ru.png` вместо текущих Mermaid-блоков.
- [x] AC-04: `SKILL.md` требует финальный локализованный раздел `Agents`/`Агенты` с числом фактически созданных logical agent runs и строкой для каждого search, critic, implementation, review и native/generic fallback run.
- [x] AC-05: каждая строка содержит роль/задачу, actual model и effort либо `unknown`, terminal status/outcome, краткую фактическую работу и AC/milestone/ТЗ mapping либо честное `none`.
- [x] AC-06: contract различает created agent, failed pre-spawn dispatch и wrapper/Codex process, не выдаёт configured/requested model за actual и не скрывает unusable/cancelled runs; `spec-template.md`, EN/RU README и mutation tests фиксируют одинаковый contract.
- [x] AC-07: до exact CLI dispatch Build выполняет OS-aware Python preflight (Windows `python`; POSIX `python3` first с `python` fallback) и `codex --version` везде; exact `winget`/PowerShell команды показывает только Windows, POSIX получает manual platform-appropriate guidance без автоматического package-manager выбора; Build предлагает manual/delegated-with-separate-approval installation, ждёт install, затем просит пользователя выполнить `codex`, пройти ручной ChatGPT sign-in и подтверждает `codex login status`; credentials не автоматизируются.
- [ ] AC-08: manifest/README/CHANGELOG синхронизированы на `2.1.1`; validation и balanced review green; commit/main push, immutable tag `v2.1.1` и GitHub Release опубликованы.

### Invariants

- Существующие receipts, Ready/TDD/single-writer/review gates и fallback semantics не ослабляются.
- Никакие secrets, private usage data, raw prompts или private run paths не попадают в user-facing agent table.
- Результат не заявляет фактическую модель без runtime/accepted explicit-dispatch evidence.
- EN/RU документация остаётся семантически симметричной.

## 6. Technical boundaries

### Affected layers and contracts

- `README.md`, `README.ru.md`, шесть image assets — GitHub presentation.
- `plugins/openbuild/skills/build/SKILL.md` — final synthesis owner.
- `plugins/openbuild/skills/build/references/spec-template.md` — durable activity ledger.
- `plugins/openbuild/skills/build/references/model-routing.md` — CLI/Python dependency checkpoint и источник exact-run evidence.
- `scripts/validate_package.py`, `scripts/test_validate_package.py` — deterministic contract owner.
- Manifest/CHANGELOG/README version notes — synchronized version surfaces.

### Data and migration

Schema/persistence migration не требуется. Legacy BUILD files без ledger могут показывать сведения из доступных receipts; отсутствующие historical facts остаются `unknown`, не восстанавливаются догадкой.

### Security and privacy

Пользовательский отчёт не содержит PID, thread ID, private run directory, raw stderr/JSONL, auth details или usage tokens. Автоустановка CLI без отдельного разрешения запрещена.

### Performance and concurrency

Новый ledger — небольшой Markdown record; дополнительных agents и сетевых вызовов ради отчёта нет.

### Observability and errors

Created/failed/interrupted/unusable status сохраняется. Pre-spawn failures перечисляются отдельно с нормализованной причиной.

### Versioning and release

Authoritative source: `plugins/openbuild/.codex-plugin/plugin.json`. План: patch `2.1.0 -> 2.1.1`, dated changelog, README release pins, immutable tag и GitHub Release; публикация явно авторизована пользователем.

## 7. Validation and review

- Primary signal: mutation validator отклоняет удаление count/actual-model/status/work/spec-mapping/CLI checkpoint semantics, package validation green, все шесть README image links/positions проверены.
- Red signal: новые mutation tests должны падать до добавления report contract.
- Minimality decision: reused existing receipts + custom owner-layer instructions/validator; новый runtime aggregator и dependency не нужны.
- Focused green: `python -m unittest scripts.test_validate_package.UsageRoutingContractTests`.
- Targeted checks: `python scripts/validate_package.py --no-commit-gate`; `python -m unittest scripts.test_validate_package`.
- Wider checks: `python -m unittest discover -s scripts -p "test_*.py" -v`; `python scripts/validate_package.py`; `git diff --check`; staged `git diff --cached --check` и `python scripts/validate_package.py --commit-gate`.
- Maintainer/release checks: official skill/plugin validators when callable; clean local plugin and standalone installs; relevant CLI-agent forward/runtime smoke; remote install from candidate commit/ref; fresh full-diff review; after publication verify public tag resolves to the reviewed commit and GitHub Release is visible without credentials. Unavailable authority/tooling is reported honestly, not imitated.
- Manual/runtime check: проверить верх обоих README, три локализованные image pairs и официальный PowerShell installer wording; installer в текущем run не выполнять, поскольку CLI уже установлен.
- Starting review tier: balanced (medium).
- Required final tier: balanced.
- Review focus: truthfulness of actual-model attribution, count semantics, fallback visibility, bilingual parity, CLI boundary and image placement.

## 8. Milestones

### M1. Public diagrams and truthful agent report

- Status: Release pending
- Scope: AC-01–AC-08.
- Excludes: silent CLI install, credential automation, host runtime/package registry.
- Implementation mode: TDD-first with Direct documentation/assets.
- Delegation: bounded-worker — exact `openbuild_implementation_balanced` pre-spawn failure recorded; native fallback owns lease `M1-agent-report-cli-r003` and only the exact task file list from its prompt.
- Red signal: mutation tests for removed agent count/model evidence/status/work/spec mapping fail.
- Minimality decision: reuse receipts and existing validator; no runtime service/dependency.
- Focused green: `python -m unittest scripts.test_validate_package.UsageRoutingContractTests`.
- Validation: package/unit/diff checks above.
- Acceptance: AC-01–AC-08.
- Review: Pending — `openbuild_review_balanced` after root handoff.
- Version: `2.1.0 -> 2.1.1`.
- Commit: Pending.

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome/scope/success | covered | product decision | D-001–D-003, AC-01–AC-08 | none |
| B-002 | image asset authority | covered | new authority | D-003 + six visually verified PNG files | none |
| B-003 | actual model truth | covered | technical decision | T-002 + existing terminal receipts | validate mutations |
| B-004 | failed/interrupted and all agent roles | covered | critic application | T-001, AC-04–AC-05 enumerate search/critic/implementation/review/native/generic runs | validate mutations |
| B-005 | CLI/Python install behavior | covered | critic application | D-002 + exact Python/CLI/auth commands in AC-07 | validate checkpoint contract |
| B-006 | privacy/secrets | covered | repository fact | no PID/path/raw logs in report invariant | reviewer audit |
| B-007 | localization/GitHub presentation | covered | product decision | D-001 + explicit EN/RU request | visual link check |
| B-008 | data/migration | not applicable | repository fact | Markdown workflow contract only | none |
| B-009 | performance/concurrency | not applicable | repository fact | no extra spawn/network path | none |
| B-010 | compatibility/rollback | covered | critic application | README must qualify self-contained packaging versus host Codex CLI/Python prerequisites; legacy specs use unknown | reviewer audit |
| B-011 | validation/version/release | covered | critic application | D-003 + CONTRIBUTING maintainer/release checklist, candidate/runtime/clean-install/public verification | run available commands and publish `v2.1.1` |
| B-012 | image count and CLI owner map | covered | critic application | Technical boundaries now names six assets and `model-routing.md` | none |
| B-013 | exact zero-prerequisite commands | covered | duplicate of B-005 applied | AC-07 has exact copy-paste commands | mutation validation |
| B-014 | complete logical-agent population | covered | duplicate of B-004 applied | AC-04 enumerates every agent role/fallback | mutation validation |
| B-015 | complete release plan/stale version | covered | duplicate of B-011 applied | validation includes repository policy gates; stale `2.2.0` removed | release verification |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Configured model mistaken for actual | medium/high | actual-only evidence rule + mutation test | Handled |
| Failed process hidden from count | medium/medium | created-run count + explicit status/outcome | Handled |
| Double count wrapper and Codex PID | medium/medium | logical run identity T-001 | Handled |
| Wrong/low-quality image committed from preview | low/medium | use only D-003 local source PNG; root visual verification completed | Handled |
| Plugin silently installs host CLI | low/high | explicit per-run authority before exact official command; manual auth only | Handled |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-002 | user request 2026-07-14: real agent count/model/work/spec mapping | AC-04–AC-06, M1 | truthfulness/privacy/fallback invariants | none |
| D-002/R-002 | user reply 2026-07-14: prompt/manual-or-delegated install/wait | AC-07, M1, CLI boundary | explicit approval and manual-auth invariants | none |
| D-003/R-002 | user reply 2026-07-14: six local PNG + release 2.1.1 | AC-01–AC-03, AC-08, M1 | localization/version immutability | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | root generalist | GAPS | image binary, D-002 | B-002/B-005 closed by user reply and R-002 application receipts |
| R-002 | native generalist / requested balanced, observed unknown | GAPS, high confidence | B-004/B-005/B-010/B-011 plus B-012–B-015 | Все замечания приняты и применены в R-003: exact commands, Python checkpoint, role enumeration, owner/image count, self-contained wording и full release validation; decisions не переоткрыты. |
| R-003 | root closure adjudication | COVERED | none | Ready — все applicable coverage IDs закрыты или N/A. |

## 10. Open questions

Blocking product questions:

- None.

Blocking new authority:

- None.

Non-blocking assumptions:

- Assets сохраняются в user-provided `plugins/openbuild/lib/`; переименование бинарников не требуется.

## 11. Agent activity ledger

Created logical agent runs: 9.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | `openbuild_search_separate` / README-report-CLI discovery | `gpt-5.3-codex-spark` | `low` | completed process, unusable evidence | Пытался исследовать AC-01–AC-07; workspace read заблокирован ACL, полезная карта не получена. | terminal `turn.completed`, exit 0, observed model/effort; semantic `unusable-evidence` |
| A-002 | yes | built-in Explorer / repository owner map | `unknown` | `unknown` | interrupted, worker-timeout | Пытался найти owner files/tests для AC-01–AC-07; результат не получен в budget. | native agent created; runtime model metadata absent; interrupted by root |
| A-003 | yes | fresh native generalist / R-002 closure critic | `unknown` | `unknown` | completed, GAPS/high confidence | Проверил AC-01–AC-08; выявил точные команды, Python prerequisite, полный agent population и release-smoke gaps, применённые в R-003. | native agent terminal result; runtime model metadata absent |
| A-004 | yes | native bounded implementation writer / M1 + remediations | `unknown` | `unknown` | completed, usable handoffs | Добавил TDD contract, six-image presentation, ledger/report, CLI/Python checkpoint и version docs; исправил POSIX portability и локализовал финальный `Agents`/`Агенты` contract. | native terminal handoffs; focused 19 → 20 → 21 green; runtime model metadata absent |
| A-005 | yes | `openbuild_search_separate` / release runtime smoke | `gpt-5.3-codex-spark` | `low` | completed, usable | Read-only проверил текущий README, верхний H1 и путь workflow image; подтвердил real CLI dispatch для AC-08. | accepted explicit selection, terminal `turn.completed`, exit 0, valid result |
| A-006 | yes | fresh native full-diff reviewer / release 2.1.1 | `unknown` | `unknown` | completed, REJECT/high confidence | Подтвердил AC-01–AC-06, нашёл POSIX portability gap в AC-07 и потребовал OS-aware remediation до AC-08. | native terminal review; score 7/10, runtime model metadata absent |
| A-007 | yes | fresh native changed-diff reviewer / POSIX remediation | `unknown` | `unknown` | completed, REJECT/high confidence | Подтвердил OS-aware implementation, нашёл stale Windows-centric wording в spec и несогласованный `Agent usage` против `Agents`/`Агенты`. | native terminal review; score 7.5/10, runtime model metadata absent |
| A-008 | yes | fresh native full-diff reviewer / localized-heading remediation | `unknown` | `unknown` | completed, REJECT/high confidence | Подтвердил текстовые remediations; визуально выявил ошибочные review arrows в `usage-ru` и dispatch-before-lease в обеих delegation схемах, плюс stale D-002. | native terminal review; score 7.5/10, runtime model metadata absent |
| A-009 | yes | fresh native final full-diff reviewer / corrected assets | `unknown` | `unknown` | completed, ACCEPT/high confidence | Проверил финальный текстовый diff и все шесть PNG; подтвердил AC-01–AC-07 без actionable findings. | native terminal review; score 9.7/10, runtime model metadata absent |

Pre-spawn dispatch failures (не входят в created count): `openbuild_search_fallback` -> `profile-not-discoverable`; `openbuild_review_balanced` spec critic -> `profile-not-discoverable`; `openbuild_implementation_balanced` M1 writer -> `profile-not-discoverable`; `openbuild_review_balanced` full-diff review -> `profile-not-discoverable`.

## 12. Execution and validation log

### 2026-07-14 — discovery/reconciliation

- Changed: создан отдельный root spec; старый `BUILD.md` сохранён без изменений.
- Routing: 2 logical agents фактически созданы; 1 explicit Spark run завершился с unusable evidence, 1 Explorer остановлен по timeout; затем root fallback.
- Primary signal: not met — implementation не начата до закрытия B-002/D-002.
- Validation: Git baseline clean; repository owners/version/docs найдены; implementation checks не запускались.
- Minimality decision: reuse existing receipts and validator; no new runtime service/dependency.
- Review: root self-audit found two blocking gaps; user closed them, then fresh native critic found four completeness gaps and root applied all in R-003.
- Version: planned patch `2.1.0 -> 2.1.1`; unchanged on disk.
- Commit: not created.
- Remaining: balanced writer fallback, root validation/review, commit/push/tag/release `2.1.1`.

### 2026-07-14 — M1 implementation handoff

- Changed: девять разрешённых owner files; user-provided PNG не редактировались.
- Routing: exact balanced writer pre-spawn failure, затем один native bounded writer под lease `M1-agent-report-cli-r003`; usable handoff принят, lease released.
- Primary signal: partially met — AC-01–AC-07 реализованы; AC-08 ожидает root validation/review/publication.
- Validation: meaningful red — 19 tests / 23 expected contract failures; worker green — 19 focused, 129 package-validator tests, 193 discovery tests with 3 POSIX-only skips, package validator and diff check green.
- Minimality decision: reused existing receipts, Markdown spec template and deterministic validator; no runtime aggregator/dependency added.
- Review: pending fresh full-diff reviewer.
- Version: patch `2.1.0 -> 2.1.1` synchronized in manifest/changelog/README by worker; publication pending.

### 2026-07-14 — root validation

- Changed: test import strengthened to call the new validator directly; source behavior unchanged.
- Routing: packaged Spark runtime smoke completed as A-005 with accepted explicit selection.
- Primary signal: met for AC-01–AC-07; AC-08 validation gates green before review/publication.
- Validation: 19 focused tests OK; package validator OK; full 193 tests OK with 3 POSIX-only skips; plugin clean install recognized/enabled `2.1.1`; standalone clean install exact SHA-256 match for 14 files; Python 3.13.7, Codex CLI 0.144.3 and ChatGPT login confirmed; `git diff --check` clean.
- Minimality decision: no additional implementation needed after root diff audit.
- Review: fresh full-diff review pending.
- Version: manifest/docs/changelog remain synchronized at `2.1.1`.

### 2026-07-14 — full-diff review 1

- Changed: none; reviewer read-only.
- Routing: exact balanced review pre-spawn failure, then fresh native full-diff reviewer A-006.
- Primary signal: not met — AC-07 partial because portable instructions required `python` and Windows installers unconditionally.
- Validation: prior green evidence accepted; reviewer identified missing POSIX mutation coverage.
- Minimality decision: targeted OS-aware checkpoint remediation in existing owner files; no new dependency or abstraction.
- Review: REJECT, high confidence, score 7/10; one MEDIUM portability finding.
- Version: remains unpublished `2.1.1`.
- Remediation lease: `M1-posix-dependency-remediation-r003`; single returning native writer, exact allowed owner files only.

### 2026-07-14 — POSIX checkpoint remediation

- Changed: OS-aware dependency text and validator contract in seven existing owner files; version stayed `2.1.1`.
- Routing: returning A-004 native writer under remediation lease; no new logical agent created, handoff accepted and lease released.
- Primary signal: met — new focused mutation test produced 7 expected failures before implementation, then 20 tests green.
- Validation: package validator green; 194 full tests green with 3 POSIX-only skips; `git diff --check` clean; root independently repeated 20 focused and package validation green.
- Minimality decision: OS switch remains instruction-level text and deterministic contract; no runtime dependency/package-manager abstraction.
- Review: fresh changed-diff reviewer pending; previous REJECT cannot close the changed diff.
- Version: unpublished `2.1.1`, no additional bump required inside the same commit.

### 2026-07-14 — full-diff review 2

- Changed: none; reviewer read-only.
- Routing: fresh native changed-diff reviewer A-007; balanced exact profile circuit remained open after recorded pre-spawn failure.
- Primary signal: not met — implementation portability accepted, but spec AC-07 was stale and final section name drifted.
- Validation: green implementation signals accepted; package validator correctly does not treat task-specific BUILD as package input.
- Minimality decision: root updates task spec; returning writer changes only localized-heading owner contract and its mutation tests.
- Review: REJECT, high confidence, score 7.5/10; one MEDIUM spec drift and one LOW localization finding.
- Version: remains unpublished `2.1.1`.
- Remediation lease: `M1-localized-agent-heading-r003`; same returning logical writer A-004, no new agent creation.

### 2026-07-14 — localized heading remediation

- Changed: localized final heading contract and deterministic coverage in five existing owner files; task spec updated separately by root.
- Routing: returning A-004 under lease `M1-localized-agent-heading-r003`; no new logical agent, handoff accepted and lease released.
- Primary signal: met — new mutation test produced 3 expected failures before implementation; final `Agents`/`Агенты` contract aligned with both README.
- Validation: 21 focused tests, package validator and diff check green in worker and root; worker full suite 195 green with 3 POSIX-only skips.
- Minimality decision: no README/runtime change beyond existing localized public promise.
- Review: third fresh changed-diff review pending.
- Version: unpublished `2.1.1`.

### 2026-07-14 — full-diff review 3 and image remediation

- Changed: reviewer read-only; root затем синхронизировал D-002 и precise-edited `usage-ru.png`, `delegat-en.png`, `delegat-ru.png` с помощью built-in imagegen.
- Routing: fresh native reviewer A-008; image generation/edit calls не являются spawned agents и не входят в agent count.
- Primary signal: initially not met — three supplied diagrams contradicted normative review/lease order; corrected assets now show `да → completion`, remediation → next-tier → review, and lease → exact dispatch → red signal.
- Validation: root visually inspected original and corrected full-resolution PNG; all text/style/layout outside targeted connectors/order preserved to the practical visual signal.
- Minimality decision: three precise raster edits instead of weakening owner contract, redrawing every image or adding runtime code.
- Review: REJECT before remediation, high confidence, score 7.5/10; fresh changed-diff review required.
- Version: unpublished `2.1.1`.

### 2026-07-14 — full-diff review 4

- Changed: none; reviewer read-only.
- Routing: fresh native final reviewer A-009; balanced exact profile remained unavailable from the recorded pre-spawn circuit.
- Primary signal: met — AC-01–AC-07 covered, release portion of AC-08 ready.
- Validation: reviewer independently repeated 21 focused tests, package validator and diff check; all green; visually checked all six PNG.
- Minimality decision: accepted final owner-layer and asset changes; no further implementation.
- Review: ACCEPT, high confidence, score 9.7/10, findings none.
- Version: `2.1.1` ready for root-owned commit/push/tag/GitHub Release.
