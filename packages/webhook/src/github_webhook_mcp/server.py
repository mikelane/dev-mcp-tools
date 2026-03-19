"""FastMCP server exposing GitHub webhook data as MCP tools."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP

from .storage import EventStore
from .telemetry import init_webhook_telemetry, query_results_counter, trace_tool_async

init_webhook_telemetry()

mcp = FastMCP("github-webhooks")

_store: EventStore | None = None
_username: str = "mikelane"


def init_server(store: EventStore, username: str = "mikelane") -> None:
    """Wire the MCP tool handlers to the given event store.

    Args:
        store: The initialized :class:`EventStore` to query.
        username: The GitHub username used to filter review requests.
    """
    global _store, _username  # noqa: PLW0603
    _store = store
    _username = username


def _require_store() -> EventStore:
    """Return the active event store or raise if :func:`init_server` was not called."""
    if _store is None:
        raise RuntimeError("init_server() must be called before using MCP tools")
    return _store


def _default_since() -> datetime:
    """Return a timestamp 24 hours ago in UTC."""
    return datetime.now(timezone.utc) - timedelta(hours=24)


@mcp.tool()
@trace_tool_async("get_pending_reviews")
async def get_pending_reviews(repo: str | None = None) -> str:
    """Get pull requests awaiting my review.

    Args:
        repo: Filter by repository name (partial match). Omit for all repos.
    """
    events = await _require_store().get_events(
        repo=repo,
        event_type="pull_request",
        action="review_requested",
    )

    pending_reviews = []
    for webhook_event in events:
        reviewer = webhook_event.payload.get("requested_reviewer", {})
        if reviewer.get("login") != _username:
            continue
        pr = webhook_event.payload.get("pull_request", {})
        pending_reviews.append({
            "repo": webhook_event.repo,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("html_url"),
            "author": pr.get("user", {}).get("login"),
            "requested_at": webhook_event.received_at.isoformat(),
        })

    query_results_counter.add(len(pending_reviews), {"tool.name": "get_pending_reviews"})
    return json.dumps(pending_reviews, indent=2)


@mcp.tool()
@trace_tool_async("get_review_feedback")
async def get_review_feedback(pr_number: int, repo: str) -> str:
    """Get review comments on a specific pull request.

    Args:
        pr_number: The PR number to check.
        repo: Repository name (partial match, e.g. 'my-repo' or 'owner/repo').
    """
    reviews = await _require_store().get_events(
        repo=repo,
        event_type="pull_request_review",
    )
    comments = await _require_store().get_events(
        repo=repo,
        event_type="pull_request_review_comment",
    )

    feedback_entries = []
    for webhook_event in reviews + comments:
        pr = webhook_event.payload.get("pull_request", {})
        if pr.get("number") != pr_number:
            continue
        review = webhook_event.payload.get("review", {})
        comment = webhook_event.payload.get("comment", {})
        feedback_entries.append({
            "repo": webhook_event.repo,
            "pr_number": pr_number,
            "author": (review or comment).get("user", {}).get("login"),
            "state": review.get("state"),
            "body": (review or comment).get("body", ""),
            "submitted_at": webhook_event.received_at.isoformat(),
        })

    query_results_counter.add(len(feedback_entries), {"tool.name": "get_review_feedback"})
    return json.dumps(feedback_entries, indent=2)


@mcp.tool()
@trace_tool_async("get_ci_status")
async def get_ci_status(pr_number: int | None = None, repo: str | None = None) -> str:
    """Get CI/CD status, filtered to failures by default.

    Args:
        pr_number: Filter to a specific PR number. Omit for all.
        repo: Filter by repository name (partial match). Omit for all repos.
    """
    ci_failures = []

    for event_type in ("check_run", "check_suite", "workflow_run"):
        events = await _require_store().get_events(repo=repo, event_type=event_type)
        for webhook_event in events:
            ci_run_payload = webhook_event.payload.get("check_run") or webhook_event.payload.get("check_suite") or webhook_event.payload.get("workflow_run", {})
            conclusion = ci_run_payload.get("conclusion")
            if conclusion not in ("failure", "timed_out", "cancelled"):
                continue

            if pr_number:
                associated_prs = ci_run_payload.get("pull_requests", [])
                if not any(pr.get("number") == pr_number for pr in associated_prs):
                    continue

            ci_failures.append({
                "repo": webhook_event.repo,
                "name": ci_run_payload.get("name"),
                "conclusion": conclusion,
                "url": ci_run_payload.get("html_url"),
                "pr_numbers": [pr.get("number") for pr in ci_run_payload.get("pull_requests", [])],
                "completed_at": webhook_event.received_at.isoformat(),
            })

    query_results_counter.add(len(ci_failures), {"tool.name": "get_ci_status"})
    return json.dumps(ci_failures, indent=2)


@mcp.tool()
@trace_tool_async("get_new_prs")
async def get_new_prs(repo: str | None = None, since: str | None = None) -> str:
    """Get recently opened pull requests.

    Args:
        repo: Filter by repository name (partial match). Omit for all repos.
        since: ISO 8601 timestamp. Defaults to last 24 hours.
    """
    since_dt = datetime.fromisoformat(since) if since else _default_since()

    events = await _require_store().get_events(
        repo=repo,
        event_type="pull_request",
        action="opened",
        since=since_dt,
    )

    opened_prs = []
    for webhook_event in events:
        pr = webhook_event.payload.get("pull_request", {})
        opened_prs.append({
            "repo": webhook_event.repo,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("html_url"),
            "author": pr.get("user", {}).get("login"),
            "opened_at": webhook_event.received_at.isoformat(),
        })

    query_results_counter.add(len(opened_prs), {"tool.name": "get_new_prs"})
    return json.dumps(opened_prs, indent=2)


@mcp.tool()
@trace_tool_async("get_notifications")
async def get_notifications(since: str | None = None) -> str:
    """Get all webhook events since a given time, grouped by repo.

    Args:
        since: ISO 8601 timestamp. Defaults to last 24 hours.
    """
    since_dt = datetime.fromisoformat(since) if since else _default_since()
    events = await _require_store().get_events(since=since_dt)

    notification_summaries = []
    for webhook_event in events:
        notification_summaries.append({
            "repo": webhook_event.repo,
            "event_type": webhook_event.event_type,
            "action": webhook_event.action,
            "sender": webhook_event.sender,
            "received_at": webhook_event.received_at.isoformat(),
            "summary": " ".join(filter(None, [webhook_event.sender, webhook_event.action, webhook_event.event_type, "on", webhook_event.repo])),
        })

    query_results_counter.add(len(notification_summaries), {"tool.name": "get_notifications"})
    return json.dumps(notification_summaries, indent=2)
