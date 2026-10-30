"""SQLite store for progress, chapter marks, kind overrides and per-series preferences."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

from mangareader.library.model import ChapterMark, ChapterSpan, Kind, Progress, SeriesPrefs, SourceRecord

log = logging.getLogger("mangareader.store")

MIGRATIONS = [
    """
    CREATE TABLE sources(id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_key TEXT NOT NULL UNIQUE,
      size INTEGER NOT NULL, mtime REAL NOT NULL, fingerprint TEXT NOT NULL, page_count INTEGER NOT NULL,
      chapters_json TEXT NOT NULL DEFAULT '[]', kind_override TEXT CHECK(kind_override IN ('volume','chapter')),
      spread_offset INTEGER NOT NULL DEFAULT 0, last_seen REAL NOT NULL);
    CREATE INDEX sources_fp ON sources(fingerprint);
    CREATE TABLE progress(source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
      position INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
    CREATE TABLE chapter_marks(source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
      page_index INTEGER NOT NULL, number TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(source_id, page_index));
    CREATE TABLE series_prefs(series_key TEXT PRIMARY KEY, direction TEXT NOT NULL, mode TEXT NOT NULL);
    """,
]

_COLUMNS = "id, path, size, mtime, fingerprint, page_count, chapters_json, kind_override, spread_offset"


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _chapters_to_json(chapters: Sequence[ChapterSpan]) -> str:
    return json.dumps([[c.title, c.start_page, c.number, c.is_mark] for c in chapters], ensure_ascii=False)


def _chapters_from_json(text: str) -> tuple[ChapterSpan, ...]:
    return tuple(ChapterSpan(t, int(s), n, bool(m)) for t, s, n, m in json.loads(text))


def _record(row) -> SourceRecord:
    rid, path, size, mtime, fp, count, chapters, kind, offset = row
    return SourceRecord(rid, Path(path), size, mtime, fp, count, _chapters_from_json(chapters),
                        Kind(kind) if kind else None, offset)


class Store:
    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._clock = 0.0
        self._conn = self._open()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= len(MIGRATIONS):
            return
        if version > 0:
            backup = sqlite3.connect(self._path.with_name(self._path.name + ".bak"))
            conn.backup(backup)
            backup.close()
        for n in range(version, len(MIGRATIONS)):
            conn.executescript(f"BEGIN; {MIGRATIONS[n]}; PRAGMA user_version = {n + 1}; COMMIT;")

    def _open(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            self._migrate(conn)
            return conn
        except sqlite3.DatabaseError as e:
            conn.close()
            corrupt = self._path.with_name(f"{self._path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
            log.warning("database %s is unreadable (%s); moved to %s", self._path, e, corrupt.name)
            shutil.move(self._path, corrupt)
            conn = self._connect()
            self._migrate(conn)
            return conn

    def _now(self) -> float:
        self._clock = max(time.time(), self._clock + 1e-6)
        return self._clock

    def _by_id(self, source_id: int) -> SourceRecord:
        return _record(self._conn.execute(f"SELECT {_COLUMNS} FROM sources WHERE id=?", (source_id,)).fetchone())

    def find_by_path(self, path: Path) -> SourceRecord | None:
        with self._lock:
            row = self._conn.execute(f"SELECT {_COLUMNS} FROM sources WHERE path_key=?", (_key(path),)).fetchone()
        return _record(row) if row else None

    def register(self, path: Path, size: int, mtime: float, fingerprint: str, page_count: int,
                 chapters: Sequence[ChapterSpan]) -> SourceRecord:
        values = (str(path), _key(path), size, mtime, fingerprint, page_count, _chapters_to_json(chapters),
                  time.time())
        set_sql = ("UPDATE sources SET path=?, path_key=?, size=?, mtime=?, fingerprint=?, page_count=?, "
                   "chapters_json=?, last_seen=? WHERE id=?")
        with self._lock:
            row = self._conn.execute("SELECT id FROM sources WHERE path_key=?", (_key(path),)).fetchone()
            if row is None:
                candidates = self._conn.execute("SELECT id, path FROM sources WHERE fingerprint=? ORDER BY id",
                                                (fingerprint,)).fetchall()
                row = next(((cid,) for cid, cpath in candidates if not Path(cpath).exists()), None)
            if row is not None:
                self._conn.execute(set_sql, values + (row[0],))
                return self._by_id(row[0])
            cur = self._conn.execute(
                "INSERT INTO sources(path, path_key, size, mtime, fingerprint, page_count, chapters_json, last_seen)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
            return self._by_id(cur.lastrowid)

    def set_kind_override(self, source_id: int, kind: Kind | None) -> None:
        with self._lock:
            self._conn.execute("UPDATE sources SET kind_override=? WHERE id=?",
                               (kind.value if kind else None, source_id))

    def set_spread_offset(self, source_id: int, offset: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE sources SET spread_offset=? WHERE id=?", (offset, source_id))

    def progress(self, source_id: int) -> Progress | None:
        with self._lock:
            row = self._conn.execute("SELECT position, finished, updated_at FROM progress WHERE source_id=?",
                                     (source_id,)).fetchone()
        return Progress(row[0], bool(row[1]), row[2]) if row else None

    def set_progress(self, source_id: int, position: int, finished: bool) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO progress(source_id, position, finished, updated_at)"
                               " VALUES (?, ?, ?, ?)", (source_id, position, int(finished), self._now()))

    def latest_progress(self, source_ids: Iterable[int]) -> int | None:
        ids = list(source_ids)
        if not ids:
            return None
        marks = ",".join("?" * len(ids))
        with self._lock:
            row = self._conn.execute(f"SELECT source_id FROM progress WHERE source_id IN ({marks})"
                                     " ORDER BY updated_at DESC LIMIT 1", ids).fetchone()
        return row[0] if row else None

    def chapter_marks(self, source_id: int) -> list[ChapterMark]:
        with self._lock:
            rows = self._conn.execute("SELECT page_index, number, title FROM chapter_marks WHERE source_id=?"
                                      " ORDER BY page_index", (source_id,)).fetchall()
        return [ChapterMark(*r) for r in rows]

    def set_chapter_mark(self, source_id: int, mark: ChapterMark) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO chapter_marks(source_id, page_index, number, title)"
                               " VALUES (?, ?, ?, ?)", (source_id, mark.page_index, mark.number, mark.title))

    def delete_chapter_mark(self, source_id: int, page_index: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM chapter_marks WHERE source_id=? AND page_index=?",
                               (source_id, page_index))

    def series_prefs(self, series: Path) -> SeriesPrefs | None:
        with self._lock:
            row = self._conn.execute("SELECT direction, mode FROM series_prefs WHERE series_key=?",
                                     (_key(series),)).fetchone()
        return SeriesPrefs(*row) if row else None

    def set_series_prefs(self, series: Path, prefs: SeriesPrefs) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO series_prefs(series_key, direction, mode) VALUES (?, ?, ?)",
                               (_key(series), prefs.direction, prefs.mode))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
