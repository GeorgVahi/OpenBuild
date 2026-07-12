# Build specification template

Use this as a flexible structure. Remove irrelevant sections and keep the document concise enough to remain the durable source of truth for a long-running task.

```markdown
# Build: <short outcome>

- Status: Draft | Questions | Ready | In progress | Complete
- Last updated: YYYY-MM-DD
- Original request: <one to three sentences in the user's language>
- Primary signal: <observable proof of success>
- Review baseline: <Git branch@SHA and initial status, or a non-Git artifact manifest>
- Complexity: low | medium | high | critical — <evidence>
- Implementation mode: Direct | Investigation | TDD-first — <evidence>
- Version impact: not applicable | prerelease | patch | minor | major — <version source, policy, and evidence>
- Routing mode: native-selector | configured-profiles | reasoning-ladder | role-only | generic-subagent | root-only
- Discovery mode: delegated | mixed | root-fallback — <observed model/tier or unknown>

## 1. Outcome

### Problem

<What is currently wrong or missing, and who it affects.>

### Desired behavior

<What the user can observe or do after completion.>

### In scope

- <required result>

### Out of scope

- <explicit exclusion>

## 2. Current state and evidence

| Area | Evidence | Confirmed fact | Why it matters |
|---|---|---|---|
| <flow> | `path:line` | <fact> | <decision impact> |

### Source of truth

<Owning layer, data, or state.>

### Gap

<Exact mismatch between the request and current project.>

## 3. Decisions

| ID | Decision | Selected option | Consequence |
|---|---|---|---|
| D-01 | <question> | <answer> | <what this determines> |

## 4. User scenarios

### Primary scenario

1. <action>
2. <observable result>

### Errors and edge cases

- <condition> -> <expected behavior>

## 5. Requirements and acceptance criteria

- [ ] AC-01: <observable user or contract result>.
- [ ] AC-02: <observable result>.

### Invariants

- <behavior that must remain true>.

## 6. Technical boundaries

### Affected layers and contracts

- <layer or contract> — <change or preserved behavior>.

### Data and migration

<Schema, backfill, compatibility, and rollback, or why none is required.>

### Security and privacy

<Permissions, validation, and sensitive data, or why none is affected.>

### Performance and concurrency

<Load, races, caching, or why none is affected.>

### Observability and errors

<How failures are detected and diagnosed.>

### Versioning and release

<Authoritative version source, current/next version, changelog/docs synchronization, and whether a release action is authorized.>

## 7. Validation and review

- Primary signal: <main proof>.
- Red signal: <failing test/reproduction and intended reason, or why not applicable/practical>.
- Minimality decision: <omitted as unneeded | reused existing | standard library | native platform | installed dependency | custom owner-layer | not applicable — evidence>.
- Focused green: `<exact command or scenario>` -> <result>.
- Targeted checks: `<command or scenario>`.
- Wider checks: `<risk-based command or scenario>`.
- Manual/runtime check: <if required>.
- Starting review tier: <tier and evidence>.
- Required final tier: <tier and evidence>.
- Review focus: <correctness, security, data, UX, etc.>.

## 8. Milestones

### M1. <coherent outcome>

- Status: Pending | In progress | Complete
- Scope: <included work>
- Excludes: <excluded work>
- Implementation mode: Direct | Investigation | TDD-first
- Red signal: <test/reproduction and expected failure, or not applicable with reason>
- Minimality decision: <selected rung, skipped complexity, and any ceiling/upgrade trigger>
- Focused green: `<command or scenario>` -> <result>
- Validation: `<commands or scenarios>`
- Acceptance: AC-01, AC-02
- Review: Pending | Accepted — <mode/tier/confidence>
- Version: unchanged | `<previous> -> <next>` — <impact/evidence>
- Commit: Pending | `<sha>` | Not applicable

## 9. Risks and blind spots

| Risk | Likelihood/impact | Mitigation | Status |
|---|---|---|---|
| <risk> | <assessment> | <action> | Open/Handled/Accepted |

## 10. Open questions

Blocking product questions:

- None.

Non-blocking assumptions:

- <assumption and how it will be verified>.

## 11. Execution and validation log

### YYYY-MM-DD — <stage>

- Changed: <summary>.
- Primary signal: met | not met | partially validated.
- Validation: `<command>` -> <result>.
- Minimality decision: <selected rung and evidence>.
- Review: <mode, tier, verdict, confidence, and material decisions>.
- Version: <impact, previous/next value, synchronized files, or not applicable>.
- Commit: `<sha>` | not created.
- Remaining: <next step or none>.
```

## Quality gate

- Every required outcome has an observable acceptance criterion.
- Repository evidence supports decisions without becoming a raw code dump.
- Product decisions are separate from autonomous technical choices.
- Complexity and routing claims use actual risk and runtime evidence.
- Every Build-created commit in a versioned repository receives a unique higher version by default; required manifest, changelog, and documentation updates stay in the same commit.
- Broad code discovery records delegation or an honest root fallback, with critical findings verified by the root.
- TDD-first milestones record an intended red signal, owner-layer implementation, and focused green evidence, or explain why an automated red signal was impractical.
- Implementation milestones record an evidence-backed minimality decision without weakening acceptance criteria or safeguards.
- Milestones deliver coherent outcomes rather than arbitrary file groups.
- Validation commands exist or are explicitly marked as proposed.
- Blocking questions are empty before implementation starts.
- `Complete` is supported by acceptance evidence, green validation, and review.
