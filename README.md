# Codex Pro Planning Bridge

Release status: **v0.3.3 Reliability Layer** (`v0.3.3-beta.1`).

Development status: **v0.4 Phase 1 — Repository Registry** (`feat/v0.4-repository-registry`, Draft PR review gate).

Codex Pro Planning Bridge is a local-first Python CLI and Codex skill for turning a complex coding request into a structured architecture review for ChatGPT Pro. Codex remains the implementation agent; ChatGPT Pro is the human-reviewed planning step.

The bridge has no OpenAI API integration, does not require an API key, and never submits a prompt automatically.

v0.3 turns those components into a recoverable planning loop. The published
`v0.3.1-beta` safety layer adds an append-only event audit log, a human approval
gate before implementation, workflow recovery commands, and a local symbol
relationship graph. v0.3.2 hardens that boundary with approval hash binding,
read-only event queries, auditable workflow rollback, and broader graph tests.
`v0.3.3-beta.1` completes the reliability layer with versioned runtime
snapshots, fail-closed recovery, pre-resume integrity checks, and an explicit
approval lifecycle. The beta.1 hardening pass adds continuous approval
invariants, post-recovery runtime baselines, atomic state/history/event writes,
strict event-ledger parsing, repository drift checks, and snapshot schema
validation. Workflow state and transition history remain persisted locally, and
the bridge pauses at the explicit Codex implementation boundary. It still has
no OpenAI API integration, browser scraping, API key configuration, or
autonomous source-code modification.

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

For local development with the repository quality checks:

```bash
python -m pip install -e ".[dev]"
```

When running directly from a checkout without installation, prefix commands with `PYTHONPATH=src`.

## Usage

All workflow operations use the single `codex-pro-planning-bridge` entry point:

```bash
# Initialize context artifacts and project memory.
cpb init --repo .

# Collect .codex/pro-plan/repo-tree.txt, git-status.txt, project-context.md, and context.json.
cpb collect --repo .

# Collect context and generate .codex/pro-plan/REQUEST.md.
cpb prompt --repo . --goal "Add the requested feature while preserving the current public API"

# Show the manual handoff checklist.
cpb handoff --repo .

# Optionally copy REQUEST.md and open ChatGPT for a human-controlled handoff.
cpb open --repo . --no-pause

# After manually saving the Pro response as PLAN.md, validate it locally.
cpb validate --repo . --plan .codex/pro-plan/PLAN.md

# Record explicit human approval before implementation can begin.
cpb approve --repo . --plan .codex/pro-plan/PLAN.md --approved-by user

# Compare the plan with changes made after a known baseline.
cpb diff --repo . --plan .codex/pro-plan/PLAN.md --base HEAD~1

# Initialize and maintain persistent project knowledge.
cpb memory init --repo .
cpb memory list --repo .
cpb memory show --repo .
cpb memory migrate --repo .
cpb memory record-plan --repo .
cpb memory adr-create --repo . --title "Keep the workflow local"

# Advance the recoverable v0.3 workflow. Repeat after each human/Codex step.
cpb loop --repo . --goal "Add the requested feature"
# After ChatGPT Pro returns a reviewed PLAN.md:
cpb loop --repo .
# After Codex implements the approved plan:
cpb loop --repo . --review --base HEAD

# Inspect or recover a workflow without advancing it implicitly.
cpb status --repo .
cpb resume --repo .
cpb pause --repo .
cpb cancel --repo .
cpb history --repo .

# Query the append-only audit log without changing workflow state.
cpb events --repo .
cpb events --repo . --event WORKFLOW_ROLLBACK --format json
cpb events --repo . --actor user --limit 20

# Restore workflow metadata to an earlier event; source files are untouched.
cpb rollback --repo . --to 3 --reason "retry validation"

# Capture and inspect complete local workflow runtime snapshots.
cpb snapshot create --repo .
cpb snapshot list --repo .
cpb snapshot show --repo . --id latest

# Restore only workflow metadata from a validated snapshot.
cpb recover --repo . --snapshot latest

# Optional approval validity window and explicit revocation.
cpb approve --repo . --plan .codex/pro-plan/PLAN.md --approved-by user --expires-in 3600
cpb approve --repo . --revoke --reason "plan needs another review"
```

## v0.4 Phase 1: Repository Registry

The first v0.4 implementation adds a per-user, versioned repository allowlist
for future read-only MCP access. The local CLI remains the authority for
registration; MCP is not implemented on this branch and must receive only a
registered `repository_id` in a later phase.

