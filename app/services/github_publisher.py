"""GitHub publisher — push morning brief articles to the cryptocatalyst-news repo."""
from __future__ import annotations

import base64
import json

import httpx

GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _get_file_sha(token: str, repo: str, path: str) -> str | None:
    """Return the blob SHA if the file already exists in the repo, else None."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_headers(token))
        if resp.status_code == 200:
            return resp.json().get("sha")
        return None


async def push_image(
    token: str,
    repo: str,
    slug: str,
    image_bytes: bytes,
    commit_message: str,
) -> str:
    """Upload a PNG to public/images/articles/ and return the /images/articles/{slug}.png path."""
    path = f"public/images/articles/{slug}.png"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    sha = await _get_file_sha(token, repo, path)
    payload: dict = {
        "message": commit_message,
        "content": encoded,
        "branch": "master",
    }
    if sha:
        payload["sha"] = sha
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.put(url, headers=_headers(token), json=payload)
        resp.raise_for_status()
    return f"/images/articles/{slug}.png"


async def push_article(
    token: str,
    repo: str,
    slug: str,
    article: dict,
    commit_message: str,
) -> dict:
    """Create or update an article JSON file in content/articles/.

    Returns the GitHub API response dict.
    """
    path = f"content/articles/{slug}.json"
    content_bytes = json.dumps(article, indent=2, ensure_ascii=False).encode("utf-8")
    encoded = base64.b64encode(content_bytes).decode("ascii")

    sha = await _get_file_sha(token, repo, path)

    payload: dict = {
        "message": commit_message,
        "content": encoded,
        "branch": "master",
    }
    if sha:
        payload["sha"] = sha  # required when updating an existing file

    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(url, headers=_headers(token), json=payload)
        resp.raise_for_status()
        return resp.json()
