"""Moving through pages, sources and chapters in reading order."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mangareader.library.classify import SourceEntry
from mangareader.ui.reader.layout import group_index


@dataclass(frozen=True, order=True)
class Position:
    entry: int
    page: int


def step(pos: Position, groups: Sequence[Sequence[int]], page_counts: Sequence[int],
         forward: bool) -> Position | None:
    gi = group_index(groups, pos.page)
    if forward:
        if gi + 1 < len(groups):
            return Position(pos.entry, groups[gi + 1][0])
        for e in range(pos.entry + 1, len(page_counts)):
            if page_counts[e] > 0:
                return Position(e, 0)
        return None
    if gi > 0:
        return Position(pos.entry, groups[gi - 1][0])
    for e in range(pos.entry - 1, -1, -1):
        if page_counts[e] > 0:
            return Position(e, page_counts[e] - 1)
    return None


def chapter_starts(entries: Sequence[SourceEntry]) -> list[Position]:
    starts = []
    for index, entry in enumerate(entries):
        if entry.page_count == 0:
            continue
        pages = sorted({c.start_page for c in entry.chapters} | {0})
        starts.extend(Position(index, p) for p in pages)
    return starts


def current_chapter(pos: Position, starts: Sequence[Position]) -> Position | None:
    before = [s for s in starts if s <= pos]
    return before[-1] if before else None


def step_chapter(pos: Position, starts: Sequence[Position], forward: bool) -> Position | None:
    if forward:
        return next((s for s in starts if s > pos), None)
    current = current_chapter(pos, starts)
    earlier = [s for s in starts if current is not None and s < current]
    return earlier[-1] if earlier else None
