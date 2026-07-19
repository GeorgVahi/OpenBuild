# Build: безопасная финализация recovery-target с preexisting overlap

- Status: Ready for final exact-tree review and publication
- Last updated: 2026-07-20
- Original request: Исправить реальный OpenBuild 2.2.4 incident, в котором успешно остановленный recovery-writer изменил уже грязные разрешённые файлы и одновременно создал новый файл вне lease. Комбинация `preexisting-dirty-overlap + outside-set-drift` оставила registry non-vacant без штатного terminal outcome; нужен полноценный новый релиз. Follow-up: OpenBuild 2.3.1 не освободил сохранившийся lifecycle, потому что проблемный writer был зарегистрирован как `normal-contained`, а v2 принимал эту пару только для `recovery-target`; нужен безопасный migration/reconciliation и новый релиз без force-unlock.
- Primary signal: owner- и runner-level fixtures воспроизводят обе формы сохранённого partial diff, получают exact reasons `[outside-set-drift, preexisting-dirty-overlap]` и доказуемо завершают тот же lifecycle через v2 для `recovery-target` либо v3 для legacy `normal-contained`; handoff/diff/root authority не принимаются, Git/index/worktree остаются неизменны, а все остальные mixed-наборы и lease kinds остаются fail-closed.
- Review baseline: `main@150f586e7338b4ace92614ab6643c71d5f2f0eda`; исходный status clean (`## main...origin/main`).
- Workflow target: Complete
- Starting phase: discovery
- Specification revision: R-015
- Complexity: high — меняются durable recovery state, downgrade boundary, single-writer release и автоматическая authority boundary.
- Implementation mode: TDD-first — меняются state-machine contracts и наблюдаемое recovery-поведение.
- Version impact: immutable `2.3.0` and `2.3.1` are published; the backward-compatible legacy-normal reconciliation advances the authoritative package to patch `2.3.2` and raises the first-write reader floor from `2.2.5` to `2.3.2` while preserving no-rewrite reads of 2.2.0–2.2.3 and 2.2.5 generations.
- Routing mode: `codex-exec-explicit-model`
- Discovery mode: mixed — exact read-only discovery transport завершился успешно, но вернул несуществующие repository paths; результат классифицирован `unusable-evidence`, затем выполнен один targeted root-recovery без второго search agent.
- Search usage route: separate-pool → targeted root-recovery; circuit breaker открыт для повторного discovery dispatch в этом Build-run.
- Search routing receipt: packaged map `OpenBuild defaults`, SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, step 1/1, exact `openbuild_search_separate`, configured/observed `gpt-5.3-codex-spark`/low/read-only, `turn.completed`, exit 0, valid result, stopped tree; semantic outcome `unusable-evidence`.
- Implementation model route: packaged `implementation.high`; старт `openbuild_implementation_balanced`, дальнейшие steps только по валидному pre-edit trigger.
- Implementation routing receipt: packaged map SHA-256 `fce8589a24dd2dd4fb8b538c91e306f7883bb3a5511f3e4b9605b031191b5e03`, implementation/high; A-007 exact step 1 `openbuild_implementation_balanced` (`gpt-5.6-terra`/medium/workspace-write) completed transport-success under the six-file lease, then exact outside-only drift was terminal-abandoned and the byte-identical six-file checkpoint continued through the existing root-completion authority; no model escalation occurred.
- Review routing receipt: packaged `critic.high`; A-008 exact Balanced and A-009/A-010 exact Strong closed the recovery-specific findings, with A-010 `ACCEPT` 94/100. Combined A-015 accepted recovery-v2 while finding discovery blockers. A-016 accepted recovery AC-01–AC-12/14 and found a result-object gap. A-017 accepted most combined behavior but found pending legacy-v1 completion lacked pre-source floor promotion and structured JSONL had the same non-regular boundary. A-018 accepted recovery-v2 again and found that raw code-bearing JSONL records could bypass the discovery error union. Discovery A-025/A-026 then closed unknown failure types and missing runner/Codex-exit binding. Combined A-019 accepted recovery-v2 but invalidated the review after external drift and found a descriptor TOCTOU gap in JSONL/stderr/result reads; R-012 closed it. Discovery A-028 then found and R-022 closed a source-side fallback-binding injection gap. Combined A-020 accepted the exact 2.3.0 tree 97/100 and it was published. A-031 accepted the zero-exit correction, and immutable 2.3.1 was published at `150f586`. R-015 adds the narrow v3 lifecycle; A-032 exact Balanced independently returned `ACCEPT` 96/100 with high confidence and no finding. A-033 confirmed the required staged tree and no safety finding but rejected publication because the prompt did not bind the `--full-index` flags used for the recorded digest; the canonical digest command is now explicit and a fresh exact-tree review remains required.

## 1. Outcome

### Problem

OpenBuild 2.2.4 разрешает автоматический `terminal-abandonment-v1` только для exact `[outside-set-drift]`. Это сохраняет fail-closed boundary для неизвестных mixed-причин, но не учитывает специальную природу recovery-target: его checkpoint может намеренно начинаться поверх сохранённого partial diff. Если recovery-writer меняет такой уже грязный разрешённый файл, revalidation добавляет `preexisting-dirty-overlap`. Если тот же run создаёт новый файл вне lease, reason set становится exact `[outside-set-drift, preexisting-dirty-overlap]`.

В приложенном реальном trace writer transport-success и full-tree-zero доказаны, handoff не принят, но обычное abandonment отклоняет mixed reasons. `_authorize-recovery` затем не может стартовать из-за занятого registry. Permission пользователя не меняет evidence, а ручное удаление registry/force-unlock запрещено. Результат — безопасное, но необратимо застрявшее lifecycle-состояние.

### Desired behavior

1. Existing exact outside-only `terminal-abandonment-v1` остаётся без изменений.
2. `terminal-abandonment-v2` остаётся разрешён только для recovery-target и только при exact sorted reasons `[outside-set-drift, preexisting-dirty-overlap]`.
3. Новый append-only `terminal-abandonment-v3` разрешает эту exact pair только для legacy `normal-contained` lease, зарегистрированного старым runner без recovery-target kind.
4. V2/V3 никогда не принимают handoff, не создают retry/escalation/grant/new writer и не расширяют producer allowlist. Они только завершают уже остановленный producer lifecycle через существующие identity/zero/invalidation/guardian/archive/release gates; v2 завершает использованную recovery-авторизацию, v3 не фабрикует её.
5. `normal-legacy`, `normal-fallback`, любой `git-control-plane-drift`, unknown/additional reason, live/unknown tree, quarantine, binding mismatch, handoff/outbox или authorization ambiguity остаются no-mutation blocked.
6. После vacancy существующая root-completion authority оценивается отдельно. Abandonment не создаёт root-completion audit, не принимает diff и не меняет Git/workspace; только отдельный root-owned вызов после exact vacancy может независимо доказать same revision/milestone/scope, attribution и risk floor.
7. Public outcome явно различает v1 outside-only, v2 recovery overlap и v3 legacy-normal overlap, не раскрывая raw paths, prompt, registry или capability data.
8. Release 2.3.2 публикуется только после full validation authoritative candidate, clean install/forward smoke и независимого high-risk `ACCEPT` точного staged tree.

### In scope

- Exact v3 semantic disposition, evidence binding, distinct invalidation reason и reader-floor migration при сохранении v1/v2.
- Lease-kind-specific v2/v3 reason classifier и no-mutation negative matrix.
- End-to-end/fault/replay/schema/forward tests в существующих runner/registry owners.
- SKILL, delegation/model/TDD/review/version contracts, validator и mutation tests.
- Manifest 2.3.2, changelog, English/Russian README, contributor/release validation.
- Scoped commit authoritative candidate, push, immutable annotated `v2.3.2` tag и GitHub Release после acceptance gate.

