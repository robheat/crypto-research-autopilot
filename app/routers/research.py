"""Research router — AI-powered token research note generation."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import brief as brief_svc

router = APIRouter(prefix="/api/research", tags=["research"])

log = logging.getLogger(__name__)


class TokenResearchRequest(BaseModel):
    token_name: str = Field(min_length=1, max_length=100)
    # `symbol` becomes a filename in 02-Research/tokens/.
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    coingecko_id: str = Field(default="", max_length=100, pattern=r"^[a-z0-9-]*$")
    custom_notes: str = Field(default="", max_length=4000)


@router.post("/token")
async def generate_token_research(req: TokenResearchRequest):
    """Use Venice AI to generate a structured token research note."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.venice_api_key or settings.venice_api_key == "your_venice_api_key_here":
        raise HTTPException(status_code=400, detail="VENICE_API_KEY is not configured.")
    try:
        return await brief_svc.generate_token_research(
            token_name=req.token_name,
            symbol=req.symbol,
            coingecko_id=req.coingecko_id,
            custom_notes=req.custom_notes,
        )
    except Exception:
        log.exception("Token research failed for %s", req.symbol)
        raise HTTPException(
            status_code=500, detail="Research generation failed. See server logs for details."
        )
