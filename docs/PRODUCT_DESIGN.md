# Codex Pro Planning Bridge Product Design

## Overview

Codex Pro Planning Bridge separates software execution from high-level project planning. Codex owns repository inspection and implementation; ChatGPT Pro provides an optional architecture review after a human chooses what context to share.

## Core Idea

- Codex is the implementation engineer.
- The bridge collects a bounded local context and writes `REQUEST.md`.
- A human reviews and pastes the request into ChatGPT Pro.
- The response is saved as `PLAN.md`, checked for planning completeness, and handed back to Codex.

## Architecture

```text
User Request
    |
    v
Codex skill / CLI
    |
    v
Local context collector ---- redacts secret-looking files
    |
    v
REQUEST.md ---------------- human review boundary
    |
    v
ChatGPT Pro (manual paste)
    |
    v
PLAN.md
    |
    v
Plan validator
    |
    v
Codex implementation
```

## Principles

1. No API dependency for planning.
2. No automated browser scraping or submission.
3. Local-first context collection with explicit size limits.
4. Sensitive-looking files are excluded from content excerpts by default.
5. Human confirmation is required before Pro handoff.
6. A plan must state assumptions, implementation steps, validation, and risks.

## MVP Components

- plugin manifest in `.codex-plugin/plugin.json`
- Codex skill in `skills/pro-planning/SKILL.md`
- local context collector in `src/codex_pro_planning_bridge/context.py`
- prompt builder in `src/codex_pro_planning_bridge/prompt.py`
- manual handoff helper in the CLI
- plan validator in `src/codex_pro_planning_bridge/plan.py`

## CLI contract

| Command | Purpose | Artifact |
| --- | --- | --- |
| `collect` | Capture bounded repository metadata and excerpts | `CONTEXT.md` |
| `request` | Add the user goal and planning contract | `REQUEST.md` |
| `handoff` | Print the human-only transfer checklist | none |
| `validate` | Check a returned plan for required sections | validation result |

## Future

- project memory with explicit user-controlled storage
- architecture review loop and plan diffs
- richer repository adapters while preserving the local-only default
