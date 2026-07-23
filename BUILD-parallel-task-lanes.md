# Build: параллельные task lanes OpenBuild

- Status: In progress — M1, M2 and M3a reservation core complete; M3b runner safe-stop/rebind and integration-owner handshakes are next after the `2.4.0-alpha.3` milestone release
- Last updated: 2026-07-23
- Original request: Поддержать безопасную параллельную работу нескольких независимых экземпляров OpenBuild над разными ТЗ одного Git-проекта. Непересекающиеся части должны выполняться одновременно, пересекающиеся файлы, контракты и runtime-ресурсы — ожидать освобождения scope, а большие задачи — дробиться на небольшие независимо проверяемые и интегрируемые milestones. Подготовить GitHub-facing документацию и выпустить новую стабильную версию плагина после реализации и validation.
- Primary signal: детерминированный concurrency-тест запускает минимум две независимые task lanes одного Git common directory, подтверждает параллельное выполнение непересекающихся milestones, сериализацию пересекающегося scope до принятия предыдущего результата в общую integration base и локализацию crash/quarantine одной lane без остановки соседей и потери изменений.
- Review baseline: `main@6e75b861f2c3f202f7db65d2bf346ec70ad576f8`; исходный status `## main...origin/main`, staged/unstaged/untracked изменений нет, remote `origin` настроен.
- Workflow target: Run
- Starting phase: M1 project-state contract
- Specification revision: R-032
- Complexity: high — меняются concurrency, Git/worktree ownership, durable registry, process containment, recovery, ordering, commits и публичный workflow плагина.
- Implementation mode: TDD-first — изменения затрагивают state machine, leases, routing, concurrency, recovery и Git-интеграцию.
- Version impact: minor, ожидаемо `2.3.6 -> 2.4.0` — новая обратно совместимая capability; если authoritative version изменится до implementation, выбирается следующая допустимая minor-линия. D-008 требует GitHub-facing docs, stable tag и GitHub Release после green validation. В режиме `refine` version-файлы не меняются, commit/tag/release не создаются.
- Routing mode: `codex-exec-explicit-model` для critic/implementation/review; discovery завершён через `root-recovery`.
- Discovery mode: root-recovery — новый run-discovery A-030 завершился с `turn.completed` и exit code `0`, но `result_evidence=invalid`; его содержимое не использовано. Исторические A-001/A-025 остаются в agent ledger.
- Search usage route: root-recovery — Spark availability fallback запрещён, поскольку failure не был `model-unavailable` или `quota-exhausted`; circuit breaker открыт для текущего Build-run.
- Search routing receipt: packaged map `3f9eceafea582baa2394a0c9744c0dbfc260b4daeb37475aca3f1c611e007701`, step `1/1`, `openbuild_search_separate`, configured `gpt-5.3-codex-spark`/low/read-only, exact runner, terminal transport success, unusable evidence.
- Implementation model route: packaged map `3f9eceafea582baa2394a0c9744c0dbfc260b4daeb37475aca3f1c611e007701`, high risk: `openbuild_implementation_balanced` (`gpt-5.6-terra`/medium) -> `openbuild_implementation_strong` (`gpt-5.6-terra`/xhigh) -> `openbuild_implementation_sol_high` (`gpt-5.6-sol`/high), только по допустимому pre-edit semantic evidence; transport fallback отсутствует.
- Implementation routing receipt: A-031 M1a completed and was finalized as a bounded scaffold; A-032 returned zero-write normalized `capability-gap` and was durably rejected with checkpoint invalidation; A-033 route step 2 timed out after edits, was cancelled with full-tree-zero and left an owner-private recovery checkpoint.
- Review routing receipt: для будущего implementation high-risk route: balanced -> strong -> Sol/high только по подтверждённым findings; readiness critic использует отдельные exact read-only receipts.

## 1. Outcome

### Problem

Текущий OpenBuild безопасно восстанавливает один write-capable lifecycle, но его безопасность основана на глобальном инварианте «один активный writer в shared workspace». Registry содержит один `lease`, а recovery checkpoint связывает `HEAD`, ref, полный index, status, ignored inventory и allowed paths. Поэтому любое изменение второго окна того же checkout выглядит как `git-control-plane-drift`, `outside-set-drift` или `preexisting-dirty-overlap`; второй implementation-start отклоняется как `workspace is not vacant`.

Пользователь запускает разные ТЗ, а не несколько исполнителей одного ТЗ. Он хочет продолжать независимые задачи параллельно и сериализовать только реально пересекающиеся участки, не ослабляя fail-closed recovery.

### Desired behavior

Один Git-проект образует project session. Каждое независимое ТЗ получает отдельную task lane: собственные worktree, branch, workspace registry, process containment и единственного writer. Project coordinator знает все lanes, их milestones, hard leases, soft intents, runtime resources и integration state.

Непересекающиеся milestones исполняются параллельно. Если milestone запрашивает занятый file/directory/contract/resource scope, он не пишет этот scope, завершает либо не запускает текущий bounded worker и переходит в `waiting-for-scope`. Scope освобождается только после доказанной остановки прежнего writer, проверки, coherent commit и принятия результата в общую integration base. Ожидающая lane затем обновляет baseline, повторно проверяет затронутые требования и получает lease.

### In scope

- отдельная worktree/branch lane для каждого независимого ТЗ;
- сохранение одного writer и текущей recovery-машины внутри каждой lane;
- project-wide registry, привязанный к Git common directory и координирующий lanes;
- hard leases для файлов, директорий, логических контрактов и runtime-ресурсов;
- soft intents для будущих вероятных scopes без преждевременной блокировки;
- динамическое расширение hard scope только до первой записи в новый scope;
- task-internal DAG небольших независимо проверяемых и интегрируемых milestones;
- последовательная integration queue и передача scope после принятия результата в общую базу;
- обнаружение stale read/contract dependencies и обязательная повторная проверка;
- deadlock prevention/recovery;
- lane-local quarantine и recovery без остановки соседних lanes;
- namespace или exclusive lease для ports, test databases, Docker Compose projects, temp/build outputs и иных runtime-ресурсов;
- observable statuses, diagnostics и bounded capacity для сценария от двух до десяти lanes;
- совместимость и миграция нынешней single-workspace registry.
- GitHub-facing документация: README EN/RU, usage/migration/limitations, architecture/lifecycle diagrams, contributor guidance, changelog и release notes;
- новая стабильная SemVer-версия, Git tag, GitHub Release и remote-install verification после полного validation/review gate.

### Out of scope

- параллельные writers в одном checkout;
- несколько writers над одним milestone или одним ТЗ без task decomposition;
- автоматическое semantic merge конфликтующих продуктовых решений;
- произвольные «коммиты на каждый файл» без coherent outcome и green validation;
- молчаливое копирование незакоммиченных пользовательских изменений во все lanes;
- автоматическое разрешение Git merge conflicts;
- изменение model-routing ladder, provider или reasoning policy;
- distributed coordination между разными компьютерами и OS-учётками в первой версии;
- hosted coordinator, новая production dependency или внешняя инфраструктура;
- любые commit, tag, GitHub Release или публикация версии в рамках текущего specification-only `new`;
- публикация implementation release до green full validation, exact review, version/docs synchronization и remote-install smoke.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Публичный writer contract | `plugins/openbuild/skills/build/SKILL.md:120-130` | Shared workspace допускает одного writer, root не пишет при активном lease | Новый capability должен сохранить инвариант внутри lane, а не ослабить его глобально |
| Делегирование | `plugins/openbuild/skills/build/references/implementation-delegation.md:7-13` | Доступны root-only, bounded-worker и sequential-workers; parallel write-heavy workers в одном checkout запрещены | Параллелизм обязан использовать разные checkout/worktree |
| Lease gate | `plugins/openbuild/skills/build/references/implementation-delegation.md:128-160` | Lease содержит milestone, allowed/forbidden files, baseline и stop conditions; overlap запрещает выдачу | Это основа lane-level hard lease |
| Handoff | `plugins/openbuild/skills/build/references/implementation-delegation.md:185-205` | Scope освобождается после root verification, finalization, guardian close и registry vacancy; Git root-owned | Project scope нельзя освобождать по одному факту worker commit |
| Workspace identity | `plugins/openbuild/skills/build/scripts/recovery_state.py:2042-2128` | Workspace registry ключуется object identity корня, отдельно хранит Git common-directory identity | Разные worktree могут иметь lane-local registries; нужен дополнительный common-dir project registry |
| Одна vacancy | `plugins/openbuild/skills/build/scripts/recovery_state.py:2684-2785` | Registry vacant только при `lease=None` и `outbox=None`; `reserve_normal` отклоняет второй lease | Текущую registry нельзя просто превратить в конкурентный список без смены ownership model |
| Полный Git snapshot | `plugins/openbuild/skills/build/scripts/recovery_state.py:3606-3690` | Checkpoint связывает `HEAD`, ref, полный index/status, ignored и allowed inventories | Изменения соседнего writer в том же checkout неизбежно загрязняют provenance |
| Drift classification | `plugins/openbuild/skills/build/scripts/recovery_state.py:3831-3895` | Изменение Git control plane, outside paths или pre-dirty allowed path делает recovery ineligible | Игнорирование dirty checks недопустимо |
| Runner start | `plugins/openbuild/skills/build/scripts/agent_runner.py:5553-5577`, `5749-5776` | Implementation start проверяет текущий lease и отклоняет non-vacant workspace | Нужна маршрутизация `repo` в lane до lane-local dispatch |
| Concurrency regression | `scripts/test_recovery_state.py:1665-1690` | Два одновременных normal-start в одном workspace детерминированно дают ровно один reservation | Existing test должен сохраниться как lane-local invariant |
| Checkpoint regression | `scripts/test_recovery_state.py:1619-1643`, `1864-1904` | Tests доказывают opaque snapshot, допустимые owned changes и отклонение outside/pre-dirty/Git drift | Новая модель не должна ослабить privacy и attribution |
| Package contract | `scripts/validate_package.py:74-121`, `3508-3553`; `scripts/test_validate_package.py:654-661`, `1218-1232` | Executable validator включает marketplace/manifest/docs surfaces, проверяет version/changelog/install pins; tests механически защищают single-writer, exact routing и root handoff | Validator и его tests нужно расширить с shared-workspace до per-lane + project coordinator, сохранив прежние gates |
| Marketplace contract | `.agents/plugins/marketplace.json:1-20`, `plugins/openbuild/.codex-plugin/plugin.json:1-20` | Marketplace объявляет local plugin, `AVAILABLE` и `ON_INSTALL`, а plugin manifest содержит только skill/interface capability и не предоставляет executable lifecycle hook | D-010 остаётся на первом явном Build, а release validation обязан сохранить install contract |
| Validation | `CONTRIBUTING.md:41-62` | Поддерживаемые checks: unittest discovery, package validator, diff checks, commit gate | Это authoritative validation path |
| Versioning | `CONTRIBUTING.md:10-39`, `plugins/openbuild/.codex-plugin/plugin.json:1-20` | Manifest `2.3.6` — source of truth; backward-compatible capability имеет minor impact | Реализация ожидаемо поднимает версию до `2.4.0` и синхронизирует docs/changelog |
| Worktree coverage gap | targeted root search по `scripts/`, `plugins/openbuild/` | Нет production lifecycle или tests для `git worktree add/remove`, project integration queue и cross-worktree scope leases | Capability отсутствует, а не скрыта за конфигурацией |
| Specification selection | headings и Original request всех `BUILD*.md`, `TZ.md` | Существующие документы описывают model routing, recovery и прошлые releases, но не parallel task lanes | Выбран новый `BUILD-parallel-task-lanes.md`; чужие ТЗ не переписываются |

### Source of truth

- Пользовательские outcomes, выбранная модель параллельной работы, conditional mixed-version policy, automatic first-invocation setup и обязательный release outcome: D-001–D-010 resolved.
- Текущий исполняемый lifecycle: `recovery_state.py` и `agent_runner.py`.
- Текущие публичные и нормативные контракты: `SKILL.md`, `implementation-delegation.md`, `tdd-workflow.md`, `model-routing.md`, README EN/RU.
- Version/release policy: `plugins/openbuild/.codex-plugin/plugin.json` и `CONTRIBUTING.md`.
- Это ТЗ становится source of truth для нового parallel-task-lanes capability; production contracts остаются authoritative для существующего поведения до реализации.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decision IDs | Outgoing normative links and discovery evidence | Editable | Reconciliation state |
|---|---|---|---|---|---|---|
| `BUILD-parallel-task-lanes.md` | пользователь + root synthesis | R-032 | Новый capability, D-001–D-010, T-001–T-022, AC-01–AC-38 | I0 capability, permanent key, immutable anchor lock, automatic first-invocation setup, validator-safe transition IDs and the cross-owner expansion/integration handshakes close bootstrap/release ownership | yes | root source |
| Текущий диалог 2026-07-23 | user | current answer | D-001–D-010 resolved | D-009 option 2a сохраняет conditional legacy policy; D-010 option 1a автоматически выполняет setup при первом явном Build до repository discovery | no | aligned |
| `plugins/openbuild/skills/build/SKILL.md` | shipped plugin contract | 2.3.6 | single writer, lifecycle, recovery, Git ownership, specification readiness | Outgoing normative edges audited: `code-discovery.md`, `model-routing.md`, `spec-template.md`, `blindspot-protocol.md`, `implementation-delegation.md`, `tdd-workflow.md`, `versioning.md`, `minimality-protocol.md`, `review-protocol.md`, `model-map-interview.md`; `SKILL.md:41,112-127,183,242-277` | yes | conflict limited to project-wide serialization; lane-local invariants preserved |
| `plugins/openbuild/skills/build/references/implementation-delegation.md` | shipped delegation contract | 2.3.6 | writer lease, allowed set, handoff, sequential workers | Outgoing edge `model-routing.md:24`; owns handoff/lease rules at `128-205` | yes | must extend to cross-worktree lanes without parallel writers per checkout |
| `plugins/openbuild/skills/build/references/tdd-workflow.md` | shipped implementation contract | 2.3.6 | coherent milestone, same writer red/green cycle | Outgoing edges `implementation-delegation.md:3,20` and `minimality-protocol.md:22` | yes | aligned; milestone granularity and project lease gates need additions |
| `plugins/openbuild/skills/build/references/model-routing.md` | shipped routing contract | 2.3.6 | `writer_policy=single`, exact agents, transport rules | Outgoing edges `implementation-delegation.md:14,133`, `model-map-interview.md:32,149`, `review-protocol.md:92`, `code-discovery.md:119` | yes | preserve one writer per lane; clarify project concurrency is not model fan-out |
| `plugins/openbuild/skills/build/references/code-discovery.md` | shipped discovery contract | 2.3.6 | per-workspace fingerprint and read-only discovery | Outgoing edge `implementation-delegation.md:3`; no implementation write authority | yes | lane discovery must bind the correct worktree; no weakening |
| `plugins/openbuild/skills/build/references/spec-template.md` | shipped specification contract | 2.3.6 | required source map, ledgers, milestones, Ready evidence | Links to blindspot and decision-provenance requirements | yes | R-028 closes the previously incomplete source graph |
| `plugins/openbuild/skills/build/references/blindspot-protocol.md` | shipped readiness contract | 2.3.6 | coverage ledger, critic closure, current-revision readiness | Links to specification and critic routing contracts | yes | B-023 and fresh R-028 closure apply it |
| `plugins/openbuild/skills/build/references/minimality-protocol.md` | shipped implementation contract | 2.3.6 | evidence-gated minimality after Ready | Links current requirements, owner layer and review audit | yes | future implementation gate; no product decision |
| `plugins/openbuild/skills/build/references/review-protocol.md` | shipped review contract | 2.3.6 | progressive review, version/docs/release evidence | Outgoing edges `tdd-workflow.md:133`, `minimality-protocol.md:134`; exact model routing is an input contract | yes | future implementation/release gate; readiness critic remains separate |
| `plugins/openbuild/skills/build/references/model-map-interview.md` | shipped configuration contract | 2.3.6 | complete model-map interview only | Outgoing edge `model-routing.md:49`; routing changes explicitly out of scope | yes | audited, no feature change |
| `plugins/openbuild/skills/build/references/versioning.md` | shipped release contract | 2.3.6 | minor capability and same-commit synchronization | Manifest, changelog, README surfaces named by policy | yes | aligned |
| `README.md`, `README.ru.md` | public user contract | 2.3.6 | one writer, recovery, Git behavior and install/update path | Outgoing edges: each other, pinned GitHub release tree, six current workflow/routing/delegation PNGs, CONTRIBUTING, CHANGELOG and LICENSE; assets are explanatory, LICENSE is legal, pinned tree is release verification | yes | future docs/diagram update required |
| `CHANGELOG.md` | repository release history and release-note source | 2.3.6 + Unreleased | released behavior, migration/security notes, future 2.4.0 notes | Outgoing SemVer edge is mapped; `di-sukharev/code-scout-skill` link at line 97 is attribution/provenance only and explicitly says no vendored code/runtime dependency | yes | future capability/release entry required |
| `CONTRIBUTING.md` | repository policy | current | tests, SemVer, per-commit version and release gates | Links manifest, changelog, README and SemVer; commands at lines 41-89 | yes | aligned; validation must expand |
| `plugins/openbuild/.codex-plugin/plugin.json` | authoritative version source | 2.3.6 | version and public capability metadata | No normative companion edge in file | yes | future `2.4.0` candidate |
| `.agents/plugins/marketplace.json` | marketplace installation policy | current | plugin availability, local source and install-time authentication policy | Points to `./plugins/openbuild`; executable package validator includes this manifest | yes | no lifecycle/setup hook; D-010 automatic first-Build ownership unchanged |
| `plugins/openbuild/skills/build/agents/openai.yaml` | public skill invocation interface | 2.3.6 | display metadata, auto-mode default prompt and explicit-only invocation | Mechanically enforced by `scripts/validate_package.py:5221-5225`; no outgoing lifecycle edge | yes | supports D-010 explicit-Build boundary but is not an install/lifecycle hook |
| `plugins/openbuild/lib/{Workflow,usage-v3,delegat}-{en,ru}.png` | public explanatory diagram assets | 2.3.6 | current workflow, routing and delegation illustrations | Reached only from README EN/RU; no outgoing executable edge | yes | non-normative visual docs; future parallel-lane diagrams required by D-008 |
| `LICENSE` | repository legal contract | MIT | distribution/license terms | Reached from both READMEs and validated by `validate_package.py`; no feature behavior edge | yes | out of feature scope and unchanged |
| `https://github.com/GeorgVahi/OpenBuild/tree/v2.3.6/plugins/openbuild/skills/build` | published release artifact | v2.3.6 | immutable current pinned skill tree | Reached from both READMEs; future M8 replaces pins only with the validated new tag | no | current release evidence, not design authority |
| `https://github.com/di-sukharev/code-scout-skill` | external attribution | current linked repository | provenance for ideas adapted in 2.3.0 | Reached only from CHANGELOG:97; changelog states no code/runtime dependency is vendored | no | explanatory/non-normative |
| `https://semver.org/` | Semantic Versioning specification | 2.0.0 | MAJOR/MINOR/PATCH meaning and immutable released versions | External standard linked by CHANGELOG/CONTRIBUTING | no | minor target and no tag rewrite aligned |

### Executable implementation-evidence registry

These sources prove current ownership and mechanical package behavior. They are authoritative for the executable behavior present on the baseline, but they do not independently authorize a new product outcome or override D-001–D-010. The cited owner ranges were inspected during discovery; future implementation MUST repeat risk-scoped call-graph and test discovery against the then-current baseline instead of treating this registry as a complete code transcription.

| Source | Classification and incoming edge | Inspected owner/test evidence | Authority boundary |
|---|---|---|---|
| `plugins/openbuild/skills/build/scripts/agent_runner.py` | executable lifecycle owner; named by `SKILL.md` and implementation delegation | implementation start/preflight at `5553-5577`, `5727-5776`; exact dispatch/result evidence remains covered by current tests and package checks | authoritative for current runner behavior, not product authority for parallel lanes |
| `plugins/openbuild/skills/build/scripts/model_map.py` | executable routing-map resolver; named by `SKILL.md`, `model-routing.md` and `model-map-interview.md` | precedence and route resolution `386-449`; packaged map validation is exercised before every created agent; R-031 does not change its route | authoritative for current route resolution, explicitly out of feature scope |
| `plugins/openbuild/skills/build/profiles/openbuild_model_map.toml` and canonical profile TOMLs | executable routing configuration; loaded and validated by `model_map.py` under `model-routing.md` | current packaged map hash and exact route/profile receipts are recorded in workflow metadata and agent ledger | configuration evidence only; model/provider/reasoning policy explicitly out of feature scope |
| `plugins/openbuild/skills/build/scripts/discovery_contract.py` | executable discovery evidence owner; imported by `agent_runner.py:45-49` and required by `code-discovery.md` | schema/fingerprint owner `17-66,506-752`; result validation `753-839` | authoritative for current read-only discovery validation, not implementation or product authority |
| `plugins/openbuild/skills/build/scripts/recovery_state.py` | executable workspace lifecycle owner; reached from implementation delegation and current-state discovery | registry identity `2042-2128`, vacancy/reservation `2672-2785`, snapshot `3606-3690`, drift `3831-3895`; regressions `scripts/test_recovery_state.py:1619-1690,1824-1904` | authoritative for current lane-local recovery behavior, not permission to weaken its gates |
| `scripts/validate_package.py` | executable package/release contract; named by both READMEs and CONTRIBUTING | package surfaces `74-121`, changelog/install-pin checks `3508-3553`, commit/version gate `4323+` | mechanical repository policy enforcement, not an independent product-decision source |
| `scripts/test_discovery_contract.py` | discovery verification owner; imports `discovery_contract.py:17-22` | fingerprint/result/path/drift tests `130-158,253-304,392-517` | test evidence only; cannot authorize writes or change product scope |
| `scripts/test_agent_runner.py` | runner verification owner; imports the packaged runner at `23-29` | exact invocation `1224+`, prompt activation/staging `5157-5421`, atomic dispatch `5628-5701`, result/timeout evidence `5888-7275` | test evidence only; future lane dispatch changes require fresh TDD discovery |
| `scripts/test_model_map.py` | routing verification owner; imports `model_map.py:12-18` | precedence/routes `59-235`, discovery fallback `237-288`, ladder constraints/resolution `300-426` | test evidence only; model routing remains out of feature scope |
| `scripts/test_recovery_state.py` | recovery verification owner; constructs `RecoveryRegistry` at `33`, contract suite at `55+` | concurrency/checkpoint/drift `1619-1690,1741+,1824-1906`; terminal/recovery fault coverage continues through `3904` | test evidence only; preserves lane-local owner gates |
| `scripts/test_validate_package.py` | verification evidence for package validator; reached from CONTRIBUTING validation commands and validator ownership | version synchronization `654-661`, changelog/install pins `1218-1232`, existing lifecycle contract fixtures `839-905` | test evidence only; cannot override specification, manifests or contributor policy |

### Source reconciliation receipts

| Source/conflict | Resolution basis | Authority provenance or user decision | Result |
|---|---|---|---|
| Global single writer против parallel tasks | Разделить project concurrency и checkout concurrency | D-001, D-002: разные ТЗ параллельны, но каждый worktree сохраняет одного writer | aligned by lane isolation |
| Release file после commit против visibility соседней lane | Release только после integration acceptance и baseline refresh | D-003, D-004; текущий handoff contract `implementation-delegation.md:185-205` | aligned |
| Частые commits против coherent milestones | Commit на independently valid milestone, не на произвольный файл | D-005 | aligned |
| Dirty исходный checkout против создания lanes | Pre-session dirty paths объявляются внешним `protected-user-work`, а не task/recovery-owned состоянием | D-007 option 1a, user answer 2026-07-23 | independent lanes allowed; conflicting scopes wait until explicit verified adoption boundary |
| Текущий workspace-key против project coordination | Не заменять lane registry; добавить отдельный common-dir coordinator | T-001, evidence `recovery_state.py:2042-2128` | aligned as outcome-neutral mechanism |
| New project lock против late legacy 2.3.6 start/write | Legacy использует отдельный workspace registry/lock и не сериализуется external scan/project CAS | D-009 option 2a, user answer 2026-07-23 | strict guarantee conditional on compatible-client operator policy; breach is detected/quarantined, not claimed atomically prevented |
| R-027 source map против полного исходящего графа | Дочитать и явно отобразить все feature/release/readiness companion contracts, marketplace manifest и внешний SemVer edge | Repository facts from `SKILL.md`, README, CONTRIBUTING, CHANGELOG, manifests and package-validator ownership; D-001–D-010 unchanged | R-028 maps the normative companion graph; A-026 then required explicit executable-evidence classification, closed in R-029 |
| R-028 executable-owner omission | Явно классифицировать executable owners и tests, не превращая их в новый product authority | A-026 finding verified against `SKILL.md`, README/CONTRIBUTING and executable owner ranges | R-029 adds a bounded implementation-evidence registry; requirements, decisions and milestones unchanged |
| R-029 public interface/discovery/test-owner omission | Добавить explicit-Build public interface authority и прямые executable/test owners, ограничив их evidence-only роль | A-027 finding verified against `openai.yaml`, runner import, validator enforcement and test imports | R-030 closes interface/discovery/test evidence without changing D/T/RQ/AC/M tuples |
| R-030 validator collision и remaining outgoing edges | Reproduce package failure, assign owner/test contract, enumerate direct reference/README/changelog edges and classify external metadata | A-028 findings plus root reproduction `python scripts/validate_package.py`; exact Markdown-link audit | R-031 adds T-021/M1/M7/AC-24/38 ownership and closes source edges; D-001–D-010 unchanged |

### Gap

OpenBuild не имеет project session, lane lifecycle, common-dir registry, scope/resource leases, dependency-aware milestone scheduler или integration queue. Нынешняя корректность достигается запретом второго writer во всём checkout и полным snapshot provenance; поэтому простое ослабление vacancy/drift checks нарушит recovery guarantees.

## 3. Decision memory

### User-owned product decisions

