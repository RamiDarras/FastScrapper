"""Async JSON file storage for scraped data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

import aiofiles
from loguru import logger

from src.exceptions import StorageError
from src.models import ScrapedData


class StorageManager:
    """Read/write scraped data as JSON files (one file per target)."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, target_name: str) -> Path:
        """Return the JSON file path for a target, sanitizing the name."""
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", target_name)
        return self.data_dir / f"{safe_name}.json"

    async def save(self, data: ScrapedData) -> None:
        """Atomically write scraped data to disk (write tmp → rename)."""
        file_path = self._get_file_path(data.target_name)
        temp_path = file_path.with_suffix(".tmp")

        try:
            payload = json.dumps(data.model_dump(mode="json"), indent=2, ensure_ascii=False)
            async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
                await f.write(payload)
            temp_path.replace(file_path)
            logger.debug("Saved data for target '{}'", data.target_name)
        except Exception as exc:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise StorageError(f"Failed to save data for target '{data.target_name}': {exc}") from exc

    async def load(self, target_name: str) -> Optional[ScrapedData]:
        """Load the latest scraped data for a target. Returns None if no data exists."""
        file_path = self._get_file_path(target_name)

        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            data_dict = json.loads(content)
            return ScrapedData(**data_dict)
        except Exception as exc:
            raise StorageError(f"Failed to load data for target '{target_name}': {exc}") from exc

    async def list_all(self) -> List[str]:
        """Return names of all targets that have stored data."""
        return [p.stem for p in self.data_dir.glob("*.json")]
