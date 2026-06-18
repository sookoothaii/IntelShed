---
name: review
description: >-
  Audit deliverables against the project brief requirement by requirement.
  Use when the user runs /review or asks to verify work matches briefs/*.md.
disable-model-invocation: true
---

# Review

When the user runs `/review`, compare the current output against the brief in `briefs/` and decide whether every requirement is fully met.

## Resolve the brief file

Use the same rules as `/create`:

1. User-named path if provided.
2. Else `briefs/current.md`.
3. Else ask which `briefs/*.md` to use.

## Review process

1. Read the full brief (**Objective**, **Requirements**, **Audience and tone**, **Definition of done**).
2. Inspect the current codebase, files, or artifacts that `/create` produced.
3. Go **requirement by requirement**. For each brief item, mark **Pass** or **Fail**.
4. For every **Fail**, name the **exact brief item** it violates and write the **specific fix** needed (file, change, or missing behavior).
5. Check **Definition of done** the same way — each criterion must pass independently.

## Output format

```markdown
# Review: [brief title]

**Brief:** briefs/{slug}.md

## Requirements

| # | Requirement | Result | Gap / fix |
|---|-------------|--------|-----------|
| 1 | [from brief] | Pass / Fail | [specific fix if Fail; "—" if Pass] |

## Definition of done

| Criterion | Result | Gap / fix |
|-----------|--------|-----------|
| [from brief] | Pass / Fail | [specific fix if Fail] |

## Verdict

**PASS** — all requirements and definition-of-done criteria met.

— or —

**FAIL** — [N] item(s) outstanding. Run `/create` with the fixes below.
```

## Pass / fail rules

- **Only pass** when **every** requirement and **every** definition-of-done criterion is fully met.
- If anything fails, include a **Fixes for /create** section: numbered, actionable, mapped to brief items. Do not hand-wave (“improve tone”) — state what to change and where.
- Do not approve partial work. “Close enough” is **Fail**.

## After a fail

Tell the user to run `/create` again with the fix list. After fixes, run `/review` again until verdict is **PASS**.