| ID | Decision key | Owner | Status | Decision | Selected option | Evidence or reopen reason | Consequence |
|---|---|---|---|---|---|---|---|
| D-001 | project.multiple-tasks.parallel | user | resolved | Какие работы параллелить | Разные ТЗ одного проекта выполняются параллельно | Пользователь: «несколько задач разных… делать их параллельно» | Единица concurrency — task lane, не несколько workers одного ТЗ |
| D-002 | lane.checkout.isolation | user | resolved | Где могут одновременно писать задачи | Отдельные worktree/branch lanes; один writer внутри каждой | Пользователь поручил включить всю согласованную worktree-lanes модель | Параллельных writers в одном checkout нет |
| D-003 | overlap.waiting | user | resolved | Что делать при пересечении | Соседний milestone ждёт освобождения пересекающегося scope | Пользователь: пересечение endpoint/form должно ждать соседа | Конфликт сериализуется, остальные scopes продолжают работу |
| D-004 | scope.release.integration | user | resolved | Когда scope становится свободным | После полной остановки owner, проверки, coherent commit и принятия в common integration base | Пользователь принял уточнение, что raw commit соседней ветки недостаточен | Следующий owner всегда стартует от видимого integrated baseline |
| D-005 | task.internal-granularity | user | resolved | Как уменьшить время ожидания | Делить ТЗ на небольшие независимо проверяемые/integrируемые milestones и чаще фиксировать coherent outcomes | Пользователь прямо подтвердил более мелкое внутреннее дробление и частые commits | Hotspot scope освобождается раньше конца всей задачи |
| D-006 | waiting.task-progress | user | resolved | Должна ли задача полностью простаивать | Она продолжает независимые milestones; bounded worker не держится idle на ожидании | Пользователь поручил включить весь предложенный scheduler behavior | Waiting — durable task state, а не живой бездействующий процесс |
| D-007 | dirty.baseline.origin | user | resolved | Как обращаться с pre-session dirty checkout, у которого ещё нет task lane и trusted task baseline | Option 1a: считать его paths `protected-user-work`; разрешать независимые lanes, конфликтующие ставить в ожидание; task ownership появляется только после отдельной verified adoption boundary | Пользователь ответил `1а` на варианты D-007 после architecture critique | Dirty work не приписывается recovery/task lane, не копируется и не коммитится автоматически; его scopes остаются зарезервированы пользователем до явного принятия |
| D-008 | release.github-docs-stable | user | resolved | Что должно сопровождать capability после реализации | Подготовить GitHub-facing docs и выпустить новую стабильную SemVer-версию с tag, GitHub Release и remote-install verification | Пользователь: «добавь в тз подготовку доков для гит и релиз новой версии» | Documentation и publication становятся обязательными завершающими milestones после green validation/review |
| D-009 | migration.mixed-version-admission | user/external operator | resolved | Какая safety semantics допустима, если legacy 2.3.6 может стартовать/писать между external scan и project CAS | Option 2a: one-time drain/update + disable ordinary legacy entry points; strict guarantee действует условно на operator policy «archived legacy binary не запускается». Policy breach может мутировать свой worktree/ref до detection, после чего managed integration/release блокируется и все данные сохраняются | Пользователь ответил `2a` после R-011 atomicity reopen | Реалистичная migration safety без второго clone/OS broker; документация обязана явно назвать condition, breach behavior и отсутствие atomic legacy exclusion |
| D-010 | coordinator.setup-ux | user | resolved | Кто выполняет one-time I0 setup, если Codex plugin manifest не предоставляет install/update lifecycle-hook | Option 1a: первый явный `$openbuild:build` автоматически выполняет setup до repository discovery и затем продолжает исходный mode; отдельный mandatory setup command не добавляется | Пользователь ответил `1а` после R-025 critic и root verification `plugin.json`/README install flow | Install остаётся стандартным; первый Build имеет bounded observable setup phase, а insecure/tampered existing I0 fail-closed возвращает `setup-required` без молчаливого ремонта |

### Technical decision ledger

| ID | Mechanism choice | Status | Evidence and alternatives | Preservation proof |
|---|---|---|---|---|
| T-001 | Двухуровневое состояние: lane-local текущая RecoveryRegistry + новый project coordinator | selected | Замена текущего registry массивом leases затронула бы зрелую recovery state machine; workspace и common-dir identities уже различимы | D-001/D-002 и все terminal/containment invariants сохраняются |
| T-002 | Project identity ключуется нормализованной, identity-checked Git common directory и OS account; lane identity дополнительно связывает worktree root, branch/ref и creation record | selected | Common directory объединяет worktrees, workspace root их различает | Не меняет user-visible behavior, предотвращает cross-project/cross-account collision |
| T-003 | Hard scope имеет тип `file`, `directory`, `contract` или `resource`; file/directory paths нормализуются case-aware и не следуют symlink/reparse | selected | Одних file locks недостаточно для API contracts, migrations, ports и DB | D-003 выполняется для физического и логического overlap |
| T-004 | Scope release — отдельный project event после lane terminal evidence и integration acceptance; worker commit сам lease не освобождает | selected | Commit ветки не меняет baseline соседней lane | Сохраняет D-004 и существующий root handoff |
| T-005 | Task plan — DAG milestones; hard lease только текущего ready milestone, soft intent — будущая подсказка scheduler | selected | Task-wide locks убивают concurrency, отсутствие intents создаёт collision churn | Сохраняет D-005/D-006 без слабой атрибуции |
| T-006 | Dynamic scope expansion проходит atomic pre-write grant; конфликт переводит task в waiting после safe stop | selected | Post-write grant не может доказать ownership | Сохраняет allowed-set и fail-closed invariants |
| T-007 | Deadlock предотвращается planned-set reservation и canonical ordering; обнаруженный dynamic cycle прерывает более новую невыполненную reservation, но не отбирает live writer lease | selected | Force-release live lease нарушил бы containment; бесконечное ожидание недопустимо | Не теряет writes и даёт детерминированный progress |
| T-008 | Интеграция выполняется последовательно в выделенной integration lane/ref с compare-and-swap base; target checkout с user dirty state не перемещается | selected | Общий index/HEAD нельзя обновлять параллельно или под dirty checkout | D-004/D-007, Git ownership и no-lost-work сохраняются |
| T-009 | Runtime isolation использует lane namespace, а non-namespacable ресурсы — exclusive resource lease; capacity scheduler ограничивает тяжёлые jobs отдельно от количества lanes | selected | Worktree не изолирует ports/DB/Docker names | Наблюдаемый результат тот же, races исключаются |
| T-010 | Fairness задаётся monotonic ticket: старейший eligible conflicting scope waiter не может быть обойдён более новым; capacity waiter не обгоняется job, поставленным позже; dependency-unblocking integration использует отдельную очередь и не меняет возраст waiters | selected | Один finite stress без adversarial arrivals не доказывает отсутствие starvation | Сохраняет D-003/D-006 и делает progress наблюдаемым без изменения product outcome |
| T-011 | Один common-dir project registry имеет authoritative session epoch; все coordinator clients attach к нему через owner lock и generation CAS, а несовместимый target/session request не создаёт второй epoch | selected | Без admission fence два окна могут создать независимые registries и double-owner | Сохраняет D-001/D-002 и все scope invariants; меняется только механизм общей координации |
| T-012 | Project registry вводит writer floor и client-version binding; lower writer не может выполнить transition после floor promotion. Unregistered/legacy worktree считается external protected actor, не получает scope и не интегрируется автоматически; active discoverable legacy lease блокирует conflicting admission до vacancy | selected | Reader floor без writer fencing не защищает от live mixed-version overwrite; старый plugin не знает новую schema | Сохраняет user work и fail-closed compatibility без обещания управлять старым процессом |
| T-013 | Project registry и lock используют проверенные owner-private durable primitives: current-user DACL/`0700`, regular non-reparse no-follow lock/object identity, bounded schema+digest, atomic write-through replace, file+parent fsync/rebarrier и reload validation | selected | Lane registry уже применяет этот класс защиты; новая registry/lock иначе допускает substitution/tamper | Не меняет observable outcome; сохраняет privacy, single-owner и replay invariants |
| T-014 | `protected-user-work` использует CAS state machine `protected -> adoption-intent -> adopted|protected`: explicit user action связывает exact scopes, checkout/index/content identity и либо user-created commit, либо отдельный managed adoption plan; scopes остаются protected до validation и integration acceptance, а crash replay завершает transition ровно один раз | selected | Одного blocked-state недостаточно: без durable adoption lifecycle scope либо вечный, либо может быть снят молча | Реализует D-007 option 1a без automatic snapshot/commit/import и без ложного task/recovery owner |
| T-015 | Live hold-and-wait запрещён. Dynamic cycle выбирает newer wait-edge victim, safe-stops его writer и сохраняет diff; held scopes освобождаются только после coherent-prefix integration либо root-owned `abandoned-no-change` transaction с immutable diff archive, restore-to-admitted-base, focused green, binding к уже accepted admitted-base commit и durable accepted no-op integration receipt без нового Git commit | selected | Снятие live lease небезопасно, а новый empty commit обязан bump'нуть version metadata и уже не является no-change | Сохраняет D-004 intent: следующий owner видит accepted coherent base, worker diff не теряется, ложный release commit не создаётся |
| T-016 | Release gate двухфазный: validated stable release commit и clean install существуют до publication; annotated tag/GitHub Release создаются только после pre-publication audit, затем public tag/Release и remote install проверяются post-publication | selected | AC-31 не может одновременно быть входным условием и результатом M8; порядок закреплён `CONTRIBUTING.md:79-89` | Сохраняет D-008, publication authority и immutable-tag policy |
| T-017 | В начале implementation выбирается stable target minor; каждый промежуточный non-empty commit получает следующий уникальный prerelease этой линии, а M8 единожды заменяет последний prerelease на stable target | selected | `CONTRIBUTING.md:18-31` требует strictly higher unique version в каждом commit; ранний stable target сделал бы последующие commits несовместимыми | Сохраняет ожидаемый stable `2.4.0` outcome и repository commit gate |
| T-018 | Prerelease numbers выдаёт durable project-wide monotonic allocator только в момент root-owned integration finalization под `contract:version-metadata`; tickets CAS-bound, никогда не переиспользуются, workers не правят version surfaces, а failed/reordered lane rebase'ится и получает новый номер | selected | Parallel branches иначе создают duplicate/out-of-order `alpha.N` и постоянно конфликтуют по manifest/changelog/README | Сохраняет D-005/D-008: code work параллелен, coherent commits/integration и version metadata сериализованы |
| T-019 | Failed untagged stable candidate не переписывается и не публикуется: receipt фиксирует его как superseded, corrective work переходит на следующую строго большую patch prerelease line и новый stable target; failed published release также исправляется только новой версией | selected | После `2.4.0` нельзя вернуться к `2.4.0-alpha.*`, amend/rewrite/tag retarget запрещены | Сохраняет immutable history/tags и D-008 stable release outcome без ложного success |
| T-020 | Upgrade admission использует automatic first-invocation I0 setup authority, permanent no-replace HMAC key, I0-issued per-project bootstrap capability, atomic BA0 anchor directory with immutable lock/manifest and separate mutable records, C/E/O, clean B0, breach BS and exact registry. Первый явный `$openbuild:build` invokes I0 before repository discovery, emits setup status/receipt, then continues the requested mode. The in-memory I0 bootstrap context is the sole formal pre-durable exception and may touch only the fixed coordinator path; once I0 exists, every BA0 sink consumes its durable capability under the identity-stable lock. Clean B0 or breach BS consumes/transfers one anchor epoch. Prompt key initialization remains an optional first ordinal inside one `O4.prompt-snapshot.stage`; all eight named reads are sink-free. Preservation/publication and conditional non-atomic D-009 rules remain | selected | Formalizes the unavoidable trust bootstrap, removes BA0 pre-receipt circularity, lock replacement split and HMAC rotation race without adding a service or manual install step | Сохраняет current recovery gates, no-lost-work, D-007/D-009 and one epoch/gen-0 outcome; D-010 adds only a bounded automatic first-run phase |
| T-021 | Package validator получает registry-aware distinction между exact registered ordinary-transition IDs/references `O1`–`O8` и реальными fixed model slugs. Маскируются только доказанно зарегистрированные transition tokens/closed class references до model scan; bare/assignment/model-context `o<digit>` любого регистра и все остальные model patterns остаются запрещены | selected | Current `fixed_model` regex at `scripts/validate_package.py:5529-5544` falsely matches this specification; `python scripts/validate_package.py` reproduces `fixed model slug is not allowed`. Renaming mature transition classes or globally weakening case-insensitive model detection is less safe | Сохраняет stable transition registry и prohibition на pinned models; M1/M7 обязаны добавить positive transition-ID fixtures и negative lowercase/uppercase model-slug controls |
| T-022 | Live dynamic expansion и scope release используют два явных cross-owner handoff. Для running lane project owner сначала публикует generation-bound safe-stop/rebind intent; lane-local runner обязан durable consume intent, остановить creation-bound tree, доказать full-tree-zero и либо attach новый allowed-set до первого write, либо оставить milestone waiting с прежними hard scopes. Scope release принимает только registry-resident integration-owner acceptance, связанный с project/session/common-dir/integration-ref, terminal archive, writer, admitted/accepted commits и validation result; caller-generated receipt/boolean не имеет authority | selected | M3 strong review воспроизвёл, что один state marker не останавливает live runner, static lane scopes не расширяют allowed-set, а self-digested caller receipt преждевременно освобождает scope. Это owner-map gap, а не новая product choice | Сохраняет D-003/D-004/D-006 и T-004/T-006/T-015: live writes не теряются, новый scope не используется до нового binding, waiter видит только accepted common base; требует M3b runner bridge и M5 integration owner |

### T-020 detector verdict matrix

Каждый channel возвращает ровно `clean`, `breach` или `indeterminate`. `clean` означает совпадение canonical evidence с admitted authority baseline с учётом одного exact transition intent. `breach` означает положительно атрибутированную legacy/unregistered mutation или activity. `indeterminate` означает, что полноту, identity либо attribution доказать нельзя. Overall verdict — `breach`, если хотя бы один channel `breach`; иначе `indeterminate`, если хотя бы один channel `indeterminate`; иначе `clean`. `breach` и `indeterminate` создают/переиспользуют один durable incident/fence. Только overall `clean` receipt допускает ordinary transition; incident-safe transition использует свой stage-specific receipt и не трактует ожидаемый live-legacy evidence как разрешение ordinary authority.

| Channel | Canonical evidence | Expected authority/baseline | `clean` predicate | `breach` predicate | `indeterminate` / fail-closed | Receipt fields in addition to common binding |
|---|---|---|---|---|---|---|
| C1 Git topology | identity-checked Git common-dir + complete normalized worktree enumeration | admitted project lanes, exact protected external actors и current transition-intent delta | observed identities равны baseline + authorized delta; managed create/close не считается breach | новый/изменённый worktree/common-dir identity атрибутирован archived legacy или unregistered actor вне baseline | enumeration/parse incomplete, no-follow identity drift либо повторный barrier не воспроизводит inventory -> incident | canonicalizer version, inventory-scope digest, expected/observed identity digests, intent-delta digest, verdict/reason |
| C2 Legacy registries | complete owner-private inventory каждой workspace registry generation, lease, outbox и in-flight recovery state | admission inventory + compatible managed generations; legacy entries должны быть vacant/retired, кроме exact incident recovery target | все entries schema-valid и соответствуют expected managed state либо documented vacant/retired legacy state | legacy lease/outbox/in-flight state или generation transition существует вне authorized recovery stage | registry unreadable, schema/digest/ownership/reparse failure либо нельзя доказать полноту inventory -> incident | registry-set digest, per-registry generation/state digest, expected recovery-target ID, verdict/reason |
| C3 Process/containment | creation-bound process tree, guardian identity и Job/cgroup membership evidence | exact managed process identities, связанные с admitted lane/attempt; на clear legacy tree отсутствует | process set и containment равны registry authority; expected live legacy tree допустим только для incident drain stage | creation-bound legacy/unregistered process tree либо containment escape положительно найден | PID creation identity, full-tree enumeration или membership proof ambiguous/unavailable -> incident | provider/canonicalizer version, expected/observed process-tree digests, containment digest, verdict/reason |
| C4 Workspace/index/status | stable `status --porcelain=v2 -z`-equivalent inventory, index identity/digest и privacy-safe worktree delta digest на каждом enumerated worktree | protected-user-work baseline + active managed lane allowed-set/scope + exact transition intent | dirties byte/index-identical protected baseline либо атрибутированы active managed lane внутри granted scope; legitimate managed dirty state — negative control | новый delta атрибутирован legacy/unregistered actor или выходит за managed authority | status/index read failure, changing two-barrier inventory или ambiguous actor/scope attribution -> incident | worktree-set digest, protected-baseline digest, allowed-set/scope digest, expected/observed delta digests, verdict/reason |
| C5 Refs | stable inventory protected/integration/task ref tips, lock state и available reflog/ancestry evidence | registry-bound base/intents + exact root-owned CAS or registered task-ref delta | ref movement точно соответствует one authorized transition intent; legitimate managed CAS — negative control | protected/integration ref или новый legacy ref положительно изменён вне bound intent | incomplete/ref-lock-racy enumeration, missing required ancestry/reflog evidence или unbound concurrent movement -> incident | ref-set/baseline/observed digests, intent/CAS expected-old/new digests, ancestry verdict, verdict/reason |

Common receipt fields: project identity, session epoch, transition type/ID, registry generation, attempt ID, channel ID, canonicalizer/schema version, completeness, baseline class+digest, expected-authority digest, transition-intent digest, observed-evidence digest, verdict и stable reason code. Receipt другого project/session/generation/attempt, replayed receipt, unknown channel/verdict/reason или changed evidence не авторизует transition.

#### Incident preservation baseline

Обычный authority baseline и incident preservation baseline — разные типы. После materialized incident и до safe-stop project owner под incident generation сохраняет immutable C1/C4/C5 snapshot: exact topology/worktree identities, status/index delta digests и ref tips, плюс original admitted-baseline digest. Запись имеет `baseline_class=incident-preservation`, `authority_usable=false`, incident ID/generation и external-protected scope classification. Она не делает legacy write допустимым задним числом, не принимает handoff и никогда не выдаёт ordinary `clean` receipt.

Для `drain-complete`, floor verification и clear unchanged C1/C4/C5 evidence MAY вернуть recovery-only `clean` относительно exact preservation baseline; C2 всё равно должен доказать registry vacancy, C3 — authenticated full-tree-zero. Любой subsequent topology/content/index/ref drift возвращает `breach` либо `indeterminate` и создаёт новую generation-bound preservation cycle, не переписывая старую snapshot. Clear CAS может перенести exact unchanged baseline только в external `protected-user-work` records/scopes D-007; это не task ownership, integration или ref authority. После clear независимые scopes допускаются, конфликтующие с preserved work ждут verified adoption.

#### Incident terminal eligibility matrix

`legacy-terminal-finalize` не является generic registry editor. Перед каждым row owner повторно валидирует exact lease kind/state, recovery capability, process creation identity, terminal/archive inputs, quarantine, outbox/handoff, source/checkpoint/grant и current registry generation. Unknown/extra state всегда выбирает E5.

| Row | Exact eligible shape | Required incident semantic disposition and gates | Finalization effect |
|---|---|---|---|
| E1 unactivated | `normal-legacy:reserved`, `normal-contained:normal-preflight-reserved|normal-snapshot-bound` или `recovery-target:reserved`; no process/provider/terminal/handoff/outbox/quarantine и byte-equal preflight/source evidence | `incident-unactivated-released`; existing unactivated-reservation lifecycle; для source/recovery target checkpoint/source invalidation и grant/authorization retirement MUST complete first | archive intent/source digests, clear only lease, retain incident/project scopes |
| E2 ordinary legacy/fallback terminal | `normal-legacy|normal-fallback` with `recovery_capable=false`, state `ordinary-process-bound-unactivated|legacy-running`, quarantine null, outbox/handoff absent | exact creation-bound stopped terminal receipt; `incident-preserved-legacy-terminal`; terminal success is evidence only and never handoff/root-completion authority; use legacy terminal-release state rules | append one unsuccessful-for-project incident terminal event, archive process/terminal/Git evidence, clear lease only |
| E3 contained/recovery terminal | `normal-contained|recovery-target`, state `stopped-terminal|handoff-committed`, quarantine null | authenticated terminal + full-tree-zero; `incident-preserved-no-handoff` permanently rejects finalize-success/retry/escalation/root-completion; applicable checkpoint/source invalidation completed; recovery grant/authorization retired; exact guardian-close; handoff/outbox material archived but not accepted | append contained incident terminal archive, clear lease+outbox exactly as current terminal owner after all state-specific gates, retain Git state/project fence |
| E4 exact containment-loss reconciliation | `normal-contained:stopped-terminal`, quarantine exactly `containment-loss-after-boundary`, durable zero already recorded, stopped/reused original guardian+worker identities, no mismatched handoff/outbox/semantic state | only current exact `_reconcile-containment-loss` eligibility/reason sets and v1–v4 abandonment path; applicable checkpoint invalidation, reconciliation-specific guardian close and archive complete | clear quarantine through existing one-shot reconciliation, then finalize through E3; no broader quarantine exception |
| E5 blocked/non-automatic | any live/unknown process; intermediate launch/active/terminal-pending state not yet reconciled by its owner lifecycle; `fallback-launch-ambiguous`, `git-common-dir-drift`, `handoff-trace-unreadable|mismatch`, pre-zero/inexact containment loss; unknown schema/kind/state/reason; missing/mismatched checkpoint/source/grant/guardian/archive evidence | no incident disposition, no force-unlock, no lease/outbox mutation. Recoverable intermediate state MAY only replay its exact existing owner lifecycle into E1–E4; ambiguous quarantine remains automatically ineligible | incident/fence and all evidence remain; clear/resume/publication stay blocked and operator docs expose manual recovery/rollback limits |

Every E1–E4 disposition is lease/run/source/project/incident-generation-bound and one-shot. A fault before its final visible CAS retains prior lease/outbox/quarantine; a fault after visibility reload-validates the exact archive, invalidation/retirement/guardian receipts and resulting vacancy. Replay cannot accept output, grant root authority, create a new writer or release project scopes.

#### Ordinary transition matrix

O1–O8 — exhaustive set coordinator-owned ordinary authority, Git and publication transitions. Перед каждым concrete transition ID owner под project lock выполняет fresh C1–C5 authority-baseline scan, сохраняет one-use project/session/generation/attempt/intent-bound receipt и повторно проверяет отсутствие active incident. `breach|indeterminate` сначала materializes incident и отклоняет transition; уже active incident отклоняет его без ordinary mutation. Receipt используется ровно один раз и invalidates на fault/cancel/retry/restart/evidence drift. Transition с ожидаемым C1/C4/C5 delta связывает exact old/new intent и после action делает rebarrier/новую baseline generation; mismatch materializes incident. Deliberate archived-legacy race после scan и до action не считается атомарно исключённым по D-009 option 2a; обнаружение на следующем mandatory barrier блокирует дальнейшую integration/publication и сохраняет state.

| Row | Concrete ordinary transitions requiring fresh receipt |
|---|---|
| O1 Project/session/schema | existing-registry session attach/resume/new epoch; compatible epoch/covenant activate; reader/writer floor promote или lower; schema promotion/migration; project-session retire; downgrade/rollback admission. Initial absent-registry session belongs to B0 |
| O2 Lane/worktree/ref lifecycle | task/lane create, register, resume, activate, cancel, terminal-success, close; task branch/ref/worktree create/register/move/remove; lane ownership transfer |
| O3 Scope/scheduler/resource | milestone ready/activate/complete; soft intent create/update/expire; hard file/directory/contract scope reserve/grant/expand/release; protected-work adoption intent/finalize/rollback; queue/fairness ticket grant; capacity/runtime namespace/resource grant/release |
| O4 Writer/recovery authority | implementation lease reserve/activate; process dispatch/write gate; same-profile retry, escalation approval, recovery-target authorization/activation; ordinary semantic disposition, handoff/outbox materialize/accept, root-completion authority, ordinary terminal lease release |
| O5 Integration | integration intent/enqueue/dequeue; result apply/cherry-pick/merge; conflict/reject/stale/accept decision; validation acceptance; integration base/ref CAS; baseline promotion и scope ownership transfer/release |
| O6 Version/package/commit | prerelease ticket allocate/consume/supersede; version/docs/package metadata mutation; task/integration/release commit create/finalize; stable candidate finalize и success declaration |
| O7 External publication/verification | Git push; annotated tag create/push; GitHub Release create/update/publish; public exact-version audit; remote install/smoke start и success receipt |
| O8 Cleanup/retention | worktree/branch/ref cleanup/delete; lane/session/registry retirement; tombstone/source/checkpoint/prompt/archive/receipt/evidence GC или deletion; cleanup success |

Incident-safe actions из T-020 не входят в O1–O8 и авторизуются только stage-specific recovery receipt. В частности, safe-stop/evidence capture/E1–E4 не превращаются в ordinary lease/scope release, а clear не выдаёт task authority. Любой новый coordinator transition при реализации MUST быть классифицирован в O1–O8 либо явно добавлен в closed incident-safe set до merge; unknown transition fail-closed.

#### Stable transition-ID registry

Implementation MUST ship one machine-readable registry consumed by runtime dispatch, tests, docs and package validation. ID is immutable after publication; alias/wrapper either owns a distinct ID or is proven side-effect-free before delegating the same receipt. Every event and receipt stores the ID. Minimum project IDs:

