"""Program entry point."""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

from mangareader import __version__
from mangareader.logging_setup import setup_logging
from mangareader.paths import resolve_data_location

log = logging.getLogger("mangareader")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="MangaReader")
    parser.add_argument("path", nargs="?", help="файл или папка для открытия")
    parser.add_argument("--self-test", action="store_true", help="проверить сборку и выйти")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    data = resolve_data_location()
    log_file = setup_logging(data.logs)
    log.info("Manga Reader %s starting, data in %s", __version__, data.root)

    if args.self_test:
        from mangareader import selftest

        return selftest.run(data.logs / "selftest.log")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from mangareader.ui.dialogs import errors
    from mangareader.ui.main_window import MainWindow
    from mangareader.ui.reader.controller import make_services
    from mangareader.ui.theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Manga Reader")
    services = make_services(data)
    apply_theme(app, services.settings.theme)
    window = MainWindow(services)

    def excepthook(exc_type, exc, tb) -> None:
        log.error("unhandled error", exc_info=(exc_type, exc, tb))
        QTimer.singleShot(0, lambda: errors.show_error(window, "Произошла непредвиденная ошибка", log_file))

    sys.excepthook = excepthook
    threading.excepthook = lambda a: log.error("unhandled error in thread %s", a.thread,
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    window.show()
    if args.path:
        window.open_paths([Path(args.path)])
    return app.exec()
