# Evidence-gated minimality protocol

Use this protocol after the Ready gate for every implementation, remediation, and behavior-preserving refactor in `run` and `full`. Apply it only after repository evidence, acceptance criteria, invariants, and the owning layer are understood. It selects the smallest justified technical means; it does not silently reopen accepted product scope.

## Preconditions

- Confirm the current acceptance criteria, invariants, risk class, and repository conventions.
- Trace the affected flow to its source of truth before choosing a smaller implementation.
- Treat current code, supported test paths, installed dependencies, and platform capabilities as evidence rather than assumptions.
- If new evidence creates a material product choice, return to the specification interview. Otherwise make the technical decision autonomously and record it.

## Decision ladder

Evaluate every proposed code element, file, dependency, abstraction, configuration surface, and compatibility layer in this order. Stop at the first option that satisfies the whole accepted requirement and its risk constraints:

1. **Does it need to exist now?** Omit work that serves no acceptance criterion, invariant, confirmed current need, or required repository policy. Do not build speculative flexibility.
2. **Does the repository already solve it?** Reuse the existing source of truth, helper, type, component, query, test utility, or established pattern. Do not duplicate decision logic.
3. **Does the standard library solve it?** Prefer the supported standard-library capability when it meets the contract and edge cases.
4. **Does the native platform solve it?** Prefer browser, framework, database, operating-system, protocol, or deployment-platform primitives when they meet accessibility, compatibility, and operational requirements.
5. **Does an already-installed dependency solve it?** Reuse it when doing so matches repository conventions and does not create a worse boundary. Do not add a new production dependency for convenience alone.
6. **Only then, write custom code.** Make the minimum coherent change in the owning layer so every affected caller follows the same rule. Prefer removing or replacing current complexity over adding a parallel path.

Minimum means the fewest justified concepts and moving parts, not the fewest characters. A one-line patch in the wrong layer, duplicated guards in callers, or compressed code that hides behavior is not minimal.

## Non-negotiable safeguards

- Preserve every explicit acceptance criterion and invariant. Question optional scope before the Ready gate, not by silently omitting it during implementation.
- Never trade away trust-boundary validation, authentication, authorization, privacy, accessibility, data-loss prevention, error handling, observability, compatibility, migration or rollback safety, concurrency correctness, or required performance.
- Use the repository's supported test conventions and risk-appropriate coverage. Do not replace them with a smaller ad hoc check merely to reduce code.
- Keep an abstraction or configuration surface when current evidence, repository architecture, or more than one real consumer justifies it; record that evidence instead of treating all abstraction as waste.
- When a deliberate simplification has a known ceiling, record the ceiling and the observable trigger for upgrading it in the specification. Do not add a speculative upgrade path now.

## Required milestone record

Record the selected rung and evidence:

```text
Minimality decision: omitted as unneeded | reused existing | standard library | native platform | installed dependency | custom owner-layer | not applicable — <path:line, contract, or runtime evidence>
Skipped complexity: <dependency, abstraction, file, configuration, or none>
Ceiling/upgrade trigger: <known limit and observable trigger, or none>
```

Use `custom owner-layer` only after the earlier rungs were checked. Use `not applicable` only when the milestone contains no implementation or remediation decision.

## Reviewer checks

Review the completed diff for evidence-backed complexity findings:

- duplicated behavior that an existing source of truth already owns;
- custom code where the standard library or native platform fully covers the contract;
- a new dependency when existing code or an installed dependency is sufficient;
- a single-use abstraction, wrapper, flag, configuration surface, or compatibility layer without a current requirement;
- a downstream symptom patch instead of one owner-layer correction;
- extra files or parallel paths that do not improve an acceptance criterion, invariant, or required boundary.

Do not score minimality by line count. Report a finding only when removing or replacing the complexity preserves accepted behavior and risk coverage.