| Class | Stable concrete IDs |
|---|---|
| Install/setup | `I0.coordinator-root.initialize`, `I0.coordinator-key.initialize`, `I0.bootstrap-capability.issue`, `I0.bootstrap-temp.gc`; automatic first-Build setup/maintenance authority selected by D-010 option 1a, never project/Git authority |
| Bootstrap anchor | `BA0.anchor.publish`, `BA0.receipt.stage`, `BA0.clean-intent`, `BA0.incident-intent`, `BA0.handoff.complete`; `O8.bootstrap-record.gc`; immutable anchor lock/manifest have no automatic deletion ID |
| B0 | `B0.project.initialize` — one composite registry+session gen-0 transition |
| O1 | `O1.session.attach`, `O1.session.resume`, `O1.epoch.activate`, `O1.covenant.activate`, `O1.floor.promote`, `O1.floor.lower`, `O1.schema.promote`, `O1.session.retire`, `O1.registry.retire-downgrade`, `O1.downgrade.admit`, `O1.rollback.admit` |
| O2 | `O2.lane.create|register|resume|activate|cancel|terminal|close|transfer`; `O2.worktree.create|register|move|remove`; `O2.task-ref.create|move|remove` |
| O3 | `O3.milestone.ready|activate|complete`; `O3.soft-intent.create|update|expire`; `O3.scope.reserve|grant|expand|release`; `O3.protected.adoption-intent|finalize|rollback`; `O3.queue-ticket.grant`; `O3.capacity.grant|release`; `O3.runtime-resource.grant|release` |
| O4 | all exact current `RecoveryRegistry`/runner mappings below plus `O4.lane-registry.initialize`, `O4.process.dispatch`, `O4.write-gate.open`, `O4.retry.approve`, `O4.escalation.approve`, `O4.recovery-target.authorize|activate`, `O4.prompt-snapshot.stage`, `O4.checkpoint.revalidate-persist` |
| O5 | `O5.integration.intent|enqueue|dequeue|apply|conflict|reject|stale|accept`; `O5.integration.validate`; `O5.integration-ref.cas`; `O5.baseline.promote`; `O5.ownership.transfer` |
| O6 | `O6.version-ticket.allocate|consume|supersede`; `O6.version-metadata.mutate`; `O6.package-metadata.mutate`; `O6.commit.task|integration|release.create`; `O6.commit.task|integration|release.finalize`; `O6.stable-candidate.finalize`; `O6.success.declare` |
| O7 | `O7.git.push`; `O7.tag.create|push`; `O7.github-release.create|update|publish`; `O7.public-version.audit`; `O7.remote-install.start|complete`; `O7.remote-smoke.start|complete` |
| O8 | `O8.worktree.cleanup`; `O8.branch.delete`; `O8.ref.delete`; `O8.lane.retire`; `O8.registry.retire`; `O8.tombstone.gc`; `O8.source.gc`; `O8.checkpoint.gc`; `O8.prompt-snapshot.release|gc`; `O8.bootstrap-record.gc`; `O8.archive.gc`; `O8.receipt.gc`; `O8.evidence.delete`; `O8.cleanup.success` |
| Incident-safe | `S1.incident.materialize`, `S1.incident.fence`, `S1.registry-drift.materialize`, `S1.preservation.capture`, `S1.drain.start`; `S2.process.safe-stop`, `S2.terminal.record`, `S2.tree-zero.prove`, `S2.quarantine.record`; `S3.owner.reconcile`, `S3.semantic-disposition.record`, `S3.checkpoint.invalidate`, `S3.authorization.retire`, `S3.guardian.close`, `S3.terminal.archive`, `S3.E1.finalize`, `S3.E2.finalize`, `S3.E3.finalize`, `S3.E4.finalize`; `S4.drain.complete`, `S4.floor.verify`, `S4.covenant-candidate.renew`, `S4.incident.clear` |
| Bootstrap incident | `BS1.incident.materialize`, `BS1.preservation.capture`, `BS1.drain.start`; `BS2.process.safe-stop`, `BS2.terminal.record`, `BS2.tree-zero.prove`, `BS2.quarantine.record`; `BS3.owner.reconcile`, `BS3.semantic-disposition.record`, `BS3.checkpoint.invalidate`, `BS3.authorization.retire`, `BS3.guardian.close`, `BS3.terminal.archive`, `BS3.E1.finalize`, `BS3.E2.finalize`, `BS3.E3.finalize`, `BS3.E4.finalize`; `BS4.drain.complete`, `BS4.clear-intent`, `BS4.project-registry.visible`, `BS4.complete` |
| Read-observation | `R.C1.git-topology.scan`, `R.C3.process.scan`, `R.C4.workspace-index-status.scan`, `R.C5.refs.scan`; these contexts may spawn bounded read-only observers but have no durable/Git/process-control sink and grant no mutation authority |
| Test-only | `TST.registry.rotate-epoch`; unavailable from production exports/runtime |

Current `RecoveryRegistry` mutation entry points MUST have the following registry mapping; the implementation MAY refactor names only if the transition IDs and behavior stay stable:

| Current entry point | Ordinary ID | Incident-safe ID/eligibility |
|---|---|---|
| `initialize` | `O4.lane-registry.initialize` | none; workspace-keyed lane registry, never project B0 |
| `retire_for_downgrade` | `O1.registry.retire-downgrade` | none |
| `mark_prompt_snapshot_released` | `O8.prompt-snapshot.release` | none |
| `reserve_normal` | `O4.lease.normal.reserve` | none |
| `release_unactivated_reservation` | `O4.lease.unactivated.release` | `S3.E1.finalize` |
| `bind_reserved_source_snapshot` | `O4.source-snapshot.bind` | none |
| `prepare_source_checkpoint` | `O4.checkpoint.prepare` | none |
| `finalize_prepared_checkpoint` | `O4.checkpoint.finalize` | none |
| `capture_checkpoint` | `O4.checkpoint.capture` | none; wrapper must consume one parent receipt |
| `revalidate_checkpoint` | `O4.checkpoint.revalidate-persist` | none; source persistence is an ordinary mutation |
| `grant_authorization` | `O4.authorization.grant` | none |
| `retire_authorization` | `O4.authorization.retire` | `S3.authorization.retire` |
| `consume_grant_and_reserve` | `O4.authorization.consume-reserve` | none |
| `claim_launch` | `O4.recovery-launch.claim` | none |
| `fail_recovery_target_before_boundary` | `O4.recovery-launch.fail-preboundary` | `S3.owner.reconcile` |
| `claim_contained_launch` | `O4.contained-launch.claim` | none |
| `bind_process_unactivated` | `O4.process.bind-unactivated` | none |
| `commit_activation` | `O4.process.activate` | none |
| `containment_failed_before_boundary` | `O4.containment.fail-preboundary` | `S3.owner.reconcile` |
| `quarantine_containment_loss` | `O4.quarantine.containment-loss` | `S2.quarantine.record` |
| `prove_fallback_teardown` | `O4.fallback.teardown-prove` | `S3.owner.reconcile` |
| `claim_normal_fallback` | `O4.fallback.claim` | none |
| `quarantine_fallback_launch` | `O4.quarantine.fallback-launch` | `S2.quarantine.record` |
| `bind_fallback_process_unactivated` | `O4.fallback-process.bind` | none |
| `bind_legacy_process_unactivated` | `O4.legacy-process.bind` | none |
| `release_legacy_terminal` | `O4.legacy-terminal.release` | `S3.E2.finalize` |
| `record_terminal_evidence` | `O4.terminal.record` | `S2.terminal.record` |
| `prove_contained_tree_empty` | `O4.tree-zero.prove` | `S2.tree-zero.prove` |
| `stage_post_commit_root_completion_action` | `O4.post-commit-action.stage` | none |
| `issue_post_commit_root_completion_authorization` | `O4.post-commit-authorization.issue` | none |
| `finalize_post_commit_root_completion` | `O4.post-commit-root-completion.finalize` | none |
| `complete_post_commit_root_completion` | `O4.post-commit-root-completion.complete` | none |
| `record_terminal_abandonment` | `O4.terminal-abandonment.record` | `S3.semantic-disposition.record` |
| `record_containment_loss_abandonment` | `O4.containment-abandonment.record` | `S3.owner.reconcile` |
| `complete_terminal_abandonment` | `O4.terminal-abandonment.complete` | `S3.owner.reconcile` |
| `reject_semantic_handoff` | `O4.semantic-handoff.reject` | `S3.semantic-disposition.record` |
| `invalidate_source_checkpoint` | `O4.source-checkpoint.invalidate` | `S3.checkpoint.invalidate` |
| `complete_source_checkpoint_invalidation` | `O4.source-checkpoint-invalidation.complete` | `S3.checkpoint.invalidate` |
| `commit_handoff` | `O4.handoff.commit` | none |
| `materialize_handoff` | `O4.handoff.materialize` | none |
| `acknowledge_containment_loss_close` | `O4.guardian.containment-loss-close` | `S3.guardian.close` |
| `acknowledge_guardian_close` | `O4.guardian.close` | `S3.guardian.close` |
| `release_contained_terminal` | `O4.contained-terminal.release` | `S3.E3.finalize|S3.E4.finalize` |
| `rotate_epoch_for_test` | `TST.registry.rotate-epoch` | test-only |

Bootstrap incident aliases are exact, not implied by the S column:

| RecoveryRegistry entry point(s) | Required BS ID |
|---|---|
| `release_unactivated_reservation` | `BS3.E1.finalize` |
| `retire_authorization` | `BS3.authorization.retire` |
| `fail_recovery_target_before_boundary`, `containment_failed_before_boundary`, `prove_fallback_teardown`, `record_containment_loss_abandonment`, `complete_terminal_abandonment` | `BS3.owner.reconcile` |
| `quarantine_containment_loss`, `quarantine_fallback_launch` | `BS2.quarantine.record` |
| `release_legacy_terminal` | `BS3.E2.finalize` |
| `record_terminal_evidence` | `BS2.terminal.record` |
| `prove_contained_tree_empty` | `BS2.tree-zero.prove` |
| `record_terminal_abandonment`, `reject_semantic_handoff` | `BS3.semantic-disposition.record` |
| `invalidate_source_checkpoint`, `complete_source_checkpoint_invalidation` | `BS3.checkpoint.invalidate` |
| `acknowledge_containment_loss_close`, `acknowledge_guardian_close` | `BS3.guardian.close` |
| `release_contained_terminal` | `BS3.E3.finalize|BS3.E4.finalize` |

A BS context binds project/common-dir identity, prospective epoch, BS generation/attempt/incident, target workspace registry identity+generation, lease/run/source/grant IDs and exact E row. Its ordered plan is `BS intent -> target registry/source mutation(s) -> target archive/vacancy evidence -> BS target-result CAS`. The workspace owner method validates the BS tag instead of normal session fields and writes the same BS backlink into its event/archive. A normal S receipt cannot authorize BS, a BS receipt cannot authorize normal S/O, and `commit_handoff`, `materialize_handoff`, success/root-completion/retry/escalation have no BS alias. Fault replay verifies both target generation and BS cursor before continuing.

The current nominal methods `state`, `state_for_activation`, `assert_reader_compatible`, `public_checkpoint_for_source`, `assert_checkpoint_allowed_paths`, `read_private_source`, `build_post_commit_root_completion_action_snapshot` and `post_commit_root_completion_replay_binding` MUST become sink-free reads. `_read_registry_locked` MUST NOT persist quarantine; it returns typed drift evidence, and only `S1.registry-drift.materialize` writes it. Read paths open only already-existing owner directories/lock files with no-create/no-follow identity checks, take a non-writing OS lock, use stable read-before/after identity+digest barriers without chmod/lock-byte/fsync, and validate common-dir identity from the persisted initialization binding plus `.git`/`commondir` filesystem reads without spawning Git. Missing read infrastructure returns absent/indeterminate and never creates it. Detector commands that require subprocess observation use `R.*` context and cannot reach mutation/process-control sinks. Completeness tests include mkdir/create, chmod, lock-byte write, write-fsync and subprocess spawn as sinks/observations and bind all eight names to strict `read-only/no-sink`.

Current runner mapping:

| Runner entry point | Transition contract |
|---|---|
| `stage_owner_prompt_snapshot` | one `O4.prompt-snapshot.stage` context; optional ordinal 1 creates the key if absent, next ordinal writes/reuses the blob; one receipt/ID/cursor |
| `acquire_owner_prompt_snapshot`, `stage_prompt_run` | side-effect-free-before-delegate aliases of `O4.prompt-snapshot.stage`; same parent context, no second receipt consumption |
| `garbage_collect_owner_prompt_snapshots` | `O8.prompt-snapshot.gc` |
| `read_owner_prompt_snapshot`, `collect_owner_prompt_snapshot_references` | sink-free reads: existing key/lock/blob only, no key/dir/lock creation, chmod, fsync, unlink or Git subprocess; absence fails without mutation |

Low-level `durable_write_private_*`, atomic replace/delete/unlink, registry/source commit, Git/process/GitHub/remote sinks are not entry points and MUST reject direct invocation without a guarded transaction context.

Completeness test builds a call graph for every production entry point in setup/project/recovery/runner/release owners and finds any direct or transitive durable/external sink: directory/file/lock-byte create, chmod, write-fsync, registry/source/private durable write or replace/delete, Git worktree/index/ref/commit mutation, process spawn/kill/containment close, Git push/tag, GitHub mutation, remote install/smoke result, filesystem cleanup. Each path MUST open exactly one registered transition context before the first sink; the sole exception is the bounded in-memory `I0.setup-bootstrap` context described below, which itself is a registered class and can reach only the fixed coordinator root/key initialization plan. Dynamic/unresolved calls, duplicate IDs, undocumented aliases and unclassified mutation fail. A bounded read-observer subprocess is separately allowed only under exact `R.*` ID, argv allowlist, no network/write descriptors and zero mutation/process-control descendants. Read-only entry points prove no sink or observer reachability. Test-only IDs require an explicit test-runtime guard. Package validation compares registry, T-020 docs and AC fixtures.

The guarded context binds transition ID/class, receipt ID+digest, project/bootstrap identity, epoch/generation/attempt, exact ordered sink-plan digest and current ordinal. Opening it validates but does not mutate. The first sink atomically consumes the one-use receipt and records/reloads transition intent; later sinks execute only inside that same context at the next declared ordinal with matching arguments/evidence. Absent context, wrong class/ID/project/generation, already-consumed receipt used to open another context, skipped/extra/reordered sink or plan drift rejects before side effect. Crash replay reloads the same intent/cursor and proves a visible exact sink result before advancing; it never opens a second context. Direct low-level sink calls are private and guarded at runtime, not only linted.

#### I0 coordinator root and BA0 bootstrap anchor

D-010 option 1a makes every explicit `$openbuild:build` entry point run the same idempotent owner setup command before repository discovery/bootstrap; on an already valid I0 this is a sink-free verification fast path. Because the plugin manifest has no install lifecycle hook, no contract may claim that `codex plugin add/update` itself executed setup, and README install commands remain unchanged. On the first invocation the command opens a bounded in-memory `I0.setup-bootstrap` context authenticated by the current OS account, installed package identity/version and that explicit Build invocation. This is the sole pre-durable exception: its compile-time/runtime allowlist contains only the fixed child path under an already existing identity-checked owner-private Codex base and the ordered root/lock/key initialization sinks; it cannot inspect or mutate a project, Git, prompt, process or publication state. Success durably records the matching I0 setup receipt and continues the originally requested mode. Missing state is initialized automatically; ambiguous, insecure or tampered existing state returns `setup-required` with remediation guidance and fails closed without silent repair.

I0 root and its immutable coordinator lock use atomic create/no-replace plus no-follow/reparse and current-user-only DACL or `0700` checks. The HMAC key is generated once and published with atomic no-replace; a concurrent loser opens and byte/format/ACL-validates the winner, never overwrites it. Plugin update does not run a hook; the first subsequent Build invocation validates and never rotates, replaces or deletes a valid key. Rotation is outside this release and would require an explicit migration preserving every old anchor lookup. Concurrent first invocations/update-validation/bootstrap fixtures prove one root/lock/key identity and stable anchor names. Missing I0 is initialized before any project read; insecure/tampered I0 returns `setup-required` with zero project/workspace mutation.

Before the first project sink, `I0.bootstrap-capability.issue` takes the existing immutable coordinator lock and durably creates a one-use capability bound to project common-dir identity, HMAC anchor slot, prospective epoch/attempt, expected anchor/project-registry/BS absence, package/schema and an exact sink-plan digest. This I0 write is not project/Git authority. It authorizes only BA0 temp creation/fsync, atomic no-replace directory publish, winner validation and same-attempt loser-temp cleanup; the first BA0 sink atomically consumes it and persists the attempt cursor under I0. Stale, cross-project, reused or mismatched capabilities reject before a sink. Abandoned temps are later removed only by `I0.bootstrap-temp.gc` under the immutable coordinator lock and retention evidence, never by ordinary `O8` before a project registry exists.

Per-project anchor name is HMAC(permanent key, project common-dir identity + OS account), so public status exposes no path. `BA0.anchor.publish` prepares a fully durable owner-private directory containing an immutable manifest and immutable lock file, then atomically publishes the directory to its final slot with no-replace semantics. POSIX uses directory-fd/no-follow creation and atomic no-replace publication; Windows uses equivalent current-user DACL, reparse-safe creation and atomic publish-no-replace. A loser validates the winner while still holding its I0 capability and follows that anchor. No partially written anchor becomes authoritative.

The published lock file identity never changes, rotates or unlinks automatically. Bootstrap locks that object, revalidates its path/object identity after acquisition, and persists receipts, clean/incident intent and handoff in separate generationed atomic state records; replacing a state record cannot replace the lock object. A crash before directory publication leaves only a capability-bound temp and chooses no authoritative epoch; a crash after publication reloads the same manifest epoch/attempt and mutable cursor. Ambiguous publication reopens the final directory and accepts only exact manifest/lock identity and digest. `O8.bootstrap-record.gc` may compact completed mutable receipts only after registry/BS backlinks and retention, while the base directory, manifest and lock remain as the permanent per-project serialization identity. Any future explicit project-forget/delete operation is out of scope and may not reuse this `O8` ID.

#### B0 absent-registry bootstrap

Under the visible BA0 anchor lock, bootstrap scan reuses its project identity, prospective epoch and attempt. Evidence receipt binds `binding_class=bootstrap`, anchor identity+generation+digest, `expected_project_registry=absent`, `expected_bs=absent|<generation>`, selected result transition ID and all C1–C5 digests; C2 treats project-registry absence as expected but enumerates every workspace registry. Normal receipt requires session epoch+registry generation. Bootstrap receipt forbids session fields; BS-stage receipt additionally requires existing BS generation+incident. Receipt creation grants no project/Git authority.

Clean path creates no BS. When overall verdict is `clean` and registry/BS are absent, `BA0.clean-intent` then one `B0.project.initialize` composite plan creates one registry object containing project+session at anchor epoch, project generation `0`, covenant/baseline and anchor/receipt backlinks; there is no second session transition. Fault before registry visibility reuses anchor intent; fault after visibility reload-validates exact epoch/gen-0/backlinks then records `BA0.handoff.complete`. Competing initializers serialize on the anchor and later use `O1` attach.

BS is created only for `breach|indeterminate`. `BA0.incident-intent` then `BS1.incident.materialize` requires expected registry+BS absence and CAS-creates BS generation `0` directly in `incident-active` with anchor backlink; no `scanning` state. BS stores the anchor epoch/attempt, incident, evidence, target registries, E results and clear candidate. Competing breach/clean initializers attach to active BS and cannot substitute epoch or run B0. Further BS receipts bind anchor + BS generation.

BS1 captures preservation/starts drain; BS2 records safe-stop/terminal/tree-zero using exact aliases; BS3 applies E1–E5 to each target registry with ordered cross-registry plans; BS4 drain-complete requires all targets vacant plus unchanged preservation. `BS4.clear-intent` stores exact gen-0 project candidate bytes+digest/backlink while project registry absence is revalidated. `BS4.project-registry.visible` atomically creates that registry with prospective epoch, generation `0`, incident history, external protected-work records and cleared fence. Pre-visibility fault leaves clear-intent; post-visibility fault reload-validates backlink/digest then `BS4.complete` advances BS. Mismatch/different registry remains fenced. Only visible exact gen-0 registry clears the bootstrap incident. `O1` attach follows; completed BS retention/GC is `O8`.

Fixtures inject concurrent I0 setup/update versus bootstrap; root/lock/key create and loser verification; capability issue/consume/replay; BA0 temp/publish ambiguity, winner/loser and before/after directory visibility; one process holding the immutable anchor lock while another attempts state replacement/acquisition; receipt/intent/handoff faults; clean registry visibility; BS incident visibility; every BS/E/clear boundary. Two or more clean, breach or mixed initializers converge to one permanent anchor lock, one epoch and one incident or gen-0 registry, with no clean BS. No update rotates the key or changes the anchor slot. Stale/replayed/cross-project/capability/anchor/BS-generation receipts reject. B0/BS do not claim atomic exclusion against the D-009 archived-legacy race.

### Pending proposals

- None. D-010 option 1a fully applied; no mandatory setup command or install-hook claim remains.

## 4. User scenarios

### Primary scenario: непересекающиеся ТЗ

1. Пользователь запускает ТЗ A и ТЗ B для одного Git-проекта в разных окнах.
2. Project coordinator создаёт/возобновляет две task lanes от одной допустимой committed integration base.
3. A получает hard scopes для backend-файлов, B — для независимого billing/UI scope.
4. Lane-local writers работают одновременно, каждый в своём worktree и containment.
5. Их milestones независимо проверяются и поступают в единую integration queue.
6. Integrator последовательно принимает commits, выполняет post-integration validation и публикует новый baseline.

### Overlap: один endpoint

1. A владеет `file:server/users/update.*` и `contract:api.users.update`.
2. B может работать над независимой разметкой формы, но его milestone API binding получает `waiting-for-scope`.
3. A terminalizes, проходит handoff, создаёт coherent commit; commit ещё не освобождает scope.
4. Integration queue принимает A и атомарно обновляет common base.
5. B обновляет lane, проверяет spec/dependencies, получает contract/file lease и продолжает.

### Dynamic overlap

1. Worker обнаруживает, что milestone дополнительно требует `schema/users.*`.
2. До записи он запрашивает расширение.
3. Свободный scope атомарно добавляется к allowed set; занятый scope останавливает milestone в безопасной точке.
4. Любая запись до grant делает handoff неприемлемым.

### Crash и recovery

1. Writer lane A зависает или теряет containment.
2. Только A и её hard scopes переходят в quarantine.
3. Lanes B–N продолжают работу на непересекающихся scopes.
4. A scopes не освобождаются по timeout/heartbeat; требуется текущая terminal/full-tree-zero/guardian evidence.
5. После safe close coordinator либо интегрирует подтверждённый result, либо сохраняет ветку и ставит milestone в blocked без принятия ambiguous diff.

### Pre-session protected user work

1. Исходный checkout имеет пользовательские незакоммиченные изменения.
2. До открытия project session coordinator фиксирует их path/index/content provenance как внешние `protected-user-work` scopes без task-lane, recovery и integration ownership.
3. Новые lanes стартуют от committed integration base и не получают копию dirties; непересекающиеся scopes могут работать параллельно.
4. Milestone, пересекающийся с `protected-user-work`, остаётся `waiting-for-scope` и не активирует writer.
5. Dirty work получает task ownership только после отдельной явной и проверенной local commit/integration/adoption boundary, которая создаёт новый trusted baseline; автоматические snapshot, commit и импорт запрещены.

### Errors and edge cases

- Две заявки на один canonical scope одновременно -> ровно одна получает hard lease, вторая становится pending.
- File и ancestor directory lease пересекаются -> конфликт независимо от порядка заявки.
- Windows case alias или path normalization collision -> fail-closed до reservation.
- Symlink/reparse path, выходящий из lane -> lease и worktree activation отклоняются.
- Rename/delete leased path -> ownership следует source/destination pair и не позволяет скрыть overlap.
- Integration base изменилась до CAS -> integration attempt не двигает ref, lane refresh/revalidation повторяется.
- Merge conflict -> обе task branches сохраняются, scope не передаётся как успешно integrated.
- Upstream изменил read dependency, но write scope не пересёкся -> downstream lane маркируется stale и повторяет affected validation.
- Task отменена до writer activation -> reservations освобождаются replay-safe.
- Task отменена после write -> обычный terminal/recovery gate, без force-release.
- Orphaned lane/worktree -> cleanup только после process-tree zero, durable branch/result evidence и отсутствия project references.
- Десять lanes запускают тяжёлые tests -> capacity scheduler ставит лишние jobs в resource queue, не ломая task concurrency.
- Project registry повреждён или reader неизвестной версии -> fail-closed project coordination; lane branches/worktrees остаются сохранными.
- Legacy process обнаружен до upgrade admission -> parallel activation ждёт exclusive drain/update. Ручной archived-legacy start после compatible epoch — operator-policy breach: он может успеть изменить свой worktree/ref до detection, но затем managed integration/release блокируется, все branches/worktrees сохраняются и требуется повторный drain.

## 5. Requirements and acceptance criteria

### Requirements

