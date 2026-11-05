"""FastAPI application — REST API with lifespan, auth, and endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from loguru import logger

from src.config import ensure_directories, load_config
from src.models import AppConfig, HealthResponse, ScrapedData, TargetListResponse
from src.scheduler import ScrapeScheduler
from src.scraper import ScraperEngine
from src.storage import StorageManager

# ---------------------------------------------------------------------------
# Module-level state (initialised in lifespan)
# ---------------------------------------------------------------------------
scheduler: Optional[ScrapeScheduler] = None
storage: Optional[StorageManager] = None
config: Optional[AppConfig] = None
app_start_time: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler, storage, config, app_start_time

    # Startup
    config = load_config()
    ensure_directories(config)

    scraper_engine = ScraperEngine(
        max_retries=config.max_retries,
        retry_delay=config.retry_delay,
    )
    storage = StorageManager(data_dir=config.data_dir)
    scheduler = ScrapeScheduler(config=config, scraper=scraper_engine, storage=storage)
    await scheduler.start()
    app_start_time = datetime.utcnow()
    logger.info("Application started — listening on {}:{}", config.server_host, config.server_port)

    yield

    # Shutdown
    if scheduler is not None:
        await scheduler.shutdown()
    logger.info("Application stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Ultimate Web Scraper",
    description="Web scraper with Cloudflare bypass and REST API",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# API-key authentication
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if config is None or api_key != config.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_key


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    """Public info endpoint — no auth required."""
    return {
        "name": "Ultimate Web Scraper",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/api/health", response_model=HealthResponse, dependencies=[Depends(verify_api_key)])
async def health():
    """Health check with uptime and aggregate stats."""
    assert scheduler is not None and app_start_time is not None

    stats = scheduler.get_stats()
    total = sum(s["total_scrapes"] for s in stats.values())
    last_times = [s["last_scrape"] for s in stats.values() if s["last_scrape"]]
    last_scrape = max(last_times) if last_times else None

    return HealthResponse(
        status="healthy",
        uptime_seconds=(datetime.utcnow() - app_start_time).total_seconds(),
        active_targets=len(stats),
        total_scrapes=total,
        last_scrape=last_scrape,
    )


@app.get("/api/targets", response_model=TargetListResponse, dependencies=[Depends(verify_api_key)])
async def list_targets():
    """List all configured targets with their current stats."""
    assert config is not None and scheduler is not None

    stats = scheduler.get_stats()
    targets: list[Dict[str, Any]] = []

    for t in config.targets:
        info: Dict[str, Any] = {
            "name": t.name,
            "url": str(t.url),
            "enabled": t.enabled,
            "interval": t.interval,
            "use_stealth": t.use_stealth,
        }
        info.update(stats.get(t.name, {}))
        targets.append(info)

    return TargetListResponse(targets=targets, total=len(targets))


@app.get("/api/data/{target_name}", response_model=ScrapedData, dependencies=[Depends(verify_api_key)])
async def get_data(target_name: str):
    """Return the latest scraped data for a target."""
    assert storage is not None

    data = await storage.load(target_name)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No data found for target '{target_name}'",
        )
    return data


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on {} {}", request.method, request.url)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Internal server error: {exc}"},
    )
