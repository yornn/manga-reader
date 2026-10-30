"""Memory-bounded LRU cache for decoded pages and scaled copies."""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any


def image_nbytes(img) -> int:
    if hasattr(img, "sizeInBytes"):  # QImage
        return int(img.sizeInBytes())
    return img.width * img.height * len(img.getbands())


class ImageCache:
    def __init__(self, budget_bytes: int):
        self._budget = budget_bytes
        self._items: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used_bytes(self) -> int:
        return self._used

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return item[0]

    def put(self, key: Hashable, value: Any, nbytes: int) -> None:
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._used -= old[1]
            self._items[key] = (value, nbytes)
            self._used += nbytes
            self._evict(keep=key)

    def set_budget(self, budget_bytes: int) -> None:
        with self._lock:
            self._budget = budget_bytes
            self._evict(keep=None)

    def discard_where(self, pred: Callable[[Hashable], bool]) -> None:
        with self._lock:
            for key in [k for k in self._items if pred(k)]:
                self._used -= self._items.pop(key)[1]

    def _evict(self, keep: Hashable | None) -> None:
        for key in list(self._items):
            if self._used <= self._budget:
                break
            if key == keep:
                continue
            self._used -= self._items.pop(key)[1]
