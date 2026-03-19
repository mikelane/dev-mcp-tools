from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from github_webhook_mcp.models import WebhookEvent
from github_webhook_mcp.storage import EventStore


@pytest.fixture(autouse=True)
def _disable_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable OpenTelemetry for all webhook tests."""
    monkeypatch.setenv("ORACLE_TELEMETRY_ENABLED", "false")


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[EventStore]:
    db_path = str(tmp_path / "test_events.db")
    event_store = EventStore(db_path)
    await event_store.initialize()
    yield event_store
    await event_store.close()


@pytest.fixture
def sample_event() -> WebhookEvent:
    return WebhookEvent(
        received_at=datetime.now(UTC),
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
