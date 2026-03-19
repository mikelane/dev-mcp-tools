"""Tests for oracle_insights tool handler."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.storage.store import OracleStore
from oracle.tools.insights import handle_oracle_insights


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    s = OracleStore(tmp_path / "oracle.db")
    yield s
    s.close()


@pytest.mark.medium
class DescribeOracleInsightsTool:
    def it_returns_formatted_insights(self, store: OracleStore) -> None:
        store.upsert_file_coaccess("server.py", "test_server.py", 1000.0)
        store.upsert_file_coaccess("server.py", "test_server.py", 2000.0)
        store.log_interaction("s1", "oracle_read", "config.py", True, 100, 1000)
        store.log_interaction("s1", "oracle_read", "config.py", True, 100, 1001)
        store.log_interaction("s1", "oracle_read", "config.py", True, 100, 1002)
        store.upsert_session_profile("s1", 1000.0, 1002.0, "{}", 1, 0.8)
        result = handle_oracle_insights(store)
        assert "File pairs" in result
        assert "server.py" in result
        assert "test_server.py" in result
        assert "config.py" in result
        assert "Cache hit rate" in result

    def it_handles_empty_data(self, store: OracleStore) -> None:
        result = handle_oracle_insights(store)
        assert "No analytics data" in result
