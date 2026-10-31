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