- RQ-01: Project session MUST различать project identity, task lane identity, milestone identity, lane-local writer lease и project-level scope lease.
- RQ-02: Каждая write-capable task lane MUST иметь отдельные worktree и branch/ref; внутри одного worktree MUST оставаться не более одного writer.
- RQ-03: Нынешние containment, exact-runner, checkpoint, terminal, handoff, archive и recovery gates MUST сохраняться lane-local без ослабления.
- RQ-04: Project registry MUST поддерживать несколько lanes, но только один active owner для каждого canonical hard scope.
- RQ-05: Scope types MUST включать как минимум file, directory, contract и resource; overlap rules MUST быть детерминированными и платформенно корректными.
- RQ-06: Task MUST декомпозироваться на coherent DAG milestones с явными dependencies, expected hard scopes, soft intents, primary/red signal и integration output.
- RQ-07: Soft intent MUST влиять только на scheduling/diagnostics и MUST NOT блокировать другой готовый milestone.
- RQ-08: Dynamic hard scope MUST выдаваться атомарно до первой записи; denied expansion MUST остановить либо не запускать writer.
- RQ-09: Waiting task MUST сохраняться durable без idle writer process и MAY выполнять только независимые ready milestones.
- RQ-10: Project scope MUST NOT освобождаться по heartbeat, timeout или task-branch commit.
- RQ-11: Для result с task-owned changes scope release MUST требовать stopped writer tree, lane-local accepted terminal disposition, validation, coherent task commit, successful integration acceptance и publication нового common base. Единственное no-change исключение — T-015 `abandoned-no-change`: immutable diff archive, exact restore к уже accepted admitted-base commit, focused green и durable accepted no-op integration receipt/generation без нового Git commit; ambiguous либо changed state исключением не считается.
- RQ-12: Перед передачей scope следующая lane MUST refresh/rebase/merge на новый common base без переписывания user-owned history, повторно проверить spec revision, allowed set, read dependencies и focused signal.
- RQ-13: Integration MUST быть single-writer, CAS-bound и не должна перемещать branch/ref под dirty user checkout.
- RQ-14: Conflict или failed integration MUST сохранять обе task branches и MUST NOT публиковать partial integration как success.
- RQ-15: Project coordinator MUST обнаруживать dependency staleness даже при непересекающихся write paths.
- RQ-16: Deadlock policy MUST давать deterministic progress без отъёма lease у live writer.
- RQ-17: Crash/quarantine MUST блокировать только affected lane/scopes, кроме явно доказанного shared resource/global integrity incident.
- RQ-18: Runtime resources MUST быть namespaced per lane либо защищены exclusive resource lease.
- RQ-19: Pre-session dirty paths MUST регистрироваться как внешние `protected-user-work` scopes без task/recovery/integration ownership, оставаться byte/index-preserved и MUST NOT автоматически snapshot/commit/import в lanes. Независимые scopes MAY работать; конфликтующие MUST ждать отдельной verified adoption boundary и нового trusted baseline.
- RQ-20: Public status MUST показывать task/lane/milestone, `running|waiting-for-scope|waiting-for-integration|stale|blocked|complete`, non-sensitive scope reason и queue dependency без private paths/nonces.
- RQ-21: Automatic first-Build I0 setup/verification, permanent coordinator lock/key, bootstrap-capability issue/consume/temp-GC, BA0 atomic directory publish plus immutable-lock/separate-record intent/handoff/compaction, project/lane operations, clean B0 visibility, BS incident/target aliases/clear→gen-0 completion and post-drain clear MUST be replay-safe, bounded and crash-recoverable; anchor/project/BS use exact backlinks, tagged bindings and generations.
- RQ-22: Старые single-workspace runs/registries MUST читаться и завершаться по прежним правилам; upgrade MUST NOT превращать retained legacy lease в свободный project scope.
- RQ-23: Capacity MUST не иметь correctness-зависимости от фиксированного числа lanes; acceptance MUST покрыть минимум 2 conflict lanes и stress scenario до 10 lanes.
- RQ-24: Git staging, commits, ref update, push и release остаются root/integration-owned; workers не получают Git authority.
- RQ-25: Все coordinator clients одного Git common directory MUST attach к одному authoritative project registry/session epoch; несовместимый integration target, schema или identity MUST fail-closed до lane/scope creation.
- RQ-26: Каждая project transition MUST проверять writer floor, client version, registry generation и session epoch. Lower-version или unregistered client MUST NOT изменять project state, освобождать scope или авторизовать integration.
- RQ-27: Project registry, lock, intents и receipts MUST храниться owner-private вне workspace, открываться без следования reparse/symlink, сохранять stable object identity через read/write barrier и проходить bounded schema/digest/reload validation до authoritative transition.
- RQ-28: GitHub-facing documentation MUST синхронно покрывать README EN/RU, quick start, parallel-lane lifecycle/statuses, task decomposition, overlap/dirty-work behavior, migration/rollback, known limitations, troubleshooting, architecture/lifecycle diagrams, contributor contract и release notes; language variants MUST оставаться semantically equivalent.
- RQ-29: После полного green validation, commit gate и progressive review implementation MUST получить одну новую стабильную SemVer-версию; manifest, changelog, README install pins, packaged metadata, Git tag и GitHub Release title/notes MUST ссылаться на один exact version и immutable commit.
- RQ-30: Publication MUST завершаться remote-install verification из immutable release tag в чистом окружении/новом Codex thread; первый явный Build MUST автоматически создать/проверить I0 до repository discovery и затем пройти smoke минимум двух независимых parallel task lanes. Failed setup/install/smoke MUST блокировать объявление release завершённым и сохранить диагностируемые артефакты без секретов.
- RQ-31: `protected-user-work` adoption MUST быть explicit, scope-bound, identity/digest-checked, replay-safe и fail-closed. Protected ownership MUST сохраняться до accepted integration; crash/cancel MUST оставлять ровно `protected` либо `adopted`, никогда промежуточно свободный scope.
- RQ-32: Active writer MUST NOT ждать новый scope, удерживая cycle-forming leases. Cycle victim MUST safe-stop, сохранить diff и освободить scopes только через обычную coherent integration либо verified `abandoned-no-change` transaction, которая восстанавливает exact admitted base, связывается с его уже accepted commit и создаёт durable no-op integration receipt без нового Git commit; force-release live/ambiguous state запрещён.
- RQ-33: Release workflow MUST соблюдать порядок stable release commit -> full validation/clean candidate install -> pre-publication audit -> annotated tag/GitHub Release -> public resolution/remote-install smoke; post-publication failure MUST создавать диагностируемый blocked release receipt, а не retarget immutable tag.
- RQ-34: Каждый non-empty implementation/docs commit MUST иметь уникальную возрастающую prerelease-версию выбранной target minor-линии и синхронные manifest/changelog/README references; только final release commit MAY использовать stable target version.
- RQ-35: Prerelease allocation MUST быть project-wide, durable, monotonic, CAS-bound и происходить только при root-owned integration finalization. Ticket MUST NOT переиспользоваться; integration reorder/failure MUST rebase lane на текущий base и выделить новый больший ticket до commit gate.
- RQ-36: Failed stable candidate до tag MUST оставаться immutable untagged/superseded и MUST NOT называться release; исправление MUST выбрать следующую strictly higher patch prerelease/stable line. После publication исправление также MUST использовать новую version/tag/Release без retarget.
- RQ-37: Every explicit `$openbuild:build` entry point MUST run idempotent I0 setup/verification before repository discovery and continue the original mode after success; `codex plugin add/update` MUST NOT be described as executing a nonexistent hook, and no mandatory manual setup command is added. Missing I0 is created automatically, while insecure/tampered existing state returns `setup-required` without project read/mutation or silent repair. Verified I0 root, immutable coordinator lock and permanent atomic-no-replace key MUST preexist project bootstrap. I0 MUST issue a durable one-use project-bound capability before any BA0 sink. BA0 MUST atomically publish one fully durable no-replace directory with immutable manifest/lock and separate replaceable state records; lock identity never rotates/unlinks automatically. `I0`/`BA0`/`O8` IDs and before/after visibility semantics cover setup, capability, temp, record compaction and replay. All eight named registry reads plus prompt read/reference collection MUST be no-create/chmod/lock-byte/fsync/Git-spawn/key-write/unlink; persistent mutation and R observers retain explicit IDs. Prompt key creation is only an optional ordinal of one `O4.prompt-snapshot.stage` context. BS aliases/cross-class rejection remain exact. Clean B0 consumes anchor to one registry+session gen-0 and no BS; breach transfers anchor to BS gen-0 and later exact clear-linked registry. C/E/O publication and conditional D-009 rules remain.

### Acceptance criteria

- [ ] AC-01: Две lanes одного Git common directory с непересекающимися hard scopes одновременно достигают write-capable running state в разных worktree; существующий тест «один reservation в одном workspace» остаётся green для каждой lane.
- [ ] AC-02: Две конкурентные заявки на один file scope дают ровно одного owner и одного `waiting-for-scope` без write/activation второго milestone.
- [ ] AC-03: Directory/file ancestor overlap и case/path aliases классифицируются одинаково при любом порядке заявок и fail-closed при неоднозначности.
- [ ] AC-04: Разные файлы, связанные одним `contract:api.*`, сериализуются, когда одна задача меняет контракт; read-only consumer получает stale marker после интеграции.
- [ ] AC-05: Task-branch commit без integration acceptance не освобождает project scope и не позволяет соседу стартовать на старом baseline.
- [ ] AC-06: После successful integration предыдущего owner следующая lane refreshes common base, повторно подтверждает dependency/spec/allowed-set binding и только затем получает scope.
- [ ] AC-07: Большое ТЗ может завершить и интегрировать ранний coherent hotspot milestone, освободив scope до завершения остальных milestones задачи.
- [ ] AC-08: Milestone commit, не проходящий focused green или оставляющий проект в недопустимом промежуточном состоянии, не принимается integration queue и не освобождает scope.
- [ ] AC-09: Soft intent виден scheduler, но не блокирует готовую соседнюю задачу; hard grant остаётся единственным write authority.
- [ ] AC-10: Dynamic expansion до записи либо атомарно расширяет lease/allowed set, либо terminalizes milestone как waiting; post-write request отклоняет handoff.
- [ ] AC-11: Ожидающий milestone не удерживает живой Codex/worker process; task может выполнять только DAG-независимую работу.
- [ ] AC-12: Planned-set reservation/canonical ordering предотвращает обычный deadlock, а injected dynamic cycle сначала детерминированно снимает более новую невыполненную reservation; уже активные owners переходят в T-015 safe-stop flow без force-release.
- [ ] AC-13: Crash, timeout или containment loss одной lane не останавливает непересекающиеся lanes; её scope остаётся quarantined до full-tree-zero и lane-local terminal close.
- [ ] AC-14: Scope никогда не освобождается только по heartbeat expiry, PID disappearance или timeout.
- [ ] AC-15: Integration CAS race или merge conflict не двигает common ref, сохраняет обе ветки и переводит lane в stale/blocked с диагностикой.
- [ ] AC-16: Integrator не обновляет ref, checked out в dirty user workspace; dedicated integration lane/ref остаётся единственным mutable integration target.
- [ ] AC-17: Port/test DB/Docker collision test доказывает уникальный lane namespace либо serialization через resource lease.
- [ ] AC-18: Pre-session dirty checkout остаётся byte/index-unchanged, его canonical paths зарегистрированы как external `protected-user-work` без task/recovery owner; непересекающаяся lane запускается, пересекающаяся остаётся `waiting-for-scope`, а автоматические snapshot/commit/import отклоняются до verified adoption boundary.
- [ ] AC-19: Path escape, symlink/reparse ancestor, Git common-directory replacement и identity drift fail-closed без чужого scope release.
- [ ] AC-20: Restart/replay после fault в I0 root/lock/key/capability, BA0 temp/directory publish/record/intent/handoff, reservation/activation/terminal/integration, clean B0 visibility, BS alias writes/CAS/clear/gen-0 completion и record compaction даёт one immutable anchor-lock identity и one authoritative outcome без double-owner, orphan clean BS, second epoch или lost fence.
- [ ] AC-21: Exact legacy registry fixtures до 2.3.6 завершаются по прежней матрице; новая project registry имеет явный reader floor и безопасную migration/retirement policy.
- [ ] AC-22: Stress fixture с десятью lanes, смешанными scopes и bounded test capacity завершается без lost update, double-owner, starvation и global stop; порядок интеграции воспроизводим.
- [ ] AC-23: README EN/RU, SKILL/reference contracts, manifest/changelog и diagrams описывают одинаковую модель «parallel tasks, one writer per lane, one integrator».
- [ ] AC-24: Полный unittest/package gate, включая T-021 positive registered-transition и negative fixed-model controls, и fresh high-risk progressive review проходят без actionable findings; actual release/push выполняются только при отдельной authority.
- [ ] AC-25: Для primary, overlap, integration-wait, stale dependency, crash/quarantine и merge-conflict fixtures публичный status/event trace однозначно показывает `running|waiting-for-scope|waiting-for-integration|stale|blocked|complete`, privacy-safe reason, queue dependency/position и safe next automatic action без private paths, nonces или process identities.
- [ ] AC-26: В adversarial arrival fixture старейший eligible conflicting scope waiter получает ownership до любого более нового conflicting waiter; старейший ready capacity waiter запускается после завершения jobs, уже занимавших capacity при его постановке, и ни один более новый job его не обгоняет. Dependency-unblocking integration имеет отдельную приоритетную очередь, не claim'ит этот scope и не сбрасывает возраст ожидающих заявок.
- [ ] AC-27: Два одновременных coordinator opens одного Git common directory сходятся на одном session epoch/generation; несовместимый target/schema request не создаёт второй registry и ни при одном injected fault не возникает double-owner.
- [ ] AC-28: Writer-floor promotion и mixed-version fixtures отклоняют lower-version project transition без mutation; active discoverable legacy lane остаётся external/protected, не освобождает и не получает managed scope, а conflicting project admission ждёт её доказанной vacancy.
- [ ] AC-29: POSIX mode/owner, Windows DACL, lock/registry symlink-reparse substitution, file replacement между check/open/EOF, malformed-but-redigested schema и failures до/после file/parent durability barrier отклоняются либо replay-complete ровно один authoritative transition без privacy leak.
- [ ] AC-30: Documentation contract test/link audit подтверждает semantic parity README EN/RU: стандартные install commands не приписывают Codex несуществующий hook, первый explicit Build автоматически выполняет setup/verification и продолжает requested mode, отдельный mandatory setup step отсутствует, insecure/tampered I0 даёт `setup-required`. Также описаны permanent key/anchor lock, BA0 record recovery/compaction, clean-B0-vs-breach-BS, BS aliases, transition/read guards, protected work, separate commit/publication fences, conditional non-atomic limitation, troubleshooting, diagrams, contributor guidance и version-matched release notes.
- [ ] AC-31: Двухфазный release fixture отклоняет tag/Release до AC-24/30, clean candidate install и pre-publication exact-version audit; после publication manifest, changelog, README pins, packaged metadata, annotated tag и GitHub Release title/notes указывают один stable version и immutable validated commit.
- [ ] AC-32: Чистая remote install из опубликованного immutable tag устанавливает ожидаемую версию; в новом thread первый явный Build без отдельного setup command автоматически создаёт I0 до repository discovery, затем проходит smoke «две независимые lanes параллельны, пересекающийся scope ждёт». Evidence URL/commit/tag, setup receipt и privacy-safe smoke log сохранены в release receipt.
- [ ] AC-33: Adoption fault matrix для каждого boundary до/после `adoption-intent`, commit/plan verification, integration acceptance и project-generation write после restart даёт ровно один исход: прежний protected scope с byte/index provenance либо adopted integrated scope; conflicting lane не активируется между ними, wrong identity/digest/user scope отклоняется.
- [ ] AC-34: Два active writers в injected A-holds-X/waits-Y и B-holds-Y/waits-X cycle не force-release'ятся: newer wait-edge victim safe-stops, diff остаётся recoverable, затем coherent-prefix либо `abandoned-no-change` transaction проходит full-tree-zero/archive/restore/focused-green/admitted-base-commit-binding/no-new-commit/no-op-receipt gates, освобождает scopes один раз и оставшаяся lane получает progress.
- [ ] AC-35: Commit-gate fixture от `2.3.6` принимает последовательность `2.4.0-alpha.1 ... 2.4.0-alpha.N -> 2.4.0` с синхронными manifest/changelog/README в каждом non-empty commit и отклоняет duplicate, downgrade, ранний stable target, commit после stable на той же линии и mismatched documentation pins.
- [ ] AC-36: Две lanes, готовые к integration одновременно, получают разные monotonic prerelease tickets только в фактическом integration order; injected reorder/failure после allocation не переиспользует ticket, stale commit не интегрируется как downgrade, version surfaces изменяет только root finalizer под одним contract lease.
- [ ] AC-37: Failure на каждом boundary после stable candidate commit, но до tag/Release, оставляет candidate untagged/superseded; следующий corrective commit проходит gate на `next-patch-alpha.1`, новый stable next-patch проходит полный M8, а старые commit/tag никогда не переписываются и не retarget'ятся.
- [ ] AC-38: Completeness fixture covers the sole bounded `I0.setup-bootstrap` pre-durable exception, root/lock/key mkdir/create/chmod/fsync/no-replace, capability issue/consume and temp GC, BA0 directory publish plus separate state writes/compaction. Every Build mode proves setup runs before the first repository read; missing I0 is initialized then the requested mode continues, valid I0 is a sink-free fast path, and insecure/tampered I0 returns `setup-required` with zero project mutation. Concurrent first invocations/update-validation/bootstrap prove one permanent key and anchor slot; a lock-holder versus state-replacer/acquirer proves serialization stays on one immutable lock identity. All eight named registry reads and prompt read/reference collection prove no sinks; prompt stage uses one ID/receipt with optional key ordinal and cursor replay. Persistent/R/BS/O mappings/direct-sink guards retain prior tests. Concurrent clean path proves one anchor, no BS and one composite gen-0 registry/session; breach/mixed path proves same anchor transferred to one BS and one clear-linked registry. `O6`/`O7` and C/E/protected/non-atomic fixtures remain. Package validation accepts only exact registry-backed O-class transition tokens/references and still rejects bare, assigned or model-context `o<digit>` slugs in lowercase and uppercase negative controls.

### Invariants

- Один checkout/worktree — максимум один active writer.
- Один canonical hard scope — максимум один active owner во всём project session.
- Commit не равен integration и сам не передаёт ownership.
- Никакой lease не освобождается, пока creation-bound writer tree может быть жив.
- Worker никогда не получает Git, product-decision, version или publication authority.
- Project coordinator не принимает lane result, который lane-local root handoff не принял.
- Unrelated lane activity не становится `outside-set-drift` другой lane, потому что физические worktrees и Git indexes раздельны.
- Ambiguous state fail-closed сохраняет branches/worktrees и ownership evidence; force-unlock отсутствует.
- User dirty work не копируется, не коммитится и не перезаписывается без отдельной явной атрибуции.
- Integration validation является primary signal объединённого поведения; lane-local checks остаются обязательными, но недостаточными.

## 6. Technical boundaries

### Architecture and ownership

```text
Git common directory / project session
├── project registry
│   ├── task/lane/milestone DAG
│   ├── hard scopes + soft intents
│   ├── resource/capacity queues
│   └── integration intents/results
├── lane A worktree + branch
│   └── existing lane-local RecoveryRegistry -> one writer
├── lane B worktree + branch
│   └── existing lane-local RecoveryRegistry -> one writer
└── dedicated integration lane/ref
    └── one Git/integration writer
```

Предпочтительный owner split:

- новый owner-layer модуль project/session state рядом с `recovery_state.py`, но с отдельной schema и lock order;
- `agent_runner.py` получает только already-resolved lane workspace и lane-local lease; он не становится scheduler;
- Build root/project coordinator владеет decomposition, scope requests, waiting/resume и integration;
- нынешняя `RecoveryRegistry` остаётся owner lane process lifecycle;
- новый integration owner владеет commits/ref CAS и post-integration validation.

### Lock order and atomicity

Канонический порядок: project registry -> scope records в canonical key order -> lane registry только для activation/finalization -> integration lock. Нельзя удерживать project lock на протяжении agent run, tests или Git subprocess. Durable intent предшествует side effect, а visible result проходит rebarrier/reload validation до state transition.

Первый совместимый client создаёт authoritative project session epoch под common-dir owner lock. Остальные окна attach к тому же epoch и выполняют transitions по generation CAS; они не являются независимыми coordinator authorities. Несовпадение common-dir identity, integration target, writer floor или session epoch отклоняется до создания lane либо scope.

Cross-registry операция не изображает одну filesystem transaction. Она использует resumable intent:

1. project reservation/integration intent;
2. lane-local authoritative transition;
3. external Git/worktree side effect;
4. identity/CAS verification;
5. project completion/release.

Каждая fault boundary обязана быть replay-safe.

### Scope model

- File scope: canonical repository-relative path.
- Directory scope: path prefix с явной ancestor/descendant collision.
- Contract scope: стабильный semantic key, объявленный milestone (`api.users.update`, `schema.user`, `ui.user-form`).
- Resource scope: стабильный key (`port:devserver`, `db:test:<suite>`, `docker:<project>`, `migration:<store>`, `lockfile:<manager>`).
- Soft intent: тот же key плюс confidence/source milestone, но без write authority.
- Read dependency: base digest/commit + semantic keys; изменение интегрированного dependency делает consumer stale.

Symbol/range locks не входят в первую версию: formatter, imports и code generation делают их недостаточно надёжными.

### Milestone decomposition

Milestone обязан:

- давать independently meaningful outcome;
- иметь observable red/primary signal и focused green;
- объявлять expected hard scopes, soft intents и dependencies;
- завершаться coherent commit, который допустим в integration base;
- по возможности больше не возвращаться к освобождённому hotspot scope;
- не создавать временный публичный contract, который ломает соседей.

Для contract migrations используется expand/contract:

1. добавить backward-compatible contract;
2. интегрировать и освободить его;
3. параллельно мигрировать consumers;
4. отдельным milestone удалить legacy contract после dependency proof.

### Git and integration

- Каждая task lane использует отдельную branch/ref; один branch не checked out одновременно в нескольких worktrees.
- Integration queue принимает только immutable task commit/result tuple.
- Integrator применяет result к текущей integration base в dedicated workspace, проверяет conflicts/read-set staleness, выполняет focused + affected wider validation и CAS-updates integration ref.
- Task branches не rebase/force-push автоматически; возможный refresh создаёт forward merge/cherry-pick strategy по repository policy без переписывания published history.
- Push остаётся отдельной external/publication boundary существующего workflow.
- Cleanup worktree/branch не входит в success critical path и выполняется только после durable references/zero proof.

### Data and migration

Новая project registry хранится owner-private вне workspace, как текущая recovery state. Она не хранит raw prompt, file contents, secrets или публичные absolute paths. Public receipts используют opaque IDs и non-sensitive scope classifications.

Нужны:

- отдельная schema/version/reader floor;
- отдельный writer floor, client-version binding и promotion barrier до первого нового-shape write;
- migration, которая обнаруживает текущие workspace registries, но не импортирует active lease как свободный project state;
- классификация legacy/unregistered worktree как external protected actor без automatic integration/lease release;
- safe downgrade только при отсутствии active/pending/quarantined lanes, scopes и integration intents;
- bounded history/tombstones/GC;
- retention для completed lane metadata и веток, достаточный для replay/audit.

### Security and privacy

- Project/session registry доступен только текущей OS-учётке.
- Registry/lock directory создаётся с current-user-only DACL на Windows либо mode `0700` на POSIX; files используют owner-only permissions.
- Lock и каждый durable object открываются как regular non-reparse/no-follow object с identity checks до open, через EOF/write barrier и после close.
- Authoritative replace требует write-through/file fsync, atomic replace, parent metadata fsync, rebarrier, schema+digest reload; self-consistent unknown fields не принимаются.
- Worktree paths, prompt snapshots, private nonces, process IDs и secret-bearing resource identifiers не выводятся публично.
- Path normalization сохраняет no-follow/reparse/symlink guards.
- Другой OS account не может claim/release project scope.
- External actions, live DB, production migration и publish не становятся разрешёнными только из-за resource lease.

### Performance and concurrency

- Correctness не зависит от числа lanes; capacity limits управляют CPU/memory/heavy tests отдельно.
- Locks короткие; hashing/inventory/Git/tests выполняются вне project mutex по immutable intent.
- Scheduler обеспечивает fairness monotonic tickets: старейший eligible conflicting hard-scope waiter получает следующий grant; старейший ready capacity waiter ждёт только jobs, уже занимавшие capacity при enqueue. Dependency-unblocking integration обрабатывается отдельной приоритетной очередью, не конкурирует за released scope и не сбрасывает возраст waiters.
- Soft intents не резервируют capacity навсегда и имеют expiry при replanning/cancel.
- Stress acceptance: 10 lanes, но default concurrency может быть ниже по ресурсам хоста.

### Observability and errors

Public status содержит:

- opaque task/lane/milestone ID и user label;
- base/integration commit ID;
- state и blocked/waiting semantic reason;
- owned hard scope classifications и pending dependency без private absolute paths;
- position/owner в integration/resource queue;
- last authoritative transition и safe next automatic action.

События минимум: `coordinator-setup-started`, `coordinator-setup-ready|setup-required`, `lane-created`, `milestone-ready`, `scope-reserved`, `scope-waiting`, `scope-expanded`, `lane-activated`, `lane-terminal`, `integration-intent`, `integration-accepted|rejected|stale`, `scope-released`, `lane-quarantined`, `lane-closed`, `upgrade-draining`, `compatible-epoch-active`, `global-integrity-incident`, `incident-preserved`, `upgrade-drain-started`, `legacy-terminal-finalized`, `upgrade-drain-complete`, `covenant-candidate-renewed`, `incident-cleared`, `session-resumed`.

### Compatibility and rollout

1. Сначала добавить automatic first-Build I0 setup/verification и project registry simulation/tests без включения parallel mode; стандартные `codex plugin add/update` commands не меняются.
2. Первый explicit Build после install/update до repository discovery создаёт отсутствующий I0 либо sink-free проверяет существующий; insecure/tampered state блокирует mode как `setup-required`.
3. Перед первым opt-in выполнить one-time exclusive drain, обновить/отключить ordinary legacy plugin entry points, зафиксировать operator compatibility condition и установить compatible-only project epoch.
4. Затем включить opt-in capability для двух compatible lanes; ручной archived-legacy start считается unsupported policy breach и обрабатывается preservation/quarantine path T-020 без atomic-exclusion claim.
5. Прогнать Windows и Linux setup/containment/worktree/mixed-version forward tests.
6. После green regression включить default parallel scheduling для разных task IDs; same-checkout writer ban остаётся, совместимые окна не требуют общего stop.
7. Downgrade разрешён только после incident-free project registry vacancy/retirement и отдельного drain; active incident запрещает lowering floor, retirement и downgrade admission.
8. Rollback выключает создание новых lanes, но при active incident может только войти в T-020 preservation/drain path; новый reader обязан reconcile существующие состояния, а удаление registry, evidence или branches не является rollback.

### Versioning and release

