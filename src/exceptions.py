class ScraperError(Exception):
    """Base exception for all scraper errors."""


class ConfigError(ScraperError):
    """Invalid or missing configuration."""


class TargetNotFoundError(ScraperError):
    """Requested scraping target does not exist."""


class ScrapeFailedError(ScraperError):
    """HTTP request or page load failed."""


class ElementNotFoundError(ScraperError):
    """Required HTML element was not found on the page."""


class BrowserError(ScraperError):
    """Browser automation (Nodriver) error."""


class StorageError(ScraperError):
    """File storage read/write error."""
