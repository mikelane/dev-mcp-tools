"""Shell wrappers for git commands — shared utilities."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def git_cmd(args: list[str], cwd: Path) -> str:
    """Run git command, return stdout. Empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        logger.warning("git command failed: %s", args, exc_info=True)
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def get_remote_url(cwd: Path) -> str | None:
    """Return normalized 'owner/repo' from git remote origin, or None."""
    url = git_cmd(["config", "--get", "remote.origin.url"], cwd=cwd).strip()
    if not url:
        return None
    # Handle SSH: git@github.com:owner/repo.git
    if url.startswith("git@"):
        path = url.split(":", 1)[1] if ":" in url else ""
        return path.removesuffix(".git")
    # Handle HTTPS: https://github.com/owner/repo.git
    parsed = urlparse(url)
    path = parsed.path.strip("/").removesuffix(".git")
    return path if "/" in path else None
