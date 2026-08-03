"""Watchlist router — manage tracked tokens."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.services import vault

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class Token(BaseModel):
    # `symbol` becomes a filename, so it must not contain separators or dots.
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    name: str = Field(min_length=1, max_length=100)
    coingecko_id: str = Field(default="", max_length=100, pattern=r"^[a-z0-9-]*$")
    entry_rationale: str = ""
    notes: str = ""

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


@router.get("")
async def get_watchlist():
    return vault.get_watchlist()


@router.post("")
async def add_token(token: Token):
    tokens = vault.get_watchlist()
    # Overwrite if symbol already exists
    tokens = [t for t in tokens if t.get("symbol", "").upper() != token.symbol.upper()]
    tokens.append(token.model_dump())
    vault.save_watchlist(tokens)

    # Also write a dedicated .md note for this token
    note_path = f"01-Market/watchlist/{token.symbol.lower()}.md"
    note_content = f"""# {token.name} ({token.symbol.upper()}) — Watchlist

## Entry Rationale
{token.entry_rationale or "Not specified."}

## Notes
{token.notes or "No notes yet."}

## CoinGecko ID
{token.coingecko_id or "Not set."}
"""
    await vault.write_file(note_path, note_content)
    return {"status": "added", "token": token.model_dump()}


@router.delete("/{symbol}")
async def remove_token(symbol: str):
    tokens = vault.get_watchlist()
    updated = [t for t in tokens if t.get("symbol", "").upper() != symbol.upper()]
    if len(updated) == len(tokens):
        raise HTTPException(status_code=404, detail=f"Token {symbol} not in watchlist")
    vault.save_watchlist(updated)
    return {"status": "removed", "symbol": symbol}
