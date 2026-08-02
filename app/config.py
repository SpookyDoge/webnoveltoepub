"""Application configuration - everything driven by WNE_* environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
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

    # --- UI / i18n ---
    default_language: str = "en"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
