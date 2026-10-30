"""PDF, EPUB, FB2, MOBI, XPS and TXT through MuPDF.

Fixed-layout pages that are a single full-page picture (typical manga PDFs) expose
that embedded picture as the page's original; everything else is rendered.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pymupdf
from PIL import Image

from mangareader.imaging import Decoded, ImageDecodeError, decode
from mangareader.sources.base import Original, PageRef, PageSource, PasswordRequired, SourceError

FIXED_DPI = 300
REFLOW_DPI = 192
DEFAULT_REFLOW = (800, 1131, 12.0)

_EXT = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "jpx": ".jp2", "bmp": ".bmp", "tiff": ".tif",
        "tif": ".tif", "webp": ".webp"}
_BROKEN = "Документ повреждён или не поддерживается"
_CHAPTER_SPAN = 1_000_000

# MuPDF is not thread-safe across documents either, so every document shares one lock
MUPDF_LOCK = threading.RLock()


class DocumentSource(PageSource):
    kind = "document"

    def __init__(self, path: Path, password: str | None = None, filetype: str | None = None):
        super().__init__(path)
        self._lock = MUPDF_LOCK
        with self._lock:
            try:
                self._doc = pymupdf.open(str(self.path), filetype=filetype)
            except Exception as e:
                raise SourceError(_BROKEN) from e
            if self._doc.needs_pass and not self._doc.authenticate(password or ""):
                self._doc.close()
                raise PasswordRequired(wrong=bool(password))
        self._xrefs: dict[int, int | None] = {}
        with self._lock:
            try:
                self.is_reflowable = bool(self._doc.is_reflowable)
                self.file_size = self.path.stat().st_size
                if self.is_reflowable:
                    self.relayout(*DEFAULT_REFLOW)
                else:
                    self._rebuild_pages()
            except Exception as e:  # MuPDF parses lazily: a broken FB2/EPUB fails here, not in open()
                self._doc.close()
                raise SourceError(_BROKEN) from e
        if not self.pages:
            self._doc.close()
            raise SourceError(_BROKEN)

    def _rebuild_pages(self) -> None:
        self.pages = [PageRef(i, f"#{i + 1}", "", "", 0) for i in range(self._doc.page_count)]
        self._xrefs.clear()

    def relayout(self, width_px: int, height_px: int, font_size: float) -> None:
        if not self.is_reflowable:
            return
        with self._lock:
            try:
                self._doc.layout(width=width_px * 0.75, height=height_px * 0.75, fontsize=font_size)
                self._rebuild_pages()
            except Exception as e:
                raise SourceError(_BROKEN) from e

    def _dpi(self) -> int:
        return REFLOW_DPI if self.is_reflowable else FIXED_DPI

    def _single_image_xref(self, i: int) -> int | None:
        if i in self._xrefs:
            return self._xrefs[i]
        xref = None
        page = self._doc[i]
        images = page.get_images(full=True)
        if len(images) == 1 and not images[0][1] and not page.get_text("text").strip():
            rects = page.get_image_rects(images[0][0])
            area = page.rect.width * page.rect.height
            if rects and rects[0].width * rects[0].height >= 0.95 * area:
                xref = images[0][0]
        self._xrefs[i] = xref
        return xref

    def _extract(self, i: int) -> tuple[dict, str] | None:
        xref = self._single_image_xref(i)
        if xref is None:
            return None
        info = self._doc.extract_image(xref)
        ext = _EXT.get(info.get("ext", ""))
        return (info, ext) if ext else None

    def read_original(self, i: int) -> Original | None:
        with self._lock:
            try:
                found = self._extract(i)
            except Exception as e:
                raise SourceError(_BROKEN) from e
        return Original(found[0]["image"], found[1]) if found else None

    def load_image(self, i: int, draft: tuple[int, int] | None = None) -> Decoded:
        original = self.read_original(i)
        if original is not None:
            try:
                return decode(original.data, draft)
            except ImageDecodeError as e:
                raise SourceError("Не удалось прочитать страницу: файл повреждён") from e
        with self._lock:
            try:
                page = self._doc[i]
                zoom = draft[1] / page.rect.height if draft else self._dpi() / 72
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            except Exception as e:
                raise SourceError(_BROKEN) from e
        return Decoded(img, None, None, None)

    def page_size(self, i: int) -> tuple[int, int] | None:
        with self._lock:
            try:
                found = self._extract(i)
                if found:
                    return found[0]["width"], found[0]["height"]
                rect = self._doc[i].rect
            except Exception:
                return None
        scale = self._dpi() / 72
        return round(rect.width * scale), round(rect.height * scale)

    # Reading position of a reflowable book: chapter number plus the position of the page's middle
    # inside the chapter, in millionths. Unlike MuPDF bookmarks (in-memory pointers) this survives
    # reopening the file and changing the font size.
    def position_token(self, i: int) -> int:
        if not self.is_reflowable:
            return i
        with self._lock:
            chapter, page_in_chapter = self._doc.location_from_page_number(i)
            pages = max(1, self._doc.chapter_page_count(chapter))
        return chapter * _CHAPTER_SPAN + ((2 * page_in_chapter + 1) * _CHAPTER_SPAN) // (2 * pages)

    def page_for_token(self, token: int) -> int:
        if not self.is_reflowable:
            return super().page_for_token(token)
        chapter, fraction = divmod(max(0, token), _CHAPTER_SPAN)
        with self._lock:
            try:
                chapter = min(chapter, self._doc.chapter_count - 1)
                pages = max(1, self._doc.chapter_page_count(chapter))
                page_in_chapter = min(pages - 1, fraction * pages // _CHAPTER_SPAN)
                page = self._doc.page_number_from_location((chapter, page_in_chapter))
            except Exception:
                page = 0
        return super().page_for_token(page)

    def close(self) -> None:
        with self._lock:
            self._doc.close()
