"""Research router — AI-powered token research note generation."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import brief as brief_svc

router = APIRouter(prefix="/api/research", tags=["research"])


class TokenResearchRequest(BaseModel):
    token_name: str
    symbol: str
    coingecko_id: str = ""
    custom_notes: str = ""


@router.post("/token")
async def generate_token_research(req: TokenResearchRequest):
    """Use Venice AI to generate a structured token research note."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.venice_api_key or settings.venice_api_key == "your_venice_api_key_here":
        raise HTTPException(status_code=400, detail="VENICE_API_KEY is not configured.")
    try:
        result = await brief_svc.generate_token_research(
            token_name=req.token_name,
            symbol=req.symbol,
            coingecko_id=req.coingecko_id,
            custom_notes=req.custom_notes,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
