# dev-mcp-tools

A monorepo for the local MCP servers that sit alongside Claude Code — one caches file reads and command results across sessions, the other pipes GitHub webhooks into the conversation.

## Packages

| Package | What it does | Transport |
|---------|-------------|-----------|
| **[oracle](packages/oracle/)** | Caches file reads, command results, and git state across sessions. Returns compact deltas on repeat reads instead of full content. | stdio (per-session) |
| **[webhook](packages/webhook/)** | Receives GitHub webhooks via Smee.io and exposes PR reviews, CI status, and notifications as MCP tools. | SSE (24/7 daemon) |
| **[shared](packages/shared/)** | Common infrastructure — SQLite base class, project detection, git helpers. | library (no server) |

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (package manager and workspace tool)
- **[jq](https://jqlang.github.io/jq/)** (required for AYLO hooks)

## Setup

```bash
git clone https://github.com/mikelane/dev-mcp-tools.git
cd dev-mcp-tools
uv sync
```

That's it. `uv sync` installs all three packages and their dependencies into a single shared virtualenv at the repo root.

## Running Tests

```bash
# All packages
uv run pytest packages/shared/tests packages/oracle/tests packages/webhook/tests

# One package at a time
uv run --package mcp-shared pytest
uv run --package project-oracle pytest
uv run --package webhook-mcp pytest

# With coverage (oracle)
uv run --package project-oracle coverage run --branch -m pytest
uv run --package project-oracle coverage report --fail-under=95

# Type checking
uv run mypy packages/oracle/src packages/shared/src

# Linting
uv run ruff check .
uv run ruff format --check .
```

## Managing the Monorepo

### How it works

This is a **uv workspace**. The root `pyproject.toml` declares `members = ["packages/*"]`, which tells uv to treat every directory under `packages/` as a workspace member. All members share:

- **One lockfile** (`uv.lock`) — no version conflicts between packages
- **One virtualenv** (`.venv/` at the root) — all packages installed in editable mode
- **Cross-package imports** — `oracle` imports from `mcp-shared` by name, uv resolves it to `packages/shared/` automatically

### Common operations

**Add a dependency to a specific package:**
```bash
uv add --package project-oracle httpx
uv add --package project-oracle --dev pytest-xdist
```

**Run a command in a specific package context:**
```bash
uv run --package project-oracle python -c "from oracle.server import mcp; print(mcp)"
uv run --package webhook-mcp python -c "from github_webhook_mcp.server import mcp; print(mcp)"
```

**Add a new package:**
```bash
mkdir -p packages/newpkg/src/newpkg
# Create packages/newpkg/pyproject.toml (see packages/shared/ for template)
uv sync  # auto-discovers via the "packages/*" glob
```

### Things to avoid

- **Don't run `uv sync` from inside a package directory** — always run from the monorepo root. Package-level `pyproject.toml` files are metadata, not standalone project roots.
- **Don't create separate `.venv` per package** — the single root venv is the source of truth.
- **Don't pin different versions of the same dep across packages** — the shared lockfile prevents this. If you try, uv will error.

### Development workflow

Feature work uses git worktrees for isolation:

```bash
# Create a worktree for your feature
git worktree add .worktrees/issue-42-feature -b issue-42-feature

# Install deps in the worktree
cd .worktrees/issue-42-feature
uv sync

# Work across packages — changes to shared/ are immediately visible in oracle/
# Push and create PR when done
```

## Registering the MCP Servers

### Project Oracle (stdio, per-session)

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "project-oracle": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/dev-mcp-tools/packages/oracle", "project-oracle"]
    }
  }
}
```

### GitHub Webhook MCP (SSE, 24/7 daemon)

Register via CLI:

```bash
claude mcp add --transport sse --scope user github-webhooks http://smee.local/sse
```

See [packages/webhook/README.md](packages/webhook/README.md) for Smee.io channel setup and LaunchAgent configuration.

## Architecture

```
Claude Code
    │
    ├──(stdio)──► Project Oracle          GitHub
    │             ├── File cache            │
    │             ├── Git state          webhooks
    │             ├── Command cache         │
    │             └── Token savings         ▼
    │                                    Smee.io
    ├──(SSE)───► GitHub Webhook MCP        │
    │             ├── PR reviews       ◄───┘
    │             ├── CI status
    │             └── Notifications
    │
    └── Both servers use mcp-shared for:
        ├── SQLite base (WAL mode)
        ├── Project root detection
        └── Git remote helpers
```

## Roadmap

- **Webhook-driven cache invalidation** — When GitHub push events arrive with changed file paths, Oracle proactively marks those files as stale. The agent sees "remote has newer version" before anyone runs `git pull`. ([Epic #1](https://github.com/mikelane/dev-mcp-tools/issues/1))

## License

Oracle: [MIT](packages/oracle/LICENSE) | Webhook: [Apache 2.0](packages/webhook/LICENSE)