### Out of scope

- Generic mixed-reason abandonment или force-unlock.
- Generic abandonment любого normal writer: v3 ограничен legacy `normal-contained` exact pair и не применим к `normal-legacy`/`normal-fallback`.
- Принятие partial/ambiguous recovery handoff.
- Автоматический replacement recovery writer или расширение writer lease.
- Откат/перезапись пользовательских или внешних workspace changes.
- Новый provider, dependency, hosted automation или model-map change.

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| Drift owner | `plugins/openbuild/skills/build/scripts/recovery_state.py:3681-3745` | `preexisting-dirty-overlap` добавляется, когда path был dirty в pre-snapshot, изменился после snapshot и находится в allowed set. | Это attribution ambiguity, а не process/containment ambiguity. |
| Current gate | `plugins/openbuild/skills/build/scripts/recovery_state.py:5171-5245` | `record_terminal_abandonment` принимает только exact `[outside-set-drift]`. | Реальный recovery-target mixed-case не имеет terminal transition. |
| Completion gate | `plugins/openbuild/skills/build/scripts/recovery_state.py:5247-5367` | Completion повторно требует exact outside-only, invalidates checkpoint, retires recovery authorization и затем разрешает owner release. | V2 должен переиспользовать этот доказательный порядок. |
| Durable validation | `plugins/openbuild/skills/build/scripts/recovery_state.py:817-864,2070-2160` | Semantic schema/history/evidence/invalidation cross-binding проверяются exact. | Новый cause/schema должен быть append-only и replay-safe. |
| Public outcome | `plugins/openbuild/skills/build/scripts/agent_runner.py:3336-3404` | Classifier принимает только completed v1 outside-only evidence. | V2 нужен отдельный privacy-safe result, а не скрытая подмена v1. |
| Runner reconciliation | `plugins/openbuild/skills/build/scripts/agent_runner.py:3590-3640,3893-3910` | Private command продолжает тот же stopped lifecycle, не принимает caller cause и пишет abandonment receipt. | Caller не получает generic cause/force input. |
| Existing positive | `scripts/test_recovery_state.py:2783-2881`; `scripts/test_agent_runner.py:2356-2520` | V1 outside-only проходит full no-handoff release trace. | Регрессия v1 запрещена. |
| Existing negative | `scripts/test_recovery_state.py:2883-2920` | `git-control-plane-drift + outside-set-drift` отклоняется byte-for-byte. | Этот mixed-case и post-commit owner path остаются неизменны. |
| Overlap detection | `scripts/test_recovery_state.py:1724-1750` | Отдельный тест доказывает preexisting dirty overlap. | Не хватает recovery-target end-to-end terminal fixture. |
| Static owner | `scripts/validate_package.py:3206-3292,4258-4317,4397-4410,4589-4597` | Validator фиксирует exact outside-only prose/runtime tokens и floor 2.2.3. | Release обязан синхронно обновить contracts и floor. |
| Release policy | `CONTRIBUTING.md:14-31,87-96`; `plugins/openbuild/.codex-plugin/plugin.json:1-4` | Manifest authoritative; каждый commit повышает версию и синхронизирует changelog/READMEs; tag/Release immutable. | Target — один reviewed 2.3.2 patch commit/tag/Release без изменения опубликованных v2.3.0/v2.3.1. |

### Source of truth

`RecoveryRegistry.record_terminal_abandonment`/`complete_terminal_abandonment` владеют durable semantic transition. `reconcile_implementation_registry` владеет terminal orchestration. `SKILL.md` и implementation/model/TDD/review/version references владеют user-facing authority, validation и release contract. Исправление не должно жить только в prose или downstream exception handling.

### Specification source map

| Source | Authority/owner | Status/revision | Normative scope and decisions | Outgoing normative links | Editable | Reconciliation |
|---|---|---|---|---|---|---|
| `BUILD-recovery-overlap-terminalization-2.3.0.md` | current user + repository root spec | R-015 In progress | D-001–D-011, T-010–T-016, AC-01–AC-16 | all current owners below | yes | root |
| `BUILD-recovery-autonomy-2.2.2.md` | accepted historical user decision record | Complete R-005 | D-001–D-004; no useless prompt/new writer/force-unlock, exact outside-only v1 | its closed source graph at Sections 2–3; current editable owners mapped below | no | conflict narrowed by new evidence and D-009 |
| `BUILD-terminal-finalization-2.2.3.md` | accepted historical user decision record | Complete R-008 | D-005–D-008; v1 exact outside-only, explicit post-commit mixed path | its closed source graph; current editable owners mapped below | no | aligned: git-control-plane mixed path unchanged |
| `plugins/openbuild/skills/build/SKILL.md` | packaged workflow owner | package 2.2.4 | lifecycle/authority/reporting | implementation/model/TDD/minimality/review/version references | yes | gap: v2 recovery-overlap route absent |
| `plugins/openbuild/skills/build/references/implementation-delegation.md` | single-writer/terminal order owner | 2.2.4 | D-001–D-003, recovery target and root completion | model routing/TDD | yes | gap: exact mixed remains blocked |
| `plugins/openbuild/skills/build/references/model-routing.md` | exact route owner | 2.2.4 | no transport fallback/new writer | implementation/review | yes | aligned; terminalization is not routing |
| `plugins/openbuild/skills/build/references/tdd-workflow.md` | behavioral test owner | 2.2.4 | red/green recovery traces | delegation/minimality | yes | gap: real recovery overlap trace absent |
| `plugins/openbuild/skills/build/references/minimality-protocol.md` | technical minimality owner | 2.2.4 | owner-layer/no fallback | none in scope | yes | aligned |
| `plugins/openbuild/skills/build/references/review-protocol.md` | high-risk acceptance owner | 2.2.4 | recovery acceptance gates | TDD/minimality/versioning | yes | gap: v2 matrix absent |
| `plugins/openbuild/skills/build/references/versioning.md`, `CONTRIBUTING.md` | release/version owner | current | version/floor/same-commit/publication | manifest/changelog/READMEs | yes | gap until 2.3.0 validation/release |
| `README.md`, `README.ru.md`, `CHANGELOG.md`, manifest | public behavior/version record | 2.2.4 | installation/recovery/release | version contract above | yes | gap until release |

Repository and installed 2.2.4 copies of `SKILL.md` and all mapped references have identical SHA-256 values. Historical source graphs were read and remain frozen; this task changes only their current editable owners.

### Source reconciliation receipts

| Conflict | Resolution basis | Authority | Result |
|---|---|---|---|
| D-003/T-003 exact outside-only v1 vs real recovery-target overlap | keep v1 unchanged; add separate v2 restricted to recovery-target exact pair | D-009, current explicit request and owner evidence | aligned after v2 implementation |
| Mixed attribution vs lease release | release producer with no handoff; evaluate root completion separately after vacancy | D-001/D-003/D-009, T-012 | aligned |
| Publication boundary | user explicitly requested a full new release; tag/Release remain gated by green validation and independent ACCEPT | D-010 | aligned |

### Gap

Опубликованный v2 закрывает exact recovery-target `[outside-set-drift, preexisting-dirty-overlap]`, но legacy 2.3.1 registry может содержать тот же доказанный stopped lifecycle как `normal-contained`. Evidence достаточно, чтобы безопасно закрыть producer без handoff, однако v2 lease-kind gate отклоняет его и удерживает registry. Нужен отдельный v3 outcome, а не ослабление v2 или ручной unlock.

## 3. Decision memory

### User-owned decisions

