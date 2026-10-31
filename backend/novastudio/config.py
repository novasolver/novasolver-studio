"""Workspace location and solver discovery. Nothing here runs a solver."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from pathlib import Path

from .osdirs import data_dir, default_workspace as user_workspace

FROZEN = bool(getattr(sys, "frozen", False))          # running from the packaged app (PyInstaller)
STUDIO_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent
INSTALLED = not FROZEN and PACKAGE_ROOT != STUDIO_ROOT / "backend" / "novastudio"
RESOURCES = Path(getattr(sys, "_MEIPASS", STUDIO_ROOT)) if FROZEN else PACKAGE_ROOT if INSTALLED else STUDIO_ROOT


def offline() -> bool:
    """No network access at all (update check, update download, solved examples). Set NOVASTUDIO_OFFLINE=1, or put an
    empty file named "offline" next to the app (an IT department can deploy it with the zip) or in the data folder."""
    if os.environ.get("NOVASTUDIO_OFFLINE", "").strip() not in ("", "0"):
        return True
    return (STUDIO_ROOT / "offline").exists() or (data_dir() / "offline").exists()


def mcp_numbers_only() -> bool:
    """The AI assistant gets numbers and text only, never a picture of the model: render_view and other images are
    withheld from MCP replies, so a cloud AI never sees the shape. Set NOVASTUDIO_MCP_NO_IMAGES=1, or put an empty
    file named "mcp_no_images" next to the app or in the data folder (an IT department can deploy it)."""
    if os.environ.get("NOVASTUDIO_MCP_NO_IMAGES", "").strip() not in ("", "0"):
        return True
    return (STUDIO_ROOT / "mcp_no_images").exists() or (data_dir() / "mcp_no_images").exists()


def default_workspace() -> Path:
    if FROZEN or INSTALLED:
        return user_workspace()
    return STUDIO_ROOT / "workspace"


def worker_argv(module: str, *args: str) -> list[str]:
    """Command line for a background worker (job runner, mesher). The packaged app re-launches itself."""
    if FROZEN:
        return [sys.executable, module.replace("novastudio.", "").replace("_", "-"), *args]
    return [sys.executable, "-m", module, *args]


def foam_workdir(jd: Path) -> Path:
    """Empty OpenFOAM case folder for the job folder jd. MinGW OpenFOAM is fragile with non-ASCII paths, so such jobs
    solve in an ASCII scratch folder (pointer in of_location.txt), named uniquely per job: convergence levels are all
    called coarse/normal/fine, and a shared folder once made a run read an older run's latest time step."""
    import hashlib
    import re
    import tempfile
    # POSIX OpenFOAM also strips spaces and quotes from -case (fileName::validate), so "safe" is ASCII without them;
    # the macOS data dir itself ("Application Support") has a space, so it cannot be the scratch root there
    safe = lambda p: str(p).isascii() and not re.search(r"[\s'\"]", str(p))
    wd = jd / "of"
    if not safe(wd):
        tag = hashlib.sha1(str(jd.resolve()).encode("utf-8")).hexdigest()[:10]
        roots = [data_dir()] if sys.platform == "win32" else [Path.home() / ".novasolver-studio", Path(tempfile.gettempdir()) / "novasolver-studio"]
        root = next((r for r in roots if safe(r)), roots[-1])
        wd = root / "runs" / f"{jd.name}_{tag}" / "of"
        (jd / "of_location.txt").write_text(str(wd), encoding="utf-8")
    if wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def workspace() -> Path:
    p = Path(os.environ.get("NOVASTUDIO_WORKSPACE", default_workspace())).resolve()
    (p / "cases").mkdir(parents=True, exist_ok=True)
    return p


def python_exe() -> str:
    return sys.executable


def find_calculix() -> str | None:
    """CalculiX 'ccx' from env NOVASTUDIO_CCX, PATH, or the bundled solver pack folder."""
    names = ("ccx", "ccx_static") if sys.platform == "win32" else ("ccx", "ccx_2.22", "ccx_2.21")
    cand = [os.environ.get("NOVASTUDIO_CCX"), *(shutil.which(n) for n in names)]
    if sys.platform == "darwin":
        cand += [str(Path(p) / n) for p in ("/opt/homebrew/bin", "/usr/local/bin") for n in names]
    for c in cand:
        if c and Path(c).is_file():
            return c
    pack = STUDIO_ROOT / "solvers" / "calculix"
    if sys.platform == "win32" and pack.is_dir():
        for name in ("ccx_static.exe", "ccx.exe", "ccx_i4.exe", "ccx_dynamic.exe"):   # static build first: no DLL deps
            hits = sorted(pack.rglob(name))
            if hits:
                return str(hits[0])
    return None


