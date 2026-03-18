"""SQLiteBase — reusable SQLite connection boilerplate."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Self


class SQLiteBase:
    """Base class providing SQLite connection setup with WAL mode."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()
