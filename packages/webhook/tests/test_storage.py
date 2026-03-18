from __future__ import annotations

from datetime import datetime, timezone

import pytest

from github_webhook_mcp.models import WebhookEvent
from github_webhook_mcp.storage import EventStore


@pytest.mark.asyncio
async def test_store_initializes_database(store: EventStore) -> None:
    rows = await store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] async for r in rows]
    assert "events" in tables


@pytest.mark.asyncio
async def test_store_event_and_retrieve(store: EventStore, sample_event: WebhookEvent) -> None:
    stored = await store.store_event(sample_event)
    assert stored is True

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].delivery_id == "delivery-001"
    assert events[0].repo == "mikelane/test-repo"


@pytest.mark.asyncio
async def test_duplicate_delivery_id_is_ignored(store: EventStore, sample_event: WebhookEvent) -> None:
    await store.store_event(sample_event)
    stored_again = await store.store_event(sample_event)

    assert stored_again is False
    events = await store.get_events()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_query_by_repo_filter(store: EventStore, sample_event: WebhookEvent) -> None:
    await store.store_event(sample_event)

    other = sample_event.model_copy(
        update={"delivery_id": "delivery-002", "repo": "other-org/other-repo"}
    )
    await store.store_event(other)

    matched_events = await store.get_events(repo="test-repo")
    assert len(matched_events) == 1
    assert matched_events[0].repo == "mikelane/test-repo"


@pytest.mark.asyncio
async def test_query_by_event_type(store: EventStore, sample_event: WebhookEvent) -> None:
    await store.store_event(sample_event)

    issue_event = sample_event.model_copy(
        update={"delivery_id": "delivery-003", "event_type": "issues"}
    )
    await store.store_event(issue_event)

    matched_events = await store.get_events(event_type="pull_request")
    assert len(matched_events) == 1


@pytest.mark.asyncio
async def test_repo_filter_escapes_sql_wildcards(store: EventStore, sample_event: WebhookEvent) -> None:
    await store.store_event(sample_event)

    percent_matches = await store.get_events(repo="%")
    assert len(percent_matches) == 0

    underscore_matches = await store.get_events(repo="_")
    assert len(underscore_matches) == 0

    exact_matches = await store.get_events(repo="test-repo")
    assert len(exact_matches) == 1


