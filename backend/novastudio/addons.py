"""Blender add-on and FreeCAD macro: find the programs on this computer and install the add-on / macro shipped with
Studio in one step (the person clicks Install in the help dialog). Nothing is downloaded; the files come from the
Studio installation itself (integrations/)."""
from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from .config import RESOURCES
from .store import StudioError

BLENDER_MIN = (4, 2)                  # extensions (blender_manifest.toml) and `--command extension` start at 4.2
ADDON_ID = "novasolver_studio"
MACRO = "NovaSolverStudio.FCMacro"
WORKBENCH = "NovaSolverStudio"        # integrations/freecad/NovaSolverStudio -> FreeCAD's user Mod folder
_VERSION = re.compile(r"(\d+)\.(\d+)")


def source_dir() -> Path:
    return RESOURCES / "integrations"


def addon_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (source_dir() / "blender" / ADDON_ID / "blender_manifest.toml")
                  .read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def _roaming() -> Path:
    """The roaming AppData folder as Windows reports it. Blender and FreeCAD ask Windows, not the APPDATA variable."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 26, None, 0, buf) == 0 and buf.value:     # CSIDL_APPDATA
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


# ---------------------------------------------------------------- Blender

def _blender_candidates() -> list[Path]:
    found: list[Path] = []
    if sys.platform == "win32":
        for root in {os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")} - {""}:
            found += sorted(Path(root, "Blender Foundation").glob("Blender*/blender.exe"), reverse=True)
            found.append(Path(root, "Steam", "steamapps", "common", "Blender", "blender.exe"))
        if os.environ.get("LOCALAPPDATA"):                                   # per-user installs (zip, winget)
            found += sorted(Path(os.environ["LOCALAPPDATA"], "Programs").glob("Blender*/blender.exe"), reverse=True)
    elif sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            found += sorted(root.glob("Blender*.app/Contents/MacOS/Blender"), reverse=True)
    else:
        found += [Path("/snap/bin/blender"), Path("/usr/bin/blender"), Path("/usr/local/bin/blender")]
    which = shutil.which("blender")
    if which:
        found.append(Path(which))
    out, seen = [], set()
    for p in found:
        try:
            key = p.resolve()
        except OSError:
            continue
        if p.is_file() and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _blender_version(exe: Path) -> tuple[int, int] | None:
    """major.minor from the folder name ("Blender 4.2") or, failing that, from `blender --version`."""
    for part in (exe.parent.name, exe.parents[2].name if len(exe.parents) > 2 else ""):
        m = _VERSION.search(part)
        if m and part.lower().startswith("blender"):
            return int(m.group(1)), int(m.group(2))
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60, **_no_window())
        m = re.search(r"Blender (\d+)\.(\d+)", r.stdout)
        return (int(m.group(1)), int(m.group(2))) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def _blender_config(ver: tuple[int, int]) -> Path:
    v = f"{ver[0]}.{ver[1]}"
    if sys.platform == "win32":
        return _roaming() / "Blender Foundation" / "Blender" / v
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Blender" / v
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "blender" / v


def _installed_addon(ver: tuple[int, int]) -> str | None:
    f = _blender_config(ver) / "extensions" / "user_default" / ADDON_ID / "blender_manifest.toml"
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    return m.group(1) if m else "?"


def blender_installs() -> list[dict]:
    out = []
    for exe in _blender_candidates():
        ver = _blender_version(exe)
        out.append({"path": str(exe), "version": f"{ver[0]}.{ver[1]}" if ver else None,
                    "supported": bool(ver and ver >= BLENDER_MIN),
                    "installed": _installed_addon(ver) if ver else None})
    return out


def _addon_zip(folder: Path) -> Path:
    src = source_dir() / "blender" / ADDON_ID
    z = folder / f"{ADDON_ID}-{addon_version()}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:          # manifest at the zip root, as Blender builds it
        for f in sorted(src.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                zf.write(f, f.relative_to(src).as_posix())
    return z


def install_blender(path: str) -> dict:
    """Install and enable the add-on in the Blender at `path` (one of blender_installs()). Blender runs in the
    background for a few seconds; an open Blender picks the add-on up after a restart."""
    exe = next((Path(b["path"]) for b in blender_installs() if Path(b["path"]) == Path(path)), None)
    if exe is None:
        raise StudioError("err.addon_program", 400, path=path)
    ver = _blender_version(exe)
    if not ver or ver < BLENDER_MIN:
        raise StudioError("err.blender_old", 400, version=f"{ver[0]}.{ver[1]}" if ver else "?")
    with tempfile.TemporaryDirectory(prefix="nss_addon_") as tmp:
        z = _addon_zip(Path(tmp))
        try:
            r = subprocess.run([str(exe), "--command", "extension", "install-file", "-r", "user_default", "-e", str(z)],
                               capture_output=True, text=True, timeout=180, **_no_window())
        except (OSError, subprocess.SubprocessError) as e:
            raise StudioError("err.addon_install", 500, detail=str(e)[:300])
    installed = _installed_addon(ver)
    if r.returncode != 0 or installed != addon_version():
        detail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [f"exit {r.returncode}"]
        raise StudioError("err.addon_install", 500, detail=detail[0][:300])
    return {"program": "blender", "path": str(exe), "version": installed}


# ---------------------------------------------------------------- FreeCAD

def _freecad_candidates() -> list[Path]:
    found: list[Path] = []
    if sys.platform == "win32":
        for root in {os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")} - {""}:
            found += sorted(Path(root).glob("FreeCAD*/bin/FreeCAD.exe"), reverse=True)
        if os.environ.get("LOCALAPPDATA"):
            found += sorted(Path(os.environ["LOCALAPPDATA"], "Programs").glob("FreeCAD*/bin/FreeCAD.exe"), reverse=True)
    elif sys.platform == "darwin":
        found += sorted(Path("/Applications").glob("FreeCAD*.app/Contents/MacOS/FreeCAD"), reverse=True)
    for name in ("freecad", "FreeCAD"):
        w = shutil.which(name)
        if w:
            found.append(Path(w))
    return list(dict.fromkeys(p for p in found if p.is_file()))


def _freecad_config_roots() -> list[Path]:
    if sys.platform == "win32":
        base = _roaming() / "FreeCAD"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "FreeCAD"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "FreeCAD"
    # FreeCAD 1.1 keeps its settings in a per-version folder (v1-1); older ones directly in FreeCAD/
    return sorted((p for p in base.glob("v*") if p.is_dir()), reverse=True) + [base]


def macro_dir() -> Path:
    """The user macro folder FreeCAD shows under Macro > Macros: MacroPath from user.cfg when set."""
    for root in _freecad_config_roots():
        cfg = root / "user.cfg"
        try:
            m = re.search(r'<FCText Name="MacroPath">([^<]+)</FCText>', cfg.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m and m.group(1).strip():
            return Path(html.unescape(m.group(1).strip()))        # user.cfg is XML: "&" is stored as "&amp;"
        return root / "Macro"
    roots = _freecad_config_roots()
    return roots[0] / "Macro"


def _sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def mod_dir() -> Path:
    """The user Mod folder FreeCAD loads workbenches from: next to user.cfg (FreeCAD 1.1: FreeCAD/v1-1/Mod)."""
    roots = _freecad_config_roots()
    return next((r for r in roots if (r / "user.cfg").is_file()), roots[0]) / "Mod"


def _tree_sha(folder: Path) -> str | None:
    if not folder.is_dir():
        return None
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.name != "README.md":
            h.update(p.relative_to(folder).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def freecad_status() -> dict:
    """installed: current when the macro and the workbench both match this Studio's copies; other when either is
    installed but differs (or one is missing)."""
    target, wb = macro_dir() / MACRO, mod_dir() / WORKBENCH
    have = (_sha(target), _tree_sha(wb))
    want = (_sha(source_dir() / "freecad" / MACRO), _tree_sha(source_dir() / "freecad" / WORKBENCH))
    state = None if have == (None, None) else "current" if have == want else "other"
    return {"installs": [{"path": str(p)} for p in _freecad_candidates()], "macro_dir": str(target.parent),
            "mod_dir": str(wb.parent), "installed": state}


def install_freecad() -> dict:
    """The macro (one click from Macro > Macros) and the workbench (send + import the Genesis result; FreeCAD
    loads it on the next start). The workbench is copied next to the old one and swapped in."""
    target, wb = macro_dir() / MACRO, mod_dir() / WORKBENCH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        shutil.copyfile(source_dir() / "freecad" / MACRO, tmp)
        os.replace(tmp, target)
        wb.parent.mkdir(parents=True, exist_ok=True)
        new, old = wb.with_name(WORKBENCH + ".new"), wb.with_name(WORKBENCH + ".old")
        for d in (new, old):
            shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(source_dir() / "freecad" / WORKBENCH, new,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "README.md"))
        if wb.exists():
            os.replace(wb, old)
        os.replace(new, wb)
        shutil.rmtree(old, ignore_errors=True)
    except OSError as e:
        raise StudioError("err.addon_install", 500, detail=str(e)[:300])
    return {"program": "freecad", "path": str(target), "workbench": str(wb)}


def status() -> dict:
    return {"addon_version": addon_version(), "blender": blender_installs(), "freecad": freecad_status()}
