"""Update check and in-place update of the portable Windows app.

Check: a small latest.json published with every release, first from novasolver.jp (reachable from mainland China),
then from the GitHub repository. Only the request itself is sent: no identifier, no usage data.

Update (portable zip on Windows only): download the release zip (GitHub, or the novasolver.jp mirror), check its
SHA-256, unpack it next to the running app, then a detached PowerShell script waits for the app to exit, renames the
running folder to <app>.old-<version> (one generation kept), moves the new folder into place and starts it. If any
step fails it moves the old folder back. User data lives outside the app folder (Documents, %LOCALAPPDATA%)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import __version__
from .config import FROZEN, INSTALLED, STUDIO_ROOT, data_dir
from .store import StudioError

LATEST_URLS = ("https://novasolver.jp/studio/latest.json",
               "https://raw.githubusercontent.com/novasolver/novasolver-studio/main/latest.json")
CHECK_EVERY_S = 24 * 3600
TIMEOUT = 10
APP = "NovaSolverStudio"


def _version(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


def _dir() -> Path:
    d = data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _dir() / "state.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(**kw) -> dict:
    s = {**load_state(), **kw}
    tmp = _state_path().with_suffix(f".{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _state_path())
    return s


def install_kind() -> str:
    """portable: the Windows zip (can update itself); mcpb: inside Claude Desktop's extension folder (Claude updates
    it); python: pip/uvx; dev: a source checkout."""
    if FROZEN:
        root = str(STUDIO_ROOT).lower()
        if "claude extensions" in root or "claude\\extensions" in root:
            return "mcpb"
        return "portable" if sys.platform == "win32" else "other"
    return "python" if INSTALLED else "dev"


def _urls() -> list[str]:
    env = os.environ.get("NOVASTUDIO_UPDATE_URL")
    return [env] if env else list(LATEST_URLS)


def _get(url: str, progress=None, limit: int = 1 << 31) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"NovaSolverStudio/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        total = int(r.headers.get("Content-Length") or 0)
        chunks, got = [], 0
        while True:
            b = r.read(1 << 20)
            if not b:
                return b"".join(chunks)
            got += len(b)
            if got > limit:
                raise ValueError("too large")
            chunks.append(b)
            if progress:
                progress(got, total)


def _allowed_url(u) -> bool:
    # https only; plain http just for a local test server (NOVASTUDIO_UPDATE_URL)
    return isinstance(u, str) and (u.startswith("https://") or u.startswith("http://127.0.0.1:"))


def _valid_latest(d) -> bool:
    try:
        return (isinstance(d, dict) and _version(d["version"]) > (0,) and all(
            _allowed_url(u) for u in d["windows_zip"]["urls"])
            and re.fullmatch(r"[0-9a-f]{64}", d["windows_zip"]["sha256"]) is not None)
    except (KeyError, TypeError):
        return False


def check(force: bool = False, passive: bool = False) -> dict:
    """{'current', 'latest', 'available', 'notes', 'kind', 'checked_at', 'auto'}; cached for a day unless forced.
    passive (the start-up check): no network request when the user turned the daily check off."""
    last_result()                                  # an update that just finished reports here once
    st = load_state()
    latest = st.get("latest")
    if passive and not st.get("auto_check", True):
        return {"current": __version__, "available": False, "kind": install_kind(), "auto": False,
                "last_result": st.get("last_result")}
    if force or not latest or time.time() - st.get("checked_at", 0) > CHECK_EVERY_S:
        error = None
        for url in _urls():
            try:
                d = json.loads(_get(url, limit=1 << 20))
                if _valid_latest(d):
                    latest, error = d, None
                    break
                error = "invalid"
            except (OSError, ValueError) as e:
                error = type(e).__name__
        if error and not latest:
            raise StudioError("err.update_offline", 503)
        st = save_state(latest=latest, checked_at=time.time()) if not error else st
    available = _version(latest["version"]) > _version(__version__)
    return {"current": __version__, "latest": latest["version"], "available": available,
            "notes": latest.get("notes", {}), "date": latest.get("date"), "page": latest.get("page"),
            "kind": install_kind(), "checked_at": st.get("checked_at"), "auto": st.get("auto_check", True),
            "size": latest["windows_zip"].get("size"),
            "pip": latest.get("python", {}).get("command"),
            "last_result": st.get("last_result")}


# ------------------------------------------------------------------ download and apply (portable Windows app)

_job = {"state": "idle"}           # idle | downloading | ready | applying | error
_lock = threading.Lock()


def status() -> dict:
    return dict(_job)


def _staging_parent() -> Path:
    """Unpack next to the app when its folder is writable (same volume: the swap is two renames); otherwise in the
    data folder (the swap then copies across volumes)."""
    parent = STUDIO_ROOT.parent
    try:
        probe = parent / f".nss-write-{secrets.token_hex(3)}"
        probe.write_text("1")
        probe.unlink()
        return parent
    except OSError:
        return _dir()


def start_download(lang: str = "en") -> dict:
    if install_kind() != "portable":
        raise StudioError("err.update_not_portable", 400, kind=install_kind())
    info = check()
    if not info["available"]:
        raise StudioError("err.update_none", 400, version=info["current"])
    with _lock:
        if _job["state"] in ("downloading", "applying"):
            return status()
        _job.clear()
        _job.update(state="downloading", version=info["latest"], bytes=0, total=info.get("size") or 0)
    threading.Thread(target=_download, args=(load_state()["latest"], lang), daemon=True).start()
    return status()


def _download(latest: dict, lang: str) -> None:
    z = latest["windows_zip"]
    urls = list(z["urls"])
    if lang == "zh":                       # mainland China: the novasolver.jp mirror before GitHub
        urls.sort(key=lambda u: 0 if "novasolver.jp" in u else 1)
    data, err = None, None
    for url in urls:
        try:
            data = _get(url, lambda got, total: _job.update(bytes=got, total=total or _job.get("total", 0)))
            if hashlib.sha256(data).hexdigest() == z["sha256"]:
                break
            err, data = "sha256", None
        except (OSError, ValueError) as e:
            err, data = type(e).__name__, None
    if data is None:
        _job.update(state="error", error=err or "download")
        return
    try:
        staged = _unpack(data, latest["version"])
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        _job.update(state="error", error=f"unpack: {type(e).__name__}")
        return
    _job.update(state="ready", staged=str(staged))


def _unpack(data: bytes, version: str) -> Path:
    import io
    target = _staging_parent() / f"{APP}.update-{version}"
    if target.exists():                            # left by an earlier attempt; its deepest files pass 260 characters
        shutil.rmtree("\\\\?\\" + str(target.resolve()) if os.name == "nt" else target)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():                 # the release zip holds one top folder, NovaSolverStudio/
            parts = name.replace("\\", "/").split("/")
            if parts[0] != APP or ".." in parts or name.startswith("/") or ":" in name:
                raise ValueError(f"unexpected entry {name[:80]}")
        # Windows: the app's deepest files plus a long Downloads path pass the 260-character limit; the \\?\ form
        # lifts it (extractall failed with FileNotFoundError on such a path)
        base = Path(str(target.resolve()))
        long_base = Path("\\\\?\\" + str(base)) if os.name == "nt" else base
        for info in zf.infolist():
            out = long_base.joinpath(*info.filename.replace("\\", "/").split("/"))
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    app = target / APP
    if not (app / f"{APP}.exe").is_file():
        raise ValueError("no exe in the update")
    return app


SWAP = r"""
$ErrorActionPreference = 'Stop'
$log = '{log}'
function Log($m) {{ Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) -Encoding UTF8 }}
# Remove-Item fails past 260 characters on Windows PowerShell 5.1; rd with the \\?\ prefix does not
function Del($p) {{ if (Test-Path -LiteralPath $p) {{ cmd /c ('rd /s /q "\\?\' + $p + '"') | Out-Null }} }}
function Result($ok, $msg) {{
  $j = @{{ ok = $ok; from = '{old}'; to = '{new}'; message = $msg; at = (Get-Date -Format s) }} | ConvertTo-Json
  Set-Content -LiteralPath '{result}' -Value $j -Encoding UTF8
}}
try {{
  Log 'waiting for the app (pid {pid}) to exit'
  $p = Get-Process -Id {pid} -ErrorAction SilentlyContinue
  if ($p) {{ $p.WaitForExit(60000) | Out-Null }}
  Start-Sleep -Milliseconds 800
  $app = '{app}'; $staged = '{staged}'; $old = '{backup}'
  Get-ChildItem -LiteralPath (Split-Path $app) -Directory -Filter '{name}.old-*' -ErrorAction SilentlyContinue |
    ForEach-Object {{ Del $_.FullName }}
  $moved = $false
  for ($i = 0; $i -lt 30 -and -not $moved; $i++) {{
    try {{ Rename-Item -LiteralPath $app -NewName (Split-Path $old -Leaf); $moved = $true }}
    catch {{ Log ('app folder busy, retrying: ' + $_.Exception.Message); Start-Sleep -Seconds 1 }}
  }}
  if (-not $moved) {{ throw 'the app folder stayed in use (is Studio still open, or used by an AI app?)' }}
  try {{
    Move-Item -LiteralPath $staged -Destination $app
  }} catch {{
    Log ('install failed, restoring: ' + $_.Exception.Message)
    Del $app
    Rename-Item -LiteralPath $old -NewName (Split-Path $app -Leaf)
    throw
  }}
  Del (Split-Path $staged)
  Result $true 'updated'
  Log 'updated, starting the new version'
}} catch {{
  Result $false $_.Exception.Message
  Log ('update failed: ' + $_.Exception.Message)
}}
Start-Process -FilePath (Join-Path '{app}' '{name}.exe') -WorkingDirectory '{app}'
"""


def apply() -> dict:
    """Start the swap script and tell the caller to exit the app (the API exits the process after replying)."""
    if _job.get("state") != "ready":
        raise StudioError("err.update_not_ready", 409)
    from . import jobs
    from .store import cases_dir
    busy = [j for c in cases_dir().glob("c_*") for j in jobs.list_for_case(c.name) if j["state"] in ("queued", "running")]
    if busy:
        raise StudioError("err.update_busy", 409, count=len(busy))
    app = STUDIO_ROOT
    staged = Path(_job["staged"])
    q = lambda p: str(p).replace("'", "''")                        # PowerShell single-quoted literal
    script = SWAP.format(log=q(_dir() / "update.log"), result=q(_dir() / "result.json"), pid=os.getpid(),
                         app=q(app), staged=q(staged), backup=q(app.parent / f"{APP}.old-{__version__}"),
                         name=APP, old=__version__, new=_job["version"])
    ps1 = _dir() / "swap.ps1"
    ps1.write_text("﻿" + script, encoding="utf-8")            # BOM: PowerShell 5.1 reads non-ASCII paths right
    # Not DETACHED_PROCESS: PowerShell started with no console at all exits at once without running the script.
    # A hidden console window of its own works and outlives this process.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    out = open(_dir() / "swap.out.log", "w", encoding="utf-8")
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                      "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                     creationflags=flags, close_fds=True, cwd=str(_dir()), stdin=subprocess.DEVNULL,
                     stdout=out, stderr=subprocess.STDOUT)
    out.close()
    _job.update(state="applying")
    return status()


def last_result() -> dict | None:
    """Outcome of the previous update, reported once by the new (or restored) app."""
    p = _dir() / "result.json"
    try:
        r = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    p.unlink(missing_ok=True)
    save_state(last_result=r)
    return r
