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
