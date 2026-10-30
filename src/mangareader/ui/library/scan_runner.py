"""Runs the library folder scan in the background and reports progress to the window."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from mangareader.library.library_scan import ScanReport, scan_library

log = logging.getLogger("mangareader.scan")


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        self._fn()


class ScanRunner(QObject):
    started = Signal()
    series_updated = Signal()
    finished = Signal()
    _series = Signal(int)
    _done = Signal(object)

    def __init__(self, services, parent: QObject | None = None):
        super().__init__(parent)
        self.services = services
        self.failed: list[tuple[Path, str]] = []
        self._running = False
        self._again = False
        self._stop = False
        self._series.connect(lambda _: self.series_updated.emit())
        self._done.connect(self._on_done)

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            self._again = True
            return
        self._running = True
        self._stop = False
        self.started.emit()
        services = self.services

        def emit(signal, value) -> None:
            try:
                signal.emit(value)
            except RuntimeError:  # the window is already gone
                pass

        def run() -> None:
            report = None
            try:
                report = scan_library(services.catalog, services.store, services.ctx,
                                      on_series=lambda sid: emit(self._series, sid), cancelled=lambda: self._stop)
            except Exception:
                log.exception("library scan failed")
            emit(self._done, report)
        QThreadPool.globalInstance().start(_Task(run))

    def stop(self) -> None:
        self._stop = True
        self._again = False

    def _on_done(self, report: ScanReport | None) -> None:
        self._running = False
        if report is not None:
            self.failed = list(report.failed)
        self.finished.emit()
        if self._again and not self._stop:
            self._again = False
            self.start()
