# v0.4 Architecture Decisions and Open Questions

Status: decisions below are frozen for `0.4.0-alpha.1` unless explicitly reopened through review.

## 1. Decision summary

| ID | Decision | Status |
|---|---|---|
| V04-D001 | ChatGPT Pro is the planning surface; Codex is the implementation surface | Accepted |
| V04-D002 | v0.4 ChatGPT MCP tools are read-only | Accepted |
| V04-D003 | No OpenAI API/model API is introduced | Accepted |
| V04-D004 | Use one plugin package with three focused Skills | Accepted |
| V04-D005 | Use five public MCP tools only | Accepted |
| V04-D006 | MCP accepts repository IDs, never arbitrary paths | Accepted |
| V04-D007 | Repository Registry is the filesystem authorization boundary | Accepted |
| V04-D008 | Use Plan Capsule for ChatGPT-to-Codex handoff | Accepted |
| V04-D009 | Conversational approval is not local execution approval | Accepted |
| V04-D010 | Existing `cpb` runtime and reliability layer remain authoritative | Accepted |
| V04-D011 | One service layer supports Streamable HTTP and stdio transports | Accepted |
| V04-D012 | Use the official Python MCP SDK unless blocked during implementation | Accepted with verification |
| V04-D013 | Local ChatGPT development uses Secure MCP Tunnel | Accepted with availability verification |
| V04-D014 | No custom MCP UI in the first alpha | Accepted |
| V04-D015 | Retain the old Skill as a compatibility router for one alpha cycle | Accepted |
| V04-D016 | No public marketplace submission before dogfood/security gates | Accepted |

## 2. Detailed decisions

### V04-D001 — Split planning and implementation surfaces

**Decision**

- ChatGPT Pro performs architecture reasoning and plan validation through read-only repository tools.
- Codex writes files, executes tests, manages local approval, and reviews implementation.

**Rationale**

- preserves the user’s ChatGPT Pro planning-quality and subscription objective;
- uses Codex where local filesystem and execution capabilities belong;
- creates a clear security boundary;
- avoids pretending ChatGPT conversational state equals repository state.

**Rejected alternatives**

- Responses API planner: adds separate API cost and misses the original objective;
- automated ChatGPT webpage control: brittle and outside the intended plugin architecture;
- ChatGPT write-enabled MCP in v0.4 Pro: not required by current Pro-compatible capability and increases risk;
- Codex-only planning: loses the intended Pro planning surface.

### V04-D002 — Read-only ChatGPT MCP

**Decision**

The five v0.4 public tools are read-only and must not write even planning artifacts.

**Rationale**

- compatible with the Pro read/fetch path;
- limits prompt-injection impact;
- makes server behavior easier to audit;
- leaves approval and writes in the local Codex/runtime boundary.

**Consequence**

A handoff artifact is required because ChatGPT cannot be assumed to save `PLAN.md` locally.

### V04-D003 — No OpenAI API

**Decision**

Do not add an OpenAI API client, model call, API key, or API billing dependency.

**Rationale**

The model invocation already occurs through the user’s ChatGPT Pro conversation. MCP supplies data and deterministic validation only.

### V04-D004 — Three focused Skills

**Decision**

Ship:

- `plan-project-with-pro`;
- `implement-approved-plan`;
- `review-implementation`.

Retain `pro-planning` as a temporary router.

**Rationale**

Each Skill has a clear trigger, surface, approval boundary, and output. A single mixed Skill had become CLI-first and ambiguous.

### V04-D005 — Exactly five public MCP tools

**Decision**

Expose only:

- `list_repositories`;
- `get_repository_status`;
- `prepare_planning_context`;
- `validate_plan`;
- `review_implementation`.

**Rationale**

- high-level tools reduce context and tool-selection noise;
- no file-by-file arbitrary fetch API is needed for the initial planning workflow;
- narrower surface is easier to secure and review;
- all tools map to existing deterministic runtime capabilities.

**Reopening condition**

A new public tool requires evidence from dogfooding that the workflow cannot be completed efficiently with these five tools.

