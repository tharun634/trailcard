"""Runtime configuration, all from environment variables with local-first defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434"))
    model: str = field(default_factory=lambda: os.getenv("TRAILCARD_MODEL", "gemma4:e4b"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("TRAILCARD_DATA", "data")).resolve())
    # Timeouts are generous: the first request has to load the model into VRAM.
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("TRAILCARD_LLM_TIMEOUT", "240")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "trailcard.sqlite3"

    @property
    def photo_dir(self) -> Path:
        return self.data_dir / "photos"
