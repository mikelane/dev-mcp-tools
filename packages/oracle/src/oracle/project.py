"""Project root detection and stack detection for Project Oracle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_shared.project_detect import StackInfo, detect_project_root, detect_stack

if TYPE_CHECKING:
    from oracle.cache.command_cache import CommandCache
    from oracle.cache.file_cache import FileCache
    from oracle.cache.git_cache import GitCache
    from oracle.integrations.chunkhound import ChunkhoundClient
    from oracle.storage.store import OracleStore

# Re-export so existing `from oracle.project import ...` still works.
__all__ = [
    "ProjectState",
    "StackInfo",
    "detect_project_root",
    "detect_stack",
]


@dataclass
class ProjectState:
    """Mutable state for a detected project."""

    root: Path
    stack: StackInfo
    project_id: str = ""
    store: OracleStore | None = None
    file_cache: FileCache | None = None
    git_cache: GitCache | None = None
    command_cache: CommandCache | None = None
    chunkhound: ChunkhoundClient | None = None
    chunkhound_failed: bool = False
    session_id: str = ""