### V04-D006 — Repository ID only

**Decision**

No public MCP input accepts a filesystem path.

**Rationale**

Prevents path traversal, accidental access to unrelated directories, and model-chosen local scope.

### V04-D007 — Registry authorization boundary

**Decision**

Only repositories explicitly registered by a local user are readable through MCP.

**Rationale**

- creates a reviewable allowlist;
- makes repository selection model-safe;
- separates local path metadata from model-visible identifiers;
- supports disabling/removing access without changing the repository.

### V04-D008 — Plan Capsule

**Decision**

Use a versioned JSON payload inside a distinct Markdown fence to transport the final plan.

**Rationale**

- works with native conversation transfer, copy/paste, and saved files;
- deterministic parsing;
- carries repository/context identity;
- avoids relying on a specific ChatGPT write capability;
- preserves exact plan Markdown.

**Rejected alternative**

Pure Markdown headings alone are too ambiguous for reliable import from a conversation containing drafts and discussion.

### V04-D009 — Dual approval semantics

**Decision**

- ChatGPT approval means “the user accepts this planning direction.”
- Codex local approval means “the user approves the exact validated `PLAN.md` SHA-256 for implementation.”

Only the second authorizes implementation.

**Rationale**

Repository context may change between planning and implementation. Exact local hash binding is already a proven safety layer.

### V04-D010 — Existing runtime remains authoritative

**Decision**

Do not reimplement context, validation, diff, memory, approval, or reliability algorithms inside the MCP package.

**Rationale**

- avoids divergence;
- preserves existing tests;
- enables CLI/MCP behavior consistency;
- keeps transport adapters thin.

### V04-D011 — Dual transport over one service

**Decision**

Use:

- Streamable HTTP for ChatGPT registration/tunnel;
- stdio for Codex bundling;
- one shared tool/service implementation.

**Rationale**

The surfaces require different connections, but business behavior must remain identical.

### V04-D012 — Official Python MCP SDK

**Decision**

Prefer the official `mcp` Python SDK and verify its current APIs during implementation.

**Rationale**

- current protocol support;
- Streamable HTTP and stdio support;
- MCP Inspector compatibility;
- avoids maintaining protocol framing.

**Fallback**

If a reviewed SDK incompatibility blocks Python 3.10 or the required transports, document it and propose an alternative before implementation. Do not silently switch stacks.

### V04-D013 — Secure MCP Tunnel

**Decision**

Use the current official Secure MCP Tunnel development path for a local server.

**Rationale**

ChatGPT cannot directly connect to localhost. A tunnel preserves the local repository runtime while enabling registered MCP testing.

**Constraint**

Do not commit tunnel credentials or ephemeral URLs.

### V04-D014 — No custom UI in alpha.1

**Decision**

Use text and structured tool output only.

**Rationale**

The critical uncertainty is cross-surface workflow reliability, not UI. A custom Apps SDK UI can be considered after dogfood.

### V04-D015 — Compatibility Skill

**Decision**

Keep `skills/pro-planning` for one alpha cycle as a router.

**Rationale**

Avoids immediately breaking existing installed plugin references while preventing two independent workflows from diverging.

### V04-D016 — No public submission before gates

**Decision**

First release is local/personal/repo marketplace alpha.

**Rationale**

- account/surface rollout must be validated;
- privacy/terms and stable connection topology are not final;
- five real dogfood workflows are required;
- public MCP hosting/distribution remains unresolved.

## 3. Open questions requiring implementation-time verification

### V04-Q001 — Which ChatGPT client surface supports this exact custom plugin on the user’s Pro account?

**Known**

ChatGPT developer mode can register MCP apps for supported plans/surfaces, and Pro supports a read/fetch development path.

**Unknown**

- whether the user’s desktop client exposes the same custom app flow as web at implementation time;
- whether a restart/refresh is required for plugin discovery;
- whether the universal plugin directory is visible identically in all tested clients.

**Resolution method**

Record tested web/desktop client versions and account behavior in the integration PR. Use ChatGPT web developer mode as the fallback acceptance surface if desktop rollout is unavailable.

