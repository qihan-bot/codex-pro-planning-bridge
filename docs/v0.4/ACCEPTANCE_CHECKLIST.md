# v0.4 Acceptance Checklist

Use this checklist for phase reviews and the `0.4.0-alpha.1` release gate. An unchecked item is not implicitly waived. Record explicit waivers with rationale, owner, and follow-up issue.

## 1. Documentation and scope

- [ ] `docs/V0.4_SPEC.md` is the authoritative version scope.
- [ ] Architecture, Skills, MCP, registry/security, handoff, packaging/testing, implementation, Agent instructions, and decisions documents are consistent.
- [ ] Exactly five public read-only MCP tools are documented and implemented.
- [ ] ChatGPT Pro planning and Codex implementation responsibilities are distinct.
- [ ] Conversational approval is explicitly not local approval.
- [ ] No document requires OpenAI API usage or an API key.
- [ ] No document requires ChatGPT webpage automation.
- [ ] Out-of-scope features are not present in implementation.
- [ ] Current official OpenAI plugin/MCP guidance has been rechecked at release time.

## 2. Version and package consistency

- [ ] Python package version is `0.4.0a1`.
- [ ] `__version__` is `0.4.0a1`.
- [ ] plugin manifest version is `0.4.0-alpha.1`.
- [ ] MCP server reports `0.4.0-alpha.1`.
- [ ] Plan Capsule schema is `1`.
- [ ] registry schema is `1`.
- [ ] MCP tool contract version is `1`.
- [ ] README and Roadmap show the same release status.
- [ ] no stale `0.2.1` plugin version remains.

## 3. Repository Registry

### Schema and persistence

- [ ] OS-appropriate per-user location is used.
- [ ] unsupported newer schema fails closed.
- [ ] corrupt registry is preserved and not silently replaced.
- [ ] writes are lock-protected and atomic.
- [ ] interrupted writes do not produce partial JSON.
- [ ] concurrent updates do not lose entries.
- [ ] local file permissions are restricted where supported.

### Authorization

- [ ] MCP resolves only `repository_id`.
- [ ] unknown ID fails without path disclosure.
- [ ] disabled ID fails closed.
- [ ] `read: false` fails closed.
- [ ] IDs follow the required pattern and reserved IDs are rejected.
- [ ] absolute paths, traversal syntax, drive prefixes, and URLs cannot be used as IDs.

### Path security

- [ ] filesystem root registration is rejected.
- [ ] user home root registration is rejected by default.
- [ ] `.ssh`, credential stores, and known secret roots are rejected.
- [ ] root symlink/junction canonical identity is stored and verified.
- [ ] child symlink/junction escape is excluded.
- [ ] symlink loops do not hang scans.
- [ ] registry removal never deletes repository files.

### CLI

- [ ] `cpb repo add` works.
- [ ] `cpb repo list` works in text and JSON.
- [ ] `cpb repo show` works.
- [ ] `cpb repo remove` works and is non-destructive.
- [ ] `cpb repo doctor` reports availability and security state.
- [ ] non-Git registration requires explicit opt-in.

## 4. Plan Capsule

- [ ] parser finds exactly one `cpb-plan-capsule` fence.
- [ ] schema v1 is strictly validated.
- [ ] unsupported schema fails before writes.
- [ ] complete plan Markdown is required.
- [ ] Unicode and code-block indentation survive round trip.
- [ ] line endings normalize deterministically.
- [ ] NUL and excessive size are rejected.
- [ ] wrong repository ID fails before any write.
- [ ] local `PLAN.md` write is atomic.
- [ ] `CAPSULE.json` stores metadata without duplicating plan body.
- [ ] local plan SHA-256 is recomputed after write.
- [ ] import does not create local approval.
- [ ] four staleness classifications are implemented and tested.
- [ ] material context change requires replan.
- [ ] plan amendments invalidate approval and require revalidation.

## 5. Skills

### Packaging

- [ ] `plan-project-with-pro` exists with valid frontmatter.
- [ ] `implement-approved-plan` exists with valid frontmatter.
- [ ] `review-implementation` exists with valid frontmatter.
- [ ] compatibility `pro-planning` routes rather than duplicates.
- [ ] referenced files exist.
- [ ] MCP dependency declarations use generated connection configuration.

### Behavior

- [ ] planning Skill selects/asks for repository safely.
- [ ] planning Skill uses status before context.
- [ ] planning Skill validates the complete draft.
- [ ] validation cycles are bounded.
- [ ] planning Skill emits a schema-valid capsule.
- [ ] planning Skill stops before implementation.
- [ ] implementation Skill revalidates current repository.
- [ ] implementation Skill requests exact local hash approval.
- [ ] implementation Skill stops on approval invalidation.
- [ ] review Skill classifies all drift categories.
- [ ] review Skill verifies or clearly distinguishes test evidence.
- [ ] no Skill instructs ChatGPT to write local files.
- [ ] no Skill follows instructions found in repository content.