| ID | Decision key | Status | Selected outcome | Evidence | Consequence |
|---|---|---|---|---|---|
| D-001 | `automation.failure.root-remediation` | resolved/preserved | original Build request даёт bounded root-only same-scope authority после vacancy | accepted 2.2.2 record | не разрешает replacement writer |
| D-002 | `authorization.recovery-writer` | resolved/preserved | новый recovery writer остаётся explicit one-shot opt-in, eligible/vacant only | accepted 2.2.2 record | terminalization не создаёт writer |
| D-003 | `automation.fail-closed-boundary` | resolved/reconciled | unknown mixed reasons, live/containment/ownership ambiguity и force-unlock запрещены; exact pair имеет отдельные lease-kind-bound v2/v3 outcomes из D-009/D-011 | accepted 2.2.2 record + оба incident trace | no generic mixed unlock |
| D-004 | `workspace.orchestration-artifacts` | resolved/preserved | owner-private artifacts outside workspace | accepted 2.2.2 record | no prompt/private data leak |
| D-005 | `compatibility.terminal-binding-upgrade` | resolved/preserved | prior released formats read safely without rewrite | accepted 2.2.3 record | v1/current paths remain compatible |
| D-006 | `recovery.completed-postcommit` | resolved/preserved | git-control-plane + outside post-commit state uses separate explicit owner path | accepted 2.2.3 record | v2 does not absorb post-commit flow |
| D-007 | `authorization.postcommit-remediation-entrypoint` | resolved/preserved | exact private capability flow for post-commit only | accepted 2.2.3 record | unrelated to recovery-target v2 |
| D-008 | `authorization.local-owner-principal` | resolved/preserved | current OS account is owner principal within documented threat model | accepted 2.2.3 record | no stronger chat-provenance claim |
| D-009 | `automation.recovery-target-overlap-abandonment` | resolved/preserved | exact stopped recovery-target pair `[outside-set-drift, preexisting-dirty-overlap]` closes through v2 without handoff/new writer | initial incident and published 2.3.0 behavior | v2 remains recovery-target-only |
| D-010 | `release.publish-authoritative-candidate` | resolved/reconciled | after green validation and independent exact-tree ACCEPT, publish the current authoritative 2.3.0 main commit, immutable annotated tag `v2.3.0` and GitHub Release | current request: “сделать полноценный новый релиз”; concurrent user-authorized 2.3.0 candidate on disk | no rollback to 2.2.5 and no publication of an unreviewed mixed tree |
| D-011 | `automation.legacy-normal-overlap-reconciliation` | resolved | exact stopped `normal-contained` pair `[outside-set-drift, preexisting-dirty-overlap]` closes through distinct v3 without diff acceptance, fabricated recovery authorization or force-unlock; publish immutable 2.3.2 after full gates | 2.3.1 follow-up incident and explicit request for another release | unblocks the retained legacy lease while preserving v2 and generic fail-closed behavior |

### Technical decision ledger

| ID | Mechanism | Status | Evidence/alternatives | Preservation proof |
|---|---|---|---|---|
| T-010 | Add append-only `terminal-abandonment-v2` with cause `outside-set-drift-with-preexisting-dirty-overlap`, same closed field set and owner-derived evidence digest. It is selectable only when `lease_kind=recovery-target` and revalidation returns the exact sorted pair. | selected | Extending v1 would hide a new durable semantic from old readers; generic mixed cause is too broad. | D-003/D-009; v1 and post-commit paths unchanged. |
| T-011 | Add exact invalidation reason `terminal-abandoned-recovery-overlap`; the first durable registry/source commit performed by 2.2.5 code raises reader floor to 2.2.5, matching the existing owner-wide `_commit_*` policy, while 2.2.0–2.2.3 floors load without rewrite. | selected | Pending v2 cannot be safely completed by 2.2.4 code; a mixed-only floor would contradict the current shared durable owner. | Explicit downgrade failure is safer than implicit partial interpretation. |
| T-012 | Root completion remains a separate post-vacancy audit; v2 terminal evidence never becomes diff acceptance or scope expansion and cannot itself create `root-completion-authorized`, mutate Git/workspace or invoke the audit owner. | selected | Existing `_record-root-completion` owner is callable only after vacancy; explicit absence/ordering coverage prevents an implementation from silently coupling it to abandonment. | D-001–D-003/D-009 and user changes preserved. |
| T-013 | One 2.3.0 release commit synchronizes the authoritative combined runtime/tests/contracts/manifest/changelog/READMEs; publication uses repository-native tag and GitHub Release after clean candidate validation. | selected/reconciled R-004 | A separate 2.2.5 commit would overwrite or strand the current authorized minor candidate; no new dependency or provider is introduced by this recovery fix. | D-010 and immutable tag policy preserved. |
| T-014 | Final publication binds review to one exact staged Git tree: root stages only task-owned paths, records `git write-tree` plus the canonical digest from `git diff --cached --binary --no-ext-diff | git hash-object --stdin`, runs a fresh final reviewer over that exact snapshot, forbids any post-review file/index mutation, creates the commit from the unchanged index, then proves `commit^{tree}` equals the reviewed tree and tag/Release resolve to that commit. | selected | Tag→commit alone does not prove review→commit identity. A final exact-tree review after all specification/log reconciliation closes the publication chain. | D-010, immutable tags and all reviewed acceptance evidence are preserved. |
| T-015 | Add append-only `terminal-abandonment-v3` with cause `legacy-normal-outside-set-drift-with-preexisting-dirty-overlap`, selectable only for `normal-contained` plus the exact sorted pair; bind it to distinct invalidation `terminal-abandoned-legacy-normal-overlap`. | selected | Reclassifying the lease as recovery-target would fabricate ownership/authorization evidence; widening v2 would erase the durable lease-kind distinction. | D-003/D-011; v1/v2 and post-commit paths unchanged. |
| T-016 | Read exact floors 2.2.0–2.2.3 and 2.2.5 without rewrite, then promote to reader floor 2.3.2 before the first new registry/source write. | selected | Existing 2.3.1 stuck registries advertise 2.2.5; v3 state must fail closed under older readers and must never expose a new source generation behind a legacy advertised floor. | D-011, no force-unlock and durable forward-only migration. |

Pending proposals: none. D-011 is explicitly resolved by the current follow-up request; no blocking product choice remains.

## 4. Scenarios and edge cases

### Primary recovery-target scenario

1. A failed source attempt leaves attributable partial changes in the allowed set.
2. User authorizes one exact recovery-target over that checkpoint.
3. Recovery writer changes a pre-dirty allowed file and creates a new path outside its lease, then terminalizes with transport success and authenticated full-tree zero.
4. Handoff remains unaccepted. Revalidation returns exact `[outside-set-drift, preexisting-dirty-overlap]`.
5. Private same-lifecycle reconciliation records v2, permanently invalidates the checkpoint, retires the consumed recovery authorization, closes guardian/archive and releases registry.
6. V2 returns with vacancy and no root-completion audit, accepted diff or Git/workspace mutation.
7. Root may separately invoke the existing audit owner, independently review attribution and either complete the same scope under existing authority or report a factual blocker; no new writer starts automatically.

### Errors

- Same pair on a stopped, fully bound legacy `normal-contained` → v3 invalidation/guardian/archive/release with no handoff, diff acceptance or root authority.
- Same pair on `normal-legacy` or `normal-fallback` → blocked without mutation.
- Pair plus `git-control-plane-drift` or any unknown/additional reason → blocked, no mutation.
- Outside-only → unchanged v1.
- Git-control-plane + outside post-commit legacy state → unchanged explicit `terminal-root-completion-v1`.
- Preexisting overlap without outside drift → blocked; no reason to abandon producer through this path.
- Live/unknown tree, quarantine, binding/guardian/source/authorization mismatch or outbox/handoff → blocked.
- Crash after v2 pending, source invalidation, completion or guardian close → exact replay resumes once.
- Downgrade a non-vacant floor-2.3.2 state → fail-closed; exact 2.2.0–2.2.3 and 2.2.5 floors load without rewrite.

