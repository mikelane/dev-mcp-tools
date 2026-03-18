"""PR reactor that auto-triggers Claude Code reviews on webhook events."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

AUTO_REVIEW_REPO = "SayMoreAI/saymore"
DEFAULT_DEBOUNCE_SECONDS = 900  # 15 minutes


class PRReactor:
    """React to pull-request webhook events by spawning automated reviews.

    When a PR is opened on the configured repository, a review is triggered
    immediately.  When new commits are pushed (``synchronize``), the review
    is debounced so that rapid successive pushes result in a single review.
    """

    def __init__(
        self,
        auto_review_repo: str = AUTO_REVIEW_REPO,
        debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
        repo_path: str = "~/dev/saymore",
    ) -> None:
        self.auto_review_repo = auto_review_repo
        self.debounce_seconds = debounce_seconds
        self.repo_path = repo_path
        self._timers: dict[str, asyncio.TimerHandle] = {}

    async def on_pr_event(self, repo: str, pr_number: int, action: str) -> None:
        """Handle an incoming pull-request webhook event.

        Args:
            repo: The full repository name (``owner/repo``).
            pr_number: The pull-request number.
            action: The webhook action (e.g. ``"opened"``, ``"synchronize"``).
        """
        if repo != self.auto_review_repo:
            return

        timer_key = f"{repo}:{pr_number}"

        if action == "opened":
            self._cancel_timer(timer_key)
            await self._spawn_review(repo, pr_number)
        elif action == "synchronize":
            self._cancel_timer(timer_key)
            loop = asyncio.get_running_loop()
            self._timers[timer_key] = loop.call_later(
                self.debounce_seconds,
                lambda: asyncio.ensure_future(self._spawn_review(repo, pr_number)),
            )
            logger.info(
                "PR %s#%d pushed — review scheduled in %ds",
                repo, pr_number, self.debounce_seconds,
            )

    def _cancel_timer(self, timer_key: str) -> None:
        """Cancel a pending debounce timer, if one exists for *timer_key*."""
        timer = self._timers.pop(timer_key, None)
        if timer is not None:
            timer.cancel()

    async def _spawn_review(self, repo: str, pr_number: int) -> None:
        """Spawn a ``claude`` CLI process to review the given PR.

        Args:
            repo: The full repository name (``owner/repo``).
            pr_number: The pull-request number to review.
        """
        self._timers.pop(f"{repo}:{pr_number}", None)
        logger.info("Spawning review for %s#%d", repo, pr_number)
        try:
            review_process = await asyncio.create_subprocess_exec(
                "claude", "-p", f"/review-pr {pr_number}",
                "--cwd", self.repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await review_process.communicate()
            if review_process.returncode == 0:
                logger.info("Review complete for %s#%d", repo, pr_number)
            else:
                logger.warning(
                    "Review failed for %s#%d (exit %d): %s",
                    repo, pr_number, review_process.returncode,
                    stderr.decode()[:500],
                )
        except FileNotFoundError:
            logger.error("claude CLI not found — cannot spawn review")
