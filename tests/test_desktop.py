"""Tests for the standalone build's launcher (app/desktop.py)."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

from app import desktop


@pytest.fixture(autouse=True)
def restore_environment():
    """Snapshot and restore os.environ around every test in this module.

    `configure_environment()` creates variables that did not exist before, and
    `monkeypatch.delenv(..., raising=False)` records nothing to undo when the
    key was absent - so without this the settings would leak into other tests.
    """
    saved = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(saved)


def _occupy(port_hint: int = 0) -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((desktop.HOST, port_hint))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def test_find_free_port_returns_the_preferred_one_when_available():
    sock, port = _occupy()
    sock.close()
    assert desktop.find_free_port(port) == port


def test_find_free_port_skips_a_busy_port():
    """A second copy of the app must not die on 'address already in use'."""
    sock, busy = _occupy()
    try:
        assert desktop.find_free_port(busy) == busy + 1
    finally:
        sock.close()


def test_find_free_port_gives_up_with_a_clear_message():
    sock, busy = _occupy()
    try:
        with pytest.raises(SystemExit) as exc:
            desktop.find_free_port(busy, attempts=1)
        assert str(busy) in str(exc.value)
    finally:
        sock.close()


def test_bundle_dir_is_the_repo_root_when_not_frozen():
    assert desktop.bundle_dir() == Path(desktop.__file__).resolve().parent.parent
    assert (desktop.bundle_dir() / "web").is_dir()


def test_bundle_dir_sits_next_to_the_executable_when_frozen(monkeypatch, tmp_path):
    """Not sys._MEIPASS: that is wiped on exit and would delete the EPUBs."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "webnoveltoepub.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI12345"), raising=False)

    assert desktop.bundle_dir() == tmp_path


def test_configure_environment_defaults_to_saving_next_to_the_executable():
    for key in ("WNE_PORT", "WNE_SAVE_TO_DISK", "WNE_OUTPUT_DIR"):
        os.environ.pop(key, None)

    desktop.configure_environment(8000)

    assert os.environ["WNE_SAVE_TO_DISK"] == "true"
    assert os.environ["WNE_OUTPUT_DIR"] == str(desktop.bundle_dir() / "output")


def test_configure_environment_does_not_override_real_settings():
    os.environ["WNE_SAVE_TO_DISK"] = "false"
    os.environ["WNE_OUTPUT_DIR"] = "/somewhere/else"

    desktop.configure_environment(8000)

    assert os.environ["WNE_SAVE_TO_DISK"] == "false"
    assert os.environ["WNE_OUTPUT_DIR"] == "/somewhere/else"