## 5. Acceptance criteria

- [x] AC-01: End-to-end runner fixture reproduces the supplied recovery-target partial-diff + outside-file trace and reaches registry vacancy without handoff, new writer or user prompt.
- [x] AC-02: V2 registration requires `lease_kind=recovery-target`; v3 requires `lease_kind=normal-contained`; both require exact sorted reasons `[outside-set-drift, preexisting-dirty-overlap]`, and caller cannot provide cause/reasons/digest/force.
- [x] AC-03: The same pair on `normal-legacy`/`normal-fallback`, or any additional/unknown/git-control-plane reason, rejects before mutation with registry/source bytes unchanged.
- [x] AC-04: V1 exact outside-only behavior, evidence, invalidation and public outcome remain green and byte-compatible.
- [x] AC-05: V2 changes terminal success to false, creates no handoff/outbox/retry/escalation/grant, permanently invalidates the checkpoint with the v2 reason and retires the consumed recovery authorization.
- [x] AC-06: V2 uses existing exact run/lease/source/allowed-set/terminal/zero/candidate identity bindings, guardian close and validated terminal archive before release.
- [x] AC-07: Exact-schema mutation and fault/reload tests cover wrong v2/v3 schema/cause/lease kind/reason tuple/digest/binding and every durable phase with one event/invalidation/archive/release.
- [x] AC-08: Public closed result distinguishes completed v1, v2 and v3 through allowlisted schema/cause tokens and leaks no private path/prompt/registry/capability data.
- [x] AC-09: Reader fixtures load exact 2.2.0–2.2.3 and 2.2.5 floors without rewrite, raise to 2.3.2 on the first new write, reject unsafe downgrade and replay a pending abandonment exactly once.
- [x] AC-10: Static validator and mutation tests require the same lease-kind-specific v2/v3 boundary across runtime, SKILL, implementation/model/TDD/review/version contracts.
- [x] AC-11: Manifest, changelog and both READMEs agree at 2.3.2, document v3 and the floor-2.3.2 downgrade implication, preserve v1/v2 and zero-exit behavior, and do not rewrite v2.3.0/v2.3.1 history.
- [x] AC-12: Focused tests, full suite, package validator, diff/commit gate, clean plugin install and realistic forward smoke pass.
- [ ] AC-13: Fresh high-risk progressive review returns `ACCEPT` with complete coverage and no actionable finding. After all final spec/log reconciliation, one fresh reviewer accepts the exact staged tree/diff identity; no file/index mutation occurs before commit, `commit^{tree}` equals the reviewed tree, and push/tag/GitHub Release are verified against that commit.
- [x] AC-14: V2 end-to-end reconciliation leaves no `root-completion-authorized` record/artifact, accepted diff, Git/index/worktree mutation or root workspace write. The existing separate root-owned audit fails before vacancy; after vacancy a fixture supplies a canonical independently computed verification/diff-attribution receipt digest and proves the owner records exactly those hashes, without claiming that runtime recomputes repository attribution.
- [x] AC-15: V3 owner/runner fixtures start from a legacy floor-2.2.5 `normal-contained` lifecycle, produce the exact distinct schema/cause/invalidation, preserve workspace contents and Git status/binary diff/index bytes, create no handoff/root authority, close the guardian/archive, and release the registry.
- [ ] AC-16: Exact reviewed 2.3.2 commit is pushed, annotated tag and public GitHub Release resolve to it, and a clean remote-tag install is source/cache byte-equal.

### Invariants

- One active writer; root does not write while the implementation lease is non-vacant.
- No accepted ambiguous/partial handoff and no synthetic zero-write proof.
- No force-unlock, live/unknown release, transport-driven replacement or automatic recovery writer.
- No raw private paths, prompts, nonces, capabilities or logs in public output/spec/release.
- Unrelated/user changes are preserved and never attributed automatically.
- Git/version/publication remain root-owned after vacancy and review.

## 6. Technical boundaries

- Runtime: `plugins/openbuild/skills/build/scripts/recovery_state.py`, `agent_runner.py`.
- Tests: `scripts/test_recovery_state.py`, `scripts/test_agent_runner.py`.
- Static: `scripts/validate_package.py`, `scripts/test_validate_package.py`.
- Workflow docs: `SKILL.md`, implementation/model/TDD/review/version references.
- Release: manifest, changelog, README/README.ru and this specification.
- Data migration: owner-private forward transition from legacy floor 2.2.5 to 2.3.2 on the first durable write only; no rewrite-on-read, workspace schema or backfill.
- Security/privacy: v2/v3 narrow by exact lease kind and reason set; all current containment, stable-object, private-state and output boundaries remain.
- Performance/concurrency: existing bounded registry/source locks and idempotent phases; no polling/service/dependency.
- Rollback: code rollback is safe only before a 2.3.2 durable write or after exact vacant retirement; a non-vacant floor-2.3.2 registry must not be opened by 2.3.1 or earlier.

## 7. Validation and review

- Primary signal: AC-01 end-to-end trace plus AC-03 no-mutation negatives and AC-07/AC-09 fault/forward matrices.
- Red signal: new recovery-target fixture on current 2.2.4 fails at `terminal abandonment requires exact outside-set-drift` and retains the stopped lease.
- Minimality decision: custom owner-layer extension — reuse current abandonment/invalidation/retirement/guardian/archive/release owners; skip service, dependency, generic cause, public force API and new writer route.
- Focused green: `python -m unittest scripts.test_recovery_state scripts.test_agent_runner scripts.test_validate_package -v` with `PYTHONDONTWRITEBYTECODE=1` during any active lease.
- Wider: `python -m unittest discover -s scripts -p "test_*.py" -v`; `python scripts/validate_package.py`; `git diff --check`.
- Commit gate: `git diff --cached --check`; `python scripts/validate_package.py --commit-gate`.
- Runtime: clean local plugin install and realistic mixed recovery-target forward smoke.
- Starting/final review tier: packaged high-risk route starts Balanced; advance only on concrete configured findings; final ACCEPT at a proven eligible tier.

## 8. Milestones

### M1. Exact v2 runtime and RED/GREEN

- Status: Complete
- Implementation mode: TDD-first
- Delegation: bounded-worker; step 1 exact `openbuild_implementation_balanced` (`gpt-5.6-terra`/medium/workspace-write), lease `recovery-overlap-2.2.5-m1`, exact six-file allowlist below; no spec/version/docs/Git.
- Allowed worker files: `plugins/openbuild/skills/build/scripts/recovery_state.py`, `plugins/openbuild/skills/build/scripts/agent_runner.py`, `scripts/test_recovery_state.py`, `scripts/test_agent_runner.py`, `scripts/validate_package.py`, `scripts/test_validate_package.py`.
- Forbidden: this specification, manifest/changelog/READMEs/workflow prose/Git.
- Red/green: AC-01–AC-10 focused suite.
- Minimality: append-only owner transition; no new component.
- Acceptance: AC-01–AC-10, AC-14.

### M2. Contracts, version, docs and release

- Status: Complete for immutable 2.3.0/2.3.1 publication
- Implementation mode: Direct for synchronized prose/version; TDD-first for any validator correction.
- Delegation: root-only after M1 exact vacancy; reviewers read-only.
- Scope: workflow docs, R-009 spec reconciliation, authoritative manifest 2.3.0, changelog, README parity, full combined validation, clean install/forward smoke, exact-tree review, commit/push/tag/Release.
- Acceptance: AC-10–AC-14.

