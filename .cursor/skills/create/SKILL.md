---
name: create
description: >-
  Build exactly what the active project brief describes — no scope creep.
  Use when the user runs /create or asks to implement from briefs/*.md.
disable-model-invocation: true
---

# Create

When the user runs `/create`, read the brief in `briefs/` and create **exactly** what it describes. **Do not add things that aren't in the brief or make assumptions about what the user might also want.**

## Resolve the brief file

1. If the user names a path (e.g. `/create briefs/onboarding.md`), use that file.
2. Otherwise read `briefs/current.md`.
3. If neither exists, list `briefs/*.md` and ask which brief to use — do not guess.

## Workflow

1. Read the full brief before touching code or content.
2. Implement only what **Objective**, **Requirements**, and **Definition of done** specify.
3. Match **Audience and tone** for any user-visible copy.
4. Do not expand scope, add “nice extras”, or refactor unrelated code unless a requirement explicitly asks for it.
5. If a requirement is ambiguous, ask one clarifying question — do not invent an interpretation.

## When you finish

List which brief requirements you covered so the review step can check them. Use this format:

```markdown
## Requirements coverage

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1 | [text from brief] | Done / Partial / Blocked | [file or artifact] |
...

## Definition of done

| Criterion | Met? | Evidence |
|-----------|------|----------|
| [from brief] | Yes / No | [how verified] |
```

If any requirement is **Partial** or **Blocked**, say why before claiming completion.

When all requirements are **Done**, suggest `/review-brief` to verify against the brief.