- Authoritative source: `plugins/openbuild/.codex-plugin/plugin.json`.
- Current: `2.3.6`.
- Expected implementation impact: `minor`, candidate `2.4.0`; если authoritative base продвинется, выбирается следующая допустимая minor-линия без downgrade/reuse.
- Первый non-empty implementation commit выбирает target minor и использует первый prerelease, ожидаемо `2.4.0-alpha.1`; каждый следующий non-empty implementation/docs commit получает never-reused номер из T-018 allocator только при root-owned integration finalization и синхронизирует manifest, `CHANGELOG.md` и README EN/RU references.
- Завершающий release commit единожды меняет последний prerelease на stable target и синхронизирует README install pins, SKILL/references, contributor docs, diagrams и release notes.
- После AC-24/30/35 release commit проходит full validation, clean candidate install и pre-publication exact-version audit; затем создаются annotated stable tag и GitHub Release, а AC-31/32 проверяют public immutable artifacts и remote smoke.
- Failed stable candidate до publication помечается superseded без history rewrite; следующий corrective release использует strictly higher patch prerelease/stable line по T-019 и AC-37.
- Release receipt MUST содержать version, commit SHA, tag, GitHub Release URL, validation/review summary и privacy-safe remote smoke result.
- Это `refine` изменяет только ТЗ, не создаёт versioned commit/tag/GitHub Release и не выполняет remote install; publication относится к будущему исполнению спецификации.

## 7. Validation and review

