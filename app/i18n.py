"""Obsluga tlumaczen UI.

Zrodlem prawdy sa pliki `web/locales/<kod>.json`. Backend jedynie je wykrywa
i wystawia liste jezykow - dodanie tlumaczenia to wrzucenie jednego pliku,
bez zmian w kodzie.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel

from .config import LOCALES_DIR

log = logging.getLogger(__name__)

#: Kod jezyka: "pl", "en", "pt-BR". Waliduje tez sciezke (zero traversalu).
LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")


class LanguageInfo(BaseModel):
    code: str
    name: str


def available_languages(locales_dir: Path | None = None) -> list[LanguageInfo]:
    directory = locales_dir or LOCALES_DIR
    languages: list[LanguageInfo] = []
    if not directory.is_dir():
        log.warning("Katalog z tlumaczeniami nie istnieje: %s", directory)
        return languages

    for path in sorted(directory.glob("*.json")):
        code = path.stem
        if not LANG_CODE_RE.match(code):
            log.warning("Pomijam plik tlumaczen o niepoprawnej nazwie: %s", path.name)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Nie udalo sie wczytac tlumaczen %s: %s", path.name, exc)
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
        log.warning("Nie udalo sie wczytac tlumaczen %s: %s", code, exc)
        return None
