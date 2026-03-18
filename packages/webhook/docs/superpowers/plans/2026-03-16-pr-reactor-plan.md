# PR Reactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically trigger `/review-pr` on SayMore PRs — immediately on open, debounced (15m) on push.

**Architecture:** Event-driven reactor inside the existing MCP server process. SmeeClient notifies the reactor after storing PR events. Reactor manages per-PR `asyncio` debounce timers and spawns `claude` subprocesses to run reviews.

**Tech Stack:** Python asyncio (timers via `call_later`), `asyncio.create_subprocess_exec` for spawning claude

**Design Document:** `docs/plans/2026-03-16-pr-reactor-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/github_webhook_mcp/reactor.py` | Create | PR reactor: event handler, debounce timers, review spawning |
| `tests/test_reactor.py` | Create | Reactor tests: filtering, immediate vs debounced, timer reset |
| `src/github_webhook_mcp/smee_client.py` | Modify | Add optional reactor, call `on_pr_event()` after storing PR events |
| `src/github_webhook_mcp/__main__.py` | Modify | Wire reactor into SmeeClient |
| `tests/test_smee_client.py` | Modify | Add test for reactor notification |

---

## Chunk 1: Reactor Core

### Task 1: PRReactor — immediate review on PR opened

**Files:**
- Create: `src/github_webhook_mcp/reactor.py`
- Create: `tests/test_reactor.py`

- [ ] **Step 1: Write failing test for immediate review on `opened`**

```python
# tests/test_reactor.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from github_webhook_mcp.reactor import PRReactor

AUTO_REVIEW_REPO = "SayMoreAI/saymore"


@pytest.fixture
def reactor():
    return PRReactor(
        auto_review_repo=AUTO_REVIEW_REPO,
        debounce_seconds=900,
        repo_path="/tmp/fake-saymore",
    )


@pytest.mark.asyncio
async def test_opened_pr_triggers_immediate_review(reactor):
    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event(AUTO_REVIEW_REPO, 42, "opened")

        mock.assert_called_once_with(AUTO_REVIEW_REPO, 42)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reactor.py::test_opened_pr_triggers_immediate_review -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'github_webhook_mcp.reactor'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/github_webhook_mcp/reactor.py
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

AUTO_REVIEW_REPO = "SayMoreAI/saymore"
DEFAULT_DEBOUNCE_SECONDS = 900  # 15 minutes


class PRReactor:
    def __init__(
        self,
        auto_review_repo: str = AUTO_REVIEW_REPO,
        debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
        repo_path: str = "~/dev/saymore",
    ) -> None:
        self.auto_review_repo = auto_review_repo
        self.debounce_seconds = debounce_seconds
        self.repo_path = repo_path
        self._timers: dict[str, asyncio.TimerHandle] = {}

    async def on_pr_event(self, repo: str, pr_number: int, action: str) -> None:
        if repo != self.auto_review_repo:
            return

        key = f"{repo}:{pr_number}"

        if action == "opened":
            self._cancel_timer(key)
            await self._spawn_review(repo, pr_number)
        elif action == "synchronize":
            self._cancel_timer(key)
            loop = asyncio.get_running_loop()
            self._timers[key] = loop.call_later(
                self.debounce_seconds,
                lambda: asyncio.ensure_future(self._spawn_review(repo, pr_number)),
            )
            logger.info(
                "PR %s#%d pushed — review scheduled in %ds",
                repo, pr_number, self.debounce_seconds,
            )

    def _cancel_timer(self, key: str) -> None:
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    async def _spawn_review(self, repo: str, pr_number: int) -> None:
        self._timers.pop(f"{repo}:{pr_number}", None)
        logger.info("Spawning review for %s#%d", repo, pr_number)
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", f"/review-pr {pr_number}",
                "--cwd", self.repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Review complete for %s#%d", repo, pr_number)
            else:
                logger.warning(
                    "Review failed for %s#%d (exit %d): %s",
                    repo, pr_number, proc.returncode,
                    stderr.decode()[:500],
                )
        except FileNotFoundError:
            logger.error("claude CLI not found — cannot spawn review")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reactor.py::test_opened_pr_triggers_immediate_review -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/github_webhook_mcp/reactor.py tests/test_reactor.py
git commit -m "feat: add PRReactor with immediate review on PR opened

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: PRReactor — debounced review on push

**Files:**
- Modify: `tests/test_reactor.py`

- [ ] **Step 1: Write test for debounced review on `synchronize`**

Append to `tests/test_reactor.py`:

```python
@pytest.fixture
def fast_reactor():
    """Reactor with 0s debounce for testing."""
    return PRReactor(
        auto_review_repo=AUTO_REVIEW_REPO,
        debounce_seconds=0,
        repo_path="/tmp/fake-saymore",
    )


