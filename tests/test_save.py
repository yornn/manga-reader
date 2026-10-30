import pytest
from PIL import Image
from PySide6.QtCore import QRectF

from mangareader.export import writer
from mangareader.export.encoders import OutFormat
from mangareader.export.writer import ExportError
from mangareader.settings import ExportPrefs
from mangareader.ui.dialogs import errors
from mangareader.ui.dialogs.save_dialog import SaveDialog
from mangareader.ui.reader.layout import Mode
from mangareader.ui.toast import Toast


def set_format(d, fmt):
    d.format_combo.setCurrentIndex(d.format_combo.findData(fmt))


def set_preset(d, preset):
    d.preset_combo.setCurrentIndex(d.preset_combo.findData(preset))


def accept_dialog_with(monkeypatch, fmt, folder, layout="separate"):
    def fake_exec(self):
        set_format(self, fmt)
        self.folder_edit.setText(str(folder))
        (self.layout_separate if layout == "separate" else self.layout_stitched).setChecked(True)
        return 1
    monkeypatch.setattr(SaveDialog, "exec", fake_exec)


def test_dialog_quality_controls(qtbot):
    d = SaveDialog(None, ExportPrefs(), default_name="x", is_spread=False, is_fragment=True, jpeg_source=True,
                   estimate=None)
    qtbot.addWidget(d)
    d.show()
    set_format(d, OutFormat.JPEG)
    set_preset(d, "high")
    assert d.quality_slider.isEnabled() and d.quality_slider.value() == 92
    set_format(d, OutFormat.WEBP)
    assert d.quality_slider.value() == 90
    set_format(d, OutFormat.PNG)
    assert not d.quality_slider.isEnabled()
    set_format(d, OutFormat.ORIGINAL)
    assert d.hint_label.isVisible() and "PNG" in d.hint_label.text()
    set_format(d, OutFormat.JPEG)
    d.quality_slider.setValue(50)
    assert d.preset_combo.currentText() == "Своё"
    assert d.choice().options.quality == 50 and d.choice().filename == "x"


def test_dialog_layout_group_only_for_spread(qtbot):
    single = SaveDialog(None, ExportPrefs(), default_name="x", is_spread=False, is_fragment=False,
                        jpeg_source=False, estimate=None)
    spread = SaveDialog(None, ExportPrefs(), default_name="x", is_spread=True, is_fragment=False,
                        jpeg_source=False, estimate=None)
    for d in (single, spread):
        qtbot.addWidget(d)
        d.show()
    assert not single.layout_group.isVisible() and spread.layout_group.isVisible()


def test_estimate_shown(qtbot):
    d = SaveDialog(None, ExportPrefs(), default_name="x", is_spread=False, is_fragment=False, jpeg_source=False,
                   estimate=lambda o: 2_500_000)
    qtbot.addWidget(d)
    d.show()
    qtbot.waitUntil(lambda: "2,4 МБ" in d.size_label.text(), timeout=3000)


def test_dialog_remembers_choice(qtbot, tmp_path):
    prefs = ExportPrefs()
    d = SaveDialog(None, prefs, default_name="x", is_spread=False, is_fragment=False, jpeg_source=False,
                   estimate=None)
    qtbot.addWidget(d)
    set_format(d, OutFormat.WEBP)
    set_preset(d, "compact")
    d.folder_edit.setText(str(tmp_path))
    d.store_into(prefs)
    assert (prefs.fmt, prefs.preset, prefs.quality, prefs.folder) == ("webp", "compact", 70, str(tmp_path))


def test_save_original_page_is_byte_copy(window, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    out = tmp_path / "out"
    out.mkdir()
    accept_dialog_with(monkeypatch, fmt=OutFormat.ORIGINAL, folder=out)
    [p] = window.save_current()
    assert p.read_bytes() == window.controller.source.read_original(0).data and p.name.endswith(".png")
    assert p.name == "S – стр 001.png"


def test_save_fragment(window, qtbot, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.selection.activate()
    window.selection.set_rect(QRectF(100, 200, 300, 400))
    accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path)
    [p] = window.save_current()
    assert Image.open(p).size == (300, 400)


def test_spread_separate_and_stitched(window, tmp_path, monkeypatch, cbz_spread):
    window.open_paths([cbz_spread])
    window.controller.set_mode(Mode.SPREAD)
    window.controller.next()
    accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path, layout="separate")
    paths = window.save_current()
    assert len(paths) == 2 and paths[0].name != paths[1].name
    accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path, layout="stitched")
    [p] = window.save_current()
    assert Image.open(p).width == 2000


def test_quick_save(window, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.services.settings.export.folder = str(tmp_path)
    window.services.settings.export.fmt = "jpeg"
    monkeypatch.setattr(SaveDialog, "exec", lambda self: pytest.fail("окно не должно открываться"))
    [p] = window.save_current(quick=True)
    assert p.suffix == ".jpg" and Toast.last_text().startswith("Сохранено:")


def test_quick_save_without_folder_opens_dialog(window, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    window.services.settings.export.folder = ""
    opened = []
    monkeypatch.setattr(SaveDialog, "exec", lambda self: opened.append(1) or 0)
    assert window.save_current(quick=True) == [] and opened


def test_export_error_shown(window, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path)

    def boom(*a):
        raise ExportError("Недостаточно места на диске")
    monkeypatch.setattr(writer, "write_atomic", boom)
    shown = []
    monkeypatch.setattr(errors, "show_error", lambda p, m, l: shown.append(m))
    assert window.save_current() == [] and shown == ["Недостаточно места на диске"]


def test_name_uses_chapter_of_current_volume(window, qtbot, tmp_path):
    from helpers import encode, make_zip, page_image
    img = encode(page_image(1), "PNG")
    s = tmp_path / "Серия"
    make_zip(s / "Vol 01.cbz", {"ch1/1.png": img, "ch1/2.png": img, "ch2/1.png": img, "ch2/2.png": img})
    make_zip(s / "Vol 02.cbz", {"ch3/1.png": img, "ch3/2.png": img, "ch4/1.png": img, "ch4/2.png": img})
    window.open_paths([s / "Vol 02.cbz"])
    qtbot.waitUntil(lambda: len(window.controller.entries) == 2, timeout=5000)
    assert window.controller.entry_index == 1
    fields = window.default_name_fields(0)
    assert (fields.series, fields.volume, fields.chapter, fields.page) == ("Серия", "2", "3", 1)
    assert window.default_name_fields(2).chapter == "4"
