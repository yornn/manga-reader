"""Writing exported files safely: unique names, no half-written files."""
from __future__ import annotations

import errno
import os
from pathlib import Path


class ExportError(Exception):
    """Failure with a ready-to-show Russian message."""


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    path = Path(folder) / f"{stem}{ext}"
    n = 2
    while path.exists():
        path = Path(folder) / f"{stem} ({n}){ext}"
        n += 1
    return path


def write_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    part = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    except OSError as e:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        if e.errno == errno.ENOSPC:
            message = "Недостаточно места на диске"
        elif e.errno in (errno.EACCES, errno.EPERM):
            message = f"Нет прав на запись в папку {path.parent}"
        else:
            message = f"Не удалось сохранить файл: {e.strerror or e}"
        raise ExportError(message) from e
