#!/usr/bin/env python3
"""Ultimate Web Scraper — entry point."""

from __future__ import annotations

import sys

import uvicorn
from loguru import logger

from src.config import load_config
from src.exceptions import ConfigError


def setup_logging(log_level: str) -> None:
    """Configure loguru with console + rotating file output."""
    logger.remove()  # remove default handler

    # Coloured stderr output
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        colorize=True,
    )

    # Rotating file handler (daily, 30-day retention, compressed)
    logger.add(
        "logs/scraper_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        enqueue=True,  # async-safe
    )


def main() -> None:
    """Load config and start the uvicorn server."""
    try:
        config = load_config()
    except ConfigError as exc:
        logger.error("Configuration error: {}", exc)
        sys.exit(1)

    setup_logging(config.log_level)

    logger.info("Starting Ultimate Web Scraper v0.1.0")
    logger.info("Server: {}:{}", config.server_host, config.server_port)
    logger.info("Targets: {}", len(config.targets))

    try:
        uvicorn.run(
            "src.server:app",
            host=config.server_host,
            port=config.server_port,
            log_level=config.log_level.lower(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully…")
        sys.exit(0)


if __name__ == "__main__":
    main()
