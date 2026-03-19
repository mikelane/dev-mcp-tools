from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from github_webhook_mcp.reactor import PRReactor

AUTO_REVIEW_REPO = "SayMoreAI/saymore"


@pytest.fixture
def reactor() -> PRReactor:
    return PRReactor(
        auto_review_repo=AUTO_REVIEW_REPO,
        debounce_seconds=900,
        repo_path="/tmp/fake-saymore",
    )


@pytest.fixture
def fast_reactor() -> PRReactor:
    """Reactor with 0s debounce for testing."""
    return PRReactor(
        auto_review_repo=AUTO_REVIEW_REPO,
        debounce_seconds=0,
        repo_path="/tmp/fake-saymore",
    )


@pytest.mark.asyncio
async def test_opened_pr_triggers_immediate_review(reactor: PRReactor) -> None:
    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event(AUTO_REVIEW_REPO, 42, "opened")

        mock.assert_called_once_with(AUTO_REVIEW_REPO, 42)


@pytest.mark.asyncio
async def test_synchronize_debounces_review(fast_reactor: PRReactor) -> None:
    with patch.object(fast_reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")

        mock.assert_not_called()

        await asyncio.sleep(0.05)

        mock.assert_called_once_with(AUTO_REVIEW_REPO, 10)


@pytest.mark.asyncio
async def test_rapid_pushes_reset_timer(fast_reactor: PRReactor) -> None:
    with patch.object(fast_reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")
        await fast_reactor.on_pr_event(AUTO_REVIEW_REPO, 10, "synchronize")

        await asyncio.sleep(0.05)

        mock.assert_called_once_with(AUTO_REVIEW_REPO, 10)


@pytest.mark.asyncio
async def test_ignores_non_saymore_repos(reactor: PRReactor) -> None:
    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event("mikelane/pytest-gremlins", 5, "opened")
        await reactor.on_pr_event("mikelane/SaunaProtocol", 3, "opened")

        mock.assert_not_called()


@pytest.mark.asyncio
async def test_unrecognized_action_does_nothing(reactor: PRReactor) -> None:
    with patch.object(reactor, "_spawn_review", new_callable=AsyncMock) as mock:
        await reactor.on_pr_event(AUTO_REVIEW_REPO, 42, "closed")
        await reactor.on_pr_event(AUTO_REVIEW_REPO, 42, "reopened")

        mock.assert_not_called()
        assert len(reactor._timers) == 0


@pytest.mark.asyncio
async def test_spawn_review_success_logs_complete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="github_webhook_mcp.reactor")
    reactor = PRReactor(repo_path="/tmp/fake-saymore")

    mock_review_process = AsyncMock()
    mock_review_process.communicate = AsyncMock(return_value=(b"output", b""))
    mock_review_process.returncode = 0

    with patch(
        "asyncio.create_subprocess_exec", return_value=mock_review_process
    ) as mock_exec:
        await reactor._spawn_review(AUTO_REVIEW_REPO, 42)

        mock_exec.assert_called_once_with(
            "claude",
            "-p",
            "/review-pr 42",
            "--cwd",
            "/tmp/fake-saymore",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    assert "Review complete for SayMoreAI/saymore#42" in caplog.text
    assert "Review failed" not in caplog.text


@pytest.mark.asyncio
async def test_spawn_review_failure_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="github_webhook_mcp.reactor")
    reactor = PRReactor(repo_path="/tmp/fake-saymore")

    mock_review_process = AsyncMock()
    mock_review_process.communicate = AsyncMock(return_value=(b"", b"error details"))
    mock_review_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_review_process):
        await reactor._spawn_review(AUTO_REVIEW_REPO, 42)

    assert "Review failed for SayMoreAI/saymore#42 (exit 1)" in caplog.text
    assert "error details" in caplog.text
    assert "Review complete" not in caplog.text


@pytest.mark.asyncio
async def test_spawn_review_claude_not_found(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="github_webhook_mcp.reactor")
    reactor = PRReactor(repo_path="/tmp/fake-saymore")

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        await reactor._spawn_review(AUTO_REVIEW_REPO, 42)

    assert "claude CLI not found" in caplog.text


@pytest.mark.asyncio
async def test_spawn_review_clears_timer() -> None:
    reactor = PRReactor(repo_path="/tmp/fake-saymore")
    timer_key = f"{AUTO_REVIEW_REPO}:42"
    reactor._timers[timer_key] = MagicMock()

    mock_review_process = AsyncMock()
    mock_review_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_review_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_review_process):
        await reactor._spawn_review(AUTO_REVIEW_REPO, 42)

    assert timer_key not in reactor._timers
