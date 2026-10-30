"""Which pages are shown together, and where they sit in the scene."""
from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from mangareader.export.geometry import Placed

DEFAULT_PAGE_SIZE = (1000, 1500)

Size = tuple[int, int] | None


class Mode(StrEnum):
    SINGLE = "single"
    SPREAD = "spread"
    RIBBON = "ribbon"
    HRIBBON = "hribbon"


RIBBON_MODES = frozenset({Mode.RIBBON, Mode.HRIBBON})


class Direction(StrEnum):
    RTL = "rtl"
    LTR = "ltr"


def is_wide(size: Size) -> bool:
    return size is not None and size[0] > size[1]


def spread_groups(sizes: Sequence[Size], offset: int) -> list[list[int]]:
    n = len(sizes)
    groups: list[list[int]] = []
    i = 0
    if n:
        groups.append([0])
        i = 1
    if offset and i < n and not is_wide(sizes[i]):
        groups.append([i])
        i += 1
    while i < n:
        if is_wide(sizes[i]):
            groups.append([i])
            i += 1
        elif i + 1 < n and not is_wide(sizes[i + 1]):
            groups.append([i, i + 1])
            i += 2
        else:
            groups.append([i])
            i += 1
    return groups


def view_groups(mode: Mode, sizes: Sequence[Size], offset: int) -> list[list[int]]:
    if mode is Mode.SPREAD:
        return spread_groups(sizes, offset)
    if mode in RIBBON_MODES:
        return [list(range(len(sizes)))] if sizes else []
    return [[i] for i in range(len(sizes))]


def group_index(groups: Sequence[Sequence[int]], page: int) -> int:
    best = 0
    for i, group in enumerate(groups):
        if page in group:
            return i
        if group and group[0] <= page:
            best = i
    return best


def _size(sizes: Sequence[Size], page: int) -> tuple[int, int]:
    size = sizes[page] if page < len(sizes) else None
    return size or DEFAULT_PAGE_SIZE


def place_group(pages: Sequence[int], sizes: Sequence[Size], direction: Direction) -> list[Placed]:
    height = max(_size(sizes, p)[1] for p in pages)
    order = list(pages) if direction is Direction.LTR else list(reversed(pages))
    placed, x = [], 0.0
    for page in order:
        w, h = _size(sizes, page)
        width = w * height / h
        placed.append(Placed(page, x, 0, width, height, w, h))
        x += width
    return placed


def place_ribbon(sizes: Sequence[Size]) -> list[Placed]:
    if not sizes:
        return []
    width = max(_size(sizes, i)[0] for i in range(len(sizes)))
    placed, y = [], 0.0
    for page in range(len(sizes)):
        w, h = _size(sizes, page)
        height = h * width / w
        placed.append(Placed(page, 0, y, width, height, w, h))
        y += height
    return placed


def place_hribbon(sizes: Sequence[Size], direction: Direction) -> list[Placed]:
    """All pages in one row at the height of the tallest; right to left puts the first page on the right."""
    if not sizes:
        return []
    height = max(_size(sizes, i)[1] for i in range(len(sizes)))
    widths = []
    for page in range(len(sizes)):
        w, h = _size(sizes, page)
        widths.append(w * height / h)
    total = sum(widths)
    placed, x = [], 0.0
    for page in range(len(sizes)):
        w, h = _size(sizes, page)
        left = x if direction is Direction.LTR else total - x - widths[page]
        placed.append(Placed(page, left, 0, widths[page], height, w, h))
        x += widths[page]
    return placed
