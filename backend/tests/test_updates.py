"""0.6.3 update check and in-place update (the swap itself is tested end to end with real builds, see the release
checklist; these cover the parts that run inside the app)."""
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from novastudio import updates
from novastudio.store import StudioError


@pytest.fixture(autouse=True)
def private_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    updates._job.clear()
    updates._job.update(state="idle")


def latest(version="9.9.9", urls=("https://example.invalid/a.zip",), sha="0" * 64):
    return {"version": version, "notes": {"en": "n"}, "windows_zip": {"urls": list(urls), "sha256": sha, "size": 1}}


def test_version_order_and_validation():
    assert updates._version("0.10.0") > updates._version("0.9.9") > updates._version("0.6.3")
    assert updates._valid_latest(latest())
    assert not updates._valid_latest(latest(urls=("http://evil.example/a.zip",)))   # plain http only for localhost
    assert updates._valid_latest(latest(urls=("http://127.0.0.1:8796/a.zip",)))
    assert not updates._valid_latest(latest(sha="xyz"))
    assert not updates._valid_latest({"version": "1"})


def test_check_caches_and_passive_respects_the_setting(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "_get", lambda url, *a, **k: calls.append(url) or json.dumps(latest()).encode())
    a = updates.check()
    assert a["available"] and a["latest"] == "9.9.9" and len(calls) == 1
    updates.check()                                    # within a day: cached
    assert len(calls) == 1
    updates.check(force=True)
    assert len(calls) == 2
    updates.save_state(auto_check=False)
    p = updates.check(passive=True)                    # start-up check with the daily check turned off
    assert len(calls) == 2 and not p["available"]


def test_offline_without_cache_is_a_clean_error(monkeypatch):
    def fail(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(updates, "_get", fail)
    with pytest.raises(StudioError) as e:
        updates.check()
    assert e.value.key == "err.update_offline"


def zip_with(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    return buf.getvalue()


def test_unpack_long_paths_and_refuse_foreign_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_staging_parent", lambda: tmp_path)
    deep = "NovaSolverStudio/_internal/" + "/".join(["very_long_directory_name_x"] * 10) + "/file.txt"
    assert len(str(tmp_path / deep)) > 260
    app = updates._unpack(zip_with(["NovaSolverStudio/NovaSolverStudio.exe", deep]), "9.9.9")
    assert (app / "NovaSolverStudio.exe").is_file()
    for bad in ("Other/x.txt", "NovaSolverStudio/../evil.txt", "/abs.txt"):
        with pytest.raises(ValueError):
            updates._unpack(zip_with(["NovaSolverStudio/NovaSolverStudio.exe", bad]), "9.9.9")
    with pytest.raises(ValueError):                    # no exe: not a Studio build
        updates._unpack(zip_with(["NovaSolverStudio/readme.txt"]), "9.9.9")


def test_download_refuses_a_wrong_checksum(tmp_path, monkeypatch):
    data = zip_with(["NovaSolverStudio/NovaSolverStudio.exe"])
    monkeypatch.setattr(updates, "_get", lambda url, progress=None, **k: data)
    monkeypatch.setattr(updates, "_staging_parent", lambda: tmp_path)
    updates._download(latest(sha="0" * 64), "en")
    assert updates.status()["state"] == "error" and updates.status()["error"] == "sha256"
    updates._download(latest(sha=hashlib.sha256(data).hexdigest()), "en")
    assert updates.status()["state"] == "ready"


def test_only_the_portable_app_updates_itself(monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "python")
    with pytest.raises(StudioError) as e:
        updates.start_download()
    assert e.value.key == "err.update_not_portable"


def test_apply_needs_a_download():
    with pytest.raises(StudioError) as e:
        updates.apply()
    assert e.value.key == "err.update_not_ready"
