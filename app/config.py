"""Application configuration - everything driven by WNE_* environment variables."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _base_dir() -> Path:
    """Root that `web/` sits under.

    In a PyInstaller build the bundled data lives in the temporary unpack
    directory (`sys._MEIPASS`), not next to the .exe, so relying on
    `__file__` alone would look for the frontend in the wrong place.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
WEB_DIR = BASE_DIR / "web"
LOCALES_DIR = WEB_DIR / "locales"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WNE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- HTTP ---
    user_agent: str = (
        "webnoveltoepub/0.1 (+https://github.com/SpookyDoge/webnoveltoepub)"
    )
    request_timeout: float = 30.0
    #: Delay between consecutive requests to the same host (seconds).
    #: Don't lower it without a good reason - it is the only thing keeping us
    #: from flooding someone else's site.
    request_delay: float = 0.75
    max_retries: int = 3

    # --- Conversion limits ---
    #: Hard cap on chapters in a single EPUB (protects against 3000-chapter
    #: monsters that a browser timeout would kill anyway).
    max_chapters: int = 300

    # --- Playwright ("heavy mode") ---
    playwright_enabled: bool = False
    playwright_wait_until: str = "networkidle"
    playwright_timeout_ms: int = 45_000

    # --- Saving to disk ---
    #: Besides streaming it in the HTTP response, save a copy of the EPUB
    #: to disk. Off by default (the app is stateless); the ready-made files
    #: for self-hosted panels turn it on, because users there look for their
    #: files in a File Manager.
    save_to_disk: bool = False
    #: A relative path resolves against WORKDIR, i.e. /app/output inside the
    #: container. That is where the bind mount is attached.
    output_dir: Path = Path("output")

    # --- Library ---
    #: Where the library registry lives. Unset means <output_dir>/library.json,
    #: which keeps it on the same volume as the EPUBs - on CasaOS that is the
    #: bind mount, so the library survives recreating the container.
    library_path: Path | None = None
    #: Pause between novels in a bulk update. Each novel gets a fresh Fetcher
    #: (so its own throttle starts from zero) and this keeps the burst polite.
    library_update_delay: float = 2.0

    # --- UI / i18n ---
    default_language: str = "en"

    log_level: str = "INFO"

    def resolved_library_path(self) -> Path:
        """Library file location, following `output_dir` unless overridden."""
        return self.library_path or (self.output_dir / "library.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
