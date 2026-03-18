# GitHub Webhook MCP Server Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local MCP server that receives GitHub webhooks via Smee.io and exposes them as tools in Claude Code, with Caddy reverse proxy for clean `smee.local` URLs.

**Architecture:** Single Python process combining a Smee.io SSE listener (`httpx-sse`) with a FastMCP SSE server (port 8321). Events stored in SQLite (WAL mode, 7-day retention). Caddy on port 80 routes `smee.local` and `signoz.local` to their respective backends. Bonjour mDNS provides `.local` hostname resolution.

**Tech Stack:** Python 3.12+, uv, FastMCP, httpx/httpx-sse, aiosqlite, Pydantic, Caddy, macOS LaunchAgents

**Design Document:** `docs/plans/2026-03-15-github-webhook-mcp-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, build config |
| `src/github_webhook_mcp/__init__.py` | Package marker, version |
| `src/github_webhook_mcp/config.py` | Settings from env vars via pydantic-settings |
| `src/github_webhook_mcp/models.py` | Pydantic models for webhook events |
| `src/github_webhook_mcp/signature.py` | HMAC-SHA256 webhook signature verification |
| `src/github_webhook_mcp/storage.py` | SQLite event store (CRUD, pruning, filtered queries) |
| `src/github_webhook_mcp/smee_client.py` | SSE client connecting to Smee.io, parses events, stores them |
| `src/github_webhook_mcp/server.py` | FastMCP server with 5 MCP tools |
| `src/github_webhook_mcp/__main__.py` | Entry point: starts Smee listener + MCP server in one event loop |
| `tests/conftest.py` | Shared fixtures (temp DB, sample events, test settings) |
| `tests/test_signature.py` | Signature verification tests (small — no I/O) |
| `tests/test_storage.py` | SQLite storage tests (medium — disk I/O) |
| `tests/test_smee_client.py` | Smee client tests (small — mocked HTTP) |
| `tests/test_server.py` | MCP tool logic tests (medium — SQLite I/O) |
| `Caddyfile` | Reverse proxy: `signoz.local` → `:8080`, `smee.local` → `:8321` |
| `launchagents/com.mikelane.github-webhook-mcp.plist` | MCP server LaunchAgent |
| `launchagents/com.local.smee-bonjour.plist` | Bonjour mDNS registration for `smee.local` |
| `setup.sh` | One-shot setup: Smee channel, GitHub webhooks, MCP registration, LaunchAgents |
| `README.md` | Architecture diagram, prerequisites, setup, usage |

---

## Chunk 1: Project Setup + Config + Models + Signature

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/github_webhook_mcp/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "github-webhook-mcp"
version = "0.1.0"
description = "MCP server exposing GitHub webhook events received via Smee.io"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=2.0.0",
    "httpx>=0.28.0",
    "httpx-sse>=0.4.0",
    "aiosqlite>=0.21.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
]

[project.scripts]
github-webhook-mcp = "github_webhook_mcp.__main__:main"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.25.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/github_webhook_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create `src/github_webhook_mcp/__init__.py`**

```python
"""GitHub Webhook MCP Server — receives webhooks via Smee.io, serves via MCP."""
```

- [ ] **Step 3: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 4: Install dependencies**

Run: `cd ~/dev/github-webhook-mcp && uv sync --all-groups`
Expected: dependencies install successfully, `.venv/` created.

- [ ] **Step 5: Verify pytest runs**

Run: `uv run pytest --co`
Expected: "no tests ran" (no test files yet), exit 0.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/github_webhook_mcp/__init__.py tests/__init__.py
git commit -m "chore: scaffold project with uv and dependencies

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Config Module

**Files:**
- Create: `src/github_webhook_mcp/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test for Settings defaults**

```python
# tests/test_config.py
import os
import pytest
from github_webhook_mcp.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SMEE_CHANNEL_URL", "https://smee.io/test123")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "testsecret")

    settings = Settings()

    assert settings.smee_channel_url == "https://smee.io/test123"
    assert settings.github_webhook_secret == "testsecret"
    assert settings.github_username == "mikelane"
    assert settings.mcp_port == 8321
    assert settings.prune_days == 7


def test_settings_requires_smee_url(monkeypatch):
    monkeypatch.delenv("SMEE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    with pytest.raises(Exception):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'github_webhook_mcp.config'`

- [ ] **Step 3: Write implementation**

```python
# src/github_webhook_mcp/config.py
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    smee_channel_url: str
    github_webhook_secret: str
    github_username: str = "mikelane"
    mcp_port: int = 8321
    db_path: str = "~/.local/share/github-webhook-mcp/events.db"
    prune_days: int = 7

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/github_webhook_mcp/config.py tests/test_config.py
git commit -m "feat: add config module with pydantic-settings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Models

**Files:**
- Create: `src/github_webhook_mcp/models.py`

- [ ] **Step 1: Create models (declarative, no TDD needed for pure data classes)**

```python
# src/github_webhook_mcp/models.py
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WebhookEvent(BaseModel):
    id: int | None = None
    received_at: datetime
    delivery_id: str
    repo: str
    event_type: str
    action: str | None = None
    sender: str | None = None
    payload: dict