```bash
# Register a Git repository. The CLI canonicalizes the path and asks for confirmation.
cpb repo add my-app D:\Projects\my-app

# Register a non-Git directory only with explicit opt-in.
cpb repo add notes D:\Notes --allow-non-git --yes

cpb repo list
cpb repo list --format json
cpb repo show my-app
cpb repo doctor my-app
cpb repo remove my-app
```

The registry is stored in the current user's platform configuration directory
as `repositories.json`. A local `CPB_REGISTRY_PATH` environment override (or
`--registry-path`, intended for tests and managed deployments) is available to
the CLI; it is not a model-facing or MCP input. Writes are schema-versioned,
lock-protected, atomic, and fail closed when the existing file is corrupt or
newer than the supported schema. Root directories, the user home directory,
credential/secret roots, symlink or junction escapes, and sensitive paths are
rejected or redacted. Removing a registration never touches repository files.

Phase 1 intentionally does not add an MCP server, Plan Capsule, client
integration, Skills split, browser automation, OpenAI API call, or API-key
configuration. See [`docs/v0.4/REGISTRY_PHASE1.md`](docs/v0.4/REGISTRY_PHASE1.md)
for the implementation boundary and verification notes.

The full codex-pro-planning-bridge command remains available as the long-form equivalent of cpb. The older request command is retained as an alias for prompt.

`diff --base <commit-or-ref>` compares the working tree with that Git baseline. Without `--base`, the engine compares staged and unstaged changes with `HEAD` and includes untracked files. The report is written to `.codex/pro-plan/PLAN_DIFF.md` and classifies steps as `Completed`, `Missing`, `Changed / Drift`, or `Blocked`, while also listing unplanned changed files.

The persistent memory documents live in `.codex/project-memory/`. Existing v0.2 files remain valid, while new decisions use numbered ADR files:

```text
.codex/project-memory/
├── architecture.md
├── decisions.md
├── constraints.md
├── known-issues.md
├── memory.json
├── migrations/
│   └── 0002-add-versioned-migrations.md
└── adr/
    ├── 0001-database.md
    └── 0002-api-design.md
```

They are ordinary Markdown and JSON files. `memory init` is idempotent, `memory list` shows versioned metadata and ADRs, `memory adr-create` creates the next ADR, and `memory record-plan` stores the Summary and Architecture sections of a local `PLAN.md` as an accepted ADR while keeping a compatibility link in `decisions.md`.

The generated `.codex/pro-plan/context.json` is the machine-readable counterpart to the human-facing Markdown context. It contains detected project types, bounded file metadata, dependencies, Git state, and redaction notes. `cpb loop` also creates local `symbol-index.json` and `symbol-graph.json` baselines for symbol-level drift review.

## v0.3 recoverable planning loop

`cpb loop` advances one local session through explicit states:

```text
NEW_TASK → CONTEXT_READY → PLAN_READY → VALIDATING
                                      ↓ approval
                              IMPLEMENTING
                                      ↓
                              REVIEWING → COMPLETED
                    active state ↔ PAUSED → CANCELLED
```

The current state is `.codex/workflow/state.json` and every transition is
recorded in `.codex/workflow/history.json`. The append-only audit trail is
`.codex/workflow/events.jsonl`. If the process stops, run `cpb resume` or the
same loop command again. When `PLAN.md` is absent, the loop stops after
generating `REQUEST.md`; it never assumes that ChatGPT Pro was contacted. When
validation passes, it requires a matching `.codex/pro-plan/APPROVAL.json`
before entering `IMPLEMENTING`. `--review` then generates `PLAN_DIFF.md`,
reports file and symbol changes, and records the plan in Project Memory.

The approval record must include the exact repository-relative plan path and
SHA-256 hash of the current `PLAN.md`; editing the plan invalidates the
approval. `cpb events` queries the existing `.codex/workflow/events.jsonl`
without initializing or rewriting state. It supports `--event`, `--actor`,
`--from-state`, `--to-state`, `--since`, `--until`, `--limit`, and
`--format json`; results include stable one-based indexes. `cpb rollback --to N`
restores only workflow metadata to event `N` and appends a
`WORKFLOW_ROLLBACK` event, preserving all earlier audit records and repository
files.

### v0.3.3 Reliability Layer: Runtime snapshots and recovery

The first v0.3.3 component captures a complete local runtime context under
`.codex/workflow/snapshots/`. Numbered JSON files such as
`001.json` are immutable, while `latest.json` is a deterministic
copy of the newest snapshot. Each snapshot records the workflow state and
event position, the repository-relative plan path and SHA-256, current
approval binding metadata, the Git commit and dirty flag, and the Project
Memory version.

