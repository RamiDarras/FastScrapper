"""Configuration loader and directory setup."""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from pydantic import ValidationError

from src.exceptions import ConfigError
from src.models import AppConfig


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load and validate the YAML configuration file.

    Raises:
        ConfigError: If the file is missing, unparseable, or fails validation.
    """
    path = Path(config_path)

    if not path.exists():
        raise ConfigError(
            f"Config file '{config_path}' not found. "
            "Copy config.example.yaml to config.yaml and customize it."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML config: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping (dict) at the top level.")

    try:
        config = AppConfig(**raw)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            errors.append(f"  {loc}: {err['msg']}")
        raise ConfigError("Config validation failed:\n" + "\n".join(errors)) from exc

    logger.info("Loaded config with {} target(s)", len(config.targets))
    return config


def ensure_directories(config: AppConfig) -> None:
    """Create data and log directories if they don't exist."""
    Path(config.data_dir).mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
