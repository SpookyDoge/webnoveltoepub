"""Heavy mode without Chromium must produce an actionable hint, not a hang."""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from app import service
from app.fetcher import FetchError, PlaywrightUnavailableError, _playwright_missing_hint
from app.main import app


def test_is_a_fetch_error_subclass():
    """Existing handlers keep catching it; only the mapping gets more specific."""
    assert issubclass(PlaywrightUnavailableError, FetchError)


def test_hint_points_at_docker_in_the_frozen_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    hint = _playwright_missing_hint()
    assert ".exe" in hint
    assert "Docker" in hint


def test_hint_points_at_installation_when_running_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    hint = _playwright_missing_hint()
    assert "playwright install chromium" in hint


def test_api_maps_it_to_its_own_code_not_a_network_error(monkeypatch):
    """422 with a distinct code - it is a setup problem, not a flaky network."""

    def boom(url, settings):
        raise PlaywrightUnavailableError("no chromium here")

    monkeypatch.setattr(service, "_make_parser", boom)

    with TestClient(app) as client:
        response = client.post(
            "/api/preview", json={"url": "https://www.royalroad.com/fiction/1/x"}
        )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("playwright_unavailable")


@pytest.mark.parametrize("locale", ["en", "pl"])
def test_frontend_has_a_translated_hint(locale):
    with TestClient(app) as client:
        strings = client.get(f"/api/languages/{locale}").json()
    assert strings["error.playwright_unavailable"]
