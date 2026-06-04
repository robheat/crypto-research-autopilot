"""Venice API client — OpenAI-compatible with optional web search."""
from __future__ import annotations

import base64
import httpx
from typing import AsyncIterator

from app.config import get_settings

VENICE_BASE_URL = "https://api.venice.ai/api/v1"


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
) -> str:
    """Send a chat completion request and return the assistant message content."""
    settings = get_settings()
    payload: dict = {
        "model": model or settings.venice_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if web_search:
        payload["venice_parameters"] = {"enable_web_search": "on"}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{VENICE_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def stream_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    web_search: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> AsyncIterator[str]:
    """Stream a chat completion, yielding text chunks."""
    settings = get_settings()
    payload: dict = {
        "model": model or settings.venice_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if web_search:
        payload["venice_parameters"] = {"enable_web_search": "on"}

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{VENICE_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    return
                import json
                try:
                    data = json.loads(chunk)
                    delta = data["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError):
                    continue


async def generate_image(
    prompt: str,
    *,
    model: str = "chroma",
    width: int = 1280,
    height: int = 720,
) -> bytes:
    """Generate an image via Venice image API. Returns raw PNG bytes."""
    payload = {
        "model": model,
        "prompt": prompt,
        "width": width,
        "height": height,
        "format": "png",
        "hide_watermark": True,
        "return_binary": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{VENICE_BASE_URL}/image/generate",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
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