### M3. Legacy normal v3 migration and 2.3.2 release

- Status: Ready for final exact-tree review
- Implementation mode: TDD-first owner/runner behavior; direct synchronized contracts/version/docs.
- Delegation: native root implementation; fresh read-only review required before publication.
- Scope: v3 owner transition, normal-contained runner reproduction, 2.2.5 no-rewrite migration, static mutation contracts, manifest/changelog/README parity, full validation, clean local/remote install, exact-tree commit/push/tag/Release.
- Acceptance: AC-02–AC-12, AC-15–AC-16.

## 9. Coverage and risks

### Coverage ledger

| ID | Concern | Status | Disposition | Evidence/decision |
|---|---|---|---|---|
| B-001 | outcome/scope/non-goals | covered | product decision | D-009/D-010, AC-01–AC-14 |
| B-002 | actors/permissions/authority | covered | product decision | D-002/D-003/D-008–D-010 |
| B-003 | primary/error/recovery flows | covered | technical decision | scenarios, T-010–T-012 |
| B-004 | accessibility/localization/responsive UI | not applicable | repository fact | CLI/plugin; EN/RU docs covered AC-11 |
| B-005 | ownership/contracts/source of truth | covered | repository fact | runtime owner evidence and source map |
| B-006 | data/schema/migration/retention | covered | technical decision | T-010/T-011, AC-05–AC-09 |
| B-007 | security/privacy/abuse | covered | product + technical | exact lease/reason boundary, existing containment/privacy invariants |
| B-008 | concurrency/ordering/idempotency | covered | technical decision | AC-06/AC-07, existing locks/phases |
| B-009 | integrations/timeouts/partial failure | covered | technical decision | stopped-tree/guardian/fault matrix |
| B-010 | compatibility/rollout/rollback | covered | product + technical | T-011/T-013/T-014, AC-04/AC-09/AC-11–AC-14 |
| B-011 | observability/support/docs | covered | technical decision | AC-08/AC-10/AC-11 |
| B-012 | acceptance/testability/minimality/cost | covered | technical decision | RED/GREEN, AC-14 absence/ordering proof and no-dependency owner extension |
| B-013 | integrations/external publication | covered | product + technical | D-010/T-014, AC-13 exact reviewed-tree release chain |
| B-014 | preexisting dirty attribution | covered | product + technical | D-009/T-012, AC-14 executable absence/ordering and exact-record proof; terminal release separated from diff acceptance |

### Risk register

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| V2/V3 become generic mixed force-unlock | medium/critical | exact lease-kind routing + exact reason tuple + mutation negatives | planned AC-02/03/07/15 |
| Root accepts preexisting user diff after release | medium/critical | separate post-vacancy attribution gate; no handoff/outbox | planned AC-05/T-012 |
| Old reader partially interprets pending v3 | medium/high | floor 2.3.2, promotion-before-source and downgrade tests | planned AC-09/15 |
| V1/post-commit paths regress | medium/high | byte-compatible v1 and mixed-git regression tests | planned AC-03/04 |
| Prose/runtime/version diverge | medium/high | validator mutations, same-commit sync, clean install | planned AC-10–AC-12 |
| Release points to unreviewed commit | low/critical | tag/Release only after exact review and commit/tag SHA verification | planned AC-13 |

### Decision application receipt

| Decisions | Source | Applied sections | Preserved | Open |
|---|---|---|---|---|
| D-001–D-008 | accepted historical specifications | outcome, boundaries, scenarios, ACs, invariants | no writer/force/private leak/post-commit changes | none |
| D-009 | current supplied incident and explicit fix request | desired behavior, T-010–T-012, AC-01–AC-10, M1, risks | D-001–D-008 and generic fail-closed boundary | none |
| D-010 | current “полноценный новый релиз” request | scope, T-013, AC-11–AC-13, M2 | immutable tags and validation/review gates | none |
| D-011 | current 2.3.1 legacy-normal incident and new-release request | desired behavior, T-015/T-016, AC-02–AC-12/15/16, M3 | v1/v2, no handoff/root authority/force-unlock and immutable prior tags | none |

### Readiness critic log

| Revision | Perspective/tier | Verdict | Findings | Adjudication |
|---|---|---|---|---|
| R-001 | product/operator UX, balanced | COVERED/high confidence | none; B-001–B-014 covered | no change; no trigger or reopen |
| R-001 | architecture/data/security, balanced | COVERED/high confidence | none; exact lease/reason/floor/retirement boundaries covered | no change; no trigger or reopen |
| R-001 | reliability/validation, strong | GAPS/high confidence; `coverage-gap` | NEW root-attribution absence/ordering proof | applied as selected T-012, AC-14, primary scenario and B-014 in R-002; no decision reopen |
| R-002 | final closure, Sol/high | GAPS/high confidence; `coverage-gap`, `unresolved-contradiction` | AC-14 missing from milestones/source map; audit matcher overclaim; review→commit identity gap; inconsistent floor/proposed decisions | applied in R-003 through corrected source/milestones, honest root-owned audit contract, selected T-010–T-014 and exact staged-tree release binding |
| R-003 | fresh final closure, Sol/high | COVERED/high confidence; triggers none | none; B-001–B-014 closed, no reopen | Ready; runtime/acceptance/release gates remain pending |

## 10. Open questions

Blocking product questions: none.

Non-blocking assumptions:

- GitHub CLI or an equivalent authenticated maintainer path is available for the authorized Release; otherwise commit/tag/push can complete, but GitHub Release remains explicitly reported as blocked rather than falsely claimed.
- The authoritative on-disk target is 2.3.0; no separate 2.2.5 tag or rollback is permitted. Reader floor 2.2.5 remains the durable recovery compatibility boundary.

## 11. Agent activity ledger

Created logical agent runs: `20`.

