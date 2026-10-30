from pathlib import Path

from mangareader.library.classify import SourceEntry
from mangareader.library.model import ChapterSpan, Kind
from mangareader.ui.reader.layout import (Direction, Mode, group_index, is_wide, place_group, place_ribbon,
                                          spread_groups, view_groups)
from mangareader.ui.reader.navigation import Position, chapter_starts, current_chapter, step, step_chapter

P, W = (1000, 1500), (2000, 1500)


def entry(chapters, pages=40):
    return SourceEntry(Path("x.cbz"), Kind.VOLUME, None, "x", pages, chapters, None)


def span(start):
    return ChapterSpan(f"Глава {start}", start, str(start))


def test_is_wide():
    assert is_wide(W) and not is_wide(P) and not is_wide(None)


def test_spread_groups():
    assert spread_groups([P] * 6, 0) == [[0], [1, 2], [3, 4], [5]]
    assert spread_groups([P] * 6, 1) == [[0], [1], [2, 3], [4, 5]]
    assert spread_groups([P, P, W, P, P], 0) == [[0], [1], [2], [3, 4]]
    assert spread_groups([P, None, P], 0) == [[0], [1, 2]]       # неизвестный размер считается обычной страницей
    assert spread_groups([], 0) == []


def test_view_groups_modes():
    assert view_groups(Mode.SINGLE, [P] * 3, 0) == [[0], [1], [2]]
    assert view_groups(Mode.SPREAD, [P] * 3, 0) == [[0], [1, 2]]
    assert view_groups(Mode.RIBBON, [P] * 3, 0) == [[0, 1, 2]]
    assert group_index([[0], [1, 2]], 2) == 1 and group_index([[0], [1, 2]], 0) == 0


def test_place_group_rtl_normalizes_height():
    placed = place_group([1, 2], [P, P, (500, 750)], Direction.RTL)
    by_page = {p.page: p for p in placed}
    assert by_page[1].x > by_page[2].x and by_page[2].h == by_page[1].h == 1500 and by_page[2].w == 1000
    assert (by_page[2].orig_w, by_page[2].orig_h) == (500, 750)


def test_place_group_ltr_and_unknown_size():
    placed = place_group([0, 1], [None, P], Direction.LTR)
    assert [p.page for p in sorted(placed, key=lambda p: p.x)] == [0, 1]
    assert (placed[0].orig_w, placed[0].orig_h) == (1000, 1500)


def test_place_ribbon_normalizes_width():
    placed = place_ribbon([(800, 1000), (400, 500)])
    assert [(p.y, p.w, p.h) for p in placed] == [(0, 800, 1000), (1000, 800, 1000)]


def test_step_across_entries():
    groups = [[0], [1, 2]]
    assert step(Position(0, 0), groups, [3, 5], True) == Position(0, 1)
    assert step(Position(0, 1), groups, [3, 5], True) == Position(1, 0)
    assert step(Position(1, 0), [[0]], [3, 5], False) == Position(0, 2)
    assert step(Position(1, 4), [[0], [1, 2], [3, 4]], [3, 5], True) is None
    assert step(Position(0, 0), [[0]], [3, 5], False) is None
    assert step(Position(0, 2), groups, [3, 0, 5], True) == Position(2, 0)   # закрытый паролем источник пропускается


def test_chapter_navigation():
    e = [entry(chapters=[]), entry(chapters=[span(0), span(10), span(30)])]
    starts = chapter_starts(e)
    assert starts == [Position(0, 0), Position(1, 0), Position(1, 10), Position(1, 30)]
    assert step_chapter(Position(1, 12), starts, True) == Position(1, 30)
    assert step_chapter(Position(1, 12), starts, False) == Position(1, 0)
    assert step_chapter(Position(1, 30), starts, True) is None
    assert current_chapter(Position(1, 12), starts) == Position(1, 10)


def test_chapter_starts_adds_page_zero():
    assert chapter_starts([entry(chapters=[span(5)])]) == [Position(0, 0), Position(0, 5)]
