"""Standalone brief runner — usable from GitHub Actions or the CLI.

Usage:
    python run_brief.py
    python run_brief.py --no-web-search

Reads all config from environment variables (or a local .env file):
    VENICE_API_KEY   — required
    GITHUB_TOKEN     — PAT with write access to the publish repo (optional)
    GITHUB_REPO      — e.g. robheat/cryptocatalyst-news (optional)
    CMC_API_KEY      — optional
    LUNARCRUSH_API_KEY — optional
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> int:
    web_search = "--no-web-search" not in sys.argv

    from app.services.brief import generate_brief

    log.info("Generating morning brief (web_search=%s)…", web_search)
    result = await generate_brief(web_search=web_search)

    log.info("Brief saved: %s", result["path"])
    if result.get("published_url"):
        log.info("Published: %s", result["published_url"])
        print(result["published_url"])
    else:
        log.warning("Brief not published — check GITHUB_TOKEN / GITHUB_REPO config")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
