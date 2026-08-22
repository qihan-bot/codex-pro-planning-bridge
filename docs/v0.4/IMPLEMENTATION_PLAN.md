# v0.4 Phased Implementation Plan

Status: ready for local Agent implementation after documentation review.  
Target: `0.4.0-alpha.1`  
Base: latest `main` containing `v0.3.3-beta.1` reliability fixes.

## 1. Delivery strategy

v0.4 must be implemented as a sequence of independently reviewable phases. Do not build the complete MCP/plugin stack in one commit or one unreviewed branch.

Required discipline:

```text
Spec freeze
  -> Issue
  -> focused branch
  -> implementation
  -> tests and security checks
  -> Draft PR
  -> review stop
  -> merge
  -> next phase
```

No phase may introduce an OpenAI API key, model API call, ChatGPT webpage automation, arbitrary filesystem path tool, ChatGPT-side write tool, or bypass of local approval.

## 2. Dependency graph

```text
Phase 1 Repository Registry
        |
        +------> Phase 2 Plan Capsule
        |               |
        v               v
Phase 3 MCP Core and Schemas
        |
        v
Phase 4 Five Read-Only Tools
        |
        v
Phase 5 Dual Transports
        |
        +------> Phase 6 Skills Split
        |               |
        v               v
Phase 7 Plugin Packaging and Local Marketplace
        |
        v
Phase 8 ChatGPT Developer-Mode / Tunnel Integration
        |
        v
Phase 9 End-to-End Dogfood and Alpha Release
```

Phase 2 may begin after Phase 1 models are stable. Phase 6 may begin after tool names and contracts are frozen, but final Skill tests depend on Phase 5/7.

## 3. Phase 0 — Documentation and architecture freeze

### Goal

Make the v0.4 specifications authoritative before implementation.

### Deliverables

- `docs/V0.4_SPEC.md`
- `docs/v0.4/ARCHITECTURE.md`
- `docs/v0.4/SKILLS_SPEC.md`
- `docs/v0.4/MCP_TOOL_CONTRACTS.md`
- `docs/v0.4/REPOSITORY_REGISTRY_AND_SECURITY.md`
- `docs/v0.4/HANDOFF_PROTOCOL.md`
- `docs/v0.4/PACKAGING_DEPLOYMENT_AND_TESTING.md`
- this implementation plan
- local Agent instructions
- decisions/open questions
- acceptance checklist
- Roadmap update

### Review gate

- no contradictory write capability in ChatGPT Pro path;
- no invented `.app.json` technical ID;
- exactly five public MCP tools;
- Skills, MCP, registry, and capsule boundaries are explicit;
- local approval remains authoritative;
- all out-of-scope items are explicit.

### Suggested PR

```text
docs: define v0.4 ChatGPT client integration
```

Do not implement production code in the documentation PR.

---

## 4. Phase 1 — Repository Registry and CLI

### Suggested issue

```text
Implement v0.4 repository registry and allowlist CLI
```

### Branch

```text
feat/v0.4-repository-registry
```

### Files

```text
src/codex_pro_planning_bridge/
├── registry.py
├── registry_models.py            # optional if models.py would become crowded
└── cli.py

tests/
├── test_registry.py
├── test_registry_cli.py
└── fixtures/registry/
```

### Required models

```python
RepositoryRegistration
RepositoryRegistry
RepositoryHealth
RegistryError
```

Fields should include:

- repository ID;
- display name;
- canonical path (local only);
- enabled/read policy;
- created/updated timestamps;
- schema version;
- optional notes.

### Required CLI

```bash
cpb repo add <id> <path> [--display-name ...] [--allow-non-git] [--yes]
cpb repo list [--format text|json]
cpb repo show <id> [--format text|json]
cpb repo remove <id> [--yes]
cpb repo doctor <id> [--format text|json]
```

### Implementation requirements

- use OS-specific user config directory;
- strict schema versioning;
- canonical path and resolved containment validation;
- reserved ID protection;
- reject dangerous roots and known credential directories;
- atomic registry replacement under inter-process lock;
- fail closed on corrupt JSON;
- do not recreate a corrupt registry automatically;
- no MCP modification tools for the registry;
- local CLI may show paths, model-facing services may not.

