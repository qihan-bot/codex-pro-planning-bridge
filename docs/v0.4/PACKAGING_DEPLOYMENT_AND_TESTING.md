# v0.4 Plugin Packaging, Deployment, and Test Plan

## 1. Objective

Package one plugin that can be discovered from supported ChatGPT and Codex surfaces while using different MCP connection mechanisms:

- ChatGPT: registered remote Streamable HTTP MCP connection through `.app.json`;
- Codex: bundled local stdio MCP server through `.mcp.json`;
- both: the same Skills and plugin identity.

The reference implementation follows the current OpenAI plugin documentation. Platform UI and availability are subject to rollout, so acceptance evidence must record the exact surface and account plan used.

## 2. Target package structure

```text
codex-pro-planning-bridge/
├── .codex-plugin/
│   └── plugin.json
├── .app.json
├── .app.example.json
├── .mcp.json
├── .agents/
│   └── plugins/
│       └── marketplace.json          # repo-local authoring/testing catalog
├── assets/
│   ├── icon.png                      # do not add font files
│   ├── logo.png
│   └── screenshots/
├── skills/
├── mcp_server/
├── src/
└── docs/
```

Only `plugin.json` belongs in `.codex-plugin/`. All other package files remain at the plugin root.

## 3. Target plugin manifest

The implementation should evolve `.codex-plugin/plugin.json` toward:

```json
{
  "name": "codex-pro-planning-bridge",
  "version": "0.4.0-alpha.1",
  "description": "Use ChatGPT Pro to plan complex repository changes and hand validated plans to Codex for locally approved implementation and review.",
  "author": {
    "name": "qihan-bot",
    "url": "https://github.com/qihan-bot"
  },
  "homepage": "https://github.com/qihan-bot/codex-pro-planning-bridge",
  "repository": "https://github.com/qihan-bot/codex-pro-planning-bridge",
  "license": "MIT",
  "keywords": [
    "codex",
    "chatgpt-pro",
    "software-architecture",
    "planning",
    "repository",
    "mcp",
    "local-first"
  ],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json",
  "apps": "./.app.json",
  "interface": {
    "displayName": "Codex Pro Planning Bridge",
    "shortDescription": "Plan with ChatGPT Pro, implement with Codex",
    "longDescription": "Read bounded context from explicitly registered repositories, create and validate architecture plans in ChatGPT Pro, then hand them to Codex for hash-bound local approval, implementation, testing, drift review, and project memory.",
    "developerName": "qihan-bot",
    "category": "Developer Tools",
    "capabilities": ["Read"],
    "websiteURL": "https://github.com/qihan-bot/codex-pro-planning-bridge",
    "privacyPolicyURL": "https://github.com/qihan-bot/codex-pro-planning-bridge/blob/main/PRIVACY.md",
    "termsOfServiceURL": "https://github.com/qihan-bot/codex-pro-planning-bridge/blob/main/TERMS.md",
    "defaultPrompt": [
      "Use ChatGPT Pro to plan a complex feature for my registered repository.",
      "Validate this architecture plan against the current repository.",
      "Implement the approved Plan Capsule in Codex.",
      "Review the implementation for drift from the approved plan."
    ],
    "brandColor": "#10A37F",
    "composerIcon": "./assets/icon.png",
    "logo": "./assets/logo.png",
    "screenshots": ["./assets/screenshots/planning-flow.png"]
  }
}
```

Implementation notes:

- manifest paths begin with `./` and remain within the plugin root;
- capability metadata is `Read` for v0.4 ChatGPT tools;
- version must be synchronized with the Python package’s `0.4.0a1` representation;
- update the current stale manifest version (`0.2.1`);
- do not add `Write` until a separately reviewed write-enabled release exists;
- legal URLs must resolve before public submission;
- visual assets are implementation deliverables, but UI is optional for local alpha.

## 4. `.app.json` lifecycle

`.app.json` references a registered ChatGPT MCP connection. Its technical ID is created by ChatGPT developer mode and begins with `plugin_asdk_app...`.

Do not invent or hardcode an ID before registration.

Development sequence:

1. run the Streamable HTTP MCP server locally;
2. expose it with Secure MCP Tunnel;
3. enable developer mode in ChatGPT;
4. register the MCP endpoint and scan tools;
5. copy the generated `plugin_asdk_app...` technical ID;
6. invoke `@plugin-creator` in ChatGPT Work or `$plugin-creator` in Codex;
7. ask it to wire that ID into this existing plugin and create a personal or repo marketplace entry;
8. review the generated `.app.json`;
9. verify `plugin.json` contains `"apps": "./.app.json"`;
10. never commit a private tunnel URL, access token, or authentication secret.

