"""LunarCrush client — gracefully disabled when LUNARCRUSH_API_KEY is not set."""
from __future__ import annotations

import httpx
from typing import Any

LUNARCRUSH_BASE = "https://lunarcrush.com/api4/public"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


async def get_coin_sentiment(api_key: str, symbol: str) -> dict[str, Any] | None:
    """Social sentiment, galaxy score, and alt rank for a single coin symbol."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{LUNARCRUSH_BASE}/coins/{symbol}/v1",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "symbol": symbol.upper(),
                "galaxy_score": data.get("galaxy_score"),
                "alt_rank": data.get("alt_rank"),
                "sentiment": data.get("sentiment"),
                "social_volume_24h": data.get("social_volume_24h"),
                "social_score": data.get("social_score"),
            }
    except Exception:
        return None


async def get_trending_topics(api_key: str) -> list[dict] | None:
    """Trending crypto topics/narratives by social volume."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{LUNARCRUSH_BASE}/topics/v1",
                headers=_headers(api_key),
                params={"sort": "interactions_24h", "limit": 10},
            )
            resp.raise_for_status()
            topics = resp.json().get("data", [])
            return [
                {
                    "topic": t.get("topic"),
                    "interactions_24h": t.get("interactions_24h"),
                    "posts_created_24h": t.get("posts_created_24h"),
                }
                for t in topics
            ]
    except Exception:
        return None


async def get_coins_list(api_key: str, limit: int = 20) -> list[dict] | None:
    """Top coins ranked by galaxy score (social + market momentum)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{LUNARCRUSH_BASE}/coins/list/v2",
                headers=_headers(api_key),
                params={"sort": "galaxy_score", "limit": limit},
            )
            resp.raise_for_status()
            coins = resp.json().get("data", [])
            return [
                {
                    "symbol": c.get("symbol"),
                    "name": c.get("name"),
                    "galaxy_score": c.get("galaxy_score"),
                    "alt_rank": c.get("alt_rank"),
                    "sentiment": c.get("sentiment"),
                    "change_24h": c.get("percent_change_24h"),
                }
                for c in coins
            ]
    except Exception:
        return None
