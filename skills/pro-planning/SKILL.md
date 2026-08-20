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

1. Run `cpb loop --repo . --goal "<user request>"` for the resumable v0.3 workflow, or run `cpb init --repo .` when preparing artifacts manually.
2. Run `cpb collect --repo .` or `cpb prompt --repo . --goal "<user request>"` when the manual stages are preferred.
3. Inspect `.codex/pro-plan/REQUEST.md` and remove any local details the user does not want to share.
4. Ask the user to paste the reviewed request into ChatGPT Pro manually; do not use an API or automated browser flow.
5. Save the response as `.codex/pro-plan/PLAN.md`.
6. Run `cpb validate --repo .` and report errors or warnings.
7. After human review, run `cpb approve --repo . --approved-by user`; the bridge will not enter `IMPLEMENTING` without this matching approval record.
8. Use the validated and approved plan as an input to implementation, confirming any open questions first.
9. Use `cpb status`, `cpb pause`, `cpb resume`, `cpb cancel`, and `cpb history` to inspect or recover interrupted workflows.
10. After implementation, run `cpb diff --repo . --base <baseline>` to detect drift, including renamed paths.
11. Initialize or update `.codex/project-memory/` with `cpb memory init`, `cpb memory list`, and `cpb memory record-plan`; use `memory migrate` for old metadata and `memory adr-create` for explicit decisions.
12. Use `cpb loop --review --base <baseline>` after implementation to write the diff report and persist the planning record.

When the package is installed, the equivalent command is:

`cpb prompt --repo . --goal "<user request>"`

The collector is local-only, bounded, and excludes secret-looking files such as `.env`, credentials, private keys, and secret directories from excerpts. It produces both human-readable Markdown and `.codex/pro-plan/context.json`; the JSON artifact contains only local scan metadata and bounded excerpts. It still produces a file inventory note for redacted paths so the planning model can see that context was intentionally omitted.

The original `scripts/` files remain compatibility wrappers for direct checkout use. Avoid the workflow for trivial edits.
