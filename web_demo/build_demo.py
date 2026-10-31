"""Assemble the browser demo into web_demo/dist: the page, its script, and Studio's solver modules copied unchanged
from backend/novastudio (so the demo runs exactly the code the app runs).  python web_demo/build_demo.py"""
import hashlib
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "backend" / "novastudio"
DIST = HERE / "dist"

shutil.rmtree(DIST, ignore_errors=True)
(DIST / "py" / "novastudio").mkdir(parents=True)
for f in ("index.html", "demo.js"):
    shutil.copy2(HERE / f, DIST / f)
shutil.copy2(HERE / "demo.py", DIST / "py" / "demo.py")
(DIST / "py" / "novastudio" / "__init__.py").write_text('"""Solver modules of NovaSolver Studio, for the browser demo."""\n', encoding="utf-8")
for f in ("fem_tet10.py", "box_mesh.py"):
    shutil.copy2(PKG / f, DIST / "py" / "novastudio" / f)
for p in sorted(DIST.rglob("*")):
    if p.is_file():
        print(f"{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(DIST).as_posix()}")
