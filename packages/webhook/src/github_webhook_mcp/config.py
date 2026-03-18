"""Application settings loaded from environment variables and .env files."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the GitHub Webhook MCP server.

    Settings are loaded from environment variables and an optional ``.env``
    file located at ``~/.config/github-webhook-mcp/.env``.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".config/github-webhook-mcp/.env"),
        env_file_encoding="utf-8",
    )

    smee_channel_url: str
    github_webhook_secret: str
    github_username: str = "mikelane"
    mcp_port: int = 8321
    db_path: str = "~/.local/share/github-webhook-mcp/events.db"
    prune_days: int = 7

    @property
    def resolved_db_path(self) -> Path:
        """Return the database path with ``~`` expanded to the user home directory."""
        return Path(self.db_path).expanduser()
