# v0.4 Architecture

## 1. Architectural objective

v0.4 introduces a plugin layer without replacing the existing `cpb` runtime. The architecture must support two different trust and capability surfaces:

- ChatGPT Pro: planning and read-only repository access;
- Codex: local implementation, testing, approval, and workflow control.

The design must not duplicate repository analysis logic across the CLI, MCP server, and Skills.

## 2. Logical layers

```text
┌───────────────────────────────────────────────────────────┐
│ User surfaces                                             │
│                                                           │
│ ChatGPT Pro                         Codex                  │
│ plan-project-with-pro               implement-approved-plan│
│                                     review-implementation  │
└───────────────────────┬───────────────────┬───────────────┘
                        │                   │
                        ▼                   ▼
┌───────────────────────────────────────────────────────────┐
│ Plugin workflow layer                                     │
│                                                           │
│ Skills: triggers, sequences, stop conditions, formats     │
│ Plan Capsule: cross-surface handoff contract              │
└───────────────────────┬───────────────────┬───────────────┘
                        │                   │
                 read-only MCP       local MCP / shell
                        │                   │
                        ▼                   ▼
┌───────────────────────────────────────────────────────────┐
│ MCP adapter layer                                         │
│                                                           │
│ Streamable HTTP transport      stdio transport            │
│ ChatGPT registered app         Codex bundled server       │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│ Shared service layer                                      │
│                                                           │
│ repository authorization                                  │
│ tool input validation                                     │
│ output bounding and redaction                             │
│ mapping between MCP schemas and typed runtime models      │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│ Existing cpb runtime                                      │
│                                                           │
│ context, validator, diff, symbol index/graph, memory,      │
│ approval, state, snapshot, recovery, integrity            │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
                    Registered repositories
```

## 3. Source layout

Target layout:

```text
codex-pro-planning-bridge/
├── .codex-plugin/
│   └── plugin.json
├── .app.json
├── .app.example.json
├── .mcp.json
├── skills/
│   ├── plan-project-with-pro/
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── plan-capsule-schema.md
│   │       └── plan-quality-checklist.md
│   ├── implement-approved-plan/
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── import-and-approval.md
│   │       └── implementation-boundaries.md
│   └── review-implementation/
│       ├── SKILL.md
│       └── references/
│           └── drift-report-format.md
├── mcp_server/
│   ├── __init__.py
│   ├── server.py
│   ├── service.py
│   ├── schemas.py
│   ├── tools.py
│   ├── errors.py
│   ├── config.py
│   └── transports/
│       ├── __init__.py
│       ├── stdio.py
│       └── streamable_http.py
├── src/codex_pro_planning_bridge/
│   ├── registry.py
│   ├── plan_capsule.py
│   └── existing modules
└── tests/
    ├── test_registry.py
    ├── test_plan_capsule.py
    ├── test_mcp_service.py
    ├── test_mcp_tools.py
    ├── test_skill_contracts.py
    └── test_plugin_end_to_end.py
```

`.app.json` is connection-specific. The implementation must not invent its schema. Register the Streamable HTTP MCP endpoint in ChatGPT developer mode, obtain the `plugin_asdk_app...` technical ID, and use `@plugin-creator` or `$plugin-creator` to generate the mapping. Keep `.app.example.json` as documentation only if the generated connection file should not be committed before an ID exists.

## 4. Component responsibilities

### 4.1 Skills

Skills contain only reusable workflow instructions and packaged references. They must define:

- trigger conditions;
- expected user input;
- exact tool sequence;
- required stop and approval points;
- output format;
- facts that must not be inferred;
- fallback behavior when a tool or surface is unavailable.

Skills must not duplicate the validator, registry, hashing, or repository scanning algorithms.

### 4.2 MCP transport adapters

Both transports initialize the same MCP server and tool registry.

`streamable_http.py`:

- used by ChatGPT through a registered MCP connection;
- compatible with Secure MCP Tunnel for local development;
- read-only in v0.4;
- must expose health and MCP endpoints without exposing repository paths.

`stdio.py`:

- bundled through `.mcp.json` for Codex;
- invokes the same tool handlers;
- is optional for Codex workflows that already use local shell access;
- must not produce different schemas or behavior from HTTP.

No business logic may depend on transport type.

### 4.3 Shared service layer

`service.py` is the only MCP-facing entry to repository capabilities. It must:

1. authorize the repository ID through the registry;
2. resolve the canonical root;
3. validate tool inputs;
4. call existing typed runtime functions;
5. remove or redact local-only fields;
6. enforce output limits;
7. return structured result objects;
8. produce stable error codes.

### 4.4 Existing runtime

Existing modules remain authoritative for:

- safe file enumeration;
- sensitive-path filtering;
- project detection;
- context export;
- repository fact validation;
- symbol indexing and graphing;
- Git status and diff;
- plan parsing and drift classification;
- project memory;
- local workflow approval and recovery.

