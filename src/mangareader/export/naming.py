"""File names from templates like "{серия} – Том {том} – Гл {глава} – стр {страница}"."""
from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_TEMPLATE = "{серия} – Том {том} – Гл {глава} – стр {страница}"
MAX_NAME = 150

_SEPARATOR = re.compile(r"(\s+[–—-]\s+)")
_FIELD = re.compile(r"\{([^{}]+)\}")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


@dataclass(frozen=True)
class NameFields:
    series: str
    volume: str | None = None
    chapter: str | None = None
    page: int | None = None          # 1-based page number as shown to the user
    page_count: int = 0
    file: str | None = None


def _pad(number: str | None) -> str | None:
    if number is None:
        return None
    whole, dot, frac = number.partition(".")
    whole = whole.zfill(2) if whole.isdigit() else whole
    return f"{whole}.{frac}" if dot else whole


def render_name(template: str, fields: NameFields) -> str:
    width = max(3, len(str(fields.page_count)))
    values = {"серия": fields.series, "том": _pad(fields.volume), "глава": _pad(fields.chapter),
              "страница": str(fields.page).zfill(width) if fields.page is not None else None,
              "файл": fields.file}
    parts = _SEPARATOR.split(template)
    segments, separators = parts[0::2], parts[1::2]
    kept: list[tuple[str, str]] = []
    for i, segment in enumerate(segments):
        missing = False

        def fill(m: re.Match) -> str:
            nonlocal missing
            key = m.group(1)
            if key not in values:
                return m.group(0)
            if not values[key]:
                missing = True
                return ""
            return values[key]

        text = _FIELD.sub(fill, segment)
        if not missing:
            kept.append((separators[i - 1] if i else "", text))
    name = "".join((sep if n else "") + text for n, (sep, text) in enumerate(kept))
    return sanitize_filename(name)


def sanitize_filename(name: str) -> str:
    clean = _FORBIDDEN.sub("_", name).rstrip(" .")
    if clean.split(".")[0].upper() in _RESERVED:
        clean = "_" + clean
    clean = clean[:MAX_NAME].rstrip(" .")
    return clean or "page"
