"""A page as export sees it: decoded pixels plus the original file bytes, if any."""
from __future__ import annotations

from dataclasses import dataclass

from mangareader.imaging import Decoded
from mangareader.sources.base import Original, PageSource


@dataclass
class PageImage:
    decoded: Decoded
    original: Original | None


def load_page_image(source: PageSource, i: int) -> PageImage:
    return PageImage(source.load_image(i), source.read_original(i))
