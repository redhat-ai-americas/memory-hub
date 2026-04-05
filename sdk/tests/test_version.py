from memoryhub import __version__


def test_version_is_set():
    assert __version__
    parts = __version__.split(".")
    assert len(parts) >= 2
