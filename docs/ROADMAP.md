# Codex Pro Planning Bridge Roadmap

## Vision

Build an architecture planning layer for Codex where:

- ChatGPT Pro acts as the senior software architect.
- Codex acts as the implementation engineer.
- The repository remains the source of truth.

The long-term goal is an AI development workflow with planning, execution, validation, and memory.

---

# v0.1 MVP - Planning Bridge

Status: Complete

Goal:

Create the first working loop:

```
Repository context
        ↓
Planning request
        ↓
ChatGPT Pro architecture plan
        ↓
PLAN.md
        ↓
Codex implementation
```

Features:

- Plugin structure
- Context collector
- Prompt generator
- ChatGPT Pro handoff
- Basic documentation

---

# v0.2 Intelligent Planning Loop

Status: Complete (`v0.2.0-beta`)

Goal:

Upgrade from a prompt generator into a planning validation system.

## Core Features

### 1. Plan Validator

Status: Complete

Validate ChatGPT Pro plans against repository facts.

Checks:

- referenced files exist
- modules exist
- dependencies exist
- APIs and symbols are reasonable
- risks are identified

Output:

```
.codex/pro-plan/VALIDATION_REPORT.md
```

---

### 2. Repository Fact Checker

Status: Complete

Detect incorrect assumptions.

Examples:

- nonexistent files
- missing classes
- unavailable functions
- unsupported frameworks

---

### 3. Plan Diff Engine

Status: Complete

Compare planned implementation with actual repository changes.

Output:

```
PLAN_DIFF.md
```

Detect:

- completed tasks
- missing tasks
- changed architecture decisions
- implementation drift

---

### 4. Project Memory

Status: Complete

Introduce persistent project knowledge.

Structure:

```
.codex/project-memory/

architecture.md

decisions.md

constraints.md

known-issues.md
```

Store:

- architecture decisions
- technical constraints
- previous planning results
- known problems

---

# v0.2.1 Architecture Hardening

Status: Complete (`v0.2.1`)

Goal:

Stabilize the planning infrastructure before implementing the v0.3 Planning Loop.

Features:

- Shared typed models for context, plans, facts, memory, and drift reports
- Layered Context Collector with scanner, detector, filters, and exporters
- Machine-readable `.codex/pro-plan/context.json`
- ADR-based Project Memory with versioned `memory.json`
- Rename-aware Plan Diff and possible symbol matches in Validator reports
- `cpb` bootstrap/prompt CLI aliases with compatibility wrappers
- Reusable test fixtures, Ruff, mypy, compile checks, and GitHub Actions CI

---

# v0.3 Continuous Planning Loop

Status: Complete (`0.3.0.dev0`)

Goal:

Make the planning bridge recoverable and continuously aligned with the local
repository while preserving the explicit ChatGPT Pro/Codex boundary.

Features:

- persisted workflow state and transition history
- local Python, JavaScript/TypeScript, and Rust symbol indexing
- context-aware plan validation and file/symbol drift reports
- resumable context → validation → implementation → review loop
- memory schema migrations and automatic planning-record updates

Workflow:

```
Task
 ↓
Context Collection
 ↓
ChatGPT Pro Planning
 ↓
Plan Validation
 ↓
Codex Implementation
 ↓
Drift Detection
 ↓
Memory Update
```

---

# v0.3.1 Planning Safety Layer

Status: Complete (`v0.3.1-beta`)

Features:

- append-only workflow event audit log
- explicit human approval records for `PLAN.md`
- `cpb status`, `resume`, `pause`, `cancel`, and `history`
- local symbol ownership, import, and call relationship graph
- recovery and approval-flow tests

Constraints remain local-first: no OpenAI API calls, API keys, browser
automation, autonomous source modification, or bypassing human approval.

---

# v0.3.2 Hardening

Status: Complete (`v0.3.2`)

Goal:

Strengthen the local control plane before introducing any multi-agent
planning capabilities.

Features:

- approval hash and plan-path binding with explicit invalidation reasons
- read-only event query CLI with stable event indexes and filters
- compensating workflow rollback that preserves the append-only audit log
- expanded Python, JavaScript/TypeScript, and Rust symbol graph coverage

Constraints remain local-first: no OpenAI API calls, API keys, browser
automation, autonomous source modification, or bypassing human approval.

---

# v0.3.3 Reliability Layer

Status: Beta.1 (`v0.3.3-beta.1`)

