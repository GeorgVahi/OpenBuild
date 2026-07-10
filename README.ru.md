# OpenBuild

[English version](README.md)

OpenBuild — workflow для Codex, который превращает идею простыми словами или существующее ТЗ в проверенную по репозиторию спецификацию и, когда это запрошено, в протестированную реализацию с делегированным поиском кода, TDD-first milestones и прогрессивным review.

В plugin входит один явно вызываемый skill **Build** с пятью режимами:

- `new` — создать спецификацию и остановиться до изменений кода;
- `refine` — проверить и улучшить существующую спецификацию без изменений кода;
- `run` — выполнить готовую или дополняемую спецификацию;
- `full` — пройти путь от идеи до реализации, проверок и review;
- `setup-models` — при желании настроить read-only профили уровней моделей с отдельным разрешением.

OpenBuild самодостаточен. Ему не нужны отдельные discovery-, TDD- или review-skills, telemetry, внешний сервис или фоновые сетевые процессы.

> OpenBuild `v0.2.0` — текущий релиз. Для воспроизводимости устанавливайте tag версии; используйте `main` только если осознанно хотите последний development-коммит.

На этой границе релиза текущий manifest указывает plugin version `0.2.0`, синхронизированную с immutable release tag `v0.2.0`.

## Требования

- Актуальная поверхность Codex с поддержкой skills. Установка plugins доступна в Codex CLI и поддерживаемых plugin-поверхностях.
- Git, если Build должен создавать milestone-коммиты или проверять task diff.
- Для `v0.2.0` нативно проверен Windows. Документация для macOS и Linux считается best-effort до отдельных нативных проверок.

OpenBuild `v0.2.0` поддерживает только Codex. Совместимость с Claude Code, Cursor, Gemini CLI и другими coding agents не заявляется.

## Установка как plugin — рекомендуется

Plugin — основной канал распространения. Он даёт версионированную установку через marketplace и namespaced-вызов `$openbuild:build`.

### Закреплённый релиз `v0.2.0`

```bash
codex plugin marketplace add GeorgVahi/OpenBuild --ref v0.2.0
codex plugin add openbuild@openbuild
```

Начните новый Codex thread и проверьте установку:

```bash
codex plugin list
```

Явный вызов:

```text
$openbuild:build new Добавить сохранённые поиски в приложение
```

### Preview из `main`

```bash
codex plugin marketplace add GeorgVahi/OpenBuild --ref main
codex plugin add openbuild@openbuild
```

Обновление установки из `main`:

```bash
codex plugin marketplace upgrade openbuild
codex plugin add openbuild@openbuild
```

### Переход между release tags

Versioned/tag-pinned marketplace закреплён за выбранным tag. Для перехода на другую версию удалите установленный plugin и запись marketplace, затем добавьте новый tag:

```bash
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
codex plugin marketplace add GeorgVahi/OpenBuild --ref v0.2.0
codex plugin add openbuild@openbuild
```

Замените `v0.2.0` на нужный release tag.

### Удаление plugin

```bash
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
```

## Установка как standalone skill

Standalone-установка даёт короткий вызов `$build`. Попросите предустановленный системный skill-installer установить canonical папку Build:

```text
Используй $skill-installer и установи skill из https://github.com/GeorgVahi/OpenBuild/tree/v0.2.0/plugins/openbuild/skills/build
```

После установки начните новый Codex thread. Откройте `/skills` или введите `$`, убедитесь, что появился `build`, и вызовите:

```text
$build new Добавить сохранённые поиски в приложение
```

Installer не перезаписывает существующую папку `$CODEX_HOME/skills/build`. При обновлении сначала проверьте её, осознанно сделайте backup или удалите и повторите установку. Для удаления standalone-версии удалите только подтверждённую папку `$CODEX_HOME/skills/build` и перезапустите Codex.

Plugin и standalone используют одну canonical source-папку; дублирующихся реализаций в репозитории нет.

## Использование

### 1. Создать спецификацию с нуля

Plugin:

```text
$openbuild:build new Добавить список желаний в существующий магазин
```

Standalone:

```text
$build new Добавить список желаний в существующий магазин
```

Build:

1. изучит текущий репозиторий и применимые `AGENTS.md`;
2. зафиксирует Git- или artifact-baseline;
3. по возможности делегирует широкий поиск кода ограниченным read-only discovery workers, затем проверит их evidence map;
4. задаст только оставшиеся продуктовые вопросы с короткими ответами вида `1а 2б`;
5. создаст `BUILD.md` на языке пользователя;
6. остановится до реализации.

Пример вопроса:

```text
1. Кто может сохранять список желаний?
   а) Только авторизованные пользователи; список привязан к аккаунту.
   б) Также гости; локальный список может объединиться после входа.
   Рекомендация: 1а — в первой версии не потребуется отдельная политика merge.

Можно ответить: 1а
```

