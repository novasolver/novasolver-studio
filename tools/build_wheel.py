"""Build the GUI and stage all resources before building an sdist and wheel into dist-py/."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stage_resources() -> None:
    package = ROOT / "backend" / "novastudio"
    # These two ignored folders contain only generated package data.
    for name, source in (("frontend_dist", ROOT / "frontend" / "dist"), ("samples", ROOT / "samples")):
        target = (package / name).resolve()
        if target.parent != package.resolve():
            raise RuntimeError(f"unexpected staging path: {target}")
        if target.exists():
            shutil.rmtree(target)
        if name == "samples":
            target.mkdir()
            for sample in source.glob("*.step"):
                shutil.copy2(sample, target / sample.name)
        else:
            shutil.copytree(source, target)


def main() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm is required to build the frontend")
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    stage_resources()
    subprocess.run([sys.executable, "-m", "build", "--outdir", str(ROOT / "dist-py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
