"""Pydantic models for GitHub webhook events and Smee.io SSE envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WebhookEvent(BaseModel):
    """A stored GitHub webhook event with parsed metadata.

    Represents a single webhook delivery after it has been received,
    validated, and persisted to the event store.
    """

    id: int | None = None
    received_at: datetime
    delivery_id: str
    repo: str
    event_type: str
    action: str | None = None
    sender: str | None = None
    payload: dict[str, Any]


class SmeeEvent(BaseModel):
    """Raw event as received from the Smee.io SSE stream.

    Smee wraps the original GitHub webhook payload with its own envelope
    that includes the original HTTP headers GitHub sent.
    """

    body: dict[str, Any]
    x_github_event: str | None = None
    x_github_delivery: str | None = None
    x_hub_signature_256: str | None = None

    @property
    def repo_full_name(self) -> str | None:
        """Extract the repository full name from the event body.

        Returns:
            The ``owner/repo`` string, or ``None`` if the body has no
            repository information.
        """
        repo = self.body.get("repository")
        if repo:
            return repo.get("full_name")
        return None

    @property
    def action(self) -> str | None:
        """Extract the action field from the event body.

        Returns:
            The action string (e.g. ``"opened"``, ``"closed"``), or ``None``.
        """
        return self.body.get("action")

    @property
    def sender_login(self) -> str | None:
        """Extract the sender's login from the event body.

        Returns:
            The sender's GitHub username, or ``None``.
        """
        sender = self.body.get("sender")
        if sender:
            return sender.get("login")
        return None
