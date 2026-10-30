"""A plain folder of images is a page source."""
from __future__ import annotations

import os
from pathlib import Path

from mangareader.sources.base import Original, PageSource, SourceError, is_image_name, is_junk, make_page_ref
from mangareader.sources.natsort import natural_path_key


def has_direct_images(path: Path) -> bool:
    try:
        return any(e.is_file() and is_image_name(e.name) and not is_junk(e.name) for e in os.scandir(path))
    except OSError:
        return False


class FolderSource(PageSource):
    def __init__(self, path: Path):
        super().__init__(path)
        found: list[tuple[str, int]] = []
        for dirpath, dirnames, filenames in os.walk(self.path):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and not is_junk(d)]
            rel_dir = Path(dirpath).relative_to(self.path).as_posix()
            for name in filenames:
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                if is_image_name(name) and not is_junk(rel):
                    found.append((rel, os.path.getsize(os.path.join(dirpath, name))))
        found.sort(key=lambda item: natural_path_key(item[0]))
        self.pages = [make_page_ref(i, rel, size) for i, (rel, size) in enumerate(found)]
        self.file_size = sum(size for _, size in found)

    def _file(self, i: int) -> Path:
        return self.path / self.pages[i].inner_path

    def read_original(self, i: int) -> Original:
        try:
            return Original(self._file(i).read_bytes(), self.pages[i].ext)
        except OSError as e:
            raise SourceError("Не удалось прочитать страницу: файл недоступен") from e

    def _read_head(self, i: int, n: int = 65536) -> bytes | None:
        try:
            with open(self._file(i), "rb") as f:
                return f.read(n)
        except OSError as e:
            raise SourceError("Не удалось прочитать страницу: файл недоступен") from e
