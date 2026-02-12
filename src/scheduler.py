"""Background scheduler — runs scrape jobs at configured intervals."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from src.models import AppConfig, TargetConfig
from src.scraper import ScraperEngine
from src.storage import StorageManager


class ScrapeScheduler:
    """Manages periodic scraping jobs using APScheduler."""

    def __init__(
        self,
        config: AppConfig,
        scraper: ScraperEngine,
        storage: StorageManager,
    ) -> None:
        self.config = config
        self.scraper = scraper
        self.storage = storage
        self.scheduler = AsyncIOScheduler()
        self.stats: Dict[str, Dict[str, Any]] = {}

    async def start(self) -> None:
        """Register jobs for all enabled targets and start the scheduler."""
        for target in self.config.targets:
            if not target.enabled:
                logger.info("Target '{}' is disabled — skipping", target.name)
                continue

            self.stats[target.name] = {
                "total_scrapes": 0,
                "successful_scrapes": 0,
                "failed_scrapes": 0,
                "last_scrape": None,
                "last_error": None,
            }

            self.scheduler.add_job(
                func=self._scrape_job,
                trigger=IntervalTrigger(seconds=target.interval),
                args=[target],
                id=target.name,
                name=f"Scrape {target.name}",
                replace_existing=True,
                max_instances=1,
            )
            logger.info(
                "Scheduled '{}' every {}s (stealth={})",
                target.name, target.interval, target.use_stealth,
            )

        self.scheduler.start()
        logger.info("Scheduler started with {} job(s)", len(self.stats))

        # Run initial scrapes immediately so data is available right away
        await self._run_initial_scrapes()

    async def _run_initial_scrapes(self) -> None:
        """Fire off one scrape per enabled target without waiting for the first interval."""
        tasks = [
            self._scrape_job(t)
            for t in self.config.targets
            if t.enabled
        ]
        if tasks:
            logger.info("Running initial scrapes for {} target(s)…", len(tasks))
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _scrape_job(self, target: TargetConfig) -> None:
        """Execute a single scrape and persist the result."""
        logger.debug("Scraping '{}'…", target.name)
        result = await self.scraper.scrape(target)

        # Update stats
        stats = self.stats.get(target.name)
        if stats is not None:
            stats["total_scrapes"] += 1
            stats["last_scrape"] = datetime.utcnow().isoformat()
            if result.success:
                stats["successful_scrapes"] += 1
                logger.info(
                    "✓ '{}' scraped in {}ms",
                    target.name, result.scrape_duration_ms,
                )
            else:
                stats["failed_scrapes"] += 1
                stats["last_error"] = result.error
                logger.warning("✗ '{}' failed: {}", target.name, result.error)

        await self.storage.save(result)

    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Return per-target statistics."""
        return self.stats

    async def shutdown(self) -> None:
        """Gracefully stop the scheduler."""
        self.scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")
