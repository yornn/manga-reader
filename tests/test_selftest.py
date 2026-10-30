from mangareader import selftest


def test_selftest_passes(tmp_path, qapp):
    report = tmp_path / "selftest.log"
    assert selftest.run(report) == 0
    text = report.read_text(encoding="utf-8")
    for step in ("zip", "7z", "rar", "pdf", "avif", "jxl", "export", "window"):
        assert f"OK {step}" in text


def test_selftest_reports_failure(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(selftest, "find_7zz", lambda: None)
    report = tmp_path / "selftest.log"
    assert selftest.run(report) == 1
    assert "FAIL 7z" in report.read_text(encoding="utf-8")


def test_selftest_checks_library_start(tmp_path, qapp, monkeypatch):
    from mangareader.ui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "is_library_shown", lambda self: False)
    report = tmp_path / "selftest.log"
    assert selftest.run(report) == 1
    assert "FAIL window" in report.read_text(encoding="utf-8")
