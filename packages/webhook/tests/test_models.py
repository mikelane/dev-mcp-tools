"""Unit tests for domain models: WebhookEvent and SmeeEvent."""

from __future__ import annotations

from datetime import datetime, timezone

from github_webhook_mcp.models import SmeeEvent, WebhookEvent


# --- WebhookEvent ---


def test_webhook_event_required_fields():
    """WebhookEvent can be constructed with all required fields."""
    event = WebhookEvent(
        received_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
        delivery_id="abc-123",
        repo="owner/repo",
        event_type="push",
        payload={"ref": "refs/heads/main"},
    )

    assert event.delivery_id == "abc-123"
    assert event.repo == "owner/repo"
    assert event.event_type == "push"
    assert event.payload == {"ref": "refs/heads/main"}


def test_webhook_event_optional_fields_default_to_none():
    """Optional fields (id, action, sender) default to None."""
    event = WebhookEvent(
        received_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
        delivery_id="abc",
        repo="owner/repo",
        event_type="push",
        payload={},
    )

    assert event.id is None
    assert event.action is None
    assert event.sender is None


def test_webhook_event_with_all_fields():
    """WebhookEvent populated with every field retains them."""
    event = WebhookEvent(
        id=42,
        received_at=datetime(2025, 3, 15, 12, 0, 0, tzinfo=timezone.utc),
        delivery_id="delivery-999",
        repo="mikelane/test-repo",
        event_type="pull_request",
        action="opened",
        sender="octocat",
        payload={"number": 1},
    )

    assert event.id == 42
    assert event.received_at == datetime(2025, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert event.action == "opened"
    assert event.sender == "octocat"


# --- SmeeEvent: repo_full_name property ---


def test_smee_event_repo_full_name_returns_full_name():
    """repo_full_name extracts repository.full_name from body."""
    event = SmeeEvent(
        body={"repository": {"full_name": "owner/repo"}},
    )

    assert event.repo_full_name == "owner/repo"


def test_smee_event_repo_full_name_returns_none_when_no_repository():
    """repo_full_name returns None when body has no 'repository' key."""
    event = SmeeEvent(body={"action": "completed"})

    assert event.repo_full_name is None


def test_smee_event_repo_full_name_returns_none_when_repository_has_no_full_name():
    """repo_full_name returns None when repository dict lacks 'full_name'."""
    event = SmeeEvent(body={"repository": {"id": 12345}})

    assert event.repo_full_name is None


# --- SmeeEvent: action property ---


def test_smee_event_action_returns_action_from_body():
    """action property extracts 'action' from body."""
    event = SmeeEvent(body={"action": "opened"})

    assert event.action == "opened"


def test_smee_event_action_returns_none_when_missing():
    """action property returns None when body has no 'action' key."""
    event = SmeeEvent(body={"ref": "refs/heads/main"})

    assert event.action is None


# --- SmeeEvent: sender_login property ---


def test_smee_event_sender_login_returns_login():
    """sender_login extracts sender.login from body."""
    event = SmeeEvent(body={"sender": {"login": "octocat"}})

    assert event.sender_login == "octocat"


def test_smee_event_sender_login_returns_none_when_no_sender():
    """sender_login returns None when body has no 'sender' key."""
    event = SmeeEvent(body={"action": "push"})

    assert event.sender_login is None


def test_smee_event_sender_login_returns_none_when_sender_has_no_login():
    """sender_login returns None when sender dict lacks 'login'."""
    event = SmeeEvent(body={"sender": {"id": 99}})

    assert event.sender_login is None


# --- SmeeEvent: optional header fields ---


def test_smee_event_header_fields_default_to_none():
    """x_github_event, x_github_delivery, x_hub_signature_256 default to None."""
    event = SmeeEvent(body={})

    assert event.x_github_event is None
    assert event.x_github_delivery is None
    assert event.x_hub_signature_256 is None


def test_smee_event_header_fields_populated():
    """Header fields are stored when provided."""
    event = SmeeEvent(
        body={},
        x_github_event="push",
        x_github_delivery="d-abc",
        x_hub_signature_256="sha256=abc123",
    )

    assert event.x_github_event == "push"
    assert event.x_github_delivery == "d-abc"
    assert event.x_hub_signature_256 == "sha256=abc123"
