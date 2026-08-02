"""Entry point for the standalone Windows build (PyInstaller).

Starts uvicorn bound to localhost and opens the default browser at it. Kept
separate from `main.py` so the Docker image never pays for any of this.

Environment variables have to be set BEFORE `app.main` is imported: settings
are read once and cached (`get_settings` is lru_cache'd), and importing
`app.main` triggers that read.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8000
#: How many consecutive ports to try before giving up.
PORT_SCAN_RANGE = 50
HOST = "127.0.0.1"


def bundle_dir() -> Path:
    """Directory the user sees: next to the .exe, or the repo root in dev mode.

    Deliberately not `sys._MEIPASS` - that is the temporary unpack directory,
    which is wiped on exit and would take the user's EPUBs with it.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_free_port(preferred: int = DEFAULT_PORT, attempts: int = PORT_SCAN_RANGE) -> int:
    """First free port starting from `preferred`.

    Another copy of the app (or anything else on 8000) must not make startup
    fail with a stack trace - we just move one port up.
    """
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return port
    raise SystemExit(
        f"No free port found in the range {preferred}-{preferred + attempts - 1}."
    )


def configure_environment(port: int) -> None:
    """Desktop defaults. `setdefault` so a real environment variable still wins."""
    os.environ.setdefault("WNE_PORT", str(port))
    # In the .exe the browser download is not the only route - people expect
    # files to simply appear in a folder next to the program.
    os.environ.setdefault("WNE_SAVE_TO_DISK", "true")
    os.environ.setdefault("WNE_OUTPUT_DIR", str(bundle_dir() / "output"))


def main() -> None:
    port = find_free_port(int(os.environ.get("WNE_PORT") or DEFAULT_PORT))
    configure_environment(port)

    # Imported after configure_environment() - see the module docstring.
    import uvicorn

    # Absolute, not relative: PyInstaller runs this file as __main__, where a
    # relative import has no parent package to resolve against.
    from app.main import app

    url = f"http://{HOST}:{port}"
    print(f"webnoveltoepub is running at {url}")
    print(f"EPUB files are saved to {os.environ['WNE_OUTPUT_DIR']}")
    print("Close this window to stop the server.")

    # Fires once uvicorn has had a moment to bind; opening it earlier would
    # land on a connection error.
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
