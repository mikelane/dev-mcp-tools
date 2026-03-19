"""Tool handler for oracle_insights — actionable agent behavior analytics."""

from __future__ import annotations

from oracle.analytics.insights import InsightsGenerator
from oracle.storage.store import OracleStore


def handle_oracle_insights(store: OracleStore) -> str:
    """Return formatted analytics insights."""
    gen = InsightsGenerator(store)

    sections: list[str] = []

    pairs = gen.top_file_pairs(limit=5)
    if pairs:
        lines = ["File pairs (always read together):"]
        lines.extend(
            f"  {p['file_a']} ↔ {p['file_b']}  ({p['session_count']} sessions)" for p in pairs
        )
        sections.append("\n".join(lines))

    rereads = gen.frequently_reread_files(min_reads=3)
    if rereads:
        lines = ["Frequently re-read files (consider pinning):"]
        for r in rereads:
            lines.append(f"  {r['path']}  ({r['read_count']} reads)")
        sections.append("\n".join(lines))

    rate = gen.average_cache_hit_rate()
    if rate > 0:
        sections.append(f"Cache hit rate: {rate:.0%} (average across sessions)")

    sequences = gen.common_tool_sequences(window_size=3, min_occurrences=2)
    if sequences:
        lines = ["Common tool patterns:"]
        for s in sequences[:5]:
            arrow = " → ".join(s["sequence"])
            lines.append(f"  {arrow}  ({s['count']}x)")
        sections.append("\n".join(lines))

    if not sections:
        return "No analytics data yet. Use Oracle tools for a few sessions to build up patterns."

    return "\n\n".join(sections)
