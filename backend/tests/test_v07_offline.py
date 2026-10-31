"""0.7: offline mode stops every network request (update check and download, solved examples)."""
import urllib.request

import pytest

from novastudio import config, examples, updates


@pytest.fixture
def no_network(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("network used")))
    return calls


def test_env_switch(monkeypatch, no_network):
    monkeypatch.setenv("NOVASTUDIO_OFFLINE", "1")
    assert config.offline()
    r = updates.check(force=True)
    assert r["offline_mode"] and not r["available"]
    with pytest.raises(OSError):
        examples._fetch("examples.json")
    assert no_network == []


def test_file_in_the_data_folder(monkeypatch, tmp_path, no_network):
    monkeypatch.delenv("NOVASTUDIO_OFFLINE", raising=False)
    assert not config.offline()
    config.data_dir().mkdir(parents=True, exist_ok=True)
    (config.data_dir() / "offline").write_text("")
    assert config.offline()
    assert updates.check(force=True)["offline_mode"]
    assert no_network == []


def test_examples_fall_back_to_the_mirror(monkeypatch, tmp_path, no_network):
    """GitHub unreachable (mainland China): the novasolver.jp mirror answers, and is asked first next time."""
    import io
    import urllib.error
    monkeypatch.delenv("NOVASTUDIO_OFFLINE", raising=False)
    monkeypatch.delenv("NOVASTUDIO_EXAMPLES_URL", raising=False)
    asked = []

    class Reply(io.BytesIO):
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=None):
        asked.append(req.full_url)
        if "github.com" in req.full_url:
            raise urllib.error.URLError("blocked")
        return Reply(b'{"examples": []}')
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert examples._fetch("examples.json") == b'{"examples": []}'
    assert "github.com" in asked[0] and asked[1].startswith("https://novasolver.jp/dl/studio/examples/v")
    asked.clear()
    examples._fetch("examples.json")
    assert asked[0].startswith("https://novasolver.jp/")          # the host that answered goes first
