"""Turning a series folder into a tree of volumes and chapters (spec 5.1)."""
from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mangareader.library.model import ChapterMark, ChapterSpan, Kind
from mangareader.sources.base import PageRef, SourceError, is_junk
from mangareader.sources.detect import SOURCE_EXTS
from mangareader.sources.folder import has_direct_images
from mangareader.sources.natsort import natural_key

START_TITLE = "Начало"
VOLUME_PAGES = 100

_NUM = r"(\d+(?:\.\d+)?)"
_CH_WORD = r"(?:\b(?:ch|chap|chapter|ep|episode)\.?|(?<![a-zа-яё])c|глава|\bгл\.?)"
_VOL_WORD = r"(?:\b(?:vol|volume|tome)\.?|(?<![a-zа-яё])v|\bтом|\bт\.)"
_CHAPTER_KIND = re.compile(rf"{_CH_WORD}\s*\d|第\s*\d+\s*話|話|глава", re.IGNORECASE)
_VOLUME_KIND = re.compile(rf"{_VOL_WORD}\s*\d|\bтом\b|第\s*\d+\s*巻|巻", re.IGNORECASE)
_NUMBER_BY_KIND = {
    Kind.CHAPTER: [re.compile(rf"{_CH_WORD}\s*{_NUM}", re.IGNORECASE), re.compile(rf"第\s*{_NUM}\s*話")],
    Kind.VOLUME: [re.compile(rf"{_VOL_WORD}\s*{_NUM}", re.IGNORECASE), re.compile(rf"第\s*{_NUM}\s*巻")],
}
_ANY_JP_NUMBER = re.compile(rf"第\s*{_NUM}\s*[話巻]")
_FIRST_NUMBER = re.compile(_NUM)
_BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}")
_PLAIN_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def name_kind(name: str) -> Kind | None:
    if _CHAPTER_KIND.search(name):
        return Kind.CHAPTER
    if _VOLUME_KIND.search(name):
        return Kind.VOLUME
    return None


def _normalize_number(text: str) -> str:
    whole, dot, frac = text.partition(".")
    whole = whole.lstrip("0") or "0"
    return f"{whole}.{frac}" if dot and frac else whole


def extract_number(name: str, kind: Kind | None = None) -> str | None:
    text = _BRACKETS.sub(" ", name)
    patterns = list(_NUMBER_BY_KIND.get(kind, [])) + [_ANY_JP_NUMBER, _FIRST_NUMBER]
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return _normalize_number(m.group(1))
    return None


def _number_value(number: str | None) -> float:
    try:
        return float(number) if number is not None else math.inf
    except ValueError:
        return math.inf


def internal_chapters(pages: Sequence[PageRef]) -> list[ChapterSpan]:
    parts = [p.folder.split("/") if p.folder else [] for p in pages]
    if not parts:
        return []
    prefix = parts[0]
    for ps in parts[1:]:
        n = 0
        while n < min(len(prefix), len(ps)) and prefix[n] == ps[n]:
            n += 1
        prefix = prefix[:n]
    groups = [ps[len(prefix)] if len(ps) > len(prefix) else "" for ps in parts]
    if len({g for g in groups if g}) < 2:
        return []
    spans = []
    previous = None
    for index, group in enumerate(groups):
        if group == previous and spans:
            continue
        previous = group
        if not group:
            spans.append(ChapterSpan(START_TITLE, index))
            continue
        number = extract_number(group, Kind.CHAPTER)
        spans.append(ChapterSpan(f"Глава {number}" if number else group, index, number))
    return spans


def _mark_title(mark: ChapterMark) -> str:
    return f"Глава {mark.number} — {mark.title}" if mark.title else f"Глава {mark.number}"


def chapter_spans(internal: Sequence[ChapterSpan], marks: Sequence[ChapterMark]) -> list[ChapterSpan]:
    by_start = {s.start_page: s for s in internal}
    for m in marks:
        by_start[m.page_index] = ChapterSpan(_mark_title(m), m.page_index, m.number, True)
    spans = sorted(by_start.values(), key=lambda s: s.start_page)
    if spans and spans[0].start_page != 0:
        spans.insert(0, ChapterSpan(START_TITLE, 0))
    return spans


def suggest_chapter_number(spans: Sequence[ChapterSpan], page: int) -> str:
    for span in sorted(spans, key=lambda s: s.start_page, reverse=True):
        if span.start_page <= page and span.number and _PLAIN_NUMBER.fullmatch(span.number):
            return str(int(float(span.number)) + 1)
    return "1"


