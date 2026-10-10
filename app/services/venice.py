"""Venice API client — OpenAI-compatible with optional web search."""
from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.config import get_settings

VENICE_BASE_URL = "https://api.venice.ai/api/v1"

logger = logging.getLogger(__name__)

# Web-search-augmented completions routinely take minutes; on 2026-10-06 the
# brief call outlasted the old flat 120s timeout and the whole run failed.
# Generous read time, quick failure on connecting.
TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
# Waits before attempts 2 and 3. Timeouts, dropped connections, 429
# (Venice's "model overloaded") and 5xx are worth retrying; other 4xx aren't.
RETRY_DELAYS = (15, 45)
RETRY_STATUSES = {429, 500, 502, 503, 504}


async def _post(path: str, payload: dict) -> dict:
    """POST to Venice with retries on transient failures; returns the JSON body."""
    for attempt, delay in enumerate((*RETRY_DELAYS, None), start=1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(f"{VENICE_BASE_URL}{path}", headers=_headers(), json=payload)
            if resp.status_code in RETRY_STATUSES and delay is not None:
                logger.warning("Venice %s returned %s (attempt %d); retrying in %ss", path, resp.status_code, attempt, delay)
            else:
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if delay is None:
                raise
            logger.warning("Venice %s failed with %s (attempt %d); retrying in %ss", path, type(exc).__name__, attempt, delay)
        await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.venice_api_key}",
        "Content-Type": "application/json",
    }


async def chat_complete(
    messages: list[dict],
    *,
    model: str | None = None,
    web_search: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    reasoning_effort: str | None = None,
) -> str:
    """Send a chat completion request and return the assistant message content.

    reasoning_effort ("none" | "low" | "medium" | "high"): how much a reasoning
    model thinks first. Thinking counts against max_tokens, and models differ
    in their default (GPT-6 Luna defaults to high): on 2026-10-10 Luna's
    default thinking used the brief's whole 3,000-token budget and returned no
    text. Set it explicitly on every call that matters.
    """
    settings = get_settings()
    payload: dict = {
        "model": model or settings.venice_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if web_search:
        payload["venice_parameters"] = {"enable_web_search": "on"}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    data = await _post("/chat/completions", payload)
    choice = data["choices"][0]
    content = choice["message"].get("content")
    if not content:
        # An empty reply is a failure, not an empty brief.
        raise RuntimeError(
            f"Venice returned no text (finish_reason={choice.get('finish_reason')}, "
            f"usage={data.get('usage')})"
        )
    return content


async def generate_image(
    prompt: str,
    *,
    model: str = "chroma",
    width: int = 1280,
    height: int = 720,
) -> bytes:
    """Generate an image via Venice image API. Returns raw WebP bytes.

    WebP instead of PNG — same visual quality tier, a fraction of the file
    size, which is what actually drives storage/bandwidth cost per brief.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "width": width,
        "height": height,
        "format": "webp",
        "hide_watermark": True,
        "return_binary": False,
    }
    data = await _post("/image/generate", payload)
    return base64.b64decode(data["images"][0])


async def list_models() -> list[dict]:
    """Return available Venice models."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{VENICE_BASE_URL}/models",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
