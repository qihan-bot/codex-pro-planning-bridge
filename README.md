# Codex Pro Planning Bridge

Codex Pro Planning Bridge is a local-first Python CLI and Codex skill for turning a complex coding request into a structured architecture review for ChatGPT Pro.

Codex remains the implementation agent. ChatGPT Pro is used as a human-reviewed planning step, with no API dependency and no automated browser submission.

## Workflow

```text
Codex
  -> collect bounded repository context locally
  -> generate REQUEST.md
  -> human reviews and pastes REQUEST.md into ChatGPT Pro
  -> save the response as PLAN.md
  -> validate PLAN.md
  -> Codex implements the approved plan
```

## Quick start

Requires Python 3.10 or newer. The package has no runtime dependencies.

```bash
python -m pip install -e .

# Generate a bounded, redacted repository context.
codex-pro-planning-bridge collect --repo . --output CONTEXT.md

# Generate the request to review and paste into ChatGPT Pro.
codex-pro-planning-bridge request \
  --repo . \
  --goal "Add the requested feature while preserving the current public API" \
  --output REQUEST.md

# Print the human handoff checklist.
codex-pro-planning-bridge handoff --request REQUEST.md --plan PLAN.md

# Validate the returned plan before implementation.
codex-pro-planning-bridge validate --plan PLAN.md
```

The v0.1 scripts can also be run directly from a checkout, which is useful before installing the package:

```bash
python scripts/collect_context.py
python scripts/build_prompt.py --goal "Add a safe export command"
python scripts/open_chat.py
# After manually obtaining the Pro response and saving it as PLAN.md:
python scripts/validate_plan.py
```

The scripts create `.codex/pro-plan/` with `repo-tree.txt`, `git-status.txt`, `project-context.md`, `REQUEST.md`, and (after validation) `VALIDATION_REPORT.md`. The generated directory is ignored by Git by default because it may contain project-specific planning context.

The same commands work without installation from a checkout:

```bash
PYTHONPATH=src python -m codex_pro_planning_bridge request --goal "Review this change"
```

## Privacy and safety defaults

- Collection is local-only and makes no network calls.
- Git-tracked and untracked files are read through `git ls-files --exclude-standard` when available.
- Secret-looking files such as `.env`, credentials, private-key files, and secret directories are excluded from excerpts.
- File and excerpt limits prevent unexpectedly large prompts. Adjust them explicitly when needed.
- The bridge may open the ChatGPT website and copy the request locally, but it never calls an API or submits content automatically.
- `REQUEST.md` is a draft: inspect it and remove any local details before manual handoff.

## Codex skill

The `skills/pro-planning/SKILL.md` skill describes when to use the bridge and the required request/plan loop. It is intentionally scoped to architecture changes, large refactors, migrations, security-sensitive work, and other tasks where a written plan reduces implementation risk.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The project is packaged with `pyproject.toml` and exposes the `codex-pro-planning-bridge` console script.

## Roadmap

- [x] Product design
- [x] Plugin manifest
- [x] Codex skill
- [x] Context collector
- [x] Prompt generator
- [x] Plan validator
- [ ] Project memory and architecture review loop

## License

MIT
