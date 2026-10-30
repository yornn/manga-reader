from PySide6.QtGui import QKeySequence

from helpers import make_epub, page_image
from mangareader.settings import load_settings
from mangareader.ui.dialogs.hotkeys_dialog import HOTKEYS
from mangareader.ui.reader.layout import Direction, Mode
from mangareader.ui.reader.view import ZoomMode


def test_brightness_dims_only_the_screen(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    view = window.view
    qtbot.waitUntil(lambda: view.page_item(0).has_scaled_image(), timeout=5000)
    center = view.viewport().rect().center()

    def shown():
        return view.viewport().grab().toImage().pixelColor(center)
    bright = shown()
    window.reader_settings.brightness_slider.setValue(50)
    dim = shown()
    assert dim.red() <= bright.red() * 0.6 and dim.green() <= bright.green() * 0.6
    assert window.reader_settings.brightness_label.text() == "50%"
    assert load_settings(window.services.data.settings_file).brightness == 50
    image, _ = window._render_target()                    # what gets saved or copied stays original
    original = page_image(1, (1000, 1500)).getpixel((500, 750))
    assert image.getpixel((image.width // 2, image.height // 2)) == original
    window.reader_settings.brightness_slider.setValue(5)
    assert window.services.settings.brightness == 20       # never darker than 20 %


def test_gear_panel_controls_reader(window, qtbot, cbz_spread, tmp_path):
    window.open_paths([cbz_spread])
    panel, c = window.reader_settings, window.controller
    panel.mode_buttons[Mode.SPREAD].click()
    assert c.mode is Mode.SPREAD
    panel.zoom_buttons[ZoomMode.FIT_WIDTH].click()
    assert window.view.zoom_mode is ZoomMode.FIT_WIDTH
    panel.direction_buttons[Direction.LTR].click()
    assert c.direction is Direction.LTR
    offset = c.record.spread_offset
    panel.offset_check.click()
    assert c.record.spread_offset != offset
    assert not panel.font_row.isVisibleTo(panel)
    window.open_paths([make_epub(tmp_path / "b.epub", 100)])
    window.gear_button.menu().aboutToShow.emit()
    assert panel.font_row.isVisibleTo(panel) and panel.mode_buttons[Mode.SINGLE].isChecked()


def test_hotkeys_match_actions(window):
    sheet = {QKeySequence(k).toString() for _, _, keys in HOTKEYS for k in keys}
    bound = {seq.toString() for action in window.actions() for seq in action.shortcuts()}
    assert sheet == bound


def test_no_menu_bar(window):
    assert window.menuBar().actions() == []
