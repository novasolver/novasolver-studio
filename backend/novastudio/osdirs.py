"""Per-user locations shared by the app, workers and solver discovery."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    # Also honoured on POSIX so tests and portable installations can isolate all state.
    if os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif sys.platform == "win32":
        base = Path.home()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "NovaSolverStudio"


def default_workspace() -> Path:
    if os.environ.get("NOVASTUDIO_WORKSPACE"):
        return Path(os.environ["NOVASTUDIO_WORKSPACE"])
    # Unsigned macOS apps should not need permission to access Documents.
    base = Path.home() / "Documents" if sys.platform == "win32" else Path.home()
    return base / "NovaSolverStudio" / "workspace"
