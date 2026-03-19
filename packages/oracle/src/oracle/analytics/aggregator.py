"""SessionAggregator — computes session profiles from agent_log data."""

from __future__ import annotations

import json

from mcp_shared.telemetry import get_tracer

from oracle.storage.store import OracleStore

_tracer = get_tracer("oracle.analytics.aggregator")


class SessionAggregator:
    """Aggregates agent_log rows into a session profile."""

    def __init__(self, store: OracleStore) -> None:
        self._store = store

    def finalize_session(self, session_id: str) -> None:
        """Compute and store a profile for the given session.

        No-op if the session has no logged interactions.
        """
        with _tracer.start_as_current_span("analytics.finalize_session") as span:
            span.set_attribute("session_id", session_id)
            rows = self._store.get_session_log(session_id)

            if not rows:
                return

            tool_counts: dict[str, int] = {}
            file_paths: set[str] = set()
            cache_hits = 0

            for row in rows:
                tool = row["tool_name"]
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
                if row["cache_hit"]:
                    cache_hits += 1
                if tool == "oracle_read" and row["input"]:
                    file_paths.add(row["input"])

            self._store.upsert_session_profile(
                session_id=session_id,
                started_at=float(rows[0]["ts"]),
                ended_at=float(rows[-1]["ts"]),
                tool_counts=json.dumps(tool_counts),
                files_touched=len(file_paths),
                cache_hit_rate=cache_hits / len(rows),
            )
            span.set_attribute("files_touched", len(file_paths))
            span.set_attribute("cache_hit_rate", cache_hits / len(rows))
