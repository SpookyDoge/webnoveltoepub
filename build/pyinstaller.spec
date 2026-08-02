# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone Windows build.

    pyinstaller build/pyinstaller.spec --noconfirm

Produces a single dist/webnoveltoepub.exe: FastAPI + uvicorn + the static
frontend. Chromium is deliberately NOT bundled (~300 MB); heavy mode stays
a Docker-only feature and the UI says so.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

# The frontend has to travel as DATA, not as code - index.html, app.js,
# styles.css and every web/locales/*.json. `app/config.py` looks for them
# under sys._MEIPASS, which is where this lands them.
datas = [(str(ROOT / "web"), "web")]

# Parsers are imported dynamically (pkgutil.iter_modules + import_module), so
# static analysis never sees them and they would silently vanish from the
# bundle - the .exe would start up with zero supported sites. Globbing the
# directory means a new parser needs no change here.
hiddenimports = [
    f"app.parsers.{path.stem}"
    for path in sorted((ROOT / "app" / "parsers").glob("*.py"))
    if path.stem != "__init__"
]
hiddenimports += [
    # uvicorn resolves its own implementation classes by string name.
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

# Optional: drop icon.ico next to this spec and it gets picked up. Without it
# the .exe keeps the default PyInstaller icon - ugly, but not fatal.
icon_path = Path(SPECPATH) / "icon.ico"
icon = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(ROOT / "app" / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Never pull Chromium into the build, even if it is installed in the
    # environment doing the building.
    excludes=["playwright", "tkinter", "pytest", "lxml.html.clean"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="webnoveltoepub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Console window on purpose: it is where the local address and the output
    # folder are printed, and closing it is how you stop the server.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
