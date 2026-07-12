# OpenBuild

[Русская версия](README.ru.md)

OpenBuild is a Codex workflow for turning a plain-language idea or an existing specification into a repository-grounded plan and, when requested, a tested implementation with delegated code discovery, evidence-gated minimality, TDD-first milestones, and progressive review.

It packages one explicit skill, **Build**, with five modes:

- `new` — create a specification and stop before code changes;
- `refine` — verify and improve an existing specification and stop before code changes;
- `run` — execute a ready or refinable specification;
- `full` — go from an idea through specification, implementation, validation, and review;
- `setup-models` — optionally configure permission-gated read-only model-tier profiles.

OpenBuild is self-contained. It does not require separate discovery, TDD, or review skills, telemetry, a hosted service, or background network access.

> OpenBuild `v0.1.0` is a preview release. Install a version tag for reproducibility; use `main` only when you intentionally want the latest preview.

The current `main` preview reports plugin version `0.2.0-dev.3`; the immutable release tag remains `v0.1.0` until a new release is published.

## Requirements

- A current Codex surface that supports skills. Plugin installation is available in Codex CLI and supported plugin surfaces.
- Git, when Build is expected to create milestone commits or review a task diff.
- Windows is verified for `v0.1.0`. macOS and Linux are documented as best-effort until native validation is completed.

OpenBuild `v0.1.0` supports Codex only. It does not claim compatibility with Claude Code, Cursor, Gemini CLI, or other coding agents.

## Install as a plugin — recommended

The plugin is the primary distribution channel. It gives you versioned marketplace installation and the namespaced invocation `$openbuild:build`.

### Pinned preview `v0.1.0`

```bash
codex plugin marketplace add GeorgVahi/OpenBuild --ref v0.1.0
codex plugin add openbuild@openbuild
```

Start a new Codex thread, then verify that `OpenBuild` is installed:

```bash
codex plugin list
```

Invoke it explicitly:

```text
$openbuild:build new Add saved searches to this application
```

### Preview from `main`

```bash
codex plugin marketplace add GeorgVahi/OpenBuild --ref main
codex plugin add openbuild@openbuild
```

Refresh a `main` installation:

```bash
codex plugin marketplace upgrade openbuild
codex plugin add openbuild@openbuild
```

### Switch between release tags

A versioned/tag-pinned marketplace is fixed to its selected tag. To move from one tag to another, remove the installed plugin and marketplace entry, then add the new tag:

```bash
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
codex plugin marketplace add GeorgVahi/OpenBuild --ref v0.1.0
codex plugin add openbuild@openbuild
```

Replace `v0.1.0` with the target release tag.

### Uninstall the plugin

```bash
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
```

## Install as a standalone skill

Standalone installation gives you the shorter `$build` invocation. Ask the preinstalled system skill installer to install the canonical Build folder:

```text
Use $skill-installer to install the skill from https://github.com/GeorgVahi/OpenBuild/tree/v0.1.0/plugins/openbuild/skills/build
```

Start a new Codex thread after installation. Open `/skills` or type `$` and verify that `build` appears, then invoke:

```text
$build new Add saved searches to this application
```

The installer refuses to overwrite an existing `$CODEX_HOME/skills/build` directory. Review that directory, back it up or remove it intentionally, and rerun the installer when updating. To uninstall the standalone version, remove only the confirmed `$CODEX_HOME/skills/build` directory and restart Codex.

The plugin and standalone channels use the same canonical source folder; there are no duplicated implementations in this repository.

## Usage

### 1. Create a specification from scratch

Plugin:

```text
$openbuild:build new Add a wishlist to the existing store
```

Standalone:

```text
$build new Add a wishlist to the existing store
```

Build will:

1. inspect the current repository and applicable `AGENTS.md` files;
2. establish a Git or artifact baseline;
3. delegate broad code search to bounded read-only discovery workers when available, then verify their evidence map;
4. ask only unresolved product questions using short answers such as `1a 2b`;
5. create `BUILD.md` in the user's language;
6. stop before implementation.

Example question:

```text
1. Who can keep a wishlist?
   a) Signed-in users only; the list follows the account.
   b) Guests too; the list starts locally and may merge after sign-in.
   Recommendation: 1a — it avoids an unresolved merge policy in the first version.

Reply with: 1a
```

### 2. Refine an existing specification

```text
$build refine BUILD.md
```

You can also pass `SPEC.md`, `TZ.md`, or another explicit path:

```text
$build refine docs/checkout-spec.md
```

