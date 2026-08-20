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

Status: In progress (`0.3.0.dev0`)

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

