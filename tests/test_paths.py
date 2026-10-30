from mangareader import paths
from mangareader.paths import find_7zz, resolve_data_location


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGAREADER_DATA", str(tmp_path / "d"))
    loc = resolve_data_location()
    assert loc.root == tmp_path / "d" and not loc.is_fallback and loc.root.is_dir()


def test_data_next_to_app(tmp_path, monkeypatch):
    monkeypatch.delenv("MANGAREADER_DATA", raising=False)
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    assert resolve_data_location().root == tmp_path / "data"


def test_fallback_when_not_writable(tmp_path, monkeypatch):
    monkeypatch.delenv("MANGAREADER_DATA", raising=False)
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "_is_writable", lambda p: False)
    monkeypatch.setattr(paths, "_user_data_dir", lambda: tmp_path / "fb")
    loc = resolve_data_location()
    assert loc.is_fallback and loc.root == tmp_path / "fb"


def test_location_subpaths(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGAREADER_DATA", str(tmp_path))
    loc = resolve_data_location()
    assert loc.db == tmp_path / "library.db"
    assert loc.settings_file == tmp_path / "settings.json"
    assert loc.thumbs == tmp_path / "cache" / "thumbs"
    assert loc.extract == tmp_path / "cache" / "extract"
    assert loc.logs == tmp_path / "logs"


def test_find_7zz_in_dev_env():
    exe = find_7zz()
    assert exe is not None and exe.exists()
