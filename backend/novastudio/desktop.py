"""The packaged app as an ordinary Windows program: the UI opens in its own window (Edge or Chrome in app mode: no
address bar, own taskbar button) instead of a browser tab, the console stays out of sight, the program ends when the
last window closes, and a double-clicked .nscase opens in the Studio that is already running.

Nothing here opens a network connection: the window is pointed at this computer's own server (127.0.0.1), and a
second start finds the first one through a lock file and running.json in the data folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .osdirs import data_dir


class Instance:
    """Holds a lock on data_dir()/app.lock for as long as this process serves the UI. The lock disappears with the
    process, so a crash never leaves a stale "already running" behind (running.json alone could not tell)."""

    def __init__(self) -> None:
        self.path = data_dir() / "app.lock"
        self.fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True

    def publish(self, port: int) -> None:
        (data_dir() / "running.json").write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")


def running_port() -> int | None:
    """Port of the Studio that holds the lock, or None when none is running (or its port is not written yet)."""
    try:
        port = int(json.loads((data_dir() / "running.json").read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if 1024 <= port <= 65535 else None


def case_file(argv: list[str]) -> Path | None:
    """The .nscase the program was started with (double-click, "Open with", or dropped on the icon)."""
    if len(argv) == 1 and argv[0].lower().endswith(".nscase") and Path(argv[0]).is_file():
        return Path(argv[0]).resolve()
    return None


def open_case(path: Path) -> str:
    """Query string that opens the case: the archive is imported on this computer (same workspace for every
    instance), so the window only needs the new case id."""
    from . import commands
    try:
        return f"?case={commands.import_case(str(path))['case']['case_id']}"
    except Exception:                       # a damaged file: open the Start screen rather than nothing
        import logging
        logging.getLogger("novastudio").exception("could not open %s", path)
        return ""


def _browsers() -> list[Path]:
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    rel = (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe")
    found = [Path(r) / p for p in rel for r in roots if r]
    return [p for p in found if p.is_file()]


def window_profile() -> Path:
    """A separate browser profile for the Studio window: its own process (so we can tell when the window closes),
    no extensions, no sign-in, and nothing mixed into the user's normal browsing data."""
    return data_dir() / "window"


def open_window(url: str) -> subprocess.Popen | None:
    """Opens url in an app window. Returns None when no Edge/Chrome is installed or NOVASTUDIO_BROWSER is set; the
    caller then falls back to the default browser."""
    if sys.platform != "win32" or os.environ.get("NOVASTUDIO_BROWSER"):
        return None
    exe = next(iter(_browsers()), None)
    if exe is None:
        return None
    args = [str(exe), f"--app={url}", f"--user-data-dir={window_profile()}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-mode", "--disable-sync", "--disable-extensions",
            "--disable-features=Translate,msEdgeSidebarV2,msImplicitSignin", "--start-maximized"]
    try:
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                close_fds=True)
    except OSError:
        return None


def wait_closed(proc: subprocess.Popen, poll_s: float = 1.0) -> None:
    """Returns when every Studio window is closed. The browser deletes <profile>/lockfile when its last window
    closes; waiting for the started process alone is not enough because a second start hands its window to the
    first browser process and exits at once."""
    lock = window_profile() / "lockfile"
    t0 = time.monotonic()
    while not lock.exists() and proc.poll() is None and time.monotonic() - t0 < 30:
        time.sleep(0.2)
    while lock.exists() or proc.poll() is None:
        if lock.exists():
            try:
                os.remove(lock)              # only succeeds when no browser holds it open any more
                break
            except OSError:
                pass
        time.sleep(poll_s)


def hide_console() -> None:
    """Hide the console window the packaged exe gets, but only when it is ours alone (started by double-click or
    from the Start menu). Started from a terminal, the console belongs to the user and stays."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    pids = (ctypes.c_uint32 * 4)()
    if k32.GetConsoleProcessList(pids, 4) == 1:
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
