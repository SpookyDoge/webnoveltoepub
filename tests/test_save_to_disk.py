"""Tests for writing a copy of the EPUB to disk (WNE_SAVE_TO_DISK)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.service import _free_path, save_epub_to_disk

PAYLOAD = b"PK\x03\x04udawany-epub"


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(save_to_disk=enabled, output_dir=tmp_path / "output")


def test_disabled_by_default():
    assert Settings().save_to_disk is False


def test_writes_file_and_creates_directory(tmp_path):
    settings = _settings(tmp_path)
    saved = save_epub_to_disk("powiesc.epub", PAYLOAD, settings)

    assert saved is not None
    assert saved.read_bytes() == PAYLOAD
    assert saved.parent == tmp_path / "output"


def test_returns_none_when_disabled(tmp_path):
    settings = _settings(tmp_path, enabled=False)
    assert save_epub_to_disk("powiesc.epub", PAYLOAD, settings) is None
    assert not (tmp_path / "output").exists()


def test_does_not_clobber_existing_file(tmp_path):
    """The same novel over a different chapter range yields the same file name."""
    settings = _settings(tmp_path)
    first = save_epub_to_disk("powiesc.epub", b"pierwszy", settings)
    second = save_epub_to_disk("powiesc.epub", b"drugi", settings)
    third = save_epub_to_disk("powiesc.epub", b"trzeci", settings)

    assert first.name == "powiesc.epub"
    assert second.name == "powiesc-2.epub"
    assert third.name == "powiesc-3.epub"
    assert first.read_bytes() == b"pierwszy"


def test_disk_failure_does_not_break_conversion(tmp_path, monkeypatch):
    """Missing bind-mount permissions must not bring the whole conversion down."""
    settings = _settings(tmp_path)

    def boom(*args, **kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", boom)
    assert save_epub_to_disk("powiesc.epub", PAYLOAD, settings) is None


def test_free_path_returns_input_when_unused(tmp_path):
    target = tmp_path / "nowy.epub"
    assert _free_path(target) == target


@pytest.mark.parametrize("name", ["a.epub", "dluga-nazwa-powiesci.epub"])
def test_saved_file_keeps_requested_name(tmp_path, name):
    assert save_epub_to_disk(name, PAYLOAD, _settings(tmp_path)).name == name