Goal:

Make the Workflow Runtime recoverable, verifiable, and auditable before
introducing multi-agent planning.

Features:

- versioned JSON-only Workflow Snapshots with immutable numbered records and a
  deterministic `latest.json` pointer;
- fail-closed `cpb recover` that restores workflow metadata and appends a
  compensating recovery event;
- read-only Workflow Integrity checks that run before `cpb resume` and verify
  state, history position, plan and approval hashes, Git state, and Project
  Memory metadata;
- approval lifecycle statuses: `APPROVED`, `INVALIDATED`, `EXPIRED`, and
  `REVOKED`, with optional local expiry and explicit revocation events; and
- automatic snapshot baselines after `cpb pause`.

Beta.1 reliability hardening adds:

- a continuous approval invariant across implementation, resume, rollback, and
  recovery paths;
- post-operation runtime snapshots that establish a new integrity baseline;
- atomic persistence for state, history, and the append-only event ledger;
- strict event-ledger parsing that rejects malformed or truncated records;
- repository commit/dirty-state checks during recovery; and
- schema, identity, and cross-file validation for numbered snapshots and
  `latest.json`.

The release remains local-first: no OpenAI API calls, API keys, browser
automation, autonomous source modification, or bypassing human approval.
Security scanning and runtime metrics are intentionally deferred to a later
hardening release.

---

# v0.4 ChatGPT Client Integration

Status: In progress — Phase 1 Repository Registry (`feat/v0.4-repository-registry`)

Goal:

Change the default experience from a CLI-first bridge into a universal plugin
that uses ChatGPT Pro as the repository-grounded planning surface and Codex as
the locally approved implementation and review surface.

Target workflow:

```text
ChatGPT Pro plugin
  ↓ read-only registered-repository MCP
Validated Plan Capsule
  ↓ human planning approval
Codex plugin
  ↓ local repository revalidation
Hash-bound local approval
  ↓
Codex implementation and tests
  ↓
Plan Diff, symbol drift, and Project Memory
```

Features:

- three focused Skills:
  - `plan-project-with-pro`
  - `implement-approved-plan`
  - `review-implementation`
- five read-only Repository MCP tools:
  - `list_repositories`
  - `get_repository_status`
  - `prepare_planning_context`
  - `validate_plan`
  - `review_implementation`
- per-user repository allowlist and `cpb repo` management CLI;
- versioned Plan Capsule handoff from ChatGPT Pro to Codex;
- one shared MCP service with Streamable HTTP and stdio transports;
- ChatGPT developer-mode registration and Secure MCP Tunnel development path;
- universal plugin packaging with `.app.json`, `.mcp.json`, Skills, and local marketplace testing;
- continued use of v0.3.3 validation, approval, audit, snapshot, recovery, integrity, diff, and memory controls;
- client integration, adversarial security, MCP Inspector, and end-to-end dogfood tests.

Constraints:

- no OpenAI API calls or API keys;
- no ChatGPT webpage automation or scraping;
- ChatGPT Pro MCP tools are read-only in v0.4;
- MCP accepts repository IDs, never arbitrary filesystem paths;
- conversational approval is not local implementation approval;
- no custom interactive UI in the first alpha;
- no public marketplace submission before dogfood, privacy, and security gates.

Implementation phases:

1. Repository Registry
2. Plan Capsule
3. MCP service core and schemas
4. Five read-only tools
5. stdio and Streamable HTTP transports
6. surface-focused Skills
7. plugin packaging and local marketplace
8. ChatGPT developer-mode/tunnel integration
9. Codex handoff, dogfood, and alpha release

Phase 1 implementation is intentionally stopped at its Draft PR review gate.
It adds only the local versioned allowlist and `cpb repo` management CLI;
MCP, Plan Capsule, Skills, packaging, and ChatGPT client integration remain
later phases.

Authoritative planning documents:

- `docs/V0.4_SPEC.md`
- `docs/v0.4/README.md`
- `docs/v0.4/IMPLEMENTATION_PLAN.md`
- `docs/v0.4/ACCEPTANCE_CHECKLIST.md`

---

# v1.0 AI Software Architect Layer

Final vision:

```
              ChatGPT Pro

          Architecture Layer

                 |

              Codex Agent

                 |

             Repository
```

Capabilities:

- architecture planning
- implementation guidance
- continuous validation
- project memory
- engineering decision tracking
