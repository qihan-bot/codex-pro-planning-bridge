# v0.4 ChatGPT Pro to Codex Handoff Protocol

Protocol name: **Plan Capsule**  
Schema version: `1`

## 1. Problem

ChatGPT Pro is the planning surface, but v0.4 does not assume that ChatGPT Pro can write local repository files. Codex needs an unambiguous, complete, and verifiable planning artifact that can survive conversation transfer, copy/paste, or client feature differences.

The Plan Capsule is the cross-surface transport format. It is not a local approval record and does not authorize implementation by itself.

## 2. Supported handoff paths

### 2.1 Native conversation handoff

Preferred when the ChatGPT client supports handing the current conversation to Codex with full context.

Requirements:

- the final assistant message still contains the complete Plan Capsule;
- Codex parses the capsule rather than relying on earlier draft discussion;
- the implementation Skill verifies repository ID, HEAD, context digest, and plan content locally;
- local approval remains mandatory.

### 2.2 Copy/paste Plan Capsule

Universal fallback:

```text
ChatGPT Pro final message
  -> user copies Plan Capsule
  -> user opens Codex in target repository
  -> user pastes capsule
  -> implementation Skill imports it
```

### 2.3 Saved capsule file

Advanced fallback:

- user saves the capsule as a UTF-8 Markdown or JSON file;
- Codex reads it locally;
- import logic extracts and validates the payload.

ChatGPT does not save the file automatically in v0.4.

### 2.4 Future write-enabled MCP

Business/Enterprise/Edu or future surface support may allow a controlled `store_plan` tool. That is out of scope for v0.4 Pro and must not be a dependency of the schema.

## 3. Capsule representation

The final ChatGPT response contains a fenced block with the exact marker:

````markdown
```cpb-plan-capsule
{
  "schema_version": 1,
  "plan_id": "cpb-plan-...",
  "repository_id": "my-app",
  "repository_head": "40-hex-or-null",
  "context_digest": "64-hex",
  "goal": "...",
  "created_at": "...",
  "planner_surface": "chatgpt-pro",
  "validation": {...},
  "plan_markdown": "# Objective\n..."
}
```
````

The capsule is JSON inside a distinct Markdown fence. Plain Markdown outside the block is explanatory and not imported.

