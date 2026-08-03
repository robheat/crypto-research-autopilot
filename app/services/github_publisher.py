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


def _branch() -> str | None:
    """Configured publish branch, or None to let GitHub use the repo default.

    This used to be hardcoded to "master", which fails outright on any repo
    whose default branch is "main".
    """
    from app.config import get_settings

    return get_settings().publish_branch.strip() or None


async def _default_branch(client: httpx.AsyncClient, token: str, repo: str) -> str:
    resp = await client.get(f"{GITHUB_API}/repos/{repo}", headers=_headers(token))
    resp.raise_for_status()
    return resp.json()["default_branch"]


async def push_brief(
    token: str,
    repo: str,
    slug: str,
    article: dict,
    image_bytes: bytes | None,
    commit_message: str,
) -> str:
    """Publish the article JSON and (optionally) its header image as a single commit.

    Uses the Git Data API (blobs/trees/commits/refs) instead of the Contents
    API so both files land in one commit — the Contents API's PUT creates and
    pushes a commit per call, which meant one Vercel deploy per file.

    Returns the new commit SHA.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        branch = _branch() or await _default_branch(client, token, repo)
        headers = _headers(token)

        ref_resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/git/ref/heads/{branch}", headers=headers
        )
        ref_resp.raise_for_status()
        parent_sha = ref_resp.json()["object"]["sha"]

        commit_resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/git/commits/{parent_sha}", headers=headers
        )
        commit_resp.raise_for_status()
        base_tree_sha = commit_resp.json()["tree"]["sha"]

        article_bytes = json.dumps(article, indent=2, ensure_ascii=False).encode("utf-8")
        tree_entries = []
        for path, blob_bytes in (
            (f"content/articles/{slug}.json", article_bytes),
            (f"public/images/articles/{slug}.png", image_bytes),
        ):
            if blob_bytes is None:
                continue
            blob_resp = await client.post(
                f"{GITHUB_API}/repos/{repo}/git/blobs",
                headers=headers,
                json={"content": base64.b64encode(blob_bytes).decode("ascii"), "encoding": "base64"},
            )
            blob_resp.raise_for_status()
            tree_entries.append(
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_resp.json()["sha"],
                }
            )

        tree_resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/git/trees",
            headers=headers,
            json={"base_tree": base_tree_sha, "tree": tree_entries},
        )
        tree_resp.raise_for_status()
        new_tree_sha = tree_resp.json()["sha"]

        new_commit_resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/git/commits",
            headers=headers,
            json={"message": commit_message, "tree": new_tree_sha, "parents": [parent_sha]},
        )
        new_commit_resp.raise_for_status()
        new_commit_sha = new_commit_resp.json()["sha"]

        update_ref_resp = await client.patch(
            f"{GITHUB_API}/repos/{repo}/git/refs/heads/{branch}",
            headers=headers,
            json={"sha": new_commit_sha},
        )
        update_ref_resp.raise_for_status()

    return new_commit_sha
