"""Building a PDF with one picture per page."""
from __future__ import annotations

from collections.abc import Sequence

import pymupdf

from mangareader.export.encoders import Encoded
from mangareader.sources.document import MUPDF_LOCK


def images_to_pdf(items: Sequence[tuple[Encoded, tuple[int, int]]], dpi: int = 300) -> bytes:
    with MUPDF_LOCK:
        doc = pymupdf.open()
        for encoded, (w, h) in items:
            page = doc.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
            page.insert_image(page.rect, stream=encoded.data)
        data = doc.tobytes(deflate=True)
        doc.close()
    return data
