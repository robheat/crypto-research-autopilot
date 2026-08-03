"""Settings router — read and update .env configuration."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.config import PROJECT_ROOT, get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Anchored to the project root so the file written is the file pydantic-settings
# reads, regardless of the process working directory.
ENV_FILE = PROJECT_ROOT / ".env"

# Keys that are safe to expose to the frontend (masked)
MASKED_KEYS = {"venice_api_key", "cmc_api_key", "lunarcrush_api_key", "github_token"}


def _write_env_value(key: str, value: str) -> None:
    """Update a single key in the .env file."""
    if "\n" in value or "\r" in value:
        raise ValueError(f"{key} must not contain newlines")
    key_upper = key.upper()
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    # \r is matched explicitly: on CRLF files `.*$` otherwise leaves a stray \r
    # attached to the replaced line.
    pattern = re.compile(rf"^{re.escape(key_upper)}=[^\r\n]*\r?$", re.MULTILINE)
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

    @field_validator("brief_schedule_cron")
    @classmethod
    def _check_cron(cls, v: str | None) -> str | None:
        """Reject a bad cron here rather than writing it to .env and failing later."""
        if v is None:
            return v
        from app.scheduler import build_trigger

        build_trigger(v)  # raises ValueError -> 422
        return v.strip()

    @field_validator("github_repo")
    @classmethod
    def _check_repo(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and not re.fullmatch(r"[\w.-]+/[\w.-]+", v):
            raise ValueError("github_repo must be in 'owner/name' form")
        return v


@router.get("")
async def get_settings_view():
    # Read through the Settings object so values supplied as real environment
    # variables (GitHub Actions, docker) are reflected, not just .env entries.
    cfg = get_settings()
    from app.scheduler import scheduler_status

    return {
        "venice_api_key_set": bool(
            cfg.venice_api_key and cfg.venice_api_key != "your_venice_api_key_here"
        ),
        "venice_model": cfg.venice_model,
        "cmc_api_key_set": bool(cfg.cmc_api_key),
        "lunarcrush_api_key_set": bool(cfg.lunarcrush_api_key),
        "brief_schedule_cron": cfg.brief_schedule_cron,
        "github_token_set": bool(cfg.github_token),
        "github_repo": cfg.github_repo,
        "scheduler": scheduler_status(),
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
        # Reload scheduler with the new cron (already validated by the model).
        from app.scheduler import reschedule_brief

        reschedule_brief(body.brief_schedule_cron)
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
