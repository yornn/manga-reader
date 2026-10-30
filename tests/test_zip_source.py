import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from helpers import encode, make_7z, make_zip, page_image
from mangareader.sources import open_source
from mangareader.sources.base import Original, PasswordRequired, SourceError
from mangareader.sources.sevenzip import SevenZipSource
from mangareader.sources.zip import ZipSource, choose_zip_encoding, zip_needs_7z


def test_choose_encoding():
    assert choose_zip_encoding([]) == "utf-8"
    assert choose_zip_encoding(["001.jpg".encode()]) == "utf-8"
    assert choose_zip_encoding(["第1話/001.jpg".encode("utf-8")]) == "utf-8"
    assert choose_zip_encoding(["第1話/001.jpg".encode("cp932")]) == "cp932"
    assert choose_zip_encoding(["Глава 1/001.jpg".encode("cp866")]) == "cp866"


@pytest.mark.parametrize("enc,name", [("cp932", "第1話/001.jpg"), ("cp866", "Глава 1/001.jpg")])
def test_legacy_names(tmp_path, ctx, enc, name):
    src = open_source(make_zip(tmp_path / "a.cbz", {name: encode(page_image(1), "JPEG")}, raw_encoding=enc), ctx)
    assert isinstance(src, ZipSource)
    assert [p.inner_path for p in src.pages] == [name]


def test_pages_order_and_junk(tmp_path, ctx):
    files = {"wrap/10.jpg": b"a", "wrap/2.jpg": b"b", "wrap/._2.jpg": b"c", "__MACOSX/wrap/2.jpg": b"d",
             "wrap/credits.txt": b"e", "wrap/Thumbs.db": b"f"}
    src = open_source(make_zip(tmp_path / "Манга" / "a.zip", files), ctx)
    assert [p.inner_path for p in src.pages] == ["wrap/2.jpg", "wrap/10.jpg"]
    assert src.read_original(1) == Original(b"a", ".jpg") and src.pages[0].folder == "wrap"
    assert src.file_size == (tmp_path / "Манга" / "a.zip").stat().st_size


def test_page_size_from_head(tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.jpg": encode(page_image(1, (1234, 2345)), "JPEG")}), ctx)
    assert src.page_size(0) == (1234, 2345)


def test_concurrent_reads(tmp_path, ctx):                      # Review Focus 5
    files = {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(20)}
    src = open_source(make_zip(tmp_path / "a.cbz", files, compress=zipfile.ZIP_DEFLATED), ctx)
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda i: src.read_original(i).data, list(range(20)) * 4))
    assert got == [files[f"{i:03}.png"] for i in range(20)] * 4


def test_truncated_zip(tmp_path, ctx):                          # Review Focus 4
    p = make_zip(tmp_path / "a.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(3)})
    p.write_bytes(p.read_bytes()[:200])
    with pytest.raises(SourceError):
        open_source(p, ctx)


def test_corrupt_member_only_that_page(tmp_path, ctx):
    files = {"1.png": encode(page_image(1), "PNG"), "2.png": encode(page_image(2), "PNG")}
    p = make_zip(tmp_path / "a.cbz", files, compress=zipfile.ZIP_DEFLATED)
    data = bytearray(p.read_bytes())
    i = data.find(b"2.png") + 40
    data[i:i + 20] = b"\0" * 20
    p.write_bytes(bytes(data))
    src = open_source(p, ctx)
    assert src.load_image(0).image.size == (600, 900)
    with pytest.raises(SourceError):
        src.load_image(1)


def test_encrypted_zip_goes_to_7zip(tmp_path, ctx):
    p = make_7z(tmp_path / "e.cbz", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw", fmt="zip")
    assert zip_needs_7z(p)
    with pytest.raises(PasswordRequired):
        open_source(p, ctx)
    assert isinstance(open_source(p, ctx, password="pw"), SevenZipSource)


def test_plain_zip_does_not_need_7z(tmp_path):
    assert not zip_needs_7z(make_zip(tmp_path / "a.cbz", {"1.jpg": b"x"}))