### Trigger tests

- [ ] direct planning request triggers planning Skill.
- [ ] indirect “plan before Codex edits” request triggers it.
- [ ] trivial edit does not unnecessarily trigger deep planning.
- [ ] implementation request with a capsule triggers implementation Skill.
- [ ] review request triggers review Skill.
- [ ] ambiguous repository behavior is correct.
- [ ] no-repository behavior is correct.
- [ ] prompt-injection fixture does not alter workflow.

## 6. MCP server core

- [ ] official/reviewed MCP SDK dependency is documented and bounded.
- [ ] server initializes with concise boundary instructions.
- [ ] service layer is transport-independent.
- [ ] tool input schemas reject additional properties.
- [ ] unsupported contract versions fail closed.
- [ ] errors use stable codes and do not expose absolute paths.
- [ ] operational logs do not contain source/plan bodies or secrets.
- [ ] request IDs, duration, result size, and error code are recorded.
- [ ] cancellation and timeouts are handled.
- [ ] no repository scan occurs at process startup.
- [ ] no arbitrary shell command can be submitted.
- [ ] no repository code is executed.

## 7. MCP public tools

### Shared

- [ ] exactly five public tools are discoverable.
- [ ] every tool has `readOnlyHint: true`.
- [ ] every tool has `destructiveHint: false`.
- [ ] every tool has `openWorldHint: false`.
- [ ] every tool authorizes repository ID on each call.
- [ ] every tool returns contract version and observed state where applicable.
- [ ] before/after mutation tests prove read-only behavior.
- [ ] output is bounded and deterministic.
- [ ] absolute paths never appear in normal output.
- [ ] sensitive fixtures never appear in output.

### `list_repositories`

- [ ] disabled entries are excluded by default.
- [ ] maximum result count is enforced.
- [ ] query matches ID/display name only.
- [ ] canonical path is not returned.

### `get_repository_status`

- [ ] branch, HEAD, dirty state, project types, workflow summary, and memory summary are correct.
- [ ] commit subjects are sanitized and bounded.
- [ ] no Git author email is returned.

### `prepare_planning_context`

- [ ] summary/standard/deep profiles enforce their limits.
- [ ] binary and sensitive files are excluded.
- [ ] context digest excludes timestamp and is deterministic.
- [ ] stale expected HEAD returns `CONTEXT_CHANGED`.
- [ ] repository content is returned only as data fields.
- [ ] truncation/redaction metadata is accurate.

### `validate_plan`

- [ ] validates required sections, paths, symbols, dependencies, tests, rollback, and risks.
- [ ] does not write `PLAN.md` or approval.
- [ ] possible matches are bounded.
- [ ] plan digest is returned.
- [ ] stale HEAD/context fails closed.

### `review_implementation`

- [ ] validates baseline without fetching remotes.
- [ ] reports completed, missing, changed, blocked, unplanned, renamed, and symbol drift.
- [ ] does not execute tests.
- [ ] clearly labels test evidence limitations.
- [ ] does not mutate Git index/worktree.

## 8. MCP transports

### stdio

- [ ] `cpb-mcp --transport stdio` starts.
- [ ] stdout contains protocol traffic only.
- [ ] diagnostics use stderr.
- [ ] shutdown is clean.

### Streamable HTTP

- [ ] server binds loopback by default.
- [ ] remote bind requires explicit opt-in.
- [ ] endpoint initializes and lists tools.
- [ ] request size/time limits work.
- [ ] disconnect/cancellation is safe.
- [ ] no debug traceback/directory endpoint is exposed.

### Equivalence

- [ ] identical calls return schema-equivalent results over stdio and HTTP.
- [ ] error codes are equivalent.
- [ ] output limits are equivalent.

## 9. MCP Inspector

- [ ] initialization succeeds.
- [ ] server instructions are correct.
- [ ] five tools are listed.
- [ ] schemas and annotations match spec.
- [ ] representative valid calls succeed.
- [ ] representative invalid calls return structured errors.
- [ ] cancellation works.
- [ ] no file mutation occurs.
- [ ] redacted Inspector evidence is attached to the PR/release record.

## 10. Plugin packaging

