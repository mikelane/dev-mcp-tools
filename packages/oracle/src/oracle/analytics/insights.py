"""InsightsGenerator — produces actionable recommendations from analytics data."""

from __future__ import annotations

from collections import Counter

from mcp_shared.telemetry import get_tracer

from oracle.storage.store import OracleStore

_tracer = get_tracer("oracle.analytics.insights")


class InsightsGenerator:
    """Queries accumulated analytics for actionable agent behavior insights."""

    def __init__(self, store: OracleStore) -> None:
        self._store = store

    def top_file_pairs(self, limit: int = 5) -> list[dict[str, object]]:
        """Return the most frequently co-accessed file pairs."""
        with _tracer.start_as_current_span("insights.top_file_pairs"):
            return self._store.get_top_coaccess_pairs(limit=limit)

    def frequently_reread_files(
        self, min_reads: int = 3, session_id: str | None = None
    ) -> list[dict[str, object]]:
        """Find files read >= min_reads times."""
        with _tracer.start_as_current_span("insights.frequently_reread"):
            return self._store.get_frequently_reread_files(
                min_reads=min_reads, session_id=session_id
            )

    def average_cache_hit_rate(self) -> float:
        """Compute average cache hit rate across all session profiles."""
        with _tracer.start_as_current_span("insights.cache_hit_rate"):
            return self._store.get_average_cache_hit_rate()

    def common_tool_sequences(
        self, window_size: int = 3, min_occurrences: int = 2
    ) -> list[dict[str, object]]:
        """Find repeated tool-call patterns of the given window size."""
        with _tracer.start_as_current_span("insights.common_sequences"):
            session_ids = self._store.get_distinct_session_ids()

            pattern_counter: Counter[tuple[str, ...]] = Counter()
            for session_id in session_ids:
                rows = self._store.get_tool_sequences(session_id)
                tools = [str(r["tool_name"]) for r in rows]
                for i in range(len(tools) - window_size + 1):
                    pattern = tuple(tools[i : i + window_size])
                    pattern_counter[pattern] += 1

            return [
                {"sequence": list(pattern), "count": count}
                for pattern, count in pattern_counter.most_common()
                if count >= min_occurrences
            ]
