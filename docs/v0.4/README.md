# v0.4 ChatGPT Client Integration Documentation

Status: **Planning complete; implementation not started on this documentation branch.**

v0.4 changes Codex Pro Planning Bridge from a CLI-first tool into a client-first universal plugin:

```text
ChatGPT Pro
  -> read-only registered repository MCP
  -> validated Plan Capsule
  -> human planning approval
  -> Codex handoff
  -> local revalidation and hash-bound approval
  -> implementation, tests, drift review, and memory
```

The existing `cpb` runtime remains the deterministic backend and advanced troubleshooting interface.

## Read before implementation

Read the documents in this order:

1. [Master v0.4 specification](../V0.4_SPEC.md)
2. [Architecture](ARCHITECTURE.md)
3. [Skills specification](SKILLS_SPEC.md)
4. [MCP tool contracts](MCP_TOOL_CONTRACTS.md)
5. [Repository registry and security](REPOSITORY_REGISTRY_AND_SECURITY.md)
6. [ChatGPT-to-Codex handoff protocol](HANDOFF_PROTOCOL.md)
7. [Packaging, deployment, and testing](PACKAGING_DEPLOYMENT_AND_TESTING.md)
8. [Phased implementation plan](IMPLEMENTATION_PLAN.md)
9. [Local Agent instructions](LOCAL_AGENT_INSTRUCTIONS.md)
10. [Architecture decisions and open questions](DECISIONS_AND_OPEN_QUESTIONS.md)
11. [Acceptance checklist](ACCEPTANCE_CHECKLIST.md)

Also read current:

- [`README.md`](../../README.md)
- [`docs/ROADMAP.md`](../ROADMAP.md)
- [`skills/pro-planning/SKILL.md`](../../skills/pro-planning/SKILL.md)
- existing runtime and reliability tests.

## Fixed v0.4 alpha boundaries

- ChatGPT Pro plans; Codex implements.
- Plugin contains three focused Skills.
- ChatGPT MCP exposes five read-only tools.
- Repositories are selected by allowlisted `repository_id`, never arbitrary paths.
- ChatGPT emits a Plan Capsule instead of writing local files.
- Codex imports, revalidates, and obtains exact local hash approval.
- Existing validation, approval, workflow, snapshot, recovery, integrity, diff, and memory systems remain authoritative.
- No OpenAI API or API key.
- No ChatGPT webpage automation or scraping.
- No custom UI in the first alpha.
- No public marketplace submission before dogfood and security gates.

## Five public MCP tools

```text
list_repositories
get_repository_status
prepare_planning_context
validate_plan
review_implementation
```

All are read-only and transport-independent.

## Three Skills

```text
plan-project-with-pro
implement-approved-plan
review-implementation
```

The old `pro-planning` Skill remains temporarily as a compatibility router.

## Implementation phases

```text
1. Repository Registry
2. Plan Capsule
3. MCP core/service schemas
4. Five public read-only tools
5. stdio + Streamable HTTP transports
6. surface-focused Skills
7. universal plugin packaging and local marketplace
8. ChatGPT developer-mode + Secure MCP Tunnel integration
9. Codex handoff, dogfood, and alpha release
```

Each phase uses a separate Issue, branch, Draft PR, review stop, and merge.

## First task for the local Agent

Use the exact Phase 1 prompt in [`LOCAL_AGENT_INSTRUCTIONS.md`](LOCAL_AGENT_INSTRUCTIONS.md). The first implementation branch is:

```text
feat/v0.4-repository-registry
```

The Agent must stop after opening the Phase 1 Draft PR. It must not implement the MCP server on the same unreviewed branch.

## Platform notes

The implementation must re-check current official OpenAI documentation during integration:

- Plugin architecture: https://developers.openai.com/plugins/concepts/plugins
- Skills: https://developers.openai.com/plugins/build/skills
- MCP servers: https://developers.openai.com/plugins/build/mcp-server
- Plugin packaging: https://developers.openai.com/plugins/build/plugins
- ChatGPT developer mode: https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt

Current planning assumes:

- ChatGPT Pro uses read/fetch MCP tools in developer mode;
- local ChatGPT development requires Secure MCP Tunnel or another supported remote endpoint;
- Codex can use the bundled local stdio MCP server and local runtime;
- exact client availability may vary by rollout and must be documented in test evidence.

## Completion definition

Documentation is complete when all documents above are merged and internally consistent.

Implementation is complete only when:

- ChatGPT Pro can produce a repository-grounded, validated Plan Capsule;
- Codex can import it, revalidate current code, obtain local approval, implement it, and run review;
- read-only MCP security tests pass;
- MCP Inspector passes;
- the plugin installs in clean ChatGPT/Codex test environments where supported;
- at least five real dogfood workflows complete;
- no P0/P1 findings remain;
- no OpenAI API key or model API call exists.
