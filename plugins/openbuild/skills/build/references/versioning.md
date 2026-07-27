# Versioning and release contract

Use this contract in `run` and `full` before every milestone or final commit. When the repository has package, application, API, schema, plugin, or release version metadata, every Build-created commit receives a unique higher version by default.

## Discover the repository policy

Before implementation, locate and record:

- applicable `AGENTS.md`, contributor, release, and changelog instructions;
- the authoritative version source, such as a manifest, generated metadata source, or release file;
- other files that must stay synchronized, including lockfiles, package metadata, documentation, and changelog links;
- the current development version, latest published version, tags, and release channel;
- the repository's version command or generator when one exists.

Do not introduce a version scheme into an unversioned repository unless the task or repository policy requires it. Do not edit generated copies directly when a source or generator owns them.

## Classify version impact

Record `Version impact` as one of:

- `not applicable`: there is no authoritative version source or no commit will be created;
- `prerelease`: another development iteration toward an already selected next release, such as incrementing `-dev.N`;
- `patch`: a backward-compatible fix to released behavior;
- `minor`: a backward-compatible feature or capability;
- `major`: a breaking public contract, migration, or compatibility change.

Follow the repository's own SemVer interpretation, especially before `1.0.0`. If the repository has a version source but no explicit commit policy, default to a unique higher version for each Build-created commit. An applicable repository policy may instead require a release-only or generated version; follow it and record the exception. When policy and impact are unambiguous, the root agent decides autonomously. Ask the user only when selecting a release line, accepting a breaking change, or resolving a material policy ambiguity.

## Same-commit gate

Before creating a scoped commit:

1. Compare the task diff with the saved baseline and identify the commit's observable impact.
2. Apply the repository's bump rule and compute a unique higher version from the authoritative source.
3. Update the authoritative version, changelog, user-facing version references, and required generated metadata in the same commit.
4. Run the repository's version/package validation and confirm every synchronized surface agrees.
5. Record the previous version, next version, impact, evidence, and validation in the specification.

For a recovery state-machine release, synchronize the manifest version with the runtime reader floor and every SKILL/implementation/model/TDD/review contract that describes prompt staging, lease ownership, terminal reconciliation, root-completion authority, or user-decision boundaries. A patch may preserve legacy reads without rewrite-on-read while making the first new durable write raise the floor; document the downgrade/retirement implication in the same commit. For 2.2.3 specifically, exact 2.2.0–2.2.2 reads remain accepted, the first new post-commit shape raises the floor to 2.2.3, and a non-vacant 2.2.3 registry cannot be safely downgraded. For the recovery-overlap transition introduced with the 2.3.0 package, exact 2.2.0–2.2.3 floors remain readable without rewrite and the first durable write by that owner raises the floor to 2.2.5. For the legacy-normal reconciliation added in 2.3.2, exact 2.2.0–2.2.3 and 2.2.5 floors remain readable without rewrite; the first durable write by that owner raises the floor to 2.3.2 before any new private-source replacement. For post-zero containment-loss reconciliation added in 2.3.5, exact 2.2.0–2.2.3, 2.2.5, and 2.3.2 generations remain readable without rewrite; the first new durable transition raises the floor to 2.3.5 before source invalidation. For exact-triple v4 reconciliation added in 2.3.6, 2.3.5 joins the no-rewrite legacy set and the first new durable transition raises the floor to 2.3.6 before source invalidation, including completion of an abandonment recorded before upgrade. For exact single-overlap v5 reconciliation added in 2.4.0, 2.3.6 joins the no-rewrite legacy set and the first new durable transition raises the floor to 2.4.0 before source invalidation, including completion of an abandonment recorded before upgrade. The 2.4.0-alpha.6 pre-zero Windows orphan transition retains the 2.4.0 reader floor, writes a new owner-origin zero/history shape only inside the same non-vacant lifecycle, and releases it immediately through existing abandonment phases; an older 2.4.0 reader must still fail closed if it encounters that in-flight shape. A non-vacant floor-2.4.0 registry must fail closed under an older reader until explicit vacant retirement.

For a versioned repository, bump every Build-created commit unless an applicable repository policy explicitly defines a different release-only or generated scheme. Never postpone a required bump to a later cleanup commit.

For the 2.4.1 task-relevant recovery snapshot transition, exact 2.4.0 and earlier supported floors remain readable without rewrite. A source whose snapshot omits the policy remains `full-ignored-v1`; a new source writes `task-relevant-v2` only after the registry floor is durably `2.4.1`, before any private-source replacement. The 2.4.1 reader must preserve that source mode through revalidation, and a 2.4.0 reader must reject a non-vacant 2.4.1 registry rather than interpreting the new policy as its historical full ignored inventory.

## Prerelease and release boundary

- Use a repository-defined prerelease sequence for development branches when applicable; increment it for each commit that changes the installable or public contract.
- Treat tag creation, GitHub Release creation, package publication, and promotion from prerelease to stable as external publication requiring existing authorization.
- Never move, recreate, or silently retarget a published tag. Published release tags are immutable.
- Before publishing, verify that the tag, manifest version, changelog entry, documentation pins, and release title agree.
- After publishing, start the next development version according to repository policy instead of editing the released tag.

## Reviewer audit

Reviewers remain read-only. When `Version impact` is not `not applicable`, require them to verify:

- the selected impact matches the observable diff and repository policy;
- the authoritative source and synchronized copies agree;
- changelog and compatibility notes are truthful;
- no published tag or historical release was rewritten;
- release/publication claims are backed by actual remote evidence.

The root agent adjudicates findings and makes any version correction before the commit or next review.

## Version record

```text
Version source: <path/key or not applicable>
Version policy: <repository rule or not found>
Version impact: <not applicable|prerelease|patch|minor|major> — <evidence>
Previous version: <value or none>
Next version: <value or unchanged>
Synchronized files: <manifest, changelog, docs, generated metadata>
Validation: <commands and results>
Release action: <none|tag|release|publish> — <authorization/evidence>
```
