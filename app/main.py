"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import brief, research, settings, vault, watchlist
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cfg = get_settings()
    _ensure_vault_dirs(cfg.vault_dir)
    start_scheduler(cfg.brief_schedule_cron)
    logger.info("Crypto Research Autopilot started. Vault: %s", cfg.vault_dir)
    yield
    # Shutdown
    stop_scheduler()


def _ensure_vault_dirs(vault: Path) -> None:
    for sub in [
        "00-Inbox",
        "01-Market/theses",
        "01-Market/narratives",
        "01-Market/watchlist",
        "02-Research/protocols",
        "02-Research/tokens",
        "02-Research/macro",
        "03-Journal",
        "04-Intelligence",
    ]:
        (vault / sub).mkdir(parents=True, exist_ok=True)


app = FastAPI(
    title="Crypto Research Autopilot",
    description="Venice-powered crypto research system with automated morning briefs.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(brief.router)
app.include_router(vault.router)
app.include_router(watchlist.router)
app.include_router(research.router)
app.include_router(settings.router)

# Serve static frontend — must be last
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