class SmeeEvent(BaseModel):
    """Raw event as received from the Smee.io SSE stream.

    Smee wraps the original GitHub webhook payload with its own envelope
    that includes the original HTTP headers GitHub sent.
    """

    body: dict
    x_github_event: str | None = None
    x_github_delivery: str | None = None
    x_hub_signature_256: str | None = None

    @property
    def repo_full_name(self) -> str | None:
        repo = self.body.get("repository")
        if repo:
            return repo.get("full_name")
        return None

    @property
    def action(self) -> str | None:
        return self.body.get("action")

    @property
    def sender_login(self) -> str | None:
        sender = self.body.get("sender")
        if sender:
            return sender.get("login")
        return None
```

- [ ] **Step 2: Commit**

```bash
git add src/github_webhook_mcp/models.py
git commit -m "feat: add Pydantic models for webhook and Smee events

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Signature Verification

**Files:**
- Create: `src/github_webhook_mcp/signature.py`
- Create: `tests/test_signature.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_signature.py
import hashlib
import hmac

from github_webhook_mcp.signature import verify_signature

SECRET = "test-webhook-secret"


def _sign(payload: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def test_valid_signature_returns_true():
    payload = b'{"action": "opened"}'
    sig = _sign(payload, SECRET)

    assert verify_signature(payload, sig, SECRET) is True


def test_invalid_signature_returns_false():
    payload = b'{"action": "opened"}'
    sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

    assert verify_signature(payload, sig, SECRET) is False


def test_wrong_secret_returns_false():
    payload = b'{"action": "opened"}'
    sig = _sign(payload, "wrong-secret")

    assert verify_signature(payload, sig, SECRET) is False


def test_missing_prefix_returns_false():
    payload = b'{"action": "opened"}'
    mac = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()

    assert verify_signature(payload, mac, SECRET) is False


def test_empty_payload():
    payload = b""
    sig = _sign(payload, SECRET)

    assert verify_signature(payload, sig, SECRET) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signature.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/github_webhook_mcp/signature.py
import hashlib
import hmac


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_signature.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/github_webhook_mcp/signature.py tests/test_signature.py
git commit -m "feat: add HMAC-SHA256 webhook signature verification

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Chunk 2: Storage Layer

### Task 5: EventStore — Initialization and store_event

**Files:**
- Create: `src/github_webhook_mcp/storage.py`
- Create: `tests/conftest.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Create shared test fixtures**

```python
# tests/conftest.py
import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from github_webhook_mcp.models import WebhookEvent
from github_webhook_mcp.storage import EventStore


@pytest_asyncio.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test_events.db")
    s = EventStore(db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def sample_event() -> WebhookEvent:
    return WebhookEvent(
        received_at=datetime.now(timezone.utc),
        delivery_id="delivery-001",
        repo="mikelane/test-repo",
        event_type="pull_request",
        action="opened",
        sender="octocat",
        payload={
            "action": "opened",
            "number": 42,
            "pull_request": {
                "title": "Add feature",
                "html_url": "https://github.com/mikelane/test-repo/pull/42",
                "user": {"login": "octocat"},
            },
            "repository": {"full_name": "mikelane/test-repo"},
            "sender": {"login": "octocat"},
        },
    )
```

- [ ] **Step 2: Write failing tests for init and store**

```python
# tests/test_storage.py
# //go:build medium — SQLite I/O
import pytest
from datetime import datetime, timezone

from github_webhook_mcp.models import WebhookEvent


@pytest.mark.asyncio
async def test_store_initializes_database(store):
    # If we get here without error, init worked
    rows = await store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] async for r in rows]
    assert "events" in tables


@pytest.mark.asyncio
async def test_store_event_and_retrieve(store, sample_event):
    stored = await store.store_event(sample_event)
    assert stored is True

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].delivery_id == "delivery-001"
    assert events[0].repo == "mikelane/test-repo"


@pytest.mark.asyncio
async def test_duplicate_delivery_id_is_ignored(store, sample_event):
    await store.store_event(sample_event)
    stored_again = await store.store_event(sample_event)

    assert stored_again is False
    events = await store.get_events()
    assert len(events) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'github_webhook_mcp.storage'`

- [ ] **Step 4: Write implementation**