Snapshot creation is read-only with respect to source files, `PLAN.md`,
approval artifacts, event records, and Project Memory; it only writes the new
numbered snapshot and `latest.json`. `cpb recover` validates the selected
snapshot, restores workflow metadata, and appends a compensating
`WORKFLOW_RECOVERED` event without deleting history or changing source files.

`cpb resume` runs a read-only Workflow Integrity check before advancing the
loop. It compares state, event position, plan path and hash, approval binding,
Git commit/dirty state, and Project Memory metadata. A failed check prints an
actionable diagnostic and blocks resume. `cpb pause` creates a runtime
snapshot baseline automatically so a paused workflow has a recoverable context.

The `v0.3.3-beta.1` reliability hotfix also keeps the implementation boundary
safe after state changes: revoking, expiring, or editing an approval pauses an
active implementation workflow, and resume/rollback/recovery cannot restore an
implementation state without a current matching approval. Runtime artifacts
are written atomically, malformed or truncated event records fail closed, and
successful resume/recovery/approval/rollback operations create a fresh
integrity baseline.

Approval records expose `APPROVED`, `INVALIDATED`, `EXPIRED`, and `REVOKED`
statuses. Editing the plan invalidates its hash binding, `--expires-in` creates
a local validity window, and `--revoke` records an explicit revocation. Only
an effective approval whose path and SHA-256 match the current plan can enter
the implementation state.

The local repository intelligence layer is in
`src/codex_pro_planning_bridge/intelligence/symbol_index.py` and
`symbol_graph.py`. They support Python AST extraction and conservative
JavaScript/TypeScript and Rust symbol and relationship extraction without
executing project code or contacting a service.

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

The generated `.codex/pro-plan/` directory contains `repo-tree.txt`, `git-status.txt`, `project-context.md`, `context.json`, `symbol-index.json`, `symbol-graph.json`, `REQUEST.md`, `PLAN.md`, `APPROVAL.json`, `VALIDATION_REPORT.md`, and `PLAN_DIFF.md`. Planning artifacts are ignored by Git; `.codex/project-memory/` and `.codex/workflow/` remain ordinary local, reviewable project records.

## Architecture and workflow layers

Context collection is split into focused layers:

```text
src/codex_pro_planning_bridge/context/
├── scanner.py     # safe file inventory
├── detector.py    # project types and dependencies
├── filters.py     # language, priority, and redaction rules
├── exporters.py   # Markdown and JSON output
└── collector.py   # orchestration
```

Shared dataclasses in `src/codex_pro_planning_bridge/models.py` form the boundary between context, planning, validation, memory, and drift reporting. Plan Diff detects Git renames, and Validator includes possible local symbol matches when a plan references an unavailable API.

The v0.3 workflow layers are:

```text
src/codex_pro_planning_bridge/
├── approval.py    # explicit PLAN.md approval records
├── state.py       # versioned state/history/event persistence
├── snapshot.py    # immutable workflow runtime snapshots
├── recovery.py    # fail-closed metadata recovery from snapshots
├── integrity.py   # read-only pre-resume runtime checks
├── workflow.py    # explicit transition rules
├── loop.py        # context → validation → review orchestration
└── intelligence/
    ├── symbol_index.py  # local Python/JS/TS/Rust symbols and imports
    └── symbol_graph.py  # local ownership/import/call relationships
```

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
- `REQUEST.md`, `PLAN.md`, `APPROVAL.json`, validation reports, diff reports, and event logs should be reviewed as project-local artifacts.

## Codex skill

The `skills/pro-planning/SKILL.md` skill describes when to use the bridge and the required request/plan loop. It is intentionally scoped to architecture changes, large refactors, migrations, security-sensitive work, and other tasks where a written plan reduces implementation risk.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
ruff check src scripts tests
mypy src
```

The project is packaged with `pyproject.toml` and exposes both the `codex-pro-planning-bridge` and `cpb` console scripts.

## Roadmap status

- [x] v0.1 MVP: context collector, prompt generator, manual Pro handoff
- [x] Plan Validator and Repository Fact Checker
- [x] Project Memory
- [x] Plan Diff Engine
- [x] Unified CLI and compatibility wrappers
- [x] v0.2.0-beta: planning validation baseline
- [x] v0.2.1 Architecture Hardening
- [x] v0.3 Planning Loop
- [x] v0.3.1 Planning Safety Layer (`v0.3.1-beta`)
- [x] v0.3.2 Hardening (`v0.3.2`)
- [x] v0.3.3 Reliability Layer (`v0.3.3-beta.1`)
- [ ] v0.4 Phase 1 Repository Registry (implementation branch; Draft PR review pending)

## License

MIT
