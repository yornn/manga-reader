import logging

from mangareader.logging_setup import setup_logging
from mangareader.settings import Settings, load_settings, save_settings


def test_settings_roundtrip(tmp_path):
    s = Settings()
    s.theme = "light"
    s.export.quality = 80
    s.add_recent("C:/a.cbz")
    save_settings(s, tmp_path / "settings.json")
    assert load_settings(tmp_path / "settings.json") == s


def test_settings_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "settings.json") == Settings()


def test_settings_corrupt_file_gives_defaults(tmp_path):
    (tmp_path / "settings.json").write_text("{oops", encoding="utf-8")
    assert load_settings(tmp_path / "settings.json") == Settings()
    assert (tmp_path / "settings.json.bad").exists()


def test_settings_unknown_keys_ignored_missing_defaulted(tmp_path):
    (tmp_path / "settings.json").write_text('{"theme": "light", "zzz": 1}', encoding="utf-8")
    s = load_settings(tmp_path / "settings.json")
    assert s.theme == "light" and s.cache_mb == 1024


def test_export_defaults():
    e = Settings().export
    assert (e.fmt, e.quality, e.preset, e.resize_mode, e.spread_layout) == ("original", 92, "high", "original", "separate")
    assert e.template == "{серия} – Том {том} – Гл {глава} – стр {страница}"


def test_recent_dedupe_and_limit():
    s = Settings()
    for i in range(12):
        s.add_recent(f"/f{i}")
    s.add_recent("/f5")
    assert s.recent[0] == "/f5" and len(s.recent) == 10 and s.recent.count("/f5") == 1


def test_logging_writes(tmp_path):
    log = setup_logging(tmp_path)
    logging.getLogger("mangareader").warning("проверка")
    for h in logging.getLogger("mangareader").handlers:
        h.flush()
    assert "проверка" in log.read_text(encoding="utf-8")
