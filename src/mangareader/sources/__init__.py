"""Opening any supported file or folder as a PageSource."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mangareader.sources.base import PageSource, SourceError
from mangareader.sources.detect import Format, detect_format


@dataclass(frozen=True)
class SourceContext:
    extract_root: Path
    seven_zip: Path | None


def open_source(path: Path, ctx: SourceContext, password: str | None = None) -> PageSource:
    path = Path(path)
    if not path.exists():
        raise SourceError(f"Файл не найден: {path.name}")
    fmt = detect_format(path)
    if fmt is Format.FOLDER:
        from mangareader.sources.folder import FolderSource

        return FolderSource(path)
    if fmt is Format.ZIP:
        from mangareader.sources.zip import ZipSource, zip_needs_7z

        if not zip_needs_7z(path):
            return ZipSource(path)
    if fmt in (Format.RAR, Format.SEVENZIP, Format.ZIP):
        from mangareader.sources.sevenzip import SevenZipSource

        return SevenZipSource(path, ctx, password)
    raise SourceError("Формат файла не поддерживается")
