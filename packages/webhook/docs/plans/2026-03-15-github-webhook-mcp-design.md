# GitHub Webhook MCP Server — Design Document

**Date:** 2026-03-15
**Status:** Approved

## Purpose

A local service that receives GitHub webhook events via Smee.io and exposes
them to Claude Code as real-time MCP tools. Cross-cutting tool for all
projects — lives at `~/dev/github-webhook-mcp/`.

## Architecture

```
GitHub.com ──webhooks──▶ Smee.io channel (cloud proxy)
                              │ SSE stream
                              ▼
              ┌──────────────────────────────┐
              │  github-webhook-mcp          │
              │  (Python, port 8321)         │
              │                              │
              │  Smee SSE ──▶ SQLite ◀── MCP │
              └──────────────────────────────┘
                              ▲
          http://smee.local/sse
                              │
              ┌───────────────┴──────────────┐
              │  Caddy (port 80)             │
              │  signoz.local → :8080        │
              │  smee.local   → :8321        │
              └──────────────────────────────┘
                              ▲
              ┌───────────────┴──────────────┐
              │  Bonjour (mDNS)              │
              │  signoz.local → 127.0.0.1    │
              │  smee.local   → 127.0.0.1    │
              └──────────────────────────────┘
```

### Data Flow

1. GitHub fires webhook → Smee.io channel (cloud proxy, works behind NAT)
2. Smee SSE client (asyncio) receives event → verifies HMAC signature → stores in SQLite
3. Claude Code calls MCP tool → FastMCP queries SQLite → returns filtered results

### Process Model

Single Python process running as a LaunchAgent:
- **Smee SSE client**: asyncio background task connecting to Smee.io channel via `httpx-sse`
- **FastMCP server**: SSE transport on port 8321, serves MCP tools to Claude Code
- **SQLite (WAL mode)**: shared storage for concurrent read/write

### Routing Layer

Caddy reverse proxy on port 80 provides clean `.local` URLs:
- `http://signoz.local` → `localhost:8080` (existing SigNoz)
- `http://smee.local` → `localhost:8321` (this service)

Each `.local` domain gets a Bonjour (mDNS) registration via a LaunchAgent
running `dns-sd -P`, matching the existing `signoz-bonjour` pattern.

## MCP Tools

| Tool | Webhook Events Used | Returns |
|------|-------------------|---------|
| `get_pending_reviews(repo?)` | `pull_request` with `review_requested` action | PRs where `mikelane` is requested reviewer |
| `get_review_feedback(pr_number, repo)` | `pull_request_review`, `pull_request_review_comment` | Review comments on a specific PR |
| `get_ci_status(pr_number?, repo?)` | `check_suite`, `check_run`, `workflow_run` | Latest CI status, filtered to failures by default |
| `get_new_prs(repo?, since?)` | `pull_request` with `opened` action | PRs opened since last check |
| `get_notifications(since?)` | All events | Everything since timestamp, grouped by repo |

- `since` defaults to last 24 hours if omitted
- All tools return structured JSON with human-readable summaries
- `repo` accepts `owner/repo` format or just `repo` (matched against stored events)

## Storage Schema

```sql
CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivery_id   TEXT UNIQUE,          -- X-GitHub-Delivery header (dedup)
    repo          TEXT NOT NULL,         -- full_name: "owner/repo"
    event_type    TEXT NOT NULL,         -- X-GitHub-Event header
    action        TEXT,                  -- payload.action (opened, closed, etc.)
    sender        TEXT,                  -- payload.sender.login
    payload       TEXT NOT NULL          -- full JSON payload
);

CREATE INDEX idx_repo_type_time ON events (repo, event_type, received_at);
CREATE INDEX idx_received_at ON events (received_at);
```

- **WAL mode** for concurrent reads (MCP queries) + writes (Smee listener)
- **UNIQUE on delivery_id** prevents duplicates (Smee replays on reconnect)
- **Auto-prune**: `DELETE FROM events WHERE received_at < datetime('now', '-7 days')` on startup + every 6 hours

## Project Structure

```
~/dev/github-webhook-mcp/
├── pyproject.toml              # uv project, dependencies
├── README.md                   # Architecture diagram, setup instructions
├── setup.sh                    # One-shot setup script
├── Caddyfile                   # Local reverse proxy config
├── launchagents/
│   ├── com.mikelane.github-webhook-mcp.plist    # MCP server
│   └── com.local.smee-bonjour.plist             # Bonjour registration
├── docs/
│   └── plans/
│       └── 2026-03-15-github-webhook-mcp-design.md
├── src/
│   └── github_webhook_mcp/
│       ├── __init__.py
│       ├── __main__.py         # Entry point: start Smee listener + FastMCP
│       ├── server.py           # FastMCP tool definitions
│       ├── smee_client.py      # SSE listener → SQLite
│       ├── storage.py          # SQLite operations (aiosqlite)
│       ├── models.py           # Pydantic models for events
│       ├── config.py           # Settings from env vars
│       └── signature.py        # HMAC-SHA256 verification
└── tests/
    ├── test_storage.py
    ├── test_smee_client.py
    ├── test_signature.py
    └── test_server.py
```

## Configuration

```bash
# ~/.config/github-webhook-mcp/.env
SMEE_CHANNEL_URL=https://smee.io/<channel-id>
GITHUB_WEBHOOK_SECRET=<auto-generated-by-setup>
GITHUB_USERNAME=mikelane
MCP_PORT=8321
DB_PATH=~/.local/share/github-webhook-mcp/events.db
```

## Resilience

| Scenario | Handling |
|----------|----------|
| Smee connection drops | Auto-reconnect with exponential backoff (1s → 30s max) |
| Duplicate events (Smee replay) | `delivery_id` UNIQUE constraint silently ignores dupes |
| Process crash | LaunchAgent `KeepAlive` restarts; SQLite persists events |
| SQLite locked | WAL mode concurrent reads; writes retry with backoff |
| Invalid HMAC signature | Event logged as warning, not stored |

## Key Decisions

- **FastMCP only, no FastAPI**: FastMCP's SSE transport uses Starlette under the hood. The Smee listener is an asyncio background task sharing the same event loop. No need for an additional web framework.
- **Pure Python SSE client**: `httpx-sse` connects directly to Smee.io's SSE endpoint. No Node.js `smee-client` dependency.
- **Caddy over nginx**: Simpler config (6 lines vs verbose blocks), native SSE proxy support, easy to extend for future `.local` services.
- **SQLite over in-memory**: Survives restarts, supports concurrent access via WAL, auto-prunes after 7 days.
- **Separate Bonjour LaunchAgents**: Matches existing `signoz-bonjour` pattern. Each `.local` domain gets its own `dns-sd -P` registration.

## Dependencies

- `fastmcp` — MCP server framework (SSE transport)
- `httpx` + `httpx-sse` — Smee.io SSE client
- `aiosqlite` — async SQLite access
- `pydantic` — event models and settings
- `pydantic-settings` — env var configuration

## Deliverables

1. Working MCP server at `~/dev/github-webhook-mcp/`
2. Caddy config + setup (takes over port 80, routes `.local` domains)
3. Bonjour LaunchAgent for `smee.local`
4. MCP server LaunchAgent for auto-start
5. Setup script: creates Smee channel, configures GitHub webhooks, registers MCP in `~/.claude/settings.json`
6. README with architecture diagram
