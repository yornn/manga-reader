from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

from helpers import encode, library, make_epub, make_zip, page_image
from mangareader.library.catalog import Section, Status
from mangareader.ui.library.scan_runner import ScanRunner
from mangareader.ui.reader.layout import Mode
from mangareader.ui.reader.navigation import Position
from mangareader.ui.toast import Toast


def test_single_file_series_and_where(window, qtbot, tmp_path):
    dl = tmp_path / "Загрузки"
    book = make_epub(dl / "b.epub", 40)
    make_epub(dl / "other.epub", 40)
    c = window.controller
    assert c.open_path(book, series=book)
    qtbot.wait(300)
    assert [e.path for e in c.entries] == [book] and c.where_parts() == []
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(4)})
    assert c.open_path(s / "Vol 01.cbz", series=s)
    c.next()
    assert c.where_parts() == ["Том 1", "стр. 2"]
    assert window.services.store.progress(c.record.id).fraction == 0.5


def test_tree_scanned_signal(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "c1.cbz", {"1.png": encode(page_image(1), "PNG")})
    make_zip(s / "c2.cbz", {"1.png": encode(page_image(1), "PNG")})
    with qtbot.waitSignal(window.controller.tree_scanned, timeout=5000) as b:
        window.controller.open_path(s / "c1.cbz", series=s)
    assert b.args[0].root == s


def test_scan_runner(qtbot, services, tmp_path):
    services.catalog.add_root(library(tmp_path))
    runner = ScanRunner(services)
    with qtbot.waitSignal(runner.finished, timeout=20000):
        runner.start()
        runner.start()                                   # a second start queues one more pass
    qtbot.waitUntil(lambda: not runner.running, timeout=20000)
    assert len(services.catalog.cards()) == 3 and runner.failed == []


def scanned_window(window, qtbot, tmp_path):
    window.services.catalog.add_root(library(tmp_path))
    with qtbot.waitSignal(window.scanner.finished, timeout=20000):
        window.scanner.start()
    return window


def tile_row(window, title):
    m = window.library_page.model
    return next(r for r in range(1, m.rowCount()) if m.card_at(r).title == title)


def test_starts_on_library(window):
    model = window.library_page.model
    assert window.is_library_shown() and model.data(model.index(0)) == "Открыть"