Build compares the document with the current repository, preserves manual edits, identifies contradictions and unknown unknowns, updates acceptance criteria and milestones, and stops at `Ready`. If several specification files are relevant or the selected file belongs to another task, Build asks before changing anything.

### 3. Execute a specification

```text
$build run BUILD.md
```

Build first verifies that the specification can reach `Ready`. It classifies implementation work as `Direct`, `Investigation`, or `TDD-first`, then implements coherent milestones, runs focused validation, performs progressive review, updates the specification log, and creates scoped milestone commits when repository policy allows. It never pushes the user's repository without explicit authorization.

### 4. Run the full workflow

```text
$build full Add organization-level API keys with rotation and audit history
```

A bare idea is an alias for `full`:

```text
$build Add organization-level API keys with rotation and audit history
```

`full` may change implementation files after the specification reaches `Ready`. It still stops for destructive operations, secrets, live infrastructure, external publication without existing authorization, or a material scope expansion.

### 5. Configure progressive model tiers

```text
$build setup-models
```

Build first checks the capabilities exposed by the current Codex runtime. If native per-subagent selection already provides a proven ladder, no files are needed. Otherwise it may propose a read-only `openbuild-discovery` profile for broad code search plus `openbuild-review-fast`, `balanced`, `strong`, and `strongest` review profiles.

Before writing anything, Build must show:

- the detected model/reasoning evidence;
- the proposed tier mapping;
- user scope (`~/.codex/agents`) or project scope (`.codex/agents`);
- exact target files and exact diff.

It writes only after separate permission, never overwrites an existing profile, validates TOML, and requires a reload or new session before claiming that model switching works. Declining setup leaves the zero-config workflow operational.

## How automatic code discovery works

Before broad file listing, repository-wide search, symbol lookup, dependency tracing, or route/test/config mapping, the root agent creates a compact search plan and delegates independent branches to bounded read-only discovery workers when available. Workers return only an evidence map with `path:line`, symbol or route, a confirmed fact, relevance, negative results, and confidence.

The root agent remains the orchestrator: it deduplicates the evidence, verifies critical files with targeted reads, makes product and architecture decisions, edits, validates, owns Git, and writes the final answer. Discovery workers never edit or decide architecture.

`openbuild-discovery` can be explicitly mapped to a suitable lower-cost code-search model through `$build setup-models` when runtime metadata or user-confirmed configuration proves the mapping. OpenBuild does not assume a particular model version, infer cost from a slug, or claim savings when the actual model is hidden. If the preferred worker is unavailable, rate-limited, or exhausted, Build immediately falls back through explorer, generic-subagent, and root-only modes without asking the user or blocking the task.

## How TDD-first implementation works

Behavior, contracts, validation, routing, state, auth or permissions, persistence, concurrency, integrations, security, and non-trivial user-facing changes use a red → green → refactor workflow. Build finds the narrowest supported test path, records a meaningful failing signal when practical, makes the minimum coherent owner-layer change, requires focused green validation, and refactors only after green.

Direct documentation or cosmetic work does not get ceremonial failing tests. Investigation work first reproduces or traces the failure and is reclassified as TDD-first before behavior changes. When an automated red signal is impractical, Build records why and uses the best reproducible contract or runtime signal.

Reviewers stay read-only. They audit the red signal, owning layer, focused green result, and risk-based coverage. Confirmed behavioral findings go back to the root agent, which runs remediation through the same TDD-first workflow before requesting another review.

## How evidence-gated minimality works

After the Ready gate and before code changes, Build evaluates every proposed file, dependency, abstraction, configuration surface, and compatibility layer through an evidence-gated ladder: is it needed now; does the repository already solve it; does the standard library or native platform cover it; does an installed dependency fit; and only then, what is the minimum coherent custom change in the owning layer. Build stops at the first option that satisfies the complete acceptance criteria, invariants, repository conventions, and risk constraints.

Minimality governs technical means, not accepted product scope. It never trades away supported tests, trust-boundary validation, security, privacy, accessibility, data-loss handling, error handling, observability, compatibility, migration or rollback safety, concurrency correctness, or required performance. A deliberate simplification with a known ceiling records that ceiling and an observable upgrade trigger instead of building the speculative upgrade immediately.

Reviewers audit the completed diff for duplicated sources of truth, avoidable dependencies, custom code covered by standard or native capabilities, speculative abstractions or configuration, and downstream symptom patches. Line count and code golf are not success metrics; a finding is actionable only when the smaller path preserves accepted behavior and risk coverage.

## How progressive review works

