"""Common interface for everything that opens as an ordered set of pages."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from mangareader.imaging import IMAGE_EXTS, Decoded, ImageDecodeError, decode, read_size

_JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
_SEP = re.compile(r"[\\/]")


@dataclass(frozen=True)
class PageRef:
    index: int
    inner_path: str
    folder: str
    ext: str
    size: int


@dataclass(frozen=True)
class Original:
    data: bytes
    ext: str


class SourceError(Exception):
    """Failure with a ready-to-show Russian message."""


class PasswordRequired(SourceError):
    def __init__(self, wrong: bool):
        super().__init__("Неверный пароль" if wrong else "Архив защищён паролем")
        self.wrong = wrong


def is_junk(inner_path: str) -> bool:
    parts = [p for p in _SEP.split(inner_path) if p]
    if not parts:
        return False
    name = parts[-1]
    return "__MACOSX" in parts or name.startswith("._") or name.lower() in _JUNK_NAMES


def is_image_name(name: str) -> bool:
    return PurePosixPath(name.replace("\\", "/")).suffix.lower() in IMAGE_EXTS


def make_page_ref(index: int, inner_path: str, size: int) -> PageRef:
    p = PurePosixPath(inner_path)
    folder = str(p.parent) if str(p.parent) != "." else ""
    return PageRef(index, inner_path, folder, p.suffix.lower(), size)


class PageSource(ABC):
    kind: str = "images"
    is_reflowable: bool = False

    def __init__(self, path: Path):
        self.path = Path(path)
        self.pages: list[PageRef] = []
        self.file_size = 0

    @abstractmethod
    def read_original(self, i: int) -> Original | None: ...

    def load_image(self, i: int, draft: tuple[int, int] | None = None) -> Decoded:
        original = self.read_original(i)
        if original is None:
            raise SourceError("Не удалось прочитать страницу")
        try:
            return decode(original.data, draft)
        except ImageDecodeError as e:
            raise SourceError("Не удалось прочитать страницу: файл повреждён") from e

    def _read_head(self, i: int, n: int = 65536) -> bytes | None:
        original = self.read_original(i)
        return original.data[:n] if original else None

    def page_size(self, i: int) -> tuple[int, int] | None:
        try:
            head = self._read_head(i)
            if head is None:
                return None
            size = read_size(head)
            if size is None:
                original = self.read_original(i)
                size = read_size(original.data) if original else None
            return size
        except SourceError:
            return None

    def wait_ready(self, i: int, timeout: float | None = None) -> bool:
        return True

    def relayout(self, width_px: int, height_px: int, font_size: float) -> None:
        pass

    def position_token(self, i: int) -> int:
        return i

    def page_for_token(self, token: int) -> int:
        return max(0, min(token, len(self.pages) - 1))

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
