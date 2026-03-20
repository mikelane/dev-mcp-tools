from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from github_webhook_mcp.reactor import PRReactor
from github_webhook_mcp.smee_client import SmeeClient
from github_webhook_mcp.storage import EventStore

SECRET = "test-secret"


def _make_smee_envelope(
    body: dict[str, Any],
    event: str = "pull_request",
    delivery: str = "d-001",
) -> dict[str, Any]:
    """Build a Smee SSE envelope dict matching Smee.io's format."""
    payload_bytes = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return {
        "body": body,
        "x-github-event": event,
        "x-github-delivery": delivery,
        "x-hub-signature-256": signature,
    }


@pytest.fixture
def client(store: EventStore) -> SmeeClient:
    return SmeeClient(
        channel_url="https://smee.io/test",
        webhook_secret=SECRET,
        store=store,
    )


@pytest.mark.asyncio
async def test_valid_event_is_stored(client: SmeeClient, store: EventStore) -> None:
    body = {
        "action": "opened",
        "number": 1,
        "repository": {"full_name": "mikelane/repo"},
        "sender": {"login": "octocat"},
    }
    smee_envelope = _make_smee_envelope(body)

    await client.process_sse_message(json.dumps(smee_envelope))

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].repo == "mikelane/repo"
    assert events[0].event_type == "pull_request"


@pytest.mark.asyncio
async def test_event_with_bad_signature_is_still_stored(
    client: SmeeClient,
    store: EventStore,
) -> None:
    """Smee.io re-serializes JSON, so signatures never match.
    Events are stored anyway since the channel URL is the security boundary."""
    smee_envelope = {
        "body": {
            "action": "opened",
            "repository": {"full_name": "x/y"},
            "sender": {"login": "x"},
        },
        "x-github-event": "push",
        "x-github-delivery": "d-bad",
        "x-hub-signature-256": "sha256=bogus",
    }

    await client.process_sse_message(json.dumps(smee_envelope))

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].repo == "x/y"


@pytest.mark.asyncio
async def test_event_missing_repo_is_skipped(
    client: SmeeClient,
    store: EventStore,
) -> None:
    body: dict[str, Any] = {"action": "completed"}  # no "repository" key
    smee_envelope = _make_smee_envelope(body, event="check_run", delivery="d-norepo")

    await client.process_sse_message(json.dumps(smee_envelope))

    events = await store.get_events()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_pr_event_notifies_reactor(store: EventStore) -> None:
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
    smee_envelope = _make_smee_envelope(body, event="pull_request", delivery="d-pr-notify")

    await client.process_sse_message(json.dumps(smee_envelope))

    reactor.on_pr_event.assert_called_once_with("SayMoreAI/saymore", 77, "opened")


@pytest.mark.asyncio
async def test_non_json_sse_data_is_skipped(
    client: SmeeClient,
    store: EventStore,
) -> None:
    """Non-JSON SSE data (e.g. keepalive messages) is silently skipped."""
    await client.process_sse_message("this is not json")

    events = await store.get_events()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_json_without_body_key_is_skipped(
    client: SmeeClient,
    store: EventStore,
) -> None:
    """SSE data that parses as JSON but has no 'body' key is skipped."""
    await client.process_sse_message(json.dumps({"timestamp": 12345}))

    events = await store.get_events()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_non_pr_event_does_not_notify_reactor(store: EventStore) -> None:
    """Push events and other non-PR events do not trigger the reactor."""
    reactor = MagicMock(spec=PRReactor)
    reactor.on_pr_event = AsyncMock()

    client = SmeeClient(
        channel_url="https://smee.io/test",
        webhook_secret=SECRET,
        store=store,
        reactor=reactor,
    )

    body = {
        "action": "completed",
        "repository": {"full_name": "mikelane/repo"},
        "sender": {"login": "bot"},
    }
    smee_envelope = _make_smee_envelope(body, event="push", delivery="d-push-no-reactor")

    await client.process_sse_message(json.dumps(smee_envelope))

    reactor.on_pr_event.assert_not_called()
    events = await store.get_events()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_pr_event_without_number_does_not_notify_reactor(
    store: EventStore,
) -> None:
    """A pull_request event where payload 'number' is missing skips reactor."""
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
        # no "number" key at top level
        "repository": {"full_name": "mikelane/repo"},
        "sender": {"login": "dev"},
    }
    smee_envelope = _make_smee_envelope(body, event="pull_request", delivery="d-pr-no-num")

    await client.process_sse_message(json.dumps(smee_envelope))

    reactor.on_pr_event.assert_not_called()
    events = await store.get_events()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_backoff_resets_after_successful_event(
    client: SmeeClient,
    store: EventStore,
) -> None:
    """After a successful process_sse_message, _backoff resets to 1.0."""
    client._backoff = 16.0  # simulate previous reconnection backoff

    body = {
        "action": "opened",
        "number": 1,
        "repository": {"full_name": "mikelane/repo"},
        "sender": {"login": "octocat"},
    }
    smee_envelope = _make_smee_envelope(body, delivery="d-backoff-reset")

    await client.process_sse_message(json.dumps(smee_envelope))

    assert client._backoff == 1.0


@pytest.mark.asyncio
async def test_event_without_signature_is_stored(
    client: SmeeClient,
    store: EventStore,
) -> None:
    """Events with no x-hub-signature-256 header are stored without error."""
    smee_envelope = {
        "body": {
            "action": "opened",
            "repository": {"full_name": "mikelane/repo"},
            "sender": {"login": "dev"},
        },
        "x-github-event": "issues",
        "x-github-delivery": "d-no-sig",
        # No x-hub-signature-256 key
    }

    await client.process_sse_message(json.dumps(smee_envelope))

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].event_type == "issues"
    assert events[0].delivery_id == "d-no-sig"


@pytest.mark.asyncio
async def test_missing_optional_headers_use_fallbacks(
    client: SmeeClient,
    store: EventStore,
) -> None:
    """Events missing x-github-event and x-github-delivery use fallbacks."""
    smee_envelope = {
        "body": {
            "action": "created",
            "repository": {"full_name": "mikelane/repo"},
            "sender": {"login": "bot"},
        },
        # No x-github-event, no x-github-delivery, no signature
    }

    await client.process_sse_message(json.dumps(smee_envelope))

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].event_type == "unknown"
    assert events[0].delivery_id == ""
