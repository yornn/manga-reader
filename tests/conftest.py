import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGAREADER_DATA", str(tmp_path / "data"))
