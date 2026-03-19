"""SQLite-backed storage for webhook events using aiosqlite."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import aiosqlite
from opentelemetry import trace

from .models import WebhookEvent

logger = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None


def _get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        from .telemetry import get_tracer

        _tracer = get_tracer("webhook.storage")
    return _tracer


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TEXT NOT NULL,
    delivery_id   TEXT UNIQUE,
    repo          TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    action        TEXT,
    sender        TEXT,
    payload       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_repo_type_time
    ON events (repo, event_type, received_at);

CREATE INDEX IF NOT EXISTS idx_received_at
    ON events (received_at);
"""


class EventStore:
    """Async SQLite store for persisting and querying webhook events.

    Call :meth:`initialize` before any other method to create the database
    and schema.  Call :meth:`close` when shutting down.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create the database file (if needed) and apply the schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(_SCHEMA)
        await self.db.commit()

    def _require_db(self) -> aiosqlite.Connection:
        """Return the active database connection or raise if uninitialized."""
        if self.db is None:
            raise RuntimeError("EventStore.initialize() must be called before use")
        return self.db

    async def store_event(self, event: WebhookEvent) -> bool:
        """Persist a webhook event, ignoring duplicates by delivery ID.

        Args:
            event: The webhook event to store.

        Returns:
            ``True`` if the event was inserted, ``False`` if it was a duplicate.
        """
        tracer = _get_tracer()
        with tracer.start_as_current_span("eventstore.store_event") as span:
            span.set_attribute("db.system", "sqlite")
            span.set_attribute("db.operation", "INSERT")
            span.set_attribute("event.delivery_id", event.delivery_id)
            span.set_attribute("event.repo", event.repo)
            span.set_attribute("event.type", event.event_type)
            db = self._require_db()
            try:
                await db.execute(
                    """INSERT INTO events
                       (received_at, delivery_id, repo, event_type, action, sender, payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.received_at.isoformat(),
                        event.delivery_id,
                        event.repo,
                        event.event_type,
                        event.action,
                        event.sender,
                        json.dumps(event.payload),
                    ),
                )
                await db.commit()
                span.set_attribute("event.stored", True)
                return True
            except aiosqlite.IntegrityError:
                logger.debug("Duplicate event ignored: %s", event.delivery_id)
                span.set_attribute("event.stored", False)
                span.set_attribute("event.duplicate", True)
                return False

    async def get_events(
        self,
        repo: str | None = None,
        event_type: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        sender: str | None = None,
    ) -> list[WebhookEvent]:
        """Query stored events with optional filters.

        Args:
            repo: Substring match on repository full name.
            event_type: Exact match on the GitHub event type.
            action: Exact match on the event action.
            since: Only return events received at or after this timestamp.
            sender: Exact match on the sender login.

        Returns:
            Matching events ordered by ``received_at`` descending.
        """
        tracer = _get_tracer()
        with tracer.start_as_current_span("eventstore.get_events") as span:
            span.set_attribute("db.system", "sqlite")
            span.set_attribute("db.operation", "SELECT")

            clauses: list[str] = []
            params: list[str] = []

            if repo:
                escaped = repo.replace("%", "\\%").replace("_", "\\_")
                clauses.append("repo LIKE ? ESCAPE '\\'")
                params.append(f"%{escaped}%")
            if event_type:
                clauses.append("event_type = ?")
                params.append(event_type)
            if action:
                clauses.append("action = ?")
                params.append(action)
            if since:
                clauses.append("received_at >= ?")
                params.append(since.isoformat())
            if sender:
                clauses.append("sender = ?")
                params.append(sender)

            where = " AND ".join(clauses) if clauses else "1=1"
            query = f"SELECT * FROM events WHERE {where} ORDER BY received_at DESC"

            db = self._require_db()
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            results = [
                WebhookEvent(
                    id=row["id"],
                    received_at=datetime.fromisoformat(row["received_at"]),
                    delivery_id=row["delivery_id"],
                    repo=row["repo"],
                    event_type=row["event_type"],
                    action=row["action"],
                    sender=row["sender"],
                    payload=json.loads(row["payload"]),
                )
                for row in rows
            ]
            span.set_attribute("db.result_count", len(results))
            return results

    async def prune(self, days: int = 7) -> int:
        """Delete events older than *days* days.

        Args:
            days: Retention window in days.

        Returns:
            The number of deleted rows.
        """
        db = self._require_db()
        cursor = await db.execute(
            "DELETE FROM events WHERE received_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        await db.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Pruned %d events older than %d days", deleted, days)
        return deleted

    async def close(self) -> None:
        """Close the database connection if open."""
        if self.db:
            await self.db.close()