```python
# src/github_webhook_mcp/storage.py
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .models import WebhookEvent

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TEXT NOT NULL,
    delivery_id   TEXT UNIQUE,
    repo          TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    action        TEXT,
    sender        TEXT,
    payload       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_repo_type_time
    ON events (repo, event_type, received_at);

CREATE INDEX IF NOT EXISTS idx_received_at
    ON events (received_at);
"""


class EventStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(_SCHEMA)
        await self.db.commit()

    async def store_event(self, event: WebhookEvent) -> bool:
        try:
            await self.db.execute(
                """INSERT INTO events
                   (received_at, delivery_id, repo, event_type, action, sender, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.received_at.isoformat(),
                    event.delivery_id,
                    event.repo,
                    event.event_type,
                    event.action,
                    event.sender,
                    json.dumps(event.payload),
                ),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            logger.debug("Duplicate event ignored: %s", event.delivery_id)
            return False

    async def get_events(
        self,
        repo: str | None = None,
        event_type: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        sender: str | None = None,
    ) -> list[WebhookEvent]:
        clauses: list[str] = []
        params: list[str] = []

        if repo:
            clauses.append("repo LIKE ?")
            params.append(f"%{repo}%")
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if since:
            clauses.append("received_at >= ?")
            params.append(since.isoformat())
        if sender:
            clauses.append("sender = ?")
            params.append(sender)

        where = " AND ".join(clauses) if clauses else "1=1"
        query = f"SELECT * FROM events WHERE {where} ORDER BY received_at DESC"

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()

        return [
            WebhookEvent(
                id=row["id"],
                received_at=datetime.fromisoformat(row["received_at"]),
                delivery_id=row["delivery_id"],
                repo=row["repo"],
                event_type=row["event_type"],
                action=row["action"],
                sender=row["sender"],
                payload=json.loads(row["payload"]),
            )
            for row in rows
        ]

    async def prune(self, days: int = 7) -> int:
        cursor = await self.db.execute(
            "DELETE FROM events WHERE received_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        await self.db.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Pruned %d events older than %d days", deleted, days)
        return deleted

    async def close(self) -> None:
        if self.db:
            await self.db.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/github_webhook_mcp/storage.py tests/conftest.py tests/test_storage.py
git commit -m "feat: add SQLite event store with dedup and WAL mode

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: EventStore — Filtered Queries

**Files:**
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for query filters**

Append to `tests/test_storage.py`:

```python
@pytest.mark.asyncio
async def test_query_by_repo_filter(store, sample_event):
    await store.store_event(sample_event)

    other = sample_event.model_copy(
        update={"delivery_id": "delivery-002", "repo": "other-org/other-repo"}
    )
    await store.store_event(other)

    results = await store.get_events(repo="test-repo")
    assert len(results) == 1
    assert results[0].repo == "mikelane/test-repo"


