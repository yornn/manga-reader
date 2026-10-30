"""Builders for test fixtures: page images, archives and documents."""
from __future__ import annotations

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from mangareader.paths import find_7zz

RAR_DIR = Path(__file__).parent / "fixtures" / "rar"


def page_image(i: int, size=(600, 900), mode: str = "RGB") -> Image.Image:
    color = ((i * 53) % 256, (i * 97) % 256, (i * 31) % 256)
    img = Image.new("RGB", size, color)
    ImageDraw.Draw(img).rectangle((10 + i, 10 + i, 59 + i, 59 + i), fill=(255, 255, 255))
    return img if mode == "RGB" else img.convert(mode)


def encode(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


class _RawNameInfo(zipfile.ZipInfo):
    """ZipInfo that writes a pre-encoded name without the UTF-8 flag."""

    raw_name: bytes = b""

    def _encodeFilenameFlags(self):
        return self.raw_name, self.flag_bits & ~0x800


def make_zip(path: Path, files: dict[str, bytes], raw_encoding: str | None = None,
             compress: int = zipfile.ZIP_STORED) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=compress) as zf:
        for name, data in files.items():
            if raw_encoding:
                info = _RawNameInfo(name)
                info.raw_name = name.encode(raw_encoding)
                info.compress_type = compress
                zf.writestr(info, data)
            else:
                zf.writestr(name, data, compress_type=compress)
    return path


def make_7z(path: Path, files: dict[str, bytes], password: str | None = None, fmt: str = "7z") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as stage:
        for name, data in files.items():
            f = Path(stage) / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        args = [str(find_7zz()), "a", f"-t{fmt}", str(path.resolve())]
        if password:
            args.append(f"-p{password}")
            if fmt == "7z":
                args.append("-mhe=on")
        args += list(files)
        subprocess.run(args, cwd=stage, check=True, stdin=subprocess.DEVNULL, capture_output=True)
    return path


def make_pdf(path: Path, images: list[bytes]) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for data in images:
        w, h = Image.open(io.BytesIO(data)).size
        page = doc.new_page(width=w * 72 / 300, height=h * 72 / 300)
        page.insert_image(page.rect, stream=data)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def make_epub(path: Path, paragraphs: int) -> Path:
    body = "".join(f"<p>Абзац {i}. Это тестовая строка книги, чтобы страниц было много.</p>"
                   for i in range(paragraphs))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
                   'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<dc:title>Книга</dc:title><dc:identifier id="id">test</dc:identifier></metadata>'
                   '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
                   '<spine><itemref idref="c1"/></spine></package>')
        z.writestr("OEBPS/c1.xhtml",
                   f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>1</title></head><body>{body}</body></html>')
    return path


def make_fb2(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"><body><section>'
        f"<p>{text}</p></section></body></FictionBook>",
        encoding="utf-8",
    )
    return path
