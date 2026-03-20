"""Entry point for the GitHub Webhook MCP server."""

from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .reactor import PRReactor
from .server import init_server, mcp
from .smee_client import SmeeClient
from .storage import EventStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _prune_loop(store: EventStore, days: int) -> None:
    while True:
        await store.prune(days)
        await asyncio.sleep(6 * 3600)  # every 6 hours


async def _run() -> None:
    settings = Settings()
    store = EventStore(settings.db_path)
    await store.initialize()
    await store.prune(settings.prune_days)

    init_server(store, settings.github_username)

    reactor = PRReactor(repo_path="~/dev/saymore")

    smee = SmeeClient(
        channel_url=settings.smee_channel_url,
        webhook_secret=settings.github_webhook_secret,
        store=store,
        reactor=reactor,
    )

    logger.info("Starting Smee listener for %s", settings.smee_channel_url)
    logger.info(
        "PR reactor active for %s (debounce: %ds)",
        reactor.auto_review_repo,
        reactor.debounce_seconds,
    )
    _smee_task = asyncio.create_task(smee.listen())  # noqa: RUF006
    _prune_task = asyncio.create_task(_prune_loop(store, settings.prune_days))  # noqa: RUF006

    logger.info("Starting MCP server on port %d", settings.mcp_port)
    await mcp.run_async(transport="sse", port=settings.mcp_port)


def main() -> None:
    """Launch the MCP server, Smee listener, and pruning loop."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
