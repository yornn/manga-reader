import os
from concurrent.futures import ThreadPoolExecutor

import pymupdf
import pytest

from helpers import encode, make_epub, make_fb2, make_pdf, page_image
from mangareader.sources import open_source
from mangareader.sources.base import Original, PasswordRequired, SourceError


def test_pdf_single_image_original(tmp_path, ctx):
    jpgs = [encode(page_image(i), "JPEG") for i in range(3)]
    src = open_source(make_pdf(tmp_path / "m.pdf", jpgs), ctx)
    assert src.kind == "document" and not src.is_reflowable and len(src.pages) == 3
    assert src.pages[0].inner_path == "#1"
    assert src.read_original(1) == Original(jpgs[1], ".jpg")
    assert src.load_image(1).image.size == (600, 900) and src.page_size(1) == (600, 900)


def test_pdf_text_page_rendered_at_300dpi(tmp_path, ctx):
    doc = pymupdf.open()
    doc.new_page(width=144, height=216).insert_text((20, 50), "Текст")
    doc.save(tmp_path / "t.pdf")
    src = open_source(tmp_path / "t.pdf", ctx)
    assert src.read_original(0) is None and src.load_image(0).image.size == (600, 900)
    assert src.page_size(0) == (600, 900)


def test_pdf_draft_render(tmp_path, ctx):
    doc = pymupdf.open()
    doc.new_page(width=144, height=216).insert_text((20, 50), "Текст")
    doc.save(tmp_path / "t.pdf")
    img = open_source(tmp_path / "t.pdf", ctx).load_image(0, draft=(240, 360)).image
    assert abs(img.height - 360) <= 2


def test_pdf_password(tmp_path, ctx):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "p.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(PasswordRequired):
        open_source(tmp_path / "p.pdf", ctx)
    with pytest.raises(PasswordRequired) as e:
        open_source(tmp_path / "p.pdf", ctx, password="bad")
    assert e.value.wrong and len(open_source(tmp_path / "p.pdf", ctx, password="pw").pages) == 1


def test_epub_relayout_keeps_position(tmp_path, ctx):
    src = open_source(make_epub(tmp_path / "b.epub", 400), ctx)
    assert src.is_reflowable and src.kind == "document"
    src.relayout(800, 1131, 12)
    n1 = len(src.pages)
    mid = n1 // 2
    tok = src.position_token(mid)
    src.relayout(800, 1131, 20)
    n2 = len(src.pages)
    assert n2 > n1 and abs(src.page_for_token(tok) / n2 - mid / n1) < 0.1


def test_fb2_renders_cyrillic(tmp_path, ctx):
    src = open_source(make_fb2(tmp_path / "k.fb2", "Привет, мир " * 50), ctx)
    img = src.load_image(0).image.convert("L")
    assert len(src.pages) >= 1 and img.getextrema()[0] < 128      # есть тёмные пиксели текста


def test_txt_opens(tmp_path, ctx):
    (tmp_path / "a.txt").write_text("Строка текста\n" * 100, encoding="utf-8")
    assert len(open_source(tmp_path / "a.txt", ctx).pages) >= 1


def test_corrupt_pdf(tmp_path, ctx):                           # Review Focus 4
    (tmp_path / "c.pdf").write_bytes(b"%PDF-1.7\n" + os.urandom(2000))
    with pytest.raises(SourceError):
        open_source(tmp_path / "c.pdf", ctx).load_image(0)


def test_concurrent_render(tmp_path, ctx):                     # Review Focus 5
    src = open_source(make_pdf(tmp_path / "m.pdf", [encode(page_image(i), "PNG") for i in range(6)]), ctx)
    with ThreadPoolExecutor(4) as ex:
        sizes = list(ex.map(lambda i: src.load_image(i % 6).image.size, range(24)))
    assert set(sizes) == {(600, 900)}
