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

Detect incorrect assumptions.

Examples:

- nonexistent files
- missing classes
- unavailable functions
- unsupported frameworks

---

### 3. Plan Diff Engine

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

# v0.3 Autonomous Planning Assistance

Goal:

Make Codex proactively recommend planning.

Features:

- task complexity detection
- automatic planning suggestions
- architecture review loop
- project memory retrieval

Workflow:

```
User request
 ↓
Complexity analysis
 ↓
Recommend Pro Planning
 ↓
Generate plan
 ↓
Execute
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

