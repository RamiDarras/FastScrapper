"""Pydantic v2 models — foundation for config, data, and API responses."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SelectorType(str, Enum):
    css = "css"
    id = "id"
    class_ = "class"
    xpath = "xpath"


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class SelectorConfig(BaseModel):
    """One data-extraction point within a target."""

    selector: str = Field(..., min_length=1, description="CSS selector, element ID, class name, or XPath")
    selector_type: SelectorType = Field(default=SelectorType.css, description="How to interpret the selector")
    content_mode: str = Field(default="text", pattern="^(text|inner_html|outer_html)$", description="Extraction mode: text, inner_html, or outer_html")
    param: str = Field(..., min_length=1, description="Key name in API response JSON")
    attribute: Optional[str] = Field(default=None, description="HTML attribute to extract (None = text content)")
    multiple: bool = Field(default=False, description="Return array of all matching elements")
    default: Optional[str] = Field(default=None, description="Fallback if element missing (None = raise error)")

    @field_validator("selector", "param")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace")
        return v.strip()


class TargetConfig(BaseModel):
    """One scraping target (one URL to poll)."""

    name: str = Field(..., description="Unique identifier (alphanumeric + - + _ only)")
    url: HttpUrl = Field(..., description="Page to scrape")
    selectors: List[SelectorConfig] = Field(..., min_length=1, description="What to extract")
    interval: int = Field(default=300, ge=10, description="Seconds between polls")
    use_stealth: bool = Field(default=True, description="True = Nodriver, False = httpx+BS4")
    enabled: bool = Field(default=True, description="Disabled targets are skipped")
    timeout: int = Field(default=30, ge=5, le=300, description="Page load timeout (seconds)")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Custom HTTP headers (httpx only)")
    proxy: Optional[str] = Field(default=None, description="Proxy URL, e.g. http://proxy:8080")
    browser_executable_path: Optional[str] = Field(default=None, description="Path to Chrome/Chromium binary (stealth mode)")
    headless: bool = Field(default=False, description="Run browser in headless mode (False is better for Cloudflare bypass)")
    wait_for_selector: Optional[str] = Field(default=None, description="XPath/CSS selector to wait for before scraping (nodriver only)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("name must contain only alphanumeric characters, hyphens, and underscores")
        return v

    @model_validator(mode="after")
    def unique_params(self) -> "TargetConfig":
        params = [s.param for s in self.selectors]
        if len(params) != len(set(params)):
            raise ValueError("All selector 'param' values within a target must be unique")
        return self


class AppConfig(BaseModel):
    """Root config loaded from YAML."""

    targets: List[TargetConfig] = Field(..., min_length=1, description="Scraping targets")
    server_host: str = Field(default="0.0.0.0", description="Bind address")
    server_port: int = Field(default=8000, ge=1, le=65535, description="Bind port")
    api_key: str = Field(..., min_length=8, description="API key for authenticating requests")
    log_level: str = Field(default="INFO", description="Loguru level")
    data_dir: str = Field(default="data", description="Directory for JSON files")
    max_retries: int = Field(default=3, ge=1, le=10, description="Retry attempts per scrape")
    retry_delay: int = Field(default=5, ge=1, le=60, description="Base retry delay (seconds)")

    @model_validator(mode="after")
    def unique_target_names(self) -> "AppConfig":
        names = [t.name for t in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("All target 'name' values must be unique")
        return self


# ---------------------------------------------------------------------------
# Data / response models
# ---------------------------------------------------------------------------

class ScrapedData(BaseModel):
    """Stored in JSON files and returned by the API."""

    target_name: str
    url: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    scrape_duration_ms: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    active_targets: int
    total_scrapes: int
    last_scrape: Optional[datetime] = None


class TargetListResponse(BaseModel):
    targets: List[Dict[str, Any]]
    total: int