### Tests

- ID validation and normalization;
- duplicate/reserved ID;
- add/list/show/remove;
- non-Git confirmation path;
- missing/unavailable repository;
- root/home/sensitive directory rejection;
- symlink/junction root identity;
- child symlink escape fixture;
- concurrent writers;
- interrupted write;
- corrupt and newer schema;
- file permission best effort;
- no repository files modified.

### Commit sequence

```text
feat: add versioned repository registry
feat: add repository allowlist CLI
 test: cover registry security and concurrency
 docs: document repository registration workflow
```

### Stop gate

Open a Draft PR and stop. Do not implement MCP tools until registry review passes.

---

## 5. Phase 2 — Plan Capsule and import workflow

### Suggested issue

```text
Implement v0.4 Plan Capsule handoff and local import
```

### Branch

```text
feat/v0.4-plan-capsule
```

### Files

```text
src/codex_pro_planning_bridge/
├── plan_capsule.py
├── capsule_schema.py             # optional generated/typed schema boundary
└── cli.py

tests/
├── test_plan_capsule.py
├── test_plan_import.py
└── fixtures/capsules/
```

### Required APIs

```python
extract_plan_capsule(text: str) -> PlanCapsule
validate_plan_capsule(value: object) -> PlanCapsule
normalize_plan_markdown(markdown: str) -> str
import_plan_capsule(repo, capsule, ...) -> PlanImportResult
classify_staleness(...) -> StalenessClassification
```

### Required CLI

```bash
cpb plan import --repo . --capsule-file capsule.md
cpb plan import --repo . --stdin
cpb plan inspect --repo .
cpb plan capsule-validate --file capsule.md
```

### Local artifacts

```text
.codex/pro-plan/
├── PLAN.md
└── CAPSULE.json
```

`CAPSULE.json` stores metadata only and must not duplicate complete plan Markdown.

### Requirements

- strict schema v1;
- exactly one capsule fence;
- Unicode preservation;
- CRLF/LF normalization;
- atomic local writes;
- no approval during import;
- repository ID verification;
- HEAD/context staleness classification;
- wrong-repository import fails before any write;
- validation runs after import;
- local plan SHA-256 is authoritative;
- material changes require replan;
- no implicit plan amendment.

### Tests

- full round trip;
- code blocks/indentation/Unicode;
- malformed/multiple/missing capsule;
- unsupported schema;
- NUL/size limits;
- wrong repository;
- four staleness classes;
- failed validation leaves approval absent;
- import is atomic;
- local digest deterministic;
- plan mutation invalidates approval through existing runtime.

### Stop gate

Draft PR and review the handoff protocol. Do not wire Skills to an unreviewed capsule importer.

---

## 6. Phase 3 — MCP core, schemas, and service boundary

### Suggested issue

```text
Implement v0.4 read-only MCP service core
```

### Branch

```text
feat/v0.4-mcp-core
```

### Files

```text
mcp_server/
├── __init__.py
├── config.py
├── errors.py
├── schemas.py
├── service.py
├── tools.py
└── server.py

src/codex_pro_planning_bridge/
└── mcp_models.py                 # optional shared typed results

tests/
├── test_mcp_schemas.py
├── test_mcp_service.py
└── test_mcp_errors.py
```

### Dependencies

Add the official Python MCP SDK as an optional/plugin dependency rather than forcing all CLI-only users to install server dependencies if packaging permits.

Possible package extras:

```toml
[project.optional-dependencies]
mcp = ["mcp>=<reviewed minimum>,<<next incompatible major>"]
dev = [..., "mcp[cli]>=..."]
```

Pin only after checking the current supported SDK version and APIs during implementation.

### Service API

The service layer should expose typed methods corresponding to the five public tools but should not depend on MCP transport classes.

```python
RepositoryPlanningService.list_repositories(...)
RepositoryPlanningService.get_repository_status(...)
RepositoryPlanningService.prepare_planning_context(...)
RepositoryPlanningService.validate_plan(...)
RepositoryPlanningService.review_implementation(...)
```

### Requirements

