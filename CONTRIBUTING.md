# Contributing to OpenBuild

OpenBuild accepts focused changes against `main`. Keep the public plugin self-contained, preserve English/Russian documentation parity, and do not add personal model IDs, local paths, secrets, or dependencies on private skills.

## Development workflow

1. Start from a clean `main` checkout and record the baseline commit.
2. Keep changes scoped to one coherent behavior or documentation contract.
3. Update `CHANGELOG.md` for the new commit version.
4. Determine the version impact before committing.
5. Run the contributor checks below; maintainers perform the additional Codex-specific checks before merge or release.
6. Use a fresh read-only reviewer for non-trivial changes and fix confirmed findings before committing.

## Versioning policy

OpenBuild follows [Semantic Versioning](https://semver.org/). The authoritative version source is `plugins/openbuild/.codex-plugin/plugin.json`.

Every OpenBuild commit must include a unique higher version in that same commit, together with the synchronized changelog and README references. Record `version impact` using these rules:

- `patch` for a backward-compatible fix;
- `minor` for a backward-compatible capability;
- `major` for a breaking contract;
- `prerelease` for another development iteration toward an already selected release.

`none` is not valid for an OpenBuild commit after the repository root. In a Build specification it may be recorded as `not applicable` only when no version source exists or no commit will be created.

For pre-`1.0.0` development, a new backward-compatible capability normally advances the minor line. That is why delegated discovery, TDD-first orchestration, and per-commit version enforcement ship as `0.2.0`, not `0.1.1`.

The manifest is authoritative. Every commit on `main` must advance to a unique SemVer value: a stable patch/minor/major version or the next prerelease counter on an explicitly selected release line. Keep it synchronized with both READMEs and a truthful `CHANGELOG.md` entry.

All tracked repository paths are covered, including tests, contributor prose, and internal validation code. Do not postpone the bump or changelog update to a later cleanup commit.

## Pull request workflow

1. Create a focused branch from the current `main` and target the pull request back to `main`.
2. Implement one coherent change, update both READMEs, and record the exact new version and outcome under `CHANGELOG.md#Unreleased`.
3. Update the manifest version, changelog, and both READMEs before staging any non-empty commit.
4. Run the contributor checks below, then stage the complete task diff.
5. Run the commit gate against the staged snapshot and commit only when it is green.
6. Push the contributor branch and open a PR describing the outcome, `version impact`, exact validation output, and any unverified platform/runtime behavior.

## Contributor validation

From the repository root:

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
python scripts/validate_package.py
git diff --check
git add <task-scoped-files>
git diff --cached --check
python scripts/validate_package.py --commit-gate
```

The unit suite locks the version-gate contract. Before staging, the normal validator checks the working tree, including untracked plugin files. After staging, `--commit-gate` rejects any remaining unstaged public package file, so structural checks match the index content; it then compares every non-empty staged snapshot with `HEAD` and requires a strictly higher manifest version plus CHANGELOG and both READMEs in the same commit.

For Build behavior changes, add a small fixture or realistic prompt and report the observable forward-test result. Readiness changes should exercise legacy specs, duplicate decisions, evidence-backed reopening, linked normative source maps, product-impact classification, and the user-answer-before-normative-write/application-receipt sequence. Routing changes should exercise separate-pool first use, quota/profile circuit-breaker fallback, exact risk-matched writer dispatch, and evidence-only sequential reviewer escalation; implementation-delegation changes should exercise the unchanged TDD contract, single-writer lease, and root handoff. For documentation-only work, verify every changed command and local link.

For search-dispatch changes, the deterministic trace fixture must prove that exact `openbuild-search-separate` selection and a complete routing receipt precede the first repository-search event. It must also reject root-first search, generic dispatch without a recorded exact-selector failure, and unknown fallback reasons. A maintainer runtime smoke uses a fresh thread with a configured separate-pool profile and a small `$openbuild:build new` repository-mapping prompt; pass only when subagent activity or runtime metadata shows the exact named dispatch before search. Treat the usage dashboard as secondary evidence and report the runtime smoke as unverified when the surface does not expose the selection.

For implementation-dispatch changes, the trace must prove that risk selects the exact named `openbuild-implementation-*` profile, its complete workspace-write routing receipt follows dispatch, and that agent owns the first test or production edit. Reject generic agents, stronger-than-requested substitution, receipt/edit reordering, sandbox mismatch, and any high/critical risk-floor downgrade.

For progressive-review changes, trace the exact read-only `openbuild-review-*` start profile from risk, its routing receipt, structured result, root adjudication/remediation, affected green validation, and the next dispatch when escalation remains necessary. Reject parallel reviewers, escalation without a concrete trigger, repeated tier on an unchanged diff, skipped proven tiers, reviewer-authored remediation, and acceptance with unresolved findings.

## Maintainer-only validation

Maintainers additionally run the official Codex skill/plugin validators, clean plugin and standalone installations, relevant multi-agent forward-tests, and a fresh independent full-diff review. Release candidates also require remote installation from the candidate ref and public tag/Release verification. These checks depend on maintainer Codex tooling and publication access; contributors should report them as not run rather than imitate unavailable authority.

## Commit and Git rules

- Commit only task-scoped files and preserve unrelated user changes.
- Keep `main` history forward-moving; do not force-push, rewrite published history, or move release tags.
- Use an imperative commit subject that describes the shipped outcome.
- Push only under the applicable repository/user authorization policy.
- Do not include the local ignored `TZ.md`, temporary homes, generated caches, or personal agent profiles.

## Release checklist

1. Select the stable SemVer version from the reviewed change impact.
2. Replace the prerelease manifest version with the stable version.
3. Move the relevant `Unreleased` notes into a dated release entry.
4. Update README installation pins and release wording in English and Russian.
5. Run all validation and clean install checks against the release commit.
6. Create a new annotated tag `v<version>` and GitHub Release only with publication authorization.
7. Verify the public tag resolves to the reviewed commit and the Release is visible without credentials.

Published tags and releases are immutable. Fixes after publication receive a new version; never retarget an existing tag.
