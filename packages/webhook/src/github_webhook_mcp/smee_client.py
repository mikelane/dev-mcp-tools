"""Smee.io SSE client that receives GitHub webhooks and stores them."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import httpx
from httpx_sse import aconnect_sse

from .models import SmeeEvent, WebhookEvent
from .signature import verify_signature
from .storage import EventStore
from .telemetry import events_received_counter, get_tracer

logger = logging.getLogger(__name__)

_tracer = get_tracer("webhook.smee_client")


@runtime_checkable
class PREventHandler(Protocol):
    """Protocol for objects that can react to pull-request webhook events."""

    async def on_pr_event(self, repo: str, pr_number: int, action: str) -> None:
        """Handle a pull-request event.

        Args:
            repo: The full repository name (``owner/repo``).
            pr_number: The pull-request number.
            action: The webhook action (e.g. ``"opened"``, ``"synchronize"``).
        """
        ...


class SmeeClient:
    """SSE client that connects to a Smee.io channel and processes webhook events.

    Maintains a persistent connection with exponential backoff on failure.
    Received events are stored via the provided :class:`EventStore` and
    optionally forwarded to a :class:`PREventHandler` for automated reactions.
    """

    def __init__(
        self,
        channel_url: str,
        webhook_secret: str,
        store: EventStore,
        reactor: PREventHandler | None = None,
    ) -> None:
        self.channel_url = channel_url
        self.webhook_secret = webhook_secret
        self.store = store
        self.reactor = reactor
        self._backoff = 1.0
        self._max_backoff = 30.0

    async def process_sse_message(self, raw_data: str) -> None:
        """Parse a raw SSE data string, store the event, and notify the reactor.

        Args:
            raw_data: The raw JSON string from the Smee.io SSE stream.
        """
        with _tracer.start_as_current_span("smee.process_message") as span:
            try:
                smee_envelope = json.loads(raw_data)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON SSE data, skipping")
                return

            if "body" not in smee_envelope:
                return

            event = SmeeEvent(
                body=smee_envelope["body"],
                x_github_event=smee_envelope.get("x-github-event"),
                x_github_delivery=smee_envelope.get("x-github-delivery"),
                x_hub_signature_256=smee_envelope.get("x-hub-signature-256"),
            )

            if not event.repo_full_name:
                logger.debug("Event has no repository, skipping: %s", event.x_github_delivery)
                return

            span.set_attribute("smee.event_type", event.x_github_event or "unknown")
            span.set_attribute("smee.delivery_id", event.x_github_delivery or "")
            span.set_attribute("smee.repo", event.repo_full_name)

            # Signature verification is best-effort with Smee.io. Smee re-serializes
            # the JSON body, so json.dumps() produces different bytes than what GitHub
            # originally signed. The Smee channel URL itself is the security boundary.
            payload_bytes = json.dumps(event.body).encode()
            if event.x_hub_signature_256 and not verify_signature(
                payload_bytes, event.x_hub_signature_256, self.webhook_secret
            ):
                logger.debug(
                    "Signature mismatch for delivery %s (expected with Smee proxy)",
                    event.x_github_delivery,
                )

            webhook_event = WebhookEvent(
                received_at=datetime.now(UTC),
                delivery_id=event.x_github_delivery or "",
                repo=event.repo_full_name,
                event_type=event.x_github_event or "unknown",
                action=event.action,
                sender=event.sender_login,
                payload=event.body,
            )

            await self.store.store_event(webhook_event)
            events_received_counter.add(
                1,
                {
                    "event.type": webhook_event.event_type,
                    "event.repo": webhook_event.repo,
                },
            )

            if self.reactor and webhook_event.event_type == "pull_request" and webhook_event.action:
                pr_number = webhook_event.payload.get("number")
                if isinstance(pr_number, int):
                    await self.reactor.on_pr_event(
                        webhook_event.repo, pr_number, webhook_event.action
                    )

            self._backoff = 1.0

    async def listen(self) -> None:
        """Connect to the Smee channel and process events indefinitely.

        Reconnects with exponential backoff (up to 30 s) on connection failures.
        This coroutine never returns under normal operation.
        """
        while True:
            try:
                logger.info("Connecting to Smee channel: %s", self.channel_url)
                with _tracer.start_as_current_span("smee.connection") as conn_span:
                    conn_span.set_attribute("smee.channel_url", self.channel_url)
                    async with (
                        httpx.AsyncClient(timeout=None) as client,  # noqa: S113
                        aconnect_sse(
                            client, "GET", self.channel_url
                        ) as source,
                    ):
                        self._backoff = 1.0
                        async for sse_event in source.aiter_sse():
                            if sse_event.data:
                                await self.process_sse_message(sse_event.data)
            except (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ) as exc:
                logger.warning(
                    "Smee connection lost (%s), reconnecting in %.0fs",
                    exc,
                    self._backoff,
                )
            except Exception:
                logger.exception(
                    "Unexpected error in Smee listener, reconnecting in %.0fs",
                    self._backoff,
                )

            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)
