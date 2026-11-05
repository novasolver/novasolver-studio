"""How often does Studio take a part it has never seen from import to a solved result? Every STEP or STL file in a folder
goes through Studio's own commands, each in its own process with a time limit: import, automatic supports and load
(one end of the longest axis fixed, a force on the other), mesh, solve, force balance. A part that fails is a record, not a crash.

    python validation/corpus.py FOLDER results.jsonl [--limit-s 600] [--hours 6]"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORCE_N = 1000.0
AXES = "xyz"


def choose(faces: list[dict]) -> tuple[list[str], list[str], int]:
    """Faces at the two ends of the longest axis, by face centre; flat faces first when an end has any."""
    pts = [f["centroid_mm"] for f in faces]
    span = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
    ax = span.index(max(span))
    lo, hi = min(p[ax] for p in pts), max(p[ax] for p in pts)
    tol = 0.02 * max(span)

    def end(v):
        near = [f for f in faces if abs(f["centroid_mm"][ax] - v) <= tol]
        flat = [f for f in near if f.get("type") == "Plane"]
        return [f["key"] for f in (flat or near)]
    return end(lo), end(hi), ax


def stage(out: dict, name: str) -> None:
    out["stage"] = name
    print("STAGE " + name, flush=True)                              # the parent reads the last one when the time limit hits


def one(path: str, out: dict) -> dict:
    os.environ["NOVASTUDIO_WORKSPACE"] = tempfile.mkdtemp(prefix="nsc_ws_")
    sys.path.insert(0, str(ROOT / "backend"))
    from novastudio import commands as C, jobs
    stage(out, "import")
    t0 = time.time()
    c = C.import_geometry("structural", Path(path).name, None, path, "en", units="mm")["case"]
    faces = [C.face_descriptor(c, f, "en") for f in c["geometry"]["faces"] if not f.get("interface")]
    out.update(faces=len(faces), bodies=len(c["geometry"].get("bodies") or []) or None, import_s=round(time.time() - t0, 1))
    stage(out, "setup")
    fixed, loaded, ax = choose(faces)
    assert fixed and loaded and not set(fixed) & set(loaded), "no two separate ends"
    ch: dict = {f"boundaries.{k}.role": "fixed" for k in fixed}
    for k in loaded:
        ch.update({f"boundaries.{k}.role": "load", f"boundaries.{k}.force": f"{FORCE_N / len(loaded)} N",
                   f"boundaries.{k}.direction": "+" + AXES[(ax + 1) % 3]})
    ch.update({"mesh.size": "coarse", "run.mode": "preview"})
    c = C.update_case(c["case_id"], c["revision"], ch, "en", source="ai")["case"]
    bad = [i for i in C.validate_case(c["case_id"], "en").get("items", []) if i.get("level") == "error"]
    if bad:
        out["validate"] = [str(i.get("message"))[:200] for i in bad][:3]
    stage(out, "solve")
    t1 = time.time()
    job = C.run_simulation(c["case_id"], "preview", 1.0, "en", source="ai")["job"]["job_id"]
    j = jobs.wait(job, 10_000)
    out["solve_s"] = round(time.time() - t1, 1)
    if j["state"] != "done":
        out["message"] = str(C.job_status(job, "en").get("message"))[:300]
        raise RuntimeError(f"solver {j['state']}")
    r = C.get_results(c["case_id"], None, "en")
    cards = {x["key"]: x["value"] for x in r["cards"]}
    out.update(stage="done", nodes=int(cards.get("nodes") or 0), elements=int(cards.get("elements") or 0),
               max_vm_mpa=cards.get("max_vm"), max_disp_mm=cards.get("max_disp"), reaction_n=cards.get("reaction"),
               converged=bool(r["gates"].get("converged")))
    if out["reaction_n"] is not None:
        out["balance_err_pct"] = round(abs(abs(float(out["reaction_n"])) - FORCE_N) / FORCE_N * 100, 3)
    return out


def kill_tree(pid: int) -> None:
    import psutil
    try:
        root = psutil.Process(pid)
        tree = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:                                    # it may end between the two calls
        return
    for q in tree:
        try:
            q.kill()
        except psutil.NoSuchProcess:
            pass


def main() -> None:
    if sys.argv[1:2] == ["--one"]:
        out = {}
        try:
            one(sys.argv[2], out)
            out["ok"] = True
        except BaseException as e:
            out.update(ok=False, error=f"{type(e).__name__}: {e}"[:400])
        print("RESULT " + json.dumps(out, ensure_ascii=False), flush=True)
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("out")
    ap.add_argument("--limit-s", type=int, default=600)
    ap.add_argument("--hours", type=float, default=6)
    a = ap.parse_args()
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(x)["file"] for x in open(a.out, encoding="utf-8") if x.strip()}
    files = sorted(p for p in Path(a.folder).rglob("*") if p.suffix.lower() in (".step", ".stp", ".stl"))
    random.Random(7).shuffle(files)                                 # so a time limit still leaves an even sample
    stop = time.time() + a.hours * 3600
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for p in files:
        rel = p.relative_to(a.folder).as_posix()
        if rel in done:
            continue
        if time.time() > stop:
            print("time limit reached", flush=True)
            break
        t0 = time.time()
        proc = subprocess.Popen([sys.executable, __file__, "--one", str(p)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", env=env)
        try:
            stdout, stderr = proc.communicate(timeout=a.limit_s)
            rows = [x for x in stdout.splitlines() if x.startswith("RESULT ")]
            rec = json.loads(rows[-1][7:]) if rows else {"ok": False, "error": f"process ended rc={proc.returncode}", "stderr": stderr[-300:]}
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)                                     # a solver left running would hold its slot and stall the next part
            stdout, _ = proc.communicate()
            stages = [x[6:].strip() for x in stdout.splitlines() if x.startswith("STAGE ")]
            rec = {"ok": False, "error": f"over the {a.limit_s} s limit", "stage": stages[-1] if stages else None}
        kill_tree(proc.pid)                                         # a finished part leaves nothing behind either
        rec.update(file=rel, size_kb=p.stat().st_size // 1024, wall_s=round(time.time() - t0, 1))
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(("ok  " if rec.get("ok") else "FAIL"), rel, rec.get("wall_s"), rec.get("error", "")[:120], flush=True)


if __name__ == "__main__":
    main()