"""Detached solver jobs. State lives in <case>/run/<job_id>/job.json, so any client (GUI or AI) can watch or stop
a job, and a server restart does not lose it. Liveness = PID plus process start time (guards against PID reuse)."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import psutil

from .config import STUDIO_ROOT, python_exe, workspace
from .store import StudioError, _write_json, case_dir

BACKEND = STUDIO_ROOT / "backend"
TERMINAL = ("done", "failed", "stopped")


def _job_dir(job_id: str) -> Path:
    if not job_id.startswith("r_") or "/" in job_id or "\\" in job_id or ".." in job_id:
        raise StudioError("err.job", 404, job_id=job_id)
    hits = list((workspace() / "cases").glob(f"c_*/run/{job_id}/job.json"))
    if not hits:
        raise StudioError("err.job", 404, job_id=job_id)
    return hits[0].parent


def read(job_dir: Path) -> dict:
    for attempt in range(40):                      # tolerate a concurrent atomic replace on Windows
        try:
            return json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
    return json.loads((job_dir / "job.json").read_text(encoding="utf-8"))


def update(job_dir: Path, **kw) -> dict:
    j = read(job_dir)
    j.update(kw)
    j["updated_at"] = time.time()
    _write_json(job_dir / "job.json", j)
    return j


def start(case: dict, mode: str, engine: str, study: str | None = None) -> dict:
    job_id = "r_" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    jd = case_dir(case["case_id"]) / "run" / job_id
    jd.mkdir(parents=True)
    _write_json(jd / "request.json", {"case": case, "mode": mode, "engine": engine, "study": study})
    job = {"job_id": job_id, "case_id": case["case_id"], "revision": case["revision"], "mode": mode, "engine": engine,
           "study": study, "state": "queued", "progress": 0.0, "message_key": "job.queued", "message_args": {},
           "created_at": time.time(), "updated_at": time.time(), "pid": None, "pid_ctime": None}
    _write_json(jd / "job.json", job)
    # one BLAS thread: OpenBLAS reserves large per-thread buffers, which fails on PCs with little free memory
    env = dict(os.environ, PYTHONPATH=str(BACKEND), OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    log = open(jd / "worker.log", "w", encoding="utf-8")
    from .config import worker_argv
    p = subprocess.Popen(worker_argv("novastudio.run_worker", str(jd)), cwd=str(BACKEND if BACKEND.is_dir() else STUDIO_ROOT), env=env,
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                         close_fds=True, start_new_session=(os.name != "nt"))
    log.close()
    try:
        ctime = psutil.Process(p.pid).create_time()
    except psutil.Error:
        ctime = None
    return update(jd, pid=p.pid, pid_ctime=ctime)


def _alive(j: dict) -> bool:
    if not j.get("pid"):
        return False
    try:
        pr = psutil.Process(j["pid"])
        return j.get("pid_ctime") is None or abs(pr.create_time() - j["pid_ctime"]) < 1.0
    except psutil.Error:
        return False


def status(job_id: str) -> dict:
    jd = _job_dir(job_id)
    j = read(jd)
    if j["state"] in ("queued", "running") and not _alive(j) and time.time() - j["created_at"] > 5:
        log = (jd / "worker.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:] \
            if (jd / "worker.log").is_file() else []
        j = update(jd, state="failed", message_key="err.solver", message_args={"detail": " | ".join(log) or "process ended"})
    return j


def stop(job_id: str) -> dict:
    jd = _job_dir(job_id)
    j = read(jd)
    if j["state"] in TERMINAL:
        return j
    (jd / "STOP").write_text("1")                    # graceful: solvers that iterate check this flag
    if _alive(j):
        try:
            pr = psutil.Process(j["pid"])
            procs = pr.children(recursive=True) + [pr]
            _, alive = psutil.wait_procs(procs, timeout=3)
            for q in alive:
                q.kill()
        except psutil.Error:
            pass
    return update(jd, state="stopped", message_key="job.stopped")


def list_for_case(case_id: str) -> list[dict]:
    rd = case_dir(case_id) / "run"
    if not rd.is_dir():
        return []
    out = []
    for jd in sorted(rd.glob("r_*"), reverse=True):
        if (jd / "job.json").is_file():
            out.append(status(jd.name))
    return out


def wait(job_id: str, seconds: float) -> dict:
    end = time.time() + seconds
    j = status(job_id)
    while j["state"] not in TERMINAL and time.time() < end:
        time.sleep(0.4)
        j = status(job_id)
    return j
