# Local Agent Instructions for v0.4

## 1. Mission

Implement **v0.4 ChatGPT Client Integration** for `qihan-bot/codex-pro-planning-bridge` without weakening the existing v0.3.3 reliability and approval controls.

The default product entry changes from a CLI-first workflow to:

```text
ChatGPT Pro plugin planning
  -> Plan Capsule
  -> Codex plugin implementation
  -> local validation and hash-bound approval
  -> drift review and project memory
```

The existing `cpb` CLI remains the deterministic local runtime.

## 2. Non-negotiable constraints

Do not introduce:

- OpenAI API calls;
- `OPENAI_API_KEY` configuration;
- Responses API or model SDK use;
- ChatGPT webpage automation, scraping, Playwright, or Computer Use submission;
- ChatGPT-side source or planning-file writes in the v0.4 Pro path;
- arbitrary path arguments in MCP tools;
- arbitrary shell execution through MCP;
- automatic approval on behalf of the user;
- bypasses around validation, approval hash, workflow integrity, recovery, or audit;
- execution of repository code from read-only MCP tools;
- public marketplace submission before dogfood and security review.

If a requested implementation conflicts with these constraints, stop and document the conflict instead of working around it.

## 3. Required reading order

Before editing code, read completely:

1. `docs/V0.4_SPEC.md`
2. `docs/v0.4/ARCHITECTURE.md`
3. `docs/v0.4/SKILLS_SPEC.md`
4. `docs/v0.4/MCP_TOOL_CONTRACTS.md`
5. `docs/v0.4/REPOSITORY_REGISTRY_AND_SECURITY.md`
6. `docs/v0.4/HANDOFF_PROTOCOL.md`
7. `docs/v0.4/PACKAGING_DEPLOYMENT_AND_TESTING.md`
8. `docs/v0.4/IMPLEMENTATION_PLAN.md`
9. `docs/v0.4/DECISIONS_AND_OPEN_QUESTIONS.md`
10. `docs/v0.4/ACCEPTANCE_CHECKLIST.md`
11. current `README.md`, `docs/ROADMAP.md`, and `skills/pro-planning/SKILL.md`
12. existing reliability modules and tests in `src/codex_pro_planning_bridge/` and `tests/`

Do not implement from this instruction file alone.

## 4. Initial repository procedure

Run:

```bash
git fetch origin --prune --tags
git switch main
git pull --ff-only origin main
git status --short
git log --oneline -10
```

Confirm:

- the worktree is clean;
- main contains the v0.3.3-beta.1 reliability hotfix;
- all existing tests pass;
- no untracked local planning artifact will be committed accidentally.

Run the baseline quality suite:

```bash
python -m unittest discover -s tests -v
ruff check src scripts tests
mypy src
python -m compileall -q src scripts tests
```

Record the baseline test count and current main SHA in the first implementation PR.

## 5. Branching model

Do not implement all phases on one branch.

Use the exact phased branches in `IMPLEMENTATION_PLAN.md`, beginning with:

```text
feat/v0.4-repository-registry
```

Each phase:

1. starts from the latest reviewed/merged main;
2. has a corresponding GitHub Issue;
3. contains focused commits;
4. opens a Draft PR;
5. stops for review;
6. is merged before dependent phases begin.

Do not stack Phase 3–9 on an unreviewed Phase 1 branch.

## 6. Phase 1 execution prompt

Use this as the first concrete task:

```text
Implement v0.4 Phase 1: Repository Registry and allowlist CLI.

Read and follow:
- docs/V0.4_SPEC.md
- docs/v0.4/ARCHITECTURE.md
- docs/v0.4/REPOSITORY_REGISTRY_AND_SECURITY.md
- docs/v0.4/IMPLEMENTATION_PLAN.md, Phase 1
- docs/v0.4/ACCEPTANCE_CHECKLIST.md

Create branch:
feat/v0.4-repository-registry

Create a GitHub Issue titled:
Implement v0.4 repository registry and allowlist CLI

Implement only:
- versioned per-user repository registry;
- safe canonical path registration;
- cpb repo add/list/show/remove/doctor;
- atomic locked persistence;
- symlink/junction and sensitive-root protections;
- typed models and comprehensive tests;
- documentation needed for Phase 1.

Do not implement:
- MCP server or tools;
- Plan Capsule;
- Skills split;
- .app.json or .mcp.json;
- ChatGPT integration;
- OpenAI API or API keys.

Preserve all existing v0.3.3 behavior and tests.

Run:
python -m unittest discover -s tests -v
ruff check src scripts tests
mypy src
python -m compileall -q src scripts tests

Use focused commits. Open a Draft PR and stop for review.
```

## 7. General implementation rules

### 7.1 Reuse before adding

Before creating a new algorithm, inspect existing modules for:

- path resolution;
- atomic writes and locks;
- sensitive path filtering;
- Git status/diff;
- context collection;
- symbol index/graph;
- validator;
- plan parsing;
- memory;
- approval and integrity.

Refactor shared logic only when tests cover old and new behavior. Do not copy existing logic into `mcp_server/`.

### 7.2 Typed boundaries

Core modules communicate through dataclasses or explicit typed structures. Avoid raw dictionaries except at JSON/MCP serialization edges.

Every versioned artifact requires:

- schema version;
- parser/validator;
- unsupported-newer-version rejection;
- deterministic serialization;
- migration or explicit no-migration policy;
- tests.

### 7.3 Read-only proof

For every MCP service/tool test:

