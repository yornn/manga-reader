from helpers import make_epub
from mangareader.ui.reader.layout import Direction


def test_font_slider_only_for_books(window, qtbot, tmp_path, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    qtbot.wait(50)
    assert not window.font_slider.isVisible()
    window.open_paths([make_epub(tmp_path / "b.epub", 400)])
    qtbot.waitUntil(window.font_slider.isVisible, timeout=2000)   # the toolbar re-lays out on the next tick
    assert window.controller.direction is Direction.LTR


def test_font_change_keeps_position(window, qtbot, tmp_path):
    window.open_paths([make_epub(tmp_path / "b.epub", 400)])
    c = window.controller
    for _ in range(5):
        c.next()
    n1, p1 = len(c.source.pages), c.position.page
    c.set_font_size(20)
    n2, p2 = len(c.source.pages), c.position.page
    assert n2 > n1 and abs(p2 / n2 - p1 / n1) < 0.1 and window.services.settings.book_font_size == 20
    assert window.nav_panel.page_count == n2


def test_resize_relayouts(window, qtbot, tmp_path):
    window.open_paths([make_epub(tmp_path / "b.epub", 400)])
    n1 = len(window.controller.source.pages)
    window.resize(window.width() // 2, window.height())
    qtbot.waitUntil(lambda: len(window.controller.source.pages) != n1, timeout=3000)


def test_book_progress_survives_reopen(make_window, qtbot, tmp_path):
    book = make_epub(tmp_path / "b.epub", 400)
    w1 = make_window(qtbot)
    w1.open_paths([book])
    for _ in range(6):
        w1.controller.next()
    ratio = w1.controller.position.page / len(w1.controller.source.pages)
    w1.close()
    w2 = make_window(qtbot)
    w2.open_paths([book])
    assert abs(w2.controller.position.page / len(w2.controller.source.pages) - ratio) < 0.1


def test_toolbar_controls_fit_narrow_window(window, qtbot, tmp_path):
    book = make_epub(tmp_path / "Очень длинное название книги, чтобы занять всю панель инструментов" / "b.epub", 50)
    window.resize(700, 600)
    window.open_paths([book])
    qtbot.waitUntil(window.font_slider.isVisible, timeout=2000)
    # the font control lives in the bottom bar, which a crowded toolbar cannot push into its "»" menu
    assert not window.toolbar.isAncestorOf(window.font_slider)


def test_book_thumbnails_follow_layout(window, qtbot, tmp_path):
    window.open_paths([make_epub(tmp_path / "b.epub", 400)])
    c, loader = window.controller, window.services.loader
    from mangareader.render.loader import pil_to_qimage
    from mangareader.render.thumbs import ThumbnailStore
    qtbot.waitUntil(lambda: loader.thumbnail(c.source_key, 0) is not None, timeout=5000)
    c.set_font_size(22)
    qtbot.waitUntil(lambda: loader.thumbnail(c.source_key, 0) is not None, timeout=5000)
    fresh = pil_to_qimage(ThumbnailStore(tmp_path / "fresh").create(c.source, 0, "x"))
    assert loader.thumbnail(c.source_key, 0) == fresh    # rendered for the current layout, not the old one


def test_toolbar_labels_do_not_overlap(window, qtbot, tmp_path):
    book = make_epub(tmp_path / "Очень длинное название книги, чтобы занять всю панель инструментов" / "b.epub", 50)
    window.resize(700, 600)
    window.open_paths([book])
    qtbot.wait(100)
    crumb, page = window.crumb_label, window.page_label
    assert crumb.width() >= 60 and crumb.geometry().right() < page.geometry().left()
    assert "…" in crumb.text()           # the long breadcrumb is shortened, not drawn over the buttons