| Run | Role/task | Actual model | Effort | Status/outcome | Work/mapping |
|---|---|---|---|---|---|
| A-001 | search / mixed-recovery-release-discovery | `gpt-5.3-codex-spark` | low | completed transport / `unusable-evidence` | identified relevant owners but cited nonexistent repository paths; targeted root-recovery supplied authoritative Section 2 evidence |
| A-002 | critic / recovery-overlap-r001-product-ux-critic | `gpt-5.6-terra` | medium | completed / COVERED, high confidence | verified D-009 narrow reopening, operator outcomes and release authority; B-001–B-014 |
| A-003 | critic / recovery-overlap-r001-architecture-critic | `gpt-5.6-terra` | medium | completed / COVERED, high confidence | verified exact v2 schema/floor/retirement/no-mutation design; B-001–B-014 |
| A-004 | critic / recovery-overlap-r001-strong-closure | `gpt-5.6-terra` | xhigh | completed / GAPS, high confidence | found missing executable proof that v2 does not create root-completion authority or accept diff; R-001 → R-002 AC-14 |
| A-005 | critic / recovery-overlap-r002-sol-closure | `gpt-5.6-sol` | high | completed / GAPS, high confidence | found AC/milestone mapping, audit overclaim, reader-floor and review→release identity gaps; R-002 → R-003 |
| A-006 | critic / recovery-overlap-r003-sol-closure | `gpt-5.6-sol` | high | completed / COVERED, high confidence, READY | closed B-001–B-014 with no gap/reopen/trigger; R-003 Ready |
| A-007 | implementation / recovery-overlap-2.2.5-m1-implementation | `gpt-5.6-terra` | medium | completed transport / terminal-abandoned outside-only, then root-completed same scope | implemented the exact v2 owner transition and focused tests in six allowlisted files; root corrected one fixture persist error, removed unsupported floor 2.2.4 compatibility and added runner-level AC-14/replay proof |
| A-008 | review / recovery-overlap-2.2.5-m1-review-balanced | `gpt-5.6-terra` | medium | completed / REVISE, high confidence | found missing v2-specific mutation, recovery-target additional-drift, durable fault and pending-v2 downgrade coverage; all findings remediated |
| A-009 | review / recovery-overlap-2.2.5-m1-review-strong | `gpt-5.6-terra` | xhigh | completed / REVISE, high confidence | confirmed A-008 closure; found missing explicit post-vacancy root-audit record proof and stale 57/57 execution count; both remediated |
| A-010 | review / recovery-overlap-2.2.5-m1-strong-closure | `gpt-5.6-terra` | xhigh | completed / ACCEPT 94/100, high confidence | verified AC-01–AC-10 and AC-14, both earlier review remediations, minimality and v1 preservation; no actionable M1 finding |
| A-011 | search / combined-recovery-smoke | `gpt-5.3-codex-spark` | low | completed transport / invalid nested evidence | exposed that canonical search prose did not explicitly require flat evidence arrays; validator failed closed |
| A-012 | search / combined-recovery-smoke-r2 | `gpt-5.3-codex-spark` | low | completed transport / invalid range evidence | confirmed flat evidence after remediation and exposed an over-wide line range; validator failed closed |
| A-013 | search / combined-recovery-smoke-r3 | `gpt-5.3-codex-spark` | low | completed transport / stale fingerprint | concurrent Spark specification write changed the full inventory during the run; result was not consumed |
| A-014 | search / combined-recovery-smoke-r4 | `gpt-5.3-codex-spark` | low | completed / valid evidence | exact Spark/low/read-only route returned valid strict evidence with an unchanged full fingerprint |
| A-015 | review / combined-release-230-preclose-sol-review | `gpt-5.6-sol` | high | completed / REVISE 84/100, high confidence | accepted recovery-v2; found missing fallback-claim parent durability, permissive fingerprint scalar types and absent checked-out-submodule dirty content; all three remediated in R-006/R-013 |
| A-016 | review / combined-release-230-r016-sol-closure | `gpt-5.6-sol` | high | completed / REVISE 87/100, high confidence | exact tree `baa5f4ad945820eb5858f0898270bb1e744b15d3`; accepted recovery AC-01–AC-12/14 and found a non-regular result-object discovery gap; concurrent unstaged drift rejected the tree |
| A-017 | review / combined-release-230-r017-sol-closure | `gpt-5.6-sol` | high | completed / REVISE 79/100, high confidence | exact tree `7a401342242413bee48f9ce01257f2bd13eff220`; found non-regular structured JSONL and floor-2.2.3 pending-v1 replay gaps; both remediated in R-009/R-018 |
| A-018 | review / combined-release-230-r018-sol-closure | `gpt-5.6-sol` | high | completed / REVISE 88/100, high confidence | exact tree `3f2358f57cf57f1b2ba450345d92798b34645177`; accepted recovery-v2 and found that a code-bearing non-error JSONL event could be omitted from the discovery error union; concurrent index drift invalidated the reviewed release tree |
| A-019 | review / combined-release-230-r011-sol-closure | `gpt-5.6-sol` | high | completed / REVISE 76/100, high confidence | exact tree `c6dfca15df11bc6616ceb20e0bcf67be696b2f96`; accepted recovery-v2 and found JSONL/stderr/result check/open/read replacement could bypass no-follow checks; external test drift independently invalidated the review identity |
| A-020 | review / release-230-exact-tree-final | `gpt-5.6-sol` | high | completed / ACCEPT 97/100, high confidence | exact tree `d2488c4306edad96acf88643f8d75db5e1c6b4a1`; no recovery, discovery, validation, documentation or publication blocker; immutable 2.3.0 publication followed |
| A-032 | review / legacy-normal-v3-pre-final-review | `gpt-5.6-terra` | medium | completed / ACCEPT 96/100, high confidence | independently reviewed the full 2.3.2 diff; confirmed exact v3 kind/cause/invalidation, floor promotion, no fabricated authorization/handoff/root authority, v1/v2 preservation, docs/version parity and no actionable finding; read-only sandbox could not create temp fixtures, so root full-suite evidence remains authoritative |
| A-033 | review / legacy-normal-v3-exact-tree-final | `gpt-5.6-terra` | medium | completed / REJECT 0/100, high confidence; `release-identity` | independently reconstructed and matched staged tree `0da592e9ea55757694c7e75fbb298f8d2e8850f3`, confirmed no unstaged task change or additional safety finding, but rejected because the required digest used undocumented `--full-index` while the reviewer derived the canonical no-ext-diff digest; T-014 now fixes the exact command and requires a fresh snapshot |

Pre-spawn dispatch failures: one combined-review dispatch was rejected because `--specification-revision` is implementation-only; the same owner-private prompt was then dispatched without that option, creating A-015 and no extra agent.

## 12. Execution log

### 2026-07-19 — discovery and R-001 draft

- Repository baseline clean on `main@7f92d4603f2eb3a2e434415c20bcf48b879dd3a3`, ahead of origin by two existing 2.2.3/2.2.4 commits.
- Exact discovery A-001 was transport-green but semantically unusable; circuit breaker opened and one targeted root-recovery localized the exact owner/test/release surfaces.
- Historical 2.2.2/2.2.3 decision records and all current workflow references were read; current repo/installed 2.2.4 hashes match.
- Primary signal not met; runtime unchanged. Next: two complementary high-risk critics and fresh closure before implementation.
- Version remains 2.2.4; no commit/push/tag/release created.

### 2026-07-19 — R-001 critics and R-002 adjudication

- Product/operator and architecture/data/security balanced critics returned `COVERED`, high confidence, with no gap or reopen request.
- Mandatory strong closure returned one technical `coverage-gap`: the spec did not require an executable absence/ordering proof between v2 abandonment and the separate root-completion audit.
- Applied selected T-012 and AC-14 without changing D-001–D-010; R-002 now requires no root audit, diff acceptance or Git/workspace mutation from v2 itself.
- An unrelated untracked `BUILD-spark-code-scout-fallback.md` appeared during the critic run; it is user-owned, unread, out of scope and must remain untouched.
- Primary signal not met; runtime unchanged. Fresh Sol/high closure is pending before `Ready`.

### 2026-07-19 — R-002 Sol closure and R-003 reconciliation

- Sol/high found four technical readiness gaps; no D-001–D-010 reopen was requested.
- Source map and M1/M2 now cover AC-01–AC-14. AC-14 documents the existing root-owned audit honestly: v2 cannot invoke it, and tests compare exact root-supplied canonical receipt hashes without claiming runtime repository recomputation.
- Reader floor now unambiguously rises on the first durable write by 2.2.5 code, consistent with the shared owner commit policy; T-010–T-014 are selected.
- Final review/publication is bound to an exact staged tree and diff digest; the release commit, tag and GitHub Release must all resolve to that reviewed tree with no intervening mutation.
- Primary signal not met; runtime unchanged. Fresh R-003 Sol/high closure is pending.

### 2026-07-19 — R-003 Ready closure

- Fresh exact Sol/high critic returned `COVERED`, high confidence, B-001–B-014 complete, no gap/reopen/trigger and determination `READY`.
- Status advanced to Ready at unchanged semantic revision R-003. Runtime, acceptance, commit, tag and Release remain pending and are not claimed green.
- M1 may start under the exact high-risk implementation route and one bounded writer lease.

### 2026-07-19 — M1 lease preparation

