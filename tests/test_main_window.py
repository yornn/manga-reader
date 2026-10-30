from pathlib import Path

from PySide6.QtCore import Qt

import mangareader
from helpers import encode, make_7z, make_zip, page_image
from mangareader.ui.dialogs import errors
from mangareader.ui.reader.layout import Direction, Mode
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
