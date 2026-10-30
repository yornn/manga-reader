import shutil

import pytest
from PySide6.QtWidgets import QPushButton

from helpers import library
from mangareader.library.catalog import Section, SectionKind, Sort, Status
from mangareader.library.library_scan import scan_library
from mangareader.ui.dialogs import errors
from mangareader.ui.library import shelf_dialog
from mangareader.ui.library.page import LibraryPage
from mangareader.ui.toast import Toast


@pytest.fixture
def page(qtbot, services, tmp_path):
    services.catalog.add_root(library(tmp_path))
    scan_library(services.catalog, services.store, services.ctx)
    p = LibraryPage(services)
    qtbot.addWidget(p)
    p.resize(1000, 700)
    p.reload()
    return p


def titles(p):
    return [c.title for c in p.visible_cards()]


def all_actions(menu):
    for action in menu.actions():
        yield action
        if action.menu():
            yield from all_actions(action.menu())


def action(menu, text):
    return next(a for a in all_actions(menu) if a.text() == text)


def test_search_status_and_sort(page):
    page.search.setText("ведь")
    assert titles(page) == ["Ведьмак"]
    page.search.clear()
    page.status_buttons[Status.READING].click()
    assert titles(page) == []
    page.status_buttons[None].click()
    page.sort_combo.setCurrentIndex(page.sort_combo.findData(Sort.TITLE))
    assert titles(page) == ["Artbook", "Berserk", "Ведьмак"]
    assert page.sort_combo.itemText(0) == "Недавно открытые"


def test_continue_row_only_in_all(page, services):
    c = next(c for c in services.catalog.cards() if c.title == "Berserk")
    src = c.cover_source_id
    services.store.set_progress(src, 1, False, 0.5)
    services.catalog.touch(c.id, src, ["Том 1", "стр. 2"])
    page.reload()
    assert [k.series_id for k in page.continue_row.cards()] == [c.id] and page.continue_row.isVisibleTo(page)
    assert page.continue_row.cards()[0].where_label.text() == "Том 1 · стр. 2"
    page.nav.select(Section(SectionKind.FAVORITES))
    assert not page.continue_row.isVisibleTo(page)


def test_tile_menu_favorite_and_new_shelf(page, services, monkeypatch):
    monkeypatch.setattr(shelf_dialog, "ask_shelf", lambda *a, **k: ("Сэйнэн", "sword"))
    sid = page.visible_cards()[0].id
    action(page.tile_menu(sid), "В избранное").trigger()
    assert services.catalog.card(sid).favorite
    action(page.tile_menu(sid), "Новая полка…").trigger()
    shelf = services.catalog.shelves()[0]
    assert services.catalog.card(sid).shelf_ids == {shelf.id}
    page.nav.select(Section(SectionKind.SHELF, shelf.id))
    assert titles(page) == [services.catalog.card(sid).title]
    action(page.tile_menu(sid), f"Убрать с полки «{shelf.name}»").trigger()
    assert titles(page) == []


def test_read_marks_and_remove_from_menu(page, services):
    sid = page.visible_cards()[0].id

    def menu():
        return [a.text() for a in all_actions(page.tile_menu(sid))]
    assert "Отметить прочитанным" in menu() and "Отметить непрочитанным" not in menu()
    assert "Убрать из библиотеки" not in menu()                       # scanned series leave with their folder only
    action(page.tile_menu(sid), "Отметить прочитанным").trigger()
    assert services.catalog.card(sid).status is Status.FINISHED and "Отметить непрочитанным" in menu()


def test_unavailable_tile_click_shows_message(page):
    shutil.rmtree(next(c.path for c in page.visible_cards() if c.title == "Berserk"))
    page.reload()
    row = next(r for r in range(1, page.model.rowCount()) if not page.model.card_at(r).available)
    page.grid.clicked.emit(page.model.index(row))
    assert Toast.last_text() == "Серия недоступна: папка или файл не найдены"


def test_tile_click_opens_series(page, qtbot):
    with qtbot.waitSignal(page.open_series) as b:
        page.grid.clicked.emit(page.model.index(1))
    assert b.args == [page.model.card_at(1).id]
    assert [a.text() for a in page.open_menu().actions()] == ["Файл…", "Папку…"]


def test_delete_current_shelf_returns_to_all(page, services, monkeypatch):
    shelf = services.catalog.add_shelf("Полка", "book")
    page.reload()
    page.nav.select(Section(SectionKind.SHELF, shelf))
    question = "Удалить полку «Полка»? Серии останутся в библиотеке"
    monkeypatch.setattr(errors, "confirm", lambda parent, text: text == question)
    page.nav.shelf_delete_requested.emit(shelf)
    assert services.catalog.shelves() == [] and page.nav.section() == Section()


def test_empty_library_hint(qtbot, services):
    p = LibraryPage(services)
    qtbot.addWidget(p)
    p.reload()
    assert p.empty_hint.isVisibleTo(p) and p.model.rowCount() == 1
    with qtbot.waitSignal(p.settings_requested):
        p.empty_hint.findChild(QPushButton).click()


def test_continue_row_replaces_cards_and_fits_narrow_window(qtbot, services):
    from helpers import card
    from mangareader.ui.library.continue_row import ContinueCard, ContinueRow
    row = ContinueRow(services.covers)
    qtbot.addWidget(row)
    cards = [card(id=i, title=f"Серия {i}", opened=1, pages_total=10, pages_read=1, last_opened_at=1.0)
             for i in range(5)]
    for _ in range(3):
        row.set_cards(cards)
    assert len([w for w in row.findChildren(ContinueCard) if w.isVisibleTo(row)]) == 5
    assert row.minimumSizeHint().width() < 600            # five cards scroll instead of widening the window


def test_enter_opens_tile(page, qtbot):
    from PySide6.QtCore import Qt
    page.grid.setFocus()
    page.grid.setCurrentIndex(page.model.index(1))
    with qtbot.waitSignal(page.open_series) as b:
        qtbot.keyClick(page.grid, Qt.Key_Return)
    assert b.args == [page.model.card_at(1).id]