- registry authorization on every method;
- contract version checking;
- stable error envelopes;
- no absolute paths in model-facing results;
- output bounding and deterministic serialization;
- operational audit metadata without source/plan bodies;
- cancellation/deadline hooks;
- no repository writes;
- service tests compare before/after filesystem snapshots.

### Stop gate

Draft PR with service tests. Tool registration and network transports can follow only after API review.

---

## 7. Phase 4 — Public MCP tool implementation

### Suggested issue

```text
Implement the five v0.4 read-only repository MCP tools
```

### Branch

```text
feat/v0.4-mcp-tools
```

### Tools

1. `list_repositories`
2. `get_repository_status`
3. `prepare_planning_context`
4. `validate_plan`
5. `review_implementation`

### Requirements

- exact v1 schemas from `MCP_TOOL_CONTRACTS.md`;
- accurate tool annotations;
- no extra public tools in alpha.1;
- concise titles/descriptions;
- structured content plus concise text content;
- hard caps for context/plan/output sizes;
- stale expected HEAD/digest handling;
- fixed Git commands only;
- no test execution in MCP review;
- context digest canonicalization;
- prompt-injection fixtures treated as data;
- no absolute paths or secret content.

### Tests

Create one test class/module per tool plus shared mutation/security tests.

```text
test_mcp_list_repositories.py
test_mcp_repository_status.py
test_mcp_planning_context.py
test_mcp_validate_plan.py
test_mcp_review_implementation.py
test_mcp_read_only_invariants.py
```

### Stop gate

Draft PR and verify all contract examples. Do not connect ChatGPT before tool contracts are stable.

---

## 8. Phase 5 — Dual transports and Inspector validation

### Suggested issue

```text
Add stdio and Streamable HTTP transports for the v0.4 MCP server
```

### Branch

```text
feat/v0.4-mcp-transports
```

### Files

```text
mcp_server/transports/
├── __init__.py
├── stdio.py
└── streamable_http.py
```

### Console entry point

```toml
cpb-mcp = "mcp_server.server:main"
```

### CLI target

