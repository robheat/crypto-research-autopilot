"""Vault service — read/write the local markdown research vault."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings


def _vault() -> Path:
    return get_settings().vault_dir


def _safe_path(relative: str) -> Path:
    """Resolve a relative vault path, blocking directory traversal."""
    vault = _vault().resolve()
    target = (vault / relative).resolve()
    if not str(target).startswith(str(vault)):
        raise ValueError("Path traversal not allowed")
    return target


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def list_vault_files(subfolder: str = "") -> list[dict[str, Any]]:
    """List all .md files under a vault subfolder, with metadata."""
    root = _vault() / subfolder if subfolder else _vault()
    if not root.exists():
        return []
    vault_resolved = _vault().resolve()
    results = []
    for p in sorted(root.rglob("*.md")):
        stat = p.stat()
        p_resolved = p.resolve()
        results.append(
            {
                "path": p_resolved.relative_to(vault_resolved).as_posix(),
                "name": p.stem,
                "folder": p_resolved.parent.relative_to(vault_resolved).as_posix(),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return results


# ---------------------------------------------------------------------------
# File read/write
# ---------------------------------------------------------------------------

async def read_file(relative_path: str) -> str:
    path = _safe_path(relative_path)
    if not path.exists():
        raise FileNotFoundError(f"Vault file not found: {relative_path}")
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


async def write_file(relative_path: str, content: str) -> str:
    """Create or overwrite a vault file. Returns the resolved relative path."""
    path = _safe_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)
    return path.relative_to(_vault().resolve()).as_posix()


def delete_file(relative_path: str) -> None:
    path = _safe_path(relative_path)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Vault section readers (used by brief orchestrator)
# ---------------------------------------------------------------------------

async def read_section(subfolder: str, max_chars: int = 12000) -> str:
    """Read all .md files in a vault subfolder, concatenated with headers."""
    root = _vault() / subfolder
    if not root.exists():
        return ""
    vault_resolved = _vault().resolve()
    chunks: list[str] = []
    total = 0
    for p in sorted(root.rglob("*.md")):
        if total >= max_chars:
            break
        text = p.read_text(encoding="utf-8")
        snippet = text[: max_chars - total]
        chunks.append(f"### {p.resolve().relative_to(vault_resolved).as_posix()}\n\n{snippet}")
        total += len(snippet)
    return "\n\n---\n\n".join(chunks)


async def read_recent_inbox(hours: int = 24) -> str:
    """Read Inbox files modified within the last N hours."""
    inbox = _vault() / "00-Inbox"
    if not inbox.exists():
        return ""
    cutoff = datetime.now(tz=timezone.utc).timestamp() - hours * 3600
    chunks: list[str] = []
    for p in sorted(inbox.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.stat().st_mtime < cutoff:
            continue
        text = p.read_text(encoding="utf-8")
        chunks.append(f"### {p.name}\n\n{text[:3000]}")
    return "\n\n---\n\n".join(chunks)


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

WATCHLIST_FILE = "01-Market/watchlist/_index.json"


def get_watchlist() -> list[dict]:
    path = _vault() / WATCHLIST_FILE
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_watchlist(tokens: list[dict]) -> None:
    path = _vault() / WATCHLIST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")


def get_watchlist_coingecko_ids() -> list[str]:
    """Extract coingecko_id from watchlist tokens that have one set."""
    return [t["coingecko_id"] for t in get_watchlist() if t.get("coingecko_id")]


def get_watchlist_symbols() -> list[str]:
    return [t["symbol"].lower() for t in get_watchlist() if t.get("symbol")]
