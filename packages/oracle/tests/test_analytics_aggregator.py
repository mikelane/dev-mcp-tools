"""Tests for SessionAggregator."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.analytics.aggregator import SessionAggregator
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    s = OracleStore(tmp_path / "oracle.db")
    yield s
    s.close()


@pytest.fixture
def aggregator(store: OracleStore) -> SessionAggregator:
    return SessionAggregator(store)


@pytest.mark.medium
class DescribeSessionAggregation:
    def it_computes_profile_from_agent_log(
        self, aggregator: SessionAggregator, store: OracleStore
    ) -> None:
        store.log_interaction("sess-1", "oracle_read", "a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "b.py", False, 0, 1001)
        store.log_interaction("sess-1", "oracle_run", "pytest", True, 200, 1002)
        aggregator.finalize_session("sess-1")
        profile = store.get_session_profile("sess-1")
        assert profile is not None
        tool_counts = json.loads(profile["tool_counts"])
        assert tool_counts == {"oracle_read": 2, "oracle_run": 1}
        assert profile["files_touched"] == 2
        assert profile["cache_hit_rate"] == pytest.approx(2 / 3)

    def it_handles_session_with_no_cache_hits(
        self, aggregator: SessionAggregator, store: OracleStore
    ) -> None:
        store.log_interaction("sess-2", "oracle_read", "a.py", False, 0, 1000)
        store.log_interaction("sess-2", "oracle_read", "b.py", False, 0, 1001)
        aggregator.finalize_session("sess-2")
        profile = store.get_session_profile("sess-2")
        assert profile is not None
        assert profile["cache_hit_rate"] == pytest.approx(0.0)

    def it_handles_empty_session(
        self, aggregator: SessionAggregator, store: OracleStore
    ) -> None:
        aggregator.finalize_session("nonexistent")
        profile = store.get_session_profile("nonexistent")
        assert profile is None

    def it_counts_unique_file_paths(
        self, aggregator: SessionAggregator, store: OracleStore
    ) -> None:
        store.log_interaction("sess-3", "oracle_read", "a.py", True, 100, 1000)
        store.log_interaction("sess-3", "oracle_read", "a.py", True, 100, 1001)
        store.log_interaction("sess-3", "oracle_read", "b.py", False, 0, 1002)
        aggregator.finalize_session("sess-3")
        profile = store.get_session_profile("sess-3")
        assert profile is not None
        assert profile["files_touched"] == 2
