import shutil

import pytest

from helpers import RAR_DIR, make_7z, make_epub, make_zip
from mangareader.sources.base import is_junk
from mangareader.sources.detect import Format, detect_format


def test_detect(tmp_path):
    z = make_zip(tmp_path / "a.cbz", {"1.jpg": b"x"})
    e = make_epub(tmp_path / "b.epub", 3)
    shutil.copy(RAR_DIR / "rar5-solid.rar", tmp_path / "fake.cbz")
    s = make_7z(tmp_path / "c.cb7", {"1.jpg": b"x"})
    (tmp_path / "d.pdf").write_bytes(b"%PDF-1.7\n")
    for name in ("e.fb2", "f.mobi", "g.txt", "h.xps", "i.bin"):
        (tmp_path / name).write_bytes(b"zz")
    expect = {z: Format.ZIP, e: Format.EPUB, tmp_path / "fake.cbz": Format.RAR, s: Format.SEVENZIP,
              tmp_path / "d.pdf": Format.PDF, tmp_path / "e.fb2": Format.FB2, tmp_path / "f.mobi": Format.MOBI,
              tmp_path / "g.txt": Format.TXT, tmp_path / "h.xps": Format.XPS, tmp_path / "i.bin": Format.UNKNOWN,
              tmp_path: Format.FOLDER}
    assert {p: detect_format(p) for p in expect} == expect


@pytest.mark.parametrize("p,junk", [("__MACOSX/a.jpg", True), ("x/._a.jpg", True), ("Thumbs.db", True),
                                    ("desktop.ini", True), ("x/.DS_Store", True), ("ch1/001.jpg", False)])
def test_is_junk(p, junk):
    assert is_junk(p) is junk