- Primary signal: новый deterministic project-lanes concurrency fixture доказывает AC-01–AC-22, status/fairness fixtures — AC-25/26, security/compatibility — AC-27–29, documentation/release — AC-30–32/35–37, adoption/live-cycle fault matrices — AC-33/34; current recovery regressions сохраняются.
- Red signal: `python -m unittest scripts.test_project_lanes -v` -> до реализации module/test target отсутствует либо tests показывают отсутствие project coordinator, cross-worktree scope serialization и integration transfer.
- Current package red: `python scripts/validate_package.py` воспроизводит `BUILD-parallel-task-lanes.md: fixed model slug is not allowed`, потому что `fixed_model` ошибочно принимает O-class transition IDs за model slug; T-021 назначает owner-layer fix и negative controls. Отдельный dirty-worktree `plugin.json ... version did not increase` ожидаем в specification-only `refine` и закрывается только будущим prerelease/version-sync commit, а не изменением версии сейчас.
- Minimality decision: новый project owner-layer поверх неизменённой lane-local recovery; не использовать hosted service, database или production dependency; symbol/range locks и distributed hosts отложены.
- Focused green: Windows PowerShell — `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest scripts.test_project_lanes scripts.test_recovery_state scripts.test_agent_runner -v`; POSIX — `PYTHONDONTWRITEBYTECODE=1 python -m unittest scripts.test_project_lanes scripts.test_recovery_state scripts.test_agent_runner -v`.
- Targeted checks: project schema/lock order/fault injection; worktree lifecycle; scope collision/deadlock; integration CAS/stale; runtime resource namespaces; legacy reader fixtures.
- Wider checks:
  - Windows PowerShell: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest discover -s scripts -p "test_*.py" -v`
  - POSIX: `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s scripts -p "test_*.py" -v`
  - `python scripts/validate_package.py`
  - `git diff --check`
- Commit gate после version/docs sync:
  - `git diff --cached --check`
  - `python scripts/validate_package.py --commit-gate`
- Platform forward tests: Windows Job + multi-worktree, Linux cgroup v2 + multi-worktree; недоступную платформу честно оставить unverified до maintainer check.
- Manual/runtime check: два и более Codex-окна, разные task lanes, один hotspot contract и независимый scope; observable wait/resume/integration.
- Starting review tier: balanced high-risk exact read-only reviewer.
- Required final tier: balanced при clean high-confidence complete coverage; strong/Sol-high только по concrete configured trigger. Readiness closure для high risk требует complementary critics и strong closure.
- Review focus: double-owner/lost update, lock order/deadlock/starvation, crash replay, process-zero release, Git/index/ref safety, dirty-user preservation, scope aliasing, stale dependencies, privacy, downgrade, performance и documentation parity.

## 8. Milestones

### M1. Project-state contract и red concurrency fixtures

- Status: Completed in commit `52fac8a` (`2.4.0-alpha.1`)
- Scope: automatic first-Build I0 setup/verification before repository discovery, permanent no-replace root/lock/key, bootstrap capability, atomic BA0 directory with immutable lock and separate records, clean composite B0 without BS, breach-only generationed BS + E aliases, all eight non-creating/no-spawn registry reads, one-ID prompt staging, guarded mutation/read-observation contexts, stable ID/sink completeness, validator-safe registered transition-ID grammar, lane/milestone/scope state, lock order and fault tests.
- Excludes: worktree creation и production scheduling.
- Implementation mode: TDD-first
- Delegation: bounded-worker, high-risk route; expected files `scripts/test_project_lanes.py`, новый project-state owner module, package contract tests; exact allowed set определяется перед lease.
- Red signal: any Build mode reads the repository before setup verification, missing I0 does not auto-initialize/continue, or insecure I0 mutates project state; concurrent setup rotates key or BA0 publishers choose different lock identities/epochs; state replacement lets a second process bypass a held anchor lock; first BA0 sink lacks I0 capability; clean bootstrap leaves BS or splits registry/session; BS cannot invoke target owner lifecycle; any named nominal/prompt read creates lock/key/chmod/fsync/Git process; prompt key and snapshot use different transition IDs; receipt requires nonexistent session; current package validator rejects registered O-class transition IDs or an exemption lets an actual fixed model slug pass.
- Minimality decision: separate stdlib owner-state module; не менять recovery schema до доказанной необходимости.
- Focused green: project registry unit tests.
- Acceptance: AC-02, AC-03, AC-09, AC-12, AC-20, AC-21, AC-24, AC-27, AC-29 and AC-38 B0/registry/validator-completeness subset.
- Review: A-035 accepted with high confidence and no findings
- Version: `2.3.6 -> 2.4.0-alpha.1` prerelease; manifest, changelog and README pins synchronized.
- Commit: `52fac8a` (`Add project coordinator bootstrap contract`)

### M2. Lane/worktree lifecycle с сохранением current recovery

- Status: Complete in the validated `2.4.0-alpha.2` release candidate
- Scope: create/resume/recovery-ready/close lane, branch/ref/worktree identity, exact runner-to-project-lane routing and pre-prompt CAS attach, lane-local one-writer invariant, real concurrent runner/guardian/worker process trees, discovery и preservation external `protected-user-work`, exact no-handoff release for legacy `normal-contained` single `preexisting-dirty-overlap`, and no-rewrite M1 schema-1 migration on the first lane-session CAS.
- Excludes: automatic integration.
- Implementation mode: TDD-first
- Delegation: bounded-worker, high-risk route.
- Red signal: the preserved M2 baseline lacked an authoritative runner bridge, real simultaneous contained process trees, replay-safe post-containment audit, and an exact M1 schema-1 migration path.
- Focused green: project/lane `36` tests with three portability/platform skips; combined project-lane/runner `184` tests with seven skips; real two-process-tree fixture `1/1`; containment replay `4/4`; M1 migration/sink-free reads `2/2`.
- Acceptance: AC-01, AC-13, AC-14, AC-18, AC-19, AC-21, AC-33.
- Review: A-037/A-038/A-039/A-040 findings were remediated; A-041/A-042 remain the truthful zero-change replacement history. A fresh read-only Sol/max native collaboration review accepted the final bridge diff with high confidence `0.94` and no actionable findings.
- Version: `2.4.0-alpha.2` metadata and GitHub-facing documentation are synchronized and accepted for the scoped prerelease.
- Commit: the scoped `2.4.0-alpha.2` release commit containing this milestone record; its exact SHA is published by the tag and GitHub Release receipt.

### M3. Scope/resource lease manager и deadlock policy

- Status: In progress — core scope state machine is green; R-032 cross-owner runner safe-stop/rebind and registry-resident integration acceptance remain blocking after strong review
- Scope: canonical scopes, hard grants, soft intents, dynamic expansion, waiting, fairness, cycle handling, lane-local safe-stop/rebind consumption and authenticated integration-release handoff.
- Excludes: Git integration content merge.
- Implementation mode: TDD-first
- Delegation: bounded-worker, high-risk route.
- Red signal: double-claim/alias/dynamic-cycle fixtures; caller-forged release; live expansion that changes neither runner allowed-set nor process authority; safe-stop marker ignored by a real runner; cancelled-reservation release replay.
- Focused green: scope state-machine and multiprocessing race tests plus real runner safe-stop/rebind and integration-acceptance/replay fixtures.
- Acceptance: AC-02, AC-03, AC-04, AC-09, AC-10, AC-12, AC-14, AC-17.
- Review: balanced and strong passes returned `REVISE`; R-032 remediation and fresh changed-diff review are required.
- Version: root finalizer выделяет следующий never-reused prerelease target minor на каждый non-empty commit.
- Commit: Pending

### M4. Milestone DAG scheduler и non-idle wait/resume

- Status: Pending
- Scope: decomposition contract, ready/pending DAG, independent progress, durable waiting, hotspot-first integration.
- Excludes: automatic product decomposition without root verification.
- Implementation mode: TDD-first
- Delegation: bounded-worker, high-risk route.
- Red signal: task-wide lease блокирует независимый milestone либо waiting сохраняет живой worker.
- Focused green: scheduler dependency/stop/resume fixtures.
- Acceptance: AC-07, AC-08, AC-11.
- Review: Pending
- Version: root finalizer выделяет следующий never-reused prerelease target minor на каждый non-empty commit.
- Commit: Pending

### M5. Single-writer integration queue и ownership transfer

- Status: Pending
- Scope: immutable result tuple, integration intent, CAS ref update, conflict/stale classification, post-integration validation, release/transfer, project-wide prerelease allocation и no-op abandonment receipt.
- Excludes: automatic merge-conflict resolution и remote publication.
- Implementation mode: TDD-first
- Delegation: bounded-worker, high-risk route.
- Red signal: commit prematurely releases scope или CAS race loses an update.
- Focused green: integration fault/replay/conflict/stale tests.
- Acceptance: AC-04, AC-05, AC-06, AC-08, AC-15, AC-16, AC-20, AC-34, AC-36.
- Review: Pending
- Version: root finalizer выделяет следующий never-reused prerelease target minor на каждый non-empty commit.
- Commit: Pending

### M6. Capacity, runtime namespaces и end-to-end stress

- Status: Pending
- Scope: ports/DB/Docker/temp resources, bounded heavy jobs, fairness, observable cross-flow status traces, 10-lane stress.
- Excludes: hosted/distributed scheduler.
- Implementation mode: TDD-first
- Delegation: bounded-worker, high-risk route.
- Red signal: shared resource collision либо starvation fixture.
- Focused green: resource namespace/queue stress.
- Acceptance: AC-17, AC-22, AC-25, AC-26.
- Review: Pending
- Version: root finalizer выделяет следующий never-reused prerelease target minor на каждый non-empty commit.
- Commit: Pending

### M7. Legacy migration, docs, package gate и progressive review

- Status: Pending
- Scope: reader floor/retirement, automatic first-Build setup/status/continue and tampered-state `setup-required`, I0 permanent key/capability/temp maintenance, BA0 immutable-lock publish plus record intent/handoff/compaction, C/E/O, clean B0, breach BS/E aliases, exact create/chmod/fsync/subprocess/prompt inventory, all eight non-creating reads, single-transition prompt staging, guarded mutation/observation contexts, bootstrap clear/gen-0 replay, protected work, `O6`/`O7` fences, T-021 registry-aware validator distinction, conditional safety and release docs, full validation/review.
- Excludes: tag/GitHub Release/remote publication до green gates.
- Implementation mode: TDD-first для migration/contracts, Direct для docs после behavior green.
- Delegation: sequential-workers внутри одной implementation lane; один writer за раз.
- Red signal: validator/docs приписывают setup команде `codex plugin add`, требуют отдельный mandatory setup либо не доказывают automatic-before-discovery/continue flow, I0 capability/permanent key/immutable BA0 lock boundary, clean-B0/breach-BS split, BS aliases, any of eight hidden lock/key/read-observer paths, single-ID prompt-stage replay, terminalization or conditional breach; docs смешивают `O6`/`O7`/non-atomic limitation; package validator принимает зарегистрированный O-class transition за model slug либо пропускает bare/assignment/model-context `o<digit>` negative control.
- Focused green: full unittest + package validator + commit gate.
- Acceptance: AC-19, AC-20, AC-21, AC-23, AC-24, AC-28, AC-30, AC-35, AC-36, AC-38.
- Review: Pending
- Version: последний implementation/docs prerelease target minor; stable version ещё не используется.
- Commit: Pending

### M8. Stable GitHub release и remote verification

- Status: Pending
- Scope: final exact-version audit, release commit/push, annotated stable tag, GitHub Release, clean remote install и parallel-lanes smoke receipt.
- Excludes: prerelease/nightly channel, hosted coordinator и публикация при любом незакрытом validation/review finding.
- Implementation mode: Direct publication после завершения behavior/docs gates.
- Delegation: root-only Git/GitHub ownership; write-capable worker не запускается.
- Preconditions: M1–M7 green, AC-24/30/35 подтверждены, compatible epoch incident-free после fresh T-020 detection barrier, task diff/branch/status повторно проверены, secrets/generated noise отсутствуют.
- Failure signal: active `global-integrity-incident`, version mismatch, candidate validation/install failure, tag не указывает на validated commit, GitHub Release неполон либо remote install/smoke не проходит; incident блокирует все publication transitions, pre-tag stable failure запускает T-019 supersede flow.
- Focused green: stable release commit + full validation/clean candidate install + pre-publication audit; затем AC-31 public exact-version/tag audit и AC-32 remote install/smoke.
- Acceptance: AC-31, AC-32, AC-37, AC-38.
- Review: Pending
- Version: новая stable minor-линия, ожидаемо `2.4.0` либо следующая допустимая minor от authoritative base.
- Commit/tag/GitHub Release: Pending

## 9. Risks and blind spots

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence or decision | Next action |
|---|---|---|---|---|---|
| B-001 | outcome/scope/non-goals | covered | product decision | D-001–D-010 resolved; D-010 option 1a adds automatic first-Build setup before discovery | closure verify |
| B-002 | actors/authority | covered | repository fact | Root owns Git/product/version; workers bounded, `SKILL.md:120-130` | preserve |
| B-003 | primary/alternate/wait/cancel/retry flows | covered | product + technical decisions | D-003/D-006, T-004–T-007/T-015, RQ-11 no-change exception, AC-34, раздел 4 | fault tests |
| B-004 | recovery/quarantine | covered | repository fact + technical decision | C1–C5 detection, E1–E5 exact recovery eligibility and O1–O8 active-incident fence preserve RQ-03 and prevent ordinary unlock/release | regression |
| B-005 | accessibility/localization/responsive UX | not applicable | repository fact | Capability is CLI/workflow state; public text/status remains EN/RU and screen-reader-readable plain text | docs review |
| B-006 | ownership/module boundaries | covered | technical decision | bounded setup-only I0, I0-issued BA0 capability, immutable anchor lock/separate records, composite B0, lane `O4` and breach-only BS have disjoint authority; exact RecoveryRegistry aliases and read/observer/mutation contexts are separated, AC-27/38 | closure verify |
| B-007 | file/contract/resource semantics | covered | product + technical decision | D-003, T-003, RQ-04/05 | collision tests |
| B-008 | data/schema/migration/retention/deletion | covered | product + technical decision | I0 permanent key/capability/temp maintenance and BA0 immutable-lock/separate-record lifecycle join C/E/O+B0/BS generations, clear backlinks, archives and bounded record compaction | fault tests |
| B-009 | security/privacy/trust boundaries | covered | repository fact + technical decision | bounded I0 bootstrap exception, owner-private permanent HMAC, atomic no-replace BA0 directory, immutable lock identity, tagged S/BS/O/R contexts, all eight non-creating reads, single-ID prompt stage and direct sink guard, AC-29/38 | security closure |
| B-010 | compatibility/rollout/rollback | covered | product + technical decision | D-009 option 2a, exact old-shape eligibility, `O1` downgrade/rollback fence, preservation-only clear and documented non-atomic race; AC-30/38 | closure review |
| B-011 | performance/capacity/concurrency/idempotency | covered | product + technical decision | 2–10 lanes, capacity queue, replay/CAS, T-018 global allocator, AC-20/22/36 | stress |
| B-012 | integrations/timeouts/partial failure | covered | technical decision | I0 setup/key/capability and BA0 directory/record ambiguity, target-registry+BS ordered alias plans, clean B0 visibility and breach BS/E/clear cursor replay have exact recovery boundaries, AC-20/38 | fault injection |
| B-013 | observability/support | covered | product decision | RQ-20, event/status contract и AC-25; normative behavior уже задан D-003/D-006, новый user choice не нужен | docs/tests |
| B-014 | acceptance/testability | covered | repository fact | AC-24/38 include concurrent I0 setup/update/bootstrap, capability replay, permanent key and immutable-lock tests, all eight sink-free reads, one prompt transition, every BS alias, clean/breach convergence and T-021 positive/negative validator controls | execute later |
| B-015 | minimality/cost/dependencies | covered | technical decision | local stdlib/file-state extension plus registry-aware validator token classification; no service/dependency or global model-scan weakening | reviewer audit |
| B-016 | dirty user work | covered | product + technical decision | D-007 option 1a, T-014, RQ-19/31, AC-18/33, M2: external `protected-user-work` until replay-safe verified adoption | fault/byte-preservation tests |
| B-017 | Git history/integration/publication | covered | product + repository decision | D-004/D-008/D-009, separate `O6` commit and `O7` push/tag/Release/smoke IDs with per-action receipts, AC-31/32/34–38 | Git/release fault tests |
| B-018 | dependency staleness/semantic conflicts | covered | technical decision | contract scopes + read dependency digests; no automatic semantic merge | stale fixtures |
| B-019 | deadlock/starvation/fairness | covered | technical decision | T-007/T-010/T-015, monotonic tickets, no live hold-and-wait, AC-26/34 | adversarial stress/fault tests |
| B-020 | platform differences | covered | repository fact | Windows/Linux forward tests; unsupported platform remains unverified | maintainer validation |
| B-021 | GitHub documentation/publication | covered | product + repository decision | D-008/D-009, transition registry + `O7` publication fence, AC-30/38 and durable active-incident M8 gate | future release execution |
| B-022 | install/setup ownership | covered | repository fact + product decision | Manifest exposes no install hook; D-010 option 1a assigns setup to every explicit Build entry point before discovery, with idempotent fast path and fail-closed tamper handling | closure verify |
| B-023 | specification source-graph completeness | covered | repository fact | R-032 preserves the complete R-031 source graph and adds only the evidence-backed T-022 cross-owner runner/integration handshake; every direct normative owner remains mapped | fresh R-032 closure |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| Ослабление зрелой recovery state machine | high/critical | Оборачивать её lane-level coordinator, не превращать текущий lease в список | Handled by T-001 |
| Cross-registry split-brain после crash | medium/critical | Durable intents, fixed lock order, rebarrier, replay по каждой boundary | Open until tests |
| Два first-session initializer создают разные epoch либо разные bootstrap incidents | low/critical | Automatic first-Build setup establishes permanent I0 identity; one-use capability + atomic no-replace BA0 directory chooses one immutable lock/epoch before project state; B0/BS handoff and backlinks replay from it | Open until AC-38 |
| Bootstrap пытается создать coordination lock до первого authority receipt | low/critical | Sole bounded `I0.setup-bootstrap` exception initializes only fixed global state; existing I0 lock then issues durable project-bound capability before every BA0 sink | Open until AC-38 |
| Concurrent install/update rotates HMAC key and orphans existing anchors | low/critical | Key creation is atomic no-replace; loser verifies winner; valid key is permanent and update only validates it; rotation is out of scope | Open until AC-38 |
| Mutable anchor state replaces the object another process has locked | low/critical | Atomic directory publishes immutable manifest+lock; all mutable records are separate; post-lock identity revalidation and lock-holder/replacer fixture prove one serialization object | Open until AC-38 |
| Новый durable writer или external side effect обходит incident barrier | medium/critical | Machine-readable registry + call-graph completeness + runtime guarded sink context; unknown/wrong/reused receipt fail-closed | Open until AC-38 |
| Номинальный read скрыто создаёт lock/key, fsync'ит или запускает Git | medium/critical | All eight named reads use existing-only non-writing lock and stable no-fsync/no-spawn barriers; `read_private_source` included; prompt key is an ordinal of the sole stage transition; explicit R observers own subprocesses | Open until AC-38 |
| Prompt key initialization и snapshot staging расходятся по receipt/transition | low/high | Один `O4.prompt-snapshot.stage` context/receipt; optional key creation is ordered ordinal 1 inside its atomic replay plan | Open until AC-38 |
| BS recovery не может вызвать session-bound workspace lifecycle | medium/critical | Exact BS2/BS3 aliases + tagged target-registry sink plan/backlinks for every E1–E4 method | Open until AC-38 |
| Clean bootstrap оставляет orphan BS scanning state | low/high | Clean path creates no BS; one composite B0 registry+session CAS; BS gen-0 only on breach with expected absence | Open until AC-38 |
| Scope prediction ошибочен | high/high | Worktree isolation, dynamic pre-write expansion, final changed-path verification | Handled by design |
| Logical conflict при разных файлах | medium/high | contract scopes + stale read dependencies + post-integration validation | Open until tests |
| Long-lived hotspot создаёт starvation | medium/high | coherent early milestones, FIFO, dependency-unblocking integration, diagnostics | Open until stress |
| Частые commits дробят историю и ломают промежуточный build | medium/medium | Только independently valid coherent milestone проходит integration | Handled by D-005/AC-08 |
| Dirty user work потеряно или попало в чужую задачу | low/critical | `protected-user-work` external scopes, byte/index preservation, no automatic ownership/snapshot/import, verified adoption boundary | Handled by D-007; open until tests |
| Main/ref сдвинут под dirty checkout | medium/critical | dedicated integration ref/worktree, CAS, запрет update checked-out dirty target | Handled by T-008 |
| Worktree cleanup удаляет единственную копию diff | low/critical | branch/result durability + zero proof + reference-aware cleanup | Open until tests |
| Shared ports/DB создают flaky tests | high/high | namespace/resource leases и capacity scheduler | Open until M6 |
| Project registry downgrade deadlock | medium/high | explicit reader floor, drain/retire, legacy fixtures/docs | Open until M7 |
| 10 lanes перегружают хост/usage | high/medium | correctness отдельно от configurable capacity; queue heavy work | Handled by T-009 |
| Два coordinator sessions создают независимое ownership | medium/critical | authoritative session epoch, owner lock, generation CAS, incompatible admission fail-closed | Handled by T-011; tests pending |
| Archived legacy writer запущен вопреки operator policy | low/critical | Не обещать atomic prevention; T-020 detects, blocks managed integration/release, preserves all state; docs expose condition | Handled by D-009 option 2a; open until AC-38 |
| Legitimate compatible activity ошибочно классифицирована как legacy breach | medium/critical | T-020 ternary per-channel authority baseline + managed worktree/dirty/ref negative controls | Open until AC-38 |
| Legacy process stopped, но lease/outbox удерживает registry non-vacant навсегда | medium/critical | E1–E4 archive-bound finalization достигает vacancy только через exact owner gates; E5 честно оставляет incident blocked | Open until AC-38 |
| Сохранённый legacy diff навсегда остаётся breach и не даёт clear | medium/critical | Authority-free incident preservation baseline разрешает только recovery-stage clean; clear reclassifies exact unchanged evidence как external protected work | Open until AC-38 |
| Incident finalizer обходит checkpoint/guardian/quarantine gates | low/critical | E1–E5 exact matrix, incident semantic disposition, invalidation/retirement/guardian/archive gates; ambiguous states no-mutation | Open until AC-38 |
| Подмена registry/lock или слабые ACL | low/critical | T-013 durable private primitives и adversarial AC-29 | Open until tests |
| Pre-session dirty work получает ложного task owner | medium/critical | D-007 option 1a: external protected scope до verified adoption boundary | Handled by D-007; tests pending |
| GitHub docs, tag и release расходятся по версии или публикуются до gates | medium/high | Single exact-version audit, AC-24/30/31 publication fence, immutable-tag remote smoke AC-32 | Open until M8 |
| Protected scope никогда не освобождается либо снимается между crash boundaries | medium/critical | T-014 CAS adoption state machine и AC-33 fault matrix | Open until M2 |
| Уже активные writers образуют hold-and-wait cycle | medium/critical | T-015 safe-stop + coherent/no-op integration release, AC-34 | Open until M3 |
| Промежуточный commit преждевременно занимает stable target version | high/high | T-017 prerelease sequence и AC-35 commit-gate fixture | Open until M7/M8 |
| Параллельные lanes получают duplicate/out-of-order prerelease versions | high/high | T-018 durable never-reused allocator под integration lease, AC-36 | Open until M5/M7 |
| Stable candidate провалил validation до tag и занял version | medium/high | T-019 supersede на next patch line, AC-37 | Open until M8 |

### Decision application receipt

| Decision/version | Selected outcome and exact current answer source | Changed files/sections/ACs/milestones | Preserved decisions/invariants | Remaining open |
|---|---|---|---|---|
| D-001/R-001 | Разные ТЗ одного проекта параллельны; user message 2026-07-23 | Outcome, RQ-01/02/23, AC-01/22, M1–M6 | single writer per checkout | none |
| D-002/R-001 | Worktree lane на задачу; user command «это всё в ТЗ» после согласованной модели | Architecture, RQ-02/03, AC-01/13/18 | current recovery gates | none |
| D-003/R-001 | Overlap ждёт; user message про endpoint/form | Scope model, RQ-04/05, AC-02–04 | independent parallelism | none |
| D-004/R-001 | Release после integration, не raw commit; accepted clarification | Integration, RQ-10–14, AC-05/06/15/16 | Git root ownership | none |
| D-005/R-001 | Небольшие coherent milestones и более частые commits; user confirmation | Milestone decomposition, RQ-06, AC-07/08, M4 | no arbitrary file commits | none |
| D-006/R-001 | Независимая работа продолжается, idle worker отсутствует; accepted scheduler model | Waiting flows, RQ-07/09, AC-09/11 | process containment | none |
| D-007/R-001 | Прежнее: dirty changes остаются originating lane; accepted full model | Dirty scenario, RQ-19, AC-18, B-016, M2 | user changes authoritative | invalidated by reopen |
| D-007/R-003 reopened | Architecture critic доказал отсутствие trusted task owner у pre-session dirty checkout; нового outcome пока нет | Prior tuples сохранены без semantic rewrite; pending proposals и question log обновлены | D-001–D-006 и no-lost-user-work invariant | D-007 |
| D-008/R-004 | GitHub-facing docs и новая stable release; user message «добавь в тз подготовку доков для гит и релиз новой версии» | Original request, scope/non-goals, RQ-28–30/33–36, AC-30–32/35–37, version/release plan, M7/M8, B-010/B-021 | D-001–D-007, repository version source и pre-publication gates | none |
| D-007/R-005 | Option 1a: pre-session dirty paths — external `protected-user-work`; user answer `1а` | Reconciliation, decision memory, Dirty scenario, RQ-19/31, AC-18/33, T-014, B-016, risks, M2 | Byte/index preservation, no silent cloning, no false recovery/task ownership, D-001–D-006/D-008 | none |
| D-009/R-008 | Option 1a: one-time exclusive upgrade/drain и compatible-only session; user answer `1а` | Source map, decision memory, T-020, edge cases, RQ-37, AC-38, events, rollout, M7, B-001/B-008/B-010, risk register | После migration compatible windows параллельны; single-owner/recovery/no-release-on-ambiguity и D-001–D-008 сохранены | none |
| D-009/R-011 reopened | R-010 critic доказал TOCTOU между external scan/project CAS и legacy workspace lock/start | Prior application tuple set сохранён и помечен stale; pending proposals/question/coverage/risk обновлены без нового normative outcome | D-001–D-008 и no-lost-work invariant | D-009 |
| D-009/R-012 | Option 2a: conditional operator policy; user answer `2a` | Source/reconciliation/decision, T-020, edge case, RQ-37, AC-38, rollout, M7, coverage/risk; prior zero-mutation semantics replaced | D-001–D-008, compatible-client strict coordination, no-lost-work и no-ambiguous-publication invariants | none |
| D-009/R-014 propagation | Existing option 2a unchanged; R-013 technical findings | T-020, RQ-21/37, AC-20/38, M8 preconditions/failure/acceptance, B-004/B-008/B-010/B-014/B-021 | Conditional guarantee, no atomic claim, all D-001–D-009 and no-ambiguous-publication | none |
| D-009/R-016 propagation | Existing option 2a unchanged; R-014/R-015 technical findings | T-020, RQ-37, AC-38, M7 detector matrix, explicit push barrier, project-bound receipt/cross-project rejection, B-001/B-008/B-009/B-017/B-021 | Conditional guarantee, closed channels/transitions, D-001–D-009, no-lost-work/no-ambiguous-publication | none |
| D-009/R-017 propagation | Existing option 2a unchanged; R-016 technical finding | T-020, RQ-37, AC-38, incident lifecycle events, M7/M8, B-004/B-008/B-010/B-012/B-014 | Conditional guarantee, closed detector channels, no atomic claim, all D-001–D-009, no-lost-work/no-ambiguous-publication | none |
| D-009/R-018 propagation | Existing option 2a unchanged; R-017 technical findings | T-020, RQ-37, AC-38, events, rollout, M7, B-001/B-008/B-010/B-012/B-014 | Conditional guarantee, five closed detector channels, no atomic claim, all D-001–D-009, no-lost-work/no-ambiguous-publication | none |
| D-009/R-019 propagation | Existing option 2a unchanged; R-018 technical findings | T-020 detector table, RQ-37, AC-38, events, M7, B-001/B-004/B-008/B-009/B-010/B-012/B-014, risks | Conditional guarantee, no atomic claim, all D-001–D-009, managed activity remains legal, legacy evidence preserved before vacancy | none |
| D-009/R-020 propagation | Existing option 2a unchanged; R-019 technical findings | T-020 preservation+E1–E5 matrices, RQ-37, AC-38, M7, B-001/B-004/B-008/B-009/B-010/B-012/B-014, risks | Conditional guarantee, RQ-03 owner gates, D-007 external protection, no atomic claim, no-lost-work/no-ambiguous-publication | none |
| D-009/R-021 propagation | Existing option 2a unchanged; R-020 technical finding | T-020 O1–O8 matrix, RQ-37, AC-30/38, M7, B-001/B-004/B-008/B-010/B-012/B-014 | Conditional guarantee, C/E matrices, no atomic claim, all authority/Git/publication transitions now explicitly fenced | none |
| D-009/R-022 propagation | Existing option 2a unchanged; R-021 valid-retry technical findings | T-020 B0/transition registry, RQ-37, AC-30/38, M1/M7, B-001/B-006/B-008/B-012/B-014/B-017/B-021, risks | Conditional guarantee, C/E/O semantics, no atomic claim, every current/future mutation must be classified | none |
| D-009/R-023 propagation | Existing option 2a unchanged; R-022 technical findings | T-020 read/sink/BS contracts, RQ-21/37, AC-20/30/38, M1/M7, B-001/B-006/B-008/B-009/B-012/B-014, risks | Conditional guarantee, C/E/O/B0 semantics, no atomic claim, hidden and bootstrap mutations now closed | none |
| D-009/R-024 propagation | Existing option 2a unchanged; R-023 technical findings | T-020 read/observer/BS-alias/clean-B0 contracts, RQ-21/37, AC-20/30/38, M1/M7, B-001/B-006/B-009/B-012/B-014, risks | Conditional guarantee, C/E/O, no atomic claim, lane lifecycle and bootstrap authority remain disjoint and complete | none |
| D-009/R-025 propagation | Existing option 2a unchanged; R-024 technical findings | T-020 install-time I0/atomic BA0, one-ID prompt stage and complete eight-read contract; RQ-21/37, AC-20/30/38, M1/M7, B-001/B-006/B-008/B-009/B-012/B-014, risks | Conditional guarantee, no atomic legacy exclusion claim, one pre-project anchor/epoch, current recovery semantics and all D-001–D-009 preserved | none |
| D-010/R-026 opened | R-025 critic + root verification: plugin manifest has no lifecycle hook | Source map, decision ledger, T-020 I0/BA0 contract, pending proposals, RQ-21/37, AC-20/30/38, M1/M7, B-001/B-022, risks and questions | Technical bootstrap authority, permanent-key and immutable-lock corrections applied without choosing first-run UX; D-001–D-009 preserved | D-010 |
| D-010/R-027 | Option 1a: automatic setup on first explicit Build before repository discovery; user answer `1а` | Status/source map, decision/technical ledgers, I0/BA0 owner contract, RQ-21/30/37, AC-30/32/38, events/rollout, M1/M7, B-001/B-022, risks/questions | Standard install commands, no false hook claim, original requested mode continues after setup, tampered state remains fail-closed; D-001–D-009 preserved | none |
| R-028 source-graph reconciliation | Repository evidence only: complete outgoing companion graph plus marketplace/validator ownership; no new product choice | Status, current-state evidence, source map/receipts, B-023, agent/execution ledgers | D-001–D-010, T-001–T-020, RQ-01–RQ-37, AC-01–AC-38 and M1–M8 propagated unchanged; release/docs ownership made explicit | none |
| R-029 executable-evidence reconciliation | A-026 coverage finding: executable owners needed explicit authority classification | Executable implementation-evidence registry, source reconciliation, B-023, agent/execution ledgers | D-001–D-010, T-001–T-020, RQ-01–RQ-37, AC-01–AC-38 and M1–M8 remain unchanged; implementation evidence cannot override product authority | none |
| R-030 interface/discovery/test-evidence reconciliation | A-027 coverage finding: public interface plus direct discovery and test owners were omitted | Source map `openai.yaml`, executable evidence registry, source reconciliation, B-023, agent/execution ledgers | D-001–D-010, T-001–T-020, RQ-01–RQ-37, AC-01–AC-38 and M1–M8 remain unchanged; interface is explicit-only, not a lifecycle hook | none |
| R-031 validator/edge reconciliation | A-028 findings: O-class false positive and incomplete outgoing edge classification | T-021, AC-24/38, M1/M7, validation red, source map/receipts, B-014/B-015/B-023, agent/execution ledgers | D-001–D-010 preserved; T-001–T-020 and RQ-01–RQ-37 unchanged; T-021 adds only owner-layer validator correctness and exact edge audit | none |
| R-032 M3 cross-owner reconciliation | M3 balanced/strong implementation review found that a local safe-stop marker cannot stop/rebind a live contained writer and a caller-digested receipt cannot prove integration acceptance | T-022, M3 scope/red/green/owner expansion, agent/execution ledgers | D-001–D-010, RQ-01–RQ-37 and AC-01–AC-38 outcomes unchanged; T-022 only completes the already-selected T-004/T-006/T-015 owner handshakes | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | New gaps or reopen requests | Root adjudication |
|---|---|---|---|---|
| R-001 | product/UX, balanced (`gpt-5.6-terra`/medium) | GAPS, high confidence | B-013 lacked observable status acceptance; B-019 lacked a starvation bound | Accepted semantic gaps; no D-008 because status behavior already locked by D-003/D-006 and RQ-20. Added AC-25; selected T-010 and added AC-26. R-002. |
| R-002 | architecture/data/security, balanced (`gpt-5.6-terra`/medium) | GAPS, high confidence | Session admission fence, mixed-version writer fence, registry/lock durability; reopen D-007 for unattributed pre-session dirties | Selected T-011–T-013 and AC-27–29. Reopened D-007 with prior tuples invalidated; R-003 remains Questions. |
| R-003 | architecture findings applied; D-007 reopened | GAPS carried forward | D-007 awaited product disposition | Resolved by user option 1a and full R-005 application; D-008 release scope applied in R-004. |
| R-005 | reliability/validation, strong (`gpt-5.6-terra`/xhigh) | GAPS, high confidence | Missing protected-work adoption lifecycle, live dynamic-cycle exit, satisfiable release ordering and per-commit SemVer sequence | Root-verified. Added T-014–T-017, RQ-31–34, AC-33–35; corrected AC-12/31, version plan and M1–M8 in R-006. No D reopen. |
| R-006 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | PowerShell commands, empty-commit/version conflict, parallel prerelease order, failed stable candidate, M1/AC-34 mismatch; late legacy start requires new authority | Technical gaps root-verified and fixed in R-007 via T-015/T-018/T-019, RQ-35/36, AC-36/37, command/milestone corrections. Opened D-009 for mixed-version policy; no prior D reopened. |
| R-007 | pending post-D-009 closure | Pending | D-009 open | Critic dispatch prohibited while awaiting user answer. |
| R-008 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | RQ-11 contradicted no-op receipt; AC-25/26/27/29 lacked milestone owners; AC-38 omitted late lease/process/workspace-only channels | Root-verified and fixed in R-009 through explicit T-015 exception, M1/M6 mapping, T-020/RQ-37/AC-38 expansion. No D reopen. |
| R-009 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Late-legacy scan was not mandatory before dynamic scope grant and every other authority transition | Root-verified; T-020/RQ-37/AC-38 now require a fresh generation-bound external scan before every authority-changing transition in R-010. No D reopen. |
| R-010 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Project-lock scan is not an atomic exclusion fence against legacy workspace lock/start/write; evidence-backed D-009 reopen | Root verified repository lock boundaries. D-009 reopened in R-011; prior zero-mutation tuples invalidated without silent rewrite. |
| R-011 | pending D-009 answer/application | Pending | D-009 reopened | Critic dispatch prohibited while awaiting user answer. |
| R-012 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Best-effort detection lacked mandatory cadence; active incident absent from stable/tag/Release/remote-smoke gates | Root-verified and propagated into T-020/RQ-37/AC-38 and M8 in R-013. No D reopen. |
| R-013 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Covenant lacked admission receipt; breach-before-scan lacked durable incident; incident replay/all-state preservation and D-009→M8 receipt incomplete | Root-verified and fixed in R-014 via T-020/RQ-21/37/AC-20/38 and D-009 propagation receipt. No D reopen. |
| R-014 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Detector regressed to abstract scan: legacy channels, complete transition set and epoch/generation/attempt binding missing | Root-verified; closed channels and one-use attempt-bound receipts restored in T-020/RQ-37/AC-38/M7 at R-015. No D reopen. |
| R-015 | generalist terminal closure, Sol-high (`gpt-5.6-sol`/high) | GAPS, high confidence | Push omitted from closed publication list; RQ/AC omitted project identity binding; current decision application receipt missing | Root-verified and fixed in R-016 through RQ-37/AC-38 and D-009/R-016 propagation receipt. No D reopen. |
| R-016 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Active incident rejected every authority transition, but the specification did not distinguish forbidden ordinary authority/publication from the incident-safe drain/renew/clear/resume path needed to recover | Root-verified and fixed in R-017 via two exhaustive transition sets in T-020/RQ-37/AC-38. No D reopen. |
| R-017 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Detector channels были ненормативными; drain-start ошибочно требовал zero; resume расширял authority под active incident; ordinary set не закрывал floor lowering/session retirement/downgrade/rollback | Root-verified and fixed in R-018 through five explicit channels, split drain, post-clear resume and expanded ordinary set. No D reopen. |
| R-018 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Five channels lacked canonical ternary attribution and managed negative controls; incident-safe path lacked repository-required transition clearing legacy lease/outbox to reach vacancy | Root-verified against `RecoveryRegistry._is_vacant` and implementation delegation. Fixed in R-019 with normative verdict table and archive-bound `legacy-terminal-finalize`. No D reopen. |
| R-019 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Generic terminal-finalize could bypass lane zero/guardian/invalidation/quarantine gates; original breach baseline made correctly preserved Git state permanently non-clean | Root-verified against current lease kinds/states/quarantines and release gates. Fixed in R-020 through E1–E5 eligibility and authority-free incident preservation baseline. No D reopen. |
| R-020 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Ordinary set was called exhaustive but no longer enumerated, leaving fresh detector cadence undefined for lane/scope/integration/version/commit/publication transitions | Root-verified and fixed in R-021 with O1–O8 concrete matrix, per-transition receipt/rebarrier rules and docs/acceptance propagation. No D reopen. |
| R-021 | generalist terminal closure retry, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | A-018 transport output unusable; valid A-019 found unclassified durable lifecycle writers, missing absent-registry bootstrap receipt and AC commit/`O7` contradiction | Root-verified. R-022 adds stable sink-complete transition registry, B0 prospective epoch/gen-0 contract and separate `O6`/`O7` fixtures. No D reopen. |
| R-022 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Current map missed eight sink-reachable RecoveryRegistry methods and runner prompt stage/GC; lane initialize was misclassified as B0; bootstrap incident had no typed binding or path through drain/clear/gen-0 | Root-verified. R-023 separates reads/writes, maps persistent/prompt/lane sinks, adds runtime sink context and generationed BS1–BS4 clear lifecycle. No D reopen. |
| R-023 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Nominal reads still reached lock/chmod/fsync/Git/prompt sinks; BS IDs had no aliases into session-bound E lifecycle; clean B0 left undefined BS scanning state and split composite ownership | Root-verified. R-024 defines non-creating/no-spawn reads, R observation IDs, prompt key stage-only, exact BS aliases and clean-no-BS composite B0. No D reopen. |
| R-024 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Bootstrap coordination was circular because its common-dir lock was itself a pre-receipt sink; prompt key and snapshot had two IDs for one guarded context; `read_private_source` was omitted from the no-sink list | Root-verified. R-025 adds install-time I0 and atomic BA0 authority, folds key creation into one prompt-stage ordinal, and names all eight reads. No D reopen. |
| R-025 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | No supported executable owner for install-time I0; BA0 first sink still lacked a receipt authority; mutable anchor-as-lock could split serialization; concurrent atomic-replace HMAC keys could diverge/orphan anchors | Root verified missing manifest hook. R-026 technically defines bounded I0 setup authority, one-use BA0 capability, permanent no-replace key and immutable anchor lock with separate records. Opened D-010 only for setup UX; no further critic until answer. |
| R-027 | generalist terminal closure, Sol/high (`gpt-5.6-sol`/high) | COVERED, high confidence | None | Terminal closure confirms automatic pre-discovery I0 setup, bounded bootstrap authority, immutable locks/permanent key, BA0/B0/BS convergence, complete sink/read registry, D-009 conditional boundary and M1–M8 ownership. Ready. |
| R-028 | source-graph reconciliation closure, balanced (`gpt-5.6-terra`/medium) | GAPS, high confidence | Executable runner/routing/recovery/validator/test sources lacked explicit authority/non-authority classification | Root-verified against SKILL, README/CONTRIBUTING and owner ranges. R-029 adds a bounded executable-evidence registry and aligns B-023 without changing any product tuple. |
| R-029 | executable-evidence reconciliation closure, strong (`gpt-5.6-terra`/xhigh) | GAPS, high confidence | Public `openai.yaml`, `discovery_contract.py` and direct runner/routing/recovery/discovery test owners were omitted | Root-verified against public interface metadata, runner import, validator enforcement and test imports. R-030 adds bounded map/evidence rows without changing product tuples. |
| R-030 | terminal source/interface closure, Sol/high (`gpt-5.6-sol`/high) | GAPS, high confidence | Package validator confuses O-class IDs with fixed models; several direct source/link edges remained implicit | Root reproduced the validator failure and audited all Markdown links. R-031 adds T-021 with M1/M7/AC ownership and explicit internal/external edge classification. |
| R-031 | validator/edge reconciliation closure, balanced (`gpt-5.6-terra`/medium) | COVERED, high confidence | None | Fresh current-revision closure confirms source/interface/evidence graph, D-009/D-010 preservation, T-021 red/green ownership, RQ/AC/M ownership and release blocking until full green. Ready. |
| R-032 | M3 cross-owner delta closure, balanced (`gpt-5.6-terra`/medium) | COVERED, high confidence | None | Fresh closure confirms T-022 is implementable, preserves D-001–D-010 and existing RQ/AC outcomes, keeps runner as lane lifecycle consumer, project coordinator as scheduler and M5 integration owner as the sole acceptance producer. Ready. |

## 10. Open questions

Blocking product questions:

- None.

Non-blocking assumptions:

- Git worktree доступен на поддерживаемых host platforms; проверить forward tests.
- Отдельный project-state module достаточен без production dependency; подтвердить minimality в M1.
- Dedicated integration ref/worktree может быть реализован без перемещения user checkout; подтвердить Git fixtures.
- Contract/read dependency keys сначала объявляются root planning, а не выводятся полностью автоматически; качество prediction страхуется worktree isolation и final verification.

## 11. Agent activity ledger

Created logical agent runs through the exact OpenBuild runner: `56`.

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| A-001 | yes | search / parallel-task-lanes-spec-discovery | `gpt-5.3-codex-spark` exact CLI selection | low | transport completed, semantic evidence unusable | Repository discovery result не потреблён; открыл targeted root recovery для раздела 2 | exact receipt: `turn.completed`, exit `0`, process tree stopped, `result_evidence=invalid` |
| A-002 | yes | critic / product-UX R-001 | `gpt-5.6-terra` | medium | completed, `GAPS`, high confidence | Выявил отсутствие observable status acceptance и строгой fairness guarantee; закрыто AC-25/26 и T-010 в R-002 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-003 | yes | critic / architecture-data-security R-002 | `gpt-5.6-terra` | medium | completed, `GAPS`, high confidence | Выявил admission/mixed-version/durable-file gaps и evidence-backed reopen D-007; technical gaps закрыты T-011–T-013/AC-27–29, D-007 затем разрешён option 1a в R-005 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-004 | yes | critic / reliability-validation R-005 strong closure | `gpt-5.6-terra` | xhigh | completed, `GAPS`, high confidence | Выявил adoption lifecycle, live-cycle, release-ordering и per-commit SemVer gaps; закрыто T-014–T-017/RQ-31–34/AC-33–35 и milestone corrections в R-006 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-005 | yes | critic / generalist R-006 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил Windows command, no-op commit, global version allocator, failed stable candidate и milestone gaps; technical findings закрыты в R-007, late legacy start routed to D-009 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-006 | yes | critic / generalist R-008 post-decision closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил RQ-11/no-op contradiction, unowned AC и неполный late-legacy detection matrix; закрыто в R-009 без D reopen | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-007 | yes | critic / generalist R-009 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил timing gap external scan перед dynamic scope grant/other authority transitions; закрыто generation-bound barrier в R-010 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-008 | yes | critic / generalist R-010 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Доказал TOCTOU между project scan/CAS и legacy workspace lock/start; D-009 evidence-backed reopened | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-009 | yes | critic / generalist R-012 post-decision closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил missing detection cadence и active-incident publication fence; закрыто в R-013 без D reopen | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-010 | yes | critic / generalist R-013 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил covenant receipt, durable incident, replay/all-state preservation и D-009→M8 trace gaps; закрыто в R-014 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-011 | yes | critic / generalist R-014 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил abstract detector regression и stale receipt risk; closed channel/attempt binding restored в R-015 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-012 | yes | critic / generalist R-015 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил missing push, project identity binding и current receipt; закрыто в R-016 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-013 | yes | critic / generalist R-016 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил незамкнутую incident recovery transition matrix; закрыто двумя exhaustive sets и fault/replay acceptance в R-017 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-014 | yes | critic / generalist R-017 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил ненормативные detector channels, drain liveness, incident-time resume и downgrade/rollback omissions; закрыто в R-018 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-015 | yes | critic / generalist R-018 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил отсутствие channel-specific verdict predicates/negative controls и невозможность достичь legacy vacancy; закрыто в R-019 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-016 | yes | critic / generalist R-019 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил bypass зрелых terminal gates и preservation-baseline dead-end; закрыто E1–E5 и recovery-only baseline в R-020 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-017 | yes | critic / generalist R-020 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил missing normative ordinary transition closure/cadence; закрыто O1–O8 и AC/docs propagation в R-021 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-018 | yes | critic / generalist R-021 terminal closure attempt | `gpt-5.6-sol` configured | high | transport failed, semantic result unusable | Specification unchanged; same-tier fresh retry required, no finding consumed | exact receipt: exit `0`, result file present, but no `turn.completed`; `event-stream-invalid`, observed model unavailable |
| A-019 | yes | critic / generalist R-021 terminal closure retry | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил unclassified state writers, bootstrap circularity и `O6`/`O7` acceptance mismatch; закрыто в R-022 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-020 | yes | critic / generalist R-022 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил hidden read/prompt sinks, lane/B0 misclassification и незамкнутый bootstrap incident; закрыто в R-023 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-021 | yes | critic / generalist R-023 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил lock/chmod/fsync/read-spawn sinks, missing BS lifecycle aliases и orphan clean BS; закрыто в R-024 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-022 | yes | critic / generalist R-024 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил pre-receipt lock circularity, dual-ID prompt staging и omission `read_private_source`; закрыто install-time I0, atomic BA0 и complete read/stage contract в R-025 | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-023 | yes | critic / generalist R-025 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил unsupported install-hook owner, BA0 pre-receipt sink, replaceable lock identity и key rotation race; technical gaps закрыты в R-026, D-010 setup UX открыт | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-024 | yes | critic / generalist R-027 terminal closure | `gpt-5.6-sol` | high | completed, `COVERED`, high confidence | Подтвердил implementation-ready coverage D-010/T-020/RQ-37/AC-38, sink/read completeness, D-009 conditional boundary и M1–M8 ownership | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result |
| A-025 | yes | search / parallel-task-lanes-r027-refine-discovery | `gpt-5.3-codex-spark` configured exact CLI selection | low | transport completed, semantic evidence unusable | Результат discovery не потреблён; targeted root recovery выявил неполный source graph и сформировал R-028 reconciliation | exact receipt: `turn.completed`, exit `0`, process tree stopped, `result_evidence=invalid`; observed model unavailable |
| A-026 | yes | critic / R-028 source-graph closure | `gpt-5.6-terra` | medium | completed, `GAPS`, high confidence | Выявил, что executable owners были только narrative evidence без authority classification; закрыто bounded evidence registry в R-029 | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-027 | yes | critic / R-029 strong closure | `gpt-5.6-terra` | xhigh | completed, `GAPS`, high confidence | Выявил omitted public interface, discovery contract и direct test owners; закрыто source/evidence rows в R-030 | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-028 | yes | critic / R-030 terminal closure | `gpt-5.6-sol` | high | completed, `GAPS`, high confidence | Выявил package-validator O-class collision и implicit outgoing edges; root reproduced failure, added T-021 ownership and completed edge classification in R-031 | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-029 | yes | critic / R-031 fresh closure | `gpt-5.6-terra` | medium | completed, `COVERED`, high confidence | Подтвердил complete authority graph, D-009/D-010 preservation, T-021 M1/M7/AC ownership, RQ-01–37, AC-01–38 and M1–M8 readiness | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-030 | yes | search / R-031 run discovery | `gpt-5.3-codex-spark` configured exact CLI selection | low | transport completed, semantic evidence unusable | Result не потреблён; targeted root recovery определил M1 owner/test scope | exact receipt: `turn.completed`, exit `0`, process tree stopped, `result_evidence=invalid` |
| A-031 | yes | implementation / M1a project-state scaffold | `gpt-5.6-terra` | medium | completed; bounded handoff accepted | Добавил изолированный project-state scaffold, первые tests и T-021 owner hook; root сохранил M1 incomplete из-за hardening gaps | exact receipt: `turn.completed`, exit `0`, valid result, full-tree-zero, durable finalize, registry vacancy |
| A-032 | yes | implementation / M1b hardening pre-edit assessment | `gpt-5.6-terra` | medium | zero-write `capability-gap`, semantic handoff rejected | Единственная malformed escalation line нормализована к configured trigger; source checkpoint invalidated до release | exact receipt: `turn.completed`, exit `0`, valid result, zero writes, `semantic-handoff-rejected`, registry vacancy |
| A-033 | yes | implementation / M1b hardening route step 2 | `gpt-5.6-terra` | xhigh | observation deadline after partial edits; cancelled | Partial project owner/validator/tests preserved; no handoff accepted and no commit created | exact receipt: no terminal event/result, cancelled, process tree stopped, registry vacancy, owner-private recovery checkpoint present |
| A-034 | yes | search / R-031 M1 continuation discovery | `gpt-5.3-codex-spark` configured exact CLI selection | low | transport completed, semantic evidence unusable | Result не потреблён; targeted root recovery подтвердил R-031 closure, M1 partial diff и owner/test scope | exact receipt: `turn.completed`, exit `0`, process tree stopped, `result_evidence=invalid`; observed model unavailable |
| A-035 | yes | review / R-031 M1 high-risk closure | `gpt-5.6-terra` | medium | completed, `ACCEPT`, high confidence | Проверил фактический M1 diff, project-state owner, Windows ACL/durability paths, validator masking, tests и prerelease metadata; findings отсутствуют | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-036 | yes | implementation / R-031 M2 lane lifecycle | `gpt-5.6-terra` | medium | transport completed; semantic handoff abandoned | Создал bounded M2 owner/tests, но оставил три generated nested-repository fixtures и не получил runtime green; root подтвердил Windows anchor-lock red, handoff не принимался | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, `terminal-abandoned` for outside-set drift, no handoff, registry vacancy |
| A-037 | yes | review / M2 balanced pass | `gpt-5.6-terra` | medium | completed, `FINDINGS`, high confidence | Выявил fail-open deletion evidence, scope aliases, неполный adoption replay и пропущенную legacy vacancy; root добавил red/green remediation | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-038 | yes | review / M2 strong pass | `gpt-5.6-terra` | xhigh | completed, `FINDINGS`, high confidence | Выявил resume/attach CAS, stale replay, fake recovery binding, rename/mode/case gaps; root исправил owner-layer lifecycle и tests | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-039 | yes | review / M2 Sol-high closure | `gpt-5.6-sol` | high | completed, `FINDINGS`, high confidence | Выявил cancel/attach race, stale running, nested schema, dirty-running replay, quarantine replay и absent-worktree close; root воспроизвёл четыре red signals и закрыл все шесть findings | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-040 | yes | review / M2 changed-diff Sol-high closure | `gpt-5.6-sol` | high | completed, `FINDINGS`, high confidence | Подтвердил session/adoption и ledger gaps, а также незакрытые production runner bridge и real two-running-lane acceptance; same-scope findings исправлены, cross-owner findings остаются blocking | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-041 | yes | replacement implementation / M2 runner bridge and real two-lane acceptance | `gpt-5.6-terra` | medium | transport completed; semantic `BLOCKED`, handoff abandoned | Не изменил leased files: focused tests не смогли создать `TemporaryDirectory` ни в системном, ни в workspace-local temp root; bridge и tests остались нереализованными, authoritative M2 diff сохранён byte-for-byte | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result; initial blocked rejection failed closed because generated `.pyc` made the checkpoint ineligible, then exact `terminal-abandoned` for outside-set drift restored registry vacancy; no handoff |
| A-042 | yes | second/final replacement implementation / M2 runner bridge and real two-lane acceptance | `gpt-5.6-terra` | medium | transport completed; semantic `BLOCKED`, handoff rejected | Прошёл host TEMP/TMP probe, но mandatory sandbox probe создал child directory и получил `PermissionError` на запись и `WinError 5` на cleanup до первой правки; leased files не изменены, bridge/tests не реализованы | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result; durable `semantic-handoff-rejected` with recovery-eligible checkpoint, no handoff, registry vacancy |
| A-043 | yes | search / R-031 M3–M8 owner map | `gpt-5.3-codex-spark` configured exact CLI selection | low | transport completed, semantic evidence unusable | Result не потреблён; targeted root recovery восстановил M3–M8 owner/AC map из current specification | exact receipt: `turn.completed`, exit `0`, process tree stopped, `result_evidence=invalid`; availability fallback ineligible |
| A-044 | yes | implementation / M3 scope manager capability assessment | `gpt-5.6-terra` | medium | zero-write `task-complexity-above-tier`, semantic handoff rejected | Verified clean zero-write state; checkpoint invalidated and route advanced exactly one rung | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result, durable `semantic-handoff-rejected`, registry vacancy |
| A-045 | yes | implementation / M3 scope manager route step 2 | `gpt-5.6-terra` | xhigh | transport completed; handoff abandoned | Produced the bounded scope owner/tests. Root found a concurrent create CAS failure and declined handoff; generated ignored fixture trees caused exact outside-set drift, so owner-derived abandonment preserved the partial diff and returned the registry to vacancy | exact receipt: observed model/agent, `turn.completed`, exit `0`, valid result, `terminal-abandonment-v1`, no handoff |
| A-046 | yes | review / M3 balanced pass | `gpt-5.6-terra` | medium | completed, `REVISE`, high confidence | Found caller-boolean release authority, unreachable live expansion and unrelated cycle-reservation victim; root reproduced all three reds | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-047 | yes | review / M3 strong changed-diff pass | `gpt-5.6-terra` | xhigh | completed, `REVISE`, high confidence | Demonstrated that self-digested release, static allowed-set and unconsumed safe-stop marker cannot satisfy cross-owner M3 acceptance; triggered R-032/T-022 | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-048 | yes | critic / R-032 M3 cross-owner closure | `gpt-5.6-terra` | medium | completed, `COVERED`, high confidence | Confirmed T-022/M3b owner order, no D reopen, implementable replay boundaries and preserved D/RQ/AC outcomes | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-049 | yes | review / R-032 M3a Sol-high pass | `gpt-5.6-sol` | high | completed, `REVISE`, high confidence | Accepted the fail-closed milestone split but found durable released-record bypass, final-link omission, expansion status, fairness evidence, ledger and unpublished-pin gaps; all owning-layer corrections are in the changed candidate | exact receipt: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-050 | yes | review / R-032 M3a changed-diff Sol-high pass | `gpt-5.6-sol` | high | completed, `REVISE`, confidence `0.98` | Found active-claim deletion/cancellation through the durable sink, granted expansion absent from fresh runner authority and inactive-cycle cancellation without a runnable victim; root added transition guards and real expansion/cycle progress tests | exact receipt `20260723T220701Z-43e7713c37`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-051 | yes | review / R-032 M3a remediated Sol-high pass | `gpt-5.6-sol` | high | completed, `REVISE`, confidence `0.98` | Found claimless alpha.2 lane authority absent from M3 conflicts and logical contract/resource keys incorrectly treated as runner filesystem paths; root added explicit legacy-claim migration/fail-closed overlap handling and separated lane authority from allowed-file authority | exact receipt `20260723T222050Z-68349a0992`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-052 | yes | review / R-032 M3a terminal release pass | `gpt-5.6-sol` | high | completed, `REVISE`, confidence `0.98` | Found logical keys still entering filesystem/protected-work checks, legacy migration missing final-link validation and batched migrated tickets colliding with the next generation; root added typed request binding, physical/logical separation, migration no-follow and strictly ordered batch tickets | exact receipt `20260723T223618Z-ebb16b4b91`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-053 | yes | review / R-032 M3a typed-scope closure pass | `gpt-5.6-sol` | high | completed, `REVISE`, confidence `0.99` | Found protected work absent from common eligibility/migration, real admission publishing before unsafe legacy preflight and claimless protected waiters lacking adoption resume; root moved all three into the durable reservation/baseline-refresh lifecycle | exact receipt `20260723T224830Z-fe63dfda42`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-054 | yes | review / R-032 M3a protected-work closure pass | `gpt-5.6-sol` | high | completed, `REVISE`, confidence `0.99` | Found claimless protected-waiter replay, accepted-tip ancestry, mixed logical-scope recovery authorization and existing-waiter legacy-preflight gaps; root added checkpoint-owned file recovery authority, reservation replay, ancestor-bound refresh and pre-mutation regression coverage | exact receipt `20260723T230415Z-1a8742e1cf`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-055 | yes | review / R-032 M3a A-054 remediation pass | `gpt-5.6-sol` | high | completed, `REVISE`, confidence `0.98` | Found crash-replay ticket inversion and generic-sink protected-adoption forgery; root made enqueue age immutable with lane intent and routed protected intent/rollback/adopt through purpose-specific sinks whose adoption commit rechecks current provenance, ref tip and Git tree | exact receipt `20260723T232225Z-28803c7585`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |
| A-056 | yes | review / R-032 M3a alpha.3 release closure | `gpt-5.6-sol` | high | completed, `ACCEPT`, confidence `0.97` | Verified immutable crash-replay fairness, generic protected-state rejection, purpose-specific Git/provenance adoption, A-054 recovery/preflight fixes, legacy migration, path guards, runner authority and truthful alpha.3 boundary; no actionable findings | exact receipt `20260723T234431Z-50406419dd`: observed model/agent, `turn.completed`, exit `0`, process tree stopped, valid result |

Native collaboration review runs, not created through `agent_runner.py` and therefore not included in the exact-runner count:

| Run | Created | Role/task | Actual model | Effort | Status/outcome | Work and specification mapping | Evidence |
|---|---|---|---|---|---|---|---|
| N-001 | yes | review / final M2 bridge and release-candidate closure | `gpt-5.6-sol` | max | completed, `APPROVE`, confidence `0.94` | Read-only review covered AC-01/13/14/18/19/21/33, found post-containment audit replay and M1 schema-1 compatibility gaps, then accepted both TDD remediations with no remaining actionable finding | native collaboration runtime, read-only strongest profile; no exact OpenBuild runner receipt, disclosed separately |

Pre-spawn dispatch failures (not included in created count): four historical local invocations were rejected before agent/process creation: unsupported model-map `--project-root`, discovery-only expected-map pairing on a critic, implementation-only specification revision on a critic, and a prompt path inside the workspace. The current run also rejected a recovery authorization before process creation because the retained checkpoint had exact reason `preexisting-dirty-overlap`; root used the already-authorized same-scope completion path after durable vacancy and diff attribution. Before A-035, two review dispatches were rejected before process creation because root first paired an expected-map digest without a discovery fallback source and then supplied implementation-only recovery metadata to a review agent; the third bounded dispatch removed those invalid options and activated normally. Before A-042, one start was rejected before process creation because redirecting root-runner TEMP put its private control-plane under the workspace and changed the reserved source boundary; the unactivated reservation was released, those private failed-start artifacts were removed, and the counted A-042 run used an explicit system-Temp control-plane path with workspace-local worker TEMP/TMP. Before A-050, one dispatch was rejected before process creation because implementation-only specification/recovery metadata was supplied to a review agent; the counted retry removed those options.

## 12. Execution and validation log

### 2026-07-23 — discovery и R-001 draft

- Changed: создано новое отдельное ТЗ; implementation/version/docs files не менялись.
- Routing: packaged map `3f9ece...`; A-001 exact Spark/low/read-only завершился с invalid result evidence; availability fallback ineligible; targeted root recovery использовал current code/tests/contracts.
- Primary signal: not run — workflow target `Ready`.
- Validation: baseline Git metadata read; source selection, evidence ranges и repository commands verified; specification critics pending.
- Minimality decision: отдельный project coordinator поверх current lane recovery, без новых dependencies/services.
- Review: pending high-risk product/UX, architecture/data/security и strong closure passes.
- Version: future minor candidate `2.4.0`; unchanged in `new`.
- Commit: not created.
- Remaining: exact readiness critics, root adjudication, final `Ready` gate.

### 2026-07-23 — product/UX critique и R-002

- Changed: добавлены observable status-transition acceptance AC-25 и starvation-free monotonic-ticket contract T-010/AC-26.
- Routing: critic high-risk route step 1, `openbuild_review_balanced`, observed `gpt-5.6-terra`/medium/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; оба findings root-verified и применены, reopen requests отсутствуют.
- Minimality decision: новый статус не введён; тестируется уже заданный RQ-20. Fairness закрыта одной deterministic ordering policy без preemption.
- Review: product/UX gap pass завершён; architecture/data/security и strong closure pending.
- Version: future minor candidate; unchanged.
- Commit: not created.
- Remaining: complementary critic и closure.

### 2026-07-23 — architecture/data/security critique и R-003 Questions

- Changed: selected T-011 authoritative session epoch, T-012 writer-floor/mixed-version fence и T-013 owner-private durable registry/lock contract; добавлены RQ-25–27 и AC-27–29. D-007 evidence-backed reopened без применения нового outcome.
- Routing: critic high-risk route step 1, `openbuild_review_balanced`, observed `gpt-5.6-terra`/medium/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; three technical gaps root-verified and resolved; one product-impacting attribution gap routed to D-007.
- Minimality decision: reuse current durable-file primitives and retain lane-local recovery; no daemon/service/dependency.
- Review: complementary high-risk pass завершён; strong closure запрещён, пока D-007 open.
- Version: future minor candidate; unchanged.
- Commit: not created.
- Remaining: user answer D-007 -> full decision application -> fresh strong closure.

### 2026-07-23 — D-008 release scope и D-007 option 1a, R-005

- Changed: GitHub-facing docs и stable release оформлены как D-008/RQ-28–30/AC-30–32/M7–M8; D-007 option 1a применён к reconciliation, scenario, RQ-19, AC-18, M2, coverage и risks.
- Decision application: pre-session dirty paths являются external `protected-user-work`; независимые lanes разрешены, конфликтующие ждут verified adoption boundary; автоматическая task/recovery attribution запрещена.
- Primary signal: not run — specification-only workflow.
- Validation: все D-007 stale tuples заменены; D-008 publication остаётся future milestone и не выполняется в `new`.
- Review: fresh reliability/validation strong closure pending.
- Version: future stable minor candidate `2.4.0` либо следующая допустимая minor от authoritative base; unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: strong readiness closure и document validation.

### 2026-07-23 — strong reliability critique и R-006 remediation

- Changed: добавлены replay-safe adoption T-014, no-live-hold-and-wait exit T-015, двухфазный release gate T-016 и prerelease sequencing T-017; requirements/AC/milestones/risks синхронизированы.
- Routing: critic high-risk route step 2/3 по ранее подтверждённому `coverage-gap`, `openbuild_review_strong`, observed `gpt-5.6-terra`/xhigh/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; четыре findings root-verified, product outcomes D-001–D-008 не изменились, reopen requests отсутствуют.
- Minimality decision: adoption и cycle exit используют project-state CAS/current recovery and Git primitives; release sequencing следует existing SemVer/commit policy, без новых dependencies/services.
- Review: R-006 terminal Sol/high closure pending по подтверждённому `coverage-gap` trigger.
- Version: stable target остаётся future `2.4.0`, промежуточные commits теперь явно prerelease; current manifest unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: terminal closure и document validation.

### 2026-07-23 — terminal Sol/high critique и R-007 Questions

- Changed: PowerShell/POSIX validation commands разделены; `abandoned-no-change` больше не создаёт запрещённый empty commit; добавлены T-018 global prerelease allocator, T-019 failed-candidate supersession, RQ-35/36 и AC-36/37; AC-34 перенесён в integration milestone.
- Routing: critic high-risk route step 3/3 по подтверждённому `coverage-gap`, `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; technical findings root-verified и применены. Late legacy start не может быть outcome-neutrally fenced старым client, поэтому создан D-009 вместо silent choice. Markdown UTF-8/no-BOM/newline/trailing-whitespace checks green; RQ-01–36, AC-01–37 и T-001–19 sequential/unique.
- Minimality decision: version allocation сериализуется существующей integration owner-layer; no-op abandonment использует admitted-base commit/receipt; failed candidate переходит на следующую SemVer line без rewrite.
- Review: terminal critic завершён, но Ready gate открыт до user answer D-009 и fresh post-answer closure.
- Version: current manifest `2.3.6` unchanged; future allocator/recovery plan documented.
- Commit/tag/GitHub Release: not created.
- Remaining: D-009 answer -> decision application -> fresh closure -> document validation.

