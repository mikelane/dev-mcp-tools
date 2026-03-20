"""Tests for mcp_shared.git_helpers."""

from unittest.mock import patch

from mcp_shared.git_helpers import get_remote_url


class TestGetRemoteUrl:
    def test_ssh_url_normalized(self, tmp_path: object) -> None:
        with patch(
            "mcp_shared.git_helpers.git_cmd",
            return_value="git@github.com:owner/repo.git\n",
        ):
            result = get_remote_url(tmp_path)  # type: ignore[arg-type]
        assert result == "owner/repo"

    def test_https_url_normalized(self, tmp_path: object) -> None:
        with patch(
            "mcp_shared.git_helpers.git_cmd",
            return_value="https://github.com/owner/repo.git\n",
        ):
            result = get_remote_url(tmp_path)  # type: ignore[arg-type]
        assert result == "owner/repo"

    def test_https_url_without_dot_git(self, tmp_path: object) -> None:
        with patch(
            "mcp_shared.git_helpers.git_cmd",
            return_value="https://github.com/owner/repo\n",
        ):
            result = get_remote_url(tmp_path)  # type: ignore[arg-type]
        assert result == "owner/repo"

    def test_returns_none_on_empty(self, tmp_path: object) -> None:
        with patch("mcp_shared.git_helpers.git_cmd", return_value=""):
            result = get_remote_url(tmp_path)  # type: ignore[arg-type]
        assert result is None

    def test_ssh_url_without_dot_git(self, tmp_path: object) -> None:
        with patch("mcp_shared.git_helpers.git_cmd", return_value="git@github.com:owner/repo\n"):
            result = get_remote_url(tmp_path)  # type: ignore[arg-type]
        assert result == "owner/repo"
