# Build: Code Scout-контракт для Spark с fallback на Terra

- Status: In progress
- Last updated: 2026-07-19
- Original request: Подтянуть встроенный поиск OpenBuild на `gpt-5.3-codex-spark` до уровня `di-sukharev/code-scout-skill`, а при недоступности Spark для аккаунта или исчерпании его отдельного лимита один раз передавать тот же read-only поиск Terra. Подготовить документацию, выпустить новый GitHub Release и опубликовать его раньше параллельно готовящегося релиза.
- Primary signal: packaged discovery route сначала запускает Spark с проверяемым компактным evidence-контрактом; только подтверждённые `model-unavailable` или `quota-exhausted` разрешают один точный fallback на `openbuild_search_balanced`/Terra; остальные ошибки не подменяют модель; полный пакет проходит проверки, публикуется под новым неизменяемым тегом и устанавливается по нему.
- Review baseline: `main@7f92d4603f2eb3a2e434415c20bcf48b879dd3a3`, clean worktree, `main...origin/main [ahead 2]`; локальные коммиты `ed6875f` (`2.2.3`) и `7f92d46` (`2.2.4`) входят в baseline и не принадлежат этой задаче.
- Workflow target: Complete
- Starting phase: discovery
- Specification revision: R-022
- Complexity: high — меняются публичный discovery-контракт, строгая маршрутизация между двумя моделями, runner failure evidence, packaged map, двуязычная документация и релизная поверхность.
- Implementation mode: TDD-first — поведение маршрута и валидатора должно быть зафиксировано failing tests до изменения production-контракта.
- Version impact: minor — backward-compatible capability, authoritative source `plugins/openbuild/.codex-plugin/plugin.json`, план `2.2.4 -> 2.3.0`.
- Routing mode: codex-exec-explicit-model
- Discovery mode: delegated — exact run `openbuild_search_separate`, observed `gpt-5.3-codex-spark`, low, read-only, `turn.completed`, exit 0, semantic evidence accepted.
- Search usage route: separate-pool — packaged map SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, step 1/1; circuit breaker closed.
- Search routing receipt: packaged `openbuild_search_separate`; configured/observed `gpt-5.3-codex-spark`, low, read-only; exact runner completed; evidence consumed for sections 2, 6, 7 and M1.
- Implementation model route: exact `implementation.high` started with `openbuild_implementation_balanced`; its partial handoff was rejected, then the root completed the unchanged M2 scope under recorded same-scope root-completion authority.
- Implementation routing receipt: Terra/medium/workspace-write created; model-map grammar accepted, incomplete runner/discovery handoff rejected; no second writer was created and root completion was recorded after vacancy.
- Review routing receipt: balanced and strong reviews returned actionable findings; source-map binding, pre-turn gating, no-follow identity validation and reparse regressions are staged. R-010 Sol found and R-011 fixed an incomplete index. R-011 Sol then found that a checked-out gitlink's stable directory/commit marker did not include dirty nested content. R-012 recursively fingerprints bounded tracked plus untracked/nonignored nested content before and after marker capture, counts nested files/bytes against global limits, validates public fingerprint field types/constants, and makes the exclusive fallback claim durable. R-013 passed the complete candidate suite; A-021/A-022/A-023 progressively closed first-match, lossy-collector, predicate and non-regular artifact gaps. A-024 reviewed immutable task tree `f4b2581c` and found raw top-level `code`/error-shaped `type` records could bypass the complete-stream collector. R-018 collected those records. A-025 reviewed immutable task tree `19f9cceb` and found that a suffix vocabulary could still omit shapes such as `unknown_failure`; R-019 replaced suffix inference with a closed grammar. A-026 reviewed immutable task tree `5bb1f7ea` and found that cleanup failures or missing/malformed creation-bound exit evidence did not participate in eligibility. R-020 binds a clean runner exit and valid `codex-exit.json` to the stream. Combined A-027 then found path-based artifact reopens after `lstat`; R-021 binds every read to one verified descriptor identity. A-028 found a preinjected source fallback binding could reintroduce a reason after eligibility failed; R-022 rejects and suppresses source-side bindings. Fresh Sol/high closure remains required.

## 1. Outcome

### Problem

OpenBuild уже запускает отдельный fresh read-only Spark-процесс и требует компактную карту `path:line`, но результат не имеет строгой машиночитаемой схемы и content-sensitive worktree fingerprint, которые защищают Code Scout от устаревшей карты. Текущий transport failure всегда завершает exact-agent route и переводит discovery в минимальный root search; подготовленный Terra search profile не используется при недоступной для плана Spark или исчерпанном отдельном Spark-лимите.

### Desired behavior

1. Spark получает один self-contained read-only prompt без истории root, читает только нужные repository instructions и возвращает ограниченную структурированную карту owners, couplings, tests, flows и constraints.
2. Карта проходит детерминированную проверку схемы, безопасных repository-relative путей, tight line ranges, обязательного owner/test evidence и совпадения content-sensitive repository fingerprint до/после scout.
3. Один созданный exact Spark run может открыть Terra fallback только по нормализованной причине `model-unavailable` или `quota-exhausted`, при доказанном запуске и полной остановке creation-bound Codex process tree и только если effective map явно содержит canonical `openbuild_search_balanced` fallback. Допустим как `turn.failed`, так и отказ Codex после process start, но до первого turn; profile/CLI/spawn failure до Codex process не подходит.
4. Authentication, CLI, sandbox, spawn, runner, timeout, malformed result, workspace drift и неизвестные ошибки не запускают Terra; после них остаётся документированный targeted-root recovery.
5. Terra получает тот же immutable task prompt, строгий evidence contract и read-only sandbox. Повторного model fallback после Terra нет.
6. README/README.ru, Build skill/references, model-map interview, validator/tests, changelog и version pins описывают один и тот же контракт.
7. Версия `2.3.0` публикуется первой от текущего `main`; следующий параллельный релиз обязан перечитать remote/tag state и выбрать более высокую версию.

### In scope

- Canonical Explorer instructions и строгий `openbuild.discovery.v1` evidence contract.
- Content-sensitive Git worktree fingerprint и детерминированная валидация discovery result.
- Privacy-safe нормализация terminal errors в `model-unavailable`, `quota-exhausted` или non-eligible failure.
- Packaged Spark-first/Terra-on-availability-failure route и строгая model-map validation.
- TDD fixtures, package validator, EN/RU docs, changelog, manifest и release pins.
- Commit, push, annotated tag, GitHub Release, public tag/release verification и remote install smoke.

### Out of scope