def find_openfoam() -> dict | None:
    """ESI OpenFOAM: Windows solver pack, macOS app launcher, or Linux project bashrc."""
    override = os.environ.get("NOVASTUDIO_OPENFOAM")
    if sys.platform == "darwin":
        apps = sorted(Path("/Applications").glob("OpenFOAM-v*.app"), key=_foam_version, reverse=True)
        roots = ([Path(override)] if override else []) + apps
        for root in roots:
            launcher = root / "Contents" / "Resources" / "etc" / "openfoam" if root.is_dir() else root
            if launcher.is_file():
                return {"root": str(root), "bin": str(launcher.parent), "launcher": str(launcher),
                        "version": root.stem.removeprefix("OpenFOAM-")}
        launcher = shutil.which("openfoam")
        if launcher:
            return {"root": str(Path(launcher).parent), "bin": str(Path(launcher).parent),
                    "launcher": launcher, "version": "unknown"}
        return None
    if sys.platform != "win32":
        roots = [Path(r) for r in (override, os.environ.get("WM_PROJECT_DIR")) if r]
        roots += sorted(Path("/usr/lib/openfoam").glob("openfoam*"), key=_foam_version, reverse=True)
        for root in roots:
            bashrc = root / "etc" / "bashrc" if root.is_dir() else root
            if bashrc.is_file():
                project = bashrc.parent.parent
                return {"root": str(project), "bin": str(project / "bin"), "bashrc": str(bashrc),
                        "version": project.name.removeprefix("openfoam")}
        return None
    roots = [override, str(STUDIO_ROOT / "solvers" / "openfoam"),
             # default install location: an ASCII-only per-user path (MinGW tools are fragile with non-ASCII paths)
             str(data_dir() / "solvers" / "openfoam")]
    for r in roots:
        if not r:
            continue
        root = Path(r)
        if not root.is_dir():
            continue
        for exe in root.rglob("blockMesh.exe"):
            bindir = exe.parent                                  # .../OpenFOAM-vXXXX/platforms/<TYPE>/bin
            project = bindir.parents[2]
            ptype = bindir.parent.name
            third = project.parent / f"ThirdParty-{project.name.split('-')[-1]}"
            return {"root": str(root), "bin": str(bindir), "project_dir": str(project), "type": ptype,
                    "version": project.name.split("-")[-1], "third_party": str(third)}
    return None


def _foam_version(path: Path) -> int:
    versions = re.findall(r"\d+", path.name)
    return int(versions[-1]) if versions else 0


def foam_argv(foam: dict, tool: str, args: list[str]) -> list[str]:
    """Keep environment setup and POSIX shell quoting in one place for every OpenFOAM tool."""
    if sys.platform == "win32":
        return [str(Path(foam["bin"]) / f"{tool}.exe"), *args]
    command = shlex.join([tool, *args])
    if sys.platform == "darwin":
        return [foam["launcher"], "-c", command]
    return ["bash", "-c", f"source {shlex.quote(foam['bashrc'])} && {command}"]


def msmpi_dir(foam: dict | None) -> Path | None:
    """msmpi.dll next to the OpenFOAM install, or bundled with the app."""
    cands = ([Path(foam["root"]).parent / "msmpi"] if foam else []) + [STUDIO_ROOT / "solvers" / "msmpi"]
    return next((d for d in cands if (d / "msmpi.dll").is_file()), None)


def openfoam_env(foam: dict) -> dict:
    """Environment equivalent to setEnvVariables-<ver>.bat of the ESI MinGW package."""
    env = dict(os.environ)
    if sys.platform != "win32":
        return env                                      # the launcher / bashrc sets the native environment
    project = Path(foam["project_dir"])
    env.update({"HOME": str(project.parent), "WM_PROJECT": "OpenFOAM", "WM_PROJECT_VERSION": foam["version"],
                "WM_PROJECT_DIR": str(project), "WM_THIRD_PARTY_DIR": foam["third_party"], "FOAM_SIGFPE": "1"})
    # msmpi.dll (Microsoft MPI runtime, MIT) is required even for serial runs: libPstream links against it.
    msmpi = [str(d) for d in (msmpi_dir(foam),) if d]
    extra = msmpi + [foam["bin"], str(project / "platforms" / foam["type"] / "lib"),
             str(project / "platforms" / foam["type"] / "lib" / "mpi"),
             str(Path(foam["third_party"]) / "platforms" / foam["type"] / "lib")]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def engines() -> dict:
    ccx = find_calculix()
    foam = find_openfoam()
    return {
        "builtin-fem": {"available": True, "version": "0.1", "kind": "structural"},
        "builtin-cavity": {"available": True, "version": "0.1", "kind": "cfd"},
        "calculix": {"available": bool(ccx), "path": ccx, "kind": "structural"},
        "openfoam": {"available": bool(foam) and (sys.platform != "win32" or msmpi_dir(foam) is not None),
                     "path": foam["bin"] if foam else None, "kind": "cfd",
                     "version": foam["version"] if foam else None},
    }
