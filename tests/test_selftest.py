from mangareader import selftest


def test_selftest_passes(tmp_path, qapp):
    report = tmp_path / "selftest.log"
    assert selftest.run(report) == 0
    text = report.read_text(encoding="utf-8")
    for step in ("zip", "7z", "pdf", "avif", "jxl", "export", "window"):
        assert f"OK {step}" in text


def test_selftest_reports_failure(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(selftest, "find_7zz", lambda: None)
    report = tmp_path / "selftest.log"
    assert selftest.run(report) == 1
    assert "FAIL 7z" in report.read_text(encoding="utf-8")
