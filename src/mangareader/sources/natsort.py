"""Natural ("human") ordering: 2.jpg before 10.jpg, ch2/ before ch10/."""
from __future__ import annotations

import re

_NUMBER = re.compile(r"(\d+)")
_SEP = re.compile(r"[\\/]")


def natural_key(s: str) -> tuple:
    parts = tuple((0, int(p)) if p.isdecimal() else (1, p)
                  for p in _NUMBER.split(s.casefold()) if p)
    return parts, s


def natural_path_key(path: str) -> tuple:
    return tuple(natural_key(part) for part in _SEP.split(path))
