"""Tests for mcp_shared.storage_base."""

from pathlib import Path

from mcp_shared.storage_base import SQLiteBase


class TestSQLiteBase:
    def test_creates_db_file_with_wal_mode(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "test.db"
        with SQLiteBase(db_path) as base:
            row = base._conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0] == "wal"
        assert db_path.exists()

    def test_context_manager_closes_connection(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        with SQLiteBase(db_path) as base:
            conn = base._conn
        # After exiting context, the connection should be closed.
        # Attempting to use it raises ProgrammingError.
        import sqlite3

        try:
            conn.execute("SELECT 1")
            closed = False
        except sqlite3.ProgrammingError:
            closed = True
        assert closed

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = tmp_path / "a" / "b" / "c" / "test.db"
        with SQLiteBase(db_path):
            pass
        assert db_path.parent.exists()
