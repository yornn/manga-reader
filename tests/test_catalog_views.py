from datetime import datetime
from pathlib import Path

from helpers import card
from mangareader.library.catalog import (Section, SectionKind, Sort, Status, continue_caption, continue_reading,
                                         filter_cards, format_counts, series_formats, tile_caption, when_text)


def test_search_casefold_and_yo():
    cards = [card(id=1, title="Ёлки"), card(id=2, title="BERSERK"), card(id=3, title="Vagabond")]
    assert [c.id for c in filter_cards(cards, query="елки")] == [1]
    assert [c.id for c in filter_cards(cards, query="ЕЛК")] == [1]
    assert [c.id for c in filter_cards(cards, query="serk")] == [2]


def test_sections_and_status():
    cards = [card(id=1, favorite=True, formats=("CBZ", "EPUB")), card(id=2, formats=("PDF",), shelf_ids=frozenset({7})),
             card(id=3, opened=1, pages_total=10, pages_read=3)]

    def ids(**kw):
        return [c.id for c in filter_cards(cards, sort=Sort.ADDED, **kw)]
    assert ids(section=Section(SectionKind.FAVORITES)) == [1]
    assert ids(section=Section(SectionKind.FORMAT, "EPUB")) == [1]
    assert ids(section=Section(SectionKind.SHELF, 7)) == [2]
    assert ids(status=Status.READING) == [3] and set(ids(status=Status.NOT_STARTED)) == {1, 2}


def test_sorts():
    cards = [card(id=1, title="Том 10", added_at=1), card(id=2, title="Том 2", added_at=3, last_opened_at=5),
             card(id=3, title="том 3", added_at=2, last_opened_at=9), card(id=4, title="А", added_at=4)]
    assert [c.id for c in filter_cards(cards, sort=Sort.RECENT)] == [3, 2, 4, 1]
    assert [c.id for c in filter_cards(cards, sort=Sort.TITLE)] == [4, 2, 3, 1]
    assert [c.id for c in filter_cards(cards, sort=Sort.ADDED)] == [4, 2, 3, 1]


def test_continue_reading():
    reading = [card(id=i, opened=1, pages_total=10, pages_read=1, last_opened_at=i) for i in range(1, 8)]
    other = [card(id=20, opened=1, finished=1, last_opened_at=100), card(id=21, opened=1, pages_total=10)]
    assert [c.id for c in continue_reading(reading + other)] == [7, 6, 5, 4, 3]   # 21 never opened in the reader


def test_formats():
    assert series_formats([Path("a.cbz"), Path("b.CBZ"), Path("c.pdf"), Path("d.oxps")]) == ["CBZ", "PDF", "XPS"]
    cards = [card(formats=("PDF",)), card(formats=("CBZ", "PDF"))]
    assert format_counts(cards) == [("CBZ", 1), ("PDF", 2)]


def test_captions():
    r = card(opened=1, pages_total=100, pages_read=18, where=("Том 3", "Глава 21", "стр. 45"))
    assert tile_caption(r) == "Том 3 · 18%" and continue_caption(r) == "Том 3 · Глава 21 · стр. 45"
    book = card(opened=1, pages_total=100, pages_read=62)
    assert tile_caption(book) == continue_caption(book) == "62%"
    assert tile_caption(card(opened=1, pages_total=1000, pages_read=999.5)) == "99%"
    assert tile_caption(card(opened=1, finished=1)) == "прочитано" and tile_caption(card()) == "не начато"
    assert tile_caption(card(available=False, opened=1, finished=1)) == "недоступно"


def test_when_text():
    now = datetime(2026, 10, 30, 12).timestamp()
    day = 86400
    assert [when_text(now - d * day, now) for d in (0, 1, 3, 5)] == ["сегодня", "вчера", "3 дня назад", "5 дней назад"]
    assert when_text(now - 10 * day, now) == "20.10.2026"