```bash
cpb-mcp --transport stdio
cpb-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

### Requirements

- one server/tool registry and one service layer;
- stdio stdout contains protocol traffic only;
- diagnostics go to stderr;
- loopback bind by default;
- explicit opt-in for remote bind;
- request and response limits;
- timeouts and graceful cancellation;
- clean shutdown;
- no eager repository scans;
- transport-equivalence tests;
- MCP Inspector validation documented and run.

### Stop gate

Publish a redacted Inspector result in the PR. Do not commit tunnel credentials or endpoint URLs.

---

## 9. Phase 6 — Skills split and compatibility migration

### Suggested issue

```text
Split the plugin into ChatGPT planning, Codex implementation, and review Skills
```

### Branch

```text
feat/v0.4-surface-skills
```

### Files

```text
skills/
├── plan-project-with-pro/
├── implement-approved-plan/
├── review-implementation/
└── pro-planning/                  # deprecated router for one alpha cycle
```

### Requirements

- implement `SKILLS_SPEC.md` exactly;
- add `agents/openai.yaml` MCP dependency for planning/review where required;
- package reference files;
- no absolute paths or private connection IDs in Skill text;
- no ChatGPT-side writes;
- conversational approval clearly separated from local approval;
- compatibility Skill routes, not duplicates;
- static contract tests;
- prompt-evaluation matrix.

### Stop gate

Review direct, indirect, negative, and adversarial trigger tests before packaging.

---

## 10. Phase 7 — Plugin packaging, manifests, and marketplace

### Suggested issue

```text
Package v0.4 as a universal ChatGPT and Codex plugin
```

### Branch

```text
feat/v0.4-plugin-packaging
```

### Deliverables

- update `.codex-plugin/plugin.json`;
- add `.mcp.json`;
- add `.app.example.json` and decide generated `.app.json` strategy;
- add `.agents/plugins/marketplace.json` through plugin creator;
- synchronize versions;
- add `PRIVACY.md`, `SECURITY.md`, and `TERMS.md` before public testing as appropriate;
- add/validate assets if used;
- plugin package static tests.

### Requirements

- use `@plugin-creator`/`$plugin-creator` for generated connection and marketplace mappings;
- do not invent a `plugin_asdk_app...` ID;
- manifest capability is `Read`;
- no secret/tunnel URL committed;
- install/reinstall from local marketplace;
- fresh ChatGPT/Codex chats discover expected Skills/tools;
- old CLI continues to work.

### Stop gate

Draft PR and manual installation evidence. Do not submit publicly.

---

## 11. Phase 8 — ChatGPT developer-mode and Secure MCP Tunnel integration

### Suggested issue

```text
Validate v0.4 ChatGPT Pro planning through registered MCP and Secure MCP Tunnel
```

### Branch

```text
feat/v0.4-chatgpt-integration
```

### Tasks

1. start the HTTP MCP server;
2. expose with the current official Secure MCP Tunnel flow;
3. enable ChatGPT developer mode;
4. register endpoint and scan tools;
5. obtain technical connection ID;
6. wire `.app.json` with plugin creator;
7. install/refresh plugin;
8. run the ChatGPT test matrix;
9. record redacted evidence and platform metadata;
10. fix only integration defects, not expand feature scope.

### Required scenarios

- repository resolution;
- standard planning;
- deep planning;
- validation repair;
- ambiguous repository;
- no repositories;
- stale HEAD;
- prompt injection fixture;
- request for arbitrary path;
- request to write files or bypass approval;
- disconnect/reconnect;
- oversized context/plan.

### Stop gate

At least one end-to-end Plan Capsule must be generated from ChatGPT Pro with no API key and no ChatGPT write tool.

---

## 12. Phase 9 — Codex handoff, dogfood, and alpha release

### Suggested issue

```text
Dogfood and release v0.4.0-alpha.1 ChatGPT client integration
```

### Branch

```text
release/v0.4.0-alpha.1
```

### Tasks

- import ChatGPT-generated capsule into Codex;
- local validation and exact-hash approval;
- implementation and test execution;
- drift review and memory update;
- run five or more real-project workflows;
- record friction, tool-call counts, latency, stale-context cases, and manual intervention;
- fix P0/P1 defects;
- synchronize documentation and versions;
- create alpha release notes.

### Dogfood report

Create:

```text
docs/v0.4/DOGFOOD_REPORT.md
```

Per run record:

- project type and anonymized repository ID;
- goal category;
- ChatGPT surface/account plan;
- context detail level and size;
- validation cycles;
- handoff method;
- staleness result;
- local approval steps;
- implementation outcome;
- drift findings;
- failure/recovery events;
- user friction;
- data disclosure review.

### Release gate

- all acceptance checklist items pass;
- no P0/P1 issues;
- five real workflows complete;
- no OpenAI API key or model API request;
- read-only MCP mutation tests pass;
- ChatGPT and Codex install instructions verified from a clean environment;
- Release is marked alpha/prerelease.

## 13. Cross-phase quality commands

The Agent must preserve existing checks and add new ones:

```bash
python -m unittest discover -s tests -v
ruff check src mcp_server scripts tests
mypy src mcp_server
python -m compileall -q src mcp_server scripts tests
```

Add as implementation evolves:

```bash
python -m json.tool .codex-plugin/plugin.json
python -m json.tool .mcp.json
python -m json.tool .agents/plugins/marketplace.json
```

Use the current official MCP Inspector command documented by the SDK; do not freeze an unverified command in the Skill.

## 14. Required PR template for each phase

```markdown
## Goal

## Spec references

## Included

## Explicitly not included

## Security and privacy impact

## Compatibility impact

## Tests

## Manual validation

## Files/artifacts written by this feature

## Rollback plan

## Follow-up issues
```

## 15. Rollback strategy

Each phase must be independently revertible.

- Registry changes: uninstall CLI feature without deleting registry; retain a documented backup/export path.
- Capsule changes: old CLI workflows remain usable; imported plan artifacts are normal local files.
- MCP server: plugin may fall back to Skills-only/manual mode.
- Skills split: compatibility Skill routes old users.
- `.app.json`: remove/disable connection without affecting Codex CLI.
- `.mcp.json`: users can disable bundled server.
- Marketplace: uninstall plugin; existing `.codex` workflow artifacts remain valid.

No rollback may delete repositories, source files, project memory, or approval/event records.
