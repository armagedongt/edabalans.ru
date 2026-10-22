---
# Creation date (YYYY-MM-DD)
created: 2026-10-21

# Status: draft | approved
status: draft

# Work type: feature | bug | refactoring
type: feature
---

# User-spec: finance-actuals

> **Не готово к исполнению.** Интервью продолжается. Этот файл пока только
> инициализированный шаблон, не ТЗ для реализации. Согласованная рамка и вопросы —
> [scope.md](scope.md), дословные ответы — `logs/userspec/interview.yml`.
> Не выполнять инструкцию исполнителю ниже до заполнения и утверждения ТЗ.
> Локальный рабочий прототип отдельно разрешён Сергеем 22.10.2026 и описан в
> `README.md`; это разрешение не означает утверждения полного production-контура.

> **Executor instruction.** If the project has Project Knowledge, first read the documentation
> entrypoint declared by its `AGENTS.md` or existing router (for example `docs/README.md` or a
> Project Knowledge `SKILL.md`), then only the materials relevant to this task.
> Read `decisions.md` if it exists. Work from
> the root of the project this spec belongs to. Implement the entire user-spec. Use the execution
> skills appropriate to the work.

## What We Are Building
[2–3 sentences describing the feature or fix]

## Why
[The problem being solved and the value created]

## Expected Behavior
[Describe the user flow in free form:
1. The user does X.
2. The system responds with Y.
3. The user gets Z.]

## Acceptance Criteria
- [ ] [Criterion 1 — observable result]
- [ ] [Criterion 2]
- [ ] [Criterion 3]

## Constraints
[Technical and business constraints: compatibility, security, scalability]

## Risks
- **Risk 1:** [what could go wrong]. **Mitigation:** [action].
- **Risk 2:** [description]. **Mitigation:** [action].

[If no risks were identified, write "No risks identified."]

## Accepted Decisions
- Chose [X] because [Y].
- Chose [X] instead of [Y] because [Z].

[Record interview decisions in plain language. Include rejected alternatives only when they help explain a decision.]

## Testing

**Unit tests:** [what is covered / "not needed — no new logic is added"] — [reason].

**Integration tests:** [needed / not needed] — [reason].

**E2E tests:** [needed / not needed] — [reason].

## Verification

### Agent Verification

| Step | Expected Result |
|------|-----------------|
| [1. Action description] | [What should happen] |
| [2. Action description] | [Expected result] |

### User Verification
- [What to verify — how to verify — why manual verification is needed]

[If the agent verifies everything, remove the "User Verification" subsection.]

