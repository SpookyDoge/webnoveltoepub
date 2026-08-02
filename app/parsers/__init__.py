"""Rejestr parserow.

`discover()` importuje wszystkie moduly z tego pakietu; import wystarcza,
bo `BaseParser.__init_subclass__` sam dopisuje klase do rejestru.
Dodanie nowego serwisu = dodanie jednego pliku .py w tym katalogu.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil

from .base import _REGISTRY, BaseParser, ParserError

log = logging.getLogger(__name__)

_discovered = False


def discover(force: bool = False) -> None:
    global _discovered
    if _discovered and not force:
        return
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_") or module_info.name == "base":
            continue
        try:
            importlib.import_module(f"{__name__}.{module_info.name}")
        except Exception:  # noqa: BLE001 - jeden zepsuty parser nie kladzie appki
            log.exception("Nie udalo sie zaladowac parsera %s", module_info.name)
    _discovered = True


def all_parsers() -> list[type[BaseParser]]:
    """Konkretne (nieabstrakcyjne) parsery, posortowane wg priorytetu i nazwy."""
    discover()
    concrete = [cls for cls in _REGISTRY if not inspect.isabstract(cls)]
    return sorted(concrete, key=lambda cls: (-cls.priority, cls.name))


def get_parser_class(url: str) -> type[BaseParser] | None:
    for parser_cls in all_parsers():
        if parser_cls.matches(url):
            return parser_cls
    return None


def get_parser_by_name(name: str) -> type[BaseParser] | None:
    return next((cls for cls in all_parsers() if cls.name == name), None)


__all__ = [
    "BaseParser",
    "ParserError",
    "all_parsers",
    "discover",
    "get_parser_by_name",
    "get_parser_class",
]