### V04-Q002 — Should `.app.json` be committed?

Options:

1. commit stable connection technical ID;
2. commit only `.app.example.json`, generate `.app.json` per developer;
3. maintain separate local marketplace connection configuration.

Decision criteria:

- whether technical ID is portable across users;
- whether it exposes private connection metadata;
- whether local tunnel endpoints differ per developer;
- plugin creator output and current marketplace behavior.

Do not decide before generating and reviewing a real connection mapping.

### V04-Q003 — What authentication does the local/tunneled MCP endpoint require?

Need to verify the current Secure MCP Tunnel and ChatGPT registration model.

Requirements regardless of mechanism:

- no unauthenticated public local endpoint;
- no secret committed;
- repository registry remains an independent authorization layer;
- connection failures are explicit and retryable.

### V04-Q004 — Hosted MCP distribution after local alpha

Options:

- local agent plus Secure MCP Tunnel per user;
- signed desktop/local companion process;
- hosted broker routing authenticated users to private agents;
- hosted repository service for explicitly connected remote repos.

This is not required for alpha.1. Choose only after dogfood and public-distribution requirements are understood.

### V04-Q005 — Plan Capsule transfer UX

Options:

- native conversation handoff;
- copy/paste fenced capsule;
- downloadable/saved capsule file;
- future write-enabled MCP.

Alpha must support copy/paste and file import. Native handoff is an enhancement if available.

### V04-Q006 — Context digest staleness cost

Recomputing a full standard/deep context may be expensive on large repositories.

Potential implementation:

- digest canonical bounded context;
- cache by HEAD + dirty fingerprint + detail level + goal normalization;
- invalidate on relevant changes;
- never use stale cache when `expected_head` mismatches.

Measure first; do not add complex caching before baseline performance tests.

### V04-Q007 — Non-Git repository support

Registry may allow non-Git roots with explicit local confirmation. Planning can work, but:

- no HEAD identity;
- weaker staleness/baseline review;
- Plan Diff semantics differ.

Alpha can expose non-Git status but should classify full handoff/review as degraded and document limitations.

### V04-Q008 — Absolute path diagnostics in Codex

MCP results must not expose paths. Local Codex CLI diagnostics may need them.

Decision:

- service layer returns safe model-facing DTOs;
- local CLI has an explicit diagnostic rendering path;
- never reuse diagnostic DTOs in MCP accidentally.

Implementation review must confirm this separation.

### V04-Q009 — Registry storage synchronization across machines

The registry is per-user/per-machine. A repository ID used in ChatGPT planning may not exist on another Codex machine.

Alpha behavior:

- import fails with a clear repository-ID mismatch;
- user registers the repository locally;
- no registry cloud sync.

Future versions may export/import registry metadata without transporting paths blindly.

### V04-Q010 — Legal/privacy publication requirements

Before public submission, verify current requirements for:

- privacy policy;
- terms;
- data handling disclosure;
- user authentication;
- MCP review;
- screenshots/assets;
- developer identity.

Alpha documentation must not claim public eligibility until verified.

## 4. Deferred proposals

The following are intentionally deferred and must not enter v0.4 alpha scope without reopening the spec:

- ChatGPT write/modify tools;
- `store_plan`, `approve_plan`, or source-write MCP tools;
- multi-agent planning or reviewer agents;
- custom Apps SDK UI;
- public hosted multi-user MCP;
- cloud repository connectors;
- automatic production deployment;
- OpenAI API fallback;
- mobile-first support;
- registry synchronization;
- automatic public marketplace submission.

## 5. Decision change process

To change an accepted decision:

1. add a dated proposal below;
2. reference the affected decision ID;
3. describe observed evidence;
4. list alternatives and security/compatibility effects;
5. recommend one option;
6. update all affected specs and tests after approval;
7. commit the decision change separately from implementation.

Template:

```markdown
### YYYY-MM-DD — Reopen V04-Dxxx

Evidence:

Options:

Impact:

Recommendation:

Decision:
```

## 6. Implementation-time decision log

No implementation-time deviations have been recorded yet.