- Status advanced to In progress without changing semantic revision R-003.
- Packaged implementation/high resolves Balanced → Strong → Sol/high, max 3; transport failure blocks and only a verified pre-edit configured trigger may advance one step.
- M1 exact allowlist contains only runtime/test/static owner files. Both untracked BUILD files, release/docs surfaces and Git remain forbidden; Python validation must set `PYTHONDONTWRITEBYTECODE=1`.

### 2026-07-19 — M1 implementation, recovery and primary signal

- A-007 completed with valid `turn.completed`, exit 0, stopped process tree and a six-file allowlisted diff. An unrelated user-owned BUILD file changed outside the lease, so the lifecycle was correctly closed through exact `terminal-abandonment-v1`; all six allowlisted records remained byte-identical to the terminal checkpoint.
- After exact registry vacancy, the existing root-completion owner recorded R-003, the original milestone/scope digest and an independently computed diff-attribution receipt. Root then removed the fixture's invalid persisted revalidation, which had drifted a consumed authorization binding.
- Runtime now admits only recovery-target plus exact `[outside-set-drift, preexisting-dirty-overlap]` as `terminal-abandonment-v2`; v1 remains separate, normal/more-mixed inputs remain blocked, and the first 2.2.5 durable write raises the reader floor while only real 2.2.0–2.2.3 floors remain loadable.
- Added runner-level proof that root completion fails before vacancy and v2 creates no root audit, handoff, Git/index/worktree mutation or workspace rewrite. Reload coverage resumes once after pending, source invalidation, completed abandonment and guardian close.
- Primary signal is green: 8 focused runtime/static tests passed; after review remediation the full recovery-state suite passed 59/59 and package contract suite passed 166/166.
- Wider combined suite is not yet green: 15 errors and 4 failures are attributable to the concurrent uncommitted `spark-code-scout` diff, which added profile-source hashing and a new discovery schema without updating its fixtures/profile contract. Those hunks and `BUILD-spark-code-scout-fallback.md` remain user-owned and untouched; exact release-tree validation is pending their resolution.

### 2026-07-19 — M1 progressive-review remediation

- A-008 Balanced returned two concrete coverage gaps without product/architecture reopen. Added recovery-target + Git-drift byte-preservation, v2 schema/cause/lease/run/source/candidate mutation rejection, pending-v2 reader 2.2.4 rejection, and before-write/after-replace pending/source-invalidation replay. Full recovery-state suite then passed 59/59.
- A-009 Strong confirmed all A-008 findings closed and found one remaining AC-14 gap: v2 proved that it did not create an audit automatically, but the fixture did not separately invoke the existing root owner after vacancy.
- The AC-14 fixture now derives a canonical diff-attribution digest from Git status, binary diff and index hashes, proves the audit fails before vacancy without an artifact, terminalizes v2, then invokes the root owner after vacancy and compares both stdout and the durable private record exactly with `root_completion_authorization_record`. Git/index/worktree bytes remain unchanged.
- The corrected AC-14 fixture passes and was submitted unchanged to fresh Strong closure A-010.

### 2026-07-19 — M1 Strong closure

- Fresh A-010 Strong reviewed the post-remediation diff and returned `ACCEPT` 94/100, high confidence, with no actionable M1 finding or escalation trigger.
- AC-01–AC-10 and AC-14 are closed; M1 is Complete. M2 advanced to In progress for contract prose, version/docs synchronization, full release-tree validation, clean install/forward smoke and final exact-tree review/publication.

### 2026-07-19 — R-004 authoritative 2.3.0 reconciliation

- A concurrent user-owned Build advanced the uncommitted authoritative manifest, changelog and README pins to 2.3.0 for a minor discovery feature while M1 was running. Its shared diff changed during review, so M2 paused all shared writes until the candidate stabilized and its runner suite passed 123/123 with four platform skips.
- The on-disk version is authoritative: R-004 reconciles D-010/T-013 and the release surface to one combined 2.3.0 candidate. It does not roll back the other Build, manufacture a conflicting 2.2.5 tag or weaken the recovery reader-floor 2.2.5 boundary.
- SKILL, implementation delegation, model routing, TDD, review and versioning contracts now describe v1 outside-only and recovery-target-only v2 consistently. Changelog and EN/RU README add the recovery outcome and downgrade implications to the existing 2.3.0 notes.
- Contract validation passed 9/9 and `python scripts/validate_package.py` passed. Because the release scope now includes the stabilized concurrent candidate, fresh R-004 combined validation and exact-tree review remain mandatory before publication.

### 2026-07-19 — R-005 combined forward signal

- The exact packaged Spark route was exercised against the recovery-overlap owner. Two validator-safe rejections exposed ambiguous evidence shape/range wording and produced no fallback because transport completed successfully; the canonical instructions and package contract were tightened without changing the schema.
- A third run proved concurrent specification drift is rejected by the full fingerprint. After the shared tree stabilized, A-014 completed with exact Spark/low/read-only selection, `turn.completed`, exit 0 and valid `openbuild.discovery.v1` evidence.
- The combined candidate has package, official skill and official plugin validator signals. A fresh full suite and the required Sol/high combined review remain before staging and publication.

### 2026-07-19 — R-006 combined Sol remediation and validation

- Exact Sol/high A-015 returned `REVISE` 84/100 while explicitly accepting the recovery-v2 lifecycle. It found three discovery-side release blockers: the exclusive source claim lacked a parent-metadata barrier, fingerprint equality admitted boolean counters and malformed constants, and checked-out gitlinks did not bind dirty nested content.
- The final owner code publishes a no-replace claim through POSIX parent-directory fsync or Windows write-through move before any target request/process; validates lowercase digest, constants and non-boolean nonnegative counts; and fingerprints bounded nested tracked plus untracked/nonignored submodule content twice under shared file/byte/time/depth limits.
- Regression signals cover claim persistence before request/process, after-metadata-barrier restart, malformed public fingerprints, tracked/untracked submodule changes and concurrent marker/content drift. All 226 affected runtime tests pass with 4 expected platform skips; the complete suite passes 393 tests with 4 expected skips.
- Package, official plugin and official skill validators pass. A clean local 2.3.0 reinstall is enabled and byte-equal to the 46-file plugin source; a clean standalone validation is byte-equal across 33 skill files. AC-11 is closed; AC-12 awaits only the staged commit gate, and AC-13 awaits exact-tree Sol/high acceptance plus publication proof.

### 2026-07-19 — R-007 combined stream-consistency closure

- A later exact Sol/high review accepted recovery-v2 but found discovery availability classification could consume the first eligible structured error while ignoring contradictory records. Complete-stream normalization, cancellation/timeout/result gates, same-payload `code`/`type` agreement and JSONL/stderr consistency now fail closed before any Terra claim.
- Recovery runtime semantics remain unchanged from the accepted M1 closure: v2 is still recovery-target-only, exact-pair-only, no-handoff and no-root-authority; v1 and all other mixed reasons remain fail-closed.
- Fresh signals: 336 affected tests pass with 4 expected platform skips; the complete combined suite passes all 396 tests with 4 expected skips; package and official plugin/skill validators pass. The clean enabled 2.3.0 install is byte-equal across all 46 tracked plugin files.
- AC-12 is closed after exact combined staging and a green commit gate. AC-13 still requires fresh Sol/high acceptance of that unchanged staged tree and publication proof.

### 2026-07-19 — R-008 exact-tree review remediation

