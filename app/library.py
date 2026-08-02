"""Persistent registry of converted novels.

Storage is a single JSON file rather than SQLite: the data is tiny (one record
per novel), writes happen once per conversion, and a self-hoster can open the
file, fix a path or delete a row with a text editor. SQLite would buy
concurrency we do not need and cost readability we do.

What it does need is safety against a half-written file: writes go to a
temporary file in the same directory and are swapped in with os.replace(),
which is atomic. A process-wide lock serialises writers, because conversions
run in worker threads and two of them can finish at once.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings, get_settings
from .models import AppSettings, AutoUpdateRun, LibraryEntry

log = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()


def entry_id(source_url: str) -> str:
    """Stable id for a novel - the same URL always yields the same id.

    Deliberately the same derivation as the EPUB's `dc:identifier`, so a file
    and its library entry can always be matched up.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source_url))


def utc_now() -> str:
    """Timestamp for library rows - UTC, second resolution, ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_json(path: Path, what: str) -> dict:
    """Reads a JSON file, treating any problem as "not there yet".

    A corrupt file must not take the app down - the user would lose the
    ability to convert anything at all over a bad settings row.
    """
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read the %s at %s: %s", what, path, exc)
        return {}


def write_json(path: Path, payload: dict) -> None:
    """Atomic write: a crash mid-save must not leave a truncated file."""
    with _WRITE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Written in the target's own directory: os.replace is only
            # atomic within a single filesystem.
            fd, tmp_name = tempfile.mkstemp(
                dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                    json.dump(payload, tmp, ensure_ascii=False, indent=2)
                os.replace(tmp_name, path)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            # Losing this is annoying; losing the conversion the user just
            # waited minutes for is worse.
            log.warning("Could not write %s: %s", path, exc)


class Library:
    """Reads and writes the library file. Cheap to construct; no state cached.

    Nothing is held in memory between calls: the file is small, and re-reading
    means an entry edited by hand (or by another process) is picked up.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path: Path = self.settings.resolved_library_path()

    # -- Reading ------------------------------------------------------------

    def load(self) -> list[LibraryEntry]:
        raw = read_json(self.path, "library")
        entries: list[LibraryEntry] = []
        for item in raw.get("entries", []):
            try:
                entries.append(LibraryEntry(**item))
            except Exception as exc:  # noqa: BLE001 - one bad row, not all of them
                log.warning("Skipping malformed library entry: %s", exc)
        return entries

    def get(self, entry_key: str) -> LibraryEntry | None:
        return next((e for e in self.load() if e.id == entry_key), None)

    # -- Writing ------------------------------------------------------------

    def save(self, entries: list[LibraryEntry]) -> None:
        write_json(
            self.path,
            {"version": 1, "entries": [entry.model_dump() for entry in entries]},
        )

    def upsert(self, entry: LibraryEntry) -> LibraryEntry:
        """Adds the novel or refreshes the existing row, keeping created_at."""
        entries = self.load()
        for index, existing in enumerate(entries):
            if existing.id == entry.id:
                entry = entry.model_copy(update={"created_at": existing.created_at})
                entries[index] = entry
                break
        else:
            entries.append(entry)

        self.save(entries)
        return entry

    def delete(self, entry_key: str, *, delete_file: bool = False) -> LibraryEntry | None:
        entries = self.load()
        removed = next((e for e in entries if e.id == entry_key), None)
        if removed is None:
            return None

        self.save([e for e in entries if e.id != entry_key])

        if delete_file and removed.file_path:
            try:
                Path(removed.file_path).unlink(missing_ok=True)
                log.info("Deleted %s", removed.file_path)
            except OSError as exc:
                log.warning("Could not delete %s: %s", removed.file_path, exc)

        return removed

    # -- Building entries ---------------------------------------------------

    @staticmethod
    def build_entry(
        *,
        source_url: str,
        parser_name: str,
        title: str,
        author: str,
        language: str,
        cover_url: str | None,
        file_path: Path | None,
        chapter_count: int,
        last_chapter_url: str | None,
    ) -> LibraryEntry:
        timestamp = utc_now()
        return LibraryEntry(
            id=entry_id(source_url),
            source_url=source_url,
            parser=parser_name,
            title=title,
            author=author,
            language=language,
            cover_url=cover_url,
            file_path=str(file_path) if file_path else None,
            chapter_count=chapter_count,
            last_chapter_url=last_chapter_url,
            created_at=timestamp,
            updated_at=timestamp,
        )


class SettingsStore:
    """Persisted app settings plus the history of automatic update runs.

    A separate file from the library on purpose: saving a checkbox should not
    rewrite every novel's row, and a corrupt library must not cost the user
    their configuration (or the other way round).
    """

    #: How many past runs to keep. Enough to see a pattern, small enough that
    #: the file stays readable by hand.
    MAX_RUNS = 20

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path: Path = self.settings.resolved_library_path().with_name("settings.json")

    def load(self) -> AppSettings:
        raw = read_json(self.path, "settings").get("settings", {})
        try:
            return AppSettings(**raw)
        except Exception as exc:  # noqa: BLE001 - fall back to defaults, never crash
            log.warning("Malformed settings, using defaults: %s", exc)
            return AppSettings()

    def save(self, app_settings: AppSettings) -> AppSettings:
        payload = read_json(self.path, "settings")
        payload["version"] = 1
        payload["settings"] = app_settings.model_dump()
        write_json(self.path, payload)
        return app_settings

    # -- Run history --------------------------------------------------------

    def runs(self) -> list[AutoUpdateRun]:
        raw = read_json(self.path, "settings").get("runs", [])
        history: list[AutoUpdateRun] = []
        for item in raw:
            try:
                history.append(AutoUpdateRun(**item))
            except Exception as exc:  # noqa: BLE001
                log.warning("Skipping malformed run entry: %s", exc)
        return history

    def record_run(self, run: AutoUpdateRun) -> None:
        payload = read_json(self.path, "settings")
        history = [*payload.get("runs", []), run.model_dump()]
        payload["version"] = 1
        payload["runs"] = history[-self.MAX_RUNS :]
        write_json(self.path, payload)

    def last_run_at(self) -> str | None:
        """When the library was last actually checked.

        Skipped passes are excluded on purpose: they are log entries about a
        check that did *not* happen, and counting one would restart the
        interval clock - postponing the real check by a whole interval.
        """
        history = [run for run in self.runs() if run.status != "skipped"]
        return history[-1].finished_at if history else None