### 2. Улучшить существующую спецификацию

```text
$build refine BUILD.md
```

Можно передать `SPEC.md`, `TZ.md` или любой явный путь:

```text
$build refine docs/checkout-spec.md
```

Build сверит документ с текущим репозиторием, сохранит ручные правки, найдёт противоречия и unknown unknowns, обновит acceptance criteria и milestones и остановится в состоянии `Ready`. Если подходят несколько файлов или выбранный документ относится к другой задаче, Build спросит до изменений.

### 3. Выполнить спецификацию

```text
$build run BUILD.md
```

Build сначала проверит, что спецификацию можно довести до `Ready`. Затем классифицирует реализацию как `Direct`, `Investigation` или `TDD-first`, выполнит когерентные milestones, запустит проверки, проведёт progressive review, обновит журнал спецификации и создаст scoped milestone-коммиты, если политика репозитория разрешает. Push пользовательского репозитория без явного разрешения не выполняется.

### 4. Полный цикл

```text
$build full Добавить API-ключи организаций с ротацией и аудитом
```

Идея без указанного режима считается `full`:

```text
$build Добавить API-ключи организаций с ротацией и аудитом
```

`full` может менять реализацию после достижения Ready-gate. Build всё равно остановится перед разрушительными действиями, секретами, live-инфраструктурой, внешней публикацией без уже выданного разрешения или существенным расширением scope.

### 5. Настроить уровни моделей

```text
$build setup-models
```

Build сначала проверит возможности текущего Codex runtime. Если native per-subagent selector уже даёт доказанную лестницу, файлы не нужны. Иначе Build может предложить read-only профиль `openbuild-discovery` для широкого поиска кода и review-профили `openbuild-review-fast`, `balanced`, `strong` и `strongest`.

До записи Build обязан показать:

- evidence доступных моделей и reasoning efforts;
- предлагаемое распределение tiers;
- scope: пользовательский `~/.codex/agents` или проектный `.codex/agents`;
- точные пути и полный diff.

Запись выполняется только после отдельного разрешения. Существующие profiles не перезаписываются, TOML проверяется, а переключение моделей считается рабочим только после reload/new session и фактического обнаружения profiles. Отказ от setup не отключает zero-config workflow.

## Как работает автоматический поиск по коду

Перед широким листингом файлов, repository-wide search, поиском symbols, трассировкой зависимостей или картированием routes/tests/configs главный агент составляет короткий search plan и по возможности делегирует независимые ветки ограниченным read-only discovery workers. Они возвращают только evidence map: `path:line`, symbol или route, подтверждённый факт, его значение, negative results и confidence.

Главный агент остаётся оркестратором: убирает дубли, точечно перечитывает критические файлы, принимает продуктовые и архитектурные решения, редактирует, валидирует, управляет Git и отвечает пользователю. Discovery workers не редактируют код и не выбирают архитектуру.

Через `$build setup-models` профиль `openbuild-discovery` можно явно сопоставить с подходящей более экономичной моделью для поиска кода, когда mapping подтверждён runtime metadata или пользователем. OpenBuild не предполагает конкретную версию модели, не выводит стоимость из slug и не заявляет экономию, если настоящая модель скрыта. Если предпочтительный worker недоступен, исчерпал лимит или квоту, Build без дополнительного вопроса переходит к explorer, generic-subagent или root-only fallback и не блокирует задачу.

## Как работает TDD-first реализация

Изменения поведения, контрактов, validation, routing, state, auth/permissions, persistence, concurrency, integrations, security и нетривиального пользовательского поведения идут по циклу red → green → refactor. Build находит самый узкий поддерживаемый test path, по возможности фиксирует осмысленный failing signal, вносит минимальное когерентное изменение во владеющем слое, требует focused green validation и рефакторит только после green.

Для документации и косметических Direct-изменений искусственный failing test не создаётся. Investigation сначала воспроизводит или трассирует проблему и перед изменением поведения переклассифицируется в TDD-first. Если автоматический red signal непрактичен, Build записывает причину и использует лучший воспроизводимый contract/runtime signal.

Reviewers остаются read-only. Они проверяют red signal, owning layer, focused green result и покрытие по риску. Подтверждённые behavioral findings возвращаются главному агенту, который проводит remediation через тот же TDD-first workflow и только затем запускает следующий review.

## Как работает progressive review

Build классифицирует задачу как `low`, `medium`, `high` или `critical` и начинает с минимально достаточного reviewer tier:

| Сложность | Типичная работа | Начальный запрос review |
|---|---|---|
| `low` | Документация или локальная механическая правка | Fast/economy |
| `medium` | Ограниченная логика или refactor с тестами | Balanced |
| `high` | Межслойное состояние, публичные контракты, persistence, concurrency, auth, permissions, privacy | Strong |
| `critical` | Необратимые действия, live-инфраструктура, secrets, разрушительная миграция | Strongest available |

