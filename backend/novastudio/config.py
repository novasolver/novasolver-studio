"""Workspace location and solver discovery. Nothing here runs a solver."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))          # running from the packaged app (PyInstaller)
STUDIO_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
RESOURCES = Path(getattr(sys, "_MEIPASS", STUDIO_ROOT)) if FROZEN else STUDIO_ROOT


def default_workspace() -> Path:
    if FROZEN:                                          # the app folder may be read-only; keep cases in Documents
        return Path.home() / "Documents" / "NovaSolverStudio" / "workspace"
    return STUDIO_ROOT / "workspace"


def worker_argv(module: str, *args: str) -> list[str]:
    """Command line for a background worker (job runner, mesher). The packaged app re-launches itself."""
    if FROZEN:
        return [sys.executable, module.replace("novastudio.", "").replace("_", "-"), *args]
    return [sys.executable, "-m", module, *args]


def workspace() -> Path:
    p = Path(os.environ.get("NOVASTUDIO_WORKSPACE", default_workspace())).resolve()
    (p / "cases").mkdir(parents=True, exist_ok=True)
    return p


def python_exe() -> str:
    return sys.executable


def find_calculix() -> str | None:
    """CalculiX 'ccx' from env NOVASTUDIO_CCX, PATH, or the bundled solver pack folder."""
    cand = [os.environ.get("NOVASTUDIO_CCX"), shutil.which("ccx"), shutil.which("ccx_static")]
    for c in cand:
        if c and Path(c).is_file():
            return c
    pack = STUDIO_ROOT / "solvers" / "calculix"
    if pack.is_dir():
        for name in ("ccx_static.exe", "ccx.exe", "ccx_i4.exe", "ccx_dynamic.exe"):   # static build first: no DLL deps
            hits = sorted(pack.rglob(name))
            if hits:
                return str(hits[0])
    return None


def find_openfoam() -> dict | None:
    """OpenFOAM (ESI MinGW build) root from env NOVASTUDIO_OPENFOAM or the solver pack folder.

    Returns {"root", "bin"} when blockMesh.exe is present.
    """
    roots = [os.environ.get("NOVASTUDIO_OPENFOAM"), str(STUDIO_ROOT / "solvers" / "openfoam"),
             # default install location: an ASCII-only per-user path (MinGW tools are fragile with non-ASCII paths)
             str(Path(os.environ.get("LOCALAPPDATA", "")) / "NovaSolverStudio" / "solvers" / "openfoam")]
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


def msmpi_dir(foam: dict | None) -> Path | None:
    """msmpi.dll next to the OpenFOAM install, or bundled with the app."""
    cands = ([Path(foam["root"]).parent / "msmpi"] if foam else []) + [STUDIO_ROOT / "solvers" / "msmpi"]
    return next((d for d in cands if (d / "msmpi.dll").is_file()), None)


def openfoam_env(foam: dict) -> dict:
    """Environment equivalent to setEnvVariables-<ver>.bat of the ESI MinGW package."""
    env = dict(os.environ)
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
        "openfoam": {"available": bool(foam) and msmpi_dir(foam) is not None,
                     "path": foam["bin"] if foam else None, "kind": "cfd",
                     "version": foam["version"] if foam else None},
    }
