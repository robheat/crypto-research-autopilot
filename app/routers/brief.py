"""Brief router — generate and retrieve morning briefs."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import brief as brief_svc
from app.services import vault

router = APIRouter(prefix="/api/brief", tags=["brief"])


class BriefRequest(BaseModel):
    web_search: bool = True


@router.post("/generate")
async def generate_brief(req: BriefRequest):
    """Trigger a morning brief generation now."""
    settings_obj = None
    try:
        from app.config import get_settings
        settings_obj = get_settings()
        if not settings_obj.venice_api_key or settings_obj.venice_api_key == "your_venice_api_key_here":
            raise HTTPException(status_code=400, detail="VENICE_API_KEY is not configured. Set it in the Settings tab.")
        result = await brief_svc.generate_brief(web_search=req.web_search)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/latest")
async def get_latest_brief():
    """Return the most recently generated brief."""
    files = vault.list_vault_files("00-Inbox")
    brief_files = sorted(
        [f for f in files if f["name"].startswith("brief-")],
        key=lambda x: x["modified"],
        reverse=True,
    )
    if not brief_files:
        return {"path": None, "content": None, "date": None}
    latest = brief_files[0]
    try:
        content = await vault.read_file(latest["path"])
    except FileNotFoundError:
        content = ""
    return {"path": latest["path"], "content": content, "date": latest["name"].replace("brief-", "")}


@router.get("/history")
async def get_brief_history():
    """List all saved briefs in the inbox."""
    files = vault.list_vault_files("00-Inbox")
    return sorted(
        [f for f in files if f["name"].startswith("brief-")],
        key=lambda x: x["modified"],
        reverse=True,
    )


@router.get("/file")
async def get_brief_by_path(path: str):
    """Read a specific brief file by vault-relative path."""
    try:
        content = await vault.read_file(path)
        return {"path": path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Brief not found")
