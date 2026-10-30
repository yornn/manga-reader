import pytest

from helpers import encode, make_zip, page_image
from mangareader.library.scanner import SourceProber
from mangareader.library.store import Store
from mangareader.render import covers as covers_module
from mangareader.render.covers import CoverLoader
from mangareader.render.thumbs import THUMB_HEIGHT, ThumbnailStore
from mangareader.sources import open_source


def prober_id(st, ctx, path):
    return SourceProber(st, ctx)(path).record_id


def test_cover_for_archive(qtbot, tmp_path, ctx):
    st = Store(tmp_path / "db")
    thumbs = ThumbnailStore(tmp_path / "thumbs")
    arc = make_zip(tmp_path / "S" / "v.cbz", {"1.png": encode(page_image(1, (600, 900)), "PNG")})
    covers = CoverLoader(st, thumbs, ctx)
    sid = prober_id(st, ctx, arc)
    with qtbot.waitSignal(covers.cover_ready):
        assert covers.cover(sid) is None
    assert covers.cover(sid).height() == THUMB_HEIGHT and thumbs.get(st.source_by_id(sid).fingerprint, 0)


def test_cover_reuses_thumbnail_on_disk(qtbot, tmp_path, ctx, monkeypatch):
    st = Store(tmp_path / "db")
    thumbs = ThumbnailStore(tmp_path / "thumbs")
    arc = make_zip(tmp_path / "S" / "v.cbz", {"1.png": encode(page_image(1), "PNG")})
    sid = prober_id(st, ctx, arc)
    with open_source(arc, ctx) as src:
        thumbs.create(src, 0, st.source_by_id(sid).fingerprint)
    monkeypatch.setattr(covers_module, "open_source", lambda *a, **k: pytest.fail("must not open"))
    covers = CoverLoader(st, thumbs, ctx)
    with qtbot.waitSignal(covers.cover_ready):
        covers.cover(sid)


def test_missing_or_locked_gives_no_cover(qtbot, tmp_path, ctx):
    st = Store(tmp_path / "db")
    covers = CoverLoader(st, ThumbnailStore(tmp_path / "t"), ctx)
    arc = make_zip(tmp_path / "S" / "v.cbz", {"1.png": encode(page_image(1), "PNG")})
    sid = prober_id(st, ctx, arc)
    arc.unlink()
    covers.cover(sid)
    qtbot.waitUntil(lambda: not covers.pending, timeout=5000)
    assert covers.cover(sid) is None and covers.cover(None) is None and not covers.pending   # no retry loop
