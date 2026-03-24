# CLAUDE.md — dev-mcp-tools

## Project Overview

Python uv workspace monorepo with three packages:

| Package | Name in pyproject | Path | What it is |
|---------|------------------|------|-----------|
| Oracle | `project-oracle` | `packages/oracle/` | Stateful file cache MCP server (stdio) |
| Webhook | `webhook-mcp` | `packages/webhook/` | GitHub webhook receiver MCP server (SSE) |
| Shared | `mcp-shared` | `packages/shared/` | Common SQLite base, project detection, git helpers |

## Commands

```bash
# Install everything (ALWAYS from monorepo root, never from inside a package)
uv sync

# Test one package
uv run --package project-oracle pytest
uv run --package webhook-mcp pytest
uv run --package mcp-shared pytest packages/shared/tests/

# Test all packages
uv run pytest packages/shared/tests packages/oracle/tests packages/webhook/tests

# Coverage (oracle — 95% minimum enforced)
uv run --package project-oracle coverage run --branch -m pytest
uv run --package project-oracle coverage report --fail-under=95

# Type check
uv run mypy packages/oracle/src packages/shared/src packages/webhook/src

# Lint + format
uv run ruff check .
uv run ruff format --check .

# BDD scenarios (oracle only)
cd packages/oracle && uv run behave
```

## Lefthook

Pre-commit (parallel): `ruff check --fix` + `ruff format` on staged files.
Pre-push (sequential): `ruff check .`, `ruff format --check .`, `mypy packages/oracle/src packages/shared/src packages/webhook/src`, `pytest` all three packages.

## MCP Registration

Oracle is registered as a stdio MCP server pointing to the monorepo:

```json
{
  "command": "uv",
  "args": ["run", "--directory", "/Users/mikelane/dev/dev-mcp-tools", "--package", "project-oracle", "project-oracle"]
}
```

Webhook uses SSE: `claude mcp add --transport sse --scope user github-webhooks http://smee.local/sse`

## Workspace Rules

- **One venv, one lockfile.** The root `.venv/` and `uv.lock` are shared across all packages. Never create package-level venvs.
- **`uv sync` from root only.** Running it from inside a package directory will fail or create a rogue venv.
- **Cross-package deps by name.** Oracle depends on `"mcp-shared"` — uv resolves it to `packages/shared/` via `[tool.uv.sources]` in the root `pyproject.toml`. Do not use relative path dependencies.
- **Editable installs.** Changes to `packages/shared/src/` are immediately visible in Oracle and Webhook without reinstalling.

## Package Boundaries

- **shared** exports: `SQLiteBase`, `detect_project_root`, `detect_stack`, `StackInfo`, `git_cmd`, `get_remote_url`. Nothing else — keep it minimal.
- **oracle** imports from `mcp_shared` for project detection and git helpers. Re-exports names in `oracle.project` and `oracle.integrations.git` for backward compatibility.
- **webhook** is currently independent of shared (will depend on it after the webhook-bridge epic).
- **Do not import oracle from webhook or vice versa.** They communicate via the filesystem (`~/.project-oracle/ingest/` queue), not via Python imports.

## Test Conventions

Both Oracle and Webhook follow these conventions (inherited from parent `~/dev/CLAUDE.md`):

- Test classes: `Describe[Component]`
- Test methods: `it_[states what happens]` (present tense, no "should")
- `@pytest.mark.medium` for tests with I/O
- No branching, loops, or conditionals in tests
- Use `pytest-mock`'s `mocker` fixture, not `unittest.mock`
- Oracle: 95% coverage minimum, mutation testing with pytest-gremlins

## Oracle-Specific

- 7 MCP tools: `oracle_read`, `oracle_grep`, `oracle_status`, `oracle_run`, `oracle_ask`, `oracle_forget`, `oracle_stats`
- File cache uses zstd compression + SHA-256 validation + `_session_seen` set for cross-session awareness
- `server.py` calls `_before_tool()` at the top of every tool function (drains ingest queue)
- `server.py` calls `_log()` after every tool function (writes to agent_log table)
- AYLO hooks in `packages/oracle/hooks/` — installed at `~/.claude/hooks/`
- Command allowlist rejects `shell=True` — commands run via `shlex.split()` + `subprocess.run(shell=False)`

## Webhook-Specific

- Smee.io SSE client runs 24/7 as macOS LaunchAgent
- SQLite event store at `~/.local/share/github-webhook-mcp/events.db`
- PRReactor auto-triggers reviews on PR open/synchronize (debounced 15min)
- Webhook signature verification via HMAC-SHA256

## Active Epic

[Webhook-driven cache invalidation](https://github.com/mikelane/dev-mcp-tools/issues/1) — 6 issues remaining (#3-#7). Plan at `~/.claude/plans/dynamic-bubbling-hamster.md`.

## Repository Mapping

| Local Path | GitHub Owner | Repo |
|------------|-------------|------|
| `~/dev/dev-mcp-tools` | `mikelane` | `dev-mcp-tools` |

The original standalone repos (`mikelane/project-oracle`, `mikelane/github-webhook-mcp`) will be archived after the monorepo is validated in production.