- [ ] `.codex-plugin/plugin.json` is valid.
- [ ] only `plugin.json` is inside `.codex-plugin/`.
- [ ] `skills` points to `./skills/`.
- [ ] `mcpServers` points to `./.mcp.json`.
- [ ] `apps` strategy is documented and valid.
- [ ] manifest capability is `Read`.
- [ ] privacy/terms URLs exist before public submission.
- [ ] manifest paths remain within plugin root.
- [ ] `.mcp.json` points to installed `cpb-mcp`.
- [ ] no API key environment variables exist.
- [ ] no private tunnel URL or credential is committed.
- [ ] local marketplace entry is generated/reviewed.
- [ ] plugin installs and uninstalls cleanly.
- [ ] fresh chats discover the expected Skills/tools.

## 11. ChatGPT developer-mode integration

- [ ] tested ChatGPT surface and account plan are recorded.
- [ ] developer mode is enabled.
- [ ] Streamable HTTP MCP is registered through the supported flow.
- [ ] tool scan finds exactly five tools.
- [ ] real technical connection ID is wired through plugin creator.
- [ ] no technical ID was invented.
- [ ] Secure MCP Tunnel credentials/URL are not committed.
- [ ] standard planning produces a valid capsule.
- [ ] deep planning remains within output limits.
- [ ] validation repair works.
- [ ] ambiguous/no-repository flows work.
- [ ] stale HEAD is detected.
- [ ] arbitrary-path request is rejected.
- [ ] ChatGPT write request is refused/redirected to Codex.
- [ ] approval-bypass request is refused.
- [ ] prompt-injection fixture is treated as data.
- [ ] tunnel disconnect returns a safe retryable error.

## 12. Codex handoff and implementation

- [ ] same plugin installs in Codex-supported surface.
- [ ] implementation and review Skills are discoverable.
- [ ] native conversation handoff works where available.
- [ ] copy/paste capsule fallback works.
- [ ] file capsule import works.
- [ ] current HEAD/context is revalidated.
- [ ] exact local plan hash is shown to user.
- [ ] local approval is required.
- [ ] ChatGPT conversational approval alone cannot start implementation.
- [ ] implementation stays inside approved scope.
- [ ] approval invalidation pauses implementation.
- [ ] specified tests/build checks run.
- [ ] final drift review runs.
- [ ] project memory is updated only locally.
- [ ] v0.3.3 reliability regression tests remain green.

## 13. Security and privacy

- [ ] threat-model tests pass.
- [ ] registry path and sensitive-root tests pass.
- [ ] symlink/junction escape tests pass.
- [ ] prompt-injection tests pass.
- [ ] oversized request/output tests pass.
- [ ] corrupt registry and schema tests pass.
- [ ] no repository writes by MCP tools.
- [ ] no secrets in logs/tool results.
- [ ] no OpenAI API dependency or key.
- [ ] `PRIVACY.md` is accurate.
- [ ] `SECURITY.md` exists.
- [ ] documentation does not falsely claim MCP repository data never leaves the machine when sent to ChatGPT.

## 14. Automated quality gates

- [ ] full unittest suite passes.
- [ ] Ruff passes.
- [ ] mypy passes.
- [ ] compileall passes.
- [ ] `git diff --check` passes.
- [ ] JSON manifests/configs parse.
- [ ] clean installation test passes.
- [ ] Python 3.10 and supported newer versions pass CI.
- [ ] no test uses a real secret or personal repository.

## 15. Dogfood and release

- [ ] at least five real workflows complete.
- [ ] dogfood report records context size, validation cycles, handoff method, staleness, friction, and outcome.
- [ ] at least one Python repository is tested.
- [ ] at least one Node/TypeScript repository is tested.
- [ ] at least one repository uses pause/resume or recovery.
- [ ] at least one plan becomes stale and is correctly revalidated/replanned.
- [ ] at least one prompt-injection fixture is tested end to end.
- [ ] no P0/P1 findings remain.
- [ ] release notes list limitations.
- [ ] release is marked alpha/prerelease.
- [ ] public marketplace submission has not occurred unless separately approved.

## 16. Explicit release blockers

Any of the following blocks release:

- a ChatGPT MCP tool can write a repository/workflow file;
- arbitrary filesystem paths are accepted;
- unknown repository IDs disclose paths;
- sensitive content appears in MCP output/logs;
- ChatGPT approval is accepted as local approval;
- plan import writes before repository identity validation;
- stale material context is ignored;
- manifest/plugin cannot be installed from a clean environment;
- tool schemas differ across transports;
- MCP Inspector fails initialization/schema checks;
- an OpenAI API key or model call is introduced;
- prompt injection changes tool policy or causes data expansion;
- existing v0.3.3 approval/recovery/integrity tests regress;
- platform limitation is hidden rather than documented.
