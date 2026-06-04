"""Settings router — read and update .env configuration."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

ENV_FILE = Path(".env")

# Keys that are safe to expose to the frontend (masked)
MASKED_KEYS = {"venice_api_key", "cmc_api_key", "lunarcrush_api_key", "github_token"}


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    result: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip().lower()] = val.strip()
    return result


def _write_env_value(key: str, value: str) -> None:
    """Update a single key in the .env file."""
    key_upper = key.upper()
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    pattern = re.compile(rf"^{re.escape(key_upper)}=.*$", re.MULTILINE)
    new_line = f"{key_upper}={value}"
    if pattern.search(text):
        text = pattern.sub(new_line, text)
    else:
        text = text.rstrip("\n") + f"\n{new_line}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


class SettingsUpdate(BaseModel):
    venice_api_key: str | None = None
    venice_model: str | None = None
    cmc_api_key: str | None = None
    lunarcrush_api_key: str | None = None
    brief_schedule_cron: str | None = None
    github_token: str | None = None
    github_repo: str | None = None


@router.get("")
async def get_settings_view():
    env = _read_env_file()
    return {
        "venice_api_key_set": bool(env.get("venice_api_key") and env["venice_api_key"] != "your_venice_api_key_here"),
        "venice_model": env.get("venice_model", "qwen/qwen3-235b-a22b-04-28"),
        "cmc_api_key_set": bool(env.get("cmc_api_key")),
        "lunarcrush_api_key_set": bool(env.get("lunarcrush_api_key")),
        "brief_schedule_cron": env.get("brief_schedule_cron", "0 6 * * *"),
        "github_token_set": bool(env.get("github_token")),
        "github_repo": env.get("github_repo", "robheat/cryptocatalyst-news"),
    }


@router.post("")
async def update_settings(body: SettingsUpdate):
    updated: list[str] = []
    if body.venice_api_key is not None:
        _write_env_value("venice_api_key", body.venice_api_key)
        updated.append("venice_api_key")
    if body.venice_model is not None:
        _write_env_value("venice_model", body.venice_model)
        updated.append("venice_model")
    if body.cmc_api_key is not None:
        _write_env_value("cmc_api_key", body.cmc_api_key)
        updated.append("cmc_api_key")
    if body.lunarcrush_api_key is not None:
        _write_env_value("lunarcrush_api_key", body.lunarcrush_api_key)
        updated.append("lunarcrush_api_key")
    if body.brief_schedule_cron is not None:
        _write_env_value("brief_schedule_cron", body.brief_schedule_cron)
        updated.append("brief_schedule_cron")
        # Reload scheduler with new cron
        try:
            from app.scheduler import reschedule_brief
            reschedule_brief(body.brief_schedule_cron)
        except Exception:
            pass
    if body.github_token is not None:
        _write_env_value("github_token", body.github_token)
        updated.append("github_token")
    if body.github_repo is not None:
        _write_env_value("github_repo", body.github_repo)
        updated.append("github_repo")

    # Bust the settings cache so next read picks up new values
    get_settings.cache_clear()
    return {"updated": updated, "status": "saved"}


@router.get("/models")
async def list_models():
    """Return available Venice models."""
    try:
        from app.services.venice import list_models
        models = await list_models()
        return {"models": [m for m in models if m.get("type") == "text"]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
