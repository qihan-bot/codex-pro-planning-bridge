---
name: pro-planning
description: Generate and validate a local-first ChatGPT Pro architecture plan before complex coding tasks.
---

# Pro Planning Skill

Use this skill before:

- architecture changes
- large refactors
- database migrations
- security-sensitive changes
- multi-module modifications

Workflow:

1. Run `codex-pro-planning-bridge collect --repo .` from the project root.
2. Run `codex-pro-planning-bridge request --repo . --goal "<user request>"`.
3. Inspect `.codex/pro-plan/REQUEST.md` and remove any local details the user does not want to share.
4. Ask the user to paste the reviewed request into ChatGPT Pro manually; do not use an API or automated browser flow.
5. Save the response as `.codex/pro-plan/PLAN.md`.
6. Run `codex-pro-planning-bridge validate --repo .` and report errors or warnings.
7. Use the validated plan as an input to implementation, confirming any open questions first.
8. After implementation, run `codex-pro-planning-bridge diff --repo . --base <baseline>` to detect drift.
9. Initialize or update `.codex/project-memory/` with `codex-pro-planning-bridge memory init` and `memory record-plan`.

When the package is installed, the equivalent command is:

`codex-pro-planning-bridge request --repo . --goal "<user request>"`

The collector is local-only, bounded, and excludes secret-looking files such as `.env`, credentials, private keys, and secret directories from excerpts. It still produces a file inventory note for redacted paths so the planning model can see that context was intentionally omitted.

The original `scripts/` files remain compatibility wrappers for direct checkout use. Avoid the workflow for trivial edits.
