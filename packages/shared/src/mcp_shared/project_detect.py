"""Project root detection and stack detection — shared utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_MARKERS = (".git", "package.json", "pyproject.toml", "go.mod", "Cargo.toml")


@dataclass(frozen=True)
class StackInfo:
    """Detected language stack and tooling for a project."""

    lang: str
    pkg_mgr: str | None = None
    test_cmd: str | None = None
    lint_cmd: str | None = None
    type_cmd: str | None = None


def detect_stack(root: Path) -> StackInfo:
    """Detect the language stack and package manager for a project root."""
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        pkg_mgr = "pip"
        if (root / "uv.lock").exists():
            pkg_mgr = "uv"
        elif (root / "poetry.lock").exists():
            pkg_mgr = "poetry"
        return StackInfo(lang="python", pkg_mgr=pkg_mgr)
    if (root / "package.json").exists():
        pkg_mgr = "npm"
        if (root / "pnpm-lock.yaml").exists():
            pkg_mgr = "pnpm"
        elif (root / "yarn.lock").exists():
            pkg_mgr = "yarn"
        return StackInfo(lang="node", pkg_mgr=pkg_mgr)
    if (root / "go.mod").exists():
        return StackInfo(lang="go", pkg_mgr="go")
    if (root / "Cargo.toml").exists():
        return StackInfo(lang="rust", pkg_mgr="cargo")
    return StackInfo(lang="unknown")


def detect_project_root(path: Path) -> Path | None:
    """Walk up from path looking for any PROJECT_MARKER."""
    current = path if path.is_dir() else path.parent
    while True:
        for marker in PROJECT_MARKERS:
            if (current / marker).exists():
                return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