@pytest.mark.asyncio
async def test_query_by_since(store: EventStore, sample_event: WebhookEvent) -> None:
    old_event = sample_event.model_copy(
        update={
            "delivery_id": "delivery-old",
            "received_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        }
    )
    await store.store_event(old_event)
    await store.store_event(sample_event)

    recent_events = await store.get_events(since=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert len(recent_events) == 1
    assert recent_events[0].delivery_id == "delivery-001"


@pytest.mark.asyncio
async def test_prune_removes_old_events(store: EventStore, sample_event: WebhookEvent) -> None:
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
async def test_prune_preserves_recent_events(store: EventStore, sample_event: WebhookEvent) -> None:
    await store.store_event(sample_event)

    deleted = await store.prune(days=7)

    assert deleted == 0
    remaining = await store.get_events()
    assert len(remaining) == 1


# --- _require_db guard ---


@pytest.mark.asyncio
async def test_require_db_raises_before_initialize() -> None:
    """Calling _require_db before initialize raises RuntimeError."""
    from github_webhook_mcp.storage import EventStore

    store = EventStore("/tmp/nonexistent/never-created.db")
    # db is None because initialize() was never called
    with pytest.raises(RuntimeError, match="initialize"):
        store._require_db()


# --- get_events: action filter ---


@pytest.mark.asyncio
async def test_query_by_action_filter(store: EventStore, sample_event: WebhookEvent) -> None:
    """Filtering by action returns only events with that action."""
    await store.store_event(sample_event)  # action="opened"

    closed_event = sample_event.model_copy(
        update={"delivery_id": "delivery-closed", "action": "closed"}
    )
    await store.store_event(closed_event)

    opened_events = await store.get_events(action="opened")
    assert len(opened_events) == 1
    assert opened_events[0].action == "opened"
    assert opened_events[0].delivery_id == "delivery-001"

    results_closed = await store.get_events(action="closed")
    assert len(results_closed) == 1
    assert results_closed[0].action == "closed"


# --- get_events: sender filter ---


@pytest.mark.asyncio
async def test_query_by_sender_filter(store: EventStore, sample_event: WebhookEvent) -> None:
    """Filtering by sender returns only events from that sender."""
    await store.store_event(sample_event)  # sender="octocat"

    other_sender = sample_event.model_copy(
        update={"delivery_id": "delivery-other-sender", "sender": "dependabot"}
    )
    await store.store_event(other_sender)

    octocat_events = await store.get_events(sender="octocat")
    assert len(octocat_events) == 1
    assert octocat_events[0].sender == "octocat"

    results_bot = await store.get_events(sender="dependabot")
    assert len(results_bot) == 1
    assert results_bot[0].sender == "dependabot"

    results_none = await store.get_events(sender="nonexistent")
    assert len(results_none) == 0


# --- get_events: combined filters ---


@pytest.mark.asyncio
async def test_query_with_multiple_filters(store: EventStore, sample_event: WebhookEvent) -> None:
    """Multiple filters are AND-combined."""
    await store.store_event(sample_event)  # repo=mikelane/test-repo, event_type=pull_request, action=opened

    issue_event = sample_event.model_copy(
        update={"delivery_id": "delivery-issue", "event_type": "issues", "action": "opened"}
    )
    await store.store_event(issue_event)

    opened_pr_events = await store.get_events(event_type="pull_request", action="opened")
    assert len(opened_pr_events) == 1
    assert opened_pr_events[0].event_type == "pull_request"
    assert opened_pr_events[0].action == "opened"

    closed_pr_events = await store.get_events(event_type="pull_request", action="closed")
    assert len(closed_pr_events) == 0


# --- get_events: no filters returns all ---


@pytest.mark.asyncio
async def test_query_no_filters_returns_all(store: EventStore, sample_event: WebhookEvent) -> None:
    """Calling get_events with no filters returns all stored events."""
    await store.store_event(sample_event)
    second = sample_event.model_copy(update={"delivery_id": "delivery-second"})
    await store.store_event(second)

    all_events = await store.get_events()
    assert len(all_events) == 2


# --- get_events: results ordered by received_at descending ---


@pytest.mark.asyncio
async def test_query_results_ordered_by_received_at_descending(store: EventStore, sample_event: WebhookEvent) -> None:
    """Events are returned newest first."""
    old = sample_event.model_copy(
        update={
            "delivery_id": "delivery-old",
            "received_at": datetime(2023, 1, 1, tzinfo=timezone.utc),
        }
    )
    new = sample_event.model_copy(
        update={
            "delivery_id": "delivery-new",
            "received_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        }
    )
    await store.store_event(old)
    await store.store_event(new)

    ordered_events = await store.get_events()
    assert ordered_events[0].delivery_id == "delivery-new"
    assert ordered_events[1].delivery_id == "delivery-old"


# --- store_event: payload roundtrip ---


@pytest.mark.asyncio
async def test_store_event_preserves_payload(store: EventStore, sample_event: WebhookEvent) -> None:
    """The full payload dict survives the store/retrieve roundtrip."""
    await store.store_event(sample_event)

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].payload == sample_event.payload
    assert events[0].payload["number"] == 42
    assert events[0].payload["pull_request"]["title"] == "Add feature"


# --- close is idempotent ---


@pytest.mark.asyncio
async def test_close_is_idempotent(store: EventStore, sample_event: WebhookEvent) -> None:
    """Calling close on a store that has no db set does not raise."""
    from github_webhook_mcp.storage import EventStore

    never_opened = EventStore("/tmp/nonexistent.db")
    # db is None, close should not raise
    await never_opened.close()
