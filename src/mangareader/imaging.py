"""Decoding page images with Pillow, keeping what export needs (format, ICC, JPEG tables)."""
from __future__ import annotations

import io
from dataclasses import dataclass

import pillow_jxl  # noqa: F401  (registers the JPEG XL plugin)
from PIL import Image, JpegImagePlugin

# Raw manga spreads can exceed Pillow's default 89 Mpx "decompression bomb" guard.
Image.MAX_IMAGE_PIXELS = 500_000_000

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".jpe", ".png", ".webp", ".avif", ".jxl",
                        ".bmp", ".gif", ".tif", ".tiff"})

_KEEP_MODES = {"L", "LA", "RGB", "RGBA"}
_FOREIGN_COLOR = {"CMYK", "YCbCr", "LAB", "HSV"}


class ImageDecodeError(Exception):
    pass


@dataclass(frozen=True)
class JpegTables:
    qtables: dict
    subsampling: int


@dataclass
class Decoded:
    image: Image.Image
    format: str | None
    icc: bytes | None
    jpeg: JpegTables | None


def _normalize(im: Image.Image, icc: bytes | None) -> tuple[Image.Image, bytes | None]:
    mode = im.mode
    if mode in _KEEP_MODES:
        return im, icc
    if mode == "1":
        return im.convert("L"), icc
    if mode.startswith("I;16") or mode == "I":
        im = im.convert("I")
        if im.getextrema()[1] > 255:
            im = im.point(lambda v: v / 256)
        return im.convert("L"), icc
    if mode == "F":
        return im.convert("L"), icc
    if mode in ("P", "PA"):
        has_alpha = mode == "PA" or "transparency" in im.info
        return im.convert("RGBA" if has_alpha else "RGB"), icc
    if mode == "La":
        return im.convert("LA"), icc
    if mode == "RGBa":
        return im.convert("RGBA"), icc
    if mode in _FOREIGN_COLOR:
        return im.convert("RGB"), None
    return im.convert("RGB"), icc


def decode(data: bytes, draft: tuple[int, int] | None = None) -> Decoded:
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        jpeg = None
        if fmt == "JPEG":
            jpeg = JpegTables(dict(im.quantization), JpegImagePlugin.get_sampling(im))
            if draft:
                im.draft("L" if im.mode == "L" else "RGB", draft)
        icc = im.info.get("icc_profile")
        im.load()
        im, icc = _normalize(im, icc)
        return Decoded(im, fmt, icc, jpeg)
    except Exception as e:  # any Pillow/plugin failure is a bad page for the user
        raise ImageDecodeError("Не удалось прочитать картинку") from e


def read_size(data: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def resize_lanczos(img: Image.Image, w: int, h: int) -> Image.Image:
    return img.resize((w, h), Image.LANCZOS, reducing_gap=3.0)
