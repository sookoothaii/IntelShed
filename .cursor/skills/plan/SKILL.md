---
name: plan
description: >-
  Interview the operator and write a project brief before any build work.
  Use when the user runs /plan or asks to plan, scope, or brief a new
  feature, artifact, or deliverable.
disable-model-invocation: true
---

# Plan

Formal written brief for larger WorldBase work. Day-to-day tasks follow **Clarify before build** in `.cursor/rules/worldbase-workflow.mdc` (ask until the operator says go; skip when scope is obvious).

When the user runs `/plan`, interview them about what they want to create. Ask **one focused question at a time** until you fully understand the goal, the must-have requirements, the audience, the tone, and what a great result looks like. **Do not start creating anything yet.**

## Interview topics

Cover these areas before writing the brief (order can vary; skip only what is already clear):

1. **Goal** — What are we building and why?
2. **Must-have requirements** — Non-negotiable features, constraints, integrations, formats.
3. **Audience** — Who will use or read this?
4. **Tone** — Voice, style, formality, brand or project conventions.
5. **Definition of done** — What does “great” look like? How will we know it is finished?

## Rules

- One question per turn. Wait for the answer before the next question.
- Do not implement, scaffold, or draft the deliverable during `/plan`.
- If the user gives partial answers, follow up until each area is concrete enough to write testable requirements.
- Early in the interview, agree on a brief filename: `briefs/{slug}.md` (kebab-case slug from the project title). Default: `briefs/current.md`.

## When you have enough

Write a clear, detailed brief and **save it** to the agreed path under `briefs/`.

The brief **must** include these sections:

```markdown
# [Title]

**Brief path:** briefs/{slug}.md

## Objective
[What we are building and why]

## Requirements
[Exact, numbered must-haves — each item must be verifiable]

## Audience and tone
[Who this is for and how it should read/feel]

## Definition of done
[Concrete, checkable criteria for “complete”]
```

## After saving

Tell the user the brief path and suggest `/create` when they are ready to build, then `/review-brief` to audit against the brief.
