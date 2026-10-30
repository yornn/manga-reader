"""Encoding pages and fragments into the formats of the save dialog (spec 8.2-8.3)."""
from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from PIL import Image

from mangareader.export.model import PageImage
from mangareader.imaging import Decoded, resize_lanczos
from mangareader.sources.base import Original


class OutFormat(StrEnum):
    ORIGINAL = "original"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    AVIF = "avif"
    TIFF = "tiff"
    BMP = "bmp"
    PDF = "pdf"


LOSSY = frozenset({OutFormat.JPEG, OutFormat.WEBP, OutFormat.AVIF})
QUALITY_PRESETS = {
    "max": {OutFormat.JPEG: 100, OutFormat.WEBP: 100, OutFormat.AVIF: 95},
    "high": {OutFormat.JPEG: 92, OutFormat.WEBP: 90, OutFormat.AVIF: 80},
    "medium": {OutFormat.JPEG: 85, OutFormat.WEBP: 80, OutFormat.AVIF: 65},
    "compact": {OutFormat.JPEG: 75, OutFormat.WEBP: 70, OutFormat.AVIF: 50},
}
PRESET_LABELS = {"max": "Максимум", "high": "Высокое", "medium": "Среднее", "compact": "Компактное"}

_EXT = {OutFormat.PNG: ".png", OutFormat.JPEG: ".jpg", OutFormat.WEBP: ".webp", OutFormat.AVIF: ".avif",
        OutFormat.TIFF: ".tif", OutFormat.BMP: ".bmp"}
_ICC_FORMATS = {OutFormat.PNG, OutFormat.JPEG, OutFormat.WEBP, OutFormat.AVIF, OutFormat.TIFF}


@dataclass(frozen=True)
class Resize:
    mode: str = "original"
    value: int = 100


@dataclass(frozen=True)
class EncodeOptions:
    fmt: OutFormat
    quality: int = 92
    resize: Resize = Resize()


@dataclass(frozen=True)
class Encoded:
    data: bytes
    ext: str


def apply_resize(img: Image.Image, resize: Resize) -> Image.Image:
    w, h = img.size
    if resize.mode == "percent":
        k = resize.value / 100
    elif resize.mode == "long_side":
        k = resize.value / max(w, h)
    else:
        return img
    if k >= 1:
        return img
    return resize_lanczos(img, max(1, round(w * k)), max(1, round(h * k)))


def _save(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **{k: v for k, v in kw.items() if v is not None})
    return buf.getvalue()


def _flatten(img: Image.Image) -> Image.Image:
    """JPEG has no transparency: put transparent pixels on white."""
    if img.mode in ("RGBA", "LA"):
        base = Image.new("RGB" if img.mode == "RGBA" else "L", img.size, "white")
        base.paste(img, mask=img.getchannel("A"))
        return base
    return img


def encode_image(img: Image.Image, fmt: OutFormat, quality: int, icc: bytes | None) -> Encoded:
    icc = icc if fmt in _ICC_FORMATS else None
    if fmt is OutFormat.JPEG:
        data = _save(_flatten(img), "JPEG", quality=quality, subsampling=0 if quality >= 90 else 2, optimize=True,
                     icc_profile=icc)
    elif fmt is OutFormat.WEBP:
        data = _save(img, "WEBP", quality=quality, icc_profile=icc)
    elif fmt is OutFormat.AVIF:
        data = _save(img, "AVIF", quality=quality, icc_profile=icc)
    elif fmt is OutFormat.TIFF:
        data = _save(img, "TIFF", compression="tiff_lzw", icc_profile=icc)
    elif fmt is OutFormat.BMP:
        data = _save(img.convert("RGBA") if img.mode == "LA" else img, "BMP")
    else:
        data = _save(img, "PNG", compress_level=6, icc_profile=icc)
    return Encoded(data, _EXT[fmt])


def _keep_original_format(img: Image.Image, src: Decoded | None) -> Encoded:
    """'As original' for changed pixels: same format as the source, as close to lossless as it allows."""
    fmt = src.format if src else None
    icc = src.icc if src else None
    if fmt == "JPEG":
        tables = src.jpeg
        if tables:
            sampling = tables.subsampling if tables.subsampling in (0, 1, 2) else None
            data = _save(_flatten(img), "JPEG", qtables=tables.qtables, subsampling=sampling, optimize=True,
                         icc_profile=icc)
        else:
            data = _save(_flatten(img), "JPEG", quality=95, subsampling=0, optimize=True, icc_profile=icc)
        return Encoded(data, ".jpg")
    if fmt == "WEBP":
        return Encoded(_save(img, "WEBP", lossless=True, icc_profile=icc), ".webp")
    if fmt == "BMP":
        return encode_image(img, OutFormat.BMP, 0, None)
    if fmt == "TIFF":
        return encode_image(img, OutFormat.TIFF, 0, icc)
    if fmt == "AVIF":
        return Encoded(_save(img, "AVIF", quality=100, icc_profile=icc), ".avif")
    if fmt == "JXL":
        return Encoded(_save(img, "JXL", lossless=True), ".jxl")
    return encode_image(img, OutFormat.PNG, 0, icc)


def _pdf(img: Image.Image, src: Decoded | None, original: Original | None) -> Encoded:
    from mangareader.export.pdf import images_to_pdf

    if original is not None and original.ext in (".jpg", ".jpeg", ".png") and src and src.format in ("JPEG", "PNG"):
        picture = Encoded(original.data, original.ext)
    else:
        picture = _keep_original_format(img, src)
        if picture.ext not in (".jpg", ".png"):
            picture = encode_image(img, OutFormat.PNG, 0, src.icc if src else None)
    return Encoded(images_to_pdf([(picture, img.size)]), ".pdf")


def encode_page(page: PageImage, opts: EncodeOptions) -> Encoded:
    unchanged = opts.resize.mode == "original"
    if opts.fmt is OutFormat.ORIGINAL and unchanged and page.original is not None:
        return Encoded(page.original.data, page.original.ext.lower())
    img = apply_resize(page.decoded.image, opts.resize)
    if opts.fmt is OutFormat.ORIGINAL:
        return _keep_original_format(img, page.decoded)
    if opts.fmt is OutFormat.PDF:
        return _pdf(img, page.decoded, page.original if unchanged else None)
    return encode_image(img, opts.fmt, opts.quality, page.decoded.icc)


def encode_fragment(img: Image.Image, sources: Sequence[PageImage], opts: EncodeOptions) -> Encoded:
    formats = {s.decoded.format for s in sources}
    src = sources[0].decoded if len(formats) == 1 else None
    img = apply_resize(img, opts.resize)
    if opts.fmt is OutFormat.ORIGINAL:
        return _keep_original_format(img, src)
    if opts.fmt is OutFormat.PDF:
        return _pdf(img, src, None)
    icc = sources[0].decoded.icc if sources else None
    return encode_image(img, opts.fmt, opts.quality, icc)