@dataclass(frozen=True)
class SourceInfo:
    page_count: int
    internal: Sequence[ChapterSpan]
    kind_override: Kind | None
    marks: Sequence[ChapterMark]
    record_id: int | None
    locked: bool = False


@dataclass
class SourceEntry:
    path: Path
    kind: Kind
    number: str | None
    title: str
    page_count: int
    chapters: list[ChapterSpan]
    record_id: int | None
    locked: bool = False
    in_volume_folder: bool = False


@dataclass
class TreeNode:
    kind: Kind
    title: str
    number: str | None
    entries: list[SourceEntry]
    folder: Path | None = None


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


@dataclass
class SeriesTree:
    root: Path
    title: str
    nodes: list[TreeNode]
    failed: list[tuple[Path, str]] = field(default_factory=list)

    def reading_order(self) -> list[SourceEntry]:
        return [e for n in self.nodes for e in n.entries]

    def index_of(self, path: Path) -> int | None:
        return next((i for i, e in enumerate(self.reading_order()) if _same(e.path, path)), None)


def _stem(path: Path) -> str:
    return path.name if path.is_dir() else path.stem


def _visible(entry: Path) -> bool:
    return not entry.name.startswith(".") and not is_junk(entry.name)


def _contains_sources(folder: Path) -> bool:
    try:
        for child in folder.iterdir():
            if not _visible(child):
                continue
            if child.is_file() and child.suffix.lower() in SOURCE_EXTS:
                return True
            if child.is_dir() and has_direct_images(child):
                return True
    except OSError:
        return False
    return False


def list_children(folder: Path) -> tuple[list[Path], list[Path]]:
    sources, volume_folders = [], []
    try:
        children = sorted(folder.iterdir(), key=lambda p: natural_key(p.name))
    except OSError:
        return [], []
    for child in children:
        if not _visible(child):
            continue
        if child.is_file():
            if child.suffix.lower() in SOURCE_EXTS:
                sources.append(child)
        elif child.is_dir():
            if has_direct_images(child):
                sources.append(child)
            elif _contains_sources(child):
                volume_folders.append(child)
    return sources, volume_folders


def is_volume_folder(folder: Path) -> bool:
    if name_kind(folder.name) is Kind.VOLUME:
        return True
    if _PLAIN_NUMBER.fullmatch(folder.name.strip()):
        sources, _ = list_children(folder)
        return bool(sources) and all(name_kind(_stem(s)) is Kind.CHAPTER for s in sources)
    return False


def find_series_root(opened: Path) -> Path:
    parent = Path(opened).parent
    return parent.parent if is_volume_folder(parent) else parent


def _sort_key(item) -> tuple:
    return _number_value(item.number), natural_key(item.title)


def classify_series(root: Path, probe: Callable[[Path], SourceInfo]) -> SeriesTree:
    failed: list[tuple[Path, str]] = []

    def make_entry(path: Path, in_folder: bool) -> SourceEntry | None:
        try:
            info = probe(path)
        except SourceError as e:
            failed.append((path, str(e)))
            return None
        if info.page_count == 0 and not info.locked:
            return None
        name = _stem(path)
        if in_folder:
            kind = Kind.CHAPTER
        elif info.kind_override:
            kind = info.kind_override
        elif info.internal:
            kind = Kind.VOLUME
        else:
            kind = name_kind(name) or (Kind.VOLUME if info.page_count >= VOLUME_PAGES else Kind.CHAPTER)
        number = extract_number(name, kind)
        word = "Том" if kind is Kind.VOLUME else "Глава"
        title = f"{word} {number}" if number else name
        chapters = chapter_spans(info.internal, info.marks) if kind is Kind.VOLUME else []
        return SourceEntry(path, kind, number, title, info.page_count, chapters, info.record_id, info.locked,
                           in_folder)

    volumes: list[TreeNode] = []
    chapters: list[TreeNode] = []
    sources, volume_folders = list_children(root)
    for source in sources:
        entry = make_entry(source, False)
        if entry:
            node = TreeNode(entry.kind, entry.title, entry.number, [entry])
            (volumes if entry.kind is Kind.VOLUME else chapters).append(node)
    for folder in volume_folders:
        entries = [e for e in (make_entry(s, True) for s in list_children(folder)[0]) if e]
        if entries:
            entries.sort(key=_sort_key)
            number = extract_number(folder.name, Kind.VOLUME)
            volumes.append(TreeNode(Kind.VOLUME, f"Том {number}" if number else folder.name, number, entries,
                                    folder))
    volumes.sort(key=_sort_key)
    chapters.sort(key=_sort_key)
    return SeriesTree(root, root.name, volumes + chapters, failed)
