from pathlib import Path

from PySide6.QtCore import Qt

import mangareader
from helpers import encode, make_7z, make_zip, page_image
from mangareader.ui.dialogs import errors
from mangareader.ui.reader.layout import Direction, Mode
from mangareader.ui.reader.navigation import Position
from mangareader.ui.toast import Toast


def series(tmp_path):
    s = tmp_path / "S"
    make_zip(s / "c001.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(3)})
    make_zip(s / "c002.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(2)})
    return s


def test_open_and_flip_rtl_default(window, qtbot, tmp_path):
    s = series(tmp_path)
    assert window.open_paths([s / "c001.cbz"])
    assert window.page_label_text() == "1/3" and window.controller.direction == Direction.RTL
    qtbot.keyClick(window.view, Qt.Key_Left)
    assert window.page_label_text() == "2/3"
    qtbot.keyClick(window.view, Qt.Key_Right)
    assert window.page_label_text() == "1/3"


def test_continues_into_next_source(window, qtbot, tmp_path):
    s = series(tmp_path)
    window.open_paths([s / "c001.cbz"])
    qtbot.waitUntil(lambda: len(window.controller.entries) == 2, timeout=5000)
    for _ in range(3):
        window.controller.next()
    assert window.controller.entry.path.name == "c002.cbz" and Toast.last_text() == "Глава 2"
    assert window.breadcrumb_text() == "S › Глава 2"
    window.controller.prev()
    assert window.controller.entry.path.name == "c001.cbz" and window.page_label_text() == "3/3"


def test_progress_and_prefs_persist(make_window, qtbot, tmp_path):
    s = series(tmp_path)
    w1 = make_window(qtbot)
    w1.open_paths([s / "c001.cbz"])
    w1.controller.next()
    qtbot.keyClick(w1.view, Qt.Key_2)
    w1.close()
    w2 = make_window(qtbot)
    w2.open_paths([s / "c001.cbz"])
    assert w2.controller.position.page == 1 and w2.controller.mode == Mode.SPREAD
    assert w2.page_label_text() == "2–3/3"


def test_open_folder_of_series_picks_first(window, tmp_path):
    s = series(tmp_path)
    assert window.open_paths([s]) and window.controller.entry.path.name == "c001.cbz"


def test_missing_file_reports_error(window, qtbot, tmp_path):
    with qtbot.waitSignal(window.controller.error):
        assert not window.open_paths([tmp_path / "nope.cbz"])


def test_password_prompt(window, monkeypatch, tmp_path):
    arc = make_7z(tmp_path / "p.cb7", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw")
    monkeypatch.setattr(errors, "ask_password", lambda *a: "pw")
    assert window.open_paths([arc]) and window.page_label_text() == "1/1"


def test_password_cancel(window, monkeypatch, tmp_path):
    arc = make_7z(tmp_path / "p.cb7", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw")
    monkeypatch.setattr(errors, "ask_password", lambda *a: None)
    assert not window.open_paths([arc])


def test_chapter_and_page_keys(window, qtbot, tmp_path):
    s = series(tmp_path)
    window.open_paths([s / "c001.cbz"])
    qtbot.waitUntil(lambda: len(window.controller.entries) == 2, timeout=5000)
    qtbot.keyClick(window.view, Qt.Key_End)
    assert window.page_label_text() == "3/3"
    qtbot.keyClick(window.view, Qt.Key_PageDown, Qt.ControlModifier)
    assert window.controller.entry.path.name == "c002.cbz"
    qtbot.keyClick(window.view, Qt.Key_D)
    assert window.controller.direction == Direction.LTR
    qtbot.keyClick(window.view, Qt.Key_3)
    assert window.controller.mode == Mode.RIBBON


def test_recent_and_no_qsettings(window, tmp_path):
    s = series(tmp_path)
    window.open_paths([s / "c001.cbz"])
    assert window.services.settings.recent[0] == str(s / "c001.cbz")
    sources = Path(mangareader.__file__).parent.rglob("*.py")
    assert not any("QSettings" in p.read_text(encoding="utf-8") for p in sources)


def test_flip_back_shows_cached_page_immediately(window, qtbot, cbz_spread):
    from mangareader.ui.reader.layout import place_group
    window.open_paths([cbz_spread])
    c, view, loader = window.controller, window.view, window.services.loader
    qtbot.waitUntil(lambda: view.page_item(0).has_scaled_image(), timeout=5000)
    window.controller.next()
    qtbot.waitUntil(lambda: view.page_item(1).has_scaled_image(), timeout=5000)
    size = view.wanted_sizes(place_group([0], c.sizes, c.direction))[0]
    qtbot.waitUntil(lambda: loader.has_scaled(c.source_key, 0, *size), timeout=5000)   # page 0 is cached
    window.controller.prev()
    assert view.page_item(0).has_scaled_image()          # no "Загрузка…" flash for a cached page


def test_next_page_is_prepared_before_flip(window, qtbot, cbz_spread):
    from mangareader.ui.reader.layout import place_group
    window.open_paths([cbz_spread])
    c, view, loader = window.controller, window.view, window.services.loader
    qtbot.waitUntil(lambda: view.page_item(0).has_scaled_image(), timeout=5000)
    qtbot.waitUntil(lambda: c.sizes[1] is not None, timeout=5000)
    size = view.wanted_sizes(place_group([1], c.sizes, c.direction))[1]
    qtbot.waitUntil(lambda: loader.has_scaled(c.source_key, 1, *size), timeout=5000)
    c.next()
    assert view.page_item(1).has_scaled_image()


def test_late_page_sizes_do_not_reset_selection(window, qtbot, tmp_path):
    from PySide6.QtCore import QRectF
    arc = make_7z(tmp_path / "S" / "v.cb7",
                  {f"{i:03}.png": encode(page_image(i, (1000, 1500)), "PNG") for i in range(6)})
    window.open_paths([arc])
    c = window.controller
    qtbot.waitUntil(lambda: c.sizes[1] is not None, timeout=5000)
    c.next()
    window.selection.activate()
    window.selection.set_rect(QRectF(10, 10, 100, 100))
    qtbot.waitUntil(lambda: all(s is not None for s in c.sizes[:4]), timeout=5000)
    qtbot.wait(300)
    assert window.selection.rect() is not None


def test_ribbon_keeps_scroll_when_a_later_size_arrives(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "w.cbz", {f"{i:03}.png": encode(page_image(i, (800, 1200)), "PNG") for i in range(6)})
    window.open_paths([s / "w.cbz"])
    c, view = window.controller, window.view
    c.set_mode(Mode.RIBBON)
    qtbot.waitUntil(lambda: all(x is not None for x in c.sizes), timeout=5000)
    qtbot.wait(300)
    view.scroll_to_page(2)
    bar = view.verticalScrollBar()
    bar.setValue(bar.value() + 37)
    before = bar.value()
    window.services.loader.size_known.emit(c.source_key, 5, 800, 2400)   # a page below gets taller
    qtbot.waitUntil(lambda: c.sizes[5] == (800, 2400), timeout=2000)
    qtbot.wait(400)
    assert abs(bar.value() - before) <= 2


def test_inside_drive_root():
    from mangareader.library.classify import is_inside
    root = Path(Path.cwd().anchor)
    assert is_inside(root / "manga" / "a.cbz", root) and not is_inside(root, root)


def test_opened_file_missing_from_tree_keeps_its_own_list(window, qtbot, tmp_path):
    from helpers import make_epub
    books = tmp_path / "Books"
    make_epub(books / "a.epub", 20)
    make_epub(books / "b.epub", 20)
    (books / "notes.txt").write_text("заметки\n" * 50, encoding="utf-8")
    window.open_paths([books / "notes.txt"])
    qtbot.wait(1500)                                   # the series scan finishes (it skips .txt)
    window.nav_panel.position_selected.emit(1, 0)        # must not index past the controller's list
    assert window.controller.entry.path.name == "notes.txt"
    assert [n.title for n in window.controller.display_tree().nodes] == ["notes"]


def hribbon_window(window, qtbot, tmp_path, direction=None):
    s = tmp_path / "S"
    make_zip(s / "w.cbz", {f"{i:03}.png": encode(page_image(i, (800, 1200)), "PNG") for i in range(5)})
    window.open_paths([s / "w.cbz"])
    c = window.controller
    c.set_mode(Mode.HRIBBON)
    qtbot.waitUntil(lambda: all(x is not None for x in c.sizes), timeout=5000)
    qtbot.wait(300)
    return c


def test_hribbon_next_scrolls_and_saves(window, qtbot, tmp_path):
    c = hribbon_window(window, qtbot, tmp_path)
    assert window.view.horizontalScrollBar().maximum() > 0
    c.next()
    assert c.page == 1 and window.services.store.progress(c.record.id).position == 1
    qtbot.keyClick(window.view, Qt.Key_4)
    assert c.mode is Mode.HRIBBON


def test_hribbon_direction_keeps_page(window, qtbot, tmp_path):
    c = hribbon_window(window, qtbot, tmp_path)
    c.go_to(Position(0, 2))
    c.toggle_direction()
    qtbot.wait(100)
    assert c.page == 2 and 2 in window.view.visible_pages()


def test_go_to_series_page(window, qtbot, tmp_path):
    s = series(tmp_path)                                  # c001: 3 pages, c002: 2 pages
    window.open_paths([s / "c001.cbz"])
    c = window.controller
    qtbot.waitUntil(lambda: len(c.entries) == 2, timeout=5000)
    assert c.series_page_count() == 5 and c.series_page() == 1
    c.go_to_series_page(5)
    assert c.entry.path.name == "c002.cbz" and c.page == 1 and c.series_page() == 5
    c.go_to_series_page(1002)
    assert c.series_page() == 5
    c.go_to_series_page(0)
    assert c.entry.path.name == "c001.cbz" and c.page == 0


def test_page_button_opens_dialog(window, qtbot, tmp_path, monkeypatch):
    from mangareader.ui.dialogs import page_dialog
    s = series(tmp_path)
    window.open_paths([s / "c001.cbz"])
    qtbot.waitUntil(lambda: len(window.controller.entries) == 2, timeout=5000)
    asked = []
    monkeypatch.setattr(page_dialog, "ask_page", lambda parent, current, total: asked.append((current, total)) or 4)
    window.page_label.click()
    assert asked == [(1, 5)] and window.controller.entry_index == 1 and window.controller.page == 0
    qtbot.keyClick(window.view, Qt.Key_G, Qt.ControlModifier)
    assert asked[-1] == (4, 5)


def test_chapter_buttons(window, qtbot, tmp_path):
    s = series(tmp_path)
    window.open_paths([s / "c001.cbz"])
    qtbot.waitUntil(lambda: len(window.controller.entries) == 2, timeout=5000)
    window.next_chapter_button.click()
    assert window.controller.entry.path.name == "c002.cbz"
    window.prev_chapter_button.click()
    assert window.controller.entry.path.name == "c001.cbz"
