# PR Reactor — Auto-Review Design

**Date:** 2026-03-16
**Status:** Approved

## Purpose

Automatically trigger `/review-pr` when PRs are opened or updated in
SayMoreAI/saymore. Debounce rapid pushes so only one review fires after
a 15-minute quiet period.

## Behavior

| Event | Action |
|-------|--------|
| PR opened (`pull_request.opened`) | Review immediately |
| Push to PR (`pull_request.synchronize`) | Start/reset 15-minute debounce timer |
| Debounce timer fires | Trigger review |

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────┐
│ Smee SSE    │────▶│ SmeeClient  │────▶│ SQLite  │
└─────────────┘     └──────┬──────┘     └─────────┘
                           │
                    notify(repo, pr, action)
                           │
                           ▼
                  ┌──────────────────┐
                  │  PR Reactor      │
                  │                  │
                  │  opened?         │──▶ spawn review now
                  │  synchronize?    │──▶ reset 15m timer
                  │                  │
                  │  timer fires ────│──▶ spawn review
                  └──────────────────┘
                           │
                           ▼
                  claude -p "/review-pr N"
                  --cwd ~/dev/saymore
```

Event-driven — no polling. SmeeClient calls `reactor.on_pr_event()` directly
after storing the event. Debounce uses `asyncio` timers (`call_later`), not
a polling loop.

## Components

### PRReactor (`src/github_webhook_mcp/reactor.py`)

- `on_pr_event(repo, pr_number, action)` — entry point called by SmeeClient
- Filters to `SayMoreAI/saymore` only
- `_timers: dict[str, asyncio.TimerHandle]` keyed by `"repo:pr_number"`
- On `opened`: cancel any existing timer, spawn review immediately
- On `synchronize`: cancel existing timer, set new `call_later(900, ...)`
- `_spawn_review(repo, pr_number)`: runs `claude -p "/review-pr <N>" --cwd <repo_path>`

### SmeeClient changes

- Accept optional `reactor: PRReactor` in constructor
- After storing a `pull_request` event, call `reactor.on_pr_event()`

### Entry point changes

- Create `PRReactor` instance
- Pass it to `SmeeClient`
- No new asyncio tasks needed (reactor is callback-driven)

## Config

- `AUTO_REVIEW_REPO = "SayMoreAI/saymore"` — hardcoded constant
- `REVIEW_DEBOUNCE_SECONDS = 900` — 15 minutes
- `SAYMORE_REPO_PATH = "~/dev/saymore"` — local checkout path (for --cwd)

## New files

- `src/github_webhook_mcp/reactor.py`
- `tests/test_reactor.py`

## Modified files

- `src/github_webhook_mcp/smee_client.py` — add reactor notification
- `src/github_webhook_mcp/__main__.py` — wire reactor into SmeeClient
