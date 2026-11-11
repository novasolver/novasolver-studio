# SPDX-License-Identifier: GPL-3.0-or-later
"""Talk to the NovaSolver Studio running on this computer (127.0.0.1 only). No FreeCAD imports here, so the
same code runs under pytest.

send()           a STEP file becomes a new case in Studio (Studio starts if needed)
find_cases()     the cases made from a given file (matched by content hash, then by file name)
genesis()        the latest Genesis result of a case, or None
download()       a result file (STEP of an extruded part, or the smoothed STL in metres)
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CASE_ID = re.compile(r"c_\d{8}_\d{6}_[0-9a-f]{4}")
STUDIO_PAGE = "https://novasolver.jp/studio/"


class StudioNotRunning(RuntimeError):
    pass


def data_dir():
    """Where Studio writes running.json while it runs (same rule as Studio's osdirs.py)."""
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "NovaSolverStudio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NovaSolverStudio"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "NovaSolverStudio"


def running_port():
    try:
        port = int(json.loads((data_dir() / "running.json").read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not 1024 <= port <= 65535:
        return None
    try:                                    # a Studio that crashed leaves running.json behind: is anyone there?
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return None
    return port


def studio_program():
    if os.environ.get("LOCALAPPDATA"):
        exe = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "NovaSolverStudio" / "NovaSolverStudio.exe"
        if exe.is_file():
            return [str(exe)]
    cmd = shutil.which("NovaSolverStudio.exe") or shutil.which("novasolver-studio")
    return [cmd] if cmd else None


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _quiet(args):
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _request(port, path, data=None, method="GET", timeout=60):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/octet-stream"} if data is not None else {})
    return urllib.request.urlopen(req, timeout=timeout)


def _json(port, path, **kw):
    with _request(port, path, **kw) as r:
        return json.loads(r.read().decode("utf-8"))


def open_in_program(program, path, physics, lang):
    """Studio 0.7.1+ imports the file and opens one window on it, starting itself if needed; FreeCAD does not
    wait for it. False when the installed Studio is older and rejects --import (argparse exits with 2 at once)."""
    p = _quiet([*program, "--import", str(path), "--physics", physics, "--units", "mm", "--lang", lang])
    try:
        code = p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return True
    if code == 2:
        return False
    if code != 0:                       # e.g. "already starting": say so instead of guessing
        raise RuntimeError(f"NovaSolver Studio exited with code {code}; try again in a moment")
    return True


def post_import(port, path, physics, lang):
    q = urllib.parse.urlencode({"physics": physics, "filename": Path(path).name, "units": "mm", "lang": lang})
    cid = _json(port, f"/api/import?{q}", data=Path(path).read_bytes(), method="POST", timeout=600)["case"]["case_id"]
    if not CASE_ID.fullmatch(cid):
        raise ValueError("unexpected case id")
    return cid


def send(path, physics="structural", lang="ja"):
    """Hand a STEP file to Studio. Returns the new case id when it is known here (Studio was running, or an older
    Studio without --import), None when Studio took the file through --import and opens it itself; the case is
    then found again by find_cases() from the file's hash."""
    port, program = running_port(), studio_program()
    if port is None and program and open_in_program(program, path, physics, lang):
        return None
    if port is None:
        if program is None:
            webbrowser.open(STUDIO_PAGE)
            raise RuntimeError("NovaSolver Studio is not installed")
        _quiet(program)
        t0 = time.monotonic()
        while (port := running_port()) is None:
            if time.monotonic() - t0 > 180:
                raise TimeoutError("NovaSolver Studio did not start within 3 minutes")
            time.sleep(1)
    cid = post_import(port, path, physics, lang)
    if program:
        _quiet([*program, "--case", cid])
    else:
        webbrowser.open(f"http://127.0.0.1:{port}/?case={cid}")
    return cid


def need_port():
    port = running_port()
    if port is None:
        raise StudioNotRunning("NovaSolver Studio is not running")
    return port


def list_cases(port):
    return _json(port, "/api/cases")["cases"]


def find_cases(port, digest=None, filename=None, case_id=None):
    """Cases made from this file, newest first: the case id stored on the document and the cases with the same
    content hash (Studio 0.7.7+ lists it). Only when neither is found, the cases with the same file name: an edited
    part sent again under its old name must not pick up the Genesis result of the earlier geometry."""
    cases = list_cases(port)
    out = [c for c in cases if case_id and c["case_id"] == case_id]
    out += [c for c in cases if digest and c.get("source_sha256") == digest and c not in out]
    if not out:
        out = [c for c in cases if filename and c.get("source_file") == filename]
    return out


def genesis(port, case_id, lang="en"):
    """The latest Genesis result of a case, or None when it has none."""
    if not CASE_ID.fullmatch(case_id):
        raise ValueError("unexpected case id")
    try:
        return _json(port, f"/api/cases/{case_id}/genesis?lang={lang}")
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise


def pick_file(result):
    """(kind, url): the STEP of an extruded part (flat faces, millimetres), else the smoothed STL (metres)."""
    files = result.get("files") or {}
    for kind in ("step", "stl_smooth", "stl"):
        url = files.get(kind)
        if url:
            if not url.startswith(f"/api/cases/{result['case_id']}/genesis/"):
                raise ValueError("unexpected file link")
            return kind, url
    raise ValueError("the result has no file")


def download(port, url, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _request(port, url, timeout=300) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    head = tmp.read_bytes()[:16]
    if head.lstrip().startswith(b"<"):       # an older Studio without this route answers with its app page
        tmp.unlink()
        raise RuntimeError("Studio did not send the file; update NovaSolver Studio")
    os.replace(tmp, dest)
    return dest