- Terra fallback для implementation, critic или review.
- Terra fallback после generic transport/auth/sandbox/timeout/runner failure или после невалидного evidence result.
- Скрапинг приватной usage-страницы, угадывание плана/квоты или переключение по имени модели без runtime evidence.
- Копирование стороннего skill как отдельного bundled skill; OpenBuild адаптирует его проверяемые discovery-инварианты в существующий Build workflow.
- Перезапись или откат существующих `BUILD.md`, `BUILD-terminal-finalization-2.2.3.md` и двух baseline-коммитов.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Packaged Spark | `plugins/openbuild/skills/build/profiles/openbuild_search_separate.toml:1-18` | Spark/low/read-only уже выполняет `rg`, focused reads и compact evidence map. | Основа уже существует; нужен контракт качества, а не новый параллельный skill. |
| Packaged Terra | `plugins/openbuild/skills/build/profiles/openbuild_search_balanced.toml:1-18` | Canonical Terra/medium/read-only profile уже поставляется. | Fallback переиспользует существующий exact profile без новой модели/зависимости. |
| Default route | `plugins/openbuild/skills/build/profiles/openbuild_model_map.toml:6-14` | Discovery содержит только Spark, `max_steps = 1`, transport failure block, затем targeted-root. | Terra нельзя выбрать после Spark availability/quota failure. |
| Map enforcement | `plugins/openbuild/skills/build/scripts/model_map.py:192-269` | Все routes требуют `transport_failure == "block"`; discovery fallback только `targeted-root`. | Owner-layer изменения должны быть в map schema/validator, не только в prose. |
| Runner evidence | `plugins/openbuild/skills/build/scripts/agent_runner.py:4335-4529` | Public receipt закрывает private error в generic classification и не выдаёт eligibility reason. | Root сейчас не может безопасно отличить план/квоту от других transport failures. |
| Package contract | `scripts/validate_package.py:26-131`, `:3370-3520` | Validator фиксирует Spark exact profile, current failure vocabulary и запрет transport-driven model substitution. | Новый узкий exception должен быть явно разрешён и mutation-tested. |
| Release policy | `CONTRIBUTING.md:14-31`, `:79-89` | Manifest authoritative; каждый commit повышает версию; tag/Release immutable. | Capability получает `2.3.0`, synchronized docs/changelog и новый tag. |
| Current release state | Git/GitHub metadata 2026-07-19 | `origin/main` и latest Release на `v2.2.2`; local clean `main` содержит unreleased `2.2.3`/`2.2.4` commits. | Публикация должна включить baseline, не переписать историю и занять первый следующий release slot. |
| Upstream Code Scout | [Code Scout repository](https://github.com/di-sukharev/code-scout-skill), `skills/code-scout/SKILL.md` | Fresh read-only scout, strict bounded evidence schema, pre/post fingerprint, root verification и bounded local fallback. | Это внешний design reference для усиления Spark contract. |
| Official Codex availability | [Codex pricing](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan) | Spark research preview доступен Pro и имеет отдельный model-specific limit; Terra подходит для routine discovery. | Подтверждает две разрешённые fallback-причины и отсутствие права угадывать entitlement. |

### Source of truth

Route policy принадлежит `model_map.py` и effective complete map; exact model/sandbox — canonical profiles и `agent_runner.py`; discovery evidence contract — shared canonical Explorer instructions плюс новый детерминированный validator; release version — plugin manifest.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD-spark-code-scout-fallback.md` | user/OpenBuild root | R-022 | Scope, AC, D-001..D-002, T-001..T-010 | Rows below; current audit 2026-07-19 | yes | aligned |
| User request 2026-07-19 | user | current | D-001, D-002 | Names Code Scout URL and publication order | no | aligned |
| `plugins/openbuild/skills/build/SKILL.md` | OpenBuild workflow | 2.2.4 | Dispatch order, fallback and agent ledger | Links code-discovery/model-routing/versioning/review | yes | gap: current fallback differs |
| `plugins/openbuild/skills/build/references/code-discovery.md` | OpenBuild discovery owner | 2.2.4 | Evidence map, root verification, circuit breaker | Links implementation delegation/model routing | yes | gap: no strict schema/fingerprint/Terra availability fallback |
| `plugins/openbuild/skills/build/references/model-routing.md` | OpenBuild routing owner | 2.2.4 | Effective map, exact runner, failure policy | Links map interview/review/delegation | yes | conflict with D-001 until changed |
| `plugins/openbuild/skills/build/references/model-map-interview.md` | OpenBuild configuration owner | 2.2.4 | User/project discovery route configuration | Links model routing | yes | gap: interview cannot express narrow fallback |
| `plugins/openbuild/skills/build/profiles/openbuild_model_map.toml` | packaged default | schema 1 | Zero-setup route | Exact canonical profiles | yes | gap: Spark only |
| `CONTRIBUTING.md` | repository maintainer | current | Version, validation and release policy | README/changelog/manifest | yes | aligned |
| `README.md`, `README.ru.md`, `CHANGELOG.md`, manifest | public package | 2.2.4 | Install/use/release truth | pinned Git tag and package | yes | gap until synchronized |
| `di-sukharev/code-scout-skill` | upstream design reference, MIT | master observed 2026-07-19 | Strict scout invariants; no OpenBuild authority | Skill links fingerprint helper/tests/license | no | adapt with attribution, no verbatim dependency |
| Official Codex pricing/manual | OpenAI | fetched 2026-07-19 | Current Spark entitlement/limit and Terra use guidance | Current product docs | no | aligned |

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| OpenBuild transport block vs Terra fallback | Explicit user decision narrows one exception | D-001, user request 2026-07-19 | targeted change; all non-eligible failures preserve current policy |
| Local 2.2.4 vs public v2.2.2 | Immutable forward release policy | D-002 + `CONTRIBUTING.md` release checklist | publish one higher release from current linear `main`; no tag movement |

### Gap

OpenBuild has the correct exact profiles but lacks both a strict Code Scout-style result freshness contract and a safe, evidence-gated path from failed Spark entitlement/quota to Terra.

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | discovery.spark.failure-fallback | user | resolved | Когда Terra заменяет Spark для code search? | Только когда Spark runtime-confirmed недоступен аккаунту/плану или исчерпан её лимит. | User request 2026-07-19 | Остальные failures не меняют модель и используют текущий targeted-root recovery. |
| D-002 | release.concurrent.order | user | resolved | В каком порядке публиковать параллельные релизы? | Этот task выпускается первым; соседний релиз — вторым от нового remote state. | User request 2026-07-19 | Эта задача занимает следующий release/tag; соседнее окно должно выбрать более высокую версию. |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Переиспользовать `openbuild_search_balanced` как единственный Terra fallback. | selected | Packaged Terra/medium/read-only profile уже существует; новый alias не нужен. | Сохраняет D-001, exact model receipt и canonical read-only sandbox. |
| T-002 | Добавить privacy-safe normalized `transport_failure_reason` и разрешать fallback только по закрытому structured allowlist T-008. | selected | Generic public failure недостаточен; raw private errors публиковать нельзя; message-only evidence не является доверенным. | Не раскрывает raw errors и не расширяет D-001; unstructured/generic unavailable/network/provider text не подходит. |
| T-003 | Адаптировать bounded JSON evidence + pre/scout/post Git fingerprint как `openbuild.discovery.v1` по детерминированной грамматике ниже. | selected | Code Scout design reference; OpenBuild exact runner уже обеспечивает fresh context и OS-enforced read-only. | Улучшает свежесть/проверяемость без изменения user-visible task outcome или write authority; любой неизвестный/неполный вариант fail closed. |
| T-004 | Повторно использовать один immutable prompt snapshot и требовать одинаковый `prompt_sha256` у Spark и Terra receipts. | selected | Runner уже публикует privacy-safe digest; новый snapshot создавал бы риск scope drift. | Сохраняет D-001 и дословно тот же search scope/primary signal без раскрытия prompt bytes. |
| T-005 | Расширить schema 1 optional discovery-only полями `availability_fallback_agent` и `availability_fallback_triggers`; `transport_failure = "availability-fallback"` разрешить только при их валидной паре. | selected | Полная project/user map не смешивается с packaged map; отсутствие optional fields сохраняет старый `block` + targeted-root. Packaged map указывает canonical Terra и оба D-001 trigger. | Backward-compatible legacy maps не получают скрытый fallback; critic/implementation/review остаются `block`. |
| T-006 | Runner нормализует eligible reason только из creation-bound stopped Spark run и exact structured code/type/model fields T-008; message fallback отсутствует. | selected | Current event parser уже владеет private JSONL error evidence; JSON stderr того же creation-bound процесса даёт второй доверенный structured source; public projection остаётся allowlisted. | Сохраняет privacy, D-001 и fail-closed поведение при неоднозначности или message-only evidence. |
| T-007 | Terra dispatch принимает one-shot `--search-fallback-source` и expected map hash; runner atomically claims exact source receipt and cross-binds source run/profile/process stop/reason, effective route, prompt snapshot ID/SHA и target request. | selected | Один digest prompt не доказывает источник; owner-private run directory позволяет replay-safe exclusive claim. | Не создаёт новый control plane, запрещает stale/cross-run/replayed fallback и не допускает третью попытку. |
| T-008 | Доверенная pre-turn причина читается только из creation-bound `codex exec --json` JSONL и JSON-объектов stderr этого же процесса до первого `turn.started`; свободный текст и post-turn errors не классифицируются. `model-unavailable` требует exact source model в структурированном provider error и code/type из закрытого множества `{model_not_found, model_not_available, model_access_denied}`. `quota-exhausted` требует строго serialized `CodexErrorInfo=usage_limit_exceeded` и `rate_limits.limit_name`, byte-for-byte равный exact source model `gpt-5.3-codex-spark`; optional sibling `model`, если присутствует, тоже обязан совпасть. Других aliases/limit IDs в `2.3.0` нет. | selected | В актуальном официальном Codex protocol есть отдельный `UsageLimitExceeded` и `RateLimitSnapshot.limit_name`; provider model rejection наблюдается как JSON error с `code=model_not_found`. Официальный source не публикует отдельный Spark limit ID, поэтому придумывать его нельзя. Неизвестные версии/поля, message-only, post-turn и generic account/workspace limits не подходят. | Даёт исчерпывающие positive/negative fixtures и закрывает обязательный post-process-start/pre-turn случай без substring-эвристик; новый официальный alias добавляется только отдельным протестированным совместимым изменением. |
| T-009 | Source и target связываются canonical profile descriptor digest: profile ID, resolved file SHA-256, model, effort, service tier, sandbox, read-only permission surface и instructions SHA-256. Source обязан быть Spark/low/read-only, target — `openbuild_search_balanced` Terra/medium/read-only; instructions SHA у них одинаков. | selected | Role name и map hash сами по себе не защищают от profile shadowing/override. | Любой profile/map drift до claim или target start отклоняется; D-001 применяется только к фактической Spark-попытке и фактической Terra-цели. |
| T-010 | Fingerprint полностью инвентаризирует Git tracked + untracked/non-ignored paths и fail closed при превышении любого лимита; пропуск «оставшихся» файлов запрещён. | selected | Bounded partial scan не доказывает отсутствие drift вне просмотренного префикса. | Большой/медленный репозиторий получает targeted-root recovery, но никогда не принимает неполный freshness proof. |

### Pending proposals

- None; D-001 и D-002 уже однозначно разрешены пользователем.

### `openbuild.discovery.v1` canonical grammar

- UTF-8 JSON object, не более 64 KiB, без неизвестных полей. Обязательны: `schema`, `worktree_fingerprint`, `summary`, `owners`, `couplings`, `tests`, `flows`, `constraints`, `uncertainties`; `schema` строго `openbuild.discovery.v1`.
- `worktree_fingerprint` содержит только `algorithm="sha256"`, lowercase 64-hex `digest`, целые `files`/`bytes` и `inventory="git-tracked-untracked-nonignored-v1"`; значения обязаны совпасть с owner-captured pre/post fingerprint.
- `summary` — непустая строка до 2 KiB. Каждая коллекция — массив максимум 64 элементов, общий объём строк — максимум 32 KiB. `owners` и `tests` непусты; если для scope тестов объективно нет, `tests` содержит один проверяемый owner-path с `kind="validation-gap"` и объяснением, а не пустое утверждение.
- Evidence item имеет только `path`, `line_start`, `line_end`, `symbol`, `reason` и, где применимо, `kind`/`related_path`. Путь — normalized repository-relative UTF-8, без absolute/`..`, существует в fingerprint inventory, не generated-output/vendor/artifact; легитимное имя source-каталога `build` не запрещено. Диапазон положительный, внутри текущего файла, `line_end >= line_start`, ширина максимум 200 строк. `symbol`/`reason` непусты и ограничены 256/512 символами. `constraints`/`uncertainties` — строки до 512 символов.
- Fingerprint inventory строится из полного NUL-safe объединения Git index и `git ls-files --others --exclude-standard`, сортируется по normalized repository-relative byte representation и включает для каждого entry path, Git/index mode, type, byte length и SHA-256 содержимого. Regular files и checked-out symlinks хэшируются по фактическим bytes; настоящий symlink — по target bytes без follow. Инициализированный gitlink/submodule включает index marker, checked-out HEAD и bounded nested fingerprint всех tracked плюс untracked/non-ignored entries; вложенные файлы/bytes входят в те же глобальные лимиты, глубина ограничена 16, а marker/content снимаются дважды. Case/path collision, unreadable/special file, disappearing entry или изменение inventory во время снимка отклоняет снимок.
- Лимиты одного снимка: максимум 100 000 entries, 2 GiB прочитанных bytes и 30 секунд monotonic wall time. Превышение file/byte/time limit, ошибка Git/IO или неполная inventory дают только `fingerprint-unavailable`; partial digest не публикуется и scout/fallback не стартует либо result не consume. Pre, scout-reported и owner post digests/счётчики обязаны совпасть.

## 4. User scenarios

### Primary scenario

1. Build определяет, что нужен repository search, снимает bounded fingerprint и запускает Spark.
2. Spark возвращает валидный `openbuild.discovery.v1`; root подтверждает fingerprint, paths/ranges/symbols и использует только релевантную карту.

### Errors and edge cases

- Spark недоступна по entitlement/model access -> creation-bound Codex process запущен, затем остановлен; его отказ нормализуется в `model-unavailable` -> один Terra run, даже если `turn` не начался.
- Spark limit исчерпан -> `quota-exhausted` -> один Terra run.
- Terra тоже не завершилась -> no third agent; targeted-root recovery.
- Spark result malformed/stale/worktree drift -> result не consume; targeted-root recovery, без Terra.
- Profile/auth/CLI/network/sandbox/spawn/runner/timeout failure без подтверждённого Spark model/quota rejection -> без Terra.
- Project/user map не содержит canonical fallback -> без неявной подстановки Terra.
- Worktree меняется соседним окном между fingerprint checks -> stale map отклоняется; чужие изменения сохраняются.

## 5. Requirements and acceptance criteria

- [x] AC-01: packaged route resolves Spark first and canonical Terra fallback second only for a stopped created Spark run with creation-bound Codex process evidence and normalized `model-unavailable`/`quota-exhausted`; post-process-start/pre-turn отказ допустим только по T-008 structured evidence.
- [x] AC-02: non-eligible transport, timeout, auth, sandbox, runner and result-validation failures cannot dispatch Terra.
- [x] AC-03: Spark and Terra share exact canonical read-only discovery instructions, the same immutable prompt snapshot/`prompt_sha256`, exact instruction SHA, and produce bounded `openbuild.discovery.v1` evidence.
- [x] AC-04: deterministic validation implements the canonical grammar/limits in T-003/T-010 and rejects unknown/malformed schema, unsafe/nonexistent paths, loose ranges, missing owner/test evidence, partial inventory, limit exhaustion and fingerprint drift.
- [x] AC-05: public receipt exposes only normalized fallback reason; classification is eligible only from the exact T-008 creation-bound structured evidence vocabulary and never publishes raw provider/auth/error text.
- [x] AC-06: schema-1 project/user complete maps without optional availability fields remain valid and keep block/targeted-root; packaged or explicit maps may enable only one canonical search fallback with allowlisted triggers; other route types cannot enable it.
- [x] AC-07: EN/RU README, Build skill/references, model-map interview, contributor guidance, validator and tests agree on the fallback and quality contract.
- [x] AC-08: full unit suite, package validation, whitespace, commit gate, clean install/candidate validation and exact search smokes are green.
- [ ] AC-09: manifest/changelog/README pins agree on `2.3.0`; commit pushed; annotated `v2.3.0` and public GitHub Release resolve to the reviewed commit.
- [ ] AC-10: post-release remote installation from `v2.3.0` resolves Spark-first/Terra-on-eligible-failure map; next parallel release remains unmodified by this task and must start from the published state.
- [x] AC-11: Terra fallback dispatch requires an atomic one-shot source claim bound to the exact stopped Spark receipt, effective map hash, canonical T-009 source/target profile descriptor digest sequence, eligible reason, creation-bound process evidence and identical prompt snapshot ID/SHA; replay, cross-run, drift, profile shadowing or a second fallback is rejected before target process start.

### Invariants

- Search and review agents stay read-only; only implementation workers may write under a lease.
- No model/plan/quota claim without exact runtime or official evidence.
- No transport fallback for implementation/review/critic.
- No concurrent writer; root owns spec/version/Git/release.
- Published tags/releases are immutable and history is never rewritten.

## 6. Technical boundaries

### Affected layers and contracts

- `agent_runner.py` — canonical search instructions and privacy-safe transport failure classifier.
- `model_map.py` / packaged map — strict discovery-only fallback schema and resolved route evidence.
- New or existing small discovery helper — fingerprint and result validation.
- Build skill/references/interview — orchestration, validation and reporting rules.
- Validator/tests — route, mutation, schema, failure classifier and documentation parity.
- README/CHANGELOG/manifest — public release contract.

### Data and migration

No user/business data migration. Model-map schema remains 1: `availability_fallback_agent` and `availability_fallback_triggers` are optional and legal only for `discovery.default` together with `transport_failure = "availability-fallback"`; absence preserves legacy `transport_failure = "block"` and targeted-root. Complete project/user maps never inherit missing packaged fields. The resolved route serializes source/target profile descriptors as canonical JSON (sorted UTF-8 keys, no whitespace) and records their SHA-256 sequence; this is recomputed immediately before claim and target start. Owner-private run metadata gains a replay-safe search-fallback claim and target binding; it is ephemeral orchestration evidence, not a durable recovery-registry schema.

### Security and privacy

Raw CLI/provider/auth errors remain private. Public classification is an allowlisted code. Eligible normalization requires a failed created run, a creation-bound Codex process, full-tree stop and exact T-008 JSON evidence; unstructured message fallback отсутствует. Unknown codes, missing exact model/limit identity, generic account/workspace usage cap, network/provider/unavailable/auth/billing text fail closed. Result paths must be repository-relative, normalized and inside the current Git root; generated-output/vendor/artifact paths are rejected without banning legitimate source directories named `build`. Fingerprint hashes contents without printing contents. The exclusive fallback claim and target request store only owner-private source bindings; public receipts expose privacy-safe hashes/codes.

### Performance and concurrency

Fingerprint is bounded by T-010 byte/time/file limits, but never partial: any exhaustion is a terminal freshness-proof failure. Terra runs only after a terminal stopped Spark run and at most once. Worktree drift fails closed so parallel window edits cannot be silently consumed.

### Observability and errors

Routing records preserve map source/hash, step, canonical source/target profile descriptor digests, configured/observed model/effort, normalized eligible reason, stopped process tree and consumed/rejected evidence. Terra additionally records the privacy-safe source receipt digest/opaque handle, one-shot claim outcome and equal prompt/instruction digests; raw snapshot IDs and errors remain private.

### Versioning and release

Authoritative current `2.2.4`; backward-compatible capability -> `2.3.0`. Publication is explicitly authorized. Immediately before commit, push, tag and Release, root rechecks branch/status/remote tags/releases so the first/second ordering cannot silently collide.

## 7. Validation and review

- Primary signal: strict evidence contract plus eligible-only Spark -> Terra route demonstrated by tests and exact-runner smokes.
- Red signal: focused model-map/runner/discovery-contract tests fail because current route blocks all transport substitution and accepts prose evidence without fingerprint/schema.
- Minimality decision: reuse existing exact runner, Terra profile, model map and stdlib; add only one small owner-layer discovery helper if existing modules cannot own fingerprint/schema coherently.
- Focused green: targeted unittest modules for model map, agent runner and discovery contract.
- Targeted checks: `python scripts/validate_package.py`; exact packaged route resolve; Spark exact discovery smoke; simulated normalized failure routing fixture.
- Wider checks: `python -m unittest discover -s scripts -p "test_*.py" -v`; `git diff --check`; official skill/plugin validators; commit gate.
- Manual/runtime check: clean candidate ref install and public release verification.
- Starting review tier: balanced — high-risk route starts at `openbuild_review_balanced`.
- Required final tier: balanced unless concrete finding/gap/low confidence triggers strong; readiness high-risk depth includes complementary perspectives and strong closure as required by Build.
- Review ladder: sequential exact profiles from resolved map, no repeats on unchanged diff.
- Review focus: fallback eligibility/privacy, schema/path safety, stale evidence, backward-compatible maps, docs/version/release agreement.

## 8. Milestones

### M1. Ready specification

- Status: Completed
- Scope: source reconciliation, acceptance criteria, risk/coverage ledgers, complementary critics and closure.
- Excludes: production/test edits.
- Implementation mode: Investigation -> TDD-first after Ready.
- Delegation: root-only for specification; exact read-only critics.
- Red signal: not applicable to specification authoring.
- Minimality decision: adapt only material Code Scout invariants; preserve stronger OpenBuild exact runner/read-only boundaries.
- Focused green: current-revision `COVERED` closure.
- Validation: source map and coverage audit.
- Acceptance: AC-01..AC-11.
- Review: R-006 `COVERED`, high confidence, sol-high closure.
- Version: unchanged in specification-only stage.
- Commit: Pending.

### M2. Discovery contract and routing implementation

- Status: In progress
- Scope: production owner layers, tests, docs, version surfaces.
- Excludes: GitHub publication before review/validation.
- Implementation mode: TDD-first.
- Delegation: exact bounded worker produced a valid partial model-map change but an incomplete semantic handoff; root completed the same allowed scope only after handoff rejection, lease vacancy and recorded root-completion authority.
- Red signal: focused tests for current missing schema/fingerprint and eligible-only Terra route.
- Minimality decision: existing profiles/map/runner + stdlib helper only.
- Focused green: deterministic discovery/routing/package checks pass; the final live Spark smoke completed with exact Spark/low/read-only selection, unchanged fingerprint and valid `openbuild.discovery.v1` evidence after two prompt/validator-grammar clarifications.
- Validation: R-022 passes 106 affected runner/evidence/discovery/package tests with 3 expected platform skips and all 403 repository tests with 4 expected platform skips, including creation-bound exit, cleanup, descriptor-replacement and source-binding injection regressions. Package and official plugin/skill validators pass. Pre-receipt task-only tree `e5a141bc44c02b4ca7f4908577b5d46413b22ab2` contains exactly 23 UTF-8 paths, compiles/parses every Python/TOML blob, binds the R-022 guards and contains no neighboring recovery marker.
- Acceptance: AC-01..AC-08, AC-11.
- Review: A-028 returned `REVISE` because an injected source-side fallback binding could republish an eligible reason after strict eligibility failed. R-022 rejects every source binding before claim and suppresses it in Spark receipts; fresh Sol/high closure is required before commit.
- Version: `2.2.4 -> 2.3.0`.
- Commit: Pending.

### M3. First publication and verification

- Status: Pending
- Scope: push reviewed commit, annotated tag, GitHub Release, public/install verification.
- Excludes: changes belonging to the neighboring release.
- Implementation mode: Direct external publication after green gates.
- Delegation: root-only Git/GitHub owner.
- Red signal: not applicable; publication preconditions are deterministic checks.
- Minimality decision: existing `git` and `gh`, no CI/provider changes.
- Focused green: remote tag/release resolves exact reviewed commit.
- Validation: candidate install + public unauthenticated tag/release checks.
- Acceptance: AC-09, AC-10.
- Review: inherits accepted full-diff review; publication metadata rechecked.
- Version: `2.3.0` stable.
- Commit: Pending.

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome.scope.non-goals | covered | product decision | User request; D-001/D-002 | none |
| B-002 | actors.permissions.abuse | covered | repository fact | read-only profiles; no new external authority beyond authorized release | reviewer verify |
| B-003 | primary.alternate.error.recovery | covered | product decision | D-001 plus T-008 exact post-process-start/pre-turn structured evidence boundary | tests |
| B-004 | accessibility.localization.responsive | covered | repository fact | CLI/Markdown only; EN/RU parity required | validator |
| B-005 | ownership.contracts.source-of-truth | covered | technical decision | T-005 map grammar; T-006/T-008 classifier; T-007/T-009 fallback/profile claim; R-004 source map | tests/review |
| B-006 | data.schema.migration.retention | covered | technical decision | schema-1 optional discovery fields preserve complete legacy maps; ephemeral owner-private claim has no recovery reader-floor effect | tests |
| B-007 | security.privacy.trust | covered | technical decision | T-002/T-006..T-009; raw errors private; structured allowlist; exact source/profile/prompt/map binding; path/fingerprint validation | tests/review |
| B-008 | performance.capacity.concurrency | covered | technical decision | T-010 full-or-fail bounded inventory; one stopped fallback; drift rejection | tests |
| B-009 | integrations.timeouts.partial-failure | covered | product decision | non-eligible failure matrix and no third agent | tests |
| B-010 | observability.support | covered | technical decision | normalized receipt + source receipt/map/prompt binding + route ledger | tests/docs |
| B-011 | rollout.rollback.release-docs | covered | product decision | D-002, immutable new tag, reinstall previous tag as rollback | release checks |
| B-012 | acceptance.testability.minimality.cost | covered | technical decision | AC-01..11, TDD, T-004/T-009 digest equality and binding, stdlib and reuse | critic/review |
| B-013 | external-source.license.attribution | covered | technical decision | conceptual adaptation; public link/credit, no vendored dependency | docs/review |
| B-014 | concurrent-release.version-collision | covered | product decision | D-002 + repeated remote checks | pre-publish gate |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Structured classifier misclassifies transient/network failure as entitlement/quota | low/high | exact T-008 closed code/type/model equality, negative tests, no message/substrings or aliases | Open |
| Fingerprint is expensive or racy on large repositories | medium/medium | byte/time bounds, content hashing, pre/scout/post equality, targeted-root recovery | Open |
| Project/user maps break after schema change | low/high | optional backward-compatible discovery fields and mutation tests | Open |
| Parallel release moves remote while this task runs | medium/high | branch/status/remote tag/release checks before every irreversible step; stop on mismatch | Open |
| Upstream Code Scout wording/code creates attribution ambiguity | low/medium | adapt concepts, credit source, avoid verbatim vendoring unless license notice is added | Handled |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-001 | Terra only for confirmed Spark entitlement/quota failure; user request 2026-07-19 | Scope, scenarios, AC-01/02/05/06, M2 | read-only, exact receipts, targeted-root for all other failures | none |
| D-002/R-001 | This release first, neighboring release second; user request 2026-07-19 | AC-09/10, version/release, M3 | immutable tags, linear history, no foreign task edits | none |
| Locked R-001 requirement/R-002 | Terra receives the same immutable task prompt; propagated without semantic change | Desired behavior 3/5, scenarios, AC-01/03, T-004 | D-001, exact receipts, prompt privacy | none |
| Locked D-001/R-003 | Fail closed except exact availability/quota fallback; technical proof made explicit | AC-05/06/11, technical boundaries, T-005..T-007 | D-001, read-only, privacy, no third agent | none |
| Locked D-001/R-004 | Exact structured eligibility, actual-profile binding and full-or-fail discovery grammar | T-003/T-008..T-010, AC-01/03/04/05/11, M1/M2, B-003/005/007/008/012 | D-001/D-002, same prompt, read-only, legacy maps, one-shot fallback | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | product/UX, balanced | GAPS, high confidence | pre-turn model rejection boundary; prompt identity AC | D-001 not reopened: clarified exact runtime evidence; added T-004 and AC-01/03 in R-002 |
| R-002 | architecture/data/security, balanced | GAPS, high confidence | map grammar/compatibility, trusted classifier input, source-bound one-shot claim | Added T-005..T-007 and AC-05/06/11 in R-003; no product decision/reopen |
| R-003 | reliability-validation, strong | GAPS, high confidence | evidence/profile/fingerprint grammars; AC-11 milestone mapping; stale source-map revision | Added T-008..T-010 and canonical grammar; corrected source map, AC and milestone coverage in R-004; no product reopen |
| R-004 | final-closure, sol-high | GAPS, high confidence | quota type/limit aliases were not a closed vocabulary | Removed “equivalent” types and invented limit IDs; R-005 accepts only exact `usage_limit_exceeded` plus exact source-model structured identity |
| R-005 | final-closure-recheck, sol-high | GAPS, high confidence | stale T-002/T-006 and risk wording still allowed message fallback | Reconciled every classifier decision/risk to structured-only T-008 semantics in R-006 |
| R-006 | final-closure-recheck, sol-high | COVERED, high confidence | none | Ready gate passed; no reopen requests |

## 10. Open questions

Blocking product questions:

- None.

Non-blocking assumptions:

- Current official Codex protocol exposes structured `UsageLimitExceeded` and rate-limit identity; provider model rejection exposes JSON code/type. Unknown CLI versions/shapes fail closed until an explicit tested compatibility update.
- The neighboring release must observe the published Git/GitHub state and start only from that immutable commit.

## 11. Agent activity ledger

Created logical agent runs: `28`.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | search / Spark fallback repository discovery | `gpt-5.3-codex-spark` | low | completed; evidence consumed | M1; sections 2, 6, 7 | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-002 | yes | critic / product-UX readiness | `gpt-5.6-terra` | medium | completed; GAPS, high confidence | M1; B-003, B-012, D-001, T-004 | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-003 | yes | critic / architecture-data-security readiness | `gpt-5.6-terra` | medium | completed; GAPS, high confidence | M1; B-005/006/007/010, T-005..T-007 | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-004 | yes | critic / reliability-validation closure | `gpt-5.6-terra` | xhigh | completed; GAPS, high confidence | M1; B-003/005/007/008/012, T-003/T-008..T-010 | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-005 | yes | critic / final readiness closure | `gpt-5.6-sol` | high | completed; GAPS, high confidence | M1; B-003/007/012, T-008 | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-006 | yes | critic / final readiness closure recheck | `gpt-5.6-sol` | high | completed; GAPS, high confidence | M1; B-003/005/007/012, T-002/T-006/T-008 | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-007 | yes | critic / current-revision closure | `gpt-5.6-sol` | high | completed; COVERED, high confidence | M1; B-001..B-014, Ready gate | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-008 | yes | implementation / M2 owner layers | `gpt-5.6-terra` | medium | partial handoff rejected; root completion used | M2; model-map grammar/tests accepted, runner/discovery/docs remained for root | exact runner, workspace-write, stopped tree; semantic handoff rejected as incomplete |
| A-009 | yes | search / post-implementation Spark smoke | `gpt-5.3-codex-spark` | low | completed; evidence rejected and defect fixed | M2; AC-03/04; exposed false rejection of source directories named `build` | exact runner, read-only, `turn.completed`, exit 0; invalid evidence due owner-path filter |
| A-010 | yes | search / regression Spark smoke | `gpt-5.3-codex-spark` | low | completed; schema valid, terminally rejected on concurrent drift | M2; AC-02/03/04; verified stale-result fail-closed behavior | exact runner, read-only, `turn.completed`, exit 0; post-fingerprint differed after neighboring edits |
| A-011 | yes | review / staged M2 balanced pass | `gpt-5.6-terra` | medium | completed; FINDINGS, high confidence | M2; B-007/012; found external symlink evidence escape | exact runner, read-only, `turn.completed`, exit 0; actionable-finding routed to strong tier |
| A-012 | yes | review / updated M2 strong pass | `gpt-5.6-terra` | xhigh | completed; FINDINGS, high confidence | M2; B-003/005/007/008/012; found source-map drift, missing pre-turn gate and symlink race | exact runner, read-only, `turn.completed`, exit 0; actionable-finding routed to Sol tier |
| A-013 | yes | search / combined recovery smoke | `gpt-5.3-codex-spark` | low | completed transport; evidence rejected | M2; AC-03/04/08; exposed ambiguous nested evidence grammar | exact runner, read-only, `turn.completed`, exit 0; no fallback because transport succeeded |
| A-014 | yes | search / flat-evidence smoke | `gpt-5.3-codex-spark` | low | completed transport; evidence rejected | M2; AC-03/04/08; flat shape fixed, over-wide range rejected | exact runner, read-only, `turn.completed`, exit 0; no fallback because transport succeeded |
| A-015 | yes | search / range-bound smoke | `gpt-5.3-codex-spark` | low | completed transport; stale evidence rejected | M2; AC-02/03/04; concurrent specification write changed fingerprint | exact runner, read-only, `turn.completed`, exit 0; fail-closed drift proof |
| A-016 | yes | search / stable final smoke | `gpt-5.3-codex-spark` | low | completed; evidence consumed | M2; AC-03/04/08; exact current Spark route and strict schema forward signal | exact runner, read-only, `turn.completed`, exit 0, valid result |
| A-017 | yes | review / Sol final implementation recheck | `gpt-5.6-sol` | high | completed; FINDINGS, high confidence | M2; no semantic defects, publication process gate not yet closed | exact runner, read-only, `turn.completed`, exit 0; required full current-candidate validation before publication |
| A-018 | yes | review / Sol exact-candidate adjudication | `gpt-5.6-sol` | high | completed; FINDINGS, high confidence | M2; alleged completed-result fallback path | exact runner, read-only, `turn.completed`, exit 0; root inspection found the path already rejected and added an integration regression |
| A-019 | yes | review / Sol R-010 staged closure | `gpt-5.6-sol` | high | completed; FINDINGS, high confidence | M2; found working-tree fixes absent from the task index | exact runner, read-only, `turn.completed`, exit 0; exposed staged runner/discovery/test inconsistency before commit |
| A-020 | yes | review / Sol R-011 staged closure | `gpt-5.6-sol` | high | completed; FINDINGS, high confidence | M2; found dirty checked-out gitlink content absent from fingerprint | exact runner, read-only, `turn.completed`, exit 0; required nested content capture and drift regression |
| A-021 | yes | review / Sol R-013 cached closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found mixed eligible plus auth/network errors could authorize Terra | exact runner, read-only, `turn.completed`, exit 0; required complete-stream normalization and isolated index restoration |
| A-022 | yes | review / Sol R-015 complete-stream closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found unrecognized error-bearing events and malformed/non-UTF-8 stderr could be omitted | exact runner, read-only, `turn.completed`, exit 0; required explicit collector validity and end-to-end regressions |
| A-023 | yes | review / Sol R-016 immutable task-tree closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found the staged validity predicate absent and non-regular evidence/result objects treated as missing | exact runner, read-only, `turn.completed`, exit 0; required direct predicate and receipt-level artifact regressions |
| A-024 | yes | review / Sol R-017 immutable task-tree closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found raw top-level `code` and error-suffixed `type` records bypassing the complete-stream collector | exact runner, read-only, `turn.completed`, exit 0; required raw conflicting/unknown record regressions |
| A-025 | yes | review / Sol R-018 immutable task-tree closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found suffix vocabulary incomplete because `unknown_failure` bypassed the collector | exact runner, read-only, `turn.completed`, exit 0; required closed protocol grammar rather than another suffix |
| A-026 | yes | review / Sol R-019 immutable task-tree closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found cleanup failure and missing/malformed creation-bound Codex exit absent from eligibility | exact runner, read-only, `turn.completed`, exit 0; required clean runner-exit rederivation and exit-evidence binding |
| A-027 | yes | review / Sol combined R-020 exact-tree closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found JSONL/stderr/result paths reopened after no-follow `lstat`, permitting check/open/read replacement | exact runner, read-only, `turn.completed`, exit 0; external test drift also invalidated the review tree |
| A-028 | yes | review / Sol R-020 task-tree closure | `gpt-5.6-sol` | high | completed; REVISE, high confidence | M2; found an injected source-side fallback binding could publish an eligible reason after cleanup/exit eligibility failed | exact runner, read-only, `turn.completed`, exit 0; required source binding absence at receipt and claim gates |

Pre-spawn dispatch failures (not included in created count): one R-006 closure dispatch and one smoke redispatch were rejected because their staged owner-private prompt snapshots were missing; one source Spark smoke command incorrectly paired `--expected-map-sha256` without a fallback source. Restaging/correct dispatch succeeded without creating an agent or changing repository state.

## 12. Execution and validation log

### 2026-07-19 — discovery and initial specification

- Changed: created task-specific specification; implementation files untouched.
- Routing: packaged discovery map SHA-256 `fce8589a...`, Spark step 1/1 exact runner completed; circuit breaker closed.
- Primary signal: partially validated — current Spark route/profile and missing Terra fallback confirmed.
- Validation: repository evidence map + targeted root reads; public GitHub release/tag state checked.
- Minimality decision: reuse exact runner, existing Terra profile and model map; adapt only strict Code Scout invariants.
- Review: pending high-risk readiness critics.
- Version: planned minor `2.2.4 -> 2.3.0`; no version files changed yet.
- Commit: not created.
- Remaining: readiness critics, TDD implementation, full validation/review, commit/push/release.

### 2026-07-19 — R-002 product-UX adjudication

- Changed: clarified eligible pre-turn Spark model rejection after creation-bound process start/stop; added immutable prompt digest equality and T-004; no product outcome changed.
- Routing: exact `openbuild_review_balanced`, observed `gpt-5.6-terra`/medium/read-only, completed with GAPS/high confidence.
- Primary signal: specification gaps B-003/B-012 closed; implementation pending.
- Validation: critic evidence checked against runner receipts/profile lifecycle and current D-001 wording.
- Minimality decision: reuse existing prompt snapshot/digest; no second prompt store or route alias.
- Review: product-UX pass adjudicated; architecture/data/security pass pending on R-002.
- Version: planned `2.3.0`; package files unchanged.
- Commit: not created.
- Remaining: complementary critic and closure.

### 2026-07-19 — R-003 architecture/security adjudication

- Changed: selected a backward-compatible discovery-only map grammar, trusted private failure-classification inputs and atomic source-bound one-shot Terra claim; added AC-11.
- Routing: exact `openbuild_review_balanced`, observed `gpt-5.6-terra`/medium/read-only, completed with GAPS/high confidence.
- Primary signal: B-005/B-006/B-007/B-010 specification gaps closed; implementation pending.
- Validation: findings verified against strict map parser, public receipt projection and owner-private run layout.
- Minimality decision: extend existing schema-1/map/runner/run directory; no new fallback profile, registry or provider.
- Review: complementary high-risk perspectives complete; fresh closure required for R-003.
- Version: planned `2.3.0`; package files unchanged.
- Commit: not created.
- Remaining: fresh closure, then implementation.

### 2026-07-19 — M2 implementation and runtime validation

- Changed: added strict `openbuild.discovery.v1`, full Git content fingerprinting, exact structured Spark availability classification, atomic source-bound Terra claim, discovery-only map grammar, packaged route, docs, release notes and `2.3.0` pins.
- Routing: exact Terra implementation worker returned only the map portion; its incomplete semantic handoff was rejected and same-scope root completion was recorded after vacancy. Two post-change Spark searches were created; neither qualified for Terra because both completed successfully at transport level.
- Primary signal: 373 tests passed with 4 expected skips; package validation passed. The second live Spark result was schema/evidence-valid and was rejected solely because concurrent neighboring edits changed the full worktree fingerprint.
- Defect found by smoke: the first result exposed an overbroad `build` path filter that rejected OpenBuild's legitimate source directory. The owner filter/instructions were corrected to distinguish generated build output, and a regression test was added.
- Minimality decision: retained existing runner/profile/map, one stdlib-only discovery helper and no new dependency/provider/registry.
- Review: task-only staged diff review pending.
- Version: manifest, changelog and EN/RU install pins now target `2.3.0`.
- Commit: not created.
- Remaining: isolate task hunks from neighboring recovery work, progressive review, commit gate, push/tag/Release and public install verification.

### 2026-07-19 — M2 balanced review finding

- Finding: a repository-relative symlink could pass inventory membership and be followed by line validation to an external file.
- Changed: evidence paths and `related_path` now reject every symlink/junction component and require strict resolved containment inside the repository; added an external-target regression with a deterministic Windows no-symlink-privilege fallback.
- Validation: 8 discovery-contract tests passed without skips; broader targeted routing tests and package validator remained green before the review fix and will be rerun on the final candidate.
- Review routing: exact `openbuild_review_balanced`, Terra/medium/read-only, FINDINGS/high confidence, `actionable-finding`; fresh `openbuild_review_strong` required.
- Version: unchanged at planned `2.3.0`.
- Commit: not created.
- Remaining: strong review of the updated staged diff, then final validation/publication gates.

### 2026-07-19 — M2 strong review findings

- Findings accepted: the source Spark request did not persist its effective map binding; errors after `turn.started` could enter the eligibility pool; line validation reopened a path after the safe-path check and the junction API was newer than Python 3.11.
- Changed: source requests now persist a canonical map/route binding and claims require exact source/current/caller equality; only pre-turn structured errors are eligible; fingerprinting uses identity-checked no-follow descriptors, explicit Windows reparse attributes, and snapshot-owned line counts so validation never reopens evidence paths.
- Tests added: source-map drift, post-turn error exclusion, malformed/mismatched quota identity, link-swap-before-read and Python-3.11-compatible reparse detection.
- Root adjudication: retained R-006 support for a serialized quota error with exact `rate_limits.limit_name` and no sibling `model`; a present `model` must also match. Requiring both fields unconditionally would discard the documented limit-only shape and weaken D-001's quota fallback outcome.
- Validation: 124 agent-runner tests passed with 4 expected platform skips; 58 focused discovery/fallback/evidence tests passed with 3 expected POSIX skips; package validator passed before newer neighboring recovery edits made the repository commit gate non-isolating.
- Review routing: exact `openbuild_review_strong`, Terra/xhigh/read-only, FINDINGS/high confidence, `actionable-finding`; fresh Sol review required for fixes and adjudication.
- Version: unchanged at planned `2.3.0`.
- Commit: not created.
- Remaining: Sol review, full candidate validation, isolated commit/push/tag/Release and public install verification.

### 2026-07-19 — R-007 combined forward-smoke remediation

- Two stable-worktree Spark smokes exposed mismatches between the canonical prose and the strict validator: the model first nested evidence collections, then emitted an over-wide line range. The validator rejected both without fallback or evidence consumption.
- Changed: every exact search profile and the runner-owned canonical instructions now require flat owner/coupling/test/flow arrays, bounded-string constraints/uncertainties, the exact `line_end - line_start + 1 <= 200` rule and no distant symbols in one item; package validation locks the same bytes.
- A later smoke was correctly rejected when this specification changed during the run. After repository stability was confirmed, A-016 completed through exact Spark/low/read-only with `turn.completed`, exit 0, unchanged full fingerprint and valid `openbuild.discovery.v1` evidence.
- Remaining: rerun the full exact candidate, complete the required Sol/high review, then stage and execute release gates.

### 2026-07-19 — R-008 exact-candidate validation and Sol process finding

- Sol/high confirmed the staged backslash, artifact-segment, lifecycle-documentation, source-map, pre-turn classifier and no-follow fingerprint fixes and reported no semantic implementation defect. It kept the publication gate closed because AC-08 and M2 had not yet recorded a full current-candidate validation.
- Validation: the first full-suite command timed out after 120 seconds and is not counted as green; an unchanged rerun completed 380 tests in 128.374 seconds with 4 expected platform skips. Package validation and both staged/working whitespace checks passed.
- Exact index substitute: all 23 staged blobs decoded as UTF-8; 8 Python blobs compiled; 5 TOML blobs parsed; version/docs tokens matched `2.3.0`; no neighboring recovery-release marker was present. The repository-wide commit gate remains intentionally non-zero because the neighboring release owns unstaged public files that this task must neither stage nor revert.
- Remaining: fresh Sol/high adjudication of the changed R-008 staged candidate, then isolated commit, exact-ref install, push/tag/Release and public verification.

### 2026-07-19 — R-009 completed-result fallback adjudication

- Sol/high alleged that an early structured availability error followed by `turn.completed` and an invalid discovery result could publish `model-unavailable`. Root inspection found the existing staged owner predicate already requires `completed is not True` and rejects terminal event `turn.completed`, so the described sequence cannot enter the classifier.
- Regression: an exact public-receipt fixture now drives `thread.started -> structured model_not_found -> turn.completed` with a missing/invalid discovery result and verifies `status=failed`, `failure_message=result-evidence-invalid`, and `transport_failure_reason=None`; it passed together with the direct coherent-pre-turn predicate test.
- Minimality: no redundant production guard was added because the owner-layer predicate already enforces AC-02; the missing signal was end-to-end regression coverage, not behavior.
- Remaining: full unchanged-candidate validation and fresh Sol/high closure, then isolated commit and release gates.

### 2026-07-19 — R-010 package-contract closure

- Validation: the R-009 full suite completed 386 tests in 144.495 seconds with 4 expected platform skips. The completed-result regression and coherent-pre-turn predicate passed in the focused 51-test set; package validation and diff checks are green.
- Contract hardening: model routing now states the coherent pre-turn/no-completed-turn boundary inside the normative fallback step, persists source-time Spark/Terra profile identities for claim-time comparison, and documents same-object fingerprint reads. The package validator and mutation tests lock those exact guarantees.
- Isolation: task-only staged blobs remain free of all neighboring recovery/version-floor markers; neighboring work remains unstaged and untouched.
- Remaining: final unchanged-candidate suite/review closure, isolated commit, exact-ref install and public release gates.

### 2026-07-19 — R-011 exact-index owner-layer reconciliation

- Sol/high verified the documentation/version surface but found that the staged runner still lacked the coherent-event predicate and source-time profile binding, while staged discovery lacked symlink/gitlink same-object checks. Those implementations already existed in the validated working tree but had not been included by earlier partial staging around neighboring recovery edits.
- Changed index: staged all task-owned route/profile/event-stream and fingerprint identity hunks, the exact source-agent map constraint and matching regressions. Reverted the accidentally coalesced neighboring recovery hunk from the index through exact Git blob replacement; no working-tree file was overwritten.
- Validation: 83 focused runner/discovery/model-map tests passed with 3 expected platform skips. An in-memory execution of the staged runner blob rejects malformed, started and completed streams; staged signatures/digests and symlink/gitlink identity gates are present. Cached diff checks and the recovery-marker scan pass.
- Remaining: fresh Sol/high closure on R-011, then isolated commit, exact-ref validation/install and public release gates.

### 2026-07-19 — R-012 checked-out gitlink and durable-claim closure

- Sol/high found that gitlink marker and directory identity were insufficient when tracked or untracked files changed inside a checked-out submodule without changing its HEAD. The fingerprint could remain stable despite readable nested content drift.
- Changed: a checked-out gitlink now contributes a bounded recursive tracked plus untracked/nonignored content fingerprint and HEAD marker twice around capture; nested file/byte totals consume the outer limits, depth is bounded, and any marker/content mismatch fails closed. Uninitialized gitlinks retain a deterministic no-content marker.
- Additional owner checks: strict public fingerprint field types/constants are validated even when the worker copies an equally malformed expected object; the one-shot fallback claim now uses an exclusive fsynced JSON creation primitive before authority is exposed.
- Validation: the initial dirty-submodule test failed as expected before implementation. The updated discovery suite passes 18 tests; the focused runner/discovery/model-map/package set passes 90 tests with 3 expected platform skips; package validation passes.
- Remaining: full task-candidate validation and fresh Sol/high closure, then isolated commit and release gates.

### 2026-07-19 — R-013 complete candidate validation

- Changed: retained the stricter on-disk recursive gitlink contract and strengthened the exclusive fallback claim with a parent-metadata durability barrier plus Windows write-through no-replace publication.
- Validation: 18 discovery tests and 106 focused runner/model-map/package-contract tests pass with 3 expected platform skips; the complete repository suite passes all 393 tests with 4 expected platform skips; package validation passes.
- Isolation: discovery and recovery are staged together as the sole `2.3.0` candidate; the repository commit gate passes with no unstaged public package file. Fresh Sol/high review must inspect that exact cached tree before publication.
- Remaining: Sol/high closure, isolated commit, exact-ref install, tag and GitHub Release verification.

### 2026-07-19 — R-014 complete-stream availability closure

- Sol/high red signal: the classifier returned the first eligible object and ignored later auth, network, unknown, or differently eligible structured errors; the same review also observed that the neighboring release had staged its files during review.
- Changed: every explicit error record must now normalize to one identical eligible reason. Cancellation, timeout, and any non-missing pre-turn result artifact fail closed before the source claim. The normative routing/docs and package mutation contract state the same complete-stream rule.
- Validation: the new mixed-stream and termination/result regressions failed before implementation, then 81 affected runner/package tests passed with 3 expected platform skips; package validation passed.
- Isolation: restore the task-only index without altering the neighboring worktree, then rerun the complete candidate suite and fresh Sol/high review.
- Remaining: full validation, isolated-index closure, Sol/high acceptance, exact-ref install and publication.

### 2026-07-19 — R-015 post-fix full validation

- Validation: all 395 repository tests pass with 4 expected platform skips; package validation and working/cached diff checks pass.
- Isolation: pre-receipt task-only index tree `6410e19f71637c6c51044749bbc6f45676499f5b` contains none of the neighboring recovery schema, reader-floor, cause, or specification markers; the neighboring worktree remains untouched and the review prompt binds the final post-receipt tree separately.
- Remaining: fresh Sol/high review of this exact tree, then isolated commit, exact-ref install and first publication.

### 2026-07-19 — R-016 lossy-collector closure

- Sol/high A-022 red signal: `read_event_evidence` could omit an unrecognized error-bearing event such as `item.failed`, while structured stderr treated malformed JSON or non-UTF-8 bytes as an empty record set. Either omission could leave one eligible Spark record and authorize Terra.
- Changed: unrecognized error-bearing JSONL events now invalidate event evidence; structured stderr returns records plus an explicit validity flag, and unreadable, malformed, or non-object input fails the availability gate. End-to-end receipt tests cover both paths.
- Validation: the unknown-event receipt test failed before implementation; the updated 81-test affected suite passes with 3 expected platform skips, all 396 repository tests pass with 4 expected platform skips, and package validation passes.
- Remaining: isolated task-only index, fresh Sol/high acceptance, exact-ref install and first publication.

### 2026-07-19 — R-017 non-regular evidence/result closure

- A-023 returned `REVISE` on immutable task tree `95545e1d`: the staged predicate did not consume `structured_stderr_valid`, and existence checks could conflate non-regular artifacts with absence.
- RED/GREEN: the direct predicate mutation and directory fixtures failed before the owner fixes. `events.jsonl`, `stderr.log` and `result.md` now use no-follow `lstat`; only `FileNotFoundError` is absence, while directories, broken symlinks, FIFOs and unreadable objects fail closed. Package mutation tests require the validity predicate and every regular-file guard.
- Validation: 45 focused routing/evidence/package tests and all 399 repository tests pass with 4 expected platform skips; package validation, official plugin/skill validators and exact task-only tree audit pass. The repository-wide commit gate reports only the preserved unstaged neighboring release. Fresh Sol/high acceptance remains.

### 2026-07-19 — R-018 raw JSONL error-record closure

- Sol/high A-024 found that a wrapped eligible model error followed by raw `{"type":"usage_limit_exceeded",...}` or `{"code":"authentication_failed"}` JSONL could lose the raw record before classification and incorrectly authorize Terra.
- RED/GREEN: both exact receipt streams returned `model-unavailable` before the fix. The owner collector now retains top-level `code` and error-suffixed `type` records; the complete classifier sees conflicting/unknown evidence and rejects fallback. Package mutation tests bind the new collector branch and closed suffix vocabulary.
- Validation: 44 focused routing/evidence/package tests and all 399 repository tests pass with 4 expected platform skips; package validation, official plugin/skill validators and exact task-only audit pass. Fresh Sol/high acceptance remains.

### 2026-07-19 — R-019 closed JSONL protocol grammar

- Sol/high A-025 found that suffix matching remained open-ended: an unknown raw `{"type":"unknown_failure"}` record could be ignored and leave an earlier eligible model error authoritative.
- RED/GREEN: the new receipt regression returned `model-unavailable` before the fix. The owner collector now accepts only exact raw availability types or known non-error protocol types; top-level `code` is always classified, while every other unknown type invalidates evidence.
- Validation: 45 focused routing/evidence/package tests and all 399 repository tests pass with 4 expected platform skips; package validation, official plugin/skill validators, diff checks and exact task-only blob audit pass. Fresh Sol/high acceptance remains.

### 2026-07-19 — R-020 creation-bound runner-exit closure

- Sol/high A-026 found that coherent availability JSON could remain authoritative after a generic runner cleanup failure or when `codex-exit.json` was missing or malformed.
- RED/GREEN: the direct predicate rejected neither the new exit arguments nor a missing receipt artifact before implementation. Eligibility now requires a valid creation-bound Codex exit, exact exit-code/terminal/failure rederivation, `success=false`, and an empty cleanup-error list; the claim gate repeats the public exit/result/cancellation checks.
- Validation: 106 affected runner/evidence/discovery/package tests pass with 3 expected platform skips; all 403 repository tests pass with 4 expected platform skips; package and official plugin/skill validators, diff checks and isolated task-tree audit pass. Fresh Sol/high acceptance remains.

### 2026-07-19 — R-021 descriptor-bound artifact closure

- Combined Sol/high A-027 found that `lstat` followed by path-based reads left JSONL, structured stderr and final discovery results vulnerable to regular-file, symlink or reparse replacement between check and open. External test drift also invalidated the exact reviewed worktree.
- The owner now reads every present routing artifact from one verified regular non-reparse descriptor. Initial and final path identities, opened and final descriptor identities, type, size, mtime and bytes through EOF must agree; only initial no-follow absence is missing.
- Swap-at-open regressions cover JSONL, stderr, generic final result and strict discovery-result validation. Package mutation coverage requires the shared reader, `O_NOFOLLOW`, both `fstat` barriers and final path identity. Focused closure and package validation pass; complete suite, combined commit-gate, clean install and fresh Sol/high acceptance remain.

### 2026-07-19 — R-022 source fallback-binding closure

- Sol/high A-028 found that a Spark source request with an injected `search_fallback_binding.reason` could republish that reason after the clean eligibility predicate returned none; the claim gate rejected nested fallback sources but not a source-side binding.
- A Spark source now requires both `search_fallback_source` and `search_fallback_binding` to be null. Public source receipts ignore any injected binding, and claim preparation rejects it before consuming a reason. Only the owner-generated Terra target binding can publish the freshly derived source reason.
- Receipt, claim-gate and package-mutation regressions pass. The complete repository suite passes all 403 tests with 4 expected platform skips; package, official plugin and official skill validators pass; the exact 30-file combined commit gate and both whitespace checks pass with no unstaged path; and the clean enabled 2.3.0 install is byte-equal across all 46 source/cache files. Fresh unchanged-tree Sol/high acceptance remains before publication.
