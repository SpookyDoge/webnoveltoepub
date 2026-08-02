from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.fetcher import make_soup  # noqa: E402


class FakeFetcher:
    """Stands in for Fetcher in tests - serves HTML from a dict, no network."""

    def __init__(self, pages: dict[str, str], binaries: dict[str, tuple[bytes, str]] | None = None):
        self.pages = pages
        self.binaries = binaries or {}
        self.requested: list[str] = []

    def get_text(self, url: str, *, use_cache: bool = True) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise AssertionError(f"Test nie przygotowal strony dla {url}")
        return self.pages[url]

    def get_soup(self, url: str, *, use_cache: bool = True):
        return make_soup(self.get_text(url))

    def get_bytes(self, url: str) -> tuple[bytes, str]:
        self.requested.append(url)
        if url not in self.binaries:
            raise AssertionError(f"Test nie przygotowal pliku dla {url}")
        return self.binaries[url]

    def close(self) -> None:
        pass


@pytest.fixture
def fake_fetcher():
    return FakeFetcher
