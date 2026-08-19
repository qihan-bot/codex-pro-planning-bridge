---
name: pro-planning
description: Generate a ChatGPT Pro architecture planning request before complex coding tasks.
---

# Pro Planning Skill

Use this skill before:

- architecture changes
- large refactors
- database migrations
- security-sensitive changes
- multi-module modifications

Workflow:

1. Collect repository context.
2. Generate REQUEST.md.
3. Ask user to obtain ChatGPT Pro planning output.
4. Save result as PLAN.md.
5. Validate assumptions.
6. Implement changes.

Avoid for trivial edits.
