from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from github_webhook_mcp.models import WebhookEvent
from github_webhook_mcp.server import (
    _require_store,
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
    event_store = EventStore(str(tmp_path / "test.db"))
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
        received_at=datetime.now(UTC),
        delivery_id=delivery_id,
        repo=repo,
        event_type=event_type,
        action=action,
        sender=sender,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_get_pending_reviews_returns_review_requests(store: EventStore) -> None:
    await store.store_event(
        _make_webhook_event(
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

    raw_response = await get_pending_reviews()
    pending_reviews = json.loads(raw_response)

    assert len(pending_reviews) == 1
    assert pending_reviews[0]["number"] == 42


@pytest.mark.asyncio
async def test_get_pending_reviews_filters_by_repo(store: EventStore) -> None:
    for i, repo in enumerate(["mikelane/repo-a", "mikelane/repo-b"]):
        await store.store_event(
            _make_webhook_event(
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

    raw_response = await get_pending_reviews(repo="repo-a")
    pending_reviews = json.loads(raw_response)
    assert len(pending_reviews) == 1


@pytest.mark.asyncio
async def test_get_ci_status_returns_failures(store: EventStore) -> None:
    await store.store_event(
        _make_webhook_event(
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

    raw_response = await get_ci_status()
    ci_failures = json.loads(raw_response)
    assert len(ci_failures) == 1
    assert ci_failures[0]["conclusion"] == "failure"
    assert ci_failures[0]["name"] == "tests"
    assert ci_failures[0]["repo"] == "mikelane/test-repo"
    assert ci_failures[0]["pr_numbers"] == [10]


@pytest.mark.asyncio
async def test_get_new_prs_returns_opened_prs(store: EventStore) -> None:
    await store.store_event(
        _make_webhook_event(
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

    raw_response = await get_new_prs()
    opened_prs = json.loads(raw_response)
    assert len(opened_prs) == 1
    assert opened_prs[0]["number"] == 99


@pytest.mark.asyncio
async def test_get_notifications_returns_all(store: EventStore) -> None:
    await store.store_event(_make_webhook_event("d-n1", "push", "push"))
    await store.store_event(_make_webhook_event("d-n2", "issues", "opened"))

    raw_response = await get_notifications()
    notifications = json.loads(raw_response)
    assert len(notifications) == 2


@pytest.mark.asyncio
async def test_get_notifications_summary_no_double_space_when_action_is_none(
    store: EventStore,
) -> None:
    """When action is None the summary must not contain a double space."""
    webhook_event = WebhookEvent(
        received_at=datetime.now(UTC),
        delivery_id="d-no-action",
        repo="mikelane/test-repo",
        event_type="push",
        action=None,
        sender="octocat",
        payload={
            "repository": {"full_name": "mikelane/test-repo"},
            "sender": {"login": "octocat"},
        },
    )
    await store.store_event(webhook_event)

    raw_response = await get_notifications()
    notifications = json.loads(raw_response)
    assert len(notifications) == 1
    summary = notifications[0]["summary"]
    assert "  " not in summary, f"Double space found in summary: {summary!r}"


# --- _require_store guard ---


@pytest.mark.asyncio
async def test_require_store_raises_when_not_initialized() -> None:
    """_require_store raises RuntimeError before init_server is called."""
    import github_webhook_mcp.server as srv

    original_store = srv._store
    try:
        srv._store = None
        with pytest.raises(RuntimeError, match="init_server"):
            _require_store()
    finally:
        srv._store = original_store


# --- get_pending_reviews: excludes non-matching reviewers ---


@pytest.mark.asyncio
async def test_get_pending_reviews_excludes_other_reviewers(store: EventStore) -> None:
    """Review requests for other users are excluded from results."""
    await store.store_event(
        _make_webhook_event(
            "d-other-reviewer",
            "pull_request",
            "review_requested",
            payload_extra={
                "requested_reviewer": {"login": "someone-else"},
                "pull_request": {
                    "number": 50,
                    "title": "Not for me",
                    "html_url": "https://github.com/mikelane/test-repo/pull/50",
                    "user": {"login": "author"},
                },
            },
        )
    )

    raw_response = await get_pending_reviews()
    pending_reviews = json.loads(raw_response)
    assert len(pending_reviews) == 0


# --- get_review_feedback (was COMPLETELY UNTESTED) ---


@pytest.mark.asyncio
async def test_get_review_feedback_returns_reviews_for_pr(store: EventStore) -> None:
    """Returns review data matching the given PR number."""
    await store.store_event(
        _make_webhook_event(
            "d-review-1",
            "pull_request_review",
            "submitted",
            payload_extra={
                "pull_request": {
                    "number": 42,
                    "html_url": "https://github.com/mikelane/test-repo/pull/42",
                    "user": {"login": "author"},
                },
                "review": {
                    "state": "changes_requested",
                    "body": "Please fix the tests",
                    "user": {"login": "reviewer1"},
                },
            },
        )
    )

    raw_response = await get_review_feedback(pr_number=42, repo="test-repo")
    feedback_entries = json.loads(raw_response)

    assert len(feedback_entries) == 1
    assert feedback_entries[0]["pr_number"] == 42
    assert feedback_entries[0]["author"] == "reviewer1"
    assert feedback_entries[0]["state"] == "changes_requested"
    assert feedback_entries[0]["body"] == "Please fix the tests"


@pytest.mark.asyncio
async def test_get_review_feedback_includes_review_comments(store: EventStore) -> None:
    """Review comments (line-level) are also included."""
    await store.store_event(
        _make_webhook_event(
            "d-comment-1",
            "pull_request_review_comment",
            "created",
            payload_extra={
                "pull_request": {
                    "number": 42,
                    "html_url": "https://github.com/mikelane/test-repo/pull/42",
                    "user": {"login": "author"},
                },
                "comment": {
                    "body": "Nit: rename this variable",
                    "user": {"login": "reviewer2"},
                },
            },
        )
    )

    raw_response = await get_review_feedback(pr_number=42, repo="test-repo")
    feedback_entries = json.loads(raw_response)

    assert len(feedback_entries) == 1
    assert feedback_entries[0]["body"] == "Nit: rename this variable"
    assert feedback_entries[0]["author"] == "reviewer2"


@pytest.mark.asyncio
async def test_get_review_feedback_excludes_other_prs(store: EventStore) -> None:
    """Reviews for a different PR number are excluded."""
    await store.store_event(
        _make_webhook_event(
            "d-review-other",
            "pull_request_review",
            "submitted",
            payload_extra={
                "pull_request": {
                    "number": 99,
                    "html_url": "https://github.com/mikelane/test-repo/pull/99",
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

    raw_response = await get_review_feedback(pr_number=42, repo="test-repo")
    feedback_entries = json.loads(raw_response)
    assert len(feedback_entries) == 0


# --- get_ci_status: success runs are excluded ---


@pytest.mark.asyncio
async def test_get_ci_status_excludes_successful_runs(store: EventStore) -> None:
    """Successful CI runs are not returned -- only failures."""
    await store.store_event(
        _make_webhook_event(
            "d-ci-success",
            "check_run",
            "completed",
            payload_extra={
                "check_run": {
                    "name": "tests",
                    "conclusion": "success",
                    "html_url": "https://github.com/mikelane/test-repo/runs/2",
                    "pull_requests": [{"number": 10}],
                },
            },
        )
    )

    raw_response = await get_ci_status()
    ci_failures = json.loads(raw_response)
    assert len(ci_failures) == 0


# --- get_ci_status: pr_number filter ---


@pytest.mark.asyncio
async def test_get_ci_status_filters_by_pr_number(store: EventStore) -> None:
    """When pr_number is specified, only failures for that PR are returned."""
    for i, pr_num in enumerate([10, 20]):
        await store.store_event(
            _make_webhook_event(
                f"d-ci-pr-{i}",
                "check_run",
                "completed",
                payload_extra={
                    "check_run": {
                        "name": f"test-{pr_num}",
                        "conclusion": "failure",
                        "html_url": f"https://github.com/mikelane/test-repo/runs/{i}",
                        "pull_requests": [{"number": pr_num}],
                    },
                },
            )
        )

    raw_response = await get_ci_status(pr_number=20)
    ci_failures = json.loads(raw_response)
    assert len(ci_failures) == 1
    assert ci_failures[0]["pr_numbers"] == [20]
    assert ci_failures[0]["name"] == "test-20"


# --- get_ci_status: check_suite and workflow_run event types ---


@pytest.mark.asyncio
async def test_get_ci_status_returns_check_suite_failures(store: EventStore) -> None:
    """check_suite events with failure conclusion are returned."""
    await store.store_event(
        _make_webhook_event(
            "d-suite-fail",
            "check_suite",
            "completed",
            payload_extra={
                "check_suite": {
                    "name": "CI Suite",
                    "conclusion": "timed_out",
                    "html_url": "https://github.com/mikelane/test-repo/suites/1",
                    "pull_requests": [],
                },
            },
        )
    )

    raw_response = await get_ci_status()
    ci_failures = json.loads(raw_response)
    assert len(ci_failures) == 1
    assert ci_failures[0]["conclusion"] == "timed_out"


@pytest.mark.asyncio
async def test_get_ci_status_returns_workflow_run_failures(store: EventStore) -> None:
    """workflow_run events with cancelled conclusion are returned."""
    await store.store_event(
        _make_webhook_event(
            "d-wf-cancel",
            "workflow_run",
            "completed",
            payload_extra={
                "workflow_run": {
                    "name": "Deploy",
                    "conclusion": "cancelled",
                    "html_url": "https://github.com/mikelane/test-repo/actions/runs/1",
                    "pull_requests": [{"number": 5}],
                },
            },
        )
    )

    raw_response = await get_ci_status()
    ci_failures = json.loads(raw_response)
    assert len(ci_failures) == 1
    assert ci_failures[0]["name"] == "Deploy"
    assert ci_failures[0]["conclusion"] == "cancelled"


# --- get_new_prs: repo filter ---


@pytest.mark.asyncio
async def test_get_new_prs_filters_by_repo(store: EventStore) -> None:
    """When repo is specified, only PRs from that repo are returned."""
    for i, repo in enumerate(["mikelane/alpha", "mikelane/beta"]):
        await store.store_event(
            _make_webhook_event(
                f"d-pr-repo-{i}",
                "pull_request",
                "opened",
                repo=repo,
                payload_extra={
                    "pull_request": {
                        "number": i + 1,
                        "title": f"PR in {repo}",
                        "html_url": f"https://github.com/{repo}/pull/{i + 1}",
                        "user": {"login": "dev"},
                    },
                },
            )
        )

    raw_response = await get_new_prs(repo="alpha")
    opened_prs = json.loads(raw_response)
    assert len(opened_prs) == 1
    assert opened_prs[0]["repo"] == "mikelane/alpha"
    assert opened_prs[0]["number"] == 1


# --- get_new_prs: since filter ---


@pytest.mark.asyncio
async def test_get_new_prs_filters_by_since(store: EventStore) -> None:
    """When since is specified, only PRs after that time are returned."""
    old_time = datetime(2020, 6, 1, tzinfo=UTC)
    old_webhook_event = WebhookEvent(
        received_at=old_time,
        delivery_id="d-pr-old",
        repo="mikelane/test-repo",
        event_type="pull_request",
        action="opened",
        sender="dev",
        payload={
            "action": "opened",
            "pull_request": {
                "number": 1,
                "title": "Old PR",
                "html_url": "https://github.com/mikelane/test-repo/pull/1",
                "user": {"login": "dev"},
            },
            "repository": {"full_name": "mikelane/test-repo"},
            "sender": {"login": "dev"},
        },
    )
    await store.store_event(old_webhook_event)

    recent_webhook_event = WebhookEvent(
        received_at=datetime.now(UTC),
        delivery_id="d-pr-new",
        repo="mikelane/test-repo",
        event_type="pull_request",
        action="opened",
        sender="dev",
        payload={
            "action": "opened",
            "pull_request": {
                "number": 2,
                "title": "New PR",
                "html_url": "https://github.com/mikelane/test-repo/pull/2",
                "user": {"login": "dev"},
            },
            "repository": {"full_name": "mikelane/test-repo"},
            "sender": {"login": "dev"},
        },
    )
    await store.store_event(recent_webhook_event)

    since_iso = datetime(2024, 1, 1, tzinfo=UTC).isoformat()
    raw_response = await get_new_prs(since=since_iso)
    opened_prs = json.loads(raw_response)

    assert len(opened_prs) == 1
    assert opened_prs[0]["number"] == 2
    assert opened_prs[0]["title"] == "New PR"


# --- get_notifications: field structure ---


@pytest.mark.asyncio
async def test_get_notifications_returns_correct_fields(store: EventStore) -> None:
    """Each notification entry has the expected field structure."""
    await store.store_event(_make_webhook_event("d-fields", "issues", "opened"))

    raw_response = await get_notifications()
    notifications = json.loads(raw_response)
    assert len(notifications) == 1
    entry = notifications[0]

    assert entry["repo"] == "mikelane/test-repo"
    assert entry["event_type"] == "issues"
    assert entry["action"] == "opened"
    assert entry["sender"] == "octocat"
    assert "received_at" in entry
    assert "summary" in entry
