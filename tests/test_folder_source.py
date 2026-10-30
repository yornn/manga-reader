import pytest

from helpers import encode, page_image
from mangareader.sources import open_source
from mangareader.sources.base import Original, SourceError
from mangareader.sources.folder import has_direct_images


def test_folder_pages(tmp_path, ctx):
    root = tmp_path / "Манга" / "日本語 漫画"          # Review Focus 2
    for rel in ["ch10/1.jpg", "ch2/1.png", "ch2/10.webp", "ch2/9.jpg", "Thumbs.db", "notes.txt", ".hidden/1.jpg"]:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(encode(page_image(1), "PNG") if rel.endswith((".jpg", ".png", ".webp")) else b"x")
    src = open_source(root, ctx)
    assert src.kind == "images"
    assert [p.inner_path for p in src.pages] == ["ch2/1.png", "ch2/9.jpg", "ch2/10.webp", "ch10/1.jpg"]
    assert src.pages[0].folder == "ch2" and src.pages[0].ext == ".png"
    assert src.read_original(0) == Original((root / "ch2/1.png").read_bytes(), ".png")
    assert src.page_size(0) == (600, 900) and src.load_image(0).image.size == (600, 900)
    assert src.file_size == sum((root / p.inner_path).stat().st_size for p in src.pages)
    assert not has_direct_images(root) and has_direct_images(root / "ch2")


def test_folder_file_vanished(tmp_path, ctx):   # Review Focus 4
    (tmp_path / "s").mkdir()
    (tmp_path / "s/1.png").write_bytes(encode(page_image(1), "PNG"))
    src = open_source(tmp_path / "s", ctx)
    (tmp_path / "s/1.png").unlink()
    with pytest.raises(SourceError):
        src.load_image(0)


def test_broken_image_is_source_error(tmp_path, ctx):
    (tmp_path / "s").mkdir()
    (tmp_path / "s/1.png").write_bytes(b"not a png")
    with pytest.raises(SourceError):
        open_source(tmp_path / "s", ctx).load_image(0)


def test_missing_and_unknown(tmp_path, ctx):
    with pytest.raises(SourceError, match="не найден"):
        open_source(tmp_path / "nope.cbz", ctx)
    (tmp_path / "x.bin").write_bytes(b"zz")
    with pytest.raises(SourceError, match="не поддерживается"):
        open_source(tmp_path / "x.bin", ctx)
