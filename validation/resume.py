"""Finish an interrupted suite run: solve only the cases missing from the result file, keeping the ones already there.
    python validation/resume.py validation/results/0.7.0.json
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
out = Path(sys.argv[1])
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))
import suite  # noqa: E402

done = {c["id"] for c in json.loads(out.read_text(encoding="utf-8"))["cases"]} if out.exists() else set()
todo = [c["id"] for c in suite.template_cases(study=True) + suite.B.CASES if c["id"] not in done]
print(f"{len(done)} done, {len(todo)} to go", flush=True)
if todo:
    sys.exit(subprocess.call([sys.executable, str(HERE / "suite.py"), "--out", str(out), "--only", *todo]))
