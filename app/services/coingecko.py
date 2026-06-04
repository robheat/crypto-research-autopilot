"""CoinGecko free-tier client — no API key required."""
from __future__ import annotations

import httpx
from typing import Any

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# CoinGecko free tier rate limit is ~30 req/min; use a single shared client.
_HEADERS = {"accept": "application/json"}


async def get_global_market() -> dict[str, Any]:
    """Global crypto market stats: total cap, dominance, volume."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{COINGECKO_BASE}/global", headers=_HEADERS)
        resp.raise_for_status()
        return resp.json().get("data", {})


async def get_trending() -> list[dict]:
    """Top-7 trending coins by CoinGecko search volume (last 24h)."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{COINGECKO_BASE}/search/trending", headers=_HEADERS)
        resp.raise_for_status()
        return resp.json().get("coins", [])


async def get_prices(coin_ids: list[str]) -> dict[str, Any]:
    """Price, 24h change, and volume for a list of CoinGecko coin IDs."""
    if not coin_ids:
        return {}
    ids_param = ",".join(coin_ids)
    params = {
        "ids": ids_param,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/simple/price", headers=_HEADERS, params=params
        )
        resp.raise_for_status()
        return resp.json()


async def search_coin(query: str) -> list[dict]:
    """Search CoinGecko for a coin by name or symbol; returns list of matches."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/search",
            headers=_HEADERS,
            params={"query": query},
        )
        resp.raise_for_status()
        return resp.json().get("coins", [])[:5]


async def get_coin_detail(coin_id: str) -> dict[str, Any]:
    """Detailed data for a single coin: description, market data, links."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/coins/{coin_id}",
            headers=_HEADERS,
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            },
        )
        resp.raise_for_status()
        return resp.json()
