"""Mapping an on-screen selection to original pixels and stitching several pages.

Scene coordinates are the reader's layout units; each placed page knows its rectangle
in the scene and its size in original pixels.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from PIL import Image

_EPS = 1e-6


@dataclass(frozen=True)
class Placed:
    page: int
    x: float
    y: float
    w: float
    h: float
    orig_w: int
    orig_h: int


@dataclass(frozen=True)
class PageCrop:
    page: int
    box: tuple[int, int, int, int]
    scene: tuple[float, float, float, float]


def crops_for_selection(placed: Sequence[Placed], sel: tuple[float, float, float, float]) -> list[PageCrop]:
    sx, sy, sw, sh = sel
    crops = []
    for p in placed:
        x0, y0 = max(sx, p.x), max(sy, p.y)
        x1, y1 = min(sx + sw, p.x + p.w), min(sy + sh, p.y + p.h)
        if x1 - x0 <= _EPS or y1 - y0 <= _EPS:
            continue
        kx, ky = p.orig_w / p.w, p.orig_h / p.h
        left = min(max(math.floor((x0 - p.x) * kx + _EPS), 0), p.orig_w - 1)
        top = min(max(math.floor((y0 - p.y) * ky + _EPS), 0), p.orig_h - 1)
        right = min(max(math.ceil((x1 - p.x) * kx - _EPS), left + 1), p.orig_w)
        bottom = min(max(math.ceil((y1 - p.y) * ky - _EPS), top + 1), p.orig_h)
        crops.append(PageCrop(p.page, (left, top, right, bottom), (x0, y0, x1 - x0, y1 - y0)))
    return crops


def _ratio(placed: Sequence[Placed], crops: Sequence[PageCrop]) -> float:
    pages = {c.page for c in crops}
    return max(p.orig_w / p.w for p in placed if p.page in pages)


def _union(crops: Sequence[PageCrop]) -> tuple[float, float, float, float]:
    x0 = min(c.scene[0] for c in crops)
    y0 = min(c.scene[1] for c in crops)
    x1 = max(c.scene[0] + c.scene[2] for c in crops)
    y1 = max(c.scene[1] + c.scene[3] for c in crops)
    return x0, y0, x1 - x0, y1 - y0


def output_size(placed: Sequence[Placed], crops: Sequence[PageCrop]) -> tuple[int, int]:
    if not crops:
        return 0, 0
    if len(crops) == 1:
        left, top, right, bottom = crops[0].box
        return right - left, bottom - top
    r = _ratio(placed, crops)
    _, _, uw, uh = _union(crops)
    return round(uw * r), round(uh * r)


def _common_mode(images: Sequence[Image.Image]) -> str:
    modes = {im.mode for im in images}
    if modes & {"RGBA", "LA"}:
        return "RGBA"
    if "RGB" in modes:
        return "RGB"
    return "L"


def stitch(placed: Sequence[Placed], crops: Sequence[PageCrop], images: Mapping[int, Image.Image]) -> Image.Image:
    if len(crops) == 1:
        return images[crops[0].page].crop(crops[0].box)
    r = _ratio(placed, crops)
    ux, uy, _, _ = _union(crops)
    mode = _common_mode([images[c.page] for c in crops])
    white = {"L": 255, "RGB": (255, 255, 255), "RGBA": (255, 255, 255, 255)}[mode]
    canvas = Image.new(mode, output_size(placed, crops), white)
    for c in crops:
        cx, cy, cw, ch = c.scene
        x0, y0 = round((cx - ux) * r), round((cy - uy) * r)
        x1, y1 = round((cx + cw - ux) * r), round((cy + ch - uy) * r)
        piece = images[c.page].crop(c.box).convert(mode)
        if piece.size != (x1 - x0, y1 - y0) and x1 > x0 and y1 > y0:
            piece = piece.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        canvas.paste(piece, (x0, y0))
    return canvas
