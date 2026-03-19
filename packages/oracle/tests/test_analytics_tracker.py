"""Tests for AnalyticsTracker."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.analytics.tracker import AnalyticsTracker
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    s = OracleStore(tmp_path / "oracle.db")
    yield s
    s.close()


@pytest.fixture
def tracker(store: OracleStore) -> AnalyticsTracker:
    return AnalyticsTracker(store, session_id="test-sess")


@pytest.mark.medium
class DescribeSequenceTracking:
    def it_records_first_tool_call_at_index_zero(
        self, tracker: AnalyticsTracker, store: OracleStore
    ) -> None:
        tracker.record("oracle_read", "/src/main.py")
        rows = store.get_tool_sequences("test-sess")
        assert len(rows) == 1
        assert rows[0]["sequence_index"] == 0
        assert rows[0]["tool_name"] == "oracle_read"

    def it_increments_sequence_index(self, tracker: AnalyticsTracker, store: OracleStore) -> None:
        tracker.record("oracle_read", "a.py")
        tracker.record("oracle_run", "pytest")
        tracker.record("oracle_read", "b.py")
        rows = store.get_tool_sequences("test-sess")
        assert [r["sequence_index"] for r in rows] == [0, 1, 2]

    def it_truncates_long_input_summary(
        self, tracker: AnalyticsTracker, store: OracleStore
    ) -> None:
        long_path = "/very/long/path/" + "x" * 300
        tracker.record("oracle_read", long_path)
        rows = store.get_tool_sequences("test-sess")
        assert len(rows[0]["input_summary"]) <= 200


@pytest.mark.medium
class DescribeCoaccessTracking:
    def it_records_no_pairs_on_first_read(
        self, tracker: AnalyticsTracker, store: OracleStore
    ) -> None:
        tracker.record("oracle_read", "a.py")
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 0

    def it_records_one_pair_on_second_read(
        self, tracker: AnalyticsTracker, store: OracleStore
    ) -> None:
        tracker.record("oracle_read", "a.py")
        tracker.record("oracle_read", "b.py")
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 1
        assert pairs[0]["file_a"] == "a.py"
        assert pairs[0]["file_b"] == "b.py"

    def it_records_three_pairs_on_third_read(
        self, tracker: AnalyticsTracker, store: OracleStore
    ) -> None:
        tracker.record("oracle_read", "a.py")
        tracker.record("oracle_read", "b.py")
        tracker.record("oracle_read", "c.py")
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 3

    def it_ignores_non_read_tools(self, tracker: AnalyticsTracker, store: OracleStore) -> None:
        tracker.record("oracle_read", "a.py")
        tracker.record("oracle_run", "pytest")
        tracker.record("oracle_read", "b.py")
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 1

    def it_does_not_duplicate_file_in_seen_set(
        self, tracker: AnalyticsTracker, store: OracleStore
    ) -> None:
        tracker.record("oracle_read", "a.py")
        tracker.record("oracle_read", "a.py")
        tracker.record("oracle_read", "b.py")
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 1
