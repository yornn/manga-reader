from helpers import encode, make_zip, page_image
from mangareader.render.cache import ImageCache, image_nbytes
from mangareader.render.loader import PageLoader, pil_to_qimage
from mangareader.render.thumbs import ThumbnailStore
from mangareader.sources import open_source
from mangareader.sources.base import SourceError


def test_cache_lru_budget():
    c = ImageCache(100)
    c.put("a", 1, 40)
    c.put("b", 2, 40)
    c.get("a")
    c.put("c", 3, 40)
    assert (c.get("a"), c.get("b"), c.get("c"), c.used_bytes) == (1, None, 3, 80)
    c.put("huge", 4, 500)
    assert c.get("huge") == 4          # только что положенное не вытесняется
    c.discard_where(lambda k: k == "huge")
    assert c.get("huge") is None and c.used_bytes == 0


def test_image_nbytes():
    assert image_nbytes(page_image(1, (10, 20))) == 600
    assert image_nbytes(pil_to_qimage(page_image(1, (10, 20)).convert("L"))) >= 200


def test_pil_to_qimage_modes():
    for mode in ("L", "RGB", "RGBA", "LA"):
        q = pil_to_qimage(page_image(1, (31, 17)).convert(mode))
        assert (q.width(), q.height()) == (31, 17) and not q.isNull()
    q = pil_to_qimage(page_image(3, (31, 17)))
    assert q.pixelColor(0, 0).red() == (3 * 53) % 256


def test_thumbnail_store(tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.jpg": encode(page_image(1, (1200, 1800)), "JPEG")}), ctx)
    ts = ThumbnailStore(tmp_path / "th")
    img = ts.create(src, 0, "fp1")
    assert img.height == 240 and ts.path_for("fp1", 0).exists() and ts.get("fp1", 0).size == img.size
    assert ts.get("fp1", 1) is None


def test_loader_full_scaled_and_failure(qtbot, tmp_path, ctx):
    files = {"1.png": encode(page_image(1, (1000, 1500)), "PNG"), "2.png": b"broken"}
    src = open_source(make_zip(tmp_path / "a.cbz", files), ctx)
    ld = PageLoader(ImageCache(512 * 2**20), ThumbnailStore(tmp_path / "th"))
    ld.register("k", src, "fp")
    with qtbot.waitSignal(ld.full_ready, timeout=5000):
        assert ld.full("k", 0) is None
    assert ld.full("k", 0).image.size == (1000, 1500)
    with qtbot.waitSignal(ld.scaled_ready, timeout=5000):
        ld.scaled("k", 0, 200, 300)
    q = ld.scaled("k", 0, 200, 300)
    assert (q.width(), q.height()) == (200, 300)
    with qtbot.waitSignal(ld.failed, timeout=5000) as sig:
        ld.full("k", 1)
    assert sig.args[0:2] == ["k", 1] and ld.error("k", 1)


def test_loader_scaled_without_full_loads_both(qtbot, tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.png": encode(page_image(1, (1000, 1500)), "PNG")}), ctx)
    ld = PageLoader(ImageCache(2**28), ThumbnailStore(tmp_path / "th"))
    ld.register("k", src, "fp")
    with qtbot.waitSignal(ld.scaled_ready, timeout=5000):
        assert ld.scaled("k", 0, 100, 150) is None
    assert ld.scaled("k", 0, 100, 150).width() == 100


def test_thumbnail_via_loader(qtbot, tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.png": encode(page_image(1, (1000, 1500)), "PNG")}), ctx)
    ld = PageLoader(ImageCache(2**28), ThumbnailStore(tmp_path / "th"))
    ld.register("k", src, "fp")
    with qtbot.waitSignal(ld.thumb_ready, timeout=5000):
        assert ld.thumbnail("k", 0) is None
    assert ld.thumbnail("k", 0).height() == 240


def test_probe_sizes_and_unregister(qtbot, tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.png": encode(page_image(1, (1600, 900)), "PNG")}), ctx)
    cache = ImageCache(2**26)
    ld = PageLoader(cache, ThumbnailStore(tmp_path / "th"))
    ld.register("k", src, "fp")
    with qtbot.waitSignal(ld.size_known, timeout=5000) as sig:
        ld.probe_sizes("k")
    assert sig.args == ["k", 0, 1600, 900]
    with qtbot.waitSignal(ld.full_ready, timeout=5000):
        ld.full("k", 0)
    ld.unregister("k")
    assert cache.used_bytes == 0


def _blocking(src, gate, fail, entered):
    real = src.load_image

    def load(i, draft=None):
        entered.set()
        gate.wait(5)
        if fail:
            raise SourceError("Не удалось прочитать страницу")
        return real(i, draft)
    src.load_image = load
    return src


def test_failure_after_unregister_is_forgotten(qtbot, tmp_path, ctx):
    import threading
    from PySide6.QtCore import QThreadPool
    data = {"1.png": encode(page_image(1, (100, 150)), "PNG")}
    gate, entered = threading.Event(), threading.Event()
    old = _blocking(open_source(make_zip(tmp_path / "a.cbz", data), ctx), gate, fail=True, entered=entered)
    ld = PageLoader(ImageCache(2**26), ThumbnailStore(tmp_path / "th"))
    ld.register("k", old, "fp")
    ld.full("k", 0)
    assert entered.wait(5)
    ld.unregister("k")
    ld.register("k", open_source(tmp_path / "a.cbz", ctx), "fp")
    gate.set()
    QThreadPool.globalInstance().waitForDone(5000)
    qtbot.wait(50)
    assert ld.error("k", 0) is None


def test_stale_scaled_copy_is_not_cached(qtbot, tmp_path, ctx):
    import threading
    from PySide6.QtCore import QThreadPool
    gate, entered = threading.Event(), threading.Event()
    old = _blocking(open_source(make_zip(tmp_path / "a.cbz", {"1.png": encode(page_image(1, (100, 150)), "PNG")}),
                                ctx), gate, fail=False, entered=entered)
    ld = PageLoader(ImageCache(2**26), ThumbnailStore(tmp_path / "th"))
    ld.register("k", old, "fp")
    ld.scaled("k", 0, 50, 75)
    assert entered.wait(5)
    ld.register("k", open_source(make_zip(tmp_path / "b.cbz", {"1.png": encode(page_image(2, (100, 150)), "PNG")}),
                                 ctx), "fp2")
    gate.set()
    QThreadPool.globalInstance().waitForDone(5000)
    assert not ld.has_scaled("k", 0, 50, 75)
