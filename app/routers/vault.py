"""Vault router — file browser CRUD."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import vault

router = APIRouter(prefix="/api/vault", tags=["vault"])


class FileWrite(BaseModel):
    path: str
    content: str


@router.get("/files")
async def list_files(folder: str = ""):
    return vault.list_vault_files(folder)


@router.get("/file")
async def read_file(path: str):
    try:
        content = await vault.read_file(path)
        return {"path": path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/file")
async def write_file(body: FileWrite):
    try:
        saved = await vault.write_file(body.path, body.content)
        return {"path": saved, "status": "saved"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/file")
async def delete_file(path: str):
    try:
        vault.delete_file(path)
        return {"status": "deleted", "path": path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