def test_tile_opens_reader_and_home_returns(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    w.library_page.grid.clicked.emit(w.library_page.model.index(tile_row(w, "Berserk")))
    assert not w.is_library_shown() and w.controller.entry.path.name == "Vol 01.cbz"
    w.controller.next()
    qtbot.keyClick(w.view, Qt.Key_Backspace)
    assert w.is_library_shown() and w.controller.source is None
    card = next(c for c in w.services.catalog.cards() if c.title == "Berserk")
    assert card.status is Status.READING and card.where == ("Том 1", "стр. 2")
    assert [k.series_id for k in w.library_page.continue_row.cards()] == [card.id]


def test_continue_card_opens_exact_place(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    w.library_page.grid.clicked.emit(w.library_page.model.index(tile_row(w, "Berserk")))
    w.controller.go_to(Position(1, 2))
    w.home_button.click()
    qtbot.mouseClick(w.library_page.continue_row.cards()[0], Qt.LeftButton)
    assert w.controller.entry.path.name == "Vol 02.cbz" and w.controller.position.page == 2


def test_open_adds_series_without_duplicates(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    lib = w.services.catalog.roots()[0].path
    assert w.open_paths([lib / "Berserk" / "Vol 02.cbz"])
    assert len(w.services.catalog.cards()) == 3
    dl = tmp_path / "Загрузки"
    book = make_epub(dl / "Книга.epub", 30)
    make_zip(dl / "x.cbz", {"1.png": encode(page_image(1), "PNG")})
    assert w.open_paths([book])
    new = next(c for c in w.services.catalog.cards() if c.path == book)
    assert new.root_id is None and new.title == "Книга"


def test_open_library_root_itself_is_refused(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    assert not w.open_paths([w.services.catalog.roots()[0].path]) and w.is_library_shown()
    assert Toast.last_text() == "Это папка библиотеки — её серии уже на главной"


def test_reader_keys_do_not_fire_on_library(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    grid = w.library_page.grid
    grid.setFocus()
    grid.setCurrentIndex(w.library_page.model.index(0))
    qtbot.keyClick(grid, Qt.Key_Right)
    assert grid.currentIndex().row() == 1
    qtbot.keyClick(grid, Qt.Key_2)
    assert w.controller.mode is Mode.SINGLE and w.is_library_shown()


def test_reader_toolbar_has_home_and_reading_gear(window, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    texts = [b.text() for b in window.toolbar.findChildren(QToolButton)]
    assert "⌂ Главная" in texts and texts.count("⚙") == 1
    assert window.gear_button.menu().actions()[0].defaultWidget() is window.reader_settings  # reading, not the app


def test_settings_from_menu_and_back(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.show_settings()
    assert window.is_library_shown() and window.library_page.content.currentWidget() is window.settings_page
    window.library_page.nav.tree.itemClicked.emit(window.library_page.nav.item_for(Section()), 0)
    assert window.library_page.content.currentIndex() == 0


def test_book_opened_from_library_is_laid_out_for_the_visible_view(window, tmp_path):
    window.open_paths([make_epub(tmp_path / "b.epub", 200)])
    viewport = window.view.viewport()
    assert window.controller._book_layout[:2] == (max(200, viewport.width()), max(200, viewport.height()))


def test_failed_open_from_library_stays_on_library(window, tmp_path):
    assert not window.open_paths([tmp_path / "nope.cbz"])
    assert window.is_library_shown()


def test_scan_signals_after_close_do_not_touch_closed_store(make_window, qtbot):
    w = make_window(qtbot)
    w.scanner.series_updated.emit()                     # starts the delayed library reload
    w.close()
    w.scanner.finished.emit()
    qtbot.wait(400)                                     # an error in a slot would fail the test here


def test_window_can_be_narrow(window, cbz_1000x1500):
    assert window.minimumSizeHint().width() <= 700         # the library, even with the empty-library hint
    window.open_paths([cbz_1000x1500])
    assert window.minimumSizeHint().width() <= 640         # reading in half of a 1280 px screen


def test_recent_files_join_the_library_once(make_window, qtbot, tmp_path):
    import json
    old = make_zip(tmp_path / "Old" / "c1.cbz", {"1.png": encode(page_image(1), "PNG")})
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "settings.json").write_text(json.dumps({"recent": [str(old)]}), encoding="utf-8")
    w = make_window(qtbot)
    assert [c.title for c in w.services.catalog.cards()] == ["Old"] and w.services.settings.recent_imported
    assert [w.library_page.model.card_at(1).title] == ["Old"]


def test_settings_highlights_settings_button(window):
    window.show_settings()
    nav = window.library_page.nav
    assert nav.settings_button.isChecked() and nav.tree.selectedItems() == []
    nav.tree.itemClicked.emit(nav.item_for(Section()), 0)
    assert not nav.settings_button.isChecked() and nav.tree.currentItem() is nav.item_for(Section())


def test_theme_switch_recolors_columns(window):
    from PySide6.QtGui import QPalette

    def lightness():
        page = window.library_page
        return (page.nav.palette().color(QPalette.Window).lightness(),
                page.content.palette().color(QPalette.Window).lightness(),
                window.nav_panel.palette().color(QPalette.Base).lightness())
    combo = window.settings_page.theme_combo
    combo.setCurrentIndex(combo.findData("light"))
    nav, content, reader_nav = lightness()
    assert nav < content                      # light theme: a grey column next to white
    combo.setCurrentIndex(combo.findData("dark"))
    nav, content, reader_nav = lightness()
    assert nav > content and reader_nav == nav    # dark theme: the navigation columns are the lighter ones
    combo.setCurrentIndex(combo.findData("light"))
