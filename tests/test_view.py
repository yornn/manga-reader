import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from helpers import encode, make_zip, page_image
from mangareader.render.cache import ImageCache
from mangareader.render.loader import PageLoader
from mangareader.render.thumbs import ThumbnailStore
from mangareader.sources import open_source
from mangareader.ui.reader.layout import Direction, place_group, place_ribbon
from mangareader.ui.reader.view import PageView, ZoomMode

SIZE = [(1000, 1500), (1000, 1500)]


def make_view(qtbot, tmp_path, ctx, files):
    src = open_source(make_zip(tmp_path / "a.cbz", files), ctx)
    loader = PageLoader(ImageCache(2**28), ThumbnailStore(tmp_path / "th"))
    loader.register("k", src, "fp")
    v = PageView(loader)
    qtbot.addWidget(v)
    v.resize(600, 600)
    v.show()
    qtbot.waitExposed(v)
    return v


@pytest.fixture
def view(qtbot, tmp_path, ctx):
    page = encode(page_image(1, (1000, 1500)), "PNG")
    return make_view(qtbot, tmp_path, ctx, {"1.png": page, "2.png": page})


@pytest.fixture
def view_with_broken_page(qtbot, tmp_path, ctx):
    v = make_view(qtbot, tmp_path, ctx, {"1.png": encode(page_image(1, (1000, 1500)), "PNG"), "2.png": b"broken"})
    v.show_pages("k", place_group([0, 1], SIZE, Direction.LTR), Direction.LTR)
    return v


def send_wheel(view, delta, modifiers=Qt.NoModifier):
    vp = view.viewport()
    center = QPointF(vp.width() / 2, vp.height() / 2)
    ev = QWheelEvent(center, vp.mapToGlobal(center), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, modifiers,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def test_fit_modes(view):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WIDTH)
    assert view.scale_factor() == pytest.approx(view.viewport().width() / 1000, rel=0.02)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)
    assert view.scale_factor() == pytest.approx(view.viewport().height() / 1500, rel=0.02)
    view.set_zoom_mode(ZoomMode.FIT_HEIGHT)
    assert view.scale_factor() == pytest.approx(view.viewport().height() / 1500, rel=0.02)
    view.set_zoom_mode(ZoomMode.ACTUAL)
    assert view.scale_factor() == pytest.approx(1 / view.devicePixelRatioF())
    assert view.zoom_mode is ZoomMode.ACTUAL


def test_ctrl_wheel_zooms(view):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)
    before = view.scale_factor()
    send_wheel(view, 120, Qt.ControlModifier)
    assert view.zoom_mode is ZoomMode.CUSTOM and view.scale_factor() == pytest.approx(before * 1.25)


@pytest.mark.parametrize("direction,x_frac,forward", [(Direction.RTL, 0.1, True), (Direction.RTL, 0.9, False),
                                                     (Direction.LTR, 0.1, False), (Direction.LTR, 0.9, True)])
def test_click_thirds(view, qtbot, direction, x_frac, forward):
    view.show_pages("k", place_group([0], SIZE, direction), direction)
    with qtbot.waitSignal(view.flip_requested) as sig:
        qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=QPoint(int(view.viewport().width() * x_frac), 300))
    assert sig.args == [forward]


def test_middle_click_does_not_flip(view, qtbot):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    with qtbot.assertNotEmitted(view.flip_requested):
        qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=QPoint(view.viewport().width() // 2, 300))


def test_wheel_never_flips(view, qtbot):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)                 # nothing to scroll: the wheel does nothing
    with qtbot.assertNotEmitted(view.flip_requested, wait=300):
        send_wheel(view, -120)
    view.set_zoom_mode(ZoomMode.FIT_WIDTH)
    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum())                             # at the end of a tall page
    with qtbot.assertNotEmitted(view.flip_requested, wait=300):
        for _ in range(3):
            send_wheel(view, -120)
    assert bar.value() == bar.maximum()


def test_wheel_scrolls_smoothly(view, qtbot):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WIDTH)
    bar = view.verticalScrollBar()
    assert bar.value() == bar.minimum()
    send_wheel(view, -120)
    assert bar.value() < bar.minimum() + 40                 # it glides, not jumps
    qtbot.waitUntil(lambda: bar.value() >= bar.minimum() + 80, timeout=1000)
    send_wheel(view, 120)
    qtbot.waitUntil(lambda: bar.value() == bar.minimum(), timeout=1000)


def test_touchpad_scrolls_at_once(view):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WIDTH)
    bar = view.verticalScrollBar()
    vp = view.viewport()
    center = QPointF(vp.width() / 2, vp.height() / 2)
    QApplication.sendEvent(vp, QWheelEvent(center, vp.mapToGlobal(center), QPoint(0, -50), QPoint(0, -60),
                                           Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    assert bar.value() == bar.minimum() + 50


def test_scaled_image_requested_at_device_size(view, qtbot):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)
    qtbot.waitUntil(lambda: view.page_item(0).has_scaled_image(), timeout=5000)
    w, h = view.page_item(0).scaled_size()
    assert h == round(1500 * view.scale_factor() * view.devicePixelRatioF())


def test_ribbon_visible_page(view, qtbot):
    view.show_pages("k", place_ribbon(SIZE), Direction.LTR, ribbon=True, focus_page=1)
    view.set_zoom_mode(ZoomMode.FIT_WIDTH)
    view.scroll_to_page(1)
    assert 1 in view.visible_pages()
    assert [p.page for p in view.placed()] == [0, 1]


def test_error_placeholder(view_with_broken_page, qtbot):        # Review Focus 4
    v = view_with_broken_page
    qtbot.waitUntil(lambda: v.page_item(1).error_text() is not None, timeout=5000)
    assert "Не удалось" in v.page_item(1).error_text()


@pytest.mark.parametrize("mode", [ZoomMode.FIT_WINDOW, ZoomMode.CUSTOM])
def test_page_is_painted(view, qtbot, mode):
    view.show_pages("k", place_group([0], SIZE, Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)
    if mode is ZoomMode.CUSTOM:
        view.zoom_by(3.0)                       # больше 100%: копия растягивается
    qtbot.waitUntil(lambda: view.page_item(0).has_scaled_image(), timeout=5000)
    qtbot.wait(100)
    img = view.viewport().grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    assert (c.red(), c.green(), c.blue()) == (53, 97, 31)
