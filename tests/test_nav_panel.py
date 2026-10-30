from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from helpers import encode, make_zip, page_image
from mangareader.ui.dialogs import chapter_mark_dialog
from mangareader.ui.reader.nav_panel import KIND_ROLE, PAGES_ROLE, PROGRESS_ROLE, RowKind
from mangareader.ui.reader.navigation import Position


def volume_with_marks(window, tmp_path, monkeypatch, pages=9):
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(pages)})
    answers = iter([("1", ""), ("2", "")])
    monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: next(answers))
    window.open_paths([s / "Vol 01.cbz"])
    window.nav_panel.mark_requested.emit(3)
    window.nav_panel.mark_requested.emit(6)
    return s


def test_rows_for_volumes_and_chapters(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")})
    make_zip(s / "c010.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"])
    tree = window.nav_panel.tree
    qtbot.waitUntil(lambda: tree.topLevelItemCount() == 2, timeout=5000)
    rows = [(tree.topLevelItem(i).text(0), tree.topLevelItem(i).data(0, KIND_ROLE)) for i in range(2)]
    assert rows == [("Том 1", RowKind.VOLUME), ("Глава 10", RowKind.CHAPTER)]


def test_one_chapter_open_at_a_time(window, qtbot, tmp_path, monkeypatch):
    volume_with_marks(window, tmp_path, monkeypatch)
    panel = window.nav_panel
    window.controller.go_to(Position(0, 7))
    start, ch1, ch2 = (panel.item("Том 1", t) for t in ("Начало", "Глава 1", "Глава 2"))
    assert ch2.isExpanded() and not start.isExpanded() and panel.item("Том 1").isExpanded()
    ch1.setExpanded(True)
    assert ch1.isExpanded() and not ch2.isExpanded()
    assert [ch1.child(i).data(0, PAGES_ROLE) for i in range(ch1.childCount())] == [[3, 4, 5]]


def test_click_thumbnail_and_chapter(window, qtbot, tmp_path, monkeypatch):
    volume_with_marks(window, tmp_path, monkeypatch)
    panel = window.nav_panel
    panel.item("Том 1", "Глава 1").setExpanded(True)
    qtbot.wait(50)
    qtbot.mouseClick(panel.tree.viewport(), Qt.LeftButton, pos=panel.thumb_rect(4).center())
    assert window.controller.position == Position(0, 4)
    panel.tree.itemClicked.emit(panel.item("Том 1", "Глава 2"), 0)
    assert window.controller.position == Position(0, 6)


def test_other_volume_has_no_thumbnails(window, qtbot, tmp_path):
    s = tmp_path / "S"
    for v in (1, 2):
        make_zip(s / f"Vol {v:02}.cbz",
                 {f"c{c}/{i}.png": encode(page_image(i), "PNG") for c in (1, 2) for i in range(2)})
    window.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItemCount() == 2, timeout=5000)
    other = window.nav_panel.item("Том 2", "Глава 2")
    assert other.childIndicatorPolicy() == QTreeWidgetItem.DontShowIndicator
    window.nav_panel.tree.itemClicked.emit(other, 0)
    assert window.controller.entry.path.name == "Vol 02.cbz" and window.controller.position.page == 2


def test_marks_badge_delete_and_restart(make_window, qtbot, tmp_path, monkeypatch):
    w = make_window(qtbot)
    s = volume_with_marks(w, tmp_path, monkeypatch)
    assert w.nav_panel.thumb_label(3) == "4 · Гл 1" and w.nav_panel.thumb_label(2) == "3"
    assert w.breadcrumb_text() == "S › Том 1 › Начало"
    w.nav_panel.mark_delete_requested.emit(6)
    vol = w.nav_panel.item("Том 1")
    assert [vol.child(i).text(0) for i in range(vol.childCount())] == ["Начало", "Глава 1"]
    w.close()
    w2 = make_window(qtbot)
    w2.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: w2.nav_panel.item("Том 1").childCount() == 2, timeout=5000)
    menu = w2.nav_panel.page_menu(3)
    assert [a.text() for a in menu.actions()] == ["Изменить отметку…", "Удалить отметку"]
    assert [a.text() for a in w2.nav_panel.page_menu(2).actions()] == ["Здесь начинается глава…"]


def test_kind_override_and_volume_progress(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(4)})
    make_zip(s / "c002.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItemCount() == 2, timeout=5000)
    window.controller.next()
    window.nav_panel.set_tree(window.controller.display_tree())
    assert window.nav_panel.item("Том 1").data(0, PROGRESS_ROLE) > 0
    menu = window.nav_panel.row_menu(window.nav_panel.item("Том 1"))
    assert [a.text() for a in menu.actions()] == ["Это том", "Это глава", "Сбросить"]
    window.nav_panel.kind_override_requested.emit(0, "chapter")
    qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItem(0).text(0) == "Глава 1", timeout=5000)


def test_tab_toggles_panel(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"])
    visible = window.nav_panel.isVisible()
    qtbot.keyClick(window.view, Qt.Key_Tab)
    assert window.nav_panel.isVisible() != visible
