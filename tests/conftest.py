import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGAREADER_DATA", str(tmp_path / "data"))


@pytest.fixture
def ctx(tmp_path):
    from mangareader.paths import find_7zz
    from mangareader.sources import SourceContext

    return SourceContext(extract_root=tmp_path / "extract", seven_zip=find_7zz())


@pytest.fixture
def make_window(qtbot):
    def factory(_qtbot=None):
        from mangareader.paths import resolve_data_location
        from mangareader.ui.main_window import MainWindow
        from mangareader.ui.reader.controller import make_services

        window = MainWindow(make_services(resolve_data_location()))
        qtbot.addWidget(window)
        window.resize(900, 700)
        with qtbot.waitExposed(window):
            window.show()
        with qtbot.waitActive(window):
            window.raise_()
            window.activateWindow()
        return window
    return factory


@pytest.fixture
def window(make_window):
    return make_window()


@pytest.fixture
def cbz_1000x1500(tmp_path):
    from helpers import encode, make_zip, page_image

    return make_zip(tmp_path / "S" / "one.cbz", {"001.png": encode(page_image(1, (1000, 1500)), "PNG")})


@pytest.fixture
def cbz_spread(tmp_path):
    from helpers import encode, make_zip, page_image

    pages = {f"{i:03}.png": encode(page_image(i, (1000, 1500)), "PNG") for i in range(3)}
    return make_zip(tmp_path / "S" / "spread.cbz", pages)


@pytest.fixture
def services(qapp):
    from mangareader.paths import resolve_data_location
    from mangareader.ui.reader.controller import make_services

    s = make_services(resolve_data_location())
    yield s
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5000)
    s.shutdown()
