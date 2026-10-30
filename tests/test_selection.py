from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QGuiApplication

from mangareader.export.geometry import crops_for_selection, output_size
from mangareader.ui.reader.layout import Mode
from mangareader.ui.reader.view import ZoomMode


def rect_tuple(r):
    return r.x(), r.y(), r.width(), r.height()


def test_drag_creates_rect_and_label(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.view.set_zoom_mode(ZoomMode.ACTUAL)
    qtbot.keyClick(window.view, Qt.Key_S)
    tool = window.selection
    assert tool.active
    vp = window.view.viewport()
    qtbot.mousePress(vp, Qt.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(vp, QPoint(250, 350))
    qtbot.mouseRelease(vp, Qt.LeftButton, pos=QPoint(250, 350))
    r = tool.rect()
    assert r is not None and r.width() > 150 and r.height() > 250
    w, h = map(int, tool.size_label().split(" × "))
    placed = window.view.placed()
    assert (w, h) == output_size(placed, crops_for_selection(placed, rect_tuple(r)))


def test_drag_inside_moves_rect(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.view.set_zoom_mode(ZoomMode.ACTUAL)
    qtbot.keyClick(window.view, Qt.Key_S)
    tool = window.selection
    start = window.view.mapToScene(QPoint(100, 100))
    tool.set_rect(QRectF(start.x(), start.y(), 200, 200))
    before = tool.rect()
    vp = window.view.viewport()
    qtbot.mousePress(vp, Qt.LeftButton, pos=QPoint(200, 200))
    qtbot.mouseMove(vp, QPoint(230, 220))
    qtbot.mouseRelease(vp, Qt.LeftButton, pos=QPoint(230, 220))
    after = tool.rect()
    assert (after.width(), after.height()) == (before.width(), before.height())
    assert after.x() > before.x() and after.y() > before.y()


def test_rect_is_clamped_to_pages(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    qtbot.keyClick(window.view, Qt.Key_S)
    window.selection.set_rect(QRectF(-500, -500, 5000, 5000))
    assert rect_tuple(window.selection.rect()) == (0, 0, 1000, 1500)


def test_copy_spread_selection_to_clipboard(window, qtbot, cbz_spread):
    window.open_paths([cbz_spread])
    window.controller.set_mode(Mode.SPREAD)
    window.controller.next()
    qtbot.keyClick(window.view, Qt.Key_S)
    placed = window.view.placed()
    union = QRectF(min(p.x for p in placed), 0, sum(p.w for p in placed), placed[0].h)
    window.selection.set_rect(union)
    qtbot.keyClick(window.view, Qt.Key_C, Qt.ControlModifier)
    img = QGuiApplication.clipboard().image()
    assert (img.width(), img.height()) == output_size(placed, crops_for_selection(placed, rect_tuple(union)))
    assert (img.width(), img.height()) == (2000, 1500)


def test_escape_cancels(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    qtbot.keyClick(window.view, Qt.Key_S)
    window.selection.set_rect(QRectF(0, 0, 10, 10))
    qtbot.keyClick(window.view, Qt.Key_Escape)
    assert not window.selection.active and window.selection.rect() is None


def test_page_change_resets_selection(window, qtbot, cbz_spread):
    window.open_paths([cbz_spread])
    qtbot.keyClick(window.view, Qt.Key_S)
    window.selection.set_rect(QRectF(0, 0, 10, 10))
    window.controller.next()
    assert window.selection.rect() is None


def test_copy_without_selection_copies_page(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    qtbot.keyClick(window.view, Qt.Key_C, Qt.ControlModifier)
    assert QGuiApplication.clipboard().image().width() == 1000


def test_render_uses_real_page_size_when_layout_guessed(tmp_path, ctx):
    from helpers import encode, make_zip, page_image
    from mangareader.export.geometry import Placed
    from mangareader.sources import open_source
    from mangareader.ui.reader.selection import render_selection
    real = page_image(4, (600, 900))
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.png": encode(real, "PNG")}), ctx)
    guessed = [Placed(0, 0, 0, 1000, 1500, 1000, 1500)]       # size not known yet: default 1000×1500
    image, _ = render_selection(src, guessed, QRectF(0, 0, 500, 750))
    assert image.size == (300, 450) and image.tobytes() == real.crop((0, 0, 300, 450)).tobytes()