The MCP layer should adapt these functions rather than fork them.

### 4.5 Repository registry

The registry is the authorization boundary between an MCP tool call and the filesystem. It maps an opaque, user-chosen repository ID to one canonical local root.

The MCP server may never accept:

- a repository root path;
- a relative path intended to escape the root;
- an environment-variable-expanded path;
- an unregistered repository URL as a substitute for local authorization.

## 5. Data flow: ChatGPT planning

```text
User selects/mentions plugin
  -> planning Skill determines repository and goal
  -> list_repositories (when repository is ambiguous)
  -> get_repository_status
  -> prepare_planning_context
  -> ChatGPT Pro drafts plan
  -> validate_plan(plan_markdown)
  -> ChatGPT Pro repairs errors and material warnings
  -> emit final Plan Capsule
  -> ask user to approve planning direction
  -> stop; do not claim local approval or implementation
```

The Skill may call `validate_plan` at most three times per user request unless the user asks for further refinement. Repeated identical validation calls are prohibited.

## 6. Data flow: Codex implementation

```text
User hands conversation or Plan Capsule to Codex
  -> implementation Skill parses capsule
  -> verify schema, repository ID, HEAD, and context digest
  -> write exact plan Markdown to .codex/pro-plan/PLAN.md
  -> run local validator
  -> if repository changed materially, stop and request replanning/revalidation
  -> present exact local plan hash and request explicit user approval
  -> after approval, call existing local approval flow
  -> enter IMPLEMENTING
  -> modify source, run tests, report scope changes
  -> run review Skill
```

The implementation Skill must not silently edit the imported plan to make validation pass. Material plan changes require a new Plan Capsule or explicit user-approved amendment.

## 7. Data flow: review

```text
Codex completes implementation
  -> establish Git baseline from capsule or workflow record
  -> call local diff/review runtime
  -> optionally call read-only review_implementation MCP tool
  -> classify completed, missing, changed, blocked, unplanned, renamed, symbol drift
  -> run declared tests/build checks
  -> write/update Project Memory through existing local runtime
  -> report outcome to user
```

ChatGPT may use `review_implementation` for an independent read-only assessment, but it must not be treated as the authoritative test runner.

## 8. Cross-surface identifiers

The following identifiers have distinct roles:

- `repository_id`: stable registry alias, safe to expose to the model;
- `context_digest`: hash of the bounded context payload supplied to planning;
- `repository_head`: Git HEAD observed when context was prepared;
- `plan_id`: unique logical plan identifier;
- `plan_sha256`: hash recomputed locally from exact imported plan Markdown;
- `workflow_id`: local runtime workflow identifier when available.

The Plan Capsule may carry all except local approval status. The local runtime is authoritative for `plan_sha256`, approval, and workflow state.

## 9. Error model

MCP errors must be explicit and stable. Minimum codes:

- `REPOSITORY_NOT_FOUND`
- `REPOSITORY_DISABLED`
- `REPOSITORY_UNAVAILABLE`
- `REPOSITORY_NOT_GIT`
- `INVALID_INPUT`
- `OUTPUT_LIMIT_EXCEEDED`
- `CONTEXT_CHANGED`
- `PLAN_INVALID`
- `BASELINE_NOT_FOUND`
- `REGISTRY_CORRUPT`
- `INTERNAL_ERROR`

Errors must not reveal absolute local paths unless the user is on the local Codex surface and explicitly requests diagnostics.

## 10. Concurrency

v0.4 supports multiple read-only MCP calls but retains one active local workflow per registered repository.

Requirements:

- registry reads are concurrency-safe;
- registry writes use atomic replacement and an inter-process lock;
- context preparation may run concurrently for different repositories;
- the same repository may have concurrent read calls, but output must be tied to the observed HEAD and context digest;
- no ChatGPT MCP tool acquires workflow write locks because all tools are read-only;
- Codex local approval and workflow operations continue using the existing runtime locks and atomic persistence guarantees.

## 11. Versioning

Synchronize the following versions during implementation:

- Python package: `0.4.0a1`;
- `src/.../__init__.py`: `0.4.0a1`;
- plugin manifest: `0.4.0-alpha.1`;
- MCP server: `0.4.0-alpha.1`;
- Plan Capsule schema: `1`;
- registry schema: `1`;
- MCP tool contract version: `1`.

Schema versions are independent of package versions and must reject newer unsupported versions.

## 12. Design constraints

- No OpenAI API dependency.
- No tool executes repository code.
- No tool accepts shell commands.
- No tool writes to the repository in ChatGPT Pro mode.
- No absolute path appears in normal tool output.
- No tool returns full unbounded repositories or large binary data.
- No planning result is considered locally approved until the existing approval hash workflow completes.
- No MCP transport-specific logic leaks into the service layer.
- No new UI is required for the first alpha.
