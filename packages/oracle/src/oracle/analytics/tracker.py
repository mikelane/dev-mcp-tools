"""AnalyticsTracker — records tool sequences and file co-access patterns."""

from __future__ import annotations

import time

from mcp_shared.telemetry import get_tracer

from oracle.storage.store import OracleStore

_MAX_INPUT_SUMMARY = 200
_tracer = get_tracer("oracle.analytics.tracker")


class AnalyticsTracker:
    """Tracks tool call sequences and file co-access within a session."""

    def __init__(self, store: OracleStore, session_id: str) -> None:
        self._store = store
        self._session_id = session_id
        self._sequence_index = 0
        self._files_seen: set[str] = set()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def files_seen(self) -> frozenset[str]:
        return frozenset(self._files_seen)

    def record(self, tool_name: str, input_summary: str | None) -> None:
        """Record a tool call — updates sequence and co-access tables."""
        with _tracer.start_as_current_span("analytics.record") as span:
            span.set_attribute("tool_name", tool_name)
            truncated = input_summary[:_MAX_INPUT_SUMMARY] if input_summary else None
            self._store.record_tool_sequence(
                self._session_id,
                self._sequence_index,
                tool_name,
                truncated,
                time.time(),
            )
            self._sequence_index += 1

            if tool_name == "oracle_read" and input_summary:
                self._record_coaccess(input_summary)

    def _record_coaccess(self, file_path: str) -> None:
        """Record co-access pairs between this file and all previously seen files."""
        if file_path in self._files_seen:
            return
        now = time.time()
        for seen in self._files_seen:
            self._store.upsert_file_coaccess(seen, file_path, now)
        self._files_seen.add(file_path)
