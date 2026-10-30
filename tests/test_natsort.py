from mangareader.sources.natsort import natural_key, natural_path_key


def test_natural_order():
    names = ["10.jpg", "2.jpg", "1.jpg", "B.jpg", "a.jpg"]
    assert sorted(names, key=natural_key) == ["1.jpg", "2.jpg", "10.jpg", "a.jpg", "B.jpg"]


def test_natural_path_order():
    paths = ["ch10/1.jpg", "ch2/10.jpg", "ch2/9.jpg"]
    assert sorted(paths, key=natural_path_key) == ["ch2/9.jpg", "ch2/10.jpg", "ch10/1.jpg"]


def test_backslash_paths_and_mixed_tokens():
    paths = ["a\\10", "a\\2", "a/1x", "a/1"]
    assert sorted(paths, key=natural_path_key) == ["a/1", "a/1x", "a\\2", "a\\10"]