### 2026-07-23 — D-009 option 1a application, R-008

- Changed: mixed-version admission закреплён как one-time exclusive upgrade/drain с compatible-only epoch; late legacy activity создаёт global-integrity safe-stop/quarantine. Добавлены T-020, RQ-37, AC-38, events, rollout/migration docs и M7 coverage.
- Decision application: user answer `1а` применён ко всем D-009 tuples; обычные compatible windows после migration продолжают parallel работу без project-wide stop.
- Primary signal: not run — specification-only workflow.
- Validation: D-009 source/decision/requirements/acceptance/milestone/coverage/risk tuples synchronized; no blocking product questions remain.
- Minimality decision: operator-enforced one-time drain + existing registry/process/ref evidence; старый 2.3.6 binary не модифицируется и поздняя активность fail-closed.
- Review: fresh R-008 terminal Sol/high closure pending; новый critic не запускался до user answer.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: fresh closure и final document validation.

### 2026-07-23 — R-008 post-decision critique и R-009 remediation

- Changed: RQ-11 получил точное T-015 no-change exception без нового commit; AC-25/26 назначены M6, AC-27/29 — M1; T-020/RQ-37/AC-38 расширены на late legacy lease, process и workspace-only write.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success на новой revision.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; три findings root-verified, outcome-neutral и применены, D-001–D-009 не переоткрывались.
- Minimality decision: no-op release связывается с existing admitted-base commit; late legacy detection использует worktree enumeration и existing workspace registry/process identities.
- Review: fresh R-009 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-009 timing critique и R-010 remediation

- Changed: T-020/RQ-37 теперь требуют fresh external-integrity scan под project lock перед каждой authority-changing transition; AC-38 покрывает все transition classes и late-legacy channels.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; единственный timing gap root-verified и исправлен без D reopen.
- Minimality decision: один generation-bound barrier переиспользует project lock/CAS и existing worktree/registry/process integrity primitives.
- Review: fresh R-010 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-010 atomicity critique и R-011 Questions

- Changed: D-009 evidence-backed reopened; prior T-020/RQ-37/AC-38/events/rollout/M7/coverage/risk application tuples marked stale without applying a new product outcome.
- Routing: terminal critic `openbuild_review_sol_high`, runner receipt observed `gpt-5.6-sol`/high/read-only, exact terminal success. Critic text lacked runtime receipt but outer runner evidence is valid.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; root verified that legacy 2.3.6 uses a separate workspace lock and can start/write between project scan and CAS. No atomic zero-mutation fence exists in current architecture.
- Minimality decision: none applied while D-009 reopened; options separate pragmatic operator policy, physical clone isolation and OS-level enforcement scope expansion.
- Review: paused by OpenBuild readiness protocol until D-009 answer and full application.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: D-009 answer -> full tuple rebuild -> fresh closure -> document validation.

### 2026-07-23 — D-009 option 2a application, R-012

- Changed: prior zero-mutation legacy fence полностью заменён conditional operator policy; T-020/RQ-37/AC-38, edge case, rollout, M7, coverage и risks rebuilt.
- Decision application: user answer `2a` фиксирует one-time drain/update и compatible-only ordinary workflow. Deliberate archived-legacy start MAY mutate до detection; managed integration/release then blocks, all Git/worktree state is preserved, atomic exclusion is not claimed.
- Primary signal: not run — specification-only workflow.
- Validation: all D-009/R-011 stale tuples received fresh R-012 application authority; no blocking product questions remain.
- Minimality decision: no clone, broker, service or OS-level ACL supervisor; compatibility covenant + detection/preservation uses existing local primitives.
- Review: fresh R-012 terminal Sol/high closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-012 propagation critique и R-013 remediation

- Changed: T-020/RQ-37/AC-38 now require best-effort fresh detection before every authority/publication transition while explicitly allowing after-scan race; M8 requires incident-free epoch and blocks stable/tag/Release/remote smoke on active incident.
- Routing: terminal critic `openbuild_review_sol_high`, runner receipt observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; cadence/publication findings root-verified and applied without changing D-009 option 2a.
- Minimality decision: detection cadence reuses current local scans; no atomic fence, clone, broker or OS supervisor added.
- Review: fresh R-013 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-013 incident critique и R-014 remediation

- Changed: durable operator covenant receipt, breach-before-scan incident materialization, crash-safe incident/fence/clear и full coordinator/Git state preservation added to T-020/RQ-21/37/AC-20/38; D-009→M8 propagation receipted.
- Routing: terminal critic `openbuild_review_sol_high`, runner receipt observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; four acceptance/traceability findings root-verified and resolved without D reopen.
- Minimality decision: covenant/incident reuse owner-private durable state and existing project epoch; no new service/dependency.
- Review: fresh R-014 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-014 detector critique и R-015 remediation

- Changed: T-020/RQ-37/AC-38 restored closed legacy detection channels, exact transition classes, epoch/generation/attempt binding and no-reuse after fault/cancel/retry/restart/drift; M7 owns the detector matrix.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; single outcome-neutral detector-contract regression fixed without D reopen.
- Minimality decision: attempt-bound receipt extends existing durable project state; no new provider/service/dependency.
- Review: fresh R-015 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-015 trace critique и R-016 remediation

- Changed: push added to closed publication barriers; project identity restored in RQ-37/AC-38 receipt binding with cross-project rejection; D-009/R-016 decision application receipt added.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; three traceability omissions fixed without D reopen.
- Minimality decision: existing attempt-bound receipt schema gains one binding field and one already-authoritative publication transition.
- Review: fresh R-016 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-016 incident-transition critique и R-017 remediation

- Changed: T-020/RQ-37/AC-38 разделяют две exhaustive группы: ordinary authority/publication transitions, всегда запрещённые при active incident, и incident-safe drain/preserve/renew/clear/resume operations, которые могут только сохранять или уменьшать authority.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; recovery dead-end root-verified и закрыт one-use receipts, full-tree-zero/vacancy, preserved-state validation, CAS generation advance и fault/replay matrix без изменения D-009 option 2a.
- Minimality decision: recovery использует существующие detector/covenant/incident records; integration refs, scope release, publication и evidence deletion во время incident запрещены.
- Review: fresh R-017 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-017 recovery-sequence critique и R-018 remediation

- Changed: T-020/RQ-37/AC-38 теперь нормативно перечисляют пять legacy detector channels; drain-start отделён от zero-gated drain-complete; covenant renewal остаётся inactive candidate; resume выполняется только после clear; floor lowering/session retirement/downgrade/rollback добавлены в forbidden ordinary set.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; четыре findings root-verified и исправлены без D reopen. Per-channel positive evidence exactly-once материализует incident до ordinary rejection; faults/restarts покрыты staged replay acceptance.
- Minimality decision: один закрытый detector matrix и существующий CAS incident record; новых providers/services/dependencies нет.
- Review: fresh R-018 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-018 detector/vacancy critique и R-019 remediation

- Changed: добавлена нормативная C1–C5 detector table с canonical evidence, authority baseline, `clean|breach|indeterminate`, fail-closed и receipt fields; incident-safe lifecycle получил archive-bound `legacy-terminal-finalize`.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; root подтвердил `RecoveryRegistry._is_vacant == lease is None && outbox is None` и обязательный legacy lease release. RQ-37/AC-38/M7 теперь проверяют managed negative controls и fault до/после terminal-finalize CAS.
- Minimality decision: использовать existing registry lifecycle/archive/CAS semantics; не вводить второй registry deleter, service или dependency.
- Review: fresh R-019 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-019 terminal-gates critique и R-020 remediation

- Changed: T-020 получил E1–E5 exact lease-kind/state/quarantine eligibility, incident-specific semantic dispositions, checkpoint/source/grant retirement и guardian/archive gates; authority-free preservation baseline делает unchanged quarantined Git state recovery-only clean.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; root сверил current lease states, `release_unactivated_reservation`, `release_legacy_terminal`, contained archive/release и единственное containment-loss reconciliation exception. AC-38 теперь покрывает каждый eligible/blocked shape и full mutation→preserve→vacancy→clear flow.
- Minimality decision: terminal-finalize только оркестрирует existing owner lifecycles; ambiguous quarantine не получает нового unlock API.
- Review: fresh R-020 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-020 ordinary-transition critique и R-021 remediation

- Changed: добавлена exhaustive O1–O8 matrix для session/schema, lane/worktree/ref, scope/resource, writer/recovery, integration, version/commit, publication и cleanup; каждый concrete transition требует fresh C1–C5 authority receipt.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, exact terminal success.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; единственный finding root-verified. RQ-37/AC-38 parameterize every transition, expected Git delta/rebarrier и active-incident zero-mutation; AC-30/M7 синхронизируют operator/release docs.
- Minimality decision: один общий receipt/barrier contract вместо отдельных ad hoc publication или scope locks; unknown transition fail-closed.
- Review: fresh R-021 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-021 closure transport failure

- Changed: none.
- Routing: `openbuild_review_sol_high`; configured `gpt-5.6-sol`/high/read-only.
- Validation: invalid terminal evidence — exit `0` and result file were present, but accepted `turn.completed`/observed model evidence was absent; runner classified `event-stream-invalid`.
- Review: semantic result not consumed; exact same-tier fresh retry required.
- Version/files: unchanged; no commit/publication.

### 2026-07-23 — R-021 valid retry critique и R-022 remediation

