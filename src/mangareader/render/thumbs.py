"""Page thumbnails, created once and kept on disk."""
from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image

from mangareader.imaging import resize_lanczos
from mangareader.sources.base import PageSource

THUMB_HEIGHT = 240


class ThumbnailStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def path_for(self, fingerprint: str, page: int) -> Path:
        return self.folder / fingerprint[:2] / f"{fingerprint}-{page}.webp"

    def get(self, fingerprint: str, page: int) -> Image.Image | None:
        path = self.path_for(fingerprint, page)
        if not path.exists():
            return None
        try:
            with Image.open(path) as im:
                im.load()
                return im.copy()
        except (OSError, ValueError):
            return None

    def create(self, source: PageSource, page: int, fingerprint: str) -> Image.Image:
        img = source.load_image(page, draft=(THUMB_HEIGHT * 2, THUMB_HEIGHT * 3)).image
        if img.mode == "LA":
            img = img.convert("RGBA")
        thumb = resize_lanczos(img, max(1, round(img.width * THUMB_HEIGHT / img.height)), THUMB_HEIGHT)
        path = self.path_for(fingerprint, page)
        part = path.with_name(path.name + ".part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            thumb.save(buf, "WEBP", quality=80)
            part.write_bytes(buf.getvalue())
            os.replace(part, path)
        except OSError:
            part.unlink(missing_ok=True)
        return thumb