Build classifies each task as `low`, `medium`, `high`, or `critical`. It starts at the minimum sufficient review tier rather than always wasting a strongest-model pass:

| Complexity | Typical work | Starting review request |
|---|---|---|
| `low` | Documentation or mechanical local changes | Fast/economy |
| `medium` | Contained behavior or refactoring with tests | Balanced |
| `high` | Cross-layer state, public contracts, persistence, concurrency, auth, permissions, privacy | Strong |
| `critical` | Irreversible actions, live infrastructure, secrets, destructive migration | Strongest available |

Reviewers return acceptance coverage, evidence-backed findings, confidence, a verdict, and an optional score. After confirmed findings are fixed and validation reruns, Build escalates when the score is below `9.5`, confidence is low, coverage is incomplete, reviewers conflict, validation fails, a high-impact finding remains, or the diff changed materially.

The score is only an escalation signal. Completion still requires green validation, evidence for every acceptance criterion, and no confirmed actionable findings. The loop is bounded by distinct proven tiers and never repeats the same reviewer on an unchanged diff.

When Codex does not expose a model selector, Build does not invent one. It falls back through configured profiles, supported reasoning efforts, a read-only explorer role, a generic subagent, and finally root-only self-review. The effective mode and any unknown tier are recorded explicitly.

## Specification resolution

Build uses an explicit path when provided. Otherwise it prefers a relevant `BUILD.md`, then a relevant `SPEC.md` or `TZ.md`, and creates `BUILD.md` for a new task. It never silently replaces a specification that belongs to another task.

## Git and safety policy

- Existing user changes remain out of scope unless the specification explicitly includes them.
- `new` and `refine` may edit only the specification.
- `run` and `full` may edit implementation files after the Ready gate.
- Milestone commits are created when Git is available, changes can be isolated, and applicable instructions do not forbid commits.
- Push always requires explicit authorization.
- Model configuration requires a separate preview and permission.
- Discovery and review workers are read-only; the root agent owns decisions, edits, TDD remediation, validation, Git, and final reporting.
- No telemetry, daemon, `curl | shell`, hidden auto-update, or background network service is included.
- Build follows the repository's `AGENTS.md`, sandbox, approval, validation, and security rules.

## Versioning and commits

Before a milestone or final commit, Build discovers the repository's authoritative version source and policy, then records `version impact` as `none`, `prerelease`, `patch`, `minor`, or `major`. When a commit changes installable behavior or a public distribution contract and policy requires a bump, the root updates the version, changelog, and required documentation in that same commit.

Build does not invent versioning for an unversioned repository or bump mechanically for prose-only/internal commits. It never moves a published tag. Tag creation, GitHub Release creation, package publication, and promotion from prerelease to stable remain separately authorized publication actions.

OpenBuild's own contributor, version, commit, and release rules are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## Troubleshooting

### The skill does not appear

- Start a new thread or restart Codex after installation.
- For the plugin, run `codex plugin list` and confirm `openbuild@openbuild` is installed and enabled.
- Open `/skills` or type `$` to inspect discovered skills.
- Use `$openbuild:build` for the plugin and `$build` for standalone installation.

### Both `$build` and `$openbuild:build` appear

You installed both channels. They use the same source but are separate local installations. Prefer the namespaced plugin invocation or intentionally remove the standalone `$CODEX_HOME/skills/build` directory.

### Model switching is reported as unavailable or unverified

Run `$build setup-models`. If the runtime exposes neither per-spawn model selection nor custom agents, Build continues with role/reasoning/root fallback and reports the limitation honestly.

### Build refuses to overwrite a specification

The discovered file is ambiguous or belongs to another task. Pass the intended path explicitly or choose a descriptive file such as `BUILD-wishlist.md`.

### The worktree is already dirty

Build records the initial status, excludes unrelated changes, and commits only task-scoped files. If changes cannot be isolated safely, it stops before committing rather than hiding or publishing them.

## Development and validation

See [CONTRIBUTING.md](CONTRIBUTING.md) for the `main` workflow, Semantic Versioning rules, same-commit version gate, and immutable release checklist.

From the repository root:

```bash
python scripts/validate_package.py
```

The release process also runs the official Codex skill and plugin validators, clean plugin installation, standalone installation from the tagged GitHub path, forward-tests for `new`, `refine`, `run`, delegated discovery, evidence-gated minimality, TDD-first remediation, and model-routing fallbacks, and a fresh full-diff review.

Useful official references:

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex subagents and custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

## License

[MIT](LICENSE)
