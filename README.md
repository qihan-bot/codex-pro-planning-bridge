# Codex Pro Planning Bridge

Release status: **v0.2.0-beta** (`0.2.0b1`).

Codex Pro Planning Bridge is a local-first Python CLI and Codex skill for turning a complex coding request into a structured architecture review for ChatGPT Pro. Codex remains the implementation agent; ChatGPT Pro is the human-reviewed planning step.

The bridge has no OpenAI API integration, does not require an API key, and never submits a prompt automatically.

## Complete planning loop

```text
collect repository context locally
        ↓
generate REQUEST.md
        ↓
human reviews and pastes REQUEST.md into ChatGPT Pro
        ↓
save the response as PLAN.md
        ↓
validate PLAN.md against repository facts
        ↓
Codex implements the approved plan
        ↓
compare PLAN.md with local Git changes
        ↓
persist decisions and project knowledge
```

## Installation

Requires Python 3.10 or newer. The package has no runtime dependencies.

```bash
python -m pip install -e .
```

When running directly from a checkout without installation, prefix commands with `PYTHONPATH=src`.

## Usage

All workflow operations use the single `codex-pro-planning-bridge` entry point:

```bash
# Collect .codex/pro-plan/repo-tree.txt, git-status.txt, and project-context.md.
codex-pro-planning-bridge collect --repo .

# Collect context and generate .codex/pro-plan/REQUEST.md.
codex-pro-planning-bridge request \
  --repo . \
  --goal "Add the requested feature while preserving the current public API"

# Show the manual handoff checklist.
codex-pro-planning-bridge handoff --repo .

# Optionally copy REQUEST.md and open ChatGPT for a human-controlled handoff.
codex-pro-planning-bridge open --repo . --no-pause

# After manually saving the Pro response as PLAN.md, validate it locally.
codex-pro-planning-bridge validate \
  --repo . \
  --plan .codex/pro-plan/PLAN.md

# Compare the plan with changes made after a known baseline.
codex-pro-planning-bridge diff \
  --repo . \
  --plan .codex/pro-plan/PLAN.md \
  --base HEAD~1

# Initialize and maintain persistent project knowledge.
codex-pro-planning-bridge memory init --repo .
codex-pro-planning-bridge memory show --repo .
codex-pro-planning-bridge memory record-plan --repo .
```

`diff --base <commit-or-ref>` compares the working tree with that Git baseline. Without `--base`, the engine compares staged and unstaged changes with `HEAD` and includes untracked files. The report is written to `.codex/pro-plan/PLAN_DIFF.md` and classifies steps as `Completed`, `Missing`, `Changed / Drift`, or `Blocked`, while also listing unplanned changed files.

The four persistent memory documents live in `.codex/project-memory/`:

```text
.codex/project-memory/
├── architecture.md
├── decisions.md
├── constraints.md
└── known-issues.md
```

They are ordinary Markdown files. `memory init` is idempotent, `memory write` can replace or append a document, and `memory record-plan` stores the Summary and Architecture sections of a local `PLAN.md` in `decisions.md`.

## Compatibility scripts

The original checkout scripts remain as thin wrappers for users of the v0.1 workflow. They delegate to the same package implementation as the unified CLI:

```bash
python scripts/collect_context.py
python scripts/build_prompt.py --goal "Add a safe export command"
python scripts/open_chat.py
python scripts/validate_plan.py
python scripts/plan_diff.py --base HEAD~1
python scripts/memory.py init
```

The generated `.codex/pro-plan/` directory contains `repo-tree.txt`, `git-status.txt`, `project-context.md`, `REQUEST.md`, `VALIDATION_REPORT.md`, and `PLAN_DIFF.md`. Planning artifacts are ignored by Git; `.codex/project-memory/` remains versionable project documentation.

## Plan Validator and Repository Fact Checker

The validator performs local static checks for:

- referenced paths and repository ownership;
- import-style modules;
- classes, functions, methods, and API symbols discoverable from source;
- declared dependencies and common framework aliases; and
- structural completeness, risks, and unresolved questions in the plan.

Findings are grouped as `ERROR`, `WARN`, or `OK`. The fact checker never executes project code and never makes a network request. If the collected context artifacts are missing, it uses a live local repository scan.

## Privacy and safety defaults

- Collection and validation are local-only.
- Git-tracked and untracked files are read through `git ls-files --exclude-standard` when available.
- Secret-looking files such as `.env`, credentials, private-key files, and secret directories are excluded from scans and excerpts.
- File and excerpt limits prevent unexpectedly large prompts.
- The bridge may open the ChatGPT website and copy a request locally, but it never calls an API or submits content automatically.
- `REQUEST.md`, `PLAN.md`, validation reports, and diff reports should be reviewed as project-local artifacts.

## Codex skill

The `skills/pro-planning/SKILL.md` skill describes when to use the bridge and the required request/plan loop. It is intentionally scoped to architecture changes, large refactors, migrations, security-sensitive work, and other tasks where a written plan reduces implementation risk.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The project is packaged with `pyproject.toml` and exposes the `codex-pro-planning-bridge` console script.

## Roadmap status

- [x] v0.1 MVP: context collector, prompt generator, manual Pro handoff
- [x] Plan Validator and Repository Fact Checker
- [x] Project Memory
- [x] Plan Diff Engine
- [x] Unified CLI and compatibility wrappers
- [x] v0.2.0-beta
- [ ] v0.3 proactive planning assistance

## License

MIT
