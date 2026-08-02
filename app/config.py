"""Konfiguracja aplikacji - wszystko sterowane zmiennymi srodowiskowymi WNE_*."""

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
    #: Odstep miedzy kolejnymi zapytaniami do tego samego hosta (sekundy).
    #: Nie zmniejszaj bez potrzeby - to jedyne, co chroni serwis przed zalaniem.
    request_delay: float = 0.75
    max_retries: int = 3

    # --- Limity konwersji ---
    #: Twardy limit rozdzialow w jednym EPUB-ie (ochrona przed 3000-rozdzialowymi
    #: potworami, ktore zabija timeout przegladarki).
    max_chapters: int = 300

    # --- Playwright ("ciezki tryb") ---
    playwright_enabled: bool = False
    playwright_wait_until: str = "networkidle"
    playwright_timeout_ms: int = 45_000

    # --- Zapis na dysk ---
    #: Poza streamowaniem w odpowiedzi HTTP zapisz kopie EPUB-a na dysku.
    #: Domyslnie wylaczone (aplikacja jest bezstanowa); wlaczaja to gotowce
    #: dla paneli self-hosted, gdzie uzytkownik szuka plikow w File Managerze.
    save_to_disk: bool = False
    #: Sciezka wzgledna rozwiazuje sie wzgledem WORKDIR, czyli /app/output
    #: w kontenerze. Tam podpina sie bind mount.
    output_dir: Path = Path("output")

    # --- UI / i18n ---
    default_language: str = "en"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