- Changed: добавлены stable transition-ID registry, exact current RecoveryRegistry writer mapping, durable/external sink completeness gate, B0 prospective epoch/gen-0 bootstrap and separate `O6` commit/`O7` publication acceptance.
- Routing: exact same-tier retry `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, valid `turn.completed`.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; three findings root-verified. AC-38 now rejects every unclassified mutation path, proves concurrent/faulted bootstrap convergence and tests commit separately from push/tag/Release/smoke.
- Minimality decision: registry constant + stdlib call-graph test; no daemon/service/dependency. Bootstrap reuses common-dir owner lock and durable CAS primitives.
- Review: fresh R-022 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-022 sink/bootstrap critique и R-023 remediation

- Changed: hidden read mutations разделены на sink-free reads + explicit drift materialization; persistent checkpoint revalidation, lane registry init и runner prompt stage/GC mapped; runtime guarded sink context specified; BS1–BS4 closes absent-registry incident to one gen-0 project registry.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, valid `turn.completed`.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; root verified eight sink-reachable methods, `_read_registry_locked` quarantine write, persistent source revalidation, prompt durable-write/unlink and workspace-keyed lane initialization. RQ-21/37, AC-20/38 and M1/M7 synchronized.
- Minimality decision: explicit read/write split and transaction context around existing sinks; BS reuses common-dir lock + intent/backlink recovery, no service/dependency.
- Review: fresh R-023 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-023 read/alias/bootstrap critique и R-024 remediation

- Changed: nominal reads now use existing-only non-writing locks/barriers and persisted filesystem Git identity; prompt key creation is stage-only; R observer IDs classify bounded scans; every E lifecycle has BS alias; clean B0 is one composite registry+session gen-0 transition with no BS.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, valid `turn.completed`.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; root verified lock/chmod/fsync/Git spawn and prompt key/reference paths. RQ-21/37, AC-20/30/38 and M1/M7 now cover exact paths, aliases and clean-vs-breach concurrency.
- Minimality decision: refactor read barriers and reuse owner methods via tagged aliases; no duplicate recovery implementation or service.
- Review: fresh R-024 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-024 pre-authority critique и R-025 remediation

- Changed: coordination root/key перенесены в install-time I0 authority; fully durable BA0 публикуется atomic no-replace и становится первым per-project replay/lock anchor; clean B0 и breach BS получают один anchor/epoch. Prompt key creation теперь optional ordinal внутри единственного `O4.prompt-snapshot.stage`; `read_private_source` добавлен к полному набору из восьми sink-free reads.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, valid `turn.completed`.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence; root verified circular pre-receipt common-dir lock, guarded-context/transition-ID contradiction and omitted read method. T-020, RQ-21/37, AC-20/30/38, M1/M7, coverage and risks synchronized.
- Minimality decision: один install-owned local coordinator root и один atomic per-project anchor, без daemon/service/dependency и без opportunistic project-start setup.
- Review: fresh R-025 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: closure и final document validation.

### 2026-07-23 — R-025 setup/identity/key critique и R-026 remediation

- Changed: добавлены bounded in-memory I0 setup bootstrap exception, durable per-project bootstrap capability before the first BA0 sink, permanent atomic-no-replace HMAC key, immutable anchor directory/manifest/lock and separate mutable records. Automatic anchor-lock deletion removed; I0 owns pre-project temp GC.
- Routing: terminal critic `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, valid `turn.completed`.
- Primary signal: not run — specification-only workflow.
- Validation: critic result `GAPS`, high confidence. Root verified `plugin.json` exposes only skills/interface and README install path has no lifecycle hook. Three technical findings applied to T-020/RQ/AC/milestones/risks; install UX separated as D-010.
- Minimality decision: one stdlib owner command and persistent local coordinator primitives; no daemon/service/dependency, key rotation or project-forget capability.
- Review: paused by OpenBuild because D-010 is a material product choice; no new critic dispatch until user answer is fully applied.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: D-010 answer, full propagation, fresh terminal closure and final document validation.

### 2026-07-23 — D-010 option 1a application, R-027

- Changed: every explicit Build entry point now owns idempotent coordinator setup/verification before repository discovery; missing I0 auto-initializes and the requested mode continues, valid I0 is sink-free, insecure/tampered state returns `setup-required`. Standard Codex install commands remain unchanged and no manual setup command or install-hook claim is introduced.
- Decision: user selected D-010 option `1а`; source map, T-020, RQ-21/30/37, AC-30/32/38, observability, rollout, M1/M7, coverage, risks and decision receipt synchronized.
- Primary signal: not run — specification-only workflow.
- Validation: textual propagation check complete; fresh R-027 terminal critic pending.
- Minimality decision: reuse every Build entry point as the supported owner boundary; one shared stdlib setup command, no new plugin manifest capability or service.
- Review: fresh R-027 terminal closure pending.
- Version: current manifest `2.3.6` unchanged.
- Commit/tag/GitHub Release: not created.
- Remaining: terminal closure and final document validation.

### 2026-07-23 — R-027 terminal closure

- Changed: no semantic change; status promoted to `Ready` after successful closure.
- Routing: `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, `turn.completed`, exit `0`, valid result evidence.
- Primary signal: not run — specification-only workflow; future implementation owns AC execution.
- Validation: terminal critic `COVERED`, high confidence; confirmed automatic pre-discovery I0 setup, bounded bootstrap authority, permanent key/immutable locks, BA0/B0/BS convergence, stable sink/read registry, D-009 limitation and M1–M8 ownership.
- Minimality decision: unchanged; local stdlib coordinator, no service/dependency/manual install step.
- Review: readiness closure passed.
- Version: current manifest `2.3.6` unchanged; future implementation targets next compatible minor, expected `2.4.0`.
- Commit/tag/GitHub Release: not created in `new`.
- Remaining: final document integrity/status validation only.

### 2026-07-23 — R-027 refine discovery и R-028 source-graph reconciliation

- Changed: source map expanded to every feature/release/readiness companion reached from SKILL, README, CONTRIBUTING, CHANGELOG and manifests; marketplace/validator ownership and B-023 added. Product behavior and D-001–D-010 remain unchanged.
- Routing: discovery A-025 used packaged `openbuild_search_separate`, configured `gpt-5.3-codex-spark`/low/read-only. Terminal transport succeeded, but `result_evidence=invalid`; no discovery content was consumed and no Terra fallback was eligible. Root recovery used narrow repository ranges and the official SemVer 2.0.0 source.
- Primary signal: not run — specification-only `refine`; future implementation owns AC execution.
- Validation: repository/source reconciliation completed; status changed to Draft because the current semantic revision needs fresh closure.
- Minimality decision: only normative companion sources/manifests were added to the source graph; executable validator/tests remain implementation evidence, avoiding a duplicate product authority.
- Review: fresh R-028 terminal closure pending.
- Version: current manifest `2.3.6` unchanged; future implementation target remains next compatible minor, expected `2.4.0`.
- Commit/tag/GitHub Release: not created in `refine`.
- Remaining: exact read-only R-028 closure and final document integrity validation.

### 2026-07-23 — R-028 critique и R-029 executable-evidence reconciliation

- Changed: added a bounded registry for `agent_runner.py`, `model_map.py`, `recovery_state.py`, `validate_package.py` and `test_validate_package.py`, including incoming discovery edges, inspected owner ranges and explicit product-authority limits; B-023 and reconciliation receipts aligned.
- Routing: A-026 used route step 1/3 `openbuild_review_balanced`, observed `gpt-5.6-terra`/medium/read-only, `turn.completed`, exit `0`, process tree stopped, valid result evidence.
- Primary signal: not run — specification-only `refine`; future implementation owns AC execution.
- Validation: critic result `GAPS`, high confidence; the single source-audit finding was root-verified and corrected without changing D/T/RQ/AC/M tuples.
- Minimality decision: classify executable owners in one evidence registry instead of duplicating their implementation contracts into the normative source map.
- Review: confirmed `coverage-gap` authorizes exactly the next configured critic step for fresh R-029 closure.
- Version: current manifest `2.3.6` unchanged; future implementation target remains expected `2.4.0`.
- Commit/tag/GitHub Release: not created in `refine`.
- Remaining: exact read-only R-029 strong closure and final document integrity validation.

### 2026-07-23 — R-029 strong critique и R-030 interface/discovery/test reconciliation

- Changed: added `agents/openai.yaml` as the explicit-only public invocation authority and bounded evidence rows for `discovery_contract.py`, `test_discovery_contract.py`, `test_agent_runner.py`, `test_model_map.py` and `test_recovery_state.py`; authority limits and incoming edges are explicit.
- Routing: A-027 used route step 2/3 `openbuild_review_strong`, observed `gpt-5.6-terra`/xhigh/read-only, `turn.completed`, exit `0`, process tree stopped, valid result evidence.
- Primary signal: not run — specification-only `refine`; future implementation owns AC execution.
- Validation: critic result `GAPS`, high confidence; the source-audit finding was root-verified against public metadata, imports and validator enforcement, then corrected without changing D/T/RQ/AC/M tuples.
- Minimality decision: extend the same evidence registry and one public-interface row; do not promote test code into product authority or duplicate code contracts.
- Review: confirmed second `coverage-gap` authorizes the final configured high-risk critic step for fresh R-030 closure.
- Version: current manifest `2.3.6` unchanged; future implementation target remains expected `2.4.0`.
- Commit/tag/GitHub Release: not created in `refine`.
- Remaining: exact read-only R-030 Sol/high closure and final document integrity validation.

### 2026-07-23 — R-030 terminal critique и R-031 validator/edge reconciliation

- Changed: added T-021 registry-aware validator contract with M1/M7 and AC-24/38 ownership; made every direct reference/README/changelog edge explicit, including diagrams, LICENSE, pinned release tree and code-scout attribution.
- Routing: A-028 used route step 3/3 `openbuild_review_sol_high`, observed `gpt-5.6-sol`/high/read-only, `turn.completed`, exit `0`, process tree stopped, valid result evidence.
- Primary signal: not run — specification-only `refine`; future implementation owns project-lanes AC execution.
- Validation: terminal critic result `GAPS`, high confidence. Root reproduced `python scripts/validate_package.py` exit `1`: O-class false positive plus the expected specification-only version-gate failure. The false positive is now an explicit TDD red; version remains unchanged intentionally until implementation.
- Minimality decision: fix exact registered transition-token classification in the validator and keep the fixed-model ban, rather than renaming the stable transition registry or weakening the global model regex.
- Review: R-031 semantic inputs changed; fresh current-revision closure required. Prior high-risk complementary/strong/terminal depth remains recorded, so only the required closure pass is repeated.
- Version: current manifest `2.3.6` unchanged; future implementation target remains expected `2.4.0`.
- Commit/tag/GitHub Release: not created in `refine`.
- Remaining: exact read-only R-031 closure and final document integrity validation.

### 2026-07-23 — R-031 fresh closure

- Changed: no semantic change; status promoted from Draft to Ready after successful current-revision closure.
- Routing: A-029 used a fresh resolved route step 1/3 `openbuild_review_balanced`, observed `gpt-5.6-terra`/medium/read-only, `turn.completed`, exit `0`, process tree stopped, valid result evidence.
- Primary signal: not run — specification-only `refine`; future implementation owns AC execution.
- Validation: critic result `COVERED`, high confidence, no findings. Source/interface/evidence graph, D-009/D-010, T-021 ownership, RQ-01–RQ-37, AC-01–AC-38 and M1–M8 are implementation-ready.
- Minimality decision: unchanged; local stdlib coordinator and registry-aware validator classification, no service/dependency/global model-scan weakening.
- Review: readiness closure passed for current semantic revision R-031.
- Version: current manifest `2.3.6` unchanged; future implementation targets the next compatible minor, expected `2.4.0`.
- Commit/tag/GitHub Release: not created in `refine`.
- Remaining: final document integrity/status validation only.

### 2026-07-23 — R-031 final document validation

- Changed: no semantic change.
- Document integrity: strict UTF-8 without BOM, LF-only, zero trailing whitespace, balanced fences; exact sequences D-001–D-010, T-001–T-021, RQ-01–RQ-37, AC-01–AC-38, B-001–B-023 and A-001–A-029; Ready/current-closure/pending-question assertions passed.
- Package signal: `python scripts/validate_package.py` exits `1` with the intentionally recorded T-021 O-class false positive and specification-only unchanged-version gate. Neither is claimed green; M1/M7/AC-24/38 own remediation/version synchronization before release.
- Git: `main`, only `BUILD-parallel-task-lanes.md` is untracked; no commit, push, tag or GitHub Release.
- Remaining for `refine`: none. Future `run` starts at M1 and the TDD/package red signals.

### 2026-07-23 — M1a scaffold, M1b partial и checkpoint-recovery boundary

- Discovery: A-030 exact Spark/low/read-only completed transport with exit `0`, but strict discovery evidence was invalid and not consumed; the run circuit breaker moved to bounded root recovery.
- M1a: A-031 exact balanced implementation completed inside four allowed files. Root focused green was `174/174`; package validation then failed only the expected unchanged-version gate. Handoff was durably finalized as a scaffold, not as complete M1, and registry vacancy was confirmed.
- M1b escalation: A-032 made zero writes and returned one malformed capability-gap escalation line. Root normalized it to configured `capability-gap`, durably rejected the semantic handoff, completed checkpoint invalidation and advanced exactly one route rung.
- M1b timeout: A-033 exact strong implementation made a partial allowed-scope diff but did not terminalize before the immutable 900-second deadline. Automatic cancel proved the complete process tree stopped; no result or handoff was accepted, registry is vacant and an owner-private recovery checkpoint is present.
- Root verification: `python -m unittest scripts.test_project_lanes scripts.test_validate_package -v` exits `0` with `182` tests, but eight Windows behavior tests are skipped because current directory flush fails closed. Direct `ProjectStateStore.ensure_setup()` reproduces `cannot flush Windows private directory`, so the Windows primary signal is not green.
- Package signal: still red beyond the version gate — fixed-model classification remains red in the specification, project owner, validator and validator tests, including an active ordinary-token model-assignment negative fixture. No package success is claimed.
- Git/version: partial diff remains uncommitted on `main`; manifest stays `2.3.6`; no review, version bump, commit, push, tag or GitHub Release occurred.
- Blocker: because A-033 edited before an observation-deadline failure, same-profile retry is ineligible. OpenBuild requires separate explicit one-shot user opt-in before a new checkpoint-bound recovery target writer may continue the same R-031/M1b allowed scope.

### 2026-07-23 — M1b same-scope root completion

- Authority: the user's explicit `run BUILD-parallel-task-lanes` was bound as a one-shot recovery opt-in, but owner revalidation rejected the retained checkpoint before process creation with exact reason `preexisting-dirty-overlap`. The stopped A-033 lifecycle remained vacant with one no-handoff release, so the original R-031/M1b request authorized a durable same-scope `root-completion-authorized` audit over the four previously allowed files.
- Changed: Windows private directory/file creation and mutable replacement now publish already-flushed objects through `MoveFileExW(MOVEFILE_WRITE_THROUGH)`; I0/BA0/B0 setup, capability, anchor, crash-resume and typed observer paths execute on Windows. The validator masks only registry-backed full IDs, code spans, transition-table cells, the closed ordinary range and the literal registry column; model/model-id assignments remain unmasked. Tests construct negative model tokens without making their own source an active package violation.
- Implementation mode: TDD-first, high risk, automatic root completion after failed exact writer; owning layers `project_state.py` durability/state owner and `validate_package.py` package-policy owner.
- Red signal: focused suite initially passed `182` tests with `8` skips and package validation reported transition-token false positives plus the unchanged-version gate. Direct Windows setup reproduced `cannot flush Windows private directory`.
- Focused green: `PYTHONDONTWRITEBYTECODE=1 python -m unittest scripts.test_project_lanes scripts.test_validate_package -v` — `182` passed, one portability-only symlink skip; no managed-Windows behavior skip remains.
- Package/version: manifest, changelog and README pins moved `2.3.6 -> 2.4.0-alpha.1`. `python scripts/validate_package.py` and `git diff --check` pass after preserving Markdown span boundaries while masking packaged-model receipts.
- Minimality decision: reused the existing Windows write-through barrier contract from the recovery owner and stdlib/native APIs; no dependency, service, duplicate registry or weakened fixed-model rule. Upgrade trigger: a platform/filesystem where `MoveFileExW(MOVEFILE_WRITE_THROUGH)` cannot provide the required atomic publication remains fail-closed.
- Review: A-035 exact balanced high-risk review returned `ACCEPT`, high confidence, no findings and no escalation trigger. Reviewer inspected the baseline diff, state owner, focused tests, validator registry/masking logic and synchronized prerelease metadata.
- Broad validation: `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s scripts -p 'test_*.py'` — `425` tests passed with five existing portability/platform skips. The first broad pass exposed one changelog mutation-fixture defect; the corrected dynamic fixture and the final broad rerun are green.
- Remaining: staged commit gate and scoped milestone commit before M2.

### 2026-07-23 — M2 lane/worktree lifecycle и protected-work adoption

- Authority/lifecycle: A-036 exact balanced writer edited only `project_state.py`, new `project_lanes.py` and `test_project_lanes.py`, then reached valid terminal transport. Its tests created three nested Git fixture directories outside the allowed set, so initial terminalization failed closed. Root removed only those generated directories after verifying exact paths and no reparse points; the run then terminalized with full-tree-zero. Root verification reproduced three Windows `anchor.lock` permission errors, so no handoff was accepted. Because the retained checkpoint was ineligible for outside-set drift, the lifecycle was durably `terminal-abandoned`, the registry returned to vacancy, and same-scope root completion was recorded against the original R-031/M2 request and exact three-file attribution.
- Root red/green: the Windows error came from byte-locking immutable `anchor.lock` and reopening it through a second descriptor. M2 now uses a separate stable `state.lock`; immutable anchor bytes remain unchanged. Later review findings produced two additional explicit red cycles: four lifecycle/schema tests first failed with two failures and two errors, and two session/adoption tests first failed two of two; both cycles are green after owner-layer remediation.
- Changed: added generationed lane create/replay across managed branch/ref/worktree identities, authoritative common-directory/integration-ref session binding, exact nested state validation on replace/reload, active-writer attach/cancel convergence, idempotent quarantine/close, verified absent-worktree close, common-directory and path-escape fences, lane-local RecoveryRegistry binding, byte/index/content/mode-bound external protected scopes, and replay-safe `protected -> adoption-intent -> adopted|protected` transitions whose accepted receipt is scope/common/ref-bound.
- Focused: `PYTHONDONTWRITEBYTECODE=1 python -m unittest scripts.test_project_lanes` — `32` tests passed with three portability/platform skips.
- Regression: `PYTHONDONTWRITEBYTECODE=1 python -m unittest scripts.test_project_lanes scripts.test_recovery_state scripts.test_agent_runner` — `237` tests passed with seven portability/platform skips. `python scripts/validate_package.py` and `git diff --check` pass.
- Minimality: stdlib and Git CLI only; no recovery-schema weakening, scheduler, integration queue, dependency, provider or service. Tests use OS temporary directories and leave no repository artifacts.
- Review history: A-037 balanced and A-038 strong findings were remediated before A-039 Sol/high. A-039's six lifecycle/schema findings were reproduced and fixed. Changed-diff A-040 correctly retained the runner bridge and real contained-process fixture as cross-owner blockers; those findings are now closed by the root completion described below.
- Replacement writer: after explicit user authorization, A-041 exact balanced implementation was activated for `agent_runner.py`, its focused tests and the minimum lane-owner integration needed to close the two A-040 findings. It returned semantic `BLOCKED` without modifying any leased file because both system and workspace-local `TemporaryDirectory` creation failed with Windows access denial. Root verified the authoritative M2 Git diff remained exactly `bad661d14e937f5282561a56c674030d32c24b2b`, so no implementation handoff was accepted.
- Replacement lifecycle: A-041 generated two ignored `.pyc` files outside its allowed set, which made the retained checkpoint `recovery-ineligible`. The required blocked rejection therefore failed closed without committing a semantic disposition. The same stopped owner lifecycle was reconciled through exact `terminal-abandoned` for `outside-set-drift`; guardian closure completed, registry returned to exact vacancy, and quarantine is absent.
- Second/final replacement writer: after a host-side writable TEMP/TMP probe, A-042 received exactly the clean `agent_runner.py` and `test_agent_runner.py` lease while the existing M2 diff remained authoritative at `941d54c2f03b658351d3e558872a85d2daef1212`. Its mandatory first sandbox action created a child under the approved workspace temp root but could not write the probe file (`PermissionError`) or clean the child (`WinError 5`), so it stopped before any edit as required. Root durably rejected the semantic `BLOCKED` result, accepted no handoff, confirmed exact registry vacancy/no quarantine and removed only the dedicated ignored temp root.
- Legacy recovery side-case: the user requested coverage for a retained 2.3.6 `normal-contained` lifecycle whose only fresh checkpoint reason is `preexisting-dirty-overlap`. A focused red reproduced `terminal abandonment requires exact outside-set-drift`; owner-derived `terminal-abandonment-v5` now binds the exact stopped-success/zero/source/candidate evidence, invalidates the checkpoint with a distinct reason, closes and releases the same lease without handoff or artificial drift, preserves the changed untracked harness bytes and Git index, reads floor 2.3.6 without rewrite and promotes to 2.4.0 before invalidation.
- Root completion: after exact registry vacancy and preservation of the authoritative M2 diff, root connected `agent_runner.py` to the complete project-lane tuple, lane-local recovery root, pre-prompt CAS attach, isolated quarantine/terminal projection, `waiting-for-integration`, and checkpoint-bound same-lane `recovery-ready`/recovery-target replay. The real acceptance fixture starts two concurrent runner/guardian/fake-Codex process trees, proves distinct live guardian/worker/Codex identities and exact `-C` worktree writes, cancels one lane while the neighbor remains live, and runs an explicitly reserved recovery target in the failed lane. Generated root fixtures and the exact orphan test tree were removed without touching unrelated processes or user work.
- Reviewer remediation: the final read-only strongest review first reproduced post-reconciliation `status` replay attempting a second quarantine. A focused red now proves that audit accepts only the exact reconciliation receipt plus complete release history and rejects drift. The review then found the preserved M1 schema-1 state lacked a migration path; an exact `52fac8a` fixture now reads it without mutation and writes the current form only on the first locked lane-session generation CAS.
- Validation: combined project-lane/runner `184` tests passed with seven skips; project/lane `36` passed with three skips; real process-tree `1/1`, containment replay `4/4`, and migration/sink-free `2/2` passed. Final repository-wide `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s scripts -p 'test_*.py'` passed `462` tests with seven portability/platform skips. Package validation and `git diff --check` are release-gate checks immediately following this milestone update.
- Review closure: native read-only `gpt-5.6-sol`/max review returned `APPROVE`, high confidence `0.94`, complete AC-01/13/14/18/19/21/33 coverage and no actionable findings. Linux cgroup publication remains the existing platform-dependent skip without delegation; scheduling and integration remain M3+.
- Package/version: manifest, changelog, README pins and GitHub-facing alpha notes are accepted at `2.4.0-alpha.2`. The scoped release commit, annotated tag, GitHub prerelease and local reinstall follow the green commit gate; M3 did not start.

### 2026-07-23 — M3a project scope/resource reservation core

- Discovery/routing: A-043 exact Spark discovery completed with invalid semantic evidence and was not consumed. Targeted root recovery selected the R-031 M3 owner/test set. A-044 exact Terra/medium made zero writes and returned canonical `task-complexity-above-tier`; semantic rejection and checkpoint invalidation completed before A-045 advanced one configured rung to Terra/xhigh.
- Implementation lifecycle: A-045 edited only `project_state.py`, `project_lanes.py`, new `project_scopes.py` and `test_project_lanes.py`, then terminalized with valid transport evidence. Root reproduced a simultaneous lane-registration CAS error and declined handoff. Generated ignored scope fixtures created exact outside-set drift, so owner-derived `terminal-abandonment-v1` invalidated the checkpoint, preserved the partial diff, accepted no handoff and restored registry vacancy. The original request then issued a durable same-scope root-completion authorization bound to the exact partial diff.
- TDD: root added a synchronized two-contender red that initially produced `ProjectLaneError: project generation changed`, then bounded CAS retry made the pair converge to one active owner and one `waiting-for-scope`. Further balanced/strong/Sol review reds covered caller-forged release, live expansion, actual cycle-edge selection, durable released-record bypass, final-component link handling, expansion public status and oldest-waiter policy. A-050 then added active-claim deletion/cancellation, granted expansion-to-runner authority and real two-expansion cycle-progress reds. A-051 added a real claimless alpha.2 running-lane migration/overlap fixture, an overlapping-live-legacy no-mutation control and mixed file/contract/resource contained-writer attachment. A-052 added logical-key/dirty-path separation, same-text typed replay binding, migration no-follow and migrated-ticket anti-overtake fixtures. A-053 added protected expansion/migration waiting, pre-admission live-legacy no-mutation and adopted-waiter accepted-base resume. A-054 added claimless protected-waiter crash replay, later accepted integration-tip refresh, exact private-checkpoint file authority for mixed logical scopes and existing-waiter legacy-preflight no-mutation coverage. A-055 added reverse-order crash replay fairness and generic-sink protected intent/adoption rejection with legitimate purpose-specific adoption acceptance; the concurrent observer retry was repeated green five times.
- Changed: M3a adds canonical file/directory/contract/resource hard claims, non-authoritative soft intents, durable generation-CAS reservations, case/ancestor/final-component path guards, bounded concurrent admission retry, monotonic ticket policy, pre-start all-or-wait expansion, inactive-cycle victim selection, scope-wait origin/status replay and active project hard-grant checks before fresh runner binding or contained-writer attach.
- Fail-closed boundary: live-writer expansion, live-cycle cancellation and scope release remain no-mutation blocked in alpha.3. The durable sink rejects every `released` scope record until M3b implements the R-032/T-022 runner safe-stop/rebind and registry-resident integration-owner acceptance handshakes.
- Specification delta: A-047 exposed a cross-owner implementation gap rather than a new product choice. R-032 added outcome-preserving T-022 and expanded the M3 owner/red/green contract; A-048 returned `COVERED`, high confidence, with no D reopen.
- Validation: current project-lanes `61` tests pass with four platform symlink/reparse skips; combined recovery/runner `215` tests pass with four platform skips; package validator contracts pass `175` tests. Final repository-wide discovery passes `488` tests with eight portability/platform skips; package validation, AST parsing and `git diff --check` are green. The prior 180-second controller timeout is superseded by the successful wider runs.
- Minimality: stdlib plus the existing ProjectStateStore generation CAS; no dependency, service, database, hosted scheduler, Git integration or recovery-schema weakening. The separate policy owner is retained; unsafe speculative release authority was removed.
- Review: A-046/A-047/A-049/A-050/A-051/A-052/A-053/A-054/A-055 findings were reproduced and remediated. A-056 fresh changed-diff Sol/high release closure returned `ACCEPT`, confidence `0.97`, with no actionable findings.
- Version/publication: manifest, changelog and README capability text use `2.4.0-alpha.3`. To keep the mandatory README install pin truthful, the validated alpha.3 commit will receive an immutable annotated prerelease tag and GitHub prerelease before M3b starts; this does not mark M3 or stable 2.4.0 complete.
