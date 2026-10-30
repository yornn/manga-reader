from helpers import encode, library, make_epub, make_zip, page_image
from mangareader.ui.library.scan_runner import ScanRunner


def test_single_file_series_and_where(window, qtbot, tmp_path):
    dl = tmp_path / "Загрузки"
    book = make_epub(dl / "b.epub", 40)
    make_epub(dl / "other.epub", 40)
    c = window.controller
    assert c.open_path(book, series=book)
    qtbot.wait(300)
    assert [e.path for e in c.entries] == [book] and c.where_parts() == []
    s = tmp_path / "S"
    make_zip(s / "Vol 01.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(4)})
    assert c.open_path(s / "Vol 01.cbz", series=s)
    c.next()
    assert c.where_parts() == ["Том 1", "стр. 2"]
    assert window.services.store.progress(c.record.id).fraction == 0.5


def test_tree_scanned_signal(window, qtbot, tmp_path):
    s = tmp_path / "S"
    make_zip(s / "c1.cbz", {"1.png": encode(page_image(1), "PNG")})
    make_zip(s / "c2.cbz", {"1.png": encode(page_image(1), "PNG")})
    with qtbot.waitSignal(window.controller.tree_scanned, timeout=5000) as b:
        window.controller.open_path(s / "c1.cbz", series=s)
    assert b.args[0].root == s


def test_scan_runner(qtbot, services, tmp_path):
    services.catalog.add_root(library(tmp_path))
    runner = ScanRunner(services)
    with qtbot.waitSignal(runner.finished, timeout=20000):
        runner.start()
        runner.start()                                   # a second start queues one more pass
    qtbot.waitUntil(lambda: not runner.running, timeout=20000)
    assert len(services.catalog.cards()) == 3 and runner.failed == []