Reviewer возвращает покрытие acceptance criteria, findings с evidence, confidence, verdict и optional score. После исправления подтверждённых замечаний и повторных проверок Build повышает tier, если confidence низкий, coverage неполный, reviewers конфликтуют, validation падает, остаётся high-impact finding или diff существенно изменился. Score ниже `9.5` запускает эскалацию только вместе с конкретным finding, uncertainty или пробелом coverage.

Score — только вторичный сигнал эскалации. Evidence-backed verdict `ACCEPT` с достаточным confidence, зелёной validation, полным coverage и без подтверждённых actionable findings достаточен, даже если score отсутствует или ниже `9.5` без конкретного пробела. Loop ограничен реальными tiers и не повторяет одного reviewer на неизменённом diff.

Если Codex не раскрывает model selector, Build не выдумывает его. Последовательность fallback: настроенные profiles, поддерживаемые reasoning efforts, read-only explorer, generic subagent и root-only self-review. Фактический режим и неизвестный tier явно записываются.

## Выбор файла спецификации

Явный путь имеет приоритет. Иначе Build выбирает релевантный `BUILD.md`, затем релевантный `SPEC.md` или `TZ.md`, а для новой задачи создаёт `BUILD.md`. Документ другой задачи никогда не перезаписывается молча.

## Git и безопасность

- Исходные изменения пользователя остаются вне scope, если спецификация явно не включает их.
- `new` и `refine` могут менять только спецификацию.
- `run` и `full` могут менять реализацию после Ready-gate.
- Milestone-коммиты создаются, когда Git доступен, изменения можно изолировать и применимые инструкции не запрещают commit.
- Push всегда требует явного разрешения.
- Настройка моделей требует отдельного preview и разрешения.
- Discovery и review workers остаются read-only; главный агент владеет решениями, edits, TDD remediation, validation, Git и итоговым ответом.
- Нет telemetry, daemon, `curl | shell`, скрытого auto-update или фонового сетевого сервиса.
- Соблюдаются `AGENTS.md`, sandbox, approvals, validation и security-правила репозитория.

## Версионность и коммиты

Перед milestone- или финальным commit Build находит авторитетный источник версии и политику репозитория, затем записывает `version impact`: `not applicable`, `prerelease`, `patch`, `minor` или `major`. В версионируемом репозитории каждый созданный Build commit по умолчанию получает уникальную более высокую версию, а CHANGELOG и обязательная документация обновляются в том же commit.

Build не придумывает versioning для неверсионируемого репозитория и соблюдает явную политику проекта с release-only или generated versions. Сам OpenBuild требует bump для каждого commit после корневого, включая prose, внутренний validator и иначе пустые commits. Опубликованный tag никогда не передвигается. Создание tag, GitHub Release, публикация package и перевод prerelease в stable остаются отдельно авторизуемыми внешними действиями.

Правила contribution, version, commit и release самого OpenBuild описаны в [CONTRIBUTING.md](CONTRIBUTING.md).

## Решение проблем

### Skill не появился

- Начните новый thread или перезапустите Codex после установки.
- Для plugin запустите `codex plugin list` и проверьте статус `openbuild@openbuild`.
- Откройте `/skills` или введите `$` для просмотра skills.
- Для plugin используйте `$openbuild:build`, для standalone — `$build`.

### Видны и `$build`, и `$openbuild:build`

Установлены оба канала. Они используют один source, но являются отдельными локальными установками. Используйте namespaced-вызов plugin или осознанно удалите standalone-папку `$CODEX_HOME/skills/build`.

### Переключение моделей недоступно или не подтверждено

Запустите `$build setup-models`. Если runtime не поддерживает ни per-spawn selection, ни custom agents, Build продолжит через role/reasoning/root fallback и честно укажет ограничение.

### Build отказывается перезаписывать спецификацию

Найденный документ неоднозначен или относится к другой задаче. Передайте нужный путь явно или выберите описательное имя, например `BUILD-wishlist.md`.

### В worktree уже есть изменения

Build сохранит initial status, исключит чужие изменения и будет коммитить только task-scoped файлы. Если безопасно изолировать изменения нельзя, он остановится перед commit, а не спрячет или опубликует их.

## Разработка и проверка

В [CONTRIBUTING.md](CONTRIBUTING.md) описаны workflow ветки `main`, правила Semantic Versioning, same-commit version gate и checklist неизменяемого релиза.

Из корня репозитория:

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
python scripts/validate_package.py
```

Release-процесс также запускает официальные Codex validators для skill/plugin, чистую установку plugin, standalone-установку по tagged GitHub path, forward-tests режимов `new`, `refine`, `run`, delegated discovery, TDD-first remediation и routing fallbacks, а также свежий review полного diff.

Официальные материалы:

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex subagents and custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

## Лицензия

[MIT](LICENSE)
