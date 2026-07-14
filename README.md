# OpenBuild

[Русская версия](README.ru.md)

OpenBuild is an explicit Codex workflow that can take a plain-language task or an existing specification from repository discovery through implementation, validation, and review. The default route is automatic: invoke Build, describe the outcome, and let it choose the first incomplete phase.

Current release: `2.1.4` ([pinned skill source](https://github.com/GeorgVahi/OpenBuild/tree/v2.1.4/plugins/openbuild/skills/build)).

## Diagrams

### Workflow

![OpenBuild workflow](plugins/openbuild/lib/Workflow-en.png)

### Exact model routing

![Exact model routing](plugins/openbuild/lib/usage-v3-en.png)

### Implementation delegation

![Adaptive implementation delegation](plugins/openbuild/lib/delegat-en.png)

## Requirements

- Codex with plugin support;
- Python 3.11 or newer;
- Codex CLI authenticated with a saved ChatGPT login;
- Git for repository and release workflows.

OpenBuild does not require direct API credentials. Its delegated agents run as separate subscription-authenticated Codex CLI processes.

## Install or update

Remove an existing installation and marketplace source:

```powershell
codex plugin remove openbuild@openbuild
codex plugin marketplace remove openbuild
```

Add the latest pinned release and install it:

```powershell
codex plugin marketplace add GeorgVahi/OpenBuild --ref v2.1.4
codex plugin add openbuild@openbuild
```

Start a new Codex thread after installation so the updated skill is loaded.

## Usage

Invoke `$openbuild:build` and describe the desired outcome. With no explicit mode, Build works in `auto` and decides whether to create, refine, or execute a specification.

Optional modes:

- `new <idea>` — create or clarify a specification without implementation;
- `refine <path>` — reconcile an existing specification with the repository;
- `run <path>` — implement an existing specification;
- `full <idea>` — specification through implementation and review;
- `auto <idea-or-path>` — explicitly request automatic routing.

For an existing specification, pass its repository-relative or absolute path. Build never chooses among multiple plausible specification files silently.

## Exact model-routed agents

OpenBuild ships ready-to-use profiles for discovery, implementation, and review. It starts every created agent only through the packaged `codex-exec-explicit-model` runner, which supplies the exact model, reasoning effort, sandbox, and task to a separate `codex exec` process and records a terminal receipt.

Profile precedence is project override, user override, then packaged default. The packaged Spark discovery profile is immutable so code search consistently uses the same read-only contract. Native Explorer, name-only custom agents, generic workers, and other routes that cannot prove model and effort are not used.

If exact discovery fails, Build records the reason and performs only the minimum targeted root search needed to continue. An exact implementation or review failure leaves that gate incomplete instead of substituting an agent with unknown model metadata.

Implementation starts on Terra for low, medium, and high risk; Sol high is used only after a completed pre-edit `NEEDS_ESCALATION`, while critical work starts on Sol xhigh. Review similarly starts low on Luna, medium/high on Terra, and reaches Sol only on evidence or for critical work.

## Progressive review

Review is sequential and read-only. Build starts at the tier required by the change risk, accepts an evidence-backed clean result, and moves one tier higher only when a concrete unresolved finding remains after remediation and validation. Every accepted review must have a successful exact-runner receipt and semantic result.

## Repository and Git behavior

OpenBuild follows applicable `AGENTS.md` files and repository tooling, preserves unrelated worktree changes, keeps one active writer, and leaves Git operations with the root orchestrator. Destructive, external, security-sensitive, or user-authority decisions still require explicit permission.

## Development

Package validation lives in `scripts/validate_package.py`; runner and contract tests live beside it. Release rules are documented in [CONTRIBUTING.md](CONTRIBUTING.md), and release changes in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
