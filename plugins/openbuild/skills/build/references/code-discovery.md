# Code discovery protocol

Use this protocol before broad repository search in every Build mode. The root agent remains the orchestrator, decision owner, editor, and final reporter.

## Mandatory routing rule

1. Detect whether the task needs broad discovery: file or symbol lookup, repository-wide search, dependency or route tracing, test/config/schema discovery, similar-pattern search, or cross-file flow mapping.
2. Write a compact search plan with the objective, likely regions, independent branches, minimum evidence, and a stop condition.
3. Use the capability order in [model routing](model-routing.md). Prefer a confirmed read-only `openbuild-discovery` profile or the cheapest suitable native tier. Otherwise use an explorer role, a generic subagent, or immediate root fallback.
4. Delegate independent search branches in parallel when capacity and scope justify it.
5. Aggregate and deduplicate results, surface contradictions and negative results, then decide whether more discovery is useful.
6. Let the root agent reread the critical files and perform only targeted follow-up searches before making decisions or edits.

Do not ask the user before falling back when a preferred model, profile, subagent slot, quota, or selector is unavailable. Do not block the task solely because delegation is unavailable.

Give every worker branch a task-appropriate time and attempt budget. A short parent polling timeout without a final worker result is not by itself a worker failure; keep the user informed while useful work continues. Stop or interrupt a branch when the platform reports failure, quota, or unavailability, when the declared time budget is exceeded, or when two completed attempts return empty or unusable evidence. Record the reason and continue with another worker or targeted root discovery instead of waiting indefinitely.

## Root-only exceptions

The root may read directly when the relevant file is already known, the lookup is genuinely narrow, it is verifying a returned finding, or subagents are unavailable or repeatedly fail. Record a material fallback, but do not pretend that delegation or model switching occurred.

## Discovery worker contract

Give each worker:

- one bounded objective and repository/workspace scope;
- relevant symbols, strings, routes, or behaviors to locate;
- explicit read-only and no-destructive-action boundaries;
- a prohibition on edits, commits, pushes, architecture/product decisions, final user answers, and secret output;
- the evidence format and stop condition below.

Do not ask a discovery worker to implement, refactor, run destructive commands, or execute broad test suites. Use it for search and evidence mapping only.

## Evidence map

Require compact items in this form:

```text
path:line | symbol/component/route | short snippet or signature | confirmed fact and why it matters
```

Also request:

- search methods or terms used;
- relevant negative results;
- confirmed facts separated from uncertainty;
- confidence and any remaining evidence gap.

Keep raw logs, large file dumps, and repetitive matches out of the root context.

## Model and savings claims

- Never infer suitability, price, speed, or strength from a model name.
- Report a concrete model only when the runtime or confirmed profile exposes it.
- If `openbuild-discovery` is explicitly mapped to a lower-cost code-search model, use that mapping; otherwise record the observed model/tier as `unknown`.
- A different role, prompt, or thread is not proof of a different model or reduced token cost.

## Discovery record

Record enough evidence in the specification to resume safely:

```text
Discovery mode: delegated | mixed | root-fallback
Routing branch: native-selector | configured-profiles | reasoning-ladder | role-only | generic-subagent | root-only
Observed discovery model/tier: <verified value or unknown>
Search branches: <objectives and workers>
Evidence map: <key path:line findings>
Fallback or limitations: <quota, selector, profile, failures, or none>
```
