"""Watchlist router — manage tracked tokens."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import vault

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class Token(BaseModel):
    symbol: str
    name: str
    coingecko_id: str = ""
    entry_rationale: str = ""
    notes: str = ""


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
