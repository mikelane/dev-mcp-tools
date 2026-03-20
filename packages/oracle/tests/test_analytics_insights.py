"""Tests for InsightsGenerator."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from oracle.analytics.insights import InsightsGenerator
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    s = OracleStore(tmp_path / "oracle.db")
    yield s
    s.close()


@pytest.fixture
def insights(store: OracleStore) -> InsightsGenerator:
    return InsightsGenerator(store)


@pytest.mark.medium
class DescribeFilePairInsights:
    def it_returns_top_file_pairs(self, insights: InsightsGenerator, store: OracleStore) -> None:
        store.upsert_file_coaccess("server.py", "test_server.py", 1000.0)
        store.upsert_file_coaccess("server.py", "test_server.py", 2000.0)
        store.upsert_file_coaccess("models.py", "test_models.py", 1000.0)
        result = insights.top_file_pairs(limit=5)
        assert len(result) == 2
        assert result[0]["file_a"] == "server.py"
        assert result[0]["session_count"] == 2

    def it_returns_empty_list_when_no_data(self, insights: InsightsGenerator) -> None:
        assert insights.top_file_pairs(limit=5) == []


@pytest.mark.medium
class DescribeFrequentRereadInsights:
    def it_identifies_files_read_multiple_times(
        self, insights: InsightsGenerator, store: OracleStore
    ) -> None:
        store.log_interaction("s1", "oracle_read", "config.py", True, 100, 1000)
        store.log_interaction("s1", "oracle_read", "config.py", True, 100, 1001)
        store.log_interaction("s1", "oracle_read", "config.py", True, 100, 1002)
        store.log_interaction("s1", "oracle_read", "other.py", False, 0, 1003)
        result = insights.frequently_reread_files(min_reads=3)
        assert len(result) == 1
        assert result[0]["path"] == "config.py"
        assert result[0]["read_count"] == 3


@pytest.mark.medium
class DescribeCacheHitTrend:
    def it_computes_average_cache_hit_rate(
        self, insights: InsightsGenerator, store: OracleStore
    ) -> None:
        store.upsert_session_profile("s1", 100.0, 200.0, "{}", 3, 0.6)
        store.upsert_session_profile("s2", 300.0, 400.0, "{}", 5, 0.8)
        rate = insights.average_cache_hit_rate()
        assert rate == pytest.approx(0.7)

    def it_returns_zero_when_no_sessions(self, insights: InsightsGenerator) -> None:
        assert insights.average_cache_hit_rate() == pytest.approx(0.0)


@pytest.mark.medium
class DescribeCommonSequences:
    def it_finds_repeated_tool_patterns(
        self, insights: InsightsGenerator, store: OracleStore
    ) -> None:
        store.record_tool_sequence("s1", 0, "oracle_read", "a.py", 1000.0)
        store.record_tool_sequence("s1", 1, "oracle_run", "pytest", 1001.0)
        store.record_tool_sequence("s1", 2, "oracle_read", "b.py", 1002.0)
        store.record_tool_sequence("s2", 0, "oracle_read", "a.py", 2000.0)
        store.record_tool_sequence("s2", 1, "oracle_run", "pytest", 2001.0)
        store.record_tool_sequence("s2", 2, "oracle_read", "b.py", 2002.0)
        result = insights.common_tool_sequences(window_size=3, min_occurrences=2)
        assert len(result) >= 1
        assert result[0]["sequence"] == ["oracle_read", "oracle_run", "oracle_read"]
        assert result[0]["count"] == 2
