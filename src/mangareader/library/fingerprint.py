"""A file's identity independent of its name: size plus the list of pages inside."""
from __future__ import annotations

import hashlib

from mangareader.sources.base import PageSource


def fingerprint(source: PageSource) -> str:
    text = f"{source.file_size}\n" + "\n".join(f"{p.inner_path}\t{p.size}" for p in source.pages)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]
