"""0.6.3 update check and in-place update (the swap itself is tested end to end with real builds, see the release
checklist; these cover the parts that run inside the app)."""
import base64
import hashlib
import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from novastudio import updates
from novastudio.store import StudioError

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
GH = "https://github.com/novasolver/novasolver-studio/releases/download/v9.9.9/NovaSolverStudio-9.9.9-win64.zip"


@pytest.fixture(autouse=True)
def private_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.delenv("NOVASTUDIO_UPDATE_URL", raising=False)
    monkeypatch.delenv("NOVASTUDIO_UPDATE_PUBKEY", raising=False)
    updates._job.clear()
    updates._job.update(state="idle")


def payload(version="9.9.9", urls=(GH,), sha="0" * 64):
    return {"version": version, "notes": {"en": "n"}, "windows_zip": {"urls": list(urls), "sha256": sha, "size": 1}}


def signed(p, key=KEY):
    return {"payload": p, "signature": base64.b64encode(key.sign(updates.canonical(p))).decode()}


def serve(monkeypatch, doc):
    """A test notice: signed with the test key, accepted only with the test URL override."""
    monkeypatch.setenv("NOVASTUDIO_UPDATE_URL", "http://127.0.0.1:1/latest.json")
    monkeypatch.setenv("NOVASTUDIO_UPDATE_PUBKEY", PUB)
    calls = []
    monkeypatch.setattr(updates, "_get", lambda url, *a, **k: calls.append(url) or json.dumps(doc).encode())
    return calls


def test_version_and_payload_validation():
    assert updates._version("0.10.0") > updates._version("0.9.9") > updates._version("0.6.3")
    assert updates._valid_latest(payload())
    # the version becomes part of folder names and the swap script: x.y.z only
    for bad in ("1.0.0/../victim", "9.9.9'; Start-Process calc; '", "1.0 'beta'", "1.0", "0.6.3-rc1"):
        assert not updates._valid_latest(payload(version=bad)), bad
    assert not updates._valid_latest(payload(urls=("https://evil.example/a.zip",)))   # release hosts only
    assert not updates._valid_latest(payload(urls=("http://127.0.0.1:8796/a.zip",)))  # not without the test override
    assert not updates._valid_latest(payload(sha="xyz"))


def test_signature_is_required(monkeypatch):
    calls = serve(monkeypatch, signed(payload()))
    assert updates.check()["available"]
    other = Ed25519PrivateKey.generate()
    for doc in (payload(), signed(payload(), other), {**signed(payload()), "payload": payload(version="9.9.8")}):
        updates.save_state(latest=None, checked_at=0)
        serve(monkeypatch, doc)
        with pytest.raises(StudioError) as e:
            updates.check(force=True)
        assert e.value.key == "err.update_offline"
    # the test key counts only with the test URL; the real notice must match the built-in key
    monkeypatch.delenv("NOVASTUDIO_UPDATE_URL")
    assert updates._verify(signed(payload())) is None


def test_check_caches_backs_off_offline_and_passive_respects_the_setting(monkeypatch):
    calls = serve(monkeypatch, signed(payload()))
    a = updates.check()
    assert a["available"] and a["latest"] == "9.9.9" and len(calls) == 1
    updates.check()
    assert len(calls) == 1                             # cached for a day
    def fail(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(updates, "_get", fail)
    assert updates.check(force=True)["available"]      # offline with a cache: the cached notice
    calls2 = serve(monkeypatch, signed(payload()))
    updates.check()
    assert not calls2                                  # and no retry on every call for an hour
    updates.save_state(auto_check=False)
    assert not updates.check(passive=True)["available"] and not calls2


def zip_with(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    return buf.getvalue()


def test_unpack_long_paths_twice_and_refuse_foreign_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_staging_parent", lambda: tmp_path)
    deep = "NovaSolverStudio/_internal/" + "/".join(["very_long_directory_name_x"] * 10) + "/file.txt"
    assert len(str(tmp_path / deep)) > 260
    for _ in range(2):                                 # a second attempt replaces the first one's long tree
        app = updates._unpack(zip_with(["NovaSolverStudio/NovaSolverStudio.exe", deep]), "9.9.9")
    assert (app / "NovaSolverStudio.exe").is_file()
    for bad in ("Other/x.txt", "NovaSolverStudio/../evil.txt", "/abs.txt"):
        with pytest.raises(ValueError):
            updates._unpack(zip_with(["NovaSolverStudio/NovaSolverStudio.exe", bad]), "9.9.9")
    with pytest.raises(ValueError):
        updates._unpack(zip_with(["NovaSolverStudio/readme.txt"]), "9.9.9")
    victim = tmp_path / "victim" / "keep.txt"
    victim.parent.mkdir()
    victim.write_text("keep")
    with pytest.raises(ValueError):                    # a version that walks out of the staging folder
        updates._unpack(zip_with(["NovaSolverStudio/NovaSolverStudio.exe"]), "1.0.0/../victim")
    assert victim.read_text() == "keep"


def test_download_refuses_a_wrong_checksum(tmp_path, monkeypatch):
    data = zip_with(["NovaSolverStudio/NovaSolverStudio.exe"])
    monkeypatch.setattr(updates, "_get", lambda url, progress=None, **k: data)
    monkeypatch.setattr(updates, "_staging_parent", lambda: tmp_path)
    updates._download(payload(sha="0" * 64), "en")
    assert updates.status()["state"] == "error" and updates.status()["error"] == "sha256"
    updates._download(payload(sha=hashlib.sha256(data).hexdigest()), "en")
    assert updates.status()["state"] == "ready"


def test_preflight_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "python")
    with pytest.raises(StudioError) as e:
        updates.start_download()
    assert e.value.key == "err.update_not_portable"
    monkeypatch.setattr(updates, "install_kind", lambda: "portable")
    for name, key in (("NovaSolverStudio.old-0.6.2", "err.update_folder_name"), ("Studio copy", "err.update_folder_name")):
        monkeypatch.setattr(updates, "STUDIO_ROOT", tmp_path / name)
        with pytest.raises(StudioError) as e:
            updates.start_download()
        assert e.value.key == key


def test_apply_needs_a_download_and_runs_once(monkeypatch):
    with pytest.raises(StudioError) as e:
        updates.apply()
    assert e.value.key == "err.update_not_ready"
    updates._job.update(state="applying", version="9.9.9")
    with pytest.raises(StudioError):                   # a second click while the first swap starts
        updates.apply()


def test_swap_script_quotes_every_value():
    text = updates.SWAP.format(log="a''b", result="r", pid=1, app="c:\\x''y", staged="s", backup="b",
                               name="NovaSolverStudio", old="0.6.3", new="0.6.4")
    assert "'a''b'" in text and "to = '0.6.4'" in text
