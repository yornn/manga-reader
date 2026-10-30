"""Plain data shared by the library modules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Kind(StrEnum):
    VOLUME = "volume"
    CHAPTER = "chapter"


@dataclass(frozen=True)
class ChapterSpan:
    title: str
    start_page: int
    number: str | None = None
    is_mark: bool = False


@dataclass(frozen=True)
class ChapterMark:
    page_index: int
    number: str
    title: str = ""


@dataclass(frozen=True)
class SourceRecord:
    id: int
    path: Path
    size: int
    mtime: float
    fingerprint: str
    page_count: int
    chapters: tuple[ChapterSpan, ...]
    kind_override: Kind | None
    spread_offset: int


@dataclass(frozen=True)
class Progress:
    position: int
    finished: bool
    updated_at: float


@dataclass(frozen=True)
class SeriesPrefs:
    direction: str
    mode: str
