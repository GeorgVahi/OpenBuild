# Versioning and release contract

Use this contract in `run` and `full` before any milestone or final commit when the repository has package, application, API, schema, plugin, or release version metadata.

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

- `none`: no shipped behavior, compatibility, installation, or public contract changed, and repository policy does not require a bump;
- `prerelease`: another development iteration toward an already selected next release, such as incrementing `-dev.N`;
- `patch`: a backward-compatible fix to released behavior;
- `minor`: a backward-compatible feature or capability;
- `major`: a breaking public contract, migration, or compatibility change.

Follow the repository's own SemVer interpretation, especially before `1.0.0`. When policy and impact are unambiguous, the root agent decides autonomously. Ask the user only when selecting a release line, accepting a breaking change, or resolving a material policy ambiguity.

## Same-commit gate

Before creating a scoped commit:

1. Compare the task diff with the saved baseline and identify shipped/public contract changes.
2. Apply the repository's bump rule and compute the next version from the authoritative source.
3. Update the authoritative version, changelog, user-facing version references, and required generated metadata in the same commit.
4. Run the repository's version/package validation and confirm every synchronized surface agrees.
5. Record the previous version, next version, impact, evidence, and validation in the specification.

Do not bump merely because a Git commit exists unless repository policy explicitly requires per-commit versions. Do not omit a required bump by splitting the version change into a later cleanup commit.

## Prerelease and release boundary

- Use a repository-defined prerelease sequence for development branches when applicable; increment it for each commit that changes the installable or public contract.
- Treat tag creation, GitHub Release creation, package publication, and promotion from prerelease to stable as external publication requiring existing authorization.
- Never move, recreate, or silently retarget a published tag. Published release tags are immutable.
- Before publishing, verify that the tag, manifest version, changelog entry, documentation pins, and release title agree.
- After publishing, start the next development version according to repository policy instead of editing the released tag.

## Reviewer audit

Reviewers remain read-only. When `Version impact` is not `none`, require them to verify:

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
Version impact: <none|prerelease|patch|minor|major> — <evidence>
Previous version: <value or none>
Next version: <value or unchanged>
Synchronized files: <manifest, changelog, docs, generated metadata>
Validation: <commands and results>
Release action: <none|tag|release|publish> — <authorization/evidence>
```
