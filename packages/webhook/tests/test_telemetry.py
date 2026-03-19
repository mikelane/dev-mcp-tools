"""Tests for webhook OpenTelemetry instrumentation."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from github_webhook_mcp.models import WebhookEvent
from github_webhook_mcp.server import (
    get_ci_status,
    get_new_prs,
    get_notifications,
    get_pending_reviews,
    get_review_feedback,
    init_server,
)
from github_webhook_mcp.storage import EventStore


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[EventStore]:
    event_store = EventStore(str(tmp_path / "test_telemetry.db"))
    await event_store.initialize()
    init_server(event_store)
    yield event_store
    await event_store.close()


def _make_webhook_event(
    delivery_id: str,
    event_type: str,
    action: str,
    repo: str = "mikelane/test-repo",
    sender: str = "octocat",
    payload_extra: dict[str, Any] | None = None,
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


# --- trace_tool_async: decorated tools still return correct results ---


@pytest.mark.asyncio
async def test_get_pending_reviews_returns_correct_result_with_decorator(
    store: EventStore,
) -> None:
    await store.store_event(
        _make_webhook_event(
            "d-tel-1",
            "pull_request",
            "review_requested",
            payload_extra={
                "requested_reviewer": {"login": "mikelane"},
                "pull_request": {
                    "number": 10,
                    "title": "Telemetry PR",
                    "html_url": "https://github.com/mikelane/test-repo/pull/10",
                    "user": {"login": "octocat"},
                },
            },
        )
    )

    result = await get_pending_reviews()
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["number"] == 10


@pytest.mark.asyncio
async def test_get_review_feedback_returns_correct_result_with_decorator(
    store: EventStore,
) -> None:
    await store.store_event(
        _make_webhook_event(
            "d-tel-2",
            "pull_request_review",
            "submitted",
            payload_extra={
                "pull_request": {
                    "number": 20,
                    "html_url": "https://github.com/mikelane/test-repo/pull/20",
                    "user": {"login": "author"},
                },
                "review": {
                    "state": "approved",
                    "body": "LGTM",
                    "user": {"login": "reviewer"},
                },
            },
        )
    )

    result = await get_review_feedback(pr_number=20, repo="test-repo")
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["state"] == "approved"


@pytest.mark.asyncio
async def test_get_ci_status_returns_correct_result_with_decorator(
    store: EventStore,
) -> None:
    await store.store_event(
        _make_webhook_event(
            "d-tel-3",
            "check_run",
            "completed",
            payload_extra={
                "check_run": {
                    "name": "lint",
                    "conclusion": "failure",
                    "html_url": "https://github.com/mikelane/test-repo/runs/1",
                    "pull_requests": [],
                },
            },
        )
    )

    result = await get_ci_status()
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["name"] == "lint"


@pytest.mark.asyncio
async def test_get_new_prs_returns_correct_result_with_decorator(
    store: EventStore,
) -> None:
    await store.store_event(
        _make_webhook_event(
            "d-tel-4",
            "pull_request",
            "opened",
            payload_extra={
                "pull_request": {
                    "number": 30,
                    "title": "New feature",
                    "html_url": "https://github.com/mikelane/test-repo/pull/30",
                    "user": {"login": "dev"},
                },
            },
        )
    )

    result = await get_new_prs()
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["number"] == 30


@pytest.mark.asyncio
async def test_get_notifications_returns_correct_result_with_decorator(
    store: EventStore,
) -> None:
    await store.store_event(
        _make_webhook_event("d-tel-5", "push", "push")
    )

    result = await get_notifications()
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["event_type"] == "push"


# --- tool_calls_counter: incremented on each tool invocation ---


@pytest.mark.asyncio
async def test_tool_calls_counter_increments_on_get_pending_reviews(
    store: EventStore,
) -> None:
    from github_webhook_mcp import telemetry

    call_args_list: list[tuple[Any, ...]] = []
    original_add = telemetry.tool_calls_counter.add

    def tracking_add(*args: Any, **kwargs: Any) -> None:
        call_args_list.append(args)
        original_add(*args, **kwargs)

    with patch.object(telemetry.tool_calls_counter, "add", side_effect=tracking_add):
        await get_pending_reviews()

    assert len(call_args_list) == 1
    assert call_args_list[0][0] == 1
    assert call_args_list[0][1]["tool.name"] == "get_pending_reviews"


# --- query_results_counter: records result counts ---


@pytest.mark.asyncio
async def test_query_results_counter_records_count_for_get_notifications(
    store: EventStore,
) -> None:
    await store.store_event(_make_webhook_event("d-qr-1", "push", "push"))
    await store.store_event(_make_webhook_event("d-qr-2", "issues", "opened"))

    from github_webhook_mcp import server

    call_args_list: list[tuple[Any, ...]] = []
    original_add = server.query_results_counter.add

    def tracking_add(*args: Any, **kwargs: Any) -> None:
        call_args_list.append(args)
        original_add(*args, **kwargs)

    with patch.object(server.query_results_counter, "add", side_effect=tracking_add):
        await get_notifications()

    assert len(call_args_list) == 1
    assert call_args_list[0][0] == 2
    assert call_args_list[0][1]["tool.name"] == "get_notifications"


@pytest.mark.asyncio
async def test_query_results_counter_records_zero_when_no_results(
    store: EventStore,
) -> None:
    from github_webhook_mcp import server

    call_args_list: list[tuple[Any, ...]] = []
    original_add = server.query_results_counter.add

    def tracking_add(*args: Any, **kwargs: Any) -> None:
        call_args_list.append(args)
        original_add(*args, **kwargs)

    with patch.object(server.query_results_counter, "add", side_effect=tracking_add):
        await get_pending_reviews()

    assert len(call_args_list) == 1
    assert call_args_list[0][0] == 0


# --- SmeeClient: events_received_counter ---


@pytest.mark.asyncio
async def test_smee_client_increments_events_received_counter(
    store: EventStore,
) -> None:
    from github_webhook_mcp import telemetry
    from github_webhook_mcp.smee_client import SmeeClient

    secret = "test-secret"
    client = SmeeClient(
        channel_url="https://smee.io/test",
        webhook_secret=secret,
        store=store,
    )

    body = {
        "action": "opened",
        "number": 1,
        "repository": {"full_name": "mikelane/repo"},
        "sender": {"login": "octocat"},
    }
    payload_bytes = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    envelope = json.dumps({
        "body": body,
        "x-github-event": "pull_request",
        "x-github-delivery": "d-smee-tel-1",
        "x-hub-signature-256": signature,
    })

    call_args_list: list[tuple[Any, ...]] = []
    original_add = telemetry.events_received_counter.add

    def tracking_add(*args: Any, **kwargs: Any) -> None:
        call_args_list.append(args)
        original_add(*args, **kwargs)

    with patch.object(
        telemetry.events_received_counter, "add", side_effect=tracking_add
    ):
        await client.process_sse_message(envelope)

    assert len(call_args_list) == 1
    assert call_args_list[0][0] == 1
    assert call_args_list[0][1]["event.type"] == "pull_request"
    assert call_args_list[0][1]["event.repo"] == "mikelane/repo"


@pytest.mark.asyncio
async def test_smee_client_does_not_increment_counter_for_non_json(
    store: EventStore,
) -> None:
    from github_webhook_mcp import telemetry
    from github_webhook_mcp.smee_client import SmeeClient

    client = SmeeClient(
        channel_url="https://smee.io/test",
        webhook_secret="secret",
        store=store,
    )

    call_args_list: list[tuple[Any, ...]] = []
    original_add = telemetry.events_received_counter.add

    def tracking_add(*args: Any, **kwargs: Any) -> None:
        call_args_list.append(args)
        original_add(*args, **kwargs)

    with patch.object(
        telemetry.events_received_counter, "add", side_effect=tracking_add
    ):
        await client.process_sse_message("not json")

    assert len(call_args_list) == 0


# --- EventStore: spans don't break store/retrieve ---


@pytest.mark.asyncio
async def test_eventstore_stores_and_retrieves_with_spans(
    store: EventStore,
) -> None:
    event = WebhookEvent(
        received_at=datetime.now(timezone.utc),
        delivery_id="d-store-tel-1",
        repo="mikelane/test-repo",
        event_type="push",
        action="push",
        sender="octocat",
        payload={"ref": "refs/heads/main"},
    )

    stored = await store.store_event(event)
    assert stored is True

    events = await store.get_events()
    assert len(events) == 1
    assert events[0].delivery_id == "d-store-tel-1"


@pytest.mark.asyncio
async def test_eventstore_handles_duplicates_with_spans(
    store: EventStore,
) -> None:
    event = WebhookEvent(
        received_at=datetime.now(timezone.utc),
        delivery_id="d-store-tel-dup",
        repo="mikelane/test-repo",
        event_type="push",
        action="push",
        sender="octocat",
        payload={"ref": "refs/heads/main"},
    )

    first = await store.store_event(event)
    second = await store.store_event(event)

    assert first is True
    assert second is False


# --- PRReactor: spans don't break reactor behavior ---


@pytest.mark.asyncio
async def test_reactor_traces_immediate_review_on_opened() -> None:
    from github_webhook_mcp.reactor import PRReactor

    reactor = PRReactor(
        auto_review_repo="SayMoreAI/saymore",
        debounce_seconds=900,
        repo_path="/tmp/fake",
    )

    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event("SayMoreAI/saymore", 42, "opened")
        mock.assert_called_once_with("SayMoreAI/saymore", 42)


@pytest.mark.asyncio
async def test_reactor_traces_skipped_non_matching_repo() -> None:
    from github_webhook_mcp.reactor import PRReactor

    reactor = PRReactor(
        auto_review_repo="SayMoreAI/saymore",
        debounce_seconds=900,
        repo_path="/tmp/fake",
    )

    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event("other/repo", 1, "opened")
        mock.assert_not_called()


@pytest.mark.asyncio
async def test_reactor_traces_spawn_review_success() -> None:
    from github_webhook_mcp.reactor import PRReactor

    reactor = PRReactor(repo_path="/tmp/fake")

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"ok", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await reactor._spawn_review("SayMoreAI/saymore", 42)


@pytest.mark.asyncio
async def test_reactor_traces_spawn_review_failure() -> None:
    from github_webhook_mcp.reactor import PRReactor

    reactor = PRReactor(repo_path="/tmp/fake")

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b"err"))
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await reactor._spawn_review("SayMoreAI/saymore", 42)


@pytest.mark.asyncio
async def test_reactor_traces_spawn_review_cli_not_found() -> None:
    from github_webhook_mcp.reactor import PRReactor

    reactor = PRReactor(repo_path="/tmp/fake")

    with patch(
        "asyncio.create_subprocess_exec", side_effect=FileNotFoundError
    ):
        await reactor._spawn_review("SayMoreAI/saymore", 42)
