"""Tests for OracleStore — SQLite persistence layer."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.mark.medium
class DescribeOracleStoreInit:
    def it_creates_db_file_on_disk(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dir" / "oracle.db"
        store = OracleStore(db_path)
        try:
            assert db_path.exists()
        finally:
            store.close()

    def it_supports_context_manager(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx.db"
        with OracleStore(db_path) as store:
            store.upsert_file_cache("a.py", b"a", "h1", None, 1000)
        # Connection is closed after with-block; verify data persisted
        with OracleStore(db_path) as store:
            assert store.get_file_cache("a.py") is not None

    def it_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "oracle.db"
        store1 = OracleStore(db_path)
        store1.close()
        store2 = OracleStore(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = sorted(row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_"))
            conn.close()
            assert tables == [
                "agent_log",
                "command_results",
                "file_cache",
                "file_coaccess",
                "git_state",
                "session_profiles",
                "tool_sequences",
            ]
        finally:
            store2.close()

    def it_creates_all_tables_on_init(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "oracle.db"
        store = OracleStore(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = sorted(row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_"))
            conn.close()
            assert tables == [
                "agent_log",
                "command_results",
                "file_cache",
                "file_coaccess",
                "git_state",
                "session_profiles",
                "tool_sequences",
            ]
        finally:
            store.close()


@pytest.mark.medium
class DescribeAnalyticsTables:
    def it_creates_analytics_tables_on_init(self, tmp_path: Path) -> None:
        db_path = tmp_path / "analytics_check.db"
        store = OracleStore(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = sorted(row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_"))
            conn.close()
            assert "tool_sequences" in tables
            assert "file_coaccess" in tables
            assert "session_profiles" in tables
        finally:
            store.close()


@pytest.mark.medium
class DescribeFileCacheOperations:
    def it_upserts_and_retrieves_entries(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"print('hello')", "abc123", None, 1000)
        result = store.get_file_cache("src/main.py")
        assert result is not None
        assert result["path"] == "src/main.py"
        assert result["content"] == b"print('hello')"
        assert result["sha256"] == "abc123"
        assert result["disk_sha256"] is None
        assert result["first_seen"] == 1000
        assert result["last_read"] == 1000
        assert result["read_count"] == 1

    def it_increments_read_count_on_upsert(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"v1", "aaa", None, 1000)
        store.upsert_file_cache("src/main.py", b"v2", "bbb", None, 2000)
        result = store.get_file_cache("src/main.py")
        assert result is not None
        assert result["read_count"] == 2
        assert result["content"] == b"v2"
        assert result["sha256"] == "bbb"
        assert result["first_seen"] == 1000
        assert result["last_read"] == 2000

    def it_returns_none_for_missing_path(self, store: OracleStore) -> None:
        assert store.get_file_cache("nonexistent.py") is None

    def it_deletes_entries(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"data", "abc", None, 1000)
        store.delete_file_cache("src/main.py")
        assert store.get_file_cache("src/main.py") is None

    def it_updates_disk_sha256(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"data", "abc", None, 1000)
        updated = store.update_disk_sha256("src/main.py", "disk_hash_999")
        assert updated is True
        result = store.get_file_cache("src/main.py")
        assert result is not None
        assert result["disk_sha256"] == "disk_hash_999"

    def it_returns_false_when_updating_disk_sha256_for_missing_path(
        self, store: OracleStore
    ) -> None:
        updated = store.update_disk_sha256("nonexistent.py", "some_hash")
        assert updated is False

    def it_lists_all_cached_paths(self, store: OracleStore) -> None:
        store.upsert_file_cache("a.py", b"a", "h1", None, 1000)
        store.upsert_file_cache("b.py", b"b", "h2", None, 1000)
        store.upsert_file_cache("c.py", b"c", "h3", None, 1000)
        paths = store.all_cached_paths()
        assert sorted(paths) == ["a.py", "b.py", "c.py"]


@pytest.mark.medium
class DescribeCommandResults:
    def it_upserts_and_retrieves(self, store: OracleStore) -> None:
        store.upsert_command_result("git status", "clean", 0, "hash1", 5000)
        result = store.get_command_result("git status")
        assert result is not None
        assert result["command"] == "git status"
        assert result["output"] == "clean"
        assert result["exit_code"] == 0
        assert result["input_hash"] == "hash1"
        assert result["ran_at"] == 5000

    def it_returns_none_for_missing(self, store: OracleStore) -> None:
        assert store.get_command_result("nonexistent") is None


@pytest.mark.medium
class DescribeAgentLog:
    def it_logs_and_queries_session_stats(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "input1", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "input2", True, 300, 2000)
        stats = store.get_session_stats("sess-1")
        assert stats["total_cache_hits"] == 2
        assert stats["total_tokens_saved"] == 800

    def it_counts_only_cache_hits(self, store: OracleStore) -> None:
        store.log_interaction("sess-2", "oracle_read", "input1", True, 500, 1000)
        store.log_interaction("sess-2", "oracle_read", "input2", False, 0, 2000)
        store.log_interaction("sess-2", "oracle_run", "input3", True, 200, 3000)
        stats = store.get_session_stats("sess-2")
        assert stats["total_cache_hits"] == 2
        assert stats["total_tokens_saved"] == 700

    def it_returns_zero_stats_for_unknown_session(self, store: OracleStore) -> None:
        stats = store.get_session_stats("nonexistent-session")
        assert stats["total_cache_hits"] == 0
        assert stats["total_tokens_saved"] == 0


@pytest.mark.medium
class DescribeEviction:
    def it_evicts_files_older_than_max_age(self, store: OracleStore) -> None:
        now = 1_000_000
        old_ts = now - (31 * 86400)  # 31 days ago
        store.upsert_file_cache("old.py", b"old", "h1", None, old_ts)
        count = store.evict_stale_files(max_age_days=30, now=now)
        assert count == 1
        assert store.get_file_cache("old.py") is None

    def it_preserves_recent_files(self, store: OracleStore) -> None:
        now = 1_000_000
        recent_ts = now - (10 * 86400)  # 10 days ago
        store.upsert_file_cache("recent.py", b"new", "h2", None, recent_ts)
        count = store.evict_stale_files(max_age_days=30, now=now)
        assert count == 0
        assert store.get_file_cache("recent.py") is not None

    def it_evicts_commands_older_than_max_hours(self, store: OracleStore) -> None:
        now = 100_000
        old_ts = now - (25 * 3600)  # 25 hours ago
        store.upsert_command_result("old cmd", "out", 0, None, old_ts)
        count = store.evict_stale_commands(max_age_hours=24, now=now)
        assert count == 1
        assert store.get_command_result("old cmd") is None

    def it_evicts_stale_files_using_current_time_by_default(self, store: OracleStore) -> None:
        old_ts = int(time.time()) - (31 * 86400)
        store.upsert_file_cache("/old.py", b"old", "a", "a", old_ts)
        count = store.evict_stale_files()
        assert count == 1

    def it_evicts_stale_commands_using_current_time_by_default(self, store: OracleStore) -> None:
        old_ts = int(time.time()) - (25 * 3600)
        store.upsert_command_result("old-cmd", "out", 0, "h1", old_ts)
        count = store.evict_stale_commands()
        assert count == 1

    def it_returns_count_of_evicted_entries(self, store: OracleStore) -> None:
        now = 1_000_000
        old_ts = now - (31 * 86400)
        store.upsert_file_cache("a.py", b"a", "h1", None, old_ts)
        store.upsert_file_cache("b.py", b"b", "h2", None, old_ts)
        store.upsert_file_cache("c.py", b"c", "h3", None, now)  # recent, keep
        count = store.evict_stale_files(max_age_days=30, now=now)
        assert count == 2


@pytest.mark.medium
class DescribeToolSequences:
    def it_records_a_tool_call_in_sequence(self, store: OracleStore) -> None:
        store.record_tool_sequence("sess-1", 0, "oracle_read", "main.py", 1000.0)
        rows = store.get_tool_sequences("sess-1")
        assert len(rows) == 1
        assert rows[0]["session_id"] == "sess-1"
        assert rows[0]["sequence_index"] == 0
        assert rows[0]["tool_name"] == "oracle_read"
        assert rows[0]["input_summary"] == "main.py"
        assert rows[0]["ts"] == 1000.0

    def it_records_multiple_calls_in_order(self, store: OracleStore) -> None:
        store.record_tool_sequence("sess-1", 0, "oracle_read", "a.py", 1000.0)
        store.record_tool_sequence("sess-1", 1, "oracle_grep", "pattern", 1001.0)
        store.record_tool_sequence("sess-1", 2, "oracle_run", "git status", 1002.0)
        rows = store.get_tool_sequences("sess-1")
        assert len(rows) == 3
        assert rows[0]["tool_name"] == "oracle_read"
        assert rows[1]["tool_name"] == "oracle_grep"
        assert rows[2]["tool_name"] == "oracle_run"


@pytest.mark.medium
class DescribeFileCoaccess:
    def it_inserts_a_new_pair(self, store: OracleStore) -> None:
        store.upsert_file_coaccess("a.py", "b.py", 1000.0)
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 1
        assert pairs[0]["file_a"] == "a.py"
        assert pairs[0]["file_b"] == "b.py"
        assert pairs[0]["session_count"] == 1
        assert pairs[0]["last_seen"] == 1000.0

    def it_increments_count_on_repeat(self, store: OracleStore) -> None:
        store.upsert_file_coaccess("a.py", "b.py", 1000.0)
        store.upsert_file_coaccess("a.py", "b.py", 2000.0)
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 1
        assert pairs[0]["session_count"] == 2

    def it_enforces_alphabetical_key_order(self, store: OracleStore) -> None:
        store.upsert_file_coaccess("z.py", "a.py", 1000.0)
        pairs = store.get_top_coaccess_pairs(limit=10)
        assert len(pairs) == 1
        assert pairs[0]["file_a"] == "a.py"
        assert pairs[0]["file_b"] == "z.py"

    def it_returns_pairs_for_a_specific_file(self, store: OracleStore) -> None:
        store.upsert_file_coaccess("a.py", "b.py", 1000.0)
        store.upsert_file_coaccess("a.py", "c.py", 1001.0)
        store.upsert_file_coaccess("d.py", "e.py", 1002.0)
        pairs = store.get_coaccess_for_file("a.py")
        assert len(pairs) == 2


@pytest.mark.medium
class DescribeSessionProfiles:
    def it_upserts_a_session_profile(self, store: OracleStore) -> None:
        store.upsert_session_profile("sess-1", 1000.0, 2000.0, '{"oracle_read": 5}', 10, 0.75)
        profile = store.get_session_profile("sess-1")
        assert profile is not None
        assert profile["session_id"] == "sess-1"
        assert profile["started_at"] == 1000.0
        assert profile["ended_at"] == 2000.0
        assert profile["tool_counts"] == '{"oracle_read": 5}'
        assert profile["files_touched"] == 10
        assert profile["cache_hit_rate"] == pytest.approx(0.75)

    def it_updates_existing_profile(self, store: OracleStore) -> None:
        store.upsert_session_profile("sess-1", 1000.0, 2000.0, '{"oracle_read": 5}', 10, 0.75)
        store.upsert_session_profile("sess-1", 1000.0, 3000.0, '{"oracle_read": 8}', 15, 0.80)
        profile = store.get_session_profile("sess-1")
        assert profile is not None
        assert profile["ended_at"] == 3000.0
        assert profile["files_touched"] == 15

    def it_returns_none_for_missing_session(self, store: OracleStore) -> None:
        assert store.get_session_profile("nonexistent") is None

    def it_returns_recent_profiles(self, store: OracleStore) -> None:
        store.upsert_session_profile("sess-old", 1000.0, 2000.0, "{}", 5, 0.5)
        store.upsert_session_profile("sess-new", 3000.0, 4000.0, "{}", 8, 0.9)
        profiles = store.get_recent_session_profiles(limit=20)
        assert len(profiles) == 2
        assert profiles[0]["session_id"] == "sess-new"
        assert profiles[1]["session_id"] == "sess-old"


@pytest.mark.medium
class DescribeSessionLog:
    def it_returns_all_log_rows_for_a_session(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "a.py", True, 100, 1000)
        store.log_interaction("sess-1", "oracle_grep", "pattern", False, 0, 2000)
        store.log_interaction("sess-2", "oracle_read", "b.py", True, 50, 3000)
        rows = store.get_session_log("sess-1")
        assert len(rows) == 2
        assert rows[0]["tool_name"] == "oracle_read"
        assert rows[1]["tool_name"] == "oracle_grep"

    def it_returns_empty_list_for_unknown_session(self, store: OracleStore) -> None:
        assert store.get_session_log("nonexistent") == []

    def it_returns_distinct_session_ids(self, store: OracleStore) -> None:
        store.record_tool_sequence("sess-1", 0, "oracle_read", "a.py", 1000.0)
        store.record_tool_sequence("sess-1", 1, "oracle_grep", "pat", 1001.0)
        store.record_tool_sequence("sess-2", 0, "oracle_run", "cmd", 2000.0)
        ids = store.get_distinct_session_ids()
        assert sorted(ids) == ["sess-1", "sess-2"]


@pytest.mark.medium
class DescribeRereadQuery:
    def it_returns_files_read_above_threshold(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "config.py", True, 100, 1000)
        store.log_interaction("sess-1", "oracle_read", "config.py", True, 100, 2000)
        store.log_interaction("sess-1", "oracle_read", "config.py", True, 100, 3000)
        store.log_interaction("sess-1", "oracle_read", "other.py", False, 0, 4000)
        results = store.get_frequently_reread_files(min_reads=3)
        assert len(results) == 1
        assert results[0]["path"] == "config.py"
        assert results[0]["read_count"] == 3

    def it_returns_empty_when_no_files_above_threshold(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "once.py", False, 0, 1000)
        results = store.get_frequently_reread_files(min_reads=3)
        assert results == []


@pytest.mark.medium
class DescribeCacheHitRateQuery:
    def it_computes_average_from_session_profiles(self, store: OracleStore) -> None:
        store.upsert_session_profile("sess-1", 1000.0, 2000.0, "{}", 5, 0.6)
        store.upsert_session_profile("sess-2", 3000.0, 4000.0, "{}", 8, 0.8)
        avg = store.get_average_cache_hit_rate()
        assert avg == pytest.approx(0.7)

    def it_returns_zero_when_no_profiles(self, store: OracleStore) -> None:
        assert store.get_average_cache_hit_rate() == 0.0
