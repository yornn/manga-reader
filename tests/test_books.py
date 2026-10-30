from helpers import make_epub
from mangareader.ui.reader.layout import Direction


def test_font_slider_only_for_books(window, qtbot, tmp_path, cbz_1000x1500):
    panel = window.reader_settings
    window.open_paths([cbz_1000x1500])
    qtbot.wait(50)
    assert not panel.font_row.isVisibleTo(panel)
    window.open_paths([make_epub(tmp_path / "b.epub", 400)])
    assert panel.font_row.isVisibleTo(panel)
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
    # the font control lives behind the gear, which a crowded toolbar cannot push into its "»" menu
    qtbot.wait(100)
    assert not window.toolbar.isAncestorOf(window.font_slider)
    assert window.gear_button.isVisible()


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
    from helpers import encode, make_zip, page_image
    folder = tmp_path / "Очень длинное название серии, чтобы занять всю панель инструментов"
    volume = make_zip(folder / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([volume])
    window.resize(450, 600)                      # the reader may be narrower than the library
    qtbot.wait(100)
    crumb, page = window.crumb_label, window.page_label
    assert crumb.width() >= 60 and crumb.geometry().right() < page.geometry().left()
    assert "…" in crumb.text()           # the long breadcrumb is shortened, not drawn over the buttons


def test_reader_bar_never_hides_buttons(window, qtbot, tmp_path):
    from helpers import encode, make_zip, page_image
    folder = tmp_path / "Очень длинное название серии, чтобы занять всю панель инструментов"
    window.open_paths([make_zip(folder / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")})])
    window.resize(400, 600)                                # as narrow as the reader allows
    qtbot.wait(100)
    for button in (window.home_button, window.focus_button, window.prev_chapter_button, window.page_label,
                   window.next_chapter_button, window.gear_button):
        assert button.isVisible(), button.text()           # nothing goes into a "»" overflow menu
    assert "…" in window.crumb_label.text()


def test_reader_bar_shortens_labels_when_narrow(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.resize(window.minimumSizeHint().width(), 600)    # as narrow as the reader allows on this machine
    qtbot.wait(100)
    assert [b.text() for b in (window.home_button, window.prev_chapter_button, window.next_chapter_button)] == \
        ["⌂", "‹", "›"]
    assert all(b.isVisible() for b in (window.home_button, window.gear_button, window.next_chapter_button))
    window.resize(1100, 600)
    qtbot.wait(100)
    assert window.home_button.text() == "⌂ Главная" and window.next_chapter_button.text() == "Глава ›"
