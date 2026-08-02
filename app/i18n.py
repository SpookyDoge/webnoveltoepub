"""UI translation handling.

The source of truth is the set of `web/locales/<code>.json` files. The backend
only discovers them and exposes the list of languages - adding a translation
means dropping in one file, with no code changes.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel

from .config import LOCALES_DIR

log = logging.getLogger(__name__)

#: Language code: "pl", "en", "pt-BR". Also validates the path (no traversal).
LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")


class LanguageInfo(BaseModel):
    code: str
    name: str


def available_languages(locales_dir: Path | None = None) -> list[LanguageInfo]:
    directory = locales_dir or LOCALES_DIR
    languages: list[LanguageInfo] = []
    if not directory.is_dir():
        log.warning("Translations directory does not exist: %s", directory)
        return languages

    for path in sorted(directory.glob("*.json")):
        code = path.stem
        if not LANG_CODE_RE.match(code):
            log.warning("Skipping translation file with an invalid name: %s", path.name)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load translations %s: %s", path.name, exc)
            continue
        name = (data.get("_meta") or {}).get("name") or code
        languages.append(LanguageInfo(code=code, name=name))

    return languages


def load_language(code: str, locales_dir: Path | None = None) -> dict | None:
    if not LANG_CODE_RE.match(code):
        return None
    path = (locales_dir or LOCALES_DIR) / f"{code}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not load translations %s: %s", code, exc)
        return None
