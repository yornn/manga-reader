import os
import time

from helpers import encode, make_zip, page_image
from mangareader.library import scanner
from mangareader.library.scanner import SourceProber, scan_series
from mangareader.library.store import Store


def test_prober_uses_cache(tmp_path, ctx, monkeypatch):
    st = Store(tmp_path / "db")
    p = make_zip(tmp_path / "s/c001.cbz", {"1.png": encode(page_image(1), "PNG")})
    calls = []
    real = scanner.open_source
    monkeypatch.setattr(scanner, "open_source", lambda *a, **k: calls.append(1) or real(*a, **k))
    prober = SourceProber(st, ctx)
    first = prober(p)
    assert prober(p) == first and first.page_count == 1 and first.record_id
    assert len(calls) == 1
    os.utime(p, (time.time() + 10, time.time() + 10))
    prober(p)
    assert len(calls) == 2


def test_prober_reads_internal_chapters_and_locked(tmp_path, ctx):
    st = Store(tmp_path / "db")
    img = encode(page_image(1), "PNG")
    p = make_zip(tmp_path / "v.cbz", {"w/ch1/1.png": img, "w/ch1/2.png": img, "w/ch2/1.png": img})
    info = SourceProber(st, ctx)(p)
    assert [c.start_page for c in info.internal] == [0, 2]
    from helpers import make_7z
    locked = make_7z(tmp_path / "l.cb7", {"1.png": img}, password="pw")
    assert SourceProber(st, ctx)(locked).locked


def test_scan_series_end_to_end(tmp_path, ctx):
    for n in ("c002", "c001"):
        make_zip(tmp_path / "S" / f"{n}.cbz", {"1.png": encode(page_image(1), "PNG")})
    tree = scan_series(tmp_path / "S", Store(tmp_path / "db"), ctx)
    assert [e.title for e in tree.reading_order()] == ["Глава 1", "Глава 2"] and tree.title == "S"
