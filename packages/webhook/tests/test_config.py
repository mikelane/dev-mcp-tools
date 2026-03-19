from __future__ import annotations

from pathlib import Path

import pytest
from github_webhook_mcp.config import Settings
from pydantic import ValidationError


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMEE_CHANNEL_URL", "https://smee.io/test123")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "testsecret")

    settings = Settings()

    assert settings.smee_channel_url == "https://smee.io/test123"
    assert settings.github_webhook_secret == "testsecret"
    assert settings.github_username == "mikelane"
    assert settings.mcp_port == 8321
    assert settings.prune_days == 7


def test_settings_requires_smee_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMEE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMEE_CHANNEL_URL", "https://smee.io/override")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("GITHUB_USERNAME", "someoneelse")
    monkeypatch.setenv("MCP_PORT", "9999")
    monkeypatch.setenv("DB_PATH", "/tmp/custom.db")
    monkeypatch.setenv("PRUNE_DAYS", "30")

    settings = Settings()

    assert settings.github_username == "someoneelse"
    assert settings.mcp_port == 9999
    assert settings.db_path == "/tmp/custom.db"
    assert settings.prune_days == 30


def test_resolved_db_path_expands_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMEE_CHANNEL_URL", "https://smee.io/test")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("DB_PATH", "~/my-data/events.db")

    settings = Settings()

    resolved = settings.resolved_db_path
    assert isinstance(resolved, Path)
    assert "~" not in str(resolved)
    assert str(resolved).endswith("my-data/events.db")