@pytest.mark.asyncio
async def test_synchronize_debounces_review(fast_reactor):
    with patch.object(fast_reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")

        # Not called yet — timer hasn't fired
        mock.assert_not_called()

        # Let the event loop run so call_later(0, ...) fires
        await asyncio.sleep(0.05)

        mock.assert_called_once_with(AUTO_REVIEW_REPO, 10)
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reactor.py
git commit -m "test: add debounced review test for PR synchronize events

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: PRReactor — timer reset on rapid pushes

**Files:**
- Modify: `tests/test_reactor.py`

- [ ] **Step 1: Write test for timer reset**

Append to `tests/test_reactor.py`:

```python
@pytest.mark.asyncio
async def test_rapid_pushes_reset_timer(fast_reactor):
    with patch.object(fast_reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")

        await asyncio.sleep(0.05)

        mock.assert_called_once_with(AUTO_REVIEW_REPO, 10)
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reactor.py
git commit -m "test: verify rapid pushes produce only one debounced review

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: PRReactor — ignores non-SayMore repos

**Files:**
- Modify: `tests/test_reactor.py`

- [ ] **Step 1: Write test for repo filtering**

Append to `tests/test_reactor.py`:

```python
@pytest.mark.asyncio
async def test_ignores_non_saymore_repos(reactor):
    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event("mikelane/pytest-gremlins", 5, "opened")
        await reactor.on_pr_event("mikelane/SaunaProtocol", 3, "opened")

        mock.assert_not_called()
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reactor.py
git commit -m "test: verify reactor ignores non-SayMore repos

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Chunk 2: Wiring

### Task 5: SmeeClient — notify reactor on PR events

**Files:**
- Modify: `src/github_webhook_mcp/smee_client.py`
- Modify: `tests/test_smee_client.py`

- [ ] **Step 1: Write failing test for reactor notification**

Append to `tests/test_smee_client.py`:

```python
@pytest.mark.asyncio
async def test_pr_event_notifies_reactor(store):
    from unittest.mock import AsyncMock, MagicMock
    from github_webhook_mcp.reactor import PRReactor

    reactor = MagicMock(spec=PRReactor)
    reactor.on_pr_event = AsyncMock()

    client = SmeeClient(
        channel_url="https://smee.io/test",
        webhook_secret=SECRET,
        store=store,
        reactor=reactor,
    )

    body = {
        "action": "opened",
        "number": 77,
        "repository": {"full_name": "SayMoreAI/saymore"},
        "sender": {"login": "dev"},
        "pull_request": {"number": 77, "title": "New feature"},
    }
    data = _make_smee_data(body, event="pull_request", delivery="d-pr-notify")

    await client.handle_raw_event(json.dumps(data))

    reactor.on_pr_event.assert_called_once_with("SayMoreAI/saymore", 77, "opened")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smee_client.py::test_pr_event_notifies_reactor -v`
Expected: FAIL — `SmeeClient.__init__() got an unexpected keyword argument 'reactor'`

- [ ] **Step 3: Modify SmeeClient**

In `src/github_webhook_mcp/smee_client.py`:

Add `from typing import Any` to imports.

Change constructor signature to:

```python
def __init__(
    self,
    channel_url: str,
    webhook_secret: str,
    store: EventStore,
    reactor: Any | None = None,
) -> None:
    self.channel_url = channel_url
    self.webhook_secret = webhook_secret
    self.store = store
    self.reactor = reactor
    self._backoff = 1.0
    self._max_backoff = 30.0
```

After `await self.store.store_event(webhook_event)` (line 76), add:

```python
        if self.reactor and webhook_event.event_type == "pull_request" and webhook_event.action:
            pr_number = webhook_event.payload.get("number")
            if pr_number is not None:
                await self.reactor.on_pr_event(
                    webhook_event.repo, pr_number, webhook_event.action
                )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`
Expected: All pass (existing tests don't pass `reactor`, so it defaults to `None`).

- [ ] **Step 5: Commit**

```bash
git add src/github_webhook_mcp/smee_client.py tests/test_smee_client.py
git commit -m "feat: notify PR reactor from SmeeClient on pull_request events

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Wire reactor into entry point

**Files:**
- Modify: `src/github_webhook_mcp/__main__.py`

- [ ] **Step 1: Add reactor to `_run()`**

Add import at top:

```python
from .reactor import PRReactor
```

In `_run()`, after `init_server()` and before `SmeeClient` creation, add:

```python
    reactor = PRReactor(repo_path="~/dev/saymore")
```

Pass reactor to SmeeClient:

```python
    smee = SmeeClient(
        channel_url=settings.smee_channel_url,
        webhook_secret=settings.github_webhook_secret,
        store=store,
        reactor=reactor,
    )
```

Add log line after the Smee log:

```python
    logger.info("PR reactor active for %s (debounce: %ds)", reactor.auto_review_repo, reactor.debounce_seconds)
```

- [ ] **Step 2: Verify module imports cleanly**

Run: `uv run python -c "from github_webhook_mcp.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/github_webhook_mcp/__main__.py
git commit -m "feat: wire PR reactor into entry point

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Push and restart

- [ ] **Step 1: Push branch**

```bash
git push -u origin <branch-name>
```

- [ ] **Step 2: Restart the MCP server LaunchAgent**

```bash
launchctl unload ~/Library/LaunchAgents/com.mikelane.github-webhook-mcp.plist
launchctl load ~/Library/LaunchAgents/com.mikelane.github-webhook-mcp.plist
```

- [ ] **Step 3: Verify reactor is active in logs**

Run: `tail -5 ~/Library/Logs/github-webhook-mcp/stderr.log`
Expected: `PR reactor active for SayMoreAI/saymore (debounce: 900s)`