1. snapshot repository files and relevant metadata before the call;
2. run the call;
3. compare after state;
4. fail on any mutation outside explicit local operational logs.

The server may write bounded operational logs outside the repository if configured. Tool handlers may not update repository `.codex` artifacts.

### 7.4 Error handling

Expected errors return stable user-facing codes. Do not expose tracebacks, absolute paths, environment variables, or registry contents through MCP.

Unexpected errors:

- log a redacted request ID locally;
- return `INTERNAL_ERROR`;
- do not partially write registry/runtime artifacts;
- remain fail closed.

### 7.5 Git subprocesses

Use only fixed Git commands and arguments assembled from validated refs/IDs. Do not invoke a shell. Do not run hooks, fetch, checkout, reset, clean, submodule, arbitrary config, pager, or editor.

### 7.6 Dependencies

Prefer the standard library and the official Python MCP SDK. Any new dependency requires:

- reason;
- security/maintenance review;
- version bound;
- license compatibility;
- tests on Python 3.10+;
- documentation.

Do not add an OpenAI model/client SDK.

## 8. Documentation responsibilities during implementation

Update documentation with the code in the same PR when behavior becomes real.

Do not mark a feature complete until:

- code exists;
- tests pass;
- CLI/tool help is accurate;
- examples are verified;
- Roadmap status is updated;
- manifest/package versions are synchronized at release gates.

Keep speculative commands out of Skills. Secure MCP Tunnel and developer-mode instructions should link to current official docs and record tested commands in developer documentation only after verification.

## 9. Review stop conditions

Stop and request review when:

- a phase’s acceptance criteria are met;
- an official platform behavior differs from the spec;
- `.app.json` or plugin creator output differs from expected structure;
- ChatGPT Pro does not expose the required custom MCP capability for the tested account/surface;
- a write action appears necessary on ChatGPT;
- repository context cannot be bounded without losing essential information;
- a security boundary requires relaxing path or tool policy;
- a P0/P1 issue appears;
- a dependency/API version requires an architectural change.

Do not silently revise architecture to “make it work.” Add a decision proposal to `DECISIONS_AND_OPEN_QUESTIONS.md` and stop.

## 10. Pull request requirements

Every phase PR must include:

```markdown
## Goal

## Spec references

## Included

## Explicitly not included

## Architecture notes

## Security and privacy impact

## Files or local state written

## Compatibility impact

## Automated tests

## Manual tests

## Rollback plan

## Open questions / follow-ups
```

For MCP-related PRs, also include:

- discovered tools and annotations;
- representative request/response examples;
- proof of no mutation;
- output bounds;
- MCP Inspector result;
- stdio/HTTP equivalence result.

For ChatGPT integration PRs, include:

- tested ChatGPT surface and account plan;
- developer mode state;
- plugin version;
- connection registration method;
- redacted tool-call transcript/evidence;
- limitations observed.

## 11. Commit guidance

Recommended focused commit style:

```text
feat: add versioned repository registry
feat: add repository allowlist CLI
fix: reject symlink escapes from registered roots
test: cover concurrent registry updates
docs: document repository registration
```

Avoid commits such as:

```text
implement v0.4
misc fixes
update files
```

Do not rewrite history after a PR is under review unless requested.

## 12. Quality gates

Run at every phase:

```bash
python -m unittest discover -s tests -v
ruff check src mcp_server scripts tests
mypy src mcp_server
python -m compileall -q src mcp_server scripts tests
```

When directories do not yet exist, adjust only the path list, not the checks’ intent.

Also check:

```bash
git diff --check
git status --short
```

At packaging phases:

- parse all JSON manifests/configs;
- inspect plugin paths;
- scan repository for secret/tunnel URLs;
- verify synchronized versions;
- test clean installation.

At MCP phases:

- run contract/integration tests;
- run MCP Inspector;
- verify no writes.

## 13. Required security regression suite

The Agent must add and preserve tests for:

- unknown/disabled repository;
- traversal-like repository ID;
- dangerous root registration;
- child symlink escape;
- sensitive files and secret directories;
- malicious README/source prompt injection;
- oversized repository and plan;
- corrupt registry and unsupported schema;
- concurrent registry write;
- arbitrary shell/path attempts;
- stale HEAD/context digest;
- ChatGPT write/approval bypass attempt;
- capsule for wrong repository;
- plan mutation after approval;
- existing workflow recovery/integrity behavior.

## 14. Plan changes

If implementation reveals a material spec change:

1. stop current coding phase;
2. add a dated proposal to `DECISIONS_AND_OPEN_QUESTIONS.md`;
3. identify affected documents and tests;
4. explain alternatives and recommendation;
5. obtain user/reviewer approval;
6. update docs in a separate commit;
7. resume implementation.

Material changes include:

- adding or removing public tools;
- introducing write capability;
- changing the Plan Capsule schema;
- accepting arbitrary paths;
- changing approval authority;
- changing connection/transport architecture;
- requiring a hosted service;
- adding OpenAI API usage;
- dropping CLI compatibility.

## 15. Definition of done for the local Agent

The Agent’s v0.4 implementation work is complete only when:

- all phases have merged through review;
- all acceptance checklist items applicable to alpha pass;
- ChatGPT Pro generates a validated capsule through the registered read-only MCP app;
- Codex imports and implements it with local approval;
- five dogfood workflows are documented;
- no P0/P1 findings remain;
- no API key/model API is present;
- the plugin installs from a clean local marketplace;
- release metadata is synchronized;
- a prerelease is prepared, not automatically published without user authorization.