@pytest.mark.asyncio
async def test_query_by_event_type(store, sample_event):
    await store.store_event(sample_event)

    issue_event = sample_event.model_copy(
        update={"delivery_id": "delivery-003", "event_type": "issues"}
    )
    await store.store_event(issue_event)

    results = await store.get_events(event_type="pull_request")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_query_by_since(store, sample_event):
    from datetime import timedelta

    old_event = sample_event.model_copy(
        update={
            "delivery_id": "delivery-old",
            "received_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        }
    )
    await store.store_event(old_event)
    await store.store_event(sample_event)

    results = await store.get_events(since=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert len(results) == 1
    assert results[0].delivery_id == "delivery-001"
```

- [ ] **Step 2: Run tests — they should pass (queries already implemented)**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 6 passed. If any fail, fix `get_events` accordingly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_storage.py
git commit -m "test: add filtered query tests for EventStore

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: EventStore — Pruning

**Files:**
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write failing test for pruning**

Append to `tests/test_storage.py`:

```python
@pytest.mark.asyncio
async def test_prune_removes_old_events(store, sample_event):
    old_event = sample_event.model_copy(
        update={
            "delivery_id": "delivery-ancient",
            "received_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        }
    )
    await store.store_event(old_event)
    await store.store_event(sample_event)

    deleted = await store.prune(days=7)

    assert deleted == 1
    remaining = await store.get_events()
    assert len(remaining) == 1
    assert remaining[0].delivery_id == "delivery-001"


@pytest.mark.asyncio
async def test_prune_preserves_recent_events(store, sample_event):
    await store.store_event(sample_event)

    deleted = await store.prune(days=7)

    assert deleted == 0
    remaining = await store.get_events()
    assert len(remaining) == 1
```

- [ ] **Step 2: Run tests — should pass (prune already implemented)**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 8 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_storage.py
git commit -m "test: add pruning tests for EventStore

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Chunk 3: Smee SSE Client

### Task 8: Smee Client — Event Parsing and Storage

**Files:**
- Create: `src/github_webhook_mcp/smee_client.py`
- Create: `tests/test_smee_client.py`

The Smee client connects to a Smee.io channel URL via SSE. Each SSE event's
`data` field contains a JSON object with the original GitHub webhook payload
in the `body` key and the original headers as top-level keys (lowercased,
hyphens replaced with underscores, prefixed with `x-`... actually Smee
provides them as top-level keys like `x-github-event`).

We test the event-handling logic by calling `_handle_raw_event` directly
with mock SSE data, avoiding actual HTTP connections.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_smee_client.py
import json
import hashlib
import hmac
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from github_webhook_mcp.smee_client import SmeeClient
from github_webhook_mcp.storage import EventStore

SECRET = "test-secret"


def _make_smee_data(body: dict, event: str = "pull_request", delivery: str = "d-001") -> dict:
    """Build a Smee SSE event data dict matching Smee.io's format."""
    payload_bytes = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return {
        "body": body,
        "x-github-event": event,
        "x-github-delivery": delivery,
        "x-hub-signature-256": sig,
    }


@pytest_asyncio.fixture
async def store(tmp_path):
    s = EventStore(str(tmp_path / "test.db"))
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def client(store):
    return SmeeClient(
        channel_url="https://smee.io/test",
        webhook_secret=SECRET,
        store=store,
    )


@pytest.mark.asyncio
async def test_handle_valid_event_stores_it(client, store):
    body = {
        "action": "opened",
        "number": 1,
        "repository": {"full_name": "mikelane/repo"},
        "sender": {"login": "octocat"},
    }
    data = _make_smee_data(body)

    await client.handle_raw_event(json.dumps(data))

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].repo == "mikelane/repo"
    assert events[0].event_type == "pull_request"


@pytest.mark.asyncio
async def test_handle_event_with_bad_signature_rejects(client, store):
    data = {
        "body": {"action": "opened", "repository": {"full_name": "x/y"}, "sender": {"login": "x"}},
        "x-github-event": "push",
        "x-github-delivery": "d-bad",
        "x-hub-signature-256": "sha256=bogus",
    }

    await client.handle_raw_event(json.dumps(data))

    events = await store.get_events()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_handle_event_missing_repo_skips(client, store):
    body = {"action": "completed"}  # no "repository" key
    data = _make_smee_data(body, event="check_run", delivery="d-norepo")

    await client.handle_raw_event(json.dumps(data))

    events = await store.get_events()
    assert len(events) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smee_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/github_webhook_mcp/smee_client.py
from __future__ import annotations

import asyncio
import json
import logging

import httpx
from httpx_sse import aconnect_sse

from .models import SmeeEvent
from .signature import verify_signature
from .storage import EventStore

logger = logging.getLogger(__name__)


class SmeeClient:
    def __init__(
        self,
        channel_url: str,
        webhook_secret: str,
        store: EventStore,
    ) -> None:
        self.channel_url = channel_url
        self.webhook_secret = webhook_secret
        self.store = store
        self._backoff = 1.0
        self._max_backoff = 30.0

    async def handle_raw_event(self, raw_data: str) -> None:
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON SSE data, skipping")
            return

        # Smee "ready" events have no body
        if "body" not in data:
            return

        event = SmeeEvent(
            body=data["body"],
            x_github_event=data.get("x-github-event"),
            x_github_delivery=data.get("x-github-delivery"),
            x_hub_signature_256=data.get("x-hub-signature-256"),
        )

        if not event.repo_full_name:
            logger.debug("Event has no repository, skipping: %s", event.x_github_delivery)
            return

        # Verify signature
        payload_bytes = json.dumps(event.body).encode()
        if event.x_hub_signature_256 and not verify_signature(
            payload_bytes, event.x_hub_signature_256, self.webhook_secret
        ):
            logger.warning("Invalid signature for delivery %s", event.x_github_delivery)
            return

        from datetime import datetime, timezone

        webhook_event = __import__("github_webhook_mcp.models", fromlist=["WebhookEvent"]).WebhookEvent(
            received_at=datetime.now(timezone.utc),
            delivery_id=event.x_github_delivery or "",
            repo=event.repo_full_name,
            event_type=event.x_github_event or "unknown",
            action=event.action,
            sender=event.sender_login,
            payload=event.body,
        )

        await self.store.store_event(webhook_event)
        self._backoff = 1.0  # reset on successful processing

    async def listen(self) -> None:
        while True:
            try:
                logger.info("Connecting to Smee channel: %s", self.channel_url)
                async with httpx.AsyncClient(timeout=None) as client:
                    async with aconnect_sse(client, "GET", self.channel_url) as source:
                        self._backoff = 1.0
                        async for sse_event in source.aiter_sse():
                            if sse_event.data:
                                await self.handle_raw_event(sse_event.data)
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                logger.warning("Smee connection lost (%s), reconnecting in %.0fs", exc, self._backoff)
            except Exception:
                logger.exception("Unexpected error in Smee listener, reconnecting in %.0fs", self._backoff)

            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)
```

**Important:** The `__import__` trick above is ugly. Refactor to a clean import:

```python
# Replace the __import__ line with:
from .models import WebhookEvent

# And use directly:
webhook_event = WebhookEvent(...)
```

(The `WebhookEvent` import should be at the top of the file alongside the other imports.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smee_client.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/github_webhook_mcp/smee_client.py tests/test_smee_client.py
git commit -m "feat: add Smee SSE client with signature verification and reconnection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Chunk 4: MCP Server + Entry Point

### Task 9: FastMCP Server — Tool Definitions

**Files:**
- Create: `src/github_webhook_mcp/server.py`
- Create: `tests/test_server.py`

The server module defines a FastMCP instance with 5 tools. Each tool queries
the EventStore. The store is injected via a module-level `init_server(store)`
call before the server starts.

- [ ] **Step 1: Write failing tests for `get_pending_reviews`**

```python
# tests/test_server.py
# //go:build medium — uses SQLite
import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from github_webhook_mcp.models import WebhookEvent
from github_webhook_mcp.storage import EventStore
from github_webhook_mcp.server import (
    get_pending_reviews,
    get_review_feedback,
    get_ci_status,
    get_new_prs,
    get_notifications,
    init_server,
)


@pytest_asyncio.fixture
async def store(tmp_path):
    s = EventStore(str(tmp_path / "test.db"))
    await s.initialize()
    init_server(s)
    yield s
    await s.close()


def _event(
    delivery_id: str,
    event_type: str,
    action: str,
    repo: str = "mikelane/test-repo",
    sender: str = "octocat",
    payload_extra: dict | None = None,
) -> WebhookEvent:
    payload = {
        "action": action,
        "repository": {"full_name": repo},
        "sender": {"login": sender},
    }
    if payload_extra:
        payload.update(payload_extra)
    return WebhookEvent(
        received_at=datetime.now(timezone.utc),
        delivery_id=delivery_id,
        repo=repo,
        event_type=event_type,
        action=action,
        sender=sender,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_get_pending_reviews_returns_review_requests(store):
    await store.store_event(
        _event(
            "d-1",
            "pull_request",
            "review_requested",
            payload_extra={
                "requested_reviewer": {"login": "mikelane"},
                "pull_request": {
                    "number": 42,
                    "title": "Add feature",
                    "html_url": "https://github.com/mikelane/test-repo/pull/42",
                    "user": {"login": "octocat"},
                },
            },
        )
    )

    result = await get_pending_reviews()
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["number"] == 42


@pytest.mark.asyncio
async def test_get_pending_reviews_filters_by_repo(store):
    for i, repo in enumerate(["mikelane/repo-a", "mikelane/repo-b"]):
        await store.store_event(
            _event(
                f"d-{i}",
                "pull_request",
                "review_requested",
                repo=repo,
                payload_extra={
                    "requested_reviewer": {"login": "mikelane"},
                    "pull_request": {
                        "number": i,
                        "title": f"PR {i}",
                        "html_url": f"https://github.com/{repo}/pull/{i}",
                        "user": {"login": "octocat"},
                    },
                },
            )
        )

    result = await get_pending_reviews(repo="repo-a")
    parsed = json.loads(result)
    assert len(parsed) == 1


@pytest.mark.asyncio
async def test_get_ci_status_returns_failures(store):
    await store.store_event(
        _event(
            "d-ci-1",
            "check_run",
            "completed",
            payload_extra={
                "check_run": {
                    "name": "tests",
                    "conclusion": "failure",
                    "html_url": "https://github.com/mikelane/test-repo/runs/1",
                    "pull_requests": [{"number": 10}],
                },
            },
        )
    )

    result = await get_ci_status()
    parsed = json.loads(result)
    assert len(parsed) >= 1
    assert parsed[0]["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_get_new_prs(store):
    await store.store_event(
        _event(
            "d-pr-1",
            "pull_request",
            "opened",
            payload_extra={
                "pull_request": {
                    "number": 99,
                    "title": "New PR",
                    "html_url": "https://github.com/mikelane/test-repo/pull/99",
                    "user": {"login": "contributor"},
                },
            },
        )
    )

    result = await get_new_prs()
    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["number"] == 99


@pytest.mark.asyncio
async def test_get_notifications_returns_all(store):
    await store.store_event(_event("d-n1", "push", "push"))
    await store.store_event(_event("d-n2", "issues", "opened"))

    result = await get_notifications()
    parsed = json.loads(result)
    assert len(parsed) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/github_webhook_mcp/server.py
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP

from .storage import EventStore

mcp = FastMCP("github-webhooks")

_store: EventStore | None = None
_username: str = "mikelane"


def init_server(store: EventStore, username: str = "mikelane") -> None:
    global _store, _username
    _store = store
    _username = username


def _default_since() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=24)


@mcp.tool()
async def get_pending_reviews(repo: str | None = None) -> str:
    """Get pull requests awaiting my review.

    Args:
        repo: Filter by repository name (partial match). Omit for all repos.
    """
    events = await _store.get_events(
        repo=repo,
        event_type="pull_request",
        action="review_requested",
    )

    results = []
    for e in events:
        reviewer = e.payload.get("requested_reviewer", {})
        if reviewer.get("login") != _username:
            continue
        pr = e.payload.get("pull_request", {})
        results.append({
            "repo": e.repo,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("html_url"),
            "author": pr.get("user", {}).get("login"),
            "requested_at": e.received_at.isoformat(),
        })

    return json.dumps(results, indent=2)


@mcp.tool()
async def get_review_feedback(pr_number: int, repo: str) -> str:
    """Get review comments on a specific pull request.

    Args:
        pr_number: The PR number to check.
        repo: Repository name (partial match, e.g. 'my-repo' or 'owner/repo').
    """
    reviews = await _store.get_events(
        repo=repo,
        event_type="pull_request_review",
    )
    comments = await _store.get_events(
        repo=repo,
        event_type="pull_request_review_comment",
    )

    results = []
    for e in reviews + comments:
        pr = e.payload.get("pull_request", {})
        if pr.get("number") != pr_number:
            continue
        review = e.payload.get("review", {})
        comment = e.payload.get("comment", {})
        results.append({
            "repo": e.repo,
            "pr_number": pr_number,
            "author": (review or comment).get("user", {}).get("login"),
            "state": review.get("state"),
            "body": (review or comment).get("body", ""),
            "submitted_at": e.received_at.isoformat(),
        })

    return json.dumps(results, indent=2)


@mcp.tool()
async def get_ci_status(pr_number: int | None = None, repo: str | None = None) -> str:
    """Get CI/CD status, filtered to failures by default.

    Args:
        pr_number: Filter to a specific PR number. Omit for all.
        repo: Filter by repository name (partial match). Omit for all repos.
    """
    results = []

    for event_type in ("check_run", "check_suite", "workflow_run"):
        events = await _store.get_events(repo=repo, event_type=event_type)
        for e in events:
            run = e.payload.get("check_run") or e.payload.get("check_suite") or e.payload.get("workflow_run", {})
            conclusion = run.get("conclusion")
            if conclusion not in ("failure", "timed_out", "cancelled"):
                continue

            if pr_number:
                prs = run.get("pull_requests", [])
                if not any(p.get("number") == pr_number for p in prs):
                    continue

            results.append({
                "repo": e.repo,
                "name": run.get("name"),
                "conclusion": conclusion,
                "url": run.get("html_url"),
                "pr_numbers": [p.get("number") for p in run.get("pull_requests", [])],
                "completed_at": e.received_at.isoformat(),
            })

    return json.dumps(results, indent=2)


@mcp.tool()
async def get_new_prs(repo: str | None = None, since: str | None = None) -> str:
    """Get recently opened pull requests.

    Args:
        repo: Filter by repository name (partial match). Omit for all repos.
        since: ISO 8601 timestamp. Defaults to last 24 hours.
    """
    since_dt = datetime.fromisoformat(since) if since else _default_since()

    events = await _store.get_events(
        repo=repo,
        event_type="pull_request",
        action="opened",
        since=since_dt,
    )

    results = []
    for e in events:
        pr = e.payload.get("pull_request", {})
        results.append({
            "repo": e.repo,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("html_url"),
            "author": pr.get("user", {}).get("login"),
            "opened_at": e.received_at.isoformat(),
        })

    return json.dumps(results, indent=2)


@mcp.tool()
async def get_notifications(since: str | None = None) -> str:
    """Get all webhook events since a given time, grouped by repo.

    Args:
        since: ISO 8601 timestamp. Defaults to last 24 hours.
    """
    since_dt = datetime.fromisoformat(since) if since else _default_since()
    events = await _store.get_events(since=since_dt)

    results = []
    for e in events:
        results.append({
            "repo": e.repo,
            "event_type": e.event_type,
            "action": e.action,
            "sender": e.sender,
            "received_at": e.received_at.isoformat(),
            "summary": f"{e.sender} {e.action or ''} {e.event_type} on {e.repo}".strip(),
        })

    return json.dumps(results, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/github_webhook_mcp/server.py tests/test_server.py
git commit -m "feat: add FastMCP server with 5 webhook query tools

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Entry Point

**Files:**
- Create: `src/github_webhook_mcp/__main__.py`

No TDD for the entry point — it wires components together and starts the
event loop. Tested by running the service manually (Task 14).

- [ ] **Step 1: Write entry point**

```python
# src/github_webhook_mcp/__main__.py
from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .server import init_server, mcp
from .smee_client import SmeeClient
from .storage import EventStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _prune_loop(store: EventStore, days: int) -> None:
    while True:
        await store.prune(days)
        await asyncio.sleep(6 * 3600)  # every 6 hours


async def _run() -> None:
    settings = Settings()
    store = EventStore(settings.db_path)
    await store.initialize()
    await store.prune(settings.prune_days)

    init_server(store, settings.github_username)

    smee = SmeeClient(
        channel_url=settings.smee_channel_url,
        webhook_secret=settings.github_webhook_secret,
        store=store,
    )

    logger.info("Starting Smee listener for %s", settings.smee_channel_url)
    asyncio.create_task(smee.listen())
    asyncio.create_task(_prune_loop(store, settings.prune_days))

    logger.info("Starting MCP server on port %d", settings.mcp_port)
    await mcp.run_async(transport="sse", port=settings.mcp_port)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it at least imports cleanly**

Run: `uv run python -c "from github_webhook_mcp.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/github_webhook_mcp/__main__.py
git commit -m "feat: add entry point wiring Smee listener + MCP server

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Chunk 5: Infrastructure

### Task 11: Caddyfile

**Files:**
- Create: `Caddyfile`

- [ ] **Step 1: Create Caddyfile**

```caddyfile
http://signoz.local {
	reverse_proxy localhost:8080
}

http://smee.local {
	reverse_proxy localhost:8321
}
```

- [ ] **Step 2: Validate syntax**

Run: `caddy validate --config ~/dev/github-webhook-mcp/Caddyfile`
Expected: `Valid configuration`

- [ ] **Step 3: Commit**

```bash
git add Caddyfile
git commit -m "feat: add Caddy reverse proxy config for .local domains

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: LaunchAgents

**Files:**
- Create: `launchagents/com.local.smee-bonjour.plist`
- Create: `launchagents/com.mikelane.github-webhook-mcp.plist`

- [ ] **Step 1: Create Bonjour LaunchAgent**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.smee-bonjour</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/dns-sd</string>
        <string>-P</string>
        <string>smee</string>
        <string>_http._tcp</string>
        <string>local</string>
        <string>80</string>
        <string>smee.local</string>
        <string>127.0.0.1</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/smee-bonjour.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/smee-bonjour.err</string>
</dict>
</plist>
```

- [ ] **Step 2: Create MCP server LaunchAgent**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mikelane.github-webhook-mcp</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/mikelane/dev/github-webhook-mcp/.venv/bin/python</string>
        <string>-m</string>
        <string>github_webhook_mcp</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/mikelane/dev/github-webhook-mcp</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/mikelane/Library/Logs/github-webhook-mcp/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/mikelane/Library/Logs/github-webhook-mcp/stderr.log</string>
</dict>
</plist>
```

Note: The plist references `~/.config/github-webhook-mcp/.env` indirectly
through pydantic-settings. The `EnvironmentVariables` dict in the plist can
also be used if `.env` loading proves unreliable under launchd. The setup
script will handle this.

- [ ] **Step 3: Validate plist syntax**

Run: `plutil -lint launchagents/*.plist`
Expected: both `OK`

- [ ] **Step 4: Commit**

```bash
git add launchagents/
git commit -m "feat: add LaunchAgent plists for Bonjour and MCP server

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: Setup Script

**Files:**
- Create: `setup.sh`

The setup script is idempotent — safe to re-run. It:
1. Creates a Smee.io channel (or accepts existing URL)
2. Generates a webhook secret
3. Configures GitHub webhooks on specified repos
4. Writes the `.env` file
5. Sets up Caddy
6. Installs LaunchAgents
7. Registers the MCP server in Claude Code settings

- [ ] **Step 1: Write setup script**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_DIR="$HOME/.config/github-webhook-mcp"
ENV_FILE="$ENV_DIR/.env"
LOG_DIR="$HOME/Library/Logs/github-webhook-mcp"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "=== GitHub Webhook MCP Server Setup ==="

# --- Step 1: Smee channel ---
if [[ -f "$ENV_FILE" ]] && grep -q SMEE_CHANNEL_URL "$ENV_FILE"; then
    SMEE_URL=$(grep SMEE_CHANNEL_URL "$ENV_FILE" | cut -d= -f2)
    echo "Using existing Smee channel: $SMEE_URL"
else
    echo "Creating new Smee.io channel..."
    SMEE_URL=$(curl -sL https://smee.io/new -o /dev/null -w '%{url_effective}')
    echo "Created: $SMEE_URL"
fi

# --- Step 2: Webhook secret ---
if [[ -f "$ENV_FILE" ]] && grep -q GITHUB_WEBHOOK_SECRET "$ENV_FILE"; then
    WEBHOOK_SECRET=$(grep GITHUB_WEBHOOK_SECRET "$ENV_FILE" | cut -d= -f2)
    echo "Using existing webhook secret"
else
    WEBHOOK_SECRET=$(openssl rand -hex 32)
    echo "Generated webhook secret"
fi

# --- Step 3: Write .env ---
mkdir -p "$ENV_DIR"
cat > "$ENV_FILE" <<EOF
SMEE_CHANNEL_URL=$SMEE_URL
GITHUB_WEBHOOK_SECRET=$WEBHOOK_SECRET
GITHUB_USERNAME=mikelane
MCP_PORT=8321
DB_PATH=$HOME/.local/share/github-webhook-mcp/events.db
EOF
chmod 600 "$ENV_FILE"
echo "Wrote $ENV_FILE"

# --- Step 4: Configure GitHub webhooks ---
echo ""
echo "Which repos should receive webhooks? (space-separated, e.g. 'owner/repo1 owner/repo2')"
echo "Leave empty to skip webhook configuration."
read -r REPOS

for REPO in $REPOS; do
    echo "Configuring webhook for $REPO..."
    gh api "repos/$REPO/hooks" \
        -f "config[url]=$SMEE_URL" \
        -f "config[content_type]=json" \
        -f "config[secret]=$WEBHOOK_SECRET" \
        -F "active=true" \
        -f "events[]=pull_request" \
        -f "events[]=pull_request_review" \
        -f "events[]=pull_request_review_comment" \
        -f "events[]=check_run" \
        -f "events[]=check_suite" \
        -f "events[]=workflow_run" \
        -f "events[]=push" \
        -f "events[]=issues" \
        --silent && echo "  ✓ $REPO" || echo "  ✗ $REPO (may already exist)"
done

# --- Step 5: Install Python deps ---
echo ""
echo "Installing Python dependencies..."
cd "$SCRIPT_DIR"
uv sync --all-groups

# --- Step 6: Set up Caddy ---
echo ""
echo "Setting up Caddy..."
CADDY_CONFIG="/opt/homebrew/etc/Caddyfile"
if [[ -f "$CADDY_CONFIG" ]] && ! diff -q "$SCRIPT_DIR/Caddyfile" "$CADDY_CONFIG" > /dev/null 2>&1; then
    echo "WARNING: Existing Caddyfile differs. Backing up to ${CADDY_CONFIG}.bak"
    cp "$CADDY_CONFIG" "${CADDY_CONFIG}.bak"
fi
cp "$SCRIPT_DIR/Caddyfile" "$CADDY_CONFIG"
brew services start caddy 2>/dev/null || brew services restart caddy
echo "Caddy started"

# --- Step 7: Install LaunchAgents ---
echo ""
mkdir -p "$LOG_DIR"

# Bonjour registration
cp "$SCRIPT_DIR/launchagents/com.local.smee-bonjour.plist" "$LAUNCH_AGENTS/"
launchctl bootout "gui/$(id -u)/com.local.smee-bonjour" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/com.local.smee-bonjour.plist"
echo "Bonjour registration installed (smee.local)"

# MCP server
cp "$SCRIPT_DIR/launchagents/com.mikelane.github-webhook-mcp.plist" "$LAUNCH_AGENTS/"
launchctl bootout "gui/$(id -u)/com.mikelane.github-webhook-mcp" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/com.mikelane.github-webhook-mcp.plist"
echo "MCP server LaunchAgent installed"

# --- Step 8: Register in Claude Code settings ---
echo ""
echo "Registering MCP server in Claude Code settings..."
if command -v jq > /dev/null; then
    TEMP=$(mktemp)
    jq '.mcpServers["github-webhooks"] = {"url": "http://smee.local/sse"}' \
        "$SETTINGS_FILE" > "$TEMP" && mv "$TEMP" "$SETTINGS_FILE"
    echo "Registered github-webhooks in $SETTINGS_FILE"
else
    echo "jq not found. Manually add to $SETTINGS_FILE:"
    echo '  "mcpServers": { "github-webhooks": { "url": "http://smee.local/sse" } }'
fi

echo ""
echo "=== Setup complete ==="
echo "Smee channel: $SMEE_URL"
echo "MCP URL:      http://smee.local/sse"
echo "Logs:         $LOG_DIR/"
echo "Config:       $ENV_FILE"
```

- [ ] **Step 2: Make executable**

Run: `chmod +x setup.sh`

- [ ] **Step 3: Commit**

```bash
git add setup.sh
git commit -m "feat: add setup script for Smee, webhooks, Caddy, and LaunchAgents

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README with architecture, prerequisites, setup, and usage**

Content should include:
- Architecture diagram (copy from design doc)
- Prerequisites: Python 3.12+, uv, Caddy, gh CLI, jq
- Quick start: `./setup.sh`
- MCP tools reference table
- Configuration reference (env vars)
- Troubleshooting (logs location, checking Smee channel, verifying Bonjour)
- Adding new repos (re-run setup or manual `gh api` command)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with architecture and setup instructions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 15: End-to-End Smoke Test

No automated test — manual verification that all components work together.

- [ ] **Step 1: Run `./setup.sh` (skip webhook config for now)**

- [ ] **Step 2: Verify Bonjour resolves**

Run: `dscacheutil -q host -a name smee.local`
Expected: `ip_address: 127.0.0.1`

- [ ] **Step 3: Verify Caddy routes**

Run: `curl -sI http://smee.local/`
Expected: HTTP response from the MCP server (may be 404 since `/` isn't an MCP endpoint, but confirms routing works)

- [ ] **Step 4: Check MCP server logs**

Run: `tail -20 ~/Library/Logs/github-webhook-mcp/stderr.log`
Expected: "Starting MCP server on port 8321" and "Connecting to Smee channel"

- [ ] **Step 5: Verify MCP registration**

Run: `jq '.mcpServers["github-webhooks"]' ~/.claude/settings.json`
Expected: `{ "url": "http://smee.local/sse" }`

- [ ] **Step 6: Test from Claude Code**

Start a new Claude Code session and call `get_notifications()`. Should
return an empty list (no events yet) without errors.