- Exact combined Sol/high A-016 reviewed tree `baa5f4ad945820eb5858f0898270bb1e744b15d3`, accepted recovery AC-01–AC-12/14, and returned `REVISE` 87/100 only because discovery treated existing non-regular `result.md` objects as missing. Concurrent unstaged collector changes appeared during review, so the reviewed tree was rejected even though its index identity remained unchanged.
- The discovery owner now distinguishes only no-follow `lstat` absence from every invalid existing object and preserves the concurrent unknown-event/malformed-stderr fail-closed fixes. Recovery runtime and authority semantics are unchanged.
- Fresh combined signals pass: 337 affected tests and all 397 repository tests with 4 expected skips, package and official plugin/skill validators, exact combined commit gate, plus a 46-file byte-equal clean install. AC-12 is closed; AC-13 awaits fresh unchanged-tree Sol/high acceptance and publication proof.

### 2026-07-19 — R-009 pending-legacy replay and collector closure

- Combined Sol/high A-017 accepted the exact recovery-v2 pair/lease boundary, no-handoff behavior, retirement/archive/release order and separate root authority, but found that a v1 abandonment already pending on floor 2.2.3 could fail before source invalidation. It also found the remaining non-regular JSONL collector path.
- `complete_terminal_abandonment` now durably promotes through `_read_registry_for_write_locked` before any replayable source replacement. The new pending-v1 fixture starts from floor 2.2.3 and asserts floor 2.2.5 inside the source commit boundary. Ordinary legacy reads remain byte-for-byte no-rewrite.
- JSONL and stderr collectors now share no-follow regular-file classification and receipt regressions for directory, broken symlink and FIFO; only true absence is eligible empty evidence. Recovery-v2 semantics are otherwise unchanged.
- Affected and full signals each pass all 399 tests with 4 expected skips; package, official plugin/skill validators and exact combined commit gate pass; clean install parity is 46/46 tracked files. AC-12 is closed; AC-13 awaits fresh unchanged-tree Sol/high acceptance and publication proof.

### 2026-07-19 — R-010 raw JSONL error-union closure

- Exact combined Sol/high A-018 accepted the recovery-v2 lease/cause boundary, legacy-v1 behavior, reader-floor replay ordering and no-handoff/no-root-authority contract. It found one discovery blocker: an event such as `{"type":"item.completed","code":"authentication_failed"}` could be omitted after an eligible Spark availability error.
- The owner collector now includes every raw top-level `code` record, recognizes only the closed raw availability-type set, and invalidates every event type outside the explicit non-error protocol allowlist before complete-stream classification. Receipt coverage includes the exact code-bearing non-error event and an unknown failure type, while package mutation coverage requires both closed sets and collector branches; contradictory evidence cannot authorize Terra.
- The A-018 tree was not release-authoritative because the shared index changed during review. No commit, tag or publication may use it; fresh full validation, stable exact staging and a new Sol/high acceptance remain required.

### 2026-07-19 — R-011 stable combined-candidate validation

- After the final collector write, index and worktree identities remained unchanged through six 20-second observations. The exact code-bearing/unknown-event regressions pass, and the current full repository suite passes all 399 tests with 4 expected platform skips.
- Package validation, official plugin validation and official skill validation pass. The first skill-validator attempt used the host cp1252 default and failed to decode UTF-8; the required UTF-8 invocation passed without package changes.
- Generated `__pycache__` directories were removed from the verified repository paths. A clean local OpenBuild 2.3.0 reinstall is enabled and its 46 source/cache files are byte-equal. The final 30-file combined index passes the package commit-gate and both whitespace checks with no unstaged path, so AC-12 is closed.

### 2026-07-19 — R-012 descriptor-bound artifact closure

- Combined Sol/high A-019 returned `REVISE`: the required tree stayed staged, but an external test edit appeared during review; independently, `lstat` followed by path-based `read_text`/`read_bytes` allowed a regular file, symlink or reparse target to replace JSONL, structured stderr or result evidence between check and read.
- The discovery owner now exposes one descriptor-bound regular-file reader. Initial/final no-follow `lstat`, opened/final `fstat`, regular/non-reparse type, stable device/inode/size/mtime identity and bytes read through EOF must agree. JSONL, stderr, final-result and strict discovery-result consumers share it; only initial absence is missing.
- Swap-at-open regressions cover all four consumers, and package mutation tests require the shared calls, no-follow open, both descriptor identities and final path identity. The concurrent R-020 runner/Codex-exit binding is preserved. Focused closure and package validation pass; AC-12 is reopened until the full suite, clean install and final combined commit-gate are recomputed.

### 2026-07-19 — R-013 combined source-binding reconciliation

- Discovery Sol/high A-028 found that a Spark source could carry an injected fallback binding and republish its reason after the clean eligibility predicate failed. Discovery R-022 now rejects such a source at the claim gate and suppresses the injected binding in public source receipts.
- Recovery-v2 runtime semantics remain unchanged: the exact recovery-only overlap pair, floor promotion, terminal invalidation and no-handoff/no-root-authority boundary retain their previously accepted behavior.
- Focused source receipt, claim-gate and package mutation tests pass. The complete repository suite passes all 403 tests with 4 expected platform skips; package, official plugin and official skill validators pass; the exact 30-file combined commit gate and both whitespace checks pass with no unstaged path; and the clean enabled 2.3.0 install is byte-equal across all 46 source/cache files. AC-12 is closed; fresh unchanged-tree Sol/high acceptance remains before publication.

### 2026-07-19 — R-014 immutable 2.3.0 and zero-exit patch reconciliation

- Combined A-020 accepted exact tree `d2488c4306edad96acf88643f8d75db5e1c6b4a1` at 97/100. Commit `7e7f247`, annotated tag `v2.3.0`, the public GitHub Release and remote tag installation all resolve to that tree; published history remains immutable.
- Concurrent discovery A-030 subsequently found that `codex_exit_code=0` could satisfy a forged failed-run envelope, and task-only A-031 accepted the correction. The owner now requires non-zero creation-bound exit evidence and advances only the package patch version to 2.3.1.
- Recovery-v2 behavior, reader floor 2.2.5 and legacy no-rewrite reads are unchanged. The affected suite passes 99 tests with 3 expected platform skips; the complete suite passes all 403 tests with 4 expected skips; package, official plugin and official skill validators pass; the clean enabled 2.3.1 install is byte-equal across 46/46 files; and the exact 10-file patch commit gate plus both whitespace checks pass with no unstaged path. AC-12 is closed; AC-13 remains open for fresh exact-tree Sol/high acceptance and immutable 2.3.1 publication.

### 2026-07-20 — R-015 legacy normal lifecycle reconciliation

- Immutable 2.3.1 is published at commit `150f586` and remains unchanged. The supplied follow-up proves that its v2 transition correctly rejected the exact overlap pair because the retained lifecycle was registered as `normal-contained`, not `recovery-target`; repeating authorization cannot change that durable owner evidence.
- RED changed the exact normal-contained overlap fixture from expected rejection to a v3 outcome and failed at the released `terminal abandonment requires exact outside-set-drift` gate. The owner now selects append-only `terminal-abandonment-v3` only for `normal-contained` plus exact `[outside-set-drift, preexisting-dirty-overlap]`, binds a distinct cause/invalidation and reuses terminal identity, full-tree zero, guardian, archive and release gates without handoff, diff acceptance, fabricated recovery authorization or root authority.
- Exact 2.2.0–2.2.3 and 2.2.5 registry generations remain readable byte-for-byte without rewrite. The first durable new transition raises the floor to 2.3.2 before any private-source replacement. Focused owner, runner, classifier, package and mutation signals are green; the complete repository suite passes all 404 tests with 4 expected platform skips; package and official plugin/skill validators pass; the enabled local 2.3.2 install is byte-equal across all 46 source/cache files. A-032 returned `ACCEPT` 96/100 with high confidence and no finding. A-033 found no safety defect and matched the staged tree but rejected the ambiguous digest command; T-014 now fixes the exact no-ext-diff command. Fresh staged-tree review, commit gate and immutable 2.3.2 publication remain pending.