Repository strategy:

- commit `.app.example.json` with descriptive placeholders if useful;
- commit `.app.json` only when it contains a stable, intended registered connection ID and no secret;
- otherwise gitignore `.app.json` during early tunnel testing and generate it per developer;
- the release process must explicitly decide which strategy is used.

## 5. Bundled `.mcp.json`

Target local Codex configuration:

```json
{
  "repository-planning": {
    "command": "cpb-mcp",
    "args": ["--transport", "stdio"],
    "tool_timeout_sec": 120
  }
}
```

Requirements:

- `cpb-mcp` is installed by the Python package or a thin console-script entry point;
- no environment variable for `OPENAI_API_KEY` exists;
- the bundled server exposes the same five read-only tools;
- users can disable the server or restrict tools in Codex plugin configuration;
- stdio output contains MCP protocol messages only; diagnostics go to stderr;
- process startup does not scan repositories until a tool call occurs.

## 6. Streamable HTTP server

Development command target:

```bash
cpb-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Requirements:

- bind to loopback by default;
- remote/public bind requires an explicit flag;
- expose the supported MCP endpoint path documented by the selected SDK;
- include server name and version;
- return concise server instructions;
- enforce request size/time limits;
- support graceful shutdown;
- never expose a directory listing or debug traceback endpoint;
- provide a separate minimal health check only if the deployment platform requires it;
- authentication/session handling follows the Secure MCP Tunnel or hosted deployment mechanism.

Use the official Python MCP SDK (`mcp`) unless implementation review identifies a blocking incompatibility. The server must support Streamable HTTP and stdio through shared handlers.

## 7. Secure MCP Tunnel development

ChatGPT cannot directly connect to a local MCP server. The reference development path uses Secure MCP Tunnel.

Tunnel test requirements:

- tunnel targets only the MCP server endpoint;
- local server stays bound to loopback;
- tunnel credentials are not committed;
- restart behavior is documented;
- expected connection URL is stored only in local developer notes/configuration;
- tool scan succeeds through the tunnel;
- cancellation and streaming behavior are tested;
- disconnects produce retryable errors without corrupting repository state.

Because tunnel commands and availability may evolve, implementation documentation must link to the current official Secure MCP Tunnel guide rather than freezing undocumented command syntax in Skills.

## 8. Local marketplace

For repo-scoped testing, target:

```text
$REPO_ROOT/.agents/plugins/marketplace.json
```

For personal testing:

```text
~/.agents/plugins/marketplace.json
```

The local Agent should use `@plugin-creator`/`$plugin-creator` to generate the first valid catalog entry rather than guessing unsupported fields.

Acceptance:

- marketplace JSON parses;
- plugin source path begins with `./` relative to marketplace root;
- display name is correct;
- plugin installs from the local source;
- refresh/reinstall behavior is documented;
- a fresh chat sees the new Skills and tools.

## 9. Surface compatibility matrix

| Surface | v0.4 target | MCP mode | Writes | Required validation |
|---|---|---|---|---|
| ChatGPT Pro web/client where supported | Planning | registered read/fetch MCP | none | developer mode, tool scan, direct prompt tests |
| ChatGPT Work | Planning and plugin authoring | registered MCP | none in Pro-compatible path | plugin creator, local marketplace |
| Codex desktop/CLI | Implementation and review | bundled stdio MCP plus local shell | local Codex writes | Skills, approval, tests, drift review |
| Deep research | Optional read-only context | read/fetch only | none | not a primary acceptance path |
| Agent mode | Not supported for custom app dependency | none | none | explicit fallback message |
| Mobile | Not an alpha acceptance target | varies/unavailable | none | document limitation |

If the ChatGPT desktop surface cannot currently use the custom MCP app on the user’s plan, the reference planning acceptance path is ChatGPT web developer mode. The plugin package must still remain compatible with the universal directory and must not add a second architecture.

## 10. Test layers

### 10.1 Static package tests

Verify:

- manifest JSON and required fields;
- synchronized versions;
- paths stay inside plugin root;
- referenced Skills/assets/config files exist;
- `.app.json` strategy is consistent;
- `.mcp.json` parses and points to an installed command;
- no secret or tunnel URL is committed;
- no `OPENAI_API_KEY` appears in runtime instructions/configuration.

### 10.2 Unit tests

Cover:

- registry schema and persistence;
- Plan Capsule parser/normalizer;
- MCP input/output schemas;
- service authorization;
- output limits and redaction;
- stable context digest;
- error envelopes;
- transport-independent handlers.

### 10.3 Integration tests

Run the MCP server in-process or as a subprocess and test:

- initialize;
- list tools;
- every tool with valid/invalid input;
- cancellation;
- concurrency;
- unavailable repository;
- malformed registry;
- non-Git repository;
- stale HEAD;
- no file mutation;
- stdio/HTTP result equivalence.

### 10.4 MCP Inspector

For each release candidate:

1. start Streamable HTTP server;
2. connect MCP Inspector;
3. verify initialization and server instructions;
4. inspect five tool schemas and annotations;
5. call representative valid and invalid cases;
6. verify structured results and errors;
7. verify no writes;
8. save a redacted test record.

### 10.5 ChatGPT developer-mode tests

Use a fresh chat for each category:

Direct:

- “Use the plugin to plan OAuth support for repository my-app.”
- “Validate this plan against my-app.”

Indirect:

- “Before Codex changes authentication, make a repository-grounded plan.”

Ambiguous:

- request without repository ID when multiple are registered.

Adversarial:

- repository README containing prompt injection;
- request for `.ssh` or an arbitrary path;
- request to write `PLAN.md` from ChatGPT;
- request to skip local approval;
- oversized plan.

Out of scope:

- trivial spelling fix;
- non-software request;
- request for immediate production deployment.

Record:

- client version/surface;
- account plan;
- developer mode state;
- installed plugin version;
- MCP connection ID (redacted where appropriate);
- tool calls selected;
- unexpected behavior.

### 10.6 Codex tests

- install from repo marketplace;
- discover implementation/review Skills;
- import valid capsule;
- reject wrong repository capsule;
- detect stale HEAD;
- local validation;
- explicit hash-bound approval;
- implementation stop on approval invalidation;
- review and memory update;
- recovery/integrity regression suite remains green.

### 10.7 End-to-end acceptance scenario

Reference scenario:

1. register a fixture repository as `oauth-demo`;
2. use ChatGPT Pro planning Skill;
3. observe repository tools and context digest;
4. draft and validate plan;
5. approve planning direction in ChatGPT;
6. transfer capsule to Codex;
7. import locally;
8. simulate a harmless and a material HEAD change in separate runs;
9. obtain local hash approval;
10. implement fixture change;
11. run tests;
12. review drift;
13. update memory;
14. verify audit and workflow state;
15. verify ChatGPT never wrote files and no OpenAI API key existed.

## 11. Release gates

### Alpha.1 documentation/skeleton gate

- all v0.4 planning docs merged;
- manifest version corrected in implementation branch;
- three Skill skeletons exist;
- registry CLI skeleton exists;
- MCP server initializes and advertises placeholder/implemented tools;
- no public release.

### Alpha.2 functional MCP gate

- all five tools implemented;
- registry/security tests pass;
- stdio and HTTP transports pass;
- MCP Inspector passes;
- local marketplace install works.

### Beta gate

- ChatGPT developer-mode planning works end-to-end;
- Codex handoff works end-to-end;
- at least five real-project dogfood runs;
- security/privacy docs complete;
- no P0/P1 findings;
- version and package metadata synchronized.

### Public submission gate

- stable remote MCP endpoint or documented supported distribution model;
- privacy/terms URLs live;
- assets and screenshots complete;
- plugin guidelines and MCP review requirements checked against current official docs;
- submission checklist passed;
- no secrets or personal connection IDs exposed unintentionally.

## 12. Fallback behavior

When ChatGPT custom MCP is unavailable:

- Skills-only mode may still guide the user to upload/provide repository context, but must clearly state that it is not live repository access;
- CLI-first `cpb prompt/open` remains available;
- Codex implementation/review Skills remain usable locally;
- do not substitute the OpenAI API.

When Secure MCP Tunnel is unavailable:

- use a trusted temporary hosted endpoint for development only if security requirements are met;
- otherwise stop ChatGPT integration testing and continue unit/Codex testing;
- never expose an unauthenticated local MCP endpoint directly to the public internet.
