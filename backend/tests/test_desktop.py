"""App-mode helpers: one Studio per user (lock + running.json), .nscase arguments, and the window command line."""
import json
import subprocess
import sys
from pathlib import Path

from novastudio import desktop

BACKEND = Path(__file__).resolve().parents[1]


def test_case_file_only_for_an_existing_nscase(tmp_path):
    f = tmp_path / "a.NSCASE"
    f.write_bytes(b"x")
    assert desktop.case_file([str(f)]) == f.resolve()
    assert desktop.case_file([str(tmp_path / "missing.nscase")]) is None
    assert desktop.case_file(["serve"]) is None
    assert desktop.case_file([str(f), "extra"]) is None


def test_second_instance_sees_the_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    first = desktop.Instance()
    assert first.acquire()
    first.publish(8790)
    assert desktop.running_port() == 8790
    # another process (not just another handle in this one) must be refused while the first holds the lock
    code = ("import sys; sys.path.insert(0, r'%s'); from novastudio import desktop; "
            "print(desktop.Instance().acquire())" % BACKEND)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**__import__("os").environ, "LOCALAPPDATA": str(tmp_path)}, timeout=120)
    assert out.stdout.strip() == "False", out.stderr
    first.fh.close()
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**__import__("os").environ, "LOCALAPPDATA": str(tmp_path)}, timeout=120)
    assert out.stdout.strip() == "True", out.stderr


def test_running_port_ignores_damaged_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = tmp_path / "NovaSolverStudio"
    d.mkdir()
    assert desktop.running_port() is None
    (d / "running.json").write_text("{bad", encoding="utf-8")
    assert desktop.running_port() is None
    (d / "running.json").write_text(json.dumps({"port": 80}), encoding="utf-8")
    assert desktop.running_port() is None


def test_window_points_at_this_computer_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    exe = tmp_path / "msedge.exe"
    exe.write_bytes(b"")
    seen = {}

    class P:
        def __init__(self, args, **kw):
            seen["args"] = args

    monkeypatch.setattr(desktop, "_browsers", lambda: [exe])
    monkeypatch.setattr(desktop.subprocess, "Popen", P)
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.delenv("NOVASTUDIO_BROWSER", raising=False)
    assert desktop.open_window("http://127.0.0.1:8765/?case=c_1") is not None
    args = seen["args"]
    assert args[1] == "--app=http://127.0.0.1:8765/?case=c_1"
    assert f"--user-data-dir={tmp_path / 'NovaSolverStudio' / 'window'}" in args
    monkeypatch.setenv("NOVASTUDIO_BROWSER", "1")
    assert desktop.open_window("http://127.0.0.1:8765/") is None


def test_running_json_removed_on_exit_only_by_its_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    inst = desktop.Instance()
    assert inst.acquire()
    inst.publish(8791)
    inst.unpublish()
    assert desktop.running_port() is None                      # Blender/FreeCAD must not find a closed Studio
    (tmp_path / "NovaSolverStudio" / "running.json").write_text(json.dumps({"port": 8792, "pid": 1}), encoding="utf-8")
    inst.unpublish()                                           # someone else's: left alone
    assert desktop.running_port() == 8792
    inst.fh.close()


def test_window_started_detects_a_browser_that_quits(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    desktop.window_profile().mkdir(parents=True)

    class Quit:
        def poll(self):
            return 1

    class Running:
        def poll(self):
            (desktop.window_profile() / "lockfile").write_text("")
            return None

    assert not desktop.window_started(Quit(), timeout_s=2)     # blocked by policy, broken install: fall back
    assert desktop.window_started(Running(), timeout_s=2)
    # a lockfile left by a crashed browser is cleared before the next window starts
    monkeypatch.setattr(desktop, "_browsers", lambda: [tmp_path / "msedge.exe"])
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: Quit())
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.delenv("NOVASTUDIO_BROWSER", raising=False)
    desktop.open_window("http://127.0.0.1:8765/")
    assert not (desktop.window_profile() / "lockfile").exists()

def test_import_cad_opens_the_new_case_with_its_material(tmp_path):
    # what `novastudio --import` does for the Blender add-on / FreeCAD macro: one process imports and opens one window
    from novastudio import store
    q = desktop.import_cad(BACKEND.parent / "samples" / "l_bracket.step", "structural", "mm", "en", "petg")
    assert q.startswith("?case=c_")
    assert store.load(q[len("?case="):])["materials"]["solid"]["preset"] == "petg"
    bad = tmp_path / "broken.step"
    bad.write_bytes(b"not a step file")
    assert desktop.import_cad(bad, "structural", "mm", "en", None) == ""      # Start screen, not a crash
