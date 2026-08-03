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


