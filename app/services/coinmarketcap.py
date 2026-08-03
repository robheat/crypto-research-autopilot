"""CoinMarketCap client — gracefully disabled when CMC_API_KEY is not set."""
from __future__ import annotations

import httpx
from typing import Any

CMC_BASE = "https://pro-api.coinmarketcap.com/v1"


def _headers(api_key: str) -> dict[str, str]:
    return {"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}


async def get_fear_and_greed(api_key: str) -> dict[str, Any] | None:
    """Return the latest Fear & Greed index value and classification."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {"value": data.get("value"), "sentiment": data.get("value_classification")}
    except Exception:
        return None


async def get_global_metrics(api_key: str) -> dict[str, Any] | None:
    """BTC dominance, ETH dominance, total market cap, total volume."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{CMC_BASE}/global-metrics/quotes/latest",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            quote = resp.json().get("data", {}).get("quote", {}).get("USD", {})
            return {
                "btc_dominance": resp.json()["data"].get("btc_dominance"),
                "eth_dominance": resp.json()["data"].get("eth_dominance"),
                "total_market_cap": quote.get("total_market_cap"),
                "total_volume_24h": quote.get("total_volume_24h"),
            }
    except Exception:
        return None


