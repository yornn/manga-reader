from PySide6.QtCore import Qt

from helpers import encode, make_zip, page_image
from mangareader.ui.dialogs import chapter_mark_dialog
from mangareader.ui.reader.navigation import Position


def volume(tmp_path, pages=6):
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(pages)})
    return s


def top_titles(w):
    tree = w.sidebar.tree_widget
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_tree_shows_volumes_and_chapters(window, qtbot, tmp_path):
    s = volume(tmp_path)
    make_zip(s / "c010.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: window.sidebar.tree_widget.topLevelItemCount() == 2, timeout=5000)
    assert top_titles(window) == ["Том 1", "Глава 10"]


def test_manual_mark_creates_chapter_and_survives_restart(make_window, qtbot, tmp_path, monkeypatch):
    s = volume(tmp_path)
    monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: ("1", "Начало пути"))
    w = make_window(qtbot)
    w.open_paths([s / "Vol 01.cbz"])
    w.sidebar.mark_requested.emit(3)
    vol = w.sidebar.tree_widget.topLevelItem(0)
    assert [vol.child(i).text(0) for i in range(vol.childCount())] == ["Начало", "Глава 1 — Начало пути"]
    assert w.breadcrumb_text() == "S › Том 1 › Начало"
    w.close()
    w2 = make_window(qtbot)
    w2.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: w2.sidebar.tree_widget.topLevelItemCount() == 1, timeout=5000)
    assert w2.sidebar.tree_widget.topLevelItem(0).childCount() == 2


def test_click_chapter_navigates(window, qtbot, tmp_path, monkeypatch):
    s = volume(tmp_path)
    monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: ("1", ""))
    window.open_paths([s / "Vol 01.cbz"])
    window.sidebar.mark_requested.emit(3)
    tree = window.sidebar.tree_widget
    chapter = tree.topLevelItem(0).child(1)
    assert chapter.text(0) == "Глава 1"
    tree.itemClicked.emit(chapter, 0)
    assert window.controller.position == Position(0, 3)


def test_thumbnails_and_mark_badge(window, qtbot, tmp_path, monkeypatch):
    s = volume(tmp_path)
    monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: ("1", ""))
    window.open_paths([s / "Vol 01.cbz"])
    model = window.sidebar.thumb_view.model()
    assert model.rowCount() == 6
    window.sidebar.mark_requested.emit(3)
    assert model.data(model.index(3), Qt.DisplayRole) == "4 · Гл 1"
    assert model.data(model.index(2), Qt.DisplayRole) == "3"


def test_delete_mark(window, qtbot, tmp_path, monkeypatch):
    s = volume(tmp_path)
    monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: ("1", ""))
    window.open_paths([s / "Vol 01.cbz"])
    window.sidebar.mark_requested.emit(3)
    window.sidebar.mark_delete_requested.emit(3)
    assert window.sidebar.tree_widget.topLevelItem(0).childCount() == 0


def test_kind_override_moves_node(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")})
    make_zip(s / "c002.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: window.sidebar.tree_widget.topLevelItemCount() == 2, timeout=5000)
    assert top_titles(window) == ["Том 1", "Глава 2"]
    window.sidebar.kind_override_requested.emit(0, "chapter")
    qtbot.waitUntil(lambda: top_titles(window) == ["Глава 1", "Глава 2"], timeout=5000)


def test_tab_toggles_sidebar(window, qtbot, tmp_path):
    window.open_paths([volume(tmp_path) / "Vol 01.cbz"])
    visible = window.sidebar.isVisible()
    qtbot.keyClick(window.view, Qt.Key_Tab)
    assert window.sidebar.isVisible() != visible


def test_thumbnail_fits_icon_size(window, qtbot, tmp_path):
    from mangareader.ui.reader.sidebar import THUMB_SIZE
    window.open_paths([volume(tmp_path) / "Vol 01.cbz"])
    model = window.sidebar.thumb_view.model()
    model.data(model.index(0), Qt.DecorationRole)
    qtbot.waitUntil(lambda: window.services.loader.thumbnail(window.controller.source_key, 0) is not None,
                    timeout=5000)
    icon = model.data(model.index(0), Qt.DecorationRole)
    assert icon.width() <= THUMB_SIZE.width() and icon.height() <= THUMB_SIZE.height()
    assert window.sidebar.thumb_view.gridSize().height() > THUMB_SIZE.height()
