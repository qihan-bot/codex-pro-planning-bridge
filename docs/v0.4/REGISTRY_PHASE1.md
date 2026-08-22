# v0.4 Phase 1 — Repository Registry

Status: **Implementation complete on `feat/v0.4-repository-registry`; stop at Draft PR review.**

This phase establishes the local authorization boundary needed by later
read-only Repository MCP tools. It does not implement MCP or connect to
ChatGPT. ChatGPT Pro remains the planning surface, Codex remains the
implementation surface, and the CLI remains the local runtime/debug surface.

## Delivered

- schema-versioned per-user `repositories.json` storage;
- lowercase canonical repository IDs with reserved-ID and traversal-like input
  rejection;
- canonical path registration with Git detection and explicit non-Git opt-in;
- `cpb repo add`, `list`, `show`, `remove`, and `doctor`;
- lock-protected read/validate/write cycles and same-directory atomic replacement;
- fail-closed handling for corrupt or unsupported newer registry schemas;
- Unix `0600` best-effort permissions and user-profile storage on Windows;
- filesystem-root, user-home, bridge-config, credential/secret-root, and
  sensitive-path protections;
- root symlink/junction canonicalization and bounded child-link containment
  checks; and
- tests for CLI behavior, no repository mutation, concurrent writers,
  interrupted writes, symlink boundaries, and schema corruption.

## Local registry location

The default file is:

- Windows: `%APPDATA%\codex-pro-planning-bridge\repositories.json`;
- macOS: `~/Library/Application Support/codex-pro-planning-bridge/repositories.json`;
- Linux: `${XDG_CONFIG_HOME:-~/.config}/codex-pro-planning-bridge/repositories.json`.

For local tests or managed deployments, the CLI accepts `--registry-path` and
the `CPB_REGISTRY_PATH` environment variable. This override is not exposed to
model-facing MCP tools.

## CLI examples

```bash
cpb repo add my-app D:\Projects\my-app
cpb repo add notes D:\Notes --allow-non-git --yes
cpb repo list --format json
cpb repo show my-app
cpb repo doctor my-app
cpb repo remove my-app
```

`add` and `remove` ask for explicit confirmation unless `--yes` is supplied.
`remove` deletes only the registry entry. The CLI may show local canonical
paths; a future MCP response must not return them.

## Verification

The branch keeps the v0.3.3 runtime behavior and adds focused registry tests.
Before opening the Draft PR, run:

```bash
python -m unittest discover -s tests -v
ruff check src scripts tests
mypy src
python -m compileall -q src scripts tests
git diff --check
```

The next phase may begin only after the registry Draft PR is reviewed. It must
not add MCP tools, Plan Capsule, Skills, `.app.json`, `.mcp.json`, browser
automation, OpenAI API calls, or `OPENAI_API_KEY` configuration to this branch.