## 4. Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CPB Plan Capsule v1",
  "type": "object",
  "required": [
    "schema_version",
    "plan_id",
    "repository_id",
    "repository_head",
    "context_digest",
    "goal",
    "created_at",
    "planner_surface",
    "validation",
    "plan_markdown"
  ],
  "properties": {
    "schema_version": {
      "type": "integer",
      "const": 1
    },
    "plan_id": {
      "type": "string",
      "pattern": "^cpb-plan-[a-z0-9-]{12,80}$"
    },
    "repository_id": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$"
    },
    "repository_head": {
      "type": ["string", "null"],
      "pattern": "^[0-9a-fA-F]{40}$"
    },
    "context_digest": {
      "type": "string",
      "pattern": "^[0-9a-fA-F]{64}$"
    },
    "goal": {
      "type": "string",
      "minLength": 1,
      "maxLength": 8000
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "planner_surface": {
      "type": "string",
      "enum": ["chatgpt-pro", "chatgpt-work", "manual"]
    },
    "validation": {
      "type": "object",
      "required": ["passed", "repository_head", "context_digest", "errors", "warnings"],
      "properties": {
        "passed": {"type": "boolean"},
        "repository_head": {"type": ["string", "null"]},
        "context_digest": {"type": "string"},
        "errors": {"type": "array", "items": {"type": "object"}},
        "warnings": {"type": "array", "items": {"type": "object"}},
        "validation_cycles": {"type": "integer", "minimum": 0, "maximum": 20}
      },
      "additionalProperties": true
    },
    "assumptions": {
      "type": "array",
      "items": {"type": "string"},
      "default": []
    },
    "open_questions": {
      "type": "array",
      "items": {"type": "string"},
      "default": []
    },
    "requested_constraints": {
      "type": "array",
      "items": {"type": "string"},
      "default": []
    },
    "plan_markdown": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200000
    }
  },
  "additionalProperties": false
}
```

## 5. Plan ID generation

The planning Skill should generate:

```text
cpb-plan-<UTC date>-<12+ random lowercase hex/base32 chars>
```

Example:

```text
cpb-plan-20260822-8f3a10c62d91
```

The ID is for correlation, not authentication. Never use it as an approval secret.

## 6. Plan Markdown normalization

The capsule transports exact Markdown as a JSON string. Import rules:

- decode JSON according to RFC 8259;
- preserve Unicode text;
- normalize line endings to LF when writing locally;
- ensure exactly one trailing newline in local `PLAN.md`;
- do not trim meaningful leading spaces inside code blocks;
- do not rewrite headings or list numbering;
- reject NUL characters;
- reject content over the configured size limit;
- compute local SHA-256 after normalization and persistence.

The capsule does not need to contain `plan_sha256`; the local runtime is authoritative. If a future field is added, it is only a transport integrity hint until recomputed locally.

## 7. ChatGPT planning completion

Before emitting a capsule, the planning Skill must ensure:

- `validation.passed` is true, or explicitly mark the capsule as not implementation-ready;
- validation HEAD equals capsule `repository_head`;
- validation context digest equals capsule `context_digest`;
- all required plan sections are present;
- unresolved questions that block implementation are clearly listed;
- plan text does not contain absolute local paths;
- no secret-looking content is included;
- no statement claims local approval exists.

When validation does not pass, the Skill may emit a **draft capsule** only if it adds:

```json
"implementation_ready": false
```

Because schema v1 uses `additionalProperties: false`, this field must be included in the final schema implementation if draft capsules are supported. The preferred v0.4 alpha behavior is to avoid draft capsules and return findings outside the capsule.

## 8. User approval in ChatGPT

When the user says “批准” or equivalent in ChatGPT:

- record this only as conversational confirmation of the planning direction;
- state that Codex will revalidate the current repository;
- do not create or simulate `APPROVAL.json`;
- do not say implementation is authorized yet;
- provide the final capsule again if the user’s approval follows a long conversation or any plan change.

## 9. Codex import

Target CLI/runtime functions:

```bash
cpb plan import --repo . --capsule-file <file>
cpb plan import --repo . --stdin
cpb plan inspect --repo .
```

The implementation Skill may invoke equivalent Python APIs directly, but CLI behavior must exist for testing and fallback.

Import steps:

1. locate exactly one `cpb-plan-capsule` fenced block;
2. parse JSON strictly;
3. reject unsupported schema;
4. validate repository ID against local registry or explicit active repository mapping;
5. compare capsule HEAD to current HEAD;
6. compare capsule context digest with a newly prepared bounded context when required;
7. write exact normalized plan Markdown atomically;
8. persist capsule metadata separately from `PLAN.md`;
9. run local validation;
10. return import status without approving.

Suggested metadata file:

```text
.codex/pro-plan/CAPSULE.json
```

It contains:

- capsule schema version;
- plan ID;
- repository ID;
- original HEAD/context digest;
- imported-at timestamp;
- planner surface;
- local plan SHA-256;
- local validation HEAD/digest;
- staleness classification.

It must not duplicate complete plan Markdown.

## 10. Staleness classification

When current HEAD differs from capsule HEAD:

### 10.1 `UNCHANGED`

HEAD and relevant context match. Continue.

### 10.2 `NON_MATERIAL_CHANGE`

Examples:

- documentation outside planned scope;
- unrelated test fixture;
- ignored generated file.

Requirements:

- local validator passes;
- relevant paths/symbols/dependencies are unchanged;
- user is informed.

### 10.3 `REVALIDATION_REQUIRED`

Examples:

- nearby implementation files changed;
- symbol moved or renamed;
- manifest or dependency changed without invalidating architecture.

Action:

- re-run context and validator;
- show differences;
- require explicit user approval of the updated local hash.

### 10.4 `REPLAN_REQUIRED`

Examples:

- API/data model changed materially;
- migration baseline changed;
- plan references removed files or symbols;
- security/compatibility assumptions no longer hold;
- repository is on a different major branch.

Action:

- stop implementation;
- return to ChatGPT Pro planning Skill with fresh context.

## 11. Local validation and approval

After successful import:

```text
CAPSULE imported
  -> PLAN.md written
  -> local validator runs
  -> local plan SHA-256 displayed
  -> user explicitly approves exact hash
  -> APPROVAL.json created through existing v0.3.3 runtime
```

The user approval prompt must include:

- repository ID/name;
- current HEAD;
- plan ID;
- plan SHA-256;
- validation status;
- summary of affected files/modules;
- high-risk operations;
- statement that plan modifications invalidate approval.

## 12. Amendments

Minor implementation detail not changing architecture may be recorded as an implementation note.

A plan amendment is required when changing:

- scope or non-goals;
- public API;
- data schema/migration;
- authentication/authorization design;
- deployment topology;
- compatibility promise;
- named major dependencies;
- rollback strategy;
- risk classification.

Amendment flow:

1. pause workflow;
2. invalidate current approval;
3. obtain an updated capsule or explicit local amendment document;
4. rewrite `PLAN.md`;
5. validate;
6. approve new hash;
7. resume.

## 13. Review correlation

Final drift reports should include:

- plan ID;
- capsule repository HEAD;
- implementation baseline;
- imported local plan SHA-256;
- final repository HEAD;
- workflow ID/state;
- validation and test summaries.

This enables ChatGPT Pro to perform a later read-only review without seeing local approval secrets or absolute paths.

## 14. Failure cases

Reject or stop on:

- multiple capsule blocks;
- malformed JSON;
- unsupported schema;
- unknown repository ID;
- missing plan Markdown;
- validation marked failed;
- inconsistent validation HEAD/digest;
- capsule generated for another repository;
- stale material context;
- embedded NUL or excessive size;
- absolute paths that expose local identity;
- plan text attempting to override approval or Skill instructions.

## 15. Tests

Unit tests:

- valid capsule round trip;
- Unicode and code-block preservation;
- CRLF/LF normalization;
- multiple/missing fences;
- malformed JSON;
- unsupported schema;
- size and NUL rejection;
- deterministic local digest;
- metadata persistence without plan duplication.

Integration tests:

- ChatGPT-shaped capsule -> local import -> validation -> approval;
- changed HEAD with each staleness classification;
- plan mutation invalidates local approval;
- native conversation text with drafts plus one final capsule imports only the final capsule;
- capsule for wrong repository fails without writing files.
